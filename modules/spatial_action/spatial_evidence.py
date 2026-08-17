from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from shapely.strtree import STRtree

from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84
from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action.metric_tools import MetricToolService
from modules.spatial_action.source_index import SourceIndex
from modules.spatial_projects.service import SpatialProjectService


SCHEMA_VERSION = "spatial_evidence/v2"
DEFAULT_DISTANCE_BANDS_M = ((0.0, 500.0), (500.0, 1000.0), (1000.0, 1600.0))
DIRECTION_CODES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
DIRECTION_LABELS = {
    "N": "北",
    "NE": "东北",
    "E": "东",
    "SE": "东南",
    "S": "南",
    "SW": "西南",
    "W": "西",
    "NW": "西北",
}
SELECTOR_DIMENSIONS = {"poi.category", "poi.subcategory", "road.class", "year"}
FORBIDDEN_OUTPUT_KEYS = {
    "geometry",
    "coordinates",
    "features",
    "featurecollection",
    "database",
    "connection",
    "file_path",
    "path",
}
MODEL_RESPONSE_CHAR_LIMIT = 8000
MODEL_STRING_CHAR_LIMIT = 1200
MODEL_LIST_ITEM_LIMIT = 20

DATASET_FIELD_CATALOG = {
    "current:dataset:poi": {
        "dataset_id": "poi",
        "identity_fields": ["name", "category", "subcategory", "typecode", "address", "year", "source"],
        "measure_fields": [],
    },
    "current:dataset:h3": {
        "dataset_id": "h3",
        "identity_fields": ["h3_id", "year"],
        "measure_fields": [
            "poi_count", "density_poi_per_km2", "category_counts", "subcategory_counts",
            "local_entropy", "neighbor_mean_density", "neighbor_mean_entropy", "lq",
            "gi_star_z_score", "lisa_i",
        ],
    },
    "current:dataset:poi_grid": {
        "dataset_id": "poi_grid",
        "identity_fields": ["cell_id", "year"],
        "measure_fields": ["poi_count", "density_poi_per_km2", "category_counts", "dominant_category_name"],
    },
    "current:dataset:population": {
        "dataset_id": "population",
        "identity_fields": ["cell_id", "year", "source"],
        "measure_fields": ["population_total", "age_5_19", "age_30_39", "age_50_64"],
    },
    "current:dataset:nightlight": {
        "dataset_id": "nightlight",
        "identity_fields": ["cell_id", "year", "unit", "has_data", "source"],
        "measure_fields": ["radiance"],
    },
    "current:dataset:road_nodes": {
        "dataset_id": "road_nodes",
        "identity_fields": ["node_id"],
        "measure_fields": ["degree"],
    },
    "current:dataset:road_edges": {
        "dataset_id": "road_edges",
        "identity_fields": ["road_name", "road_class"],
        "measure_fields": ["length_m", "metrics.integration", "metrics.choice", "metrics.connectivity", "metrics.depth", "metrics.control"],
    },
    "current:dataset:road_grid": {
        "dataset_id": "road_grid",
        "identity_fields": ["cell_id"],
        "measure_fields": [
            "road_length_km", "road_length_km_per_km2", "road_segment_count", "road_choice",
            "road_integration", "road_connectivity", "road_control", "road_depth",
        ],
    },
}


class SpatialEvidenceSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: Literal["poi.category", "poi.subcategory", "road.class", "year"]
    values: list[str | int] = Field(min_length=1, max_length=20)


class SpatialEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: Literal["scope", "distance", "direction", "neighborhood", "rank", "relationship", "inspect"]
    metric_ids: list[str] = Field(default_factory=list, max_length=4)
    selectors: list[SpatialEvidenceSelector] = Field(default_factory=list, max_length=8)
    distance_bands_m: list[tuple[float, float]] | None = Field(default=None, max_length=6)
    neighbor_steps: int = Field(default=1, ge=1, le=3)
    rank_order: Literal["highest", "lowest"] = "highest"
    top_k: int = Field(default=10, ge=1, le=20)
    record_refs: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_mode(self) -> "SpatialEvidenceRequest":
        count = len(self.metric_ids)
        if self.analysis in {"distance", "direction"} and not 1 <= count <= 4:
            raise ValueError(f"{self.analysis}_requires_1_to_4_metrics")
        if self.analysis == "rank" and count != 1:
            raise ValueError("rank_requires_exactly_1_metric")
        if self.analysis == "relationship" and not 2 <= count <= 4:
            raise ValueError("relationship_requires_2_to_4_metrics")
        if self.analysis == "neighborhood" and (not 1 <= count <= 4 or not self.record_refs):
            raise ValueError("neighborhood_requires_metrics_and_record_refs")
        if self.analysis == "inspect" and not self.record_refs:
            raise ValueError("inspect_requires_record_refs")
        if self.analysis not in {"neighborhood", "inspect"} and self.record_refs:
            raise ValueError("record_refs_only_supported_for_neighborhood_or_inspect")
        if self.distance_bands_m:
            previous_end = -1.0
            for start, end in self.distance_bands_m:
                if start < 0 or end <= start or start < previous_end:
                    raise ValueError("distance_bands_must_be_sorted_non_overlapping_positive_ranges")
                previous_end = end
        return self


@dataclass(frozen=True)
class MetricBinding:
    metric_id: str
    label: str
    unit: str
    source_ids: tuple[str, ...]
    fields: tuple[str, ...]
    aggregate: Literal["sum", "mean", "max", "p90", "ratio_positive"]
    h3_native: bool = False
    supported_analyses: tuple[str, ...] = (
        "scope",
        "distance",
        "direction",
        "neighborhood",
        "rank",
        "relationship",
        "inspect",
    )


@dataclass(frozen=True)
class CatalogScopeBinding:
    """Explicit range-summary strategy for catalog metrics not native to this API."""

    metric_id: str
    source_ids: tuple[str, ...]


def _binding(
    metric_id: str,
    label: str,
    unit: str,
    source_ids: Sequence[str],
    fields: Sequence[str],
    aggregate: Literal["sum", "mean", "max", "p90", "ratio_positive"],
    *,
    h3_native: bool = False,
    supported: Sequence[str] | None = None,
) -> MetricBinding:
    return MetricBinding(
        metric_id=metric_id,
        label=label,
        unit=unit,
        source_ids=tuple(source_ids),
        fields=tuple(fields),
        aggregate=aggregate,
        h3_native=h3_native,
        supported_analyses=tuple(supported or MetricBinding.__dataclass_fields__["supported_analyses"].default),
    )


_POI = "current:dataset:poi"
_H3 = "current:dataset:h3"
_POI_GRID = "current:dataset:poi_grid"
_POPULATION = "current:dataset:population"
_NIGHTLIGHT = "current:dataset:nightlight"
_ROAD_NODES = "current:dataset:road_nodes"
_ROAD_EDGES = "current:dataset:road_edges"
_ROAD_GRID = "current:dataset:road_grid"


