from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Optional

from shapely.geometry import Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84
from sqlalchemy.orm import Session

from core.years import available_business_years, normalize_year, resolve_business_year
from modules.evidence_retrieval.schemas import EvidenceNode
from store.artifact_identity import build_artifact_slot_key
from store.database import SessionLocal
from store.models import AnalysisArtifact, PoiResult
from .spatial import SpatialQueryError, query_spatial_records


DATASET_TITLES = {
    "current:dataset:poi": "当前范围 POI",
    "current:dataset:h3": "当前范围 POI H3",
    "current:dataset:poi_grid": "当前范围 POI 规则栅格",
    "current:dataset:population": "当前范围人口网格",
    "current:dataset:nightlight": "当前范围夜光网格",
    "current:dataset:road_edges": "当前范围路网线段",
    "current:dataset:road_grid": "当前范围路网共享栅格",
}

ARTIFACT_SOURCE_MAP = {
    "poi_h3_grid": "current:dataset:h3",
    "poi_raster_grid": "current:dataset:poi_grid",
    "population": "current:dataset:population",
    "nightlight": "current:dataset:nightlight",
    "road_syntax": "current:dataset:road_edges",
}

DATASET_FILTER_FIELDS = {
    "current:dataset:poi": {"id", "name", "type", "typecode", "address", "category", "source", "year"},
    "current:dataset:h3": {"record_id", "cell_id", "h3_id", "poi_count", "density", "lq", "year"},
    "current:dataset:poi_grid": {"record_id", "cell_id", "poi_count", "density", "lq", "year"},
    "current:dataset:population": {"record_id", "cell_id", "value", "population", "density", "year", "view"},
    "current:dataset:nightlight": {"record_id", "cell_id", "value", "radiance", "year", "view"},
    "current:dataset:road_edges": {"record_id", "edge_id", "feature_kind", "choice_score", "integration_score", "connectivity_score", "control_score", "depth_score", "metric"},
    "current:dataset:road_grid": {"record_id", "cell_id", "feature_kind", "road_has_data", "road_length_km", "road_length_km_per_km2", "road_choice", "road_integration", "road_connectivity", "road_control", "road_depth"},
}

DATASET_SPATIAL_CAPABILITIES = {
    "current:dataset:poi": {
        "geometry_type": "Point",
        "grid_type": "none",
        "spatial_relations": ["nearest", "within_distance", "intersects"],
    },
    "current:dataset:h3": {
        "geometry_type": "Polygon",
        "grid_type": "h3",
        "spatial_relations": ["at_point", "nearest", "intersects"],
    },
    "current:dataset:poi_grid": {
        "geometry_type": "Polygon",
        "grid_type": "regular_raster",
        "spatial_relations": ["at_point", "nearest", "intersects"],
    },
    "current:dataset:population": {
        "geometry_type": "Polygon",
        "grid_type": "population_raster",
        "spatial_relations": ["at_point", "nearest", "intersects"],
    },
    "current:dataset:nightlight": {
        "geometry_type": "Polygon",
        "grid_type": "nightlight_raster",
        "spatial_relations": ["at_point", "nearest", "intersects"],
    },
    "current:dataset:road_edges": {
        "geometry_type": "LineString",
        "grid_type": "none",
        "spatial_relations": ["nearest", "within_distance", "intersects"],
    },
    "current:dataset:road_grid": {
        "geometry_type": "Polygon",
        "grid_type": "road_raster",
        "spatial_relations": ["at_point", "nearest", "intersects"],
    },
}

DATASET_SPATIAL_AGGREGATIONS = {
    "current:dataset:population": [
        {
            "op": "area_weighted_sum",
            "fields": ["population", "value"],
            "method": "record_value_times_record_overlap_ratio",
            "assumptions": ["uniform_distribution_within_cell"],
        }
    ],
    "current:dataset:nightlight": [
        {
            "op": "area_weighted_avg",
            "fields": ["radiance", "value"],
            "method": "overlap_area_weighted_mean",
            "assumptions": [],
        }
    ],
    "current:dataset:road_edges": [
        {
            "op": "intersection_length_sum",
            "fields": ["intersection_length_m"],
            "method": "sum_clipped_intersection_length",
            "assumptions": [],
            "unit": "m",
        }
    ],
}

GENERIC_AGGREGATE_OPS = {"count", "sum", "avg", "min", "max"}
SPATIAL_AGGREGATE_OPS = {"area_weighted_sum", "area_weighted_avg", "intersection_length_sum"}

POI_GEOMETRY_COORD_TYPE = "gcj02"

# Analysis artifacts created by the current frontend have always stored their
# GeoJSON coordinates in GCJ-02.  Older history rows predate the explicit
# geometry_coord_type field, so retain that producer contract when reading
# those known artifact types.  Unknown artifact types must still provide an
# explicit coordinate system rather than being guessed.
LEGACY_ARTIFACT_GEOMETRY_COORD_TYPES = {
    "poi_h3_grid": "gcj02",
    "poi_raster_grid": "gcj02",
    "population": "gcj02",
    "nightlight": "gcj02",
    "road_syntax": "gcj02",
}

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_QUERY_SNAPSHOT_FEATURES = 10_000


class ScopeDatasetQueryError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(message)


@dataclass(frozen=True)
class _SpatialSelection:
    records: List[ScopeRecord]
    matches: Dict[int, Dict[str, Any]]
    warnings: List[str]
    skipped_record_count: int


def _clone_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clone_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_json(item) for item in value]
    return value


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _path_value(payload: Any, path: str) -> Any:
    current = payload
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _first_value(payload: Dict[str, Any], paths: Iterable[str]) -> Any:
    for path in paths:
        value = _path_value(payload, path)
        if value not in (None, ""):
            return value
    return None


def _feature_record_id(feature: Dict[str, Any], fallback: str) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    value = _first_value(
        {"feature": feature, "properties": props},
        [
            "feature.id",
            "properties.id",
            "properties.record_id",
            "properties.edge_id",
            "properties.cell_id",
            "properties.h3_id",
            "properties.road_id",
            "properties.node_id",
            "properties.osm_id",
        ],
    )
    return _as_text(value) or fallback


def _time_scope(*, year: Any = None, data_version: str = "", scope_fingerprint: str = "") -> Dict[str, Any]:
    normalized_year = _as_int(year)
    if normalized_year is not None:
        return {
            "year": normalized_year,
            "label": f"{normalized_year} 年",
            "granularity": "year",
            "data_version": data_version,
            "scope_fingerprint": scope_fingerprint,
        }
    return {
        "label": "未标注年份",
        "data_version": data_version,
        "scope_fingerprint": scope_fingerprint,
    }


def _static_time_scope(*, data_version: str = "", scope_fingerprint: str = "") -> Dict[str, Any]:
    return {
        "kind": "static_snapshot",
        "label": "当前路网模型",
        "data_version": data_version,
        "scope_fingerprint": scope_fingerprint,
    }


def _year_from_artifact(artifact: Dict[str, Any]) -> Any:
    params = artifact.get("params") if isinstance(artifact.get("params"), dict) else {}
    payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
    return params.get("year") if params.get("year") not in (None, "") else payload.get("year")


def _dataset_warning_for_year(year: Any) -> List[str]:
    return [] if _as_int(year) is not None else ["该来源未提供明确年份，回答时不能做跨年比较。"]


