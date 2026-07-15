from __future__ import annotations

import math
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Optional

from shapely.geometry import Point, shape
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
    "current:dataset:road_edges": {"record_id", "edge_id", "choice_score", "integration_score", "connectivity_score", "control_score", "depth_score", "metric"},
    "current:dataset:road_grid": {"record_id", "cell_id", "road_has_data", "road_length_km", "road_length_km_per_km2", "road_choice", "road_integration", "road_connectivity", "road_control", "road_depth"},
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

POI_GEOMETRY_COORD_TYPE = "gcj02"

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


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


class ScopeDatasetService:
    def __init__(self, repository: Optional[ScopeDatasetRepository] = None):
        self.repository = repository or ScopeDatasetRepository()

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
            datasets.append(self._dataset_payload(source_id, len(records), years=years, selected_year=selected_year, variants=len(selected), summary=summary))
        return {"datasets": datasets, "warnings": []}

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
        records, available_years, selected_year = self._records_with_selection(
            history_id=history_id,
            source_id=source_id,
            year=year,
            require_geometry_metadata=spatial is not None,
        )
        spatial_matches: Dict[int, Dict[str, Any]] = {}
        spatial_warnings: List[str] = []
        spatial_query = _clone_json(spatial) if isinstance(spatial, dict) else None
        spatial_records = records
        if spatial is not None:
            relation = _as_text(spatial.get("relation")).lower() if isinstance(spatial, dict) else ""
            supported_relations = DATASET_SPATIAL_CAPABILITIES.get(source_id, {}).get("spatial_relations") or []
            if relation not in supported_relations:
                raise SpatialQueryError(
                    "spatial_relation_unsupported",
                    f"{source_id} 不支持空间关系: {relation or '空'}",
                )
            spatial_result = query_spatial_records(
                records,
                spatial,
                cache_key=self._spatial_cache_key(history_id, source_id, selected_year, records),
            )
            spatial_records = [records[index] for index in spatial_result.matches]
            spatial_matches = {
                id(records[index]): match.as_payload()
                for index, match in spatial_result.matches.items()
            }
            spatial_warnings.extend(spatial_result.warnings)
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
            "records": [record.as_payload(spatial_matches.get(id(record))) for record in page],
            "evidence_nodes": [record.evidence_node(spatial_matches.get(id(record))) for record in page],
            "warnings": sorted(set(warnings)),
        }

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
    ) -> Dict[str, Any]:
        selected_records, available_years, selected_year = self._records_with_selection(
            history_id=history_id,
            source_id=source_id,
            year=year,
        )
        records = self._apply_filters(selected_records, source_id, filters or {})
        group_field = _as_text(group_by)
        metric_specs = metrics if isinstance(metrics, list) and metrics else [{"op": "count", "field": "*", "as": "count"}]
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
                row[alias] = self._metric_value(items, op=op, field=field_name)
            rows.append(row)
        rows.sort(key=lambda item: item.get("count") or 0, reverse=True)
        safe_top_k = min(max(int(top_k or 10), 1), 100)
        return {
            "source_id": source_id,
            "selected_year": selected_year,
            "available_years": available_years,
            "group_by": group_field,
            "total_groups": len(rows),
            "rows": rows[:safe_top_k],
            "warnings": self._missing_year_warnings(records),
        }

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
    ) -> Dict[str, Any]:
        is_static = source_id in {"current:dataset:road_edges", "current:dataset:road_grid"}
        warnings = [] if years or is_static else ["该来源未提供明确年份。"]
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

    def _metric_value(self, records: List[ScopeRecord], *, op: str, field: str) -> Any:
        if op == "count":
            return len(records)
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