METRIC_BINDINGS = {
    item.metric_id: item
    for item in [
        _binding("poi.count", "POI 数量", "places", [_POI], ["__count__"], "sum"),
        _binding("poi.category_count", "POI 分类数量", "places", [_POI], ["__count__"], "sum"),
        _binding("poi.grid_count", "网格 POI 数量", "places", [_POI_GRID, _H3, _POI], ["poi_count"], "sum"),
        _binding("poi.grid_density", "POI 网格密度", "places/km2", [_POI_GRID, _H3, _POI], ["density_poi_per_km2", "density"], "mean"),
        _binding("poi.category_density", "POI 分类密度", "places/km2", [_POI_GRID, _H3, _POI], ["__category_density__"], "mean"),
        _binding("population.total", "总人口", "person", [_POPULATION], ["population_total"], "sum"),
        _binding("population.age_structure", "人口年龄结构", "person", [_POPULATION], ["population_total"], "sum", supported=["scope", "inspect"]),
        _binding("nightlight.mean_radiance", "平均夜光辐亮度", "nW/(cm2 sr)", [_NIGHTLIGHT], ["radiance"], "mean"),
        _binding("nightlight.total_radiance", "夜光辐亮度总量", "nW/(cm2 sr)", [_NIGHTLIGHT], ["radiance"], "sum"),
        _binding("nightlight.max_radiance", "最大夜光辐亮度", "nW/(cm2 sr)", [_NIGHTLIGHT], ["radiance"], "max"),
        _binding("nightlight.p90", "夜光 P90", "nW/(cm2 sr)", [_NIGHTLIGHT], ["radiance"], "p90"),
        _binding("nightlight.lit_pixel_ratio", "亮灯单元比例", "ratio", [_NIGHTLIGHT], ["radiance"], "ratio_positive"),
        _binding("road.network_size", "路网长度", "m", [_ROAD_GRID, _ROAD_EDGES], ["road_length_km", "length_m"], "sum"),
        _binding("road.integration", "路网整合度", "index", [_ROAD_GRID, _ROAD_EDGES], ["road_integration", "metrics.integration"], "mean"),
        _binding("road.choice", "路网选择度", "index", [_ROAD_GRID, _ROAD_EDGES], ["road_choice", "metrics.choice"], "mean"),
        _binding("road.connectivity", "路网连通性", "index", [_ROAD_GRID, _ROAD_EDGES], ["road_connectivity", "metrics.connectivity"], "mean"),
        _binding("road.control", "路网控制值", "index", [_ROAD_GRID, _ROAD_EDGES], ["road_control", "metrics.control"], "mean"),
        _binding("road.mean_depth", "路网平均深度", "index", [_ROAD_GRID, _ROAD_EDGES], ["road_depth", "metrics.depth"], "mean"),
        _binding("road.degree", "路网节点度数", "connections", [_ROAD_NODES], ["degree"], "mean"),
        _binding("poi.local_entropy", "POI 局部混合熵", "index", [_H3], ["local_entropy"], "mean", h3_native=True),
        _binding("poi.neighbor_mean_density", "邻域平均 POI 密度", "places/km2", [_H3], ["neighbor_mean_density"], "mean", h3_native=True),
        _binding("poi.neighbor_mean_entropy", "邻域平均混合熵", "index", [_H3], ["neighbor_mean_entropy"], "mean", h3_native=True),
        _binding("poi.lq", "POI 区位商", "index", [_H3], ["lq"], "mean", h3_native=True),
        _binding("spatial.gi_star", "Getis-Ord Gi*", "z-score", [_H3], ["gi_star_z_score", "gi_star_value"], "mean", h3_native=True),
        _binding("spatial.lisa", "局部 Moran", "index", [_H3], ["lisa_i", "lisa_z_score"], "mean", h3_native=True),
        _binding("spatial.neighbor_density_delta", "网格相对邻域密度差", "places/km2", [_H3], ["__neighbor_delta__"], "mean", h3_native=True),
        _binding("grid.opportunity_flag", "网格空间条件标记", "boolean", [_H3], ["is_opportunity", "opportunity_flag"], "mean", h3_native=True),
    ]
}

# These metrics are executed by the existing domain metric executor, but are
# intentionally registered here one by one.  The model still sees only the
# semantic spatial-evidence contract; no alternate request shape is exposed.
CATALOG_SCOPE_BINDINGS = {
    item.metric_id: item
    for item in [
        CatalogScopeBinding("poi.multi_year_count", (_POI,)),
        CatalogScopeBinding("poi.local_entropy_normalized", (_POI_GRID, _H3, _POI)),
        CatalogScopeBinding("spatial.global_moran_i_density", (_H3, _POI_GRID)),
        CatalogScopeBinding("grid.type", (_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT, _ROAD_GRID)),
        CatalogScopeBinding("population.sex_structure", (_POPULATION,)),
        CatalogScopeBinding("population.selected_ratio", (_POPULATION,)),
        CatalogScopeBinding("nightlight.hotspot_class", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.hotspot_ratio", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.spatial_profile", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.sector_profile", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.activity_level", (_NIGHTLIGHT,)),
        CatalogScopeBinding("road.node_degree", (_ROAD_NODES, _ROAD_EDGES, _ROAD_GRID)),
        CatalogScopeBinding("road.orientation", (_ROAD_EDGES, _ROAD_GRID)),
        CatalogScopeBinding("road.intelligibility", (_ROAD_EDGES, _ROAD_GRID)),
        CatalogScopeBinding("isochrone.reachable_area", (_ROAD_EDGES,)),
        CatalogScopeBinding("timeseries.population_change", (_POPULATION,)),
        CatalogScopeBinding("timeseries.population_density_change", (_POPULATION,)),
        CatalogScopeBinding("timeseries.age_shift", (_POPULATION,)),
        CatalogScopeBinding("timeseries.nightlight_change", (_NIGHTLIGHT,)),
        CatalogScopeBinding("timeseries.hotspot_shift", (_NIGHTLIGHT,)),
        CatalogScopeBinding("gwr.nightlight_spatial_model", (_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT)),
        CatalogScopeBinding("gwr.model_fit", (_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT)),
        CatalogScopeBinding("poi.kernel_density", (_POI_GRID, _H3, _POI)),
        CatalogScopeBinding("poi.open_close_rate", (_POI,)),
        CatalogScopeBinding("access.network_reachable_area", (_ROAD_EDGES,)),
        CatalogScopeBinding("spatial.thematic_visual", ()),
        CatalogScopeBinding("report.decision_visual", ()),
        CatalogScopeBinding("regional.directional_evidence_matrix", (_POI, _POPULATION, _NIGHTLIGHT, _ROAD_EDGES, _ROAD_GRID)),
        CatalogScopeBinding("poi.supply_structure", (_POI, _ROAD_EDGES)),
        CatalogScopeBinding("poi.focused_accessibility", (_POI, _ROAD_EDGES)),
    ]
}


@dataclass
class _SpatialRow:
    record_ref: str
    source_id: str
    record_id: str
    title: str
    geometry: BaseGeometry
    centroid: tuple[float, float]
    distance_m: float
    direction: str
    area_km2: float
    values: dict[str, float | None]
    identity: dict[str, Any]


class _RecordIndex:
    def __init__(self, records: Sequence[ScopeRecord]) -> None:
        self.records = [record for record in records if record.geometry is not None and not record.geometry.is_empty]
        self.geometries = [record.geometry for record in self.records]
        self.tree = STRtree(self.geometries) if self.geometries else None

    def query(self, geometry: BaseGeometry) -> list[ScopeRecord]:
        if self.tree is None:
            return []
        return [self.records[int(index)] for index in self.tree.query(geometry)]