def _geometry_from_feature(feature: Dict[str, Any], source_id: str, coord_type: str) -> BaseGeometry | None:
    raw_geometry = feature.get("geometry") if isinstance(feature, dict) else None
    if not isinstance(raw_geometry, dict):
        return None
    try:
        geometry = shape(raw_geometry)
        if geometry.is_empty:
            return None
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        if geometry.is_empty:
            return None
        normalized_coord_type = str(coord_type or "").strip().lower()
        if normalized_coord_type not in {"gcj02", "wgs84"}:
            return None
        if normalized_coord_type == "gcj02":
            geometry = transform(
                lambda x, y, z=None: _transform_xy(x, y, gcj02_to_wgs84),
                geometry,
            )
        return geometry
    except Exception:
        return None


def _transform_xy(x: Any, y: Any, converter):
    if hasattr(x, "__iter__"):
        converted = [converter(float(px), float(py)) for px, py in zip(x, y)]
        xs, ys = zip(*converted) if converted else ((), ())
        return tuple(xs), tuple(ys)
    return converter(float(x), float(y))


def _point_from_poi(poi: Dict[str, Any], coord_type: str) -> BaseGeometry | None:
    location = poi.get("location")
    if isinstance(location, str):
        parts = [item.strip() for item in location.split(",")]
        location = parts if len(parts) >= 2 else None
    if isinstance(location, (list, tuple)) and len(location) >= 2:
        lon = _as_float(location[0])
        lat = _as_float(location[1])
    else:
        lon = _as_float(poi.get("lng") if poi.get("lng") is not None else poi.get("longitude"))
        lat = _as_float(poi.get("lat") if poi.get("lat") is not None else poi.get("latitude"))
    if lon is None or lat is None:
        return None
    try:
        point = Point(lon, lat)
        if str(coord_type or "").strip().lower() == "gcj02":
            point = transform(lambda x, y, z=None: gcj02_to_wgs84(float(x), float(y)), point)
        return point
    except Exception:
        return None


