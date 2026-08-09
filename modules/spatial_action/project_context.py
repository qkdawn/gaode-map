from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import asin, ceil, cos, floor, log, radians, sin, sqrt
from typing import Any, Iterable

from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union

from core.config import settings
from modules.nightlight.service import build_nightlight_meta_payload, get_nightlight_layer
from modules.population.runtime_check import run_population_runtime_check
from modules.population.service import get_population_grid, get_population_layer, get_population_overview
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84, wgs84_to_gcj02
from modules.road.metrics import build_road_orientation_analysis
from modules.scope_datasets.service import ScopeDatasetService, ScopeRecord
from modules.spatial_action.focused_poi_accessibility import (
    FocusedPoiAccessibilityService,
    FocusedPoiCandidate,
    FocusedPoiTypeGroup,
)
from modules.spatial_action.poi_supply_structure import (
    PoiSupplyCandidate,
    PoiSupplyStructureService,
)
from modules.spatial_action.schemas import LocalizedPatternInputCell
from modules.spatial_action.road_network_routing import LocalRoadNetworkRouter, RoadNetworkRoutingUnavailable, build_route_map_context
from modules.spatial_action.service import SpatialActionService
from modules.spatial_cells import build_directional_evidence_matrix, build_shared_grid_analysis

CATALOG_VERSION = "2.0.0"

# Deterministic capabilities exposed to the planning layer.  This is a registry of
# concrete domain adapters, not a project-specific recommendation list.
EXECUTABLE_METRIC_IDS = frozenset({
    "project.document_constraints", "isochrone.reachable_area",
    "poi.count", "poi.category_count", "poi.multi_year_count",
    "poi.grid_count", "poi.local_entropy", "poi.local_entropy_normalized",
    "poi.neighbor_mean_density", "poi.neighbor_mean_entropy", "poi.lq", "poi.kernel_density",
    "spatial.gi_star", "spatial.lisa", "poi.grid_density",
    "spatial.global_moran_i_density", "spatial.neighbor_density_delta", "grid.opportunity_flag",
    "road.integration", "road.choice", "road.connectivity", "road.mean_depth",
    "road.network_size", "road.intelligibility", "road.orientation", "road.degree", "road.node_degree", "road.control",
    "population.total", "population.sex_structure", "population.age_structure", "population.selected_ratio",
    "nightlight.total_radiance", "nightlight.mean_radiance", "nightlight.max_radiance",
    "nightlight.lit_pixel_ratio", "nightlight.p90", "nightlight.hotspot_class",
    "nightlight.hotspot_ratio", "nightlight.spatial_profile", "nightlight.sector_profile",
    "nightlight.activity_level", "regional.directional_evidence_matrix",
    "poi.focused_accessibility", "poi.supply_structure",
})

POI_SCOPE_ADAPTER_METRICS = frozenset({"poi.count", "poi.kernel_density"})
POI_GRID_ADAPTER_METRICS = frozenset({
    "poi.grid_count", "poi.local_entropy", "poi.local_entropy_normalized",
    "poi.neighbor_mean_density", "poi.neighbor_mean_entropy", "poi.lq",
    "spatial.global_moran_i_density", "spatial.neighbor_density_delta", "grid.opportunity_flag",
})
ROAD_ADAPTER_METRICS = frozenset({
    "road.network_size", "road.intelligibility", "road.orientation",
    "road.degree", "road.node_degree", "road.control",
})
ENTROPY_MIN_POI_COUNT = 3
ENTROPY_CATEGORY_COUNT = 7
LQ_SMOOTHING_ALPHA = 0.5


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _geojson(geometry: Any) -> dict[str, Any]:
    return mapping(geometry) if geometry is not None and not geometry.is_empty else {"type": "GeometryCollection", "geometries": []}


def _percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None
    return float(ordered[min(len(ordered) - 1, max(0, floor((len(ordered) - 1) * quantile)))])


def _linear_quantile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values if value is not None)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    lower = floor(position)
    upper = min(len(ordered) - 1, lower + 1)
    ratio = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * ratio



def _attempt(entry: dict[str, Any], target_id: str, status: str, evidence_ids: list[str] | None = None, reason: str = "") -> dict[str, Any]:
    return {"plan_entry_id": entry["plan_entry_id"], "metric_id": entry["metric_id"], "spatial_target": {"unit": entry["planned_spatial_target"]["unit"], "target_id": target_id}, "execution_status": status, "reason": reason, "evidence_node_ids": evidence_ids or []}


def _evidence(evidence_id: str, source_ids: list[str], metric_ids: list[str], title: str, summary: str, data: dict[str, Any], method: str, state: str, *, locator: str = "", flags: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"id": evidence_id, "kind": "spatial_metric", "source_ids": source_ids, "metric_ids": metric_ids, "title": title, "summary": summary, "content": summary, "data": {**data, "evidence_state": state}, "time_scope": {}, "spatial_scope": {}, "method": method, "quality_flags": flags or [], "locator": locator, "citation": "当前历史快照的规范化空间数据"}


@dataclass
class ProjectSpatialAnalysis:
    history_id: str
    project_name: str
    source_versions: list[dict[str, Any]]
    metric_attempts: list[dict[str, Any]]
    evidence_nodes: list[dict[str, Any]]
    spatial_action_map: dict[str, Any]
    coordinate_alignment: dict[str, Any]
    project_document_snapshot: dict[str, Any]
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class MetricToolExecution:
    """Normalized result of one requested metric, with execution internals hidden."""

    tool_id: str
    status: str
    summary: str
    structured_result: dict[str, Any] = field(default_factory=dict)
    input_sources: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


@dataclass
class DataHealth:
    """Short, interpretation-oriented health result kept inside the spatial domain."""

    source_id: str
    data_kind: str
    status: str
    checks: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    eligible_metric_ids: list[str] = field(default_factory=list)
    blocked_metric_ids: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "data_kind": self.data_kind,
            "status": self.status,
            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "checks": self.checks,
            "limitations": self.limitations,
            "eligible_metric_ids": self.eligible_metric_ids,
            "blocked_metric_ids": self.blocked_metric_ids,
        }