class SpatialEvidenceService:
    """One semantic spatial evidence interface over heterogeneous project datasets."""

    def __init__(
        self,
        *,
        projects: SpatialProjectService | None = None,
        metric_catalog: MetricToolService | None = None,
    ) -> None:
        self._projects = projects or SpatialProjectService()
        self._datasets = self._projects.datasets
        self._metric_catalog = metric_catalog

    def _catalog(self) -> MetricToolService:
        if self._metric_catalog is None:
            self._metric_catalog = MetricToolService()
        return self._metric_catalog

    def analyze(
        self,
        *,
        history_id: str,
        request: SpatialEvidenceRequest | Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_history_id = str(history_id or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        query = request if isinstance(request, SpatialEvidenceRequest) else SpatialEvidenceRequest.model_validate(request)
        project = self._projects.read_history_project(normalized_history_id)
        scope_geometry, center = self._scope_geometry(project)
        if scope_geometry is None:
            return self._unavailable(query, project, "当前项目没有可用的保存范围。")
        if center is None:
            return self._unavailable(query, project, "当前项目范围没有可解析的分析中心。")
        available = {
            str(item.get("source_id") or "")
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("status") or "") == "ready"
        }
        scope = self._scope_summary(project, scope_geometry, center)
        if query.analysis == "scope" and not query.metric_ids:
            return self._overview(query, project, scope, available)

        registered_metric_ids = set(METRIC_BINDINGS) | set(CATALOG_SCOPE_BINDINGS)
        unknown = sorted(set(query.metric_ids) - registered_metric_ids)
        if unknown:
            raise ValueError("unsupported_metric_ids:" + ",".join(unknown))
        catalog_scope_metrics = [metric_id for metric_id in query.metric_ids if metric_id in CATALOG_SCOPE_BINDINGS]
        unsupported = sorted(
            metric_id
            for metric_id in query.metric_ids
            if metric_id in METRIC_BINDINGS and query.analysis not in METRIC_BINDINGS[metric_id].supported_analyses
        )
        if unsupported:
            raise ValueError(f"metrics_not_supported_for_{query.analysis}:" + ",".join(unsupported))
        if catalog_scope_metrics:
            if query.analysis != "scope":
                return self._unavailable(
                    query,
                    project,
                    "目录指标已登记为范围汇总策略，不支持本次空间分组模式。",
                    scope=scope,
                )
            if len(catalog_scope_metrics) != len(query.metric_ids):
                raise ValueError("scope_mixed_native_and_catalog_metrics_not_supported")
            return self._catalog_scope_result(query, project, scope)

        records, years, warnings = self._load_records(normalized_history_id, available)
        missing_metrics = self._missing_metric_sources(query.metric_ids, records)
        if missing_metrics:
            return self._unavailable(
                query,
                project,
                "请求指标缺少可用数据集：" + ", ".join(missing_metrics),
                scope=scope,
            )
        if query.analysis == "scope":
            return self._scope_result(query, project, scope, records, years, warnings)
        if query.analysis == "inspect":
            return self._inspect_result(query, project, scope, records, years, warnings)

        base_source = self._base_source(query, records)
        base_records = records.get(base_source, []) if base_source else []
        if not base_source or not base_records:
            return self._unavailable(query, project, "当前数据无法形成该模式所需的可定位空间单元。", scope=scope)
        rows = self._spatial_rows(query, base_source, base_records, records, center, scope_geometry)
        if not rows:
            return self._unavailable(query, project, "当前范围内没有可用于本次分析的空间单元。", scope=scope)
        if query.analysis == "rank":
            return self._rank_result(query, project, scope, rows, years, warnings)
        if query.analysis == "neighborhood":
            return self._neighborhood_result(query, project, scope, rows, years, warnings)
        if query.analysis == "relationship":
            return self._relationship_result(query, project, scope, rows, years, warnings)
        return self._grouped_result(query, project, scope, rows, years, warnings)

    def _overview(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        available: set[str],
    ) -> dict[str, Any]:
        catalog = {item.tool_id: item for item in self._catalog().catalog()}
        metrics = []
        registered_metric_ids = set(METRIC_BINDINGS) | set(CATALOG_SCOPE_BINDINGS)
        metric_ids = [metric_id for metric_id in catalog if metric_id in registered_metric_ids]
        metric_ids.extend(metric_id for metric_id in METRIC_BINDINGS if metric_id not in catalog)
        for metric_id in metric_ids:
            binding = METRIC_BINDINGS.get(metric_id)
            item = catalog.get(metric_id)
            catalog_binding = CATALOG_SCOPE_BINDINGS.get(metric_id)
            source_ids = binding.source_ids if binding else (catalog_binding.source_ids if catalog_binding else ())
            data_status = "ready" if any(source in available for source in source_ids) else "unavailable"
            if catalog_binding and not source_ids:
                data_status = "ready"
            supported_analyses = list(binding.supported_analyses) if binding else ["scope"]
            analysis_profile = (
                "all"
                if supported_analyses == list(MetricBinding.__dataclass_fields__["supported_analyses"].default)
                else ",".join(supported_analyses)
            )
            metrics.append({
                "metric_id": metric_id,
                "available": data_status == "ready",
                "analyses": analysis_profile,
            })
        datasets = [
            {
                "dataset_id": DATASET_FIELD_CATALOG.get(str(item.get("source_id") or ""), {}).get("dataset_id", ""),
                "title": str(item.get("title") or ""),
                "year": item.get("selected_year"),
                "record_count": int(item.get("record_count") or 0),
                "status": str(item.get("status") or ""),
                "identity_fields": DATASET_FIELD_CATALOG.get(str(item.get("source_id") or ""), {}).get("identity_fields", []),
                "measure_fields": DATASET_FIELD_CATALOG.get(str(item.get("source_id") or ""), {}).get("measure_fields", []),
            }
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("source_id") or "") in DATASET_FIELD_CATALOG
        ]
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=metrics,
            summary={
                "catalog_metric_count": len(metrics),
                "available_metric_count": sum(item["available"] for item in metrics),
                "datasets": datasets,
            },
            coverage={"complete": True, "available_dataset_count": len(available)},
            limitations=[],
            method={"kind": "spatial_evidence_catalog", "scope_policy": "current_saved_scope_only"},
            provenance=self._provenance(project, {}, available),
        )

    def _catalog_scope_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
    ) -> dict[str, Any]:
        """Run explicitly registered catalog range strategies behind the semantic contract."""
        catalog = self._catalog()
        if not hasattr(catalog, "execute"):
            return self._unavailable(query, project, "目录执行器当前不可用。", scope=scope)
        source_index = SourceIndex(run_id=str(project.get("history_id") or ""), project_name=str(project.get("project_name") or ""))
        history_detail = dict(project)
        raw_scope = project.get("scope")
        if isinstance(raw_scope, Mapping):
            raw_scope = raw_scope.get("polygon") or raw_scope.get("coordinates")
        if isinstance(raw_scope, list):
            history_detail["polygon"] = raw_scope[0] if raw_scope and isinstance(raw_scope[0], list) and raw_scope[0] and isinstance(raw_scope[0][0], (list, tuple)) else raw_scope
        project_documents = {"project_name": project.get("project_name", ""), "documents": project.get("documents", [])}
        parameters = {"selectors": [selector.model_dump(mode="json") for selector in query.selectors]}
        summary: dict[str, Any] = {}
        evidence: list[dict[str, Any]] = []
        limitations: list[str] = []
        statuses: list[str] = []
        result_records: list[dict[str, Any]] = []
        used_sources: set[str] = set()
        for metric_id in query.metric_ids:
            item = next((entry for entry in catalog.catalog() if entry.tool_id == metric_id), None)
            if item is None:
                statuses.append("unavailable")
                limitations.append(f"目录中没有指标 {metric_id} 的执行定义。")
                continue
            try:
                result = catalog.execute(
                    tool_id=metric_id,
                    history_id=str(project.get("history_id") or ""),
                    history_detail=history_detail,
                    project_documents=project_documents,
                    source_index=source_index,
                    parameters=parameters,
                    project_anchors=project.get("params") if isinstance(project.get("params"), Mapping) else {},
                )
                status = str(result.status)
                statuses.append(status)
                structured = _compact_value(result.structured_result or {"summary": result.summary})
                if isinstance(structured, dict):
                    # Keep domain result metadata alongside the metric payload so saved
                    # isochrone responses remain auditable without exposing geometry.
                    structured.setdefault("result_id", result.result_id)
                    structured.setdefault("tool_id", result.tool_id)
                    structured.setdefault("tool_version", result.tool_version)
                    structured.setdefault("status", result.status)
                    structured.setdefault("input_sources", list(result.input_sources))
                    structured.setdefault("spatial_scope", _compact_value(result.spatial_scope))
                    structured.setdefault("time_scope", _compact_value(result.time_scope))
                    structured.setdefault("limitations", list(result.limitations))
                summary[metric_id] = structured
                used_sources.update(str(source) for source in result.input_sources if str(source).strip())
                result_records.append({
                    "metric_id": metric_id,
                    "result_id": result.result_id,
                    "tool_version": result.tool_version,
                    "status": result.status,
                    "input_sources": list(result.input_sources),
                    "spatial_scope": _compact_value(result.spatial_scope),
                    "time_scope": _compact_value(result.time_scope),
                })
                limitations.extend(str(value) for value in result.limitations if str(value).strip())
                evidence.append(self._evidence(project, query, f"metric:{metric_id}", [metric_id], [], summary[metric_id]))
            except (LookupError, ValueError, TypeError) as exc:
                statuses.append("unavailable")
                limitations.append(f"{metric_id} 执行不可用：{type(exc).__name__}。")
        status = "available" if any(value == "available" for value in statuses) else "unavailable"
        provenance = self._provenance(project, {}, used_sources)
        provenance["results"] = result_records
        provenance["data_versions"] = {
            str(item.get("source_id")): {
                str(key): item[key]
                for key in ("version", "dataset_version", "data_version", "selected_year", "snapshot_id")
                if item.get(key) not in (None, "")
            }
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("source_id") or "") in used_sources
        }
        params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        route_version = {
            str(key): params[key]
            for key in ("mode", "time_min", "road_version", "route_provider", "network_version", "data_version")
            if params.get(key) not in (None, "")
        }
        if route_version:
            provenance["analysis_parameters"] = route_version
        return self._response(
            query=query,
            project=project,
            scope=scope,
            status=status,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=summary,
            coverage={"complete": all(value == "available" for value in statuses), "metric_statuses": dict(zip(query.metric_ids, statuses))},
            evidence=evidence,
            limitations=limitations,
            method={
                "kind": "catalog_scope_strategy",
                "scope_policy": "current_saved_scope_only",
                "isochrone_mode": "scope + isochrone.reachable_area or access.network_reachable_area",
            },
            provenance=provenance,
        )

    def _scope_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        records: Mapping[str, list[ScopeRecord]],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        evidence: list[dict[str, Any]] = []
        highlights: list[dict[str, Any]] = []
        used_sources: set[str] = set()
        skipped = 0
        center = tuple(scope["center_wgs84"])
        for metric_id in query.metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            source_id = self._metric_source(binding, records, query)
            selected = self._selected_records(records.get(source_id, []), query.selectors, source_id)
            values = [self._direct_record_value(binding, record) for record in selected]
            numeric = [value for value in values if value is not None]
            skipped += len(values) - len(numeric)
            if binding.metric_id == "population.age_structure":
                summary[metric_id] = {
                    field: round(sum(_number(record.properties.get(field)) or 0.0 for record in selected), 6)
                    for field in ("population_total", "age_5_19", "age_30_39", "age_50_64")
                }
            else:
                summary[metric_id] = self._aggregate_values(binding, numeric)
            if source_id:
                used_sources.add(source_id)
            evidence.append(self._evidence(project, query, f"metric:{metric_id}", [metric_id], [], summary[metric_id]))
            remaining = max(0, query.top_k - len(highlights))
            for record in self._representative_records(binding, records, query)[:remaining]:
                row = self._row_from_record(record, center, [metric_id])
                if row is not None:
                    highlights.append(self._highlight(row, [metric_id], reason=f"{metric_id} 具名记录"))
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=summary,
            highlights=highlights,
            coverage={"complete": skipped == 0, "skipped_value_count": skipped},
            evidence=evidence,
            limitations=warnings,
            method={"kind": "current_scope_aggregate", "missing_values": "excluded_not_zero_filled"},
            provenance=self._provenance(project, years, used_sources),
        )

    def _representative_records(
        self,
        binding: MetricBinding,
        records: Mapping[str, list[ScopeRecord]],
        query: SpatialEvidenceRequest,
    ) -> list[ScopeRecord]:
        if binding.metric_id.startswith("poi.") and records.get(_POI):
            source_id = _POI
        elif binding.metric_id.startswith("road.") and records.get(_ROAD_EDGES):
            source_id = _ROAD_EDGES
        else:
            source_id = self._metric_source(binding, records, query)
        selected = self._selected_records(records.get(source_id, []), query.selectors, source_id)

        def sort_key(record: ScopeRecord) -> tuple[float, str, str]:
            value = self._direct_record_value(binding, record)
            if value is None and source_id == _POI and binding.metric_id.startswith("poi."):
                value = 1.0
            return (-(value if value is not None else float("-inf")), record.title, record.record_id)

        ordered = sorted(selected, key=sort_key)
        if source_id not in {_POI, _ROAD_EDGES}:
            return ordered
        distinct: list[ScopeRecord] = []
        seen_names: set[str] = set()
        identity_field = "name" if source_id == _POI else "road_name"
        named = [record for record in ordered if str(record.properties.get(identity_field) or "").strip()]
        for record in named or ordered:
            name = str(record.properties.get(identity_field) or record.title or record.record_id).strip()
            identity_key = name.casefold()
            if identity_key in seen_names:
                continue
            seen_names.add(identity_key)
            distinct.append(record)
        return distinct

    def _row_from_record(
        self,
        record: ScopeRecord,
        center: tuple[float, float],
        metric_ids: Sequence[str],
    ) -> _SpatialRow | None:
        geometry = record.geometry
        if geometry is None or geometry.is_empty:
            return None
        centroid = geometry.centroid
        if centroid.is_empty:
            return None
        distance, direction = _distance_direction(center, (centroid.x, centroid.y))
        values: dict[str, float | None] = {}
        for metric_id in metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            value = self._direct_record_value(binding, record) if record.source_id in binding.source_ids else None
            if value is None and record.source_id == _POI and metric_id.startswith("poi."):
                value = 1.0
            values[metric_id] = value
        return _SpatialRow(
            record_ref=self._record_ref(record),
            source_id=record.source_id,
            record_id=record.record_id,
            title=record.title,
            geometry=geometry,
            centroid=(centroid.x, centroid.y),
            distance_m=distance,
            direction=direction,
            area_km2=_area_km2(geometry),
            values=values,
            identity=self._record_identity(record),
        )

    def _grouped_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        rows: list[_SpatialRow],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        groups: list[dict[str, Any]] = []
        if query.analysis == "distance":
            bands = tuple(query.distance_bands_m or DEFAULT_DISTANCE_BANDS_M)
            for start, end in bands:
                members = [row for row in rows if start <= row.distance_m < end]
                groups.append(self._group_payload(f"{int(start)}-{int(end)}m", members, query.metric_ids))
        else:
            for direction in DIRECTION_CODES:
                members = [row for row in rows if row.direction == direction]
                payload = self._group_payload(direction, members, query.metric_ids)
                payload["label"] = DIRECTION_LABELS[direction]
                groups.append(payload)
        evidence = [
            self._evidence(project, query, f"group:{group['key']}", query.metric_ids, [], group["values"])
            for group in groups
        ]
        primary_metric = query.metric_ids[0]
        representative_rows = sorted(
            (row for row in rows if row.values.get(primary_metric) is not None),
            key=lambda row: (-float(row.values[primary_metric]), row.record_ref),
        )[: query.top_k]
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=self._group_payload("overall", rows, query.metric_ids)["values"],
            groups=groups[:32],
            highlights=[
                self._highlight(row, query.metric_ids, reason=f"{query.analysis} 中 {primary_metric} 高值记录")
                for row in representative_rows
            ],
            coverage=self._row_coverage(rows, query.metric_ids),
            evidence=evidence[:32],
            limitations=warnings,
            method={
                "kind": f"{query.analysis}_grouping",
                "direction_sectors": 8 if query.analysis == "direction" else None,
                "distance_bands_m": [list(value) for value in (query.distance_bands_m or DEFAULT_DISTANCE_BANDS_M)],
                "missing_values": "excluded_not_zero_filled",
            },
            provenance=self._provenance(project, years, {row.source_id for row in rows}),
        )

    def _rank_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        rows: list[_SpatialRow],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        metric_id = query.metric_ids[0]
        valid = [row for row in rows if row.values.get(metric_id) is not None]
        valid.sort(key=lambda row: float(row.values[metric_id]), reverse=query.rank_order == "highest")
        highlights = [self._highlight(row, query.metric_ids, reason=f"{metric_id} {query.rank_order}") for row in valid[: query.top_k]]
        evidence = [
            self._evidence(project, query, f"record:{row.record_ref}", [metric_id], [row.record_ref], row.values)
            for row in valid[: query.top_k]
        ]
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary={"ranked_metric": metric_id, "order": query.rank_order, "valid_record_count": len(valid)},
            highlights=highlights,
            coverage=self._row_coverage(rows, query.metric_ids),
            evidence=evidence,
            limitations=warnings,
            method={"kind": "single_metric_rank", "normalization": "none", "combined_score": False},
            provenance=self._provenance(project, years, {row.source_id for row in rows}),
        )

    def _neighborhood_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        rows: list[_SpatialRow],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        targets = [row for row in rows if self._matches_ref(row.record_ref, query.record_refs)]
        groups = []
        highlights = []
        for target in targets[:20]:
            neighborhood = {target.record_ref: target}
            frontier = [target]
            for _ in range(query.neighbor_steps):
                next_frontier = []
                for candidate in rows:
                    if candidate.record_ref in neighborhood:
                        continue
                    if any(self._neighbors(item, candidate, query.neighbor_steps) for item in frontier):
                        neighborhood[candidate.record_ref] = candidate
                        next_frontier.append(candidate)
                frontier = next_frontier
            members = list(neighborhood.values())
            payload = self._group_payload(target.record_ref, members, query.metric_ids)
            payload["target_values"] = dict(target.values)
            payload["neighbor_count"] = max(0, len(members) - 1)
            groups.append(payload)
            highlights.append(self._highlight(target, query.metric_ids, reason=f"{query.neighbor_steps}级邻域目标"))
        if not targets:
            return self._unavailable(query, project, "指定 record_refs 不属于本次分析空间单元。", scope=scope)
        evidence = [
            self._evidence(project, query, f"neighborhood:{group['key']}", query.metric_ids, [group["key"]], group["values"])
            for group in groups
        ]
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary={"target_count": len(targets), "neighbor_steps": query.neighbor_steps},
            groups=groups,
            highlights=highlights,
            coverage=self._row_coverage(rows, query.metric_ids),
            evidence=evidence,
            limitations=warnings,
            method={"kind": "geometry_adjacency", "neighbor_steps": query.neighbor_steps},
            provenance=self._provenance(project, years, {row.source_id for row in rows}),
        )

    @staticmethod
    def _neighbors(left: _SpatialRow, right: _SpatialRow, steps: int) -> bool:
        """Use H3's canonical k-ring when both records expose H3 cell IDs."""
        if left.source_id == _H3 and right.source_id == _H3:
            try:
                import h3

                cell = str(left.record_id)
                if hasattr(h3, "grid_disk"):
                    return str(right.record_id) in {str(item) for item in h3.grid_disk(cell, steps)}
                if hasattr(h3, "k_ring"):
                    return str(right.record_id) in {str(item) for item in h3.k_ring(cell, steps)}
            except (ImportError, ValueError, TypeError):
                pass
        return left.geometry.buffer(1e-12).intersects(right.geometry.buffer(1e-12))

    def _relationship_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        rows: list[_SpatialRow],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        complete = [row for row in rows if all(row.values.get(metric_id) is not None for metric_id in query.metric_ids)]
        if len(complete) < 20:
            return self._unavailable(
                query,
                project,
                f"共同有效空间单元只有 {len(complete)} 个，少于关系分析要求的 20 个。",
                scope=scope,
            )
        thresholds = {
            metric_id: {
                "p25": _quantile([float(row.values[metric_id]) for row in complete], 0.25),
                "p75": _quantile([float(row.values[metric_id]) for row in complete], 0.75),
            }
            for metric_id in query.metric_ids
        }
        patterns = {"joint_high": [], "joint_low": [], "conflict": [], "middle": []}
        for row in complete:
            states = []
            for metric_id in query.metric_ids:
                value = float(row.values[metric_id])
                threshold = thresholds[metric_id]
                states.append("high" if value >= threshold["p75"] else "low" if value <= threshold["p25"] else "middle")
            pattern = "joint_high" if all(state == "high" for state in states) else "joint_low" if all(state == "low" for state in states) else "conflict" if "high" in states and "low" in states else "middle"
            patterns[pattern].append(row)
        relationship = {
            "spatial_unit_count": len(complete),
            "thresholds": thresholds,
            "pattern_counts": {key: len(value) for key, value in patterns.items()},
            "correlation_computed": False,
            "combined_score_computed": False,
        }
        highlighted = (patterns["joint_high"] + patterns["conflict"] + patterns["joint_low"])[: query.top_k]
        highlights = [
            self._highlight(row, query.metric_ids, reason=next(key for key, values in patterns.items() if row in values))
            for row in highlighted
        ]
        evidence = [
            self._evidence(project, query, f"relationship:{key}", query.metric_ids, [row.record_ref for row in values[: query.top_k]], {"count": len(values)})
            for key, values in patterns.items()
        ]
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary={"common_valid_cell_count": len(complete)},
            highlights=highlights,
            relationship=relationship,
            coverage=self._row_coverage(rows, query.metric_ids),
            evidence=evidence,
            limitations=warnings + ["分位共位仅描述空间共同出现，不表示因果关系。"],
            method={"kind": "p25_p75_colocation", "correlation": False, "combined_score": False},
            provenance=self._provenance(project, years, {row.source_id for row in rows}),
        )

    def _inspect_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        records: Mapping[str, list[ScopeRecord]],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        center = tuple(scope["center_wgs84"])
        matches = [
            record
            for values in records.values()
            for record in values
            if self._matches_ref(self._record_ref(record), query.record_refs)
        ][:20]
        highlights = []
        evidence = []
        for record in matches:
            centroid = record.geometry.centroid if record.geometry is not None else None
            if centroid is None or centroid.is_empty:
                continue
            distance, direction = _distance_direction(center, (centroid.x, centroid.y))
            values = {}
            for metric_id in query.metric_ids:
                binding = METRIC_BINDINGS[metric_id]
                values[metric_id] = self._direct_record_value(binding, record) if record.source_id in binding.source_ids else None
            row = _SpatialRow(
                record_ref=self._record_ref(record), source_id=record.source_id, record_id=record.record_id,
                title=record.title, geometry=record.geometry, centroid=(centroid.x, centroid.y), distance_m=distance,
                direction=direction, area_km2=_area_km2(record.geometry), values=values,
                identity=self._record_identity(record),
            )
            highlights.append(self._highlight(row, query.metric_ids, reason="指定空间记录"))
            evidence.append(self._evidence(project, query, f"record:{row.record_ref}", query.metric_ids, [row.record_ref], values))
        remaining = max(0, min(20, query.top_k) - len(highlights))
        grid_sources = {_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT, _ROAD_GRID}
        for target in matches:
            if remaining <= 0 or target.source_id not in grid_sources:
                continue
            for related, relation in self._named_relations(target, records, limit=remaining):
                row = self._row_from_record(related, center, query.metric_ids)
                if row is None:
                    continue
                highlight = self._highlight(row, query.metric_ids, reason="目标单元具名空间关系")
                highlight["relation_to_target"] = {
                    "target_record_ref": self._record_ref(target),
                    "kind": relation,
                }
                highlights.append(highlight)
                evidence.append(
                    self._evidence(
                        project,
                        query,
                        f"relation:{self._record_ref(target)}:{row.record_ref}",
                        query.metric_ids,
                        [self._record_ref(target), row.record_ref],
                        {"relation": relation, "values": row.values},
                    )
                )
                remaining -= 1
                if remaining <= 0:
                    break
        if not highlights:
            return self._unavailable(query, project, "没有找到指定的空间记录。", scope=scope)
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary={
                "matched_record_count": len(matches),
                "related_named_record_count": max(0, len(highlights) - len(matches)),
            },
            highlights=highlights,
            coverage={"complete": len(matches) == len(query.record_refs), "matched_record_count": len(matches)},
            evidence=evidence,
            limitations=warnings,
            method={
                "kind": "stable_record_lookup_with_named_relations",
                "relations": ["contained_poi", "intersecting_road", "nearest_poi", "nearest_road"],
                "geometry_returned": False,
            },
            provenance=self._provenance(project, years, {record.source_id for record in matches}),
        )

    def _named_relations(
        self,
        target: ScopeRecord,
        records: Mapping[str, list[ScopeRecord]],
        *,
        limit: int,
    ) -> list[tuple[ScopeRecord, str]]:
        """Project a grid target to bounded, named POI and road facts."""
        geometry = target.geometry
        if geometry is None or geometry.is_empty or limit <= 0:
            return []

        poi_records = [
            record
            for record in records.get(_POI, [])
            if record.geometry is not None
            and not record.geometry.is_empty
            and str(record.properties.get("name") or record.title or "").strip()
        ]
        road_records = [
            record
            for record in records.get(_ROAD_EDGES, [])
            if record.geometry is not None
            and not record.geometry.is_empty
            and str(record.properties.get("road_name") or record.title or "").strip()
        ]
        related: list[tuple[ScopeRecord, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(record: ScopeRecord, relation: str) -> None:
            identity = str(
                record.properties.get("name")
                or record.properties.get("road_name")
                or record.title
                or record.record_id
            ).strip().casefold()
            key = (record.source_id, identity)
            if not identity or key in seen or len(related) >= limit:
                return
            seen.add(key)
            related.append((record, relation))

        for record in sorted(poi_records, key=lambda item: (item.title, item.record_id)):
            if geometry.intersects(record.geometry):
                add(record, "contained_poi")
        for record in sorted(road_records, key=lambda item: (str(item.properties.get("road_name") or item.title), item.record_id)):
            if geometry.intersects(record.geometry):
                add(record, "intersecting_road")

        # Fill any remaining response capacity with the closest named context.
        # This is a deterministic fact projection, not a recommendation to query further.
        if len(related) < limit:
            for record in sorted(poi_records, key=lambda item: (geometry.distance(item.geometry), item.title, item.record_id)):
                if geometry.intersects(record.geometry):
                    continue
                add(record, "nearest_poi")
                if len(related) >= limit:
                    break
        if len(related) < limit:
            for record in sorted(road_records, key=lambda item: (geometry.distance(item.geometry), str(item.properties.get("road_name") or item.title), item.record_id)):
                if geometry.intersects(record.geometry):
                    continue
                add(record, "nearest_road")
                if len(related) >= limit:
                    break
        return related

    def _spatial_rows(
        self,
        query: SpatialEvidenceRequest,
        base_source: str,
        base_records: Sequence[ScopeRecord],
        records: Mapping[str, list[ScopeRecord]],
        center: tuple[float, float],
        scope_geometry: BaseGeometry,
    ) -> list[_SpatialRow]:
        selected_by_source = {
            source_id: self._selected_records(values, query.selectors, source_id)
            for source_id, values in records.items()
        }
        indexes = {source_id: _RecordIndex(values) for source_id, values in selected_by_source.items()}
        rows = []
        for base in base_records:
            geometry = base.geometry
            if geometry is None or geometry.is_empty or not geometry.intersects(scope_geometry):
                continue
            centroid = geometry.centroid
            distance, direction = _distance_direction(center, (centroid.x, centroid.y))
            values: dict[str, float | None] = {}
            for metric_id in query.metric_ids:
                binding = METRIC_BINDINGS[metric_id]
                source_id = self._metric_source(binding, selected_by_source, query)
                candidates = indexes.get(source_id, _RecordIndex([])).query(geometry)
                values[metric_id] = self._value_for_unit(binding, geometry, candidates)
            rows.append(_SpatialRow(
                record_ref=self._record_ref(base), source_id=base_source, record_id=base.record_id,
                title=base.title, geometry=geometry, centroid=(centroid.x, centroid.y), distance_m=distance,
                direction=direction, area_km2=_area_km2(geometry), values=values,
                identity=self._record_identity(base),
            ))
        return rows

    def _value_for_unit(self, binding: MetricBinding, unit: BaseGeometry, candidates: Sequence[ScopeRecord]) -> float | None:
        if not candidates:
            return None
        if binding.source_ids[0] == _POI or all(record.geometry is not None and record.geometry.geom_type == "Point" for record in candidates):
            included = [record for record in candidates if record.geometry is not None and unit.covers(record.geometry)]
            if binding.metric_id in {"poi.count", "poi.category_count", "poi.grid_count"}:
                return float(len(included))
            if binding.metric_id in {"poi.grid_density", "poi.category_density"}:
                area = _area_km2(unit)
                return float(len(included)) / area if area > 0 else None
        weighted: list[tuple[float, float]] = []
        contributions: list[float] = []
        for record in candidates:
            if record.geometry is None or not unit.intersects(record.geometry):
                continue
            value = self._direct_record_value(binding, record)
            if value is None:
                continue
            intersection = unit.intersection(record.geometry)
            if intersection.is_empty:
                continue
            if record.geometry.geom_type in {"LineString", "MultiLineString"}:
                weight = float(intersection.length)
                fraction = weight / float(record.geometry.length) if record.geometry.length > 0 else 0.0
            else:
                weight = float(intersection.area)
                fraction = weight / float(record.geometry.area) if record.geometry.area > 0 else 0.0
            if binding.aggregate == "sum":
                if binding.metric_id == "road.network_size" and record.source_id == _ROAD_GRID:
                    contributions.append(value * 1000.0 * fraction)
                else:
                    contributions.append(value * fraction)
            else:
                weighted.append((value, weight if weight > 0 else 1.0))
        if binding.aggregate == "sum":
            return sum(contributions) if contributions else None
        if not weighted:
            return None
        if binding.aggregate == "max":
            return max(value for value, _ in weighted)
        if binding.aggregate == "p90":
            return _quantile([value for value, _ in weighted], 0.9)
        if binding.aggregate == "ratio_positive":
            return sum(1 for value, _ in weighted if value > 0) / len(weighted)
        total_weight = sum(weight for _, weight in weighted)
        return sum(value * weight for value, weight in weighted) / total_weight if total_weight > 0 else None

    def _direct_record_value(self, binding: MetricBinding, record: ScopeRecord) -> float | None:
        if binding.fields == ("__count__",):
            return 1.0
        if binding.fields == ("__category_density__",):
            counts = record.properties.get("category_counts")
            if isinstance(counts, Mapping):
                total = sum(_number(value) or 0.0 for value in counts.values())
                area = _number(record.properties.get("area_km2")) or (_area_km2(record.geometry) if record.geometry else 0.0)
                return total / area if area > 0 else None
            return None
        if binding.fields == ("__neighbor_delta__",):
            density = _number(record.properties.get("density_poi_per_km2") or record.properties.get("density"))
            neighbor = _number(record.properties.get("neighbor_mean_density"))
            return density - neighbor if density is not None and neighbor is not None else None
        for field in binding.fields:
            value: Any = record.properties
            for part in field.split("."):
                value = value.get(part) if isinstance(value, Mapping) else None
            numeric = _number(value)
            if numeric is not None:
                if binding.metric_id == "road.network_size" and field == "road_length_km":
                    return numeric * 1000.0
                return numeric
        return None

    def _selected_records(
        self,
        records: Sequence[ScopeRecord],
        selectors: Sequence[SpatialEvidenceSelector],
        source_id: str,
    ) -> list[ScopeRecord]:
        selected = list(records)
        for selector in selectors:
            expected = {str(value) for value in selector.values}
            if selector.dimension == "year":
                selected = [record for record in selected if str(record.properties.get("year") or record.time_scope.get("year") or "") in expected]
            elif selector.dimension == "poi.category" and source_id == _POI:
                selected = [record for record in selected if str(record.properties.get("category") or "") in expected]
            elif selector.dimension == "poi.subcategory" and source_id == _POI:
                selected = [record for record in selected if str(record.properties.get("subcategory") or "") in expected]
            elif selector.dimension == "road.class" and source_id == _ROAD_EDGES:
                selected = [record for record in selected if str(record.properties.get("road_class") or "") in expected]
        return selected

    def _load_records(
        self,
        history_id: str,
        available: set[str],
    ) -> tuple[dict[str, list[ScopeRecord]], dict[str, int | None], list[str]]:
        records: dict[str, list[ScopeRecord]] = {}
        years: dict[str, int | None] = {}
        warnings: list[str] = []
        for source_id in (_POI, _H3, _POI_GRID, _POPULATION, _NIGHTLIGHT, _ROAD_NODES, _ROAD_EDGES, _ROAD_GRID):
            if source_id not in available:
                continue
            try:
                values, _, selected_year = self._datasets.load_scope_records(
                    history_id=history_id,
                    source_id=source_id,
                    require_geometry_metadata=True,
                )
            except (LookupError, ValueError) as exc:
                warnings.append(f"{source_id}:{exc}")
                continue
            records[source_id] = values
            years[source_id] = selected_year
            warnings.extend(warning for record in values for warning in record.warnings)
        return records, years, sorted(set(warnings))

    @staticmethod
    def _missing_metric_sources(
        metric_ids: Sequence[str], records: Mapping[str, Sequence[ScopeRecord]]
    ) -> list[str]:
        return [
            metric_id
            for metric_id in metric_ids
            if not any(records.get(source_id) for source_id in METRIC_BINDINGS[metric_id].source_ids)
        ]

    def _base_source(self, query: SpatialEvidenceRequest, records: Mapping[str, list[ScopeRecord]]) -> str:
        bindings = [METRIC_BINDINGS[metric_id] for metric_id in query.metric_ids]
        if any(binding.h3_native for binding in bindings) and records.get(_H3):
            return _H3
        if query.analysis == "neighborhood":
            for source_id, values in records.items():
                if any(self._matches_ref(self._record_ref(record), query.record_refs) for record in values):
                    return source_id
        if query.analysis == "rank" and bindings:
            for source_id in bindings[0].source_ids:
                if records.get(source_id) and source_id not in {_POI, _ROAD_NODES, _ROAD_EDGES}:
                    return source_id
        for source_id in (_POPULATION, _NIGHTLIGHT, _POI_GRID, _ROAD_GRID, _H3):
            if records.get(source_id):
                return source_id
        if bindings:
            return next((source for source in bindings[0].source_ids if records.get(source)), "")
        return ""

    @staticmethod
    def _metric_source(binding: MetricBinding, records: Mapping[str, Sequence[ScopeRecord]], query: SpatialEvidenceRequest) -> str:
        dimensions = {selector.dimension for selector in query.selectors}
        if binding.metric_id.startswith("poi.") and dimensions & {"poi.category", "poi.subcategory"} and records.get(_POI):
            return _POI
        if binding.metric_id.startswith("road.") and "road.class" in dimensions and records.get(_ROAD_EDGES):
            return _ROAD_EDGES
        return next((source_id for source_id in binding.source_ids if records.get(source_id)), "")

    @staticmethod
    def _group_payload(key: str, rows: Sequence[_SpatialRow], metric_ids: Sequence[str]) -> dict[str, Any]:
        values = {}
        for metric_id in metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            numeric = [float(row.values[metric_id]) for row in rows if row.values.get(metric_id) is not None]
            values[metric_id] = SpatialEvidenceService._aggregate_values(binding, numeric)
        return {"key": key, "cell_count": len(rows), "values": values}

    @staticmethod
    def _aggregate_values(binding: MetricBinding, values: Sequence[float]) -> float | None:
        if not values:
            return None
        if binding.aggregate == "sum":
            return round(sum(values), 6)
        if binding.aggregate == "max":
            return round(max(values), 6)
        if binding.aggregate == "p90":
            return round(_quantile(values, 0.9), 6)
        if binding.aggregate == "ratio_positive":
            return round(sum(1 for value in values if value > 0) / len(values), 6)
        return round(sum(values) / len(values), 6)

    @staticmethod
    def _metric_descriptors(metric_ids: Sequence[str]) -> list[dict[str, Any]]:
        return [
            {
                "metric_id": metric_id,
                "label": METRIC_BINDINGS[metric_id].label if metric_id in METRIC_BINDINGS else metric_id,
                "unit": METRIC_BINDINGS[metric_id].unit if metric_id in METRIC_BINDINGS else "catalog_result",
            }
            for metric_id in metric_ids
        ]

    @staticmethod
    def _row_coverage(rows: Sequence[_SpatialRow], metric_ids: Sequence[str]) -> dict[str, Any]:
        valid = {metric_id: sum(row.values.get(metric_id) is not None for row in rows) for metric_id in metric_ids}
        return {
            "complete": all(count == len(rows) for count in valid.values()),
            "spatial_unit_count": len(rows),
            "valid_value_count": valid,
            "missing_values": "excluded_not_zero_filled",
        }

    @staticmethod
    def _highlight(row: _SpatialRow, metric_ids: Sequence[str], *, reason: str) -> dict[str, Any]:
        return {
            "record_ref": row.record_ref,
            "title": row.title,
            "identity": row.identity,
            "centroid_wgs84": [round(row.centroid[0], 6), round(row.centroid[1], 6)],
            "distance_m": round(row.distance_m, 1),
            "direction": row.direction,
            "values": {metric_id: _rounded(row.values.get(metric_id)) for metric_id in metric_ids},
            "reason": reason,
        }

    @staticmethod
    def _record_identity(record: ScopeRecord) -> dict[str, Any]:
        descriptor = DATASET_FIELD_CATALOG.get(record.source_id, {})
        identity: dict[str, Any] = {
            "dataset_id": descriptor.get("dataset_id", "spatial_record"),
            "display_name": record.title,
        }
        for field_name in descriptor.get("identity_fields", []):
            value: Any = record.properties
            for part in str(field_name).split("."):
                value = value.get(part) if isinstance(value, Mapping) else None
            if value not in (None, "", []):
                identity[str(field_name)] = value
        cleaned = _safe_value(identity)
        return cleaned if isinstance(cleaned, dict) else {"display_name": record.title}

    @staticmethod
    def _scope_summary(project: Mapping[str, Any], geometry: BaseGeometry, center: tuple[float, float]) -> dict[str, Any]:
        return {
            "scope_ref": "current",
            "scope_type": str((project.get("params") or {}).get("scope_type") or "saved_project_scope"),
            "center_wgs84": [round(center[0], 6), round(center[1], 6)],
            "area_km2": round(_area_km2(geometry), 6),
            "geometry_returned": False,
        }

    @staticmethod
    def _scope_geometry(project: Mapping[str, Any]) -> tuple[BaseGeometry | None, tuple[float, float] | None]:
        raw_scope: Any = project.get("scope")
        if isinstance(raw_scope, Mapping):
            raw_scope = raw_scope.get("polygon") or raw_scope.get("geometry") or raw_scope
        if isinstance(raw_scope, list):
            coordinates = raw_scope
            if coordinates and all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in coordinates):
                coordinates = [coordinates]
            raw_scope = {"type": "Polygon", "coordinates": coordinates}
        try:
            geometry = shape(raw_scope) if isinstance(raw_scope, Mapping) else None
        except (TypeError, ValueError):
            geometry = None
        if geometry is None or geometry.is_empty:
            return None, None
        params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        declared = str(params.get("coord_type") or params.get("coordinate_system") or "wgs84").lower()
        if declared == "gcj02":
            geometry = transform(lambda x, y, z=None: gcj02_to_wgs84(float(x), float(y)), geometry)
        raw_center = params.get("center")
        center = None
        if isinstance(raw_center, (list, tuple)) and len(raw_center) >= 2:
            try:
                center = (float(raw_center[0]), float(raw_center[1]))
                if declared == "gcj02":
                    center = gcj02_to_wgs84(*center)
            except (TypeError, ValueError):
                center = None
        if center is None:
            centroid = geometry.centroid
            center = (float(centroid.x), float(centroid.y)) if not centroid.is_empty else None
        return geometry, center

    @staticmethod
    def _record_ref(record: ScopeRecord) -> str:
        return f"{record.source_id}/{record.record_id}"

    @staticmethod
    def _matches_ref(record_ref: str, requested: Sequence[str]) -> bool:
        return record_ref in requested

    def _evidence(
        self,
        project: Mapping[str, Any],
        query: SpatialEvidenceRequest,
        key: str,
        metric_ids: Sequence[str],
        record_refs: Sequence[str],
        content: Any,
    ) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        evidence_id = "spatial:" + _digest({"snapshot_id": snapshot_id, "analysis": query.analysis, "key": key, "metrics": list(metric_ids), "content": content})[:24]
        return {
            "evidence_id": evidence_id,
            "title": "项目空间证据",
            "source_type": "project_spatial_evidence",
            "source_locator": f"spatial_evidence:{snapshot_id}:{query.analysis}:{key}",
            "metric_ids": list(metric_ids),
            "record_refs": list(record_refs)[:20],
            "content": _safe_value(content),
        }

    @staticmethod
    def _provenance(project: Mapping[str, Any], years: Mapping[str, int | None], source_ids: Iterable[str]) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        sources = sorted(source_id for source_id in source_ids if source_id)
        return {
            "snapshot_id": snapshot_id,
            "source_ids": sources,
            "selected_years": {source_id: years.get(source_id) for source_id in sources},
            "result_checksum": "sha256:" + _digest({"snapshot_id": snapshot_id, "sources": sources, "years": dict(years)}),
        }

    def _unavailable(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        limitation: str,
        *,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._response(
            query=query,
            project=project,
            scope=scope or {},
            status="unavailable",
            metrics=self._metric_descriptors(query.metric_ids),
            coverage={"complete": False},
            limitations=[limitation],
            method={"kind": query.analysis, "executed": False},
            provenance=self._provenance(project, {}, set()),
        )

    @staticmethod
    def _response(
        *,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        status: Literal["available", "unavailable", "failed"] = "available",
        metrics: list[dict[str, Any]] | None = None,
        summary: dict[str, Any] | None = None,
        groups: list[dict[str, Any]] | None = None,
        highlights: list[dict[str, Any]] | None = None,
        relationship: dict[str, Any] | None = None,
        coverage: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        limitations: list[str] | None = None,
        method: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "analysis": query.analysis,
            "scope": scope,
            "metrics": metrics or [],
            "summary": summary or {},
            "groups": groups or [],
            "highlights": highlights or [],
            "relationship": relationship or {},
            "coverage": coverage or {},
            "evidence": evidence or [],
            "limitations": list(dict.fromkeys(str(item) for item in (limitations or []) if str(item).strip())),
            "method": method or {},
            "provenance": provenance or {},
        }
        return _bounded_model_response(response)


def _safe_value(value: Any, *, key: str = "") -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            normalized_key = str(raw_key).lower()
            if normalized_key in FORBIDDEN_OUTPUT_KEYS:
                continue
            cleaned = _safe_value(item, key=normalized_key)
            if cleaned is not _OMIT:
                result[str(raw_key)] = cleaned
        return result
    if isinstance(value, (list, tuple)):
        limit = 80 if key == "metrics" else MODEL_LIST_ITEM_LIMIT
        cleaned = [_safe_value(item, key=key) for item in list(value)[:limit]]
        return [item for item in cleaned if item is not _OMIT]
    if isinstance(value, str):
        if _looks_like_geometry_string(value):
            return _OMIT
        return value[:MODEL_STRING_CHAR_LIMIT]
    return value


class _OmitValue:
    pass


_OMIT = _OmitValue()


def _looks_like_geometry_string(value: str) -> bool:
    """Reject serialized GeoJSON/WKT even when it is hidden inside a string."""
    normalized = value.strip().lower()
    if not normalized:
        return False
    has_geometry_key = any(
        marker in normalized
        for marker in ('"geometry"', "'geometry'", '"coordinates"', "'coordinates'", '"features"', "'features'")
    )
    has_geometry_type = any(
        token in normalized
        for token in ("polygon", "multipolygon", "linestring", "multilinestring", "point", "multipoint")
    )
    return (
        normalized.startswith(("polygon(", "multipolygon(", "linestring(", "multilinestring(", "point(", "multipoint("))
        or has_geometry_key and has_geometry_type
        or ('"type"' in normalized or "'type'" in normalized) and has_geometry_type
        or normalized.startswith(("{\"type\":", "{ 'type':"))
    )


def _bounded_model_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Project a spatial result into a small, geometry-free model response."""
    projected = _safe_value(response)
    if not isinstance(projected, dict):
        return {"status": "unavailable", "limitations": ["空间结果投影失败。"]}

    for key, limit in (("groups", 12), ("highlights", 20), ("evidence", 20)):
        if isinstance(projected.get(key), list):
            projected[key] = projected[key][:limit]
    if isinstance(projected.get("evidence"), list):
        for item in projected["evidence"]:
            if isinstance(item, dict) and isinstance(item.get("content"), (dict, list)):
                item["content"] = _safe_value(item["content"])

    def serialized_size() -> int:
        return len(json.dumps(projected, ensure_ascii=False, separators=(",", ":"), default=str))

    # Trim the least useful payloads first while preserving the response contract.
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT and isinstance(projected.get("evidence"), list):
        for item in projected["evidence"]:
            if isinstance(item, dict) and "content" in item:
                item["content"] = str(item["content"])[:240]
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT and isinstance(projected.get("highlights"), list):
        projected["highlights"] = projected["highlights"][:10]
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT and isinstance(projected.get("groups"), list):
        projected["groups"] = projected["groups"][:8]
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT:
        original_method = projected.get("method") or {}
        projected["method"] = {
            key: original_method[key]
            for key in ("kind", "direction_sectors", "distance_bands_m", "neighbor_steps", "missing_values", "combined_score")
            if key in original_method
        }
        projected["method"].setdefault("kind", "spatial_evidence")
        projected["provenance"] = {"snapshot_id": str((projected.get("provenance") or {}).get("snapshot_id", ""))}
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT:
        projected["summary"] = {"message": "空间结果已压缩，请根据已返回的分组和高亮记录判断。"}
    return projected


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    """Bound catalog payloads before they enter the model context."""
    if depth >= 3:
        return str(value)[:1000]
    if isinstance(value, Mapping):
        return {str(key): _compact_value(item, depth=depth + 1) for key, item in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_compact_value(item, depth=depth + 1) for item in list(value)[:20]]
    if isinstance(value, str):
        return value[:4000]
    return value


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None else None


def _quantile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("quantile_requires_values")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def _distance_direction(origin: tuple[float, float], target: tuple[float, float]) -> tuple[float, str]:
    lon0, lat0 = origin
    lon, lat = target
    latitude = math.radians((lat0 + lat) / 2.0)
    dx = (lon - lon0) * 111_320.0 * math.cos(latitude)
    dy = (lat - lat0) * 110_574.0
    distance = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dx, dy)) % 360.0
    direction = DIRECTION_CODES[int((bearing + 22.5) // 45.0) % len(DIRECTION_CODES)]
    return distance, direction


def _area_km2(geometry: BaseGeometry | None) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    centroid = geometry.centroid
    scale_x = 111.32 * math.cos(math.radians(float(centroid.y)))
    scale_y = 110.574
    return abs(float(geometry.area)) * scale_x * scale_y


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "CATALOG_SCOPE_BINDINGS",
    "METRIC_BINDINGS",
    "SCHEMA_VERSION",
    "SpatialEvidenceRequest",
    "SpatialEvidenceSelector",
    "SpatialEvidenceService",
]