@dataclass
class ScopeRecord:
    source_id: str
    record_id: str
    title: str
    content: str
    properties: Dict[str, Any]
    raw: Dict[str, Any]
    time_scope: Dict[str, Any]
    locator: str
    citation: str
    warnings: List[str] = field(default_factory=list)
    geometry: BaseGeometry | None = None

    def as_payload(self, spatial_match: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "record_id": self.record_id,
            "source_id": self.source_id,
            "title": self.title,
            "content": self.content,
            "properties": _clone_json(self.properties),
            "time_scope": _clone_json(self.time_scope),
            "locator": self.locator,
            "citation": self.citation,
            "warnings": list(self.warnings or []),
        }
        if spatial_match is not None:
            payload["spatial_match"] = _clone_json(spatial_match)
        return payload

    def evidence_node(self, spatial_match: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        evidence_data = {
            "record_id": self.record_id,
            "properties": _clone_json(self.properties),
        }
        if spatial_match is not None:
            evidence_data["spatial_match"] = _clone_json(spatial_match)
        node = EvidenceNode(
            id=f"{self.source_id}:record:{self.record_id}",
            kind="dataset_record",
            source_ids=[self.source_id],
            title=self.title,
            content=self.content,
            summary=self.content[:260],
            data=evidence_data,
            time_scope=_clone_json(self.time_scope),
            locator=self.locator,
            quality_flags=[{"code": "source_quality_note", "severity": "warning", "effect": item} for item in self.warnings],
            citation=self.citation,
        )
        return node.model_dump(mode="python")


class ScopeDatasetRepository:
    def list_poi_results(self, history_id: str) -> List[Dict[str, Any]]:
        session: Session = SessionLocal()
        try:
            rows = (
                session.query(
                    PoiResult.id,
                    PoiResult.source,
                    PoiResult.year,
                    PoiResult.summary,
                    PoiResult.created_at,
                )
                .filter_by(history_id=str(history_id or "").strip())
                .order_by(PoiResult.created_at.desc(), PoiResult.id.desc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "source": row.source,
                    "year": row.year,
                    "summary": row.summary if isinstance(row.summary, dict) else {},
                }
                for row in rows
            ]
        finally:
            session.close()

    def get_poi_data(self, poi_result_id: Any) -> List[Dict[str, Any]]:
        if poi_result_id in (None, ""):
            return []
        session: Session = SessionLocal()
        try:
            row = session.query(PoiResult.poi_data).filter(PoiResult.id == poi_result_id).first()
            poi_data = row[0] if row else []
            return poi_data if isinstance(poi_data, list) else []
        finally:
            session.close()

    def list_analysis_artifacts(self, history_id: str) -> List[Dict[str, Any]]:
        session: Session = SessionLocal()
        try:
            id_rows = (
                session.query(AnalysisArtifact.id)
                .filter_by(history_id=str(history_id or "").strip())
                .order_by(AnalysisArtifact.updated_at.desc(), AnalysisArtifact.id.desc())
                .all()
            )
            record_ids = [int(row[0] if isinstance(row, tuple) else getattr(row, "id", row)) for row in id_rows]
            rows = [session.get(AnalysisArtifact, record_id) for record_id in record_ids]
            return [
                {
                    "id": row.id,
                    "artifact_type": row.artifact_type,
                    "slot_key": row.slot_key,
                    "params": row.params if isinstance(row.params, dict) else {},
                    "payload": row.payload if isinstance(row.payload, dict) else {},
                    "summary": row.summary if isinstance(row.summary, dict) else {},
                    "data_version": row.data_version,
                    "scope_fingerprint": row.scope_fingerprint,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                }
                for row in rows
                if row is not None
            ]
        finally:
            session.close()


class SavedProjectSnapshotRepository(ScopeDatasetRepository):
    """Read-only repository for an explicitly supplied saved-project snapshot.

    The production path remains the database-backed repository.  This adapter is
    intentionally opt-in: it is useful when an immutable run already contains a
    saved spatial extraction and the database is temporarily unreachable.  It
    exposes the same normalized artifact shape as the database repository, so the
    spatial tool does not gain a second geometry or renderer contract.
    """

    _SUPPORTED_ARTIFACT_TYPES = {"population", "nightlight", "poi_raster_grid", "road_syntax"}

    def __init__(self, snapshot: Dict[str, Any]):
        if not isinstance(snapshot, dict):
            raise ValueError("saved spatial snapshot must be an object")
        history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
        history_id = _as_text(snapshot.get("history_id") or history.get("id"))
        if not history_id:
            raise ValueError("saved spatial snapshot must include history id")
        self.history_id = history_id
        self.snapshot = _clone_json(snapshot)
        self._artifacts = [
            _clone_json(value)
            for key, value in snapshot.items()
            if str(key).isdigit()
            and isinstance(value, dict)
            and _as_text(value.get("artifact_type")) in self._SUPPORTED_ARTIFACT_TYPES
        ]
        self._pois = []
        poi_payload = snapshot.get("pois_2024")
        if isinstance(poi_payload, dict) and isinstance(poi_payload.get("pois"), list):
            self._pois = [item for item in poi_payload["pois"] if isinstance(item, dict)]

    @classmethod
    def from_json_path(cls, path: Any) -> "SavedProjectSnapshotRepository":
        from pathlib import Path

        snapshot_path = Path(path)
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError("saved spatial snapshot cannot be read") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("saved spatial snapshot is not valid JSON") from exc
        return cls(payload)

    def list_poi_results(self, history_id: str) -> List[Dict[str, Any]]:
        if str(history_id or "").strip() != self.history_id or not self._pois:
            return []
        return [{
            "id": f"snapshot:poi:{self.history_id}:2024",
            "source": "saved-project",
            "year": 2024,
            "summary": {"total": len(self._pois)},
        }]

    def get_poi_data(self, poi_result_id: Any) -> List[Dict[str, Any]]:
        if str(poi_result_id or "") != f"snapshot:poi:{self.history_id}:2024":
            return []
        return _clone_json(self._pois)

    def list_analysis_artifacts(self, history_id: str) -> List[Dict[str, Any]]:
        if str(history_id or "").strip() != self.history_id:
            return []
        return _clone_json(self._artifacts)

    def history_detail(self) -> Dict[str, Any]:
        history = self.snapshot.get("history") if isinstance(self.snapshot.get("history"), dict) else {}
        polygon = history.get("polygon_wgs84") or history.get("polygon")
        detail: Dict[str, Any] = {"history_id": self.history_id}
        if isinstance(polygon, list) and polygon:
            detail["polygon_wgs84"] = {
                "type": "Polygon",
                "coordinates": [polygon],
            }
        return detail


class ScopeDatasetService:
    def __init__(self, repository: Optional[ScopeDatasetRepository] = None):
        self.repository = repository or ScopeDatasetRepository()

    @classmethod
    def from_saved_snapshot(cls, path: Any) -> "ScopeDatasetService":
        return cls(repository=SavedProjectSnapshotRepository.from_json_path(path))

    def list_scope_datasets(self, history_id: str) -> Dict[str, Any]:
        normalized_history_id = _as_text(history_id)
        if not normalized_history_id:
            return {"datasets": [], "warnings": ["history_id_required"]}
        poi_rows = self.repository.list_poi_results(normalized_history_id)
        artifacts = self.repository.list_analysis_artifacts(normalized_history_id)
        datasets = []
        if poi_rows:
            years = available_business_years(row.get("year") for row in poi_rows)
            selected_year = resolve_business_year(years)
            selected_rows = [row for row in poi_rows if normalize_year(row.get("year")) == selected_year]
            count = sum(self._poi_result_count(row) for row in selected_rows)
            datasets.append(self._dataset_payload("current:dataset:poi", count, years=years, selected_year=selected_year, variants=len(selected_rows)))
        for source_id in ["current:dataset:h3", "current:dataset:poi_grid", "current:dataset:population", "current:dataset:nightlight", "current:dataset:road_edges", "current:dataset:road_grid"]:
            matching = [
                item for item in artifacts
                if (
                    ARTIFACT_SOURCE_MAP.get(_as_text(item.get("artifact_type"))) == source_id
                    or (_as_text(item.get("artifact_type")) == "road_syntax" and source_id == "current:dataset:road_grid")
                )
            ]
            selected, years, selected_year = self._select_artifacts(
                source_id=source_id,
                artifacts=matching,
                requested_year=None,
                poi_rows=poi_rows,
            )
            if not selected and not matching:
                continue
            records = []
            for artifact in selected:
                records.extend(self._records_from_artifact(source_id, artifact))
            summary = self._selected_artifact_summary(selected)
            spatial_ready = bool(selected) and all(self._artifact_coord_type(source_id, artifact) for artifact in selected)
            datasets.append(
                self._dataset_payload(
                    source_id,
                    len(records),
                    years=years,
                    selected_year=selected_year,
                    variants=len(selected),
                    summary=summary,
                    spatial_ready=spatial_ready,
                )
            )
        return {"datasets": datasets, "warnings": []}

    def load_scope_records(
        self,
        *,
        history_id: str,
        source_id: str,
        year: Any = None,
        require_geometry_metadata: bool = False,
    ) -> tuple[List[ScopeRecord], List[int], int | None]:
        """Load normalized typed records for a selected historical dataset snapshot.

        This is the domain-level counterpart to query_scope_dataset: callers that
        need to compose multiple spatial metrics can use stable WGS84 geometries
        without reaching into artifact payloads or this service's private loaders.
        """
        return self._records_with_selection(
            history_id=history_id,
            source_id=source_id,
            year=year,
            require_geometry_metadata=require_geometry_metadata,
        )


    def query_scope_dataset(
        self,
        *,
        history_id: str,
        source_id: str,
        filters: Optional[Dict[str, Any]] = None,
        sort: Optional[Dict[str, Any]] = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        year: Any = None,
        spatial: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._validate_query_fields(source_id, filters=filters or {}, sort=sort or {})
        records, available_years, selected_year = self._records_with_selection(
            history_id=history_id,
            source_id=source_id,
            year=year,
            require_geometry_metadata=spatial is not None,
        )
        spatial_matches: Dict[int, Dict[str, Any]] = {}
        spatial_warnings: List[str] = []
        spatial_query = _clone_json(spatial) if isinstance(spatial, dict) else None
        spatial_diagnostics: Dict[str, Any] = {}
        spatial_records = records
        if spatial is not None:
            selection = self._select_spatial_records(
                history_id=history_id,
                source_id=source_id,
                selected_year=selected_year,
                records=records,
                spatial=spatial,
            )
            spatial_records = selection.records
            spatial_matches = selection.matches
            spatial_warnings.extend(selection.warnings)
            spatial_diagnostics = {
                "matched_record_count": len(selection.records),
                "skipped_record_count": selection.skipped_record_count,
                "result_complete": selection.skipped_record_count == 0,
            }
        filtered = self._apply_filters(spatial_records, source_id, filters or {})
        if spatial is not None and str(spatial.get("relation") or "").strip().lower() in {"nearest", "within_distance"}:
            sorted_records = list(filtered)
        else:
            sorted_records = self._apply_sort(filtered, sort or {})
        safe_limit = min(max(int(limit or DEFAULT_LIMIT), 1), MAX_LIMIT)
        safe_offset = max(int(offset or 0), 0)
        page = sorted_records[safe_offset : safe_offset + safe_limit]
        warnings = self._missing_year_warnings(page)
        warnings.extend(spatial_warnings)
        return {
            "source_id": source_id,
            "selected_year": selected_year,
            "available_years": available_years,
            "total_count": len(filtered),
            "limit": safe_limit,
            "offset": safe_offset,
            "has_more": safe_offset + safe_limit < len(filtered),
            "spatial_query": spatial_query,
            "spatial_diagnostics": spatial_diagnostics,
            "records": [record.as_payload(spatial_matches.get(id(record))) for record in page],
            "evidence_nodes": [record.evidence_node(spatial_matches.get(id(record))) for record in page],
            "warnings": sorted(set(warnings)),
        }

    def materialize_query_snapshot(
        self,
        *,
        history_id: str,
        source_id: str,
        filters: Optional[Dict[str, Any]] = None,
        year: Any = None,
        spatial: Optional[Dict[str, Any]] = None,
        max_features: int = MAX_QUERY_SNAPSHOT_FEATURES,
    ) -> Dict[str, Any]:
        """Materialize one complete, reproducible WGS84 dataset selection.

        Unlike the Agent-facing paged query, this method returns every matching
        geometry to the private snapshot boundary. It never samples or truncates.
        """
        self._validate_query_fields(source_id, filters=filters or {}, sort={})
        records, available_years, selected_year = self._records_with_selection(
            history_id=history_id,
            source_id=source_id,
            year=year,
            require_geometry_metadata=True,
        )
        spatial_warnings: List[str] = []
        if spatial is not None:
            selection = self._select_spatial_records(
                history_id=history_id,
                source_id=source_id,
                selected_year=selected_year,
                records=records,
                spatial=spatial,
            )
            records = selection.records
            spatial_warnings.extend(selection.warnings)
        records = self._apply_filters(records, source_id, filters or {})

        features: List[Dict[str, Any]] = []
        missing_geometry_count = 0
        for record_index, record in enumerate(sorted(records, key=lambda item: item.record_id), 1):
            parts = self._standard_geometry_parts(record.geometry)
            if not parts:
                missing_geometry_count += 1
                continue
            for part_index, geometry in enumerate(parts, 1):
                features.append({
                    "id": f"{record.record_id}:record:{record_index}:part:{part_index}",
                    "record_id": record.record_id,
                    "source_id": source_id,
                    "title": record.title,
                    "properties": _clone_json(record.properties),
                    "geometry": json.loads(json.dumps(mapping(geometry), ensure_ascii=False)),
                })
                if len(features) > max_features:
                    return {
                        "status": "unavailable",
                        "source_id": source_id,
                        "selected_year": selected_year,
                        "available_years": available_years,
                        "record_count": len(records),
                        "normalized_feature_count": len(features),
                        "features": [],
                        "warnings": sorted(set(spatial_warnings)),
                        "failure_reasons": [f"normalized_feature_count_exceeds_limit:{max_features}"],
                    }

        warnings = list(spatial_warnings)
        if missing_geometry_count:
            warnings.append(f"records_without_geometry:{missing_geometry_count}")
        return {
            "status": "available",
            "source_id": source_id,
            "selected_year": selected_year,
            "available_years": available_years,
            "record_count": len(records),
            "normalized_feature_count": len(features),
            "features": features,
            "warnings": sorted(set(warnings)),
            "failure_reasons": [],
        }

    @staticmethod
    def _standard_geometry_parts(geometry: BaseGeometry | None) -> List[BaseGeometry]:
        if geometry is None or geometry.is_empty:
            return []
        if geometry.geom_type in {"Point", "LineString", "Polygon"}:
            return [geometry]
        parts: List[BaseGeometry] = []
        for child in getattr(geometry, "geoms", ()):
            parts.extend(ScopeDatasetService._standard_geometry_parts(child))
        return parts

    def _select_spatial_records(
        self,
        *,
        history_id: str,
        source_id: str,
        selected_year: int | None,
        records: List[ScopeRecord],
        spatial: Dict[str, Any],
    ) -> _SpatialSelection:
        relation = _as_text(spatial.get("relation")).lower() if isinstance(spatial, dict) else ""
        supported_relations = DATASET_SPATIAL_CAPABILITIES.get(source_id, {}).get("spatial_relations") or []
        if relation not in supported_relations:
            raise SpatialQueryError(
                "spatial_relation_unsupported",
                f"{source_id} 不支持空间关系: {relation or '空'}",
            )
        engine_query, target_record = self._resolve_spatial_target(history_id, spatial)
        spatial_result = query_spatial_records(
            records,
            engine_query,
            cache_key=self._spatial_cache_key(history_id, source_id, selected_year, records),
        )
        exclude_target = bool(spatial.get("exclude_target", True))
        selected: List[ScopeRecord] = []
        matches: Dict[int, Dict[str, Any]] = {}
        for index, match in spatial_result.matches.items():
            record = records[index]
            if (
                target_record
                and exclude_target
                and target_record["source_id"] == source_id
                and target_record["record_id"] == record.record_id
            ):
                continue
            selected.append(record)
            matches[id(record)] = match.as_payload()
        return _SpatialSelection(
            records=selected,
            matches=matches,
            warnings=list(spatial_result.warnings),
            skipped_record_count=spatial_result.skipped_record_count,
        )

    def _resolve_spatial_target(
        self,
        history_id: str,
        spatial: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, str] | None]:
        engine_query = _clone_json(spatial)
        target = spatial.get("record") if isinstance(spatial.get("record"), dict) else None
        if target is None:
            engine_query.pop("exclude_target", None)
            return engine_query, None
        if spatial.get("point") is not None or spatial.get("geometry") is not None:
            raise SpatialQueryError(
                "spatial_query_invalid",
                "spatial.record 不能与 point 或 geometry 同时使用",
            )
        target_source_id = _as_text(target.get("source_id"))
        target_record_id = _as_text(target.get("record_id"))
        if target_source_id not in DATASET_TITLES or not target_record_id:
            raise SpatialQueryError(
                "spatial_query_invalid",
                "spatial.record 必须提供有效 source_id 和 record_id",
            )
        target_records, _, _ = self._records_with_selection(
            history_id=history_id,
            source_id=target_source_id,
            year=target.get("year"),
            require_geometry_metadata=True,
        )
        matched_target = next((record for record in target_records if record.record_id == target_record_id), None)
        if matched_target is None:
            raise SpatialQueryError(
                "spatial_target_record_not_found",
                f"未找到空间目标记录: {target_source_id}/{target_record_id}",
            )
        if matched_target.geometry is None:
            raise SpatialQueryError(
                "spatial_geometry_missing",
                f"空间目标记录没有可用 geometry: {target_source_id}/{target_record_id}",
            )
        engine_query.pop("record", None)
        engine_query.pop("exclude_target", None)
        engine_query["geometry"] = mapping(matched_target.geometry)
        engine_query["coord_type"] = "wgs84"
        return engine_query, {"source_id": target_source_id, "record_id": target_record_id}

    @staticmethod
    def _validate_query_fields(source_id: str, *, filters: Dict[str, Any], sort: Dict[str, Any]) -> None:
        allowed = DATASET_FILTER_FIELDS.get(source_id)
        if allowed is None:
            raise ScopeDatasetQueryError("scope_dataset_source_unsupported", f"不支持的数据源: {source_id}")
        unsupported_filters = sorted(set(filters) - allowed)
        if unsupported_filters:
            raise ScopeDatasetQueryError(
                "scope_dataset_field_unsupported",
                f"{source_id} 不支持筛选字段: {', '.join(unsupported_filters)}",
            )
        sort_field = _as_text(sort.get("field")) if isinstance(sort, dict) else ""
        if sort_field and sort_field not in allowed:
            raise ScopeDatasetQueryError(
                "scope_dataset_field_unsupported",
                f"{source_id} 不支持排序字段: {sort_field}",
            )

    @staticmethod
    def _spatial_cache_key(history_id: str, source_id: str, selected_year: int | None, records: List[ScopeRecord]) -> str:
        fingerprint = sha256()
        for record in records:
            fingerprint.update(record.record_id.encode("utf-8"))
            fingerprint.update(b"\0")
            fingerprint.update(record.locator.encode("utf-8"))
            fingerprint.update(b"\0")
            fingerprint.update(_as_text(record.time_scope.get("data_version")).encode("utf-8"))
            fingerprint.update(b"\0")
            fingerprint.update(_as_text(record.time_scope.get("scope_fingerprint")).encode("utf-8"))
            fingerprint.update(b"\0")
            if record.geometry is not None:
                fingerprint.update(record.geometry.wkb)
            fingerprint.update(b"\xff")
        digest = fingerprint.hexdigest()[:24]
        return f"{history_id}:{source_id}:{selected_year or 'static'}:{len(records)}:{digest}"

    def aggregate_scope_dataset(
        self,
        *,
        history_id: str,
        source_id: str,
        group_by: str = "",
        metrics: Optional[List[Dict[str, Any]]] = None,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
        year: Any = None,
        spatial: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metric_specs = metrics if isinstance(metrics, list) and metrics else [{"op": "count", "field": "*", "as": "count"}]
        self._validate_aggregate_request(
            source_id,
            group_by=group_by,
            metrics=metric_specs,
            filters=filters or {},
            spatial=spatial,
        )
        selected_records, available_years, selected_year = self._records_with_selection(
            history_id=history_id,
            source_id=source_id,
            year=year,
            require_geometry_metadata=spatial is not None,
        )
        spatial_matches: Dict[int, Dict[str, Any]] = {}
        spatial_warnings: List[str] = []
        skipped_record_count = 0
        spatial_records = selected_records
        if spatial is not None:
            selection = self._select_spatial_records(
                history_id=history_id,
                source_id=source_id,
                selected_year=selected_year,
                records=selected_records,
                spatial=spatial,
            )
            spatial_records = selection.records
            spatial_matches = selection.matches
            spatial_warnings.extend(selection.warnings)
            skipped_record_count = selection.skipped_record_count
        records = self._apply_filters(spatial_records, source_id, filters or {})
        group_field = _as_text(group_by)
        grouped: Dict[str, List[ScopeRecord]] = {}
        if group_field:
            for record in records:
                key = _as_text(record.properties.get(group_field)) or "未标注"
                grouped.setdefault(key, []).append(record)
        else:
            grouped["all"] = list(records)
        rows = []
        for key, items in grouped.items():
            row: Dict[str, Any] = {"group": key, "count": len(items)}
            for spec in metric_specs:
                if not isinstance(spec, dict):
                    continue
                op = _as_text(spec.get("op") or "count").lower()
                field_name = _as_text(spec.get("field") or "*")
                alias = _as_text(spec.get("as")) or f"{op}_{field_name.replace('.', '_')}"
                row[alias] = self._metric_value(
                    items,
                    op=op,
                    field=field_name,
                    spatial_matches=spatial_matches,
                )
            rows.append(row)
        rows.sort(key=lambda item: item.get("count") or 0, reverse=True)
        safe_top_k = min(max(int(top_k or 10), 1), 100)
        warnings = self._missing_year_warnings(records)
        warnings.extend(spatial_warnings)
        payload = {
            "source_id": source_id,
            "selected_year": selected_year,
            "available_years": available_years,
            "group_by": group_field,
            "spatial_query": _clone_json(spatial) if isinstance(spatial, dict) else None,
            "spatial_summary": self._spatial_aggregate_summary(
                records,
                spatial_matches=spatial_matches,
                skipped_record_count=skipped_record_count,
                relation=_as_text(spatial.get("relation")) if isinstance(spatial, dict) else "",
            ),
            "metric_methods": [self._aggregate_metric_method(source_id, spec) for spec in metric_specs],
            "total_groups": len(rows),
            "rows": rows[:safe_top_k],
            "warnings": sorted(set(warnings)),
        }
        payload["evidence_node"] = self._aggregate_evidence_node(payload)
        return payload

    @staticmethod
    def _validate_aggregate_request(
        source_id: str,
        *,
        group_by: str,
        metrics: List[Dict[str, Any]],
        filters: Dict[str, Any],
        spatial: Optional[Dict[str, Any]],
    ) -> None:
        ScopeDatasetService._validate_query_fields(source_id, filters=filters, sort={})
        allowed = DATASET_FILTER_FIELDS[source_id]
        group_field = _as_text(group_by)
        if group_field and group_field not in allowed:
            raise ScopeDatasetQueryError(
                "scope_dataset_field_unsupported",
                f"{source_id} 不支持分组字段: {group_field}",
            )
        spatial_capabilities = DATASET_SPATIAL_AGGREGATIONS.get(source_id, [])
        for spec in metrics:
            if not isinstance(spec, dict):
                raise ScopeDatasetQueryError("scope_dataset_metric_invalid", "聚合 metric 必须是对象")
            op = _as_text(spec.get("op") or "count").lower()
            field_name = _as_text(spec.get("field") or "*")
            if op in GENERIC_AGGREGATE_OPS:
                if op != "count" and field_name not in allowed:
                    raise ScopeDatasetQueryError(
                        "scope_dataset_field_unsupported",
                        f"{source_id} 不支持聚合字段: {field_name}",
                    )
                relation = _as_text((spatial or {}).get("relation")).lower()
                unsafe_population = (
                    source_id == "current:dataset:population"
                    and relation == "intersects"
                    and op == "sum"
                    and field_name in {"population", "value"}
                )
                unsafe_nightlight = (
                    source_id == "current:dataset:nightlight"
                    and relation == "intersects"
                    and op in {"sum", "avg"}
                    and field_name in {"radiance", "value"}
                )
                if unsafe_population or unsafe_nightlight:
                    recommended = "area_weighted_sum" if unsafe_population else "area_weighted_avg"
                    raise ScopeDatasetQueryError(
                        "spatial_aggregate_unsafe",
                        f"{source_id} 的范围聚合不能使用 {op}({field_name})，请使用 {recommended}",
                    )
                continue
            if op not in SPATIAL_AGGREGATE_OPS:
                raise ScopeDatasetQueryError("scope_dataset_metric_unsupported", f"不支持的聚合方法: {op}")
            if not isinstance(spatial, dict) or _as_text(spatial.get("relation")).lower() != "intersects":
                raise ScopeDatasetQueryError(
                    "spatial_aggregate_invalid",
                    f"{op} 必须与 spatial.relation=intersects 一起使用",
                )
            capability = next((item for item in spatial_capabilities if item.get("op") == op), None)
            if capability is None or field_name not in (capability.get("fields") or []):
                raise ScopeDatasetQueryError(
                    "spatial_aggregate_unsupported",
                    f"{source_id} 不支持 {op}({field_name})",
                )

    @staticmethod
    def _aggregate_metric_method(source_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        op = _as_text(spec.get("op") or "count").lower()
        field_name = _as_text(spec.get("field") or "*")
        alias = _as_text(spec.get("as")) or f"{op}_{field_name.replace('.', '_')}"
        capability = next(
            (item for item in DATASET_SPATIAL_AGGREGATIONS.get(source_id, []) if item.get("op") == op),
            None,
        )
        return {
            "alias": alias,
            "op": op,
            "field": field_name,
            "method": _as_text((capability or {}).get("method")) or op,
            "assumptions": list((capability or {}).get("assumptions") or []),
            "unit": _as_text((capability or {}).get("unit")),
        }

    @staticmethod
    def _spatial_aggregate_summary(
        records: List[ScopeRecord],
        *,
        spatial_matches: Dict[int, Dict[str, Any]],
        skipped_record_count: int,
        relation: str,
    ) -> Dict[str, Any]:
        if not relation:
            return {}
        matches = [spatial_matches.get(id(record)) or {} for record in records]
        overlap_area = sum(_as_float(match.get("overlap_area_m2")) or 0.0 for match in matches)
        intersection_length = sum(_as_float(match.get("intersection_length_m")) or 0.0 for match in matches)
        return {
            "relation": relation,
            "matched_record_count": len(records),
            "skipped_record_count": int(skipped_record_count or 0),
            "overlap_area_m2": round(overlap_area, 3),
            "intersection_length_m": round(intersection_length, 3),
        }

    @staticmethod
    def _aggregate_evidence_node(payload: Dict[str, Any]) -> Dict[str, Any]:
        source_id = _as_text(payload.get("source_id"))
        selected_year = _as_int(payload.get("selected_year"))
        methods = payload.get("metric_methods") if isinstance(payload.get("metric_methods"), list) else []
        assumptions = sorted({
            _as_text(assumption)
            for method in methods
            if isinstance(method, dict)
            for assumption in (method.get("assumptions") or [])
            if _as_text(assumption)
        })
        identity_payload = {
            "source_id": source_id,
            "selected_year": selected_year,
            "group_by": payload.get("group_by"),
            "spatial_query": payload.get("spatial_query"),
            "rows": payload.get("rows"),
        }
        identity = sha256(
            json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:20]
        title = f"{DATASET_TITLES.get(source_id, source_id)}空间聚合"
        matched_count = _as_int((payload.get("spatial_summary") or {}).get("matched_record_count"))
        content = f"{title}，返回 {len(payload.get('rows') or [])} 个聚合分组"
        if matched_count is not None:
            content += f"，匹配 {matched_count} 条空间记录"
        warnings = list(payload.get("warnings") or [])
        node = EvidenceNode(
            id=f"{source_id}:aggregate:{identity}",
            kind="spatial_metric",
            source_ids=[source_id],
            title=title,
            content=content,
            summary=content,
            data={
                "group_by": payload.get("group_by"),
                "rows": _clone_json(payload.get("rows") or []),
                "spatial_query": _clone_json(payload.get("spatial_query")),
                "spatial_summary": _clone_json(payload.get("spatial_summary") or {}),
                "metric_methods": _clone_json(methods),
                "assumptions": assumptions,
            },
            time_scope=_time_scope(year=selected_year),
            locator=f"{source_id}/aggregate/{identity}",
            quality_flags=[
                {"code": "aggregate_warning", "severity": "warning", "effect": warning}
                for warning in warnings
            ],
            citation=f"{DATASET_TITLES.get(source_id, source_id)}空间聚合，{selected_year or '当前版本'}",
        )
        return node.model_dump(mode="python")

    def read_scope_record(self, *, history_id: str, source_id: str, record_id: str, year: Any = None) -> Dict[str, Any]:
        normalized_record_id = _as_text(record_id)
        for record in self._records(history_id=history_id, source_id=source_id, year=year):
            if record.record_id == normalized_record_id:
                return {
                    "source_id": source_id,
                    "record_id": normalized_record_id,
                    "record": record.as_payload(),
                    "evidence_node": record.evidence_node(),
                    "warnings": list(record.warnings or []),
                }
        return {
            "source_id": source_id,
            "record_id": normalized_record_id,
            "record": {},
            "evidence_node": None,
            "warnings": [f"未找到当前范围记录: {normalized_record_id}"],
        }

    def _dataset_payload(
        self,
        source_id: str,
        record_count: int,
        *,
        years: List[int],
        selected_year: int | None,
        variants: int,
        summary: Optional[Dict[str, Any]] = None,
        spatial_ready: bool = True,
    ) -> Dict[str, Any]:
        is_static = source_id in {"current:dataset:road_edges", "current:dataset:road_grid"}
        warnings = [] if years or is_static else ["该来源未提供明确年份。"]
        if record_count and not spatial_ready:
            warnings.append("artifact 缺少有效 geometry_coord_type，属性查询可用，但空间查询不可用。")
        spatial_capabilities = DATASET_SPATIAL_CAPABILITIES.get(source_id, {})
        return {
            "source_id": source_id,
            "source_kind": "system",
            "title": DATASET_TITLES.get(source_id, source_id),
            "status": "ready" if record_count else "pending",
            "record_count": int(record_count or 0),
            "selected_year": selected_year,
            "available_years": years,
            "summary": _clone_json(summary or {}),
            "geometry_type": _as_text(spatial_capabilities.get("geometry_type")),
            "grid_type": _as_text(spatial_capabilities.get("grid_type")),
            "geometry_coord_type": "wgs84",
            "time_scope": {
                "years": years,
                "selected_year": selected_year,
                "kind": "static_snapshot" if is_static else "year",
                "label": "当前路网模型" if is_static else (f"{selected_year} 年" if selected_year else "未标注年份"),
            },
            "query_capabilities": {
                "filter_fields": sorted(DATASET_FILTER_FIELDS.get(source_id, set())),
                "sort_fields": sorted(DATASET_FILTER_FIELDS.get(source_id, set())),
                "aggregate_fields": sorted(DATASET_FILTER_FIELDS.get(source_id, set())),
                "spatial_relations": list(spatial_capabilities.get("spatial_relations") or []),
                "spatial_aggregations": _clone_json(DATASET_SPATIAL_AGGREGATIONS.get(source_id, [])),
                "spatial_ready": bool(spatial_ready),
                "input_coord_types": ["gcj02", "wgs84"],
                "distance_unit": "m",
                "variants": int(variants or 0),
            },
            "warnings": warnings,
        }

    def _records(self, *, history_id: str, source_id: str, year: Any = None) -> List[ScopeRecord]:
        records, _, _ = self._records_with_selection(history_id=history_id, source_id=source_id, year=year)
        return records

    def _records_with_selection(
        self,
        *,
        history_id: str,
        source_id: str,
        year: Any = None,
        require_geometry_metadata: bool = False,
    ) -> tuple[List[ScopeRecord], List[int], int | None]:
        normalized_source_id = _as_text(source_id)
        if not _as_text(history_id) or normalized_source_id not in DATASET_TITLES:
            return [], [], normalize_year(year)
        if normalized_source_id == "current:dataset:poi":
            rows = self.repository.list_poi_results(history_id)
            years = available_business_years(row.get("year") for row in rows)
            selected_year = resolve_business_year(years, year)
            return self._poi_records(history_id, year=selected_year), years, selected_year
        all_artifacts = [
            item
            for item in self.repository.list_analysis_artifacts(history_id)
            if (
                ARTIFACT_SOURCE_MAP.get(_as_text(item.get("artifact_type"))) == normalized_source_id
                or (_as_text(item.get("artifact_type")) == "road_syntax" and normalized_source_id == "current:dataset:road_grid")
            )
        ]
        poi_rows = self.repository.list_poi_results(history_id) if normalized_source_id in {"current:dataset:h3", "current:dataset:poi_grid"} else []
        artifacts, years, selected_year = self._select_artifacts(
            source_id=normalized_source_id,
            artifacts=all_artifacts,
            requested_year=year,
            poi_rows=poi_rows,
        )
        records: List[ScopeRecord] = []
        for artifact in artifacts:
            records.extend(
                self._records_from_artifact(
                    normalized_source_id,
                    artifact,
                    require_geometry_metadata=require_geometry_metadata,
                )
            )
        return records, years, selected_year

    @staticmethod
    def _artifact_sort_key(artifact: Dict[str, Any]) -> tuple[str, int]:
        return (_as_text(artifact.get("updated_at")), int(artifact.get("id") or 0))

    def _dedupe_artifacts(self, artifacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        latest: Dict[tuple[str, str], Dict[str, Any]] = {}
        for artifact in artifacts:
            artifact_type = _as_text(artifact.get("artifact_type"))
            slot_key = _as_text(artifact.get("slot_key"))
            if not slot_key:
                try:
                    slot_key = build_artifact_slot_key(artifact_type, artifact.get("params"), artifact.get("payload"))
                except ValueError:
                    slot_key = "year:unknown"
            key = (artifact_type, slot_key)
            existing = latest.get(key)
            if existing is None or self._artifact_sort_key(artifact) > self._artifact_sort_key(existing):
                latest[key] = artifact
        return list(latest.values())

    def _select_artifacts(
        self,
        *,
        source_id: str,
        artifacts: List[Dict[str, Any]],
        requested_year: Any,
        poi_rows: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], List[int], int | None]:
        deduped = self._dedupe_artifacts(artifacts)
        if source_id in {"current:dataset:road_edges", "current:dataset:road_grid"}:
            selected = sorted(deduped, key=self._artifact_sort_key, reverse=True)[:1]
            return selected, [], None
        years = available_business_years(_year_from_artifact(item) for item in deduped)
        if source_id in {"current:dataset:h3", "current:dataset:poi_grid"}:
            poi_years = available_business_years(row.get("year") for row in poi_rows)
            selected_year = resolve_business_year(poi_years or years, requested_year)
        else:
            selected_year = resolve_business_year(years, requested_year)
        selected = [item for item in deduped if normalize_year(_year_from_artifact(item)) == selected_year]
        return sorted(selected, key=self._artifact_sort_key, reverse=True), years, selected_year

    @staticmethod
    def _selected_artifact_summary(artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        if len(artifacts) == 1:
            artifact = artifacts[0]
            payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
            summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
            return _clone_json(summary or (payload.get("summary") if isinstance(payload.get("summary"), dict) else {}))
        return {
            _as_text(item.get("artifact_type")): _clone_json(item.get("summary") if isinstance(item.get("summary"), dict) else {})
            for item in artifacts
        }

    def _poi_records(self, history_id: str, *, year: Any = None) -> List[ScopeRecord]:
        records: List[ScopeRecord] = []
        requested_year = _as_int(year)
        for row in self.repository.list_poi_results(history_id):
            row_year = _as_int(row.get("year"))
            if requested_year is not None and row_year != requested_year:
                continue
            source = _as_text(row.get("source")) or "local"
            time_scope = _time_scope(year=row_year)
            warnings = _dataset_warning_for_year(row_year)
            for index, poi in enumerate(self.repository.get_poi_data(row.get("id"))):
                if not isinstance(poi, dict):
                    continue
                record_id = _as_text(poi.get("id") or poi.get("uid") or poi.get("poi_id")) or f"{source}:{row_year or 'unknown'}:{index}"
                name = _as_text(poi.get("name")) or f"POI {index + 1}"
                category = _as_text(poi.get("type") or poi.get("category") or poi.get("typecode"))
                address = _as_text(poi.get("address"))
                props = {
                    **_clone_json(poi),
                    "record_id": record_id,
                    "source": source,
                    "year": row_year,
                    "category": category,
                }
                content_parts = [name]
                if category:
                    content_parts.append(f"类型：{category}")
                if address:
                    content_parts.append(f"地址：{address}")
                records.append(
                    ScopeRecord(
                        source_id="current:dataset:poi",
                        record_id=record_id,
                        title=name,
                        content="；".join(content_parts),
                        properties=props,
                        raw=_clone_json(poi),
                        time_scope=time_scope,
                        locator=f"current:dataset:poi/{record_id}",
                        citation=f"当前范围 POI，{time_scope.get('label')}",
                        warnings=warnings,
                        geometry=_point_from_poi(poi, POI_GEOMETRY_COORD_TYPE),
                    )
                )
        return records

    @staticmethod
    def _poi_result_count(row: Dict[str, Any]) -> int:
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        total = _as_int(summary.get("total"))
        if total is not None:
            return total
        return len(row.get("poi_data") or [])

    def _records_from_artifact(
        self,
        source_id: str,
        artifact: Dict[str, Any],
        *,
        require_geometry_metadata: bool = False,
    ) -> List[ScopeRecord]:
        artifact_type = _as_text(artifact.get("artifact_type"))
        if source_id == "current:dataset:road_edges":
            return self._road_edge_records(artifact, require_geometry_metadata=require_geometry_metadata)
        if source_id == "current:dataset:road_grid":
            return self._road_grid_records(artifact, require_geometry_metadata=require_geometry_metadata)
        return self._grid_records(
            source_id,
            artifact,
            artifact_type,
            require_geometry_metadata=require_geometry_metadata,
        )

    @staticmethod
    def _artifact_coord_type(
        source_id: str,
        artifact: Dict[str, Any],
        *,
        required: bool = False,
    ) -> str:
        params = artifact.get("params") if isinstance(artifact.get("params"), dict) else {}
        payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
        coord_type = _as_text(
            payload.get("geometry_coord_type")
            or payload.get("coord_type")
            or params.get("geometry_coord_type")
            or params.get("coord_type")
        ).lower()
        if coord_type in {"gcj02", "wgs84"}:
            return coord_type
        inferred_coord_type = LEGACY_ARTIFACT_GEOMETRY_COORD_TYPES.get(
            _as_text(artifact.get("artifact_type"))
        )
        if inferred_coord_type:
            return inferred_coord_type
        if required:
            artifact_type = _as_text(artifact.get("artifact_type")) or "unknown"
            raise SpatialQueryError(
                "spatial_coord_type_unknown",
                f"{source_id} 的 {artifact_type} artifact 缺少有效 geometry_coord_type",
            )
        return ""

    def _grid_records(
        self,
        source_id: str,
        artifact: Dict[str, Any],
        artifact_type: str,
        *,
        require_geometry_metadata: bool = False,
    ) -> List[ScopeRecord]:
        payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
        coord_type = self._artifact_coord_type(source_id, artifact, required=require_geometry_metadata)
        grid = payload.get("grid") if isinstance(payload.get("grid"), dict) else {}
        layer = payload.get("layer") if isinstance(payload.get("layer"), dict) else {}
        cells_by_id = {}
        for cell in layer.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            cell_id = _as_text(cell.get("cell_id") or cell.get("id") or cell.get("h3_id"))
            if cell_id:
                cells_by_id[cell_id] = cell
        year = _year_from_artifact(artifact)
        time_scope = _time_scope(
            year=year,
            data_version=_as_text(artifact.get("data_version")),
            scope_fingerprint=_as_text(artifact.get("scope_fingerprint")),
        )
        warnings = _dataset_warning_for_year(year)
        records: List[ScopeRecord] = []
        for index, feature in enumerate(grid.get("features") or []):
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            feature_id = _feature_record_id(feature, f"{artifact_type}:{index}")
            cell = cells_by_id.get(feature_id) or cells_by_id.get(_as_text(props.get("cell_id"))) or {}
            merged = {
                **_clone_json(props),
                **_clone_json(cell if isinstance(cell, dict) else {}),
                "record_id": feature_id,
                "year": _as_int(year),
                "view": payload.get("view") or layer.get("view"),
                "artifact_type": artifact_type,
            }
            title = _as_text(merged.get("name") or merged.get("cell_id") or merged.get("h3_id") or feature_id)
            value = _first_value(merged, ["value", "population", "density", "radiance", "poi_count", "lq"])
            content = f"{DATASET_TITLES.get(source_id, source_id)}记录 {title}"
            if value not in (None, ""):
                content += f"，指标值 {value}"
            records.append(
                ScopeRecord(
                    source_id=source_id,
                    record_id=feature_id,
                    title=title,
                    content=content,
                    properties=merged,
                    raw={"feature": _clone_json(feature), "cell": _clone_json(cell)},
                    time_scope=time_scope,
                    locator=f"{source_id}/{feature_id}",
                    citation=f"{DATASET_TITLES.get(source_id, source_id)}，{time_scope.get('label')}",
                    warnings=warnings,
                    geometry=_geometry_from_feature(feature, source_id, coord_type),
                )
            )
        return records

    def _road_edge_records(self, artifact: Dict[str, Any], *, require_geometry_metadata: bool = False) -> List[ScopeRecord]:
        payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
        metric = payload.get("metric") or payload.get("mode") or ""
        coord_type = self._artifact_coord_type(
            "current:dataset:road_edges",
            artifact,
            required=require_geometry_metadata,
        )
        time_scope = _static_time_scope(
            data_version=_as_text(artifact.get("data_version")),
            scope_fingerprint=_as_text(artifact.get("scope_fingerprint")),
        )
        records: List[ScopeRecord] = []
        for kind, collection_key in [("road_edge", "road_edges")]:
            collection = payload.get(collection_key) if isinstance(payload.get(collection_key), dict) else {}
            for index, feature in enumerate(collection.get("features") or []):
                if not isinstance(feature, dict):
                    continue
                props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                base_id = _feature_record_id(feature, f"{kind}:{index}")
                record_id = f"{kind}:{base_id}"
                merged = {
                    **_clone_json(props),
                    "record_id": record_id,
                    "feature_kind": kind,
                    "metric": metric,
                }
                title = _as_text(merged.get("name") or merged.get("road_name") or merged.get("node_id") or record_id)
                metric_value = _first_value(merged, ["choice", "integration", "connectivity", "depth", "value"])
                content = f"路网线段 {title}"
                if metric_value not in (None, ""):
                    content += f"，指标值 {metric_value}"
                records.append(
                    ScopeRecord(
                        source_id="current:dataset:road_edges",
                        record_id=record_id,
                        title=title,
                        content=content,
                        properties=merged,
                        raw={"feature": _clone_json(feature)},
                        time_scope=time_scope,
                        locator=f"current:dataset:road_edges/{record_id}",
                        citation="当前范围路网线段，当前路网模型",
                        warnings=[],
                        geometry=_geometry_from_feature(feature, "current:dataset:road_edges", coord_type),
                    )
                )
        return records

    def _road_grid_records(self, artifact: Dict[str, Any], *, require_geometry_metadata: bool = False) -> List[ScopeRecord]:
        payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
        collection = payload.get("road_grid") if isinstance(payload.get("road_grid"), dict) else {}
        coord_type = self._artifact_coord_type(
            "current:dataset:road_grid",
            artifact,
            required=require_geometry_metadata,
        )
        time_scope = _static_time_scope(
            data_version=_as_text(artifact.get("data_version")),
            scope_fingerprint=_as_text(artifact.get("scope_fingerprint")),
        )
        records: List[ScopeRecord] = []
        for index, feature in enumerate(collection.get("features") or []):
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            record_id = _as_text(props.get("cell_id") or props.get("h3_id")) or _feature_record_id(feature, f"road_grid:{index}")
            merged = {**_clone_json(props), "record_id": record_id, "feature_kind": "road_grid"}
            records.append(ScopeRecord(
                source_id="current:dataset:road_grid",
                record_id=record_id,
                title=record_id,
                content=f"路网共享栅格 {record_id}，道路长度 {merged.get('road_length_km', 0)} km",
                properties=merged,
                raw={"feature": _clone_json(feature)},
                time_scope=time_scope,
                locator=f"current:dataset:road_grid/{record_id}",
                citation="当前范围路网共享栅格，当前路网模型",
                warnings=[],
                geometry=_geometry_from_feature(feature, "current:dataset:road_grid", coord_type),
            ))
        return records

    def _apply_filters(self, records: List[ScopeRecord], source_id: str, filters: Dict[str, Any]) -> List[ScopeRecord]:
        allowed = DATASET_FILTER_FIELDS.get(source_id, set())
        predicates = {key: value for key, value in (filters or {}).items() if key in allowed}
        if not predicates:
            return records
        return [record for record in records if self._record_matches(record, predicates)]

    def _record_matches(self, record: ScopeRecord, predicates: Dict[str, Any]) -> bool:
        for field_name, expected in predicates.items():
            actual = record.properties.get(field_name)
            if isinstance(expected, dict):
                contains = expected.get("contains")
                if contains not in (None, "") and str(contains).lower() not in str(actual or "").lower():
                    return False
                if "eq" in expected and actual != expected.get("eq"):
                    return False
                actual_number = _as_float(actual)
                if "gte" in expected and (actual_number is None or actual_number < float(expected.get("gte"))):
                    return False
                if "lte" in expected and (actual_number is None or actual_number > float(expected.get("lte"))):
                    return False
            elif actual != expected:
                return False
        return True

    def _apply_sort(self, records: List[ScopeRecord], sort: Dict[str, Any]) -> List[ScopeRecord]:
        field_name = _as_text(sort.get("field") if isinstance(sort, dict) else "")
        if not field_name:
            return list(records)
        direction = _as_text(sort.get("direction") if isinstance(sort, dict) else "").lower()

        def key(record: ScopeRecord):
            value = record.properties.get(field_name)
            number = _as_float(value)
            return (number is None, number if number is not None else _as_text(value))

        return sorted(records, key=key, reverse=direction == "desc")

    def _metric_value(
        self,
        records: List[ScopeRecord],
        *,
        op: str,
        field: str,
        spatial_matches: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Any:
        if op == "count":
            return len(records)
        matches = spatial_matches or {}
        if op == "intersection_length_sum":
            total = sum(
                _as_float((matches.get(id(record)) or {}).get("intersection_length_m")) or 0.0
                for record in records
            )
            return round(total, 3)
        if op == "area_weighted_sum":
            total = 0.0
            for record in records:
                value = _as_float(record.properties.get(field))
                ratio = _as_float((matches.get(id(record)) or {}).get("record_overlap_ratio"))
                if value is not None and ratio is not None:
                    total += value * ratio
            return round(total, 6)
        if op == "area_weighted_avg":
            weighted_total = 0.0
            total_area = 0.0
            for record in records:
                value = _as_float(record.properties.get(field))
                area = _as_float((matches.get(id(record)) or {}).get("overlap_area_m2"))
                if value is not None and area is not None and area > 0:
                    weighted_total += value * area
                    total_area += area
            return round(weighted_total / total_area, 6) if total_area > 0 else None
        values = [_as_float(record.properties.get(field)) for record in records]
        numbers = [value for value in values if value is not None]
        if not numbers:
            return None
        if op == "sum":
            return sum(numbers)
        if op == "avg":
            return sum(numbers) / len(numbers)
        if op == "min":
            return min(numbers)
        if op == "max":
            return max(numbers)
        return None

    def _missing_year_warnings(self, records: List[ScopeRecord]) -> List[str]:
        return sorted({warning for record in records for warning in (record.warnings or [])})
