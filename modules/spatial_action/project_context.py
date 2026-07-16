from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import floor
from typing import Any, Iterable

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from core.config import settings
from modules.nightlight.service import build_nightlight_meta_payload, get_nightlight_layer
from modules.population.runtime_check import run_population_runtime_check
from modules.population.service import get_population_overview
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84
from modules.scope_datasets.service import ScopeDatasetService, ScopeRecord
from modules.spatial_action.schemas import LocalizedPatternInputCell
from modules.spatial_action.service import SpatialActionService

CATALOG_VERSION = "2.0.0"

# Deterministic capabilities exposed to the planning layer.  This is a registry of
# concrete domain adapters, not a project-specific recommendation list.
EXECUTABLE_METRIC_IDS = frozenset({
    "project.document_constraints", "isochrone.reachable_area",
    "poi.count", "poi.category_count", "poi.multi_year_count",
    "spatial.gi_star", "spatial.lisa", "poi.grid_density",
    "road.integration", "road.choice", "road.connectivity", "road.mean_depth",
    "road.entrance_distance", "road.walk_detour_ratio",
    "population.total", "population.sex_structure", "population.age_structure", "population.selected_ratio",
    "nightlight.total_radiance", "nightlight.mean_radiance", "nightlight.max_radiance",
    "nightlight.lit_pixel_ratio", "nightlight.p90", "nightlight.hotspot_class",
    "nightlight.hotspot_ratio", "nightlight.spatial_profile", "nightlight.sector_profile",
    "nightlight.activity_level", "project.boundary_geometry",
})

EVIDENCE_GATE_REASONS = {
    "competition.operating_performance": "缺少可核验的竞品经营、客流、出租或运营表现来源；本轮只保留补数门槛。",
    "operations.operator_commitment": "缺少运营主体、团队能力、开放时段与资源承诺；不能把空间代理写成运营可行性。",
    "finance.cost_revenue_model": "缺少成本、收入、投资节奏与敏感性模型；不能生成伪精确财务判断。",
}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _geojson(geometry: Any) -> dict[str, Any]:
    return mapping(geometry) if geometry is not None and not geometry.is_empty else {"type": "GeometryCollection", "geometries": []}


def _percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None
    return float(ordered[min(len(ordered) - 1, max(0, floor((len(ordered) - 1) * quantile)))])



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
        MetricPlan is locked.
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
        """Execute the locked MetricPlan and deterministic source-backed evidence adapters.

        The method owns deterministic spatial work and its evidence/object output.
        It never invents questions, chooses metrics, writes findings, or authors a
        report. Every non-excluded metric entry receives an explicit MetricAttempt;
        the orchestrator materializes the unified EvidenceAttempt bundle for all
        metric and non-metric EvidencePlan items.
        """
        del decision_questions  # Plan validation belongs to the orchestrator / AnalysisRun.
        inventory, loaded, selected_years = self._load_snapshot(history_id)
        source_versions = [
            *self._source_versions(loaded, selected_years, project_documents),
            *self._external_source_versions(),
        ]
        if (project_anchors or {}).get("project_boundary"):
            source_versions.append(
                {
                    "source_id": "project:boundary",
                    "sha256": "runtime:formal-project-boundary",
                    "record_count": 1,
                }
            )
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
            "entrance_relations": [],
            "path_relations": [],
            "coordinate_alignment": alignment,
            "diagnostics": {
                "analysis_center_used_as_entrance": False,
                "isochrone_boundary_used_as_project_boundary": False,
                "formal_entrance_geometry_available": bool((project_anchors or {}).get("entrances")),
                "project_boundary_geometry_available": bool((project_anchors or {}).get("project_boundary")),
            },
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

        if "project.boundary_geometry" in selected:
            boundary = (project_anchors or {}).get("project_boundary")
            if boundary:
                layers["project_boundary"] = boundary
                evidence.append(
                    _evidence(
                        "evidence:project-boundary",
                        ["project:boundary"],
                        ["project.boundary_geometry"],
                        "正式项目边界",
                        "项目边界由显式项目锚点提供，可用于后续入口、界面和项目内外关系分析。",
                        {"project_boundary": boundary},
                        "declared formal project boundary",
                        "measured",
                        locator="artifacts/spatial-action-map.json#project_boundary",
                    )
                )
            else:
                blocked_reasons["project.boundary_geometry"] = "缺少正式项目边界；历史等时圈仅是区域分析范围，不能替代项目红线。"

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
            if selected & {"poi.count", "poi.category_count"}:
                evidence.append(poi_evidence)
            if "poi.multi_year_count" in selected:
                evidence.append(temporal_evidence)

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
                        "gcj02",
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
                    layer = get_nightlight_layer(polygon, "gcj02", view="hotspot")
                    evidence.append(
                        _evidence(
                            "evidence:nightlight:scope-profile",
                            ["current:dataset:nightlight"],
                            sorted(selected & nightlight_metrics),
                            "区域夜间灯光强度与空间形态代理",
                            "夜间灯光用于描述夜间活动强度与空间分布代理；它不能证明项目客流、营业额或特定业态需求。",
                            {"year": layer.get("year"), "summary": layer.get("summary"), "analysis": layer.get("analysis")},
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
                        f"在同一规则网格中识别 {len(colocation_result['zones'])} 个 POI 高值与路网高值共位观察区；它们是空间组织线索，不是客流或入口排名。",
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
            project_anchors,
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
                        "record_count": 0,
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
                    "record_count": 0,
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
        entrances = list((anchors or {}).get("entrances") or [])
        boundary = bool((anchors or {}).get("project_boundary"))
        return {"analysis_center": center, "analysis_center_declared_coordinate_system": declared, "normalized_coordinate_system": "wgs84", "metric_crs_policy": "所有距离、去重和路网关系都在本地投影米制坐标中计算。", "formal_project_boundary_available": boundary, "formal_entrance_count": len(entrances), "project_reference_proxy": None, "distance_to_project_reference_m": None, "coordinate_consistency": "normalized_without_mixed_coordinate_distance", "summary": "历史中心点已按声明坐标系规范到 WGS84；没有正式项目边界或入口锚点，中心点等时圈只作为区域背景。" if center else "历史记录没有可解析中心点，也没有正式项目锚点。", "warnings": (["project_boundary_missing"] if not boundary else []) + (["formal_entrance_geometry_missing"] if not entrances else [])}

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
        anchors: dict[str, Any] | None,
        *,
        available_source_ids: set[str],
        blocked_reasons: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Materialize the locked plan one entry at a time without fixed entry IDs."""
        entrances = bool((anchors or {}).get("entrances"))
        pairs = bool((anchors or {}).get("origin_destination_pairs"))
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
            elif metric_id in EVIDENCE_GATE_REASONS:
                attempt = _attempt(entry, target_id, "blocked", reason=EVIDENCE_GATE_REASONS[metric_id])
            elif metric_id == "road.entrance_distance":
                reason = (
                    "缺少正式项目边界和入口点位；不从中心点或等时圈推断入口。"
                    if not entrances
                    else "正式入口已提供，但入口路网挂接适配器尚未收到可执行输入。"
                )
                attempt = _attempt(entry, target_id, "blocked", reason=reason)
            elif metric_id == "road.walk_detour_ratio":
                if not (entrances and pairs):
                    attempt = _attempt(
                        entry,
                        target_id,
                        "not_applicable",
                        reason="condition_not_met：缺少经确认的入口—目的地组合，不能调用真实步行路径。",
                    )
                else:
                    attempt = _attempt(entry, target_id, "blocked", reason="真实路径适配器尚未收到可执行的目的地几何。")
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