class ProjectSpatialAnalysisService:
    """Deep project-context module; the runner persists results but contains no spatial rules."""

    def __init__(self, *, datasets: ScopeDatasetService | None = None, spatial_actions: SpatialActionService | None = None) -> None:
        self._datasets = datasets or ScopeDatasetService()
        self._spatial_actions = spatial_actions or SpatialActionService()

    @staticmethod
    def executable_metric_ids() -> list[str]:
        return sorted(EXECUTABLE_METRIC_IDS)

    def inspect_history_snapshot(
        self,
        *,
        history_id: str,
        project_documents: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a bounded, non-evidentiary inventory for the research agents.

        This deliberately does not calculate metric results.  It tells the planning
        stage which source versions and object types can be considered before a
        a report workflow chooses its requested tools.
        """
        inventory, loaded, selected_years = self._load_snapshot(history_id)
        sources = [
            *self._source_versions(loaded, selected_years, project_documents),
            *self._external_source_versions(),
        ]
        record_counts = {source_id: len(records) for source_id, records in loaded.items()}
        return {
            "history_id": history_id,
            "source_versions": sources,
            "inventory": {
                "ready_source_ids": sorted(loaded),
                "record_counts": record_counts,
                "warnings": list(inventory.get("warnings") or []),
            },
            "execution_capabilities": self.executable_metric_ids(),
            "data_preview": {
                "poi": self._poi_preview(loaded.get("current:dataset:poi", [])),
                "grid_cell_count": len(loaded.get("current:dataset:poi_grid", [])),
                "road_segment_count": len(loaded.get("current:dataset:road_edges", [])),
                "road_grid_cell_count": len(loaded.get("current:dataset:road_grid", [])),
                "project_document_extract_count": sum(
                    len(doc.get("extracts") or [])
                    for doc in project_documents.get("documents") or []
                    if isinstance(doc, dict)
                ),
                "ready_source_ids": [item["source_id"] for item in sources],
            },
        }

    def analyze_history_snapshot(
        self,
        *,
        history_id: str,
        history_detail: dict[str, Any],
        project_documents: dict[str, Any],
        decision_questions: list[dict[str, Any]],
        metric_plan_entries: list[dict[str, Any]],
        evidence_plans: list[dict[str, Any]] | None = None,
        project_anchors: dict[str, Any] | None = None,
    ) -> ProjectSpatialAnalysis:
        """Execute requested spatial metrics against a normalized project snapshot.

        This legacy-stage helper owns deterministic spatial work and intermediate
        source-backed outputs. It never invents questions, chooses tools, writes
        findings, or authors a report.
        """
        del decision_questions  # Plan validation belongs to the orchestrator / AnalysisRun.
        inventory, loaded, selected_years = self._load_snapshot(history_id)
        source_versions = [
            *self._source_versions(loaded, selected_years, project_documents),
            *self._external_source_versions(),
        ]
        selected = {str(entry.get("metric_id") or "") for entry in metric_plan_entries if entry.get("role") != "excluded"}
        alignment = self._coordinate_alignment(history_detail, project_anchors)
        layers: dict[str, Any] = {
            "type": "SpatialActionLayerCollection",
            "history_id": history_id,
            "coordinate_system": "wgs84",
            "localized_patterns": [],
            "grid_colocation": None,
            "road_corridors": [],
            "action_candidates": [],
            "coordinate_alignment": alignment,
            "diagnostics": {},
        }
        evidence: list[dict[str, Any]] = []
        blocked_reasons: dict[str, str] = {}

        document_evidence_planned = any(
            plan.get("document_evidence")
            for plan in (evidence_plans or [])
            if isinstance(plan, dict)
        )
        has_document_extracts = any(
            item.get("text")
            for document in project_documents.get("documents") or []
            if isinstance(document, dict)
            for item in document.get("extracts") or []
            if isinstance(item, dict)
        )
        if document_evidence_planned and has_document_extracts:
            evidence.append(self._document_evidence(project_documents))

        if "project.document_constraints" in selected and not document_evidence_planned:
            evidence.append(self._document_evidence(project_documents))
        if "isochrone.reachable_area" in selected:
            evidence.append(
                _evidence(
                    "evidence:coordinate-alignment",
                    ["history:isochrone"],
                    ["isochrone.reachable_area"],
                    "中心点、坐标与项目锚点审计",
                    alignment["summary"],
                    alignment,
                    "declared coordinate normalization; no POI name proxy",
                    "measured",
                    locator="artifacts/coordinate-alignment.json",
                )
            )

        poi_metrics = {"poi.count", "poi.category_count", "poi.multi_year_count"}
        if selected & poi_metrics and "current:dataset:poi" in loaded:
            poi_evidence, temporal_evidence = self._poi_evidence(history_id, loaded["current:dataset:poi"])
            if "poi.category_count" in selected:
                evidence.append(poi_evidence)
            if "poi.multi_year_count" in selected:
                evidence.append(temporal_evidence)

        adapter_evidence, adapter_blocked = self._snapshot_metric_evidence(
            selected=selected,
            inventory=inventory,
            loaded=loaded,
            selected_years=selected_years,
            history_detail=history_detail,
        )
        evidence.extend(adapter_evidence)
        blocked_reasons.update(adapter_blocked)

        coordinate_system = self._history_coordinate_system(history_detail)
        population_metrics = {
            "population.total",
            "population.sex_structure",
            "population.age_structure",
            "population.selected_ratio",
        }
        if selected & population_metrics:
            polygon = history_detail.get("polygon")
            if not isinstance(polygon, list) or not polygon:
                blocked_reasons.update(
                    {metric_id: "缺少可执行的区域 polygon，无法裁剪人口栅格。" for metric_id in selected & population_metrics}
                )
            else:
                try:
                    overview = get_population_overview(
                        polygon,
                        coordinate_system,
                        str(settings.population_data_year),
                    )
                    evidence.append(
                        _evidence(
                            "evidence:population:scope-profile",
                            ["current:dataset:population"],
                            sorted(selected & population_metrics),
                            "区域人口规模与结构代理",
                            "人口栅格描述分析范围内的常住人口规模、性别与年龄结构；它不是项目客群、到访者或消费需求。",
                            overview,
                            "population raster clip and aggregate",
                            "proxy",
                            locator="artifacts/population-profile.json",
                            flags=[{"code": "resident_population_proxy", "severity": "warning", "effect": "不代表项目实际客群、到访或消费"}],
                        )
                    )
                except Exception as exc:
                    blocked_reasons.update(
                        {metric_id: f"人口数据执行失败：{exc}" for metric_id in selected & population_metrics}
                    )

        nightlight_metrics = {
            "nightlight.total_radiance",
            "nightlight.mean_radiance",
            "nightlight.max_radiance",
            "nightlight.lit_pixel_ratio",
            "nightlight.p90",
            "nightlight.hotspot_class",
            "nightlight.hotspot_ratio",
            "nightlight.spatial_profile",
            "nightlight.sector_profile",
            "nightlight.activity_level",
        }
        if selected & nightlight_metrics:
            polygon = history_detail.get("polygon")
            if not isinstance(polygon, list) or not polygon:
                blocked_reasons.update(
                    {metric_id: "缺少可执行的区域 polygon，无法裁剪夜间灯光数据。" for metric_id in selected & nightlight_metrics}
                )
            else:
                try:
                    layer = get_nightlight_layer(polygon, coordinate_system, view="hotspot")
                    evidence.append(
                        _evidence(
                            "evidence:nightlight:scope-profile",
                            ["current:dataset:nightlight"],
                            sorted(selected & nightlight_metrics),
                            "区域夜间灯光强度与空间形态代理",
                            "夜间灯光用于描述夜间活动强度与空间分布代理；它不能证明项目客流、营业额或特定业态需求。",
                            {
                                "year": layer.get("year"),
                                "summary": layer.get("summary"),
                                "analysis": self._nightlight_spatial_analysis(layer),
                            },
                            "Black Marble raster clip, aggregation, hotspot and gradient profile",
                            "proxy",
                            locator="artifacts/nightlight-profile.json",
                            flags=[{"code": "night_activity_proxy", "severity": "warning", "effect": "不代表项目客流、收入或因果需求"}],
                        )
                    )
                except Exception as exc:
                    blocked_reasons.update(
                        {metric_id: f"夜间灯光数据执行失败：{exc}" for metric_id in selected & nightlight_metrics}
                    )

        local_metrics = {"spatial.gi_star", "spatial.lisa", "poi.grid_density"}
        patterns = None
        if selected & local_metrics and "current:dataset:poi_grid" in loaded:
            patterns = self._local_patterns(loaded["current:dataset:poi_grid"])
            layers["localized_patterns"].append(patterns.model_dump(mode="json"))
            evidence.append(
                _evidence(
                    "evidence:local-pattern:poi-density",
                    ["current:dataset:poi_grid"],
                    ["spatial.gi_star", "spatial.lisa", "poi.grid_density"],
                    "规则网格 POI 局部高值集中区",
                    f"识别 {len(patterns.zones)} 个可定位局部区域；单元 p 值缺失，均为高值集中区代理而非统计热点。",
                    patterns.model_dump(mode="json"),
                    "SpatialActionService local pattern with contiguous-zone merge",
                    patterns.evidence_state,
                    locator="artifacts/spatial-action-map.json#localized_patterns",
                    flags=[{"code": "p_values_missing", "severity": "warning", "effect": "不得称统计热点"}],
                )
            )

        road_metrics = {"road.integration", "road.choice", "road.connectivity", "road.mean_depth"}
        corridors: list[dict[str, Any]] = []
        corridor_segments: dict[str, list[ScopeRecord]] = {}
        if selected & road_metrics and "current:dataset:road_edges" in loaded:
            corridors, corridor_segments = self._road_corridors(loaded["current:dataset:road_edges"])
            layers["road_corridors"] = corridors
            evidence.append(
                _evidence(
                    "evidence:road-syntax:corridors",
                    ["current:dataset:road_edges"],
                    ["road.integration", "road.choice", "road.connectivity", "road.mean_depth"],
                    "局部路网句法廊道与断点候选",
                    self._road_summary(corridors),
                    {"corridors": corridors},
                    "depthmapX attributes; upper/lower quartile corridor selection",
                    "proxy",
                    locator="artifacts/spatial-action-map.json#road_corridors",
                    flags=[{"code": "syntax_proxy", "severity": "warning", "effect": "不等于实测人流"}],
                )
            )

        # The overlay is a derived object board, not an unplanned metric.  It exists
        # only when the locked plan selected both independent signal families.
        if patterns is not None and corridors:
            grid_colocation = None
            if "current:dataset:road_grid" in loaded:
                grid_colocation = self._shared_grid_colocation(loaded["current:dataset:poi_grid"], loaded["current:dataset:road_grid"])
                layers["grid_colocation"] = grid_colocation
                colocation_result = grid_colocation["result"]
                evidence.append(
                    _evidence(
                        "evidence:spatial-action:grid-colocation",
                        ["current:dataset:poi_grid", "current:dataset:road_grid"],
                        ["poi.grid_density", "road.integration", "road.choice"],
                        "POI 与路网共享网格共位区",
                        f"在同一规则网格中识别 {len(colocation_result['zones'])} 个 POI 高值与路网高值共位观察区；它们是空间组织线索，不是客流或项目优先级排名。",
                        grid_colocation,
                        "same-cell upper-quartile POI density plus road integration or choice; contiguous-zone merge",
                        "proxy",
                        locator="artifacts/spatial-action-map.json#grid_colocation",
                        flags=[{"code": "descriptive_colocation", "severity": "warning", "effect": "不表示因果、客流或实际需求"}],
                    )
                )
            action_patterns = grid_colocation["result"] if grid_colocation is not None else patterns.model_dump(mode="json")
            candidates = self._overlay_actions(action_patterns, corridors, corridor_segments)
            layers["action_candidates"] = candidates
            evidence.append(
                _evidence(
                    "evidence:spatial-action:poi-road-overlay",
                    ["current:dataset:poi_grid", "current:dataset:road_edges"],
                    ["poi.grid_density", "road.integration", "road.choice"],
                    "POI 局部区域与路网廊道交叉候选",
                    f"形成 {len(candidates)} 个可定位踏勘/公共界面观察候选；它们是供给与路网结构交叉代理。",
                    {"candidates": candidates},
                    "localized zone and road corridor geometry overlay",
                    "proxy",
                    locator="artifacts/spatial-action-map.json#action_candidates",
                )
            )

        attempts = self._attempts(
            metric_plan_entries,
            evidence,
            available_source_ids={item["source_id"] for item in source_versions},
            blocked_reasons=blocked_reasons,
        )
        diagnostics = list(inventory.get("warnings") or []) + alignment["warnings"]
        diagnostics.extend(
            f"{attempt['plan_entry_id']}: {attempt['reason']}"
            for attempt in attempts
            if attempt["execution_status"] in {"blocked", "failed"}
        )
        return ProjectSpatialAnalysis(
            history_id,
            str(project_documents.get("project_name") or "项目"),
            source_versions,
            attempts,
            evidence,
            layers,
            alignment,
            project_documents,
            diagnostics,
        )

    def _snapshot_metric_evidence(
        self,
        *,
        selected: set[str],
        inventory: dict[str, Any],
        loaded: dict[str, list[ScopeRecord]],
        selected_years: dict[str, int | None],
        history_detail: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Expose persisted snapshot semantics through one adapter contract per metric."""

        evidence: list[dict[str, Any]] = []
        blocked: dict[str, str] = {}
        summaries = {
            str(item.get("source_id")): _mapping(item.get("summary"))
            for item in inventory.get("datasets") or []
            if isinstance(item, dict)
        }
        record_counts = {
            str(item.get("source_id")): int(_number(item.get("record_count")) or 0)
            for item in inventory.get("datasets") or []
            if isinstance(item, dict)
        }

        poi_records = loaded.get("current:dataset:poi", [])
        for metric_id in sorted(selected & POI_SCOPE_ADAPTER_METRICS):
            if not poi_records:
                blocked[metric_id] = "当前快照没有可用于该指标的 POI 记录。"
                continue
            if metric_id == "poi.count":
                data, reason = self._verified_poi_count(poi_records, history_detail, selected_years.get("current:dataset:poi"))
                if reason:
                    blocked[metric_id] = reason
                    continue
                title = "15 分钟步行等时圈 POI 数量"
                summary = f"经等时圈 covers 核验并去重后共有 {data['count']} 个 POI。"
                method = "verified walking isochrone covers and stable-record deduplication"
            else:
                data = self._poi_heatmap_surface(poi_records, selected_years.get("current:dataset:poi"))
                if not data["heatmap_surface"]["points"]:
                    blocked[metric_id] = "当前 POI 快照没有可用于热力表面的有效点坐标。"
                    continue
                title = "POI 相对集聚热力表面"
                summary = f"以 {data['heatmap_surface']['point_count']} 个去重点生成可复现的高德热力层输入。"
                method = "AMap heatmap render contract over valid deduplicated POI points"
            source_ids = ["current:dataset:poi", "history:isochrone"] if metric_id == "poi.count" else ["current:dataset:poi"]
            evidence.append(self._adapter_evidence(metric_id, source_ids, title, summary, data, method))

        grid_records = loaded.get("current:dataset:poi_grid", [])
        for metric_id in sorted(selected & POI_GRID_ADAPTER_METRICS):
            if not grid_records:
                blocked[metric_id] = "当前快照没有可用于该指标的 POI 网格记录。"
                continue
            data, reason = self._poi_grid_metric_data(
                metric_id,
                grid_records,
                summaries.get("current:dataset:poi_grid", {}),
                selected_years.get("current:dataset:poi_grid"),
                scope_poi_count=record_counts.get("current:dataset:poi"),
            )
            if reason:
                blocked[metric_id] = reason
                continue
            title, summary, method = self._poi_grid_metric_description(metric_id, data)
            evidence.append(self._adapter_evidence(metric_id, "current:dataset:poi_grid", title, summary, data, method))

        road_records = loaded.get("current:dataset:road_edges", [])
        for metric_id in sorted(selected & ROAD_ADAPTER_METRICS):
            if not road_records:
                blocked[metric_id] = "当前快照没有可用于该指标的路网边记录。"
                continue
            data, reason = self._road_metric_data(
                metric_id,
                road_records,
                summaries.get("current:dataset:road_edges", {}),
            )
            if reason:
                blocked[metric_id] = reason
                continue
            title, summary, method = self._road_metric_description(metric_id, data)
            evidence.append(
                self._adapter_evidence(
                    metric_id,
                    "current:dataset:road_edges",
                    title,
                    summary,
                    data,
                    method,
                    state="proxy",
                    flags=[{"code": "road_syntax_proxy", "severity": "warning", "effect": "不等于实测人流、交通控制或主观导航认知"}],
                )
            )
        return evidence, blocked

    @staticmethod
    def _adapter_evidence(
        metric_id: str,
        source_id: str | list[str],
        title: str,
        summary: str,
        data: dict[str, Any],
        method: str,
        *,
        state: str = "measured",
        flags: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return _evidence(
            f"evidence:metric:{metric_id}",
            [source_id] if isinstance(source_id, str) else source_id,
            [metric_id],
            title,
            summary,
            data,
            method,
            state,
            locator=source_id if isinstance(source_id, str) else source_id[0],
            flags=flags,
        )

    def _verified_poi_count(
        self,
        records: list[ScopeRecord],
        history_detail: dict[str, Any],
        year: int | None,
    ) -> tuple[dict[str, Any], str]:
        isochrone, scope = self._verified_fifteen_minute_walking_isochrone(history_detail)
        if isochrone is None:
            return {}, str(scope)
        try:
            isochrone_shape = shape(isochrone)
        except Exception:
            return {}, "15 分钟 walking 等时圈几何无法解析。"
        if isochrone_shape.is_empty or not isochrone_shape.is_valid:
            return {}, "15 分钟 walking 等时圈几何无效。"

        accepted: list[ScopeRecord] = []
        seen: set[str] = set()
        duplicate_count = invalid_geometry_count = outside_count = raw_coordinate_match_count = 0
        for record in records:
            geometry = record.geometry
            props = record.properties or {}
            key = str(record.record_id or props.get("record_id") or props.get("id") or "").strip()
            if not key:
                point = geometry.representative_point() if geometry is not None and not geometry.is_empty else None
                key = f"{props.get('name') or ''}|{point.x:.6f},{point.y:.6f}" if point is not None else f"{props.get('name') or ''}"
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            candidates = []
            if geometry is not None and not geometry.is_empty and geometry.geom_type in {"Point", "MultiPoint"}:
                candidates.append((geometry, "normalized_geometry"))
            raw_location = props.get("location")
            if isinstance(raw_location, str):
                raw_location = [part.strip() for part in raw_location.split(",")]
            if isinstance(raw_location, (list, tuple)) and len(raw_location) >= 2:
                try:
                    candidates.append((Point(float(raw_location[0]), float(raw_location[1])), "raw_location"))
                except (TypeError, ValueError):
                    pass
            matched = next(((candidate, source) for candidate, source in candidates if isochrone_shape.covers(candidate)), None)
            if matched is None:
                outside_count += 1
                continue
            if matched[1] == "raw_location":
                raw_coordinate_match_count += 1
            if not candidates:
                invalid_geometry_count += 1
            accepted.append(record)

        categories = Counter(
            str(record.properties.get("category") or record.properties.get("type") or "unknown")
            for record in accepted
        )
        count = len(accepted)
        return {
            "count": count,
            "category_counts": dict(sorted(categories.items())),
            "summary_by_year": [{"year": year, "count": count}],
            "year": year,
            "scope": scope,
            "audit": {
                "source_record_count": len(records),
                "duplicate_count": duplicate_count,
                "invalid_geometry_count": invalid_geometry_count,
                "outside_isochrone_count": outside_count,
                "included_count": count,
                "raw_location_match_count": raw_coordinate_match_count,
            },
        }, ""

    @staticmethod
    def _poi_heatmap_surface(records: list[ScopeRecord], year: int | None) -> dict[str, Any]:
        points: list[dict[str, Any]] = []
        seen: set[str] = set()
        invalid_count = duplicate_count = 0
        for record in records:
            geometry = record.geometry
            if geometry is None or geometry.is_empty or geometry.geom_type != "Point":
                invalid_count += 1
                continue
            props = record.properties or {}
            key = str(record.record_id or props.get("record_id") or props.get("id") or "").strip()
            if not key:
                key = f"{geometry.x:.6f},{geometry.y:.6f}"
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            raw_location = props.get("location")
            if isinstance(raw_location, str):
                raw_location = [part.strip() for part in raw_location.split(",")]
            if isinstance(raw_location, (list, tuple)) and len(raw_location) >= 2:
                try:
                    longitude, latitude = float(raw_location[0]), float(raw_location[1])
                except (TypeError, ValueError):
                    longitude, latitude = wgs84_to_gcj02(float(geometry.x), float(geometry.y))
            else:
                longitude, latitude = wgs84_to_gcj02(float(geometry.x), float(geometry.y))
            points.append({"lng": round(longitude, 8), "lat": round(latitude, 8), "count": 1})
        return {
            "heatmap_surface": {
                "renderer": "amap.HeatMap",
                "points": points,
                "point_count": len(points),
                "radius": 28,
                "max": max(6, ceil(len(points) / 40)),
                "opacity": 0.7,
                "coordinate_system": "gcj02",
                "intensity_semantics": "relative_visual_intensity",
            },
            "year": year,
            "audit": {"source_record_count": len(records), "duplicate_count": duplicate_count, "invalid_geometry_count": invalid_count},
        }

    def _poi_grid_metric_data(
        self,
        metric_id: str,
        records: list[ScopeRecord],
        source_summary: dict[str, Any],
        year: int | None,
        *,
        scope_poi_count: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        cells = []
        for record in records:
            props = record.properties or {}
            cells.append({
                "cell_id": str(props.get("cell_id") or props.get("h3_id") or record.record_id),
                "poi_count": int(_number(props.get("poi_count")) or 0),
                "density_poi_per_km2": _number(props.get("density_poi_per_km2")),
                "local_entropy": _number(props.get("local_entropy")),
                "neighbor_mean_density": _number(props.get("neighbor_mean_density")),
                "neighbor_mean_entropy": _number(props.get("neighbor_mean_entropy")),
                "neighbor_count": int(_number(props.get("neighbor_count")) or 0),
                "category_counts": dict(_mapping(props.get("category_counts"))),
            })
        common = {"year": year, "grid_count": len(cells), "parameters": {"minimum_poi_count": ENTROPY_MIN_POI_COUNT}}

        if metric_id == "poi.grid_count":
            rows = [{"cell_id": cell["cell_id"], "poi_count": cell["poi_count"]} for cell in cells]
            assigned = sum(row["poi_count"] for row in rows)
            return {
                **common,
                "poi_count": rows,
                "assigned_poi_count": assigned,
                "max_poi_count": max((row["poi_count"] for row in rows), default=0),
                "source_scope_poi_count": scope_poi_count,
                "grid_assignment_ratio": round(assigned / scope_poi_count, 6) if scope_poi_count else None,
            }, ""

        eligible = [cell for cell in cells if cell["poi_count"] >= ENTROPY_MIN_POI_COUNT]
        if metric_id in {"poi.local_entropy", "poi.local_entropy_normalized"}:
            key = "local_entropy" if metric_id == "poi.local_entropy" else "displayed_entropy"
            rows = []
            for cell in cells:
                value = cell["local_entropy"] if cell["poi_count"] >= ENTROPY_MIN_POI_COUNT else None
                if value is not None and key == "displayed_entropy":
                    value = max(0.0, min(1.0, value / log(ENTROPY_CATEGORY_COUNT)))
                rows.append({"cell_id": cell["cell_id"], "poi_count": cell["poi_count"], key: None if value is None else round(value, 6)})
            values = [row[key] for row in rows if row[key] is not None]
            if not values:
                return {}, "当前网格没有达到最小样本 3 的有效熵单元。"
            data = {**common, key: rows, "valid_cell_count": len(values), "insufficient_sample_cell_count": len(rows) - len(values)}
            if metric_id == "poi.local_entropy":
                data["avg_local_entropy"] = round(sum(values) / len(values), 6)
            else:
                data["normalization"] = "local_entropy / ln(7)"
            return data, ""

        if metric_id in {"poi.neighbor_mean_density", "poi.neighbor_mean_entropy", "spatial.neighbor_density_delta"}:
            output_key = {
                "poi.neighbor_mean_density": "neighbor_mean_density",
                "poi.neighbor_mean_entropy": "neighbor_mean_entropy",
                "spatial.neighbor_density_delta": "neighbor_delta",
            }[metric_id]
            rows = []
            for cell in cells:
                if metric_id == "spatial.neighbor_density_delta":
                    density, neighbor = cell["density_poi_per_km2"], cell["neighbor_mean_density"]
                    value = density - neighbor if density is not None and neighbor is not None else None
                else:
                    value = cell[output_key]
                rows.append({
                    "cell_id": cell["cell_id"],
                    "neighbor_count": cell["neighbor_count"],
                    output_key: None if value is None else round(value, 6),
                })
            if not any(row[output_key] is not None for row in rows):
                return {}, f"当前网格缺少 {output_key} 字段。"
            return {**common, output_key: rows}, ""

        if metric_id == "poi.lq":
            categories = sorted({str(key) for cell in cells for key in cell["category_counts"]})
            if not categories or not eligible:
                return {}, "当前网格缺少可按同一分类体系计算 LQ 的有效类别记录。"
            global_counts = Counter()
            for cell in cells:
                global_counts.update({str(key): int(_number(value) or 0) for key, value in cell["category_counts"].items()})
            global_total = sum(global_counts.values())
            alpha = LQ_SMOOTHING_ALPHA
            category_size = len(categories)
            rows = []
            for cell in eligible:
                lq_by_category: dict[str, float | None] = {}
                for category in categories:
                    global_share = (global_counts[category] + alpha) / (global_total + alpha * category_size)
                    cell_share = (int(_number(cell["category_counts"].get(category)) or 0) + alpha) / (cell["poi_count"] + alpha * category_size)
                    lq_by_category[category] = round(cell_share / global_share, 6) if global_share > 0 else None
                ranked = [(category, value) for category, value in lq_by_category.items() if value is not None]
                dominant = max(ranked, key=lambda item: item[1])[0] if ranked else None
                rows.append({"cell_id": cell["cell_id"], "poi_count": cell["poi_count"], "lq_by_category": lq_by_category, "location_quotient": lq_by_category, "dominant_lq_category": dominant})
            return {**common, "parameters": {"minimum_poi_count": ENTROPY_MIN_POI_COUNT, "smoothing_alpha": alpha, "category_count": category_size}, "global_category_counts": dict(global_counts), "lq_by_category": rows, "location_quotient": rows}, ""

        if metric_id == "grid.opportunity_flag":
            density_values = [cell["density_poi_per_km2"] for cell in cells if cell["density_poi_per_km2"] is not None]
            entropy_values = [max(0.0, min(1.0, cell["local_entropy"] / log(ENTROPY_CATEGORY_COUNT))) for cell in eligible if cell["local_entropy"] is not None]
            density_p70, entropy_p70 = _linear_quantile(density_values, .7), _linear_quantile(entropy_values, .7)
            if density_p70 is None or entropy_p70 is None:
                return {}, "当前网格缺少计算空间条件筛选标记所需的密度或有效熵分布。"
            rows = []
            for cell in cells:
                entropy = max(0.0, min(1.0, cell["local_entropy"] / log(ENTROPY_CATEGORY_COUNT))) if cell["poi_count"] >= ENTROPY_MIN_POI_COUNT and cell["local_entropy"] is not None else None
                density, neighbor = cell["density_poi_per_km2"], cell["neighbor_mean_density"]
                delta = density - neighbor if density is not None and neighbor is not None else None
                flag = bool(density is not None and entropy is not None and delta is not None and density >= density_p70 and entropy >= entropy_p70 and delta > 0)
                rows.append({"cell_id": cell["cell_id"], "is_spatial_condition_flag": flag, "density": density, "displayed_entropy": entropy, "neighbor_delta": delta})
            return {**common, "thresholds": {"density_p70": density_p70, "displayed_entropy_p70": entropy_p70}, "is_spatial_condition_flag": rows, "flagged_cell_count": sum(1 for row in rows if row["is_spatial_condition_flag"]), "interpretation": "空间条件筛选标记，不代表商业机会、需求缺口或投资建议。"}, ""

        if metric_id == "spatial.global_moran_i_density":
            moran_i = _number(source_summary.get("global_moran_i_density"))
            z_score = _number(source_summary.get("global_moran_z_score"))
            if moran_i is None:
                return {}, "当前 POI 网格 summary 未保存全局 Moran I。"
            limitations = [] if z_score is not None else ["当前快照未保存 global_moran_z_score，只能报告 Moran I 描述值，不能判断统计显著性。"]
            return {**common, "global_moran_i_density": moran_i, "global_moran_z_score": z_score, "significance_status": "available" if z_score is not None else "not_available", "limitations": limitations}, ""

        return {}, f"未识别的 POI 网格指标：{metric_id}。"

    @staticmethod
    def _poi_grid_metric_description(metric_id: str, data: dict[str, Any]) -> tuple[str, str, str]:
        titles = {
            "poi.grid_count": "网格 POI 数量",
            "poi.local_entropy": "POI 类别局部熵",
            "poi.local_entropy_normalized": "归一化局部熵",
            "poi.neighbor_mean_density": "邻域平均 POI 密度",
            "poi.neighbor_mean_entropy": "邻域平均 POI 混合度",
            "poi.lq": "POI 类别区位商",
            "spatial.global_moran_i_density": "POI 密度全局 Moran I",
            "spatial.neighbor_density_delta": "网格相对邻域密度差",
            "grid.opportunity_flag": "空间条件筛选标记",
        }
        if metric_id == "poi.grid_count":
            summary = f"{data['grid_count']} 个网格共落入 {data['assigned_poi_count']} 个 POI。"
        elif metric_id == "poi.local_entropy":
            summary = f"{data['valid_cell_count']} 个网格达到最小样本并形成局部熵。"
        elif metric_id == "poi.local_entropy_normalized":
            summary = f"{data['valid_cell_count']} 个网格形成 ln(7) 归一化混合度。"
        elif metric_id == "poi.neighbor_mean_density":
            summary = f"返回 {data['grid_count']} 个网格的邻域平均密度。"
        elif metric_id == "poi.neighbor_mean_entropy":
            summary = f"返回 {data['grid_count']} 个网格的邻域平均熵。"
        elif metric_id == "poi.lq":
            summary = f"按 alpha=0.5 返回 {len(data['lq_by_category'])} 个有效网格的分类 LQ。"
        elif metric_id == "spatial.global_moran_i_density":
            summary = f"当前范围 POI 密度 Moran I={data['global_moran_i_density']:.6f}。"
        elif metric_id == "spatial.neighbor_density_delta":
            summary = f"返回 {data['grid_count']} 个网格相对邻域的密度差。"
        else:
            summary = f"按同范围 P70 规则标记 {data['flagged_cell_count']} 个空间条件单元。"
        methods = {
            "poi.grid_count": "persisted shared-grid POI aggregation",
            "poi.local_entropy": "persisted Shannon entropy with minimum sample policy",
            "poi.local_entropy_normalized": "Shannon entropy divided by ln(7) with minimum sample policy",
            "poi.neighbor_mean_density": "persisted same-ring neighbor arithmetic mean",
            "poi.neighbor_mean_entropy": "persisted same-ring neighbor entropy arithmetic mean",
            "poi.lq": "same-scope category share quotient with additive smoothing",
            "spatial.global_moran_i_density": "persisted global spatial autocorrelation summary",
            "spatial.neighbor_density_delta": "cell density minus persisted neighbor mean density",
            "grid.opportunity_flag": "same-scope P70 density and entropy rule plus positive neighbor delta",
        }
        return titles[metric_id], summary, methods[metric_id]

    def _road_metric_data(
        self,
        metric_id: str,
        records: list[ScopeRecord],
        source_summary: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        nodes = self._road_node_degree_rows(records)
        if metric_id == "road.network_size":
            edge_count = int(_number(source_summary.get("edge_count")) or len(records))
            node_count = int(_number(source_summary.get("node_count")) or len(nodes))
            network_length = _number(source_summary.get("network_length_km"))
            if network_length is None:
                network_length = sum(_number(record.properties.get("length_m")) or 0.0 for record in records) / 1000.0
            return {
                "node_count": node_count,
                "edge_count": edge_count,
                "rendered_edge_count": int(_number(source_summary.get("rendered_edge_count"))) if _number(source_summary.get("rendered_edge_count")) is not None else None,
                "network_length_km": round(network_length, 4),
                "edge_merge_ratio": _number(source_summary.get("edge_merge_ratio")),
            }, ""
        if metric_id == "road.orientation":
            orientation = _mapping(source_summary.get("road_orientation_analysis"))
            if not orientation:
                features = [{"type": "Feature", "geometry": _geojson(record.geometry), "properties": dict(record.properties)} for record in records if record.geometry is not None]
                orientation = build_road_orientation_analysis(features)
            return {"road_orientation_analysis": orientation}, "" if orientation.get("orientation_rows") else "当前路网没有可计算方向的有效线段。"
        if metric_id == "road.node_degree":
            if not nodes:
                return {}, "当前路网几何无法恢复节点拓扑。"
            return {"degree": nodes, "degree_score": nodes, "avg_degree": round(sum(row["degree"] for row in nodes) / len(nodes), 6), "node_count": len(nodes), "coordinate_precision": 6}, ""
        if metric_id == "road.degree":
            rows = [{"edge_id": record.record_id, "degree_score": _number(record.properties.get("degree_score"))} for record in records if _number(record.properties.get("degree_score")) is not None]
            if not rows:
                return {}, "当前路网边记录缺少 degree_score。"
            avg_degree = _number(source_summary.get("avg_degree"))
            if avg_degree is None and nodes:
                avg_degree = sum(row["degree"] for row in nodes) / len(nodes)
            return {"degree": rows, "degree_score": rows, "avg_degree": None if avg_degree is None else round(avg_degree, 6), "edge_count": len(rows), "semantics": "edge score averaged from normalized endpoint node degrees"}, ""
        if metric_id == "road.control":
            rows = [{"edge_id": record.record_id, "control_score": _number(record.properties.get("control_score")), "control_global": _number(record.properties.get("control_global"))} for record in records if _number(record.properties.get("control_score")) is not None]
            if not rows:
                return {}, "当前路网边记录缺少 control_score。"
            source_column = str(source_summary.get("control_source_column") or "")
            avg_control = _number(source_summary.get("avg_control"))
            if avg_control is None:
                avg_control = sum(float(row["control_score"]) for row in rows) / len(rows)
            return {"control_score": rows, "control_global": rows, "avg_control": round(avg_control, 8), "control_source_column": source_column, "control_valid_count": int(_number(source_summary.get("control_valid_count")) or len(rows)), "evidence_state": "proxy" if source_column == "topology_fallback" else "measured_model_output"}, ""
        if metric_id == "road.intelligibility":
            rows = [{"edge_id": record.record_id, "intelligibility_score": _number(record.properties.get("intelligibility_score"))} for record in records if _number(record.properties.get("intelligibility_score")) is not None]
            regression = self._road_intelligibility_regression(records)
            avg = _number(source_summary.get("avg_intelligibility"))
            r2 = _number(source_summary.get("avg_intelligibility_r2"))
            if avg is None:
                avg = regression.get("r")
            if r2 is None:
                r2 = regression.get("r2")
            if avg is None:
                return {}, "当前路网缺少计算可理解度所需的连通度与整合度配对。"
            return {"intelligibility_score": rows, "avg_intelligibility": avg, "avg_intelligibility_r2": r2, "diagnostics": {"regression": regression}}, ""
        return {}, f"未识别的路网指标：{metric_id}。"

    @staticmethod
    def _road_node_degree_rows(records: list[ScopeRecord]) -> list[dict[str, Any]]:
        neighbors: dict[tuple[float, float], set[tuple[float, float]]] = {}
        for record in records:
            geometry = record.geometry
            if geometry is None or geometry.is_empty:
                continue
            lines = list(geometry.geoms) if geometry.geom_type == "MultiLineString" else [geometry]
            for line in lines:
                if line.geom_type != "LineString":
                    continue
                coords = list(line.coords)
                if len(coords) < 2:
                    continue
                start = (round(float(coords[0][0]), 6), round(float(coords[0][1]), 6))
                end = (round(float(coords[-1][0]), 6), round(float(coords[-1][1]), 6))
                if start == end:
                    continue
                neighbors.setdefault(start, set()).add(end)
                neighbors.setdefault(end, set()).add(start)
        degrees = {node: len(values) for node, values in neighbors.items()}
        if not degrees:
            return []
        minimum, maximum = min(degrees.values()), max(degrees.values())
        span = maximum - minimum
        return [
            {"node_id": f"{node[0]:.6f},{node[1]:.6f}", "coordinate": [node[0], node[1]], "degree": degree, "degree_score": round((degree - minimum) / span, 8) if span else 0.0}
            for node, degree in sorted(degrees.items())
        ]

    @staticmethod
    def _road_intelligibility_regression(records: list[ScopeRecord]) -> dict[str, Any]:
        pairs = []
        for record in records:
            x = _number(record.properties.get("connectivity_score"))
            y = _number(record.properties.get("integration_global"))
            if x is not None and y is not None:
                pairs.append((x, y))
        if len(pairs) < 2:
            return {"r": None, "r2": None, "slope": None, "intercept": None, "n": len(pairs)}
        mean_x = sum(x for x, _ in pairs) / len(pairs)
        mean_y = sum(y for _, y in pairs) / len(pairs)
        ss_x = sum((x - mean_x) ** 2 for x, _ in pairs)
        ss_y = sum((y - mean_y) ** 2 for _, y in pairs)
        covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
        r = covariance / sqrt(ss_x * ss_y) if ss_x > 0 and ss_y > 0 else None
        slope = covariance / ss_x if ss_x > 0 else None
        return {"r": None if r is None else round(r, 8), "r2": None if r is None else round(r * r, 8), "slope": None if slope is None else round(slope, 8), "intercept": None if slope is None else round(mean_y - slope * mean_x, 8), "n": len(pairs)}

    @staticmethod
    def _road_metric_description(metric_id: str, data: dict[str, Any]) -> tuple[str, str, str]:
        if metric_id == "road.network_size":
            return "路网规模", f"当前模型包含 {data['node_count']} 个节点、{data['edge_count']} 条边和 {data['network_length_km']:.4f} 公里线网。", "persisted road-syntax scope summary"
        if metric_id == "road.intelligibility":
            return "路网可理解度", f"归一化连通度与全局整合度相关系数为 {data['avg_intelligibility']:.6f}。", "persisted road intelligibility plus deterministic regression diagnostics"
        if metric_id == "road.orientation":
            dominant = data["road_orientation_analysis"].get("dominant_orientation") or "未识别"
            return "道路方向分布", f"长度加权的路网主导方向为{dominant}。", "length-weighted road segment orientation"
        if metric_id == "road.degree":
            return "边级节点度分数", f"返回 {data['edge_count']} 条边的端点度归一化分数。", "persisted edge score averaged from endpoint node degrees"
        if metric_id == "road.node_degree":
            return "路网节点度", f"从输出路网恢复 {data['node_count']} 个节点及其直接邻接数量。", "six-decimal endpoint topology reconstruction"
        return "路网控制值", f"返回 {data['control_valid_count']} 条有效控制值，来源为 {data['control_source_column'] or '未标注'}。", "persisted depthmapX control or declared topology fallback"

    @staticmethod
    def _metric_source_ids(tool_id: str) -> list[str]:
        if tool_id == "regional.directional_evidence_matrix":
            return [
                "current:dataset:poi",
                "current:dataset:population",
                "current:dataset:nightlight",
                "current:dataset:road_edges",
            ]
        if tool_id in {"poi.supply_structure", "poi.focused_accessibility"}:
            return ["current:dataset:poi", "current:dataset:road_edges"]
        if tool_id == "poi.count":
            return ["current:dataset:poi", "history:isochrone"]
        if tool_id in POI_SCOPE_ADAPTER_METRICS or tool_id in {"poi.category_count", "poi.multi_year_count"}:
            return ["current:dataset:poi"]
        if tool_id.startswith("population."):
            return ["current:dataset:population"]
        if tool_id.startswith("nightlight."):
            return ["current:dataset:nightlight"]
        if tool_id.startswith("road."):
            return ["current:dataset:road_edges"]
        if tool_id in POI_GRID_ADAPTER_METRICS or (tool_id.startswith("poi.") and "grid" in tool_id):
            return ["current:dataset:poi_grid"]
        if tool_id.startswith("spatial.") or tool_id.startswith("grid."):
            return ["current:dataset:poi_grid"]
        if tool_id.startswith("isochrone."):
            return ["history:isochrone"]
        if tool_id.startswith("project."):
            return ["document:project-extracts"]
        return []

    @staticmethod
    def _project_scope_geometry(history_detail: dict[str, Any]) -> Any | None:
        """Build the normalized project scope used by record-health checks."""

        coordinates = history_detail.get("polygon")
        if not isinstance(coordinates, list) or len(coordinates) < 4:
            return None
        try:
            normalized = [
                gcj02_to_wgs84(float(point[0]), float(point[1]))
                if str(history_detail.get("coordinate_system") or "").lower() == "gcj02"
                else (float(point[0]), float(point[1]))
                for point in coordinates
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if len(normalized) < 4:
                return None
            scope = Polygon(normalized)
            if scope.is_empty:
                return None
            return scope if scope.is_valid else scope.buffer(0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _record_health(
        source_id: str,
        records: list[ScopeRecord],
        metric_ids: list[str],
        *,
        scope_geometry: Any | None = None,
        data_year: int | None = None,
    ) -> DataHealth:
        """Check record/vector data where its spatial semantics are known.

        ScopeDatasetService normalizes usable records to WGS84 before they reach
        this module.  This method verifies the remaining project-specific facts:
        geometry validity, scope relationship, expected unit shape, attributes
        required by the requested metric, and road topology where appropriate.
        Only one interpretation-relevant limitation is returned to callers.
        """
        if not records:
            return DataHealth(
                source_id, "vector", "unavailable",
                {"record_count": 0, "valid_geometry_count": 0, "record_id_unique_ratio": 0.0, "year": data_year},
                ["当前快照没有可用于该指标的空间记录。"], [], metric_ids,
            )

        valid = [
            record for record in records
            if record.geometry is not None and not record.geometry.is_empty and record.geometry.is_valid
        ]
        if not valid:
            return DataHealth(
                source_id, "vector", "unavailable",
                {
                    "record_count": len(records), "valid_geometry_count": 0,
                    "invalid_geometry_ratio": 1.0,
                    "record_id_unique_ratio": round(len({record.record_id for record in records if record.record_id}) / len(records), 6),
                    "year": data_year,
                },
                ["当前记录没有任何有效几何，无法与项目对象建立空间关系。"], [], metric_ids,
            )

        expected_geometry_types = {
            "current:dataset:poi": {"Point", "MultiPoint"},
            "current:dataset:h3": {"Polygon", "MultiPolygon"},
            "current:dataset:poi_grid": {"Polygon", "MultiPolygon"},
            "current:dataset:road_edges": {"LineString", "MultiLineString"},
            "current:dataset:road_grid": {"Polygon", "MultiPolygon"},
        }.get(source_id, set())
        required_fields_by_metric = {
            "poi.category_count": ("type", "typecode", "category"),
            "poi.multi_year_count": ("year",),
            "poi.grid_density": ("density", "poi_density", "poi_count"),
            "poi.grid_count": ("poi_count",),
            "poi.local_entropy": ("local_entropy",),
            "poi.local_entropy_normalized": ("local_entropy",),
            "poi.neighbor_mean_density": ("neighbor_mean_density",),
            "poi.neighbor_mean_entropy": ("neighbor_mean_entropy",),
            "poi.lq": ("category_counts",),
            "spatial.global_moran_i_density": ("density_poi_per_km2",),
            "spatial.neighbor_density_delta": ("density_poi_per_km2", "neighbor_mean_density"),
            "grid.opportunity_flag": ("density_poi_per_km2", "local_entropy", "neighbor_mean_density"),
            "spatial.gi_star": ("density", "poi_density", "poi_count", "value"),
            "spatial.lisa": ("density", "poi_density", "poi_count", "value"),
            "road.integration": ("integration", "integration_score", "road_integration"),
            "road.choice": ("choice", "choice_score", "road_choice"),
            "road.connectivity": ("connectivity", "connectivity_score", "road_connectivity"),
            "road.mean_depth": ("mean_depth", "depth", "depth_score", "road_depth"),
            "road.intelligibility": ("intelligibility_score", "connectivity_score"),
            "road.degree": ("degree_score",),
            "road.control": ("control_score", "control_global"),
            "road.network_size": ("length_m",),
        }
        required_fields = [
            field_group
            for metric_id in metric_ids
            if (field_group := required_fields_by_metric.get(metric_id))
        ]

        invalid_count = len(records) - len(valid)
        invalid_ratio = invalid_count / len(records)
        nonempty_properties = sum(1 for record in valid if record.properties)
        identifiers = [record.record_id for record in records if record.record_id]
        unique_ratio = len(set(identifiers)) / len(records)
        property_ratio = nonempty_properties / len(valid)
        coordinate_valid_count = sum(
            1
            for record in valid
            if -180 <= record.geometry.bounds[0] <= 180
            and -180 <= record.geometry.bounds[2] <= 180
            and -90 <= record.geometry.bounds[1] <= 90
            and -90 <= record.geometry.bounds[3] <= 90
        )
        expected_type_count = sum(
            1 for record in valid
            if not expected_geometry_types or record.geometry.geom_type in expected_geometry_types
        )
        scope_intersection_count = (
            sum(1 for record in valid if record.geometry.intersects(scope_geometry))
            if scope_geometry is not None and not scope_geometry.is_empty
            else None
        )
        missing_required_attribute_count = sum(
            1
            for record in valid
            if any(not any(record.properties.get(field) not in (None, "") for field in group) for group in required_fields)
        )

        road_connected_ratio: float | None = None
        if source_id == "current:dataset:road_edges":
            endpoint_counts: Counter[tuple[float, float]] = Counter()
            line_records = [record for record in valid if record.geometry.geom_type == "LineString"]
            for record in line_records:
                coordinates = list(record.geometry.coords)
                if len(coordinates) >= 2:
                    endpoint_counts.update(((round(coordinates[0][0], 7), round(coordinates[0][1], 7)), (round(coordinates[-1][0], 7), round(coordinates[-1][1], 7))))
            if len(line_records) >= 2:
                connected = sum(
                    1
                    for record in line_records
                    if any(endpoint_counts[(round(point[0], 7), round(point[1], 7))] > 1 for point in (record.geometry.coords[0], record.geometry.coords[-1]))
                )
                road_connected_ratio = round(connected / len(line_records), 6)

        limitations: list[str] = []
        if scope_intersection_count == 0:
            return DataHealth(
                source_id, "vector", "unavailable",
                {
                    "record_count": len(records), "valid_geometry_count": len(valid), "scope_intersection_count": 0,
                    "year": data_year, "coordinate_system": "wgs84",
                },
                ["有效空间记录与当前分析范围不相交，无法形成范围内比较。"], [], metric_ids,
            )
        if invalid_count:
            limitations.append(f"{invalid_count} 条记录缺少或具有无效几何，结果仅覆盖其余可用空间对象。")
        if unique_ratio < 0.99:
            limitations.append("部分记录标识不唯一，避免将记录数量解释为独立设施或独立客户数量。")
        if property_ratio < 0.95:
            limitations.append("部分空间记录缺少属性，分类或结构比较仅基于属性完整的对象。")
        if coordinate_valid_count != len(valid):
            limitations.append("部分几何不符合 WGS84 坐标范围，无法可靠叠加到分析范围。")
        if expected_geometry_types and expected_type_count != len(valid):
            limitations.append("部分空间对象的几何类型与当前数据单元不一致，不能按预期网格或路段口径比较。")
        if scope_intersection_count is not None and scope_intersection_count / len(valid) < 0.6:
            limitations.append("多数有效对象未与分析范围相交，当前范围内的比较覆盖不足。")
        if missing_required_attribute_count:
            limitations.append("部分记录缺少当前指标所需属性，不能完整解释分类、网格或路网差异。")
        if road_connected_ratio is not None and road_connected_ratio < 0.6:
            limitations.append("路网线段连通性不足，不能把当前路段指标解释为完整的网络进入条件。")

        limited = bool(limitations)
        return DataHealth(
            source_id, "vector", "limited" if limited else "ready",
            {
                "record_count": len(records),
                "valid_geometry_count": len(valid),
                "invalid_geometry_ratio": round(invalid_ratio, 6),
                "record_id_unique_ratio": round(unique_ratio, 6),
                "property_complete_ratio": round(property_ratio, 6),
                "coordinate_valid_ratio": round(coordinate_valid_count / len(valid), 6),
                "expected_geometry_ratio": round(expected_type_count / len(valid), 6),
                "scope_intersection_count": scope_intersection_count,
                "required_attribute_missing_count": missing_required_attribute_count,
                "road_connected_ratio": road_connected_ratio,
                "geometry_types": sorted({record.geometry.geom_type for record in valid if record.geometry is not None}),
                "coordinate_system": "wgs84",
                "year": data_year,
            },
            limitations[:1],
            metric_ids,
            [],
        )

    @staticmethod
    def _nightlight_spatial_analysis(layer: dict[str, Any]) -> dict[str, Any]:
        """Expose nightlight as a brightness pattern, never as economic activity.

        The shared nightlight module also powers legacy experiences that use
        economic-activity labels.  The Spatial Business Analyst must keep its
        proxy boundary at the domain edge, so its reusable evidence contains
        only brightness distribution, hotspots, gradients, and directionality.
        """
        analysis = _mapping(layer.get("analysis"))
        safe = {
            key: value
            for key, value in analysis.items()
            if not str(key).startswith("economic_activity_")
        }
        level = analysis.get("economic_activity_intensity_level")
        if level not in (None, ""):
            safe["night_brightness_spatial_level"] = str(level)
        sector = _mapping(analysis.get("sector_direction_analysis"))
        direction = str(sector.get("dominant_direction") or "").strip()
        if direction:
            safe["night_brightness_distribution_note"] = f"夜间亮度高值相对集中于{direction}方向。"
        return safe

    @staticmethod
    def _raster_status(*, valid_cell_count: int, total_cell_count: int) -> tuple[str, float, float]:
        total = max(0, int(total_cell_count))
        valid = max(0, int(valid_cell_count))
        if not valid:
            return "unavailable", 0.0, 1.0
        coverage_ratio = min(1.0, valid / total) if total else 1.0
        nodata_ratio = max(0.0, 1.0 - coverage_ratio)
        status = "limited" if coverage_ratio < 0.6 or nodata_ratio > 0.4 else "ready"
        return status, round(coverage_ratio, 6), round(nodata_ratio, 6)

    def _raster_health(self, *, source_id: str, history_detail: dict[str, Any], metric_ids: list[str]) -> DataHealth:
        polygon = history_detail.get("polygon")
        if not isinstance(polygon, list) or not polygon:
            return DataHealth(source_id, "raster", "unavailable", {"polygon_available": False, "record_count": None}, ["缺少可裁剪的分析范围。"], [], metric_ids)
        coordinate_system = self._history_coordinate_system(history_detail)
        try:
            if source_id == "current:dataset:population":
                overview = get_population_overview(polygon, coordinate_system, str(settings.population_data_year))
                grid = get_population_grid(polygon, coordinate_system, str(settings.population_data_year))
                total = int(grid.get("cell_count") or len(grid.get("features") or []))
                valid = sum(1 for feature in grid.get("features") or [] if isinstance(feature, dict) and feature.get("geometry"))
                status, coverage_ratio, nodata_ratio = self._raster_status(valid_cell_count=valid, total_cell_count=total)
                limitations = [] if status == "ready" else ["人口栅格裁剪后没有足够有效单元，不能用于当前范围的空间比较。"]
                return DataHealth(
                    source_id, "raster", status,
                    {"adapter_readable": True, "record_count": None, "year": int(settings.population_data_year), "valid_cell_count": valid, "total_cell_count": total, "coverage_ratio": coverage_ratio, "nodata_ratio": nodata_ratio, "total_population": (overview.get("summary") or {}).get("total_population")},
                    limitations, metric_ids if status != "unavailable" else [], [] if status != "unavailable" else metric_ids,
                )
            layer = get_nightlight_layer(polygon, coordinate_system, view="hotspot")
            summary = _mapping(layer.get("summary"))
            cells = [cell for cell in layer.get("cells") or [] if isinstance(cell, dict)]
            # `summary.valid_pixel_count` counts source-raster pixels, whereas
            # `cells` are interpolated analysis units. Health coverage must use
            # one unit on both sides of the ratio.
            valid = sum(
                1
                for cell in cells
                if bool(cell.get("has_data", int(cell.get("valid_pixel_count") or 0) > 0))
            )
            total = len(cells)
            status, coverage_ratio, nodata_ratio = self._raster_status(valid_cell_count=valid, total_cell_count=total)
            limitations = [] if status == "ready" else ["夜间亮度栅格裁剪后没有足够有效像元，不能形成亮度比较。"]
            return DataHealth(
                source_id, "raster", status,
                {"adapter_readable": True, "record_count": None, "year": layer.get("year"), "valid_cell_count": valid, "total_cell_count": total, "coverage_ratio": coverage_ratio, "nodata_ratio": nodata_ratio, "aggregated_cell_count": total},
                limitations, metric_ids if status != "unavailable" else [], [] if status != "unavailable" else metric_ids,
            )
        except Exception as exc:
            return DataHealth(source_id, "raster", "unavailable", {"adapter_readable": False, "record_count": None}, [f"栅格读取或裁剪失败：{type(exc).__name__}。"], [], metric_ids)

    def data_health(self, *, history_id: str, history_detail: dict[str, Any], tool_ids: list[str] | None = None) -> list[DataHealth]:
        """Check only the sources relevant to requested metrics, without exposing adapter internals upstream."""
        _, loaded, selected_years = self._load_snapshot(history_id)
        metric_ids = list(tool_ids or self.executable_metric_ids())
        scope_geometry = self._project_scope_geometry(history_detail)
        by_source: dict[str, list[str]] = {}
        for metric_id in metric_ids:
            for source_id in self._metric_source_ids(metric_id):
                by_source.setdefault(source_id, []).append(metric_id)
        results: list[DataHealth] = []
        for source_id, source_metrics in sorted(by_source.items()):
            if source_id in {"current:dataset:population", "current:dataset:nightlight"}:
                results.append(self._raster_health(source_id=source_id, history_detail=history_detail, metric_ids=source_metrics))
            elif source_id in {"history:isochrone", "document:project-extracts"}:
                results.append(DataHealth(source_id, "reference", "ready", {"available": True}, [], source_metrics, []))
            else:
                results.append(self._record_health(
                    source_id,
                    loaded.get(source_id, []),
                    source_metrics,
                    scope_geometry=scope_geometry,
                    data_year=selected_years.get(source_id),
                ))
        return results

    @staticmethod
    def _target_coordinate(target: dict[str, Any]) -> tuple[float, float] | None:
        value = target.get("coordinates") or target.get("coordinate") or target.get("center")
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                return float(value[0]), float(value[1])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _haversine_m(left: tuple[float, float], right: tuple[float, float]) -> float:
        lon1, lat1, lon2, lat2 = map(radians, (left[0], left[1], right[0], right[1]))
        a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
        return 6371008.8 * 2 * asin(sqrt(a))

    @staticmethod
    def _numeric_record_value(record: ScopeRecord, tool_id: str) -> float:
        properties = record.properties or {}
        metric_candidates = {
            "road.integration": ("road_integration", "integration_score", "integration_global"),
            "road.choice": ("road_choice", "choice_score", "choice_global"),
            "road.connectivity": ("road_connectivity", "connectivity_score"),
            "road.mean_depth": ("road_depth", "depth_score", "depth_global"),
            "road.degree": ("degree_score",),
            "road.node_degree": ("road_connectivity", "connectivity_score"),
            "road.control": ("road_control", "control_score", "control_global"),
            "road.intelligibility": ("intelligibility_score",),
            "poi.local_entropy": ("local_entropy",),
            "poi.local_entropy_normalized": ("local_entropy",),
            "poi.neighbor_mean_density": ("neighbor_mean_density",),
            "poi.neighbor_mean_entropy": ("neighbor_mean_entropy",),
            "spatial.neighbor_density_delta": ("density_poi_per_km2",),
        }
        candidates = metric_candidates.get(tool_id, ("density_poi_per_km2", "density", "poi_density", "count", "poi_count", "value", "score"))
        for key in candidates:
            value = _number(properties.get(key))
            if value is not None:
                return value
        return 1.0

    @staticmethod
    def _comparison_records(
        *,
        tool_id: str,
        source_id: str,
        loaded: dict[str, list[ScopeRecord]],
    ) -> tuple[list[ScopeRecord], str, str]:
        """Choose the most meaningful existing internal units for one-area comparison.

        Candidate ranges should aggregate the source the metric actually measures.
        A single project area is different: raw POI points or road segments are not a
        useful comparison grid by themselves. Prefer the project snapshot's aligned
        grids (or H3 cells) so the writer receives comparable spatial units.
        """
        if tool_id.startswith("road."):
            preferred = ("current:dataset:road_grid", "current:dataset:h3", source_id)
        elif tool_id.startswith(("poi.", "spatial.", "grid.")):
            preferred = ("current:dataset:poi_grid", "current:dataset:h3", source_id)
        else:
            preferred = (source_id,)
        for comparison_source_id in dict.fromkeys(item for item in preferred if item):
            units = loaded.get(comparison_source_id) or []
            if not units:
                continue
            unit = (
                "h3_cell"
                if comparison_source_id.endswith(":h3")
                else "project_grid_cell"
                if comparison_source_id.endswith("_grid")
                else "source_record"
            )
            return units, comparison_source_id, unit
        return [], source_id, "source_record"

    def _raster_comparison_cells(
        self,
        *,
        source_id: str,
        history_detail: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int | None, str]:
        """Return normalized raster cells as project-internal comparison units.

        Population and nightlight are runtime rasters, not rows in the scope
        database.  Converting their already clipped cells here lets the same
        candidate and in-area comparison mechanism work without pretending a
        raster has a record count.
        """
        polygon = history_detail.get("polygon")
        if not isinstance(polygon, list) or not polygon:
            return [], None, ""
        coordinate_system = self._history_coordinate_system(history_detail)
        try:
            population_grid = get_population_grid(polygon, coordinate_system, str(settings.population_data_year))
            coordinate_by_cell = {
                str((feature.get("properties") or {}).get("cell_id") or ""): list((feature.get("properties") or {}).get("centroid_gcj02") or [])
                for feature in population_grid.get("features") or []
                if isinstance(feature, dict)
            }
            if source_id == "current:dataset:population":
                layer = get_population_layer(polygon, coordinate_system, str(settings.population_data_year), view="density")
                raw_cells = [cell for cell in layer.get("cells") or [] if isinstance(cell, dict)]
                year: int | None = int(settings.population_data_year)
                label = "人口栅格单元"
                valid = lambda cell: _number(cell.get("value")) is not None
            else:
                layer = get_nightlight_layer(polygon, coordinate_system, view="radiance")
                raw_cells = [cell for cell in layer.get("cells") or [] if isinstance(cell, dict)]
                year_value = layer.get("year")
                year = int(year_value) if year_value not in (None, "") else None
                label = "夜间亮度栅格单元"
                valid = lambda cell: bool(cell.get("has_data", int(cell.get("valid_pixel_count") or 0) > 0))

            cells: list[dict[str, Any]] = []
            for cell in raw_cells:
                cell_id = str(cell.get("cell_id") or "").strip()
                centroid_gcj02 = coordinate_by_cell.get(cell_id) or []
                if len(centroid_gcj02) < 2 or not valid(cell):
                    continue
                value = _number(cell.get("value"))
                if value is None:
                    continue
                lon, lat = gcj02_to_wgs84(float(centroid_gcj02[0]), float(centroid_gcj02[1]))
                cells.append({"unit_id": cell_id, "coordinate": [lon, lat], "value": round(value, 6)})
            return cells, year, label
        except Exception:
            return [], None, ""

    def _project_internal_comparison(
        self,
        *,
        tool_id: str,
        history_id: str,
        history_detail: dict[str, Any],
        project_anchors: dict[str, Any],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Build same-parameter candidate or project-cell comparisons.

        This creates an explicit *project internal* baseline. It deliberately
        does not rank against a guessed city or industry benchmark.
        """
        source_ids = self._metric_source_ids(tool_id)
        source_id = next((item for item in source_ids if item.startswith("current:dataset:")), "")
        _, loaded, selected_years = self._load_snapshot(history_id)
        records = loaded.get(source_id, [])
        raster_cells: list[dict[str, Any]] = []
        data_year = selected_years.get(source_id)
        unit_label = "existing_grid_or_record"
        if source_id in {"current:dataset:population", "current:dataset:nightlight"}:
            raster_cells, data_year, unit_label = self._raster_comparison_cells(source_id=source_id, history_detail=history_detail)

        targets = [target for target in (project_anchors.get("candidate_targets") or []) if isinstance(target, dict)]
        spatial_targets = [(target, self._target_coordinate(target)) for target in targets]
        spatial_targets = [(target, coordinate) for target, coordinate in spatial_targets if coordinate]
        radius_m = max(50, int(_number(parameters.get("radius_m")) or 800))

        if len(spatial_targets) >= 2 and (records or raster_cells):
            area_sq_km = 3.141592653589793 * (radius_m / 1000) ** 2
            rows = []
            for target, coordinate in spatial_targets:
                values: list[float] = []
                if raster_cells:
                    values = [
                        float(cell["value"]) for cell in raster_cells
                        if self._haversine_m(coordinate, (float(cell["coordinate"][0]), float(cell["coordinate"][1]))) <= radius_m
                    ]
                    value = round(sum(values) / len(values), 6) if values else None
                    normalized_value = value
                else:
                    for record in records:
                        geometry = record.geometry
                        if geometry is None or geometry.is_empty:
                            continue
                        centroid = geometry.centroid
                        if self._haversine_m(coordinate, (centroid.x, centroid.y)) <= radius_m:
                            values.append(self._numeric_record_value(record, tool_id))
                    value = round(sum(values), 6)
                    normalized_value = round(value / area_sq_km, 6)
                rows.append({
                    "target_id": target.get("target_id"),
                    "label": target.get("label") or target.get("target_id"),
                    "value": value,
                    "normalized_value": normalized_value,
                    "matched_unit_count": len(values),
                })
            comparable = [float(row["normalized_value"]) for row in rows if row["normalized_value"] is not None]
            aggregation = "范围内有效栅格单元均值" if raster_cells else "范围内值按每平方公里归一化"
            return {
                "mode": "candidate_uniform_buffer",
                "comparison_design": project_anchors.get("comparison_design") or "同半径候选范围比较",
                "parameters": {"radius_m": radius_m, "data_year": data_year, "source_id": source_id, "normalization": aggregation, "spatial_range_type": "uniform_buffer_approximation"},
                "comparison_table": rows,
                "main_differences": [f"当前候选对象的同口径比较值范围为 {min(comparable):.3f}–{max(comparable):.3f}，只表示本项目对照组内的空间差异。"] if comparable else [],
                "spatial_assets": [],
                "interpretation_prompts": ["该范围使用同半径缓冲近似；应与可达性和现场条件共同解释，不把数值差异直接升级为经营结果。"],
            }

        if raster_cells:
            rows = [
                {"unit_id": cell["unit_id"], "value": cell["value"], "coordinate": cell["coordinate"]}
                for cell in raster_cells[:200]
            ]
            numeric = [float(row["value"]) for row in rows]
            return {
                "mode": "project_internal_cells",
                "comparison_design": project_anchors.get("comparison_design") or "分析范围内部同源栅格单元比较",
                "parameters": {"source_id": source_id, "data_year": data_year, "unit": unit_label, "normalization": "同一裁剪范围、同一栅格与同一数据年份"},
                "comparison_table": rows,
                "main_differences": [f"当前范围内 {len(rows)} 个可比较栅格单元的值范围为 {min(numeric):.3f}–{max(numeric):.3f}。"] if numeric else [],
                "spatial_assets": [],
                "interpretation_prompts": ["把栅格差异理解为分析范围内的分布与踏勘优先级，不把它解释为实际消费、客流或收益。"],
            }

        comparison_records, comparison_source_id, comparison_unit = self._comparison_records(
            tool_id=tool_id,
            source_id=source_id,
            loaded=loaded,
        )
        if comparison_records:
            rows = []
            for record in comparison_records[:200]:
                geometry = record.geometry
                rows.append({"unit_id": record.record_id, "value": self._numeric_record_value(record, tool_id), "geometry": _geojson(geometry) if geometry is not None else None})
            numeric = [row["value"] for row in rows]
            source_year = selected_years.get(comparison_source_id, data_year)
            return {
                "mode": "project_internal_cells",
                "comparison_design": project_anchors.get("comparison_design") or "分析范围内部同源空间单元比较",
                "parameters": {
                    "source_id": source_id,
                    "comparison_source_id": comparison_source_id,
                    "data_year": source_year,
                    "unit": comparison_unit,
                    "normalization": "沿用同一快照、同一内部空间单元和同一指标参数",
                },
                "comparison_table": rows,
                "main_differences": [f"当前范围内 {len(rows)} 个可比较空间单元的值范围为 {min(numeric):.3f}–{max(numeric):.3f}。"] if numeric else [],
                "spatial_assets": [],
                "interpretation_prompts": ["把内部单元差异理解为踏勘或服务场景核查优先级，而不是外部市场排名。"],
            }
        return {
            "mode": "not_available",
            "comparison_design": project_anchors.get("comparison_design") or "项目内部比较",
            "comparison_table": [],
            "main_differences": [],
            "spatial_assets": [],
            "interpretation_prompts": ["当前指标没有可生成内部对照的空间单元；保留原始事实并补充可比较的候选对象或网格。"],
        }

    def execute_metric_tool(
        self,
        *,
        tool_id: str,
        primary_spatial_unit: str,
        history_id: str,
        history_detail: dict[str, Any],
        project_documents: dict[str, Any],
        project_anchors: dict[str, Any] | None = None,
        comparison_design: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> MetricToolExecution:
        """Run one chosen V4 tool and expose only its reusable result semantics."""

        if tool_id == "regional.directional_evidence_matrix":
            return self._execute_directional_evidence_matrix(
                history_id=history_id,
                history_detail=history_detail,
                parameters=parameters or {},
            )
        if tool_id == "poi.focused_accessibility":
            return self._execute_focused_poi_accessibility(
                history_id=history_id,
                history_detail=history_detail,
                parameters=parameters or {},
            )

        if tool_id == "poi.supply_structure":
            return self._execute_poi_supply_structure(
                history_id=history_id,
                history_detail=history_detail,
                parameters=parameters or {},
            )

        analysis = self.analyze_history_snapshot(
            history_id=history_id,
            history_detail=history_detail,
            project_documents=project_documents,
            decision_questions=[],
            metric_plan_entries=[
                {
                    "plan_entry_id": f"tool:{tool_id}",
                    "metric_id": tool_id,
                    "role": "primary",
                    "planned_spatial_target": {
                        "unit": primary_spatial_unit,
                        "source": "current-snapshot",
                    },
                    "required_source_ids": [],
                }
            ],
            project_anchors=project_anchors or {},
        )
        attempt = next(
            (item for item in analysis.metric_attempts if item.get("metric_id") == tool_id),
            {},
        )
        result_ids = {str(value) for value in attempt.get("evidence_node_ids") or []}
        outputs = [item for item in analysis.evidence_nodes if str(item.get("id")) in result_ids]
        if attempt.get("execution_status") != "succeeded" or not outputs:
            reason = str(attempt.get("reason") or "当前分析范围内没有可用指标结果。")
            return MetricToolExecution(
                tool_id=tool_id,
                status="unavailable",
                summary=reason,
                limitations=[reason],
            )
        input_sources = sorted(
            {
                str(source)
                for item in outputs
                for source in item.get("source_ids") or item.get("source_refs") or []
            }
        )
        health = self.data_health(history_id=history_id, history_detail=history_detail, tool_ids=[tool_id])
        limitations = [limitation for item in health for limitation in item.limitations]
        limitations.extend(
            str(limitation)
            for item in outputs
            for limitation in _mapping(item.get("data")).get("limitations") or []
            if str(limitation).strip()
        )
        comparison = self._project_internal_comparison(
            tool_id=tool_id,
            history_id=history_id,
            history_detail=history_detail,
            project_anchors={**(project_anchors or {}), "comparison_design": comparison_design or (project_anchors or {}).get("comparison_design", "")},
            parameters=parameters or {},
        )
        structured = {str(item.get("id")): dict(item.get("data") or {}) for item in outputs}
        structured["project_internal_comparison"] = comparison
        structured["data_health"] = [item.model_dump() for item in health]
        return MetricToolExecution(
            tool_id=tool_id,
            status="available",
            summary="；".join(str(item.get("summary") or item.get("title") or tool_id) for item in outputs),
            structured_result=structured,
            input_sources=input_sources,
            limitations=limitations + ["指标结果用于空间条件判断，不能单独外推消费、客流、营收或投资回报。"],
        )

    def _execute_poi_supply_structure(
        self,
        *,
        history_id: str,
        history_detail: dict[str, Any],
        parameters: dict[str, Any],
    ) -> MetricToolExecution:
        """Audit selected POI supply against the saved 15-minute walking polygon."""
        isochrone, scope_or_reason = self._verified_fifteen_minute_walking_isochrone(history_detail)
        if isochrone is None:
            return MetricToolExecution(
                tool_id="poi.supply_structure",
                status="unavailable",
                summary="POI 供给结构缺少可核验的 15 分钟步行等时圈，未用 POI 快照声明替代几何核验。",
                input_sources=["current:dataset:poi", "history:walking_isochrone"],
                limitations=[str(scope_or_reason)],
            )
        geometry = self._focused_analysis_geometry(history_detail)
        _, loaded, selected_years = self._load_snapshot(history_id)
        poi_records = loaded.get("current:dataset:poi", [])
        road_records = loaded.get("current:dataset:road_edges", [])
        if not poi_records:
            return MetricToolExecution(
                tool_id="poi.supply_structure",
                status="unavailable",
                summary="POI 供给结构缺少当前 POI 数据快照。",
                input_sources=["current:dataset:poi", "history:walking_isochrone"],
                limitations=["没有可用于逐点等时圈核验的真实 POI 记录。"],
            )
        candidates = [candidate for record in poi_records if (candidate := self._supply_poi_candidate(record)) is not None]
        if not candidates:
            return MetricToolExecution(
                tool_id="poi.supply_structure",
                status="unavailable",
                summary="当前 POI 快照没有带真实类别的记录，无法形成供给结构。",
                input_sources=["current:dataset:poi", "history:walking_isochrone"],
                limitations=["不从名称或假设类别推断供给结构。"],
            )

        router = None
        road_diagnostic = None
        if road_records:
            try:
                router = LocalRoadNetworkRouter([record.geometry for record in road_records if record.geometry is not None])
            except RoadNetworkRoutingUnavailable as exc:
                road_diagnostic = f"保存路网不可用于五分钟连续道路可达性：{exc}"
        else:
            road_diagnostic = "当前没有保存路网；图中将只展示 15 分钟等时圈内 POI。"

        result = PoiSupplyStructureService(router).analyze(
            analysis_geometry=geometry,
            isochrone_geometry=isochrone,
            raw_groups=parameters.get("groups"),
            pois=candidates,
        )
        serialized = self._serialize_poi_supply_structure_result(result)
        serialized.update({
            "year": selected_years.get("current:dataset:poi"),
            "source_id": "current:dataset:poi",
            "scope": scope_or_reason,
        })
        input_sources = ["current:dataset:poi", "history:walking_isochrone"]
        if road_records:
            input_sources.append("current:dataset:road_edges")
        if result.status == "unavailable":
            return MetricToolExecution(
                tool_id="poi.supply_structure",
                status="unavailable",
                summary="没有通过分类与等时圈核验的 POI 供给结构可用于图表。",
                structured_result={"poi_supply_structure": serialized},
                input_sources=input_sources,
                limitations=list(result.diagnostics) or [result.error_reason or "等时圈内没有可映射的已选 POI。"],
            )
        accessible_groups = [group for group in result.groups if group.nearby_5_min_poi_count is not None]
        availability = "available" if result.status == "available" else "partial"
        return MetricToolExecution(
            tool_id="poi.supply_structure",
            status=availability,
            summary=(
                f"已对 {len(result.classified_rows)} 个真实 POI 附属类完成 15 分钟步行等时圈几何核验；"
                f"其中 {len(accessible_groups)} 个已选类型组同时具备五分钟连续道路可达统计。"
            ),
            structured_result={"poi_supply_structure": serialized},
            input_sources=input_sources,
            limitations=[
                *result.diagnostics,
                *([road_diagnostic] if road_diagnostic else []),
                "深色数量仅是经 15 分钟等时圈几何核验后的 POI；五分钟数量仅表示保存道路网络连续可达记录，不表示客流、消费、经营质量、市场规模、合作关系或项目定位定案。",
            ],
        )

    @staticmethod
    def _verified_fifteen_minute_walking_isochrone(history_detail: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | str]:
        params = history_detail.get("params") if isinstance(history_detail.get("params"), dict) else {}
        try:
            time_min = int(params.get("time_min"))
        except (TypeError, ValueError):
            time_min = None
        mode = str(params.get("mode") or "").strip().lower()
        if time_min != 15 or mode != "walking":
            return None, "当前保存范围不是 15 分钟 walking 等时圈，供给图不会把其他范围混作 15 分钟口径。"
        raw = history_detail.get("polygon_wgs84") or history_detail.get("result_polygon") or history_detail.get("polygon")
        if isinstance(raw, dict) and raw.get("type") in {"Polygon", "MultiPolygon"}:
            geometry = raw
        elif isinstance(raw, list) and raw:
            geometry = {"type": "Polygon", "coordinates": [raw]}
        else:
            return None, "缺少有效的 WGS84 等时圈 Polygon/MultiPolygon 几何。"
        return geometry, {
            "kind": "verified_walking_isochrone",
            "time_min": 15,
            "mode": "walking",
            "geometry_source": "history.result_polygon_wgs84",
            "geometry_type": geometry.get("type"),
            "point_inclusion_method": "covers",
            "description": "每个 POI 点位均以 saved 15 分钟 walking 等时圈 Polygon/MultiPolygon 的 covers 关系核验。",
        }

    def _execute_focused_poi_accessibility(
        self,
        *,
        history_id: str,
        history_detail: dict[str, Any],
        parameters: dict[str, Any],
    ) -> MetricToolExecution:
        """Route approved POI groups across the saved local road snapshot.

        The output contains only paths assembled from ``current:dataset:road_edges``.
        It deliberately has no third-party route call, key, endpoint, or straight-line
        fallback.  The visual layer receives route geometry only through the
        structured metric result, never through a free-form map request.
        """
        groups = self._focused_poi_groups(parameters.get("groups"))
        if not groups:
            return MetricToolExecution(
                tool_id="poi.focused_accessibility",
                status="unavailable",
                summary="重点 POI 步行可达性需要报告已审校的 POI 类型组；未提供时不猜测使用场景。",
                limitations=["缺少参数 groups，且不会以 POI 密度或直线距离替代本地路网路径。"],
            )
        geometry = self._focused_analysis_geometry(history_detail)
        if geometry is None:
            return MetricToolExecution(
                tool_id="poi.focused_accessibility",
                status="unavailable",
                summary="当前项目正式范围不可用，无法从项目多边形几何中心点计算本地路网路径。",
                limitations=["缺少有效的 Polygon 或 MultiPolygon 分析范围。"],
            )
        _, loaded, selected_years = self._load_snapshot(history_id)
        poi_records = loaded.get("current:dataset:poi", [])
        road_records = loaded.get("current:dataset:road_edges", [])
        if not poi_records or not road_records:
            missing = [label for label, records in (("POI", poi_records), ("路网", road_records)) if not records]
            return MetricToolExecution(
                tool_id="poi.focused_accessibility",
                status="unavailable",
                summary="重点 POI 本地路网可达性缺少必要来源：" + "、".join(missing) + "。",
                input_sources=["current:dataset:poi", "current:dataset:road_edges", "scope:analysis"],
                limitations=["路径必须来自当前保存的 road_edges；不使用直线、速度估算或在线路由替代。"],
            )
        pois = [self._focused_poi_candidate(record) for record in poi_records]
        candidates = [poi for poi in pois if poi is not None]
        if not candidates:
            return MetricToolExecution(
                tool_id="poi.focused_accessibility",
                status="unavailable",
                summary="当前 POI 快照没有可用于本地路网计算的有效地点坐标。",
                input_sources=["current:dataset:poi", "current:dataset:road_edges"],
                limitations=["POI 地点坐标不可用；没有用名称、类别或直线距离生成替代结果。"],
            )
        try:
            router = LocalRoadNetworkRouter([record.geometry for record in road_records if record.geometry is not None])
        except RoadNetworkRoutingUnavailable as exc:
            return MetricToolExecution(
                tool_id="poi.focused_accessibility",
                status="unavailable",
                summary="当前路网快照无法建立本地步行路径网络。",
                input_sources=["current:dataset:poi", "current:dataset:road_edges", "scope:analysis"],
                limitations=[f"路网建图未通过：{exc}"],
            )

        result = FocusedPoiAccessibilityService(router).analyze(analysis_geometry=geometry, groups=groups, pois=candidates)
        serialized = self._serialize_focused_poi_result(result)
        serialized["year"] = selected_years.get("current:dataset:poi")
        if result.origin:
            route_geometries = [poi.route_geometry for group in result.groups for poi in group.pois if poi.route_geometry_status == "available"]
            if route_geometries:
                try:
                    serialized["map_context"] = build_route_map_context(
                        analysis_geometry=geometry,
                        origin=result.origin,
                        route_geometries=route_geometries,
                        road_records=road_records,
                    )
                except RoadNetworkRoutingUnavailable as exc:
                    serialized["map_context"] = {"status": "unavailable", "omission_reason": str(exc)}
        if result.status == "error":
            reason = result.error_reason or "analysis_geometry_invalid"
            return MetricToolExecution(
                tool_id="poi.focused_accessibility",
                status="unavailable",
                summary="分析范围无法用于重点 POI 本地路网计算。",
                structured_result={"focused_poi_accessibility": serialized},
                input_sources=["current:dataset:poi", "current:dataset:road_edges", "scope:analysis"],
                limitations=[f"范围校验未通过：{reason}"],
            )
        available_groups = [group for group in result.groups if group.status == "available" and group.pois]
        omissions = [f"{group.title}：{group.omission_reason or 'no_local_road_path'}" for group in result.groups if group.status == "omitted"]
        if not available_groups:
            return MetricToolExecution(
                tool_id="poi.focused_accessibility",
                status="unavailable",
                summary="未形成沿当前路网的重点 POI 路径；没有使用直线或替代路线。",
                structured_result={"focused_poi_accessibility": serialized},
                input_sources=["current:dataset:poi", "current:dataset:road_edges", "scope:analysis"],
                limitations=omissions or ["保存的路网中没有形成可达路径。"],
            )
        return MetricToolExecution(
            tool_id="poi.focused_accessibility",
            status="available",
            summary=f"从项目多边形几何中心点沿当前路网计算 {len(available_groups)} 个重点 POI 类型组，共 {sum(len(group.pois) for group in available_groups)} 个真实地点的最短路径。",
            structured_result={"focused_poi_accessibility": serialized},
            input_sources=["current:dataset:poi", "current:dataset:road_edges", "scope:analysis"],
            limitations=[
                *omissions,
                "距离来自当前路网快照上的本地最短路径；分钟按统一 4.5 km/h 参考步行速度换算。结果不表示合作关系、客流导入、消费转化、经营质量或市场规模。",
            ],
        )

    @staticmethod
    def _focused_poi_groups(raw_groups: Any) -> list[FocusedPoiTypeGroup]:
        if not isinstance(raw_groups, list):
            return []
        groups: list[FocusedPoiTypeGroup] = []
        for index, raw in enumerate(raw_groups[:4]):
            if not isinstance(raw, dict):
                continue
            type_codes = raw.get("type_codes") or raw.get("typecodes") or raw.get("type_code")
            if isinstance(type_codes, str):
                normalized_codes = tuple(part.strip() for part in type_codes.split("|") if part.strip())
            elif isinstance(type_codes, (list, tuple)):
                normalized_codes = tuple(str(part).strip() for part in type_codes if str(part).strip())
            else:
                normalized_codes = ()
            groups.append(FocusedPoiTypeGroup(
                group_id=str(raw.get("group_id") or raw.get("id") or f"group-{index + 1}").strip(),
                title=str(raw.get("title") or raw.get("label") or "").strip(),
                role=str(raw.get("role") or "").strip(),
                type_codes=normalized_codes,
                statement_ref=str(raw.get("statement_ref") or "").strip(),
            ))
        return groups

    def _focused_analysis_geometry(self, history_detail: dict[str, Any]) -> dict[str, Any] | None:
        raw = history_detail.get("analysis_geometry")
        if not isinstance(raw, dict):
            polygon = history_detail.get("polygon")
            raw = {"type": "Polygon", "coordinates": [polygon]} if isinstance(polygon, list) and polygon else None
        if not isinstance(raw, dict) or raw.get("type") not in {"Polygon", "MultiPolygon"}:
            return None
        try:
            geometry = shape(raw)
            if self._history_coordinate_system(history_detail) == "gcj02":
                geometry = shapely_transform(
                    lambda x, y, z=None: gcj02_to_wgs84(float(x), float(y)),
                    geometry,
                )
            if geometry.is_empty:
                return None
            return _geojson(geometry)
        except Exception:
            return None

    @staticmethod
    def _focused_poi_candidate(record: ScopeRecord) -> FocusedPoiCandidate | None:
        geometry = record.geometry
        if geometry is None or geometry.is_empty:
            return None
        point = geometry.centroid
        try:
            location = (float(point.x), float(point.y))
        except (TypeError, ValueError):
            return None
        raw = record.raw if isinstance(record.raw, dict) else {}
        properties = record.properties if isinstance(record.properties, dict) else {}
        poi_type = (
            raw.get("typecode") or raw.get("type") or raw.get("category")
            or properties.get("typecode") or properties.get("type") or properties.get("category")
        )
        return FocusedPoiCandidate(
            poi_id=str(record.record_id),
            name=str(raw.get("name") or record.title or "").strip(),
            poi_type=str(poi_type).strip() if poi_type not in (None, "") else None,
            location=location,
            address=str(raw.get("address") or properties.get("address") or "").strip() or None,
        )

    @staticmethod
    def _supply_poi_candidate(record: ScopeRecord) -> PoiSupplyCandidate | None:
        raw = record.raw if isinstance(record.raw, dict) else {}
        properties = record.properties if isinstance(record.properties, dict) else {}
        poi_type = (
            raw.get("typecode") or raw.get("type") or raw.get("category")
            or properties.get("typecode") or properties.get("type") or properties.get("category")
        )
        normalized_type = str(poi_type).strip() if poi_type not in (None, "") else None
        if normalized_type is None:
            return None
        geometry = record.geometry
        location = None
        if geometry is not None and not geometry.is_empty:
            point = geometry.centroid
            try:
                location = (float(point.x), float(point.y))
            except (TypeError, ValueError):
                location = None
        return PoiSupplyCandidate(poi_id=str(record.record_id), poi_type=normalized_type, location=location)

    @staticmethod
    def _serialize_poi_supply_structure_result(result: Any) -> dict[str, Any]:
        return {
            "status": result.status,
            "origin": list(result.origin) if result.origin else None,
            "routing_algorithm": "local_road_network_shortest_path",
            "duration_method": "road_network_length_at_4_5_km_per_hour",
            "nearby_threshold_seconds": 300,
            "groups": [
                {
                    "group_id": group.group_id,
                    "title": group.title,
                    "role": group.role,
                    "statement_ref": group.statement_ref,
                    "requested_type_codes": list(group.requested_type_codes),
                    "matched_type_codes": list(group.matched_type_codes),
                    "status": group.status,
                    "isochrone_poi_count": group.isochrone_poi_count,
                    "nearby_5_min_poi_count": group.nearby_5_min_poi_count,
                    "route_status": group.route_status,
                    "routable_candidate_count": group.routable_candidate_count,
                    "unroutable_poi_count": group.unroutable_poi_count,
                    "omission_reason": group.omission_reason,
                }
                for group in result.groups
            ],
            "classified_rows": [
                {
                    "role": row.role,
                    "main_category": row.main_category,
                    "subcategory": row.subcategory,
                    "isochrone_poi_count": row.isochrone_poi_count,
                    "nearby_5_min_poi_count": row.nearby_5_min_poi_count,
                    "selected_type_codes": list(row.selected_type_codes),
                    "source_group_ids": list(row.source_group_ids),
                    "statement_refs": list(row.statement_refs),
                }
                for row in result.classified_rows
            ],
            "taxonomy_audit": {
                "source": "share/type_map.json",
                "unmapped_type_codes": list(result.audit.unmapped_type_codes),
                "unmapped_poi_count": result.audit.unmapped_poi_count,
            },
            "isochrone_audit": {
                "included_poi_count": result.audit.isochrone_included_poi_count,
                "outside_isochrone_poi_count": result.audit.outside_isochrone_poi_count,
                "missing_coordinate_poi_count": result.audit.missing_coordinate_poi_count,
                "invalid_coordinate_poi_count": result.audit.invalid_coordinate_poi_count,
            },
            "five_minute_accessibility_status": result.audit.five_minute_accessibility_status,
            "diagnostics": list(result.diagnostics),
            "error_reason": result.error_reason,
        }

    @staticmethod
    def _serialize_focused_poi_result(result: Any) -> dict[str, Any]:
        return {
            "status": result.status,
            "origin": list(result.origin) if result.origin else None,
            "routing_algorithm": "local_road_network_shortest_path",
            "duration_method": "road_network_length_at_4_5_km_per_hour",
            "groups": [
                {
                    "group_id": group.group_id,
                    "title": group.title,
                    "role": group.role,
                    "status": group.status,
                    "matched_type_codes": list(group.matched_type_codes),
                    "statement_ref": group.statement_ref,
                    "candidates_considered": group.candidates_considered,
                    "route_failures": group.route_failures,
                    "omission_reason": group.omission_reason,
                    "pois": [
                        {
                            "id": poi.poi_id,
                            "name": poi.name,
                            "type": poi.poi_type,
                            "category": poi.poi_type,
                            "address": poi.address,
                            "location": list(poi.location),
                            "walking_distance_m": round(poi.walking_distance_m, 1),
                            "walking_duration_s": round(poi.walking_duration_s, 1),
                            "route_status": "available",
                            "route_geometry": poi.route_geometry,
                            "route_geometry_status": poi.route_geometry_status,
                            "route_length_m": round(poi.route_length_m, 1),
                            "origin_snap": list(poi.origin_snap),
                            "destination_snap": list(poi.destination_snap),
                            "origin_snap_distance_m": round(poi.origin_snap_distance_m, 1),
                            "destination_snap_distance_m": round(poi.destination_snap_distance_m, 1),
                            "routing_algorithm": poi.routing_algorithm,
                        }
                        for poi in group.pois
                    ],
                }
                for group in result.groups
            ],
            "diagnostics": list(result.diagnostics),
        }

    def _execute_directional_evidence_matrix(
        self,
        *,
        history_id: str,
        history_detail: dict[str, Any],
        parameters: dict[str, Any],
    ) -> MetricToolExecution:
        """Build the one cross-source result used for directional portrait evidence."""
        center = parameters.get("center")
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            return MetricToolExecution(
                tool_id="regional.directional_evidence_matrix",
                status="unavailable",
                summary="方向矩阵需要明确的 WGS84 分析中心。",
                limitations=["缺少必填参数 center。"],
            )
        polygon = history_detail.get("polygon")
        if not isinstance(polygon, list) or not polygon:
            return MetricToolExecution(
                tool_id="regional.directional_evidence_matrix",
                status="unavailable",
                summary="当前分析范围不可用，无法建立共同空间网格。",
                limitations=["缺少可裁剪的当前分析范围。"],
            )

        inventory, loaded, selected_years = self._load_snapshot(history_id)
        poi_records = loaded.get("current:dataset:poi", [])
        road_records = loaded.get("current:dataset:road_edges", [])
        if not poi_records or not road_records:
            missing = [label for label, records in (("POI", poi_records), ("路网", road_records)) if not records]
            return MetricToolExecution(
                tool_id="regional.directional_evidence_matrix",
                status="unavailable",
                summary="方向矩阵缺少必要来源：" + "、".join(missing) + "。",
                limitations=["共同网格要求 POI、人口、夜光和路网均可用；不以单源替代。"],
            )

        coordinate_system = self._history_coordinate_system(history_detail)
        try:
            nightlight_year = int(build_nightlight_meta_payload()["default_year"])
            shared = build_shared_grid_analysis(
                polygon=polygon,
                coord_type=coordinate_system,
                population_year=str(settings.population_data_year),
                nightlight_year=nightlight_year,
                pois=[dict(record.raw) for record in poi_records if isinstance(record.raw, dict)],
                poi_coord_type="wgs84",
                poi_year=selected_years.get("current:dataset:poi"),
                poi_ready=True,
                road_features=[
                    dict(record.raw.get("feature") or {})
                    for record in road_records
                    if isinstance(record.raw, dict) and isinstance(record.raw.get("feature"), dict)
                ],
                road_coord_type="wgs84",
                road_ready=True,
            )
            matrix = build_directional_evidence_matrix(
                shared,
                center_wgs84=[float(center[0]), float(center[1])],
                distance_bands_m=parameters.get("distance_bands_m"),
            )
        except (TypeError, ValueError, KeyError) as exc:
            return MetricToolExecution(
                tool_id="regional.directional_evidence_matrix",
                status="unavailable",
                summary="方向矩阵未形成：共同网格或参数不可用。",
                limitations=[f"方向矩阵数据边界：{exc}"],
            )

        health = self.data_health(
            history_id=history_id,
            history_detail=history_detail,
            tool_ids=[
                "poi.grid_density", "population.total", "nightlight.sector_profile", "road.integration",
            ],
        )
        health_limitations = [item for value in health for item in value.limitations]
        return MetricToolExecution(
            tool_id="regional.directional_evidence_matrix",
            status="available",
            summary=(
                f"以临时中心汇总 {matrix['overall_baseline']['cell_count']} 个共同网格单元，"
                f"形成 {len(matrix['rows'])} 个方向-距离带比较行；中心仅用于区域参照。"
            ),
            structured_result={
                "directional_evidence_matrix": matrix,
                "data_health": [item.model_dump() for item in health],
            },
            input_sources=[
                "current:dataset:poi",
                "current:dataset:population",
                "current:dataset:nightlight",
                "current:dataset:road_edges",
            ],
            limitations=health_limitations + list(matrix["limitations"]),
        )

    def _load_snapshot(self, history_id: str) -> tuple[dict[str, Any], dict[str, list[ScopeRecord]], dict[str, int | None]]:
        inventory = self._datasets.list_scope_datasets(history_id)
        available = {
            item["source_id"]: item
            for item in inventory.get("datasets", [])
            if item.get("status") == "ready"
        }
        loaded: dict[str, list[ScopeRecord]] = {}
        selected_years: dict[str, int | None] = {}
        for source_id in (
            "current:dataset:poi",
            "current:dataset:h3",
            "current:dataset:poi_grid",
            "current:dataset:road_edges",
            "current:dataset:road_grid",
        ):
            if source_id in available:
                records, _, selected_year = self._datasets.load_scope_records(
                    history_id=history_id, source_id=source_id
                )
                loaded[source_id] = records
                selected_years[source_id] = selected_year
        return inventory, loaded, selected_years

    @staticmethod
    def _source_versions(
        loaded: dict[str, list[ScopeRecord]],
        selected_years: dict[str, int | None],
        project_documents: dict[str, Any],
    ) -> list[dict[str, Any]]:
        sources = [
            {
                "source_id": source_id,
                "year": selected_years[source_id],
                "sha256": f"snapshot:{source_id}:{len(records)}:{selected_years[source_id]}",
                "record_count": len(records),
            }
            for source_id, records in loaded.items()
        ]
        sources.extend(
            [
                {"source_id": "history:isochrone", "sha256": "snapshot:history-isochrone", "record_count": 1},
                {
                    "source_id": "document:project-extracts",
                    "sha256": "snapshot:project-documents",
                    "record_count": len(project_documents.get("documents") or []),
                },
            ]
        )
        return sources

    @staticmethod
    def _external_source_versions() -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        try:
            population = run_population_runtime_check()
            if population.get("ok"):
                sources.append(
                    {
                        "source_id": "current:dataset:population",
                        "year": int(settings.population_data_year),
                        "sha256": f"runtime:population:{population.get('data_dir')}:{settings.population_data_year}",
                        "record_count": None,
                        "data_kind": "raster",
                        "health_hint": "runtime_readable; scope-specific valid_cell_count is checked before execution",
                    }
                )
        except Exception:
            pass
        try:
            nightlight = build_nightlight_meta_payload()
            sources.append(
                {
                    "source_id": "current:dataset:nightlight",
                    "year": int(nightlight["default_year"]),
                    "sha256": f"runtime:nightlight:{nightlight['default_year']}",
                    "record_count": None,
                    "data_kind": "raster",
                    "health_hint": "runtime_readable; scope-specific valid_cell_count is checked before execution",
                }
            )
        except Exception:
            pass
        return sources

    @staticmethod
    def _poi_preview(records: list[ScopeRecord]) -> dict[str, Any]:
        categories = Counter(
            str(record.properties.get("category") or record.properties.get("type") or "unknown")
            for record in records
        )
        return {
            "record_count": len(records),
            "category_count": len(categories),
            "top_categories": [
                {"category": category, "count": count}
                for category, count in categories.most_common(8)
            ],
        }

    @staticmethod
    def _history_coordinate_system(detail: dict[str, Any]) -> str:
        """Return the declared coordinate system for history geometry inputs.

        History repository records retain WGS84 geometry unless an explicit source
        declaration says otherwise. Raster adapters need this declaration so they
        do not silently shift a WGS84 analysis polygon as if it were GCJ-02.
        """
        params = detail.get("params") if isinstance(detail.get("params"), dict) else {}
        value = str(params.get("coord_type") or params.get("coordinate_system") or "wgs84").lower()
        return value if value in {"wgs84", "gcj02"} else "wgs84"

    def _coordinate_alignment(self, detail: dict[str, Any], anchors: dict[str, Any] | None) -> dict[str, Any]:
        params = detail.get("params") if isinstance(detail.get("params"), dict) else {}
        raw_center = params.get("center") or detail.get("center")
        declared = str(params.get("coord_type") or params.get("coordinate_system") or "wgs84").lower()
        center: list[float] | None = None
        if isinstance(raw_center, (list, tuple)) and len(raw_center) >= 2:
            lon, lat = float(raw_center[0]), float(raw_center[1])
            if declared == "gcj02":
                lon, lat = gcj02_to_wgs84(lon, lat)
            center = [lon, lat]
        return {"analysis_center": center, "analysis_center_declared_coordinate_system": declared, "normalized_coordinate_system": "wgs84", "metric_crs_policy": "所有距离、去重和路网关系都在本地投影米制坐标中计算。", "coordinate_consistency": "normalized_without_mixed_coordinate_distance", "summary": "分析中心已按声明坐标系规范到 WGS84。" if center else "历史记录没有可解析分析中心。", "warnings": []}

    def _document_evidence(self, documents: dict[str, Any]) -> dict[str, Any]:
        extracts = [{"document_id": doc.get("document_id"), "title": doc.get("title"), "text": item.get("text", "")} for doc in documents.get("documents", []) for item in doc.get("extracts", []) if item.get("text")]
        return _evidence("evidence:project-documents", ["document:project-extracts"], ["project.document_constraints"], "项目文档空间约束与构想", f"提取 {len(extracts)} 条项目空间事实；它们是约束与待验证意图，不是自动批准的实施条件。", {"project_name": documents.get("project_name", ""), "extracts": extracts, "conflicts": documents.get("conflicts", [])}, "project document extraction snapshot", "measured", locator="artifacts/project-document-extracts-snapshot.json")

    def _poi_evidence(self, history_id: str, selected_records: list[ScopeRecord]) -> tuple[dict[str, Any], dict[str, Any]]:
        categories = Counter(str(r.properties.get("category") or r.properties.get("type") or "unknown") for r in selected_records)
        top = [{"category": key, "count": val} for key, val in categories.most_common(12)]
        years: list[dict[str, Any]] = []
        _, available_years, _ = self._datasets.load_scope_records(history_id=history_id, source_id="current:dataset:poi")
        for year in available_years:
            records, _, _ = self._datasets.load_scope_records(history_id=history_id, source_id="current:dataset:poi", year=year)
            counts = Counter(str(r.properties.get("category") or r.properties.get("type") or "unknown") for r in records)
            years.append({"year": year, "poi_count": len(records), "category_count": len(counts), "top_categories": [{"category": key, "count": val} for key, val in counts.most_common(8)]})
        structure = _evidence("evidence:poi:facility-structure", ["current:dataset:poi"], ["poi.category_count"], "当前 POI 设施供给结构", f"当前快照包含 {len(selected_records)} 个 POI、{len(categories)} 个类别代码；结果仅描述设施供给存在与结构。", {"poi_count": len(selected_records), "category_count": len(categories), "top_categories": top}, "normalized POI category aggregation", "proxy", locator="current:dataset:poi", flags=[{"code": "supply_not_demand", "severity": "warning", "effect": "POI 不代表客流、消费或市场缺口"}])
        temporal = _evidence("evidence:poi:multi-year-structure", ["current:dataset:poi"], ["poi.multi_year_count"], "多年份 POI 设施快照对比", "多年份 POI 仅用于对照设施记录变化；不同年份的采集与覆盖差异需要一并核验。", {"years": years}, "year-selected POI snapshot comparison", "proxy", locator="current:dataset:poi#years", flags=[{"code": "temporal_coverage_not_open_close", "severity": "warning", "effect": "不能把快照变化写成开闭店率或市场增长"}])
        return structure, temporal

    def _local_patterns(self, records: list[ScopeRecord]):
        spatial = [r for r in records if r.geometry is not None]
        cells: list[LocalizedPatternInputCell] = []
        for record in spatial:
            neighbors = [other.record_id for other in spatial if other.record_id != record.record_id and record.geometry.buffer(1e-10).intersects(other.geometry.buffer(1e-10))]
            cells.append(LocalizedPatternInputCell(cell_id=record.record_id, metric_id="poi.grid_density", value=float(record.properties.get("density_poi_per_km2") or 0), statistic=_number(record.properties.get("gi_star_value")), z_score=_number(record.properties.get("gi_star_z_score")), geometry=_geojson(record.geometry), neighbor_ids=neighbors))
        return self._spatial_actions.analyze_local_patterns(cells)

    def _shared_grid_colocation(self, poi_grid: list[ScopeRecord], road_grid: list[ScopeRecord]) -> dict[str, Any]:
        """Keep the POI--road action signal on cells that exist in both independent grids."""
        def cell_id(record: ScopeRecord) -> str:
            return str(record.properties.get("cell_id") or record.record_id)

        roads = {cell_id(record): record for record in road_grid if record.geometry is not None}
        joined = [(record, roads.get(cell_id(record))) for record in poi_grid if record.geometry is not None and roads.get(cell_id(record)) is not None]
        density_threshold = _percentile([value for poi, _ in joined if (value := _number(poi.properties.get("density_poi_per_km2"))) is not None], .75)
        integration_threshold = _percentile([value for _, road in joined if (value := _number(road.properties.get("road_integration"))) is not None], .75)
        choice_threshold = _percentile([value for _, road in joined if (value := _number(road.properties.get("road_choice"))) is not None], .75)
        qualifying: list[ScopeRecord] = []
        for poi, road in joined:
            density, integration, choice = _number(poi.properties.get("density_poi_per_km2")), _number(road.properties.get("road_integration")), _number(road.properties.get("road_choice"))
            high_density = density_threshold is not None and density is not None and density >= density_threshold
            high_road = ((integration_threshold is not None and integration is not None and integration >= integration_threshold) or (choice_threshold is not None and choice is not None and choice >= choice_threshold))
            if high_density and high_road:
                qualifying.append(poi)
        cells = [LocalizedPatternInputCell(cell_id=record.record_id, metric_id="poi.grid_density", value=1.0, geometry=_geojson(record.geometry), neighbor_ids=[other.record_id for other in qualifying if other.record_id != record.record_id and record.geometry.touches(other.geometry)]) for record in qualifying]
        result = self._spatial_actions.analyze_local_patterns(cells).model_dump(mode="json") if cells else {"evidence_state": "proxy", "pattern_label": "POI—路网共享网格共位区", "cells": [], "zones": [], "diagnostics": ["no_joint_upper_quartile_cells"]}
        result["pattern_label"] = "POI—路网共享网格共位区"
        return {"result": result, "joined_cell_count": len(joined), "qualifying_cell_count": len(qualifying), "thresholds": {"poi_density_upper_quartile": density_threshold, "road_integration_upper_quartile": integration_threshold, "road_choice_upper_quartile": choice_threshold}, "evidence_state": "proxy"}

    def _road_corridors(self, records: list[ScopeRecord]) -> tuple[list[dict[str, Any]], dict[str, list[ScopeRecord]]]:
        definitions = [("high_integration_corridor", "integration_score", "road.integration", .75, "upper"), ("high_choice_corridor", "choice_score", "road.choice", .75, "upper"), ("low_connectivity_break", "connectivity_score", "road.connectivity", .25, "lower"), ("high_depth_break", "depth_score", "road.mean_depth", .75, "upper")]
        output: list[dict[str, Any]] = []
        segments_by_corridor: dict[str, list[ScopeRecord]] = {}
        for kind, field_name, metric_id, q, mode in definitions:
            threshold = _percentile([value for r in records if (value := _number(r.properties.get(field_name))) is not None], q)
            if threshold is None:
                continue
            selected = [r for r in records if r.geometry is not None and (value := _number(r.properties.get(field_name))) is not None and (value >= threshold if mode == "upper" else value <= threshold)]
            if selected:
                corridor_id = f"corridor:{kind}"
                segments_by_corridor[corridor_id] = selected
                output.append({"corridor_id": corridor_id, "pattern_type": kind, "metric_id": metric_id, "threshold": threshold, "segment_ids": [r.record_id for r in selected], "geometry": _geojson(unary_union([r.geometry for r in selected])), "segment_count": len(selected), "evidence_state": "proxy"})
        return output, segments_by_corridor

    @staticmethod
    def _road_summary(corridors: list[dict[str, Any]]) -> str:
        return "从路网线段提取分位数廊道与断点候选：" + "；".join(f"{x['pattern_type']} {x['segment_count']} 段" for x in corridors) + "。它们描述句法结构，不等于实测人流。"

    def _overlay_actions(self, patterns: dict[str, Any], corridors: list[dict[str, Any]], corridor_segments: dict[str, list[ScopeRecord]]) -> list[dict[str, Any]]:
        """Keep only road segments that truly meet each local zone, not an entire corridor."""
        candidates: list[dict[str, Any]] = []
        for zone in patterns.get("zones") or []:
            zone_geometry = shape(zone["geometry"])
            for corridor in corridors:
                if not corridor["pattern_type"].startswith("high_"):
                    continue
                matched_segments = [segment for segment in corridor_segments.get(corridor["corridor_id"], []) if segment.geometry is not None and zone_geometry.intersects(segment.geometry)]
                if not matched_segments:
                    continue
                matched_geometry = unary_union([segment.geometry for segment in matched_segments])
                candidates.append({"candidate_id": f"action:{zone['zone_id']}:{corridor['corridor_id']}", "geometry": _geojson(matched_geometry), "source_zone_ids": [zone["zone_id"]], "road_segment_ids": [segment.record_id for segment in matched_segments], "poi_pattern": zone["pattern_type"], "road_pattern": corridor["pattern_type"], "action_target": "public_space", "recommended_observation": "核查沿线开放性、围墙/门禁、首层界面、安全与可停留条件，再决定是否布置可逆低门槛测试。", "evidence_state": "proxy"})
        return candidates

    def _attempts(
        self,
        plan: list[dict[str, Any]],
        evidence_nodes: list[dict[str, Any]],
        *,
        available_source_ids: set[str],
        blocked_reasons: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Materialize the locked plan one entry at a time without fixed entry IDs."""
        by_metric: dict[str, list[str]] = {}
        known_ids = {str(node.get("id")) for node in evidence_nodes}
        for node in evidence_nodes:
            for metric_id in node.get("metric_ids") or []:
                by_metric.setdefault(str(metric_id), []).append(str(node["id"]))

        statuses: dict[str, str] = {}
        attempts: list[dict[str, Any]] = []
        for entry in plan:
            if entry["role"] == "excluded":
                continue
            activation = entry.get("activation") or {"type": "always"}
            activation_type = str(activation.get("type") or "always")
            source_statuses = [statuses.get(str(item), "not_attempted") for item in activation.get("source_entry_ids") or []]
            condition_met = activation_type == "always" or (
                activation_type == "if_primary_blocked" and any(status in {"blocked", "failed"} for status in source_statuses)
            ) or (
                activation_type == "if_quality_failed" and any(status in {"blocked", "failed"} for status in source_statuses)
            ) or (
                activation_type == "if_pattern_detected" and source_statuses and all(status == "succeeded" for status in source_statuses)
            )
            if not condition_met:
                attempt = _attempt(
                    entry,
                    "condition-not-met",
                    "not_applicable",
                    reason="condition_not_met：锁定计划中的激活条件未满足。",
                )
                attempts.append(attempt)
                statuses[entry["plan_entry_id"]] = attempt["execution_status"]
                continue

            metric_id = entry["metric_id"]
            target_id = str((entry.get("planned_spatial_target") or {}).get("source") or "current-snapshot")
            missing_sources = sorted(set(entry.get("required_source_ids") or []) - available_source_ids)
            if missing_sources:
                attempt = _attempt(
                    entry,
                    target_id,
                    "blocked",
                    reason=f"缺少计划要求的数据源：{', '.join(missing_sources)}。",
                )
            elif metric_id in blocked_reasons:
                attempt = _attempt(entry, target_id, "blocked", reason=blocked_reasons[metric_id])
            else:
                evidence_ids = list(dict.fromkeys(by_metric.get(metric_id, [])))
                if metric_id in {"spatial.gi_star", "poi.grid_density"} and "road" in target_id and "evidence:spatial-action:poi-road-overlay" in known_ids:
                    evidence_ids = ["evidence:spatial-action:poi-road-overlay"]
                attempt = (
                    _attempt(entry, target_id, "succeeded", evidence_ids)
                    if evidence_ids
                    else _attempt(entry, target_id, "blocked", reason="当前锁定计划所选指标缺少可执行的本地数据或适配器。")
                )
            attempts.append(attempt)
            statuses[entry["plan_entry_id"]] = attempt["execution_status"]
        return attempts
