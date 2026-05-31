from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from modules.providers.amap.utils.get_type_info import infer_type_info_from_text, resolve_type_info

from ..analysis_extractors import build_h3_gap_rows_for_target, build_h3_structure_analysis
from ..schemas import AnalysisSnapshot, ToolResult
from .h3_tools import compute_h3_metrics_from_scope_and_pois
from .nightlight_tools import compute_nightlight_overview_from_scope
from .poi_tools import fetch_pois_in_scope
from .population_tools import compute_population_overview_from_scope
from .road_tools import compute_road_syntax_from_scope

ToolAdapter = Callable[..., Awaitable[ToolResult]]


def _resolve_target(arguments: Dict[str, Any], question: str) -> Optional[Dict[str, Any]]:
    place_type = str(arguments.get("place_type") or "").strip()
    if place_type:
        return (
            resolve_type_info(place_type)
            or infer_type_info_from_text(place_type)
            or infer_type_info_from_text(f"{place_type} {question}")
        )
    return infer_type_info_from_text(question)


def _child_status(result: ToolResult) -> Dict[str, Any]:
    return {
        "tool_name": result.tool_name,
        "status": result.status,
        "error": result.error or "",
        "warning_count": len(result.warnings or []),
    }


def _friendly_optional_tool_warning(tool_name: str, error: str = "") -> str:
    labels = {
        "compute_population_overview_from_scope": "人口数据",
        "compute_nightlight_overview_from_scope": "夜间灯光数据",
        "compute_road_syntax_from_scope": "路网可达性数据",
    }
    label = labels.get(tool_name, tool_name)
    suffix = "，已降级继续"
    if str(error or "").strip() == "ValueError":
        return f"{label}当前不可用{suffix}"
    if str(error or "").strip() == "RuntimeError":
        return f"{label}服务暂不可用{suffix}"
    return f"{label}暂未跑通{suffix}"


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _canonical_place_type_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    resolved = resolve_type_info(text) or infer_type_info_from_text(text)
    return str((resolved or {}).get("label") or text).strip()


def _same_place_type(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    left_label = _canonical_place_type_label(left_text)
    right_label = _canonical_place_type_label(right_text)
    return left_label == right_label or left_text in right_text or right_text in left_text


def _has_reusable_site_selection_base(
    *,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    target_label: str,
) -> bool:
    h3_summary = _safe_dict(artifacts.get("current_poi_h3_summary")) or _safe_dict(
        _safe_dict(snapshot.h3).get("summary")
    )
    if not h3_summary:
        return False
    h3_structure = build_h3_structure_analysis(snapshot, artifacts)
    if not h3_structure.get("evidence_ready"):
        return bool(build_h3_gap_rows_for_target(snapshot, artifacts, target_label=target_label, limit=1))
    h3_target_label = str(
        h3_structure.get("target_category_label") or h3_structure.get("target_category") or ""
    ).strip()
    if not h3_target_label:
        return bool(h3_structure.get("gap_rows")) or bool(
            build_h3_gap_rows_for_target(snapshot, artifacts, target_label=target_label, limit=1)
        )
    return _same_place_type(target_label, h3_target_label) or bool(
        build_h3_gap_rows_for_target(snapshot, artifacts, target_label=target_label, limit=1)
    )


async def _run_child_tool(
    *,
    runner: ToolAdapter,
    tool_name: str,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    try:
        return await runner(arguments=arguments, snapshot=snapshot, artifacts=artifacts, question=question)
    except Exception as exc:
        return ToolResult(
            tool_name=tool_name,
            status="failed",
            warnings=[str(exc)],
            error=exc.__class__.__name__,
        )


async def run_business_site_advice(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    polygon = artifacts.get("scope_polygon") or []
    if not polygon:
        return ToolResult(
            tool_name="run_business_site_advice",
            status="failed",
            warnings=["缺少分析范围，无法执行开店/选址建议组合分析"],
            error="missing_scope_polygon",
        )

    target = _resolve_target(arguments, question)
    if not target:
        return ToolResult(
            tool_name="run_business_site_advice",
            status="failed",
            warnings=["无法从问题或 place_type 中解析目标业态，请使用 share/type_map.json 中的类型名称或别名"],
            error="unresolved_place_type",
            artifacts={"business_site_advice": {"resolved": False}},
        )

    target_label = str(target.get("label") or arguments.get("place_type") or "").strip()
    target_types = str(target.get("types") or "").strip()
    target_keywords = str(target.get("keywords") or target_label).strip()
    point_type = str(target.get("point_type") or "").strip()
    if not target_types and not target_keywords:
        return ToolResult(
            tool_name="run_business_site_advice",
            status="failed",
            warnings=[f"目标业态 `{target_label}` 缺少可用 types/keywords"],
            error="unresolved_place_type",
            artifacts={"business_site_advice": {"resolved": False, "place_type": target_label}},
        )

    if _has_reusable_site_selection_base(snapshot=snapshot, artifacts=artifacts, target_label=target_label):
        business_site_advice = {
            "resolved": True,
            "place_type": target_label,
            "types": target_types,
            "keywords": target_keywords,
            "point_type": point_type,
            "tool_statuses": [_child_status(ToolResult(tool_name="read_current_results", status="success"))],
            "reused_current_results": True,
        }
        return ToolResult(
            tool_name="run_business_site_advice",
            status="success",
            result={
                "place_type": target_label,
                "types": target_types,
                "keywords": target_keywords,
                "poi_count": (
                    _safe_dict(artifacts.get("current_poi_summary")) or _safe_dict(snapshot.poi_summary)
                ).get("total"),
                "h3_grid_count": (
                    _safe_dict(artifacts.get("current_poi_h3_summary"))
                    or _safe_dict(_safe_dict(snapshot.h3).get("summary"))
                ).get("grid_count"),
            },
            evidence=[
                {"field": "business_site_advice.place_type", "value": target_label},
                {"field": "business_site_advice.reused_current_results", "value": True},
            ],
            warnings=["已复用当前页面已生成的 POI/H3 结构化证据，未重复请求本地 POI 服务。"],
            artifacts={
                "current_pois": artifacts.get("current_pois") or list(snapshot.pois or []),
                "current_poi_summary": artifacts.get("current_poi_summary") or dict(snapshot.poi_summary or {}),
                "current_poi_h3": artifacts.get("current_poi_h3") or dict(snapshot.h3 or {}),
                "current_poi_h3_grid": artifacts.get("current_poi_h3_grid")
                or _safe_dict(_safe_dict(snapshot.h3).get("grid")),
                "current_poi_h3_summary": artifacts.get("current_poi_h3_summary")
                or _safe_dict(_safe_dict(snapshot.h3).get("summary")),
                "current_poi_h3_charts": artifacts.get("current_poi_h3_charts")
                or _safe_dict(_safe_dict(snapshot.h3).get("charts")),
                "current_population": artifacts.get("current_population") or dict(snapshot.population or {}),
                "current_population_summary": artifacts.get("current_population_summary")
                or _safe_dict(_safe_dict(snapshot.population).get("summary")),
                "current_nightlight": artifacts.get("current_nightlight") or dict(snapshot.nightlight or {}),
                "current_nightlight_summary": artifacts.get("current_nightlight_summary")
                or _safe_dict(_safe_dict(snapshot.nightlight).get("summary")),
                "current_road": artifacts.get("current_road") or dict(snapshot.road or {}),
                "current_road_summary": artifacts.get("current_road_summary")
                or _safe_dict(_safe_dict(snapshot.road).get("summary")),
                "current_frontend_analysis": artifacts.get("current_frontend_analysis") or dict(snapshot.frontend_analysis or {}),
                "business_site_advice": business_site_advice,
            },
        )

    tool_statuses: List[Dict[str, Any]] = []
    warnings: List[str] = []
    evidence: List[Dict[str, Any]] = [
        {"field": "business_site_advice.place_type", "value": target_label},
        {"field": "business_site_advice.types", "value": target_types},
        {"field": "business_site_advice.keywords", "value": target_keywords},
    ]

    poi_arguments = {
        "source": str(arguments.get("source") or snapshot.current_filters.get("poi_source") or snapshot.context.get("source") or "local"),
        "types": target_types,
        "keywords": target_keywords,
        "year": arguments.get("year"),
    }
    if arguments.get("max_count") is not None:
        poi_arguments["max_count"] = int(arguments.get("max_count") or 0)
    poi_result = await _run_child_tool(
        runner=fetch_pois_in_scope,
        tool_name="fetch_pois_in_scope",
        arguments=poi_arguments,
        snapshot=snapshot,
        artifacts=artifacts,
        question=question,
    )
    tool_statuses.append(_child_status(poi_result))
    warnings.extend(poi_result.warnings or [])
    evidence.extend(poi_result.evidence or [])
    if poi_result.status == "failed":
        return ToolResult(
            tool_name="run_business_site_advice",
            status="failed",
            result={"place_type": target_label, "types": target_types, "keywords": target_keywords},
            evidence=evidence,
            warnings=warnings,
            error=poi_result.error or "poi_analysis_failed",
            artifacts={
                "business_site_advice": {
                    "resolved": True,
                    "place_type": target_label,
                    "types": target_types,
                    "keywords": target_keywords,
                    "point_type": point_type,
                    "tool_statuses": tool_statuses,
                }
            },
        )
    artifacts.update(poi_result.artifacts or {})

    h3_arguments = {
        "resolution": int(arguments.get("resolution") or snapshot.current_filters.get("h3_resolution") or 10),
        "include_mode": str(arguments.get("include_mode") or "intersects"),
        "min_overlap_ratio": float(arguments.get("min_overlap_ratio") or 0.0),
        "neighbor_ring": int(arguments.get("neighbor_ring") or 1),
    }
    h3_result = await _run_child_tool(
        runner=compute_h3_metrics_from_scope_and_pois,
        tool_name="compute_h3_metrics_from_scope_and_pois",
        arguments=h3_arguments,
        snapshot=snapshot,
        artifacts=artifacts,
        question=question,
    )
    tool_statuses.append(_child_status(h3_result))
    warnings.extend(h3_result.warnings or [])
    evidence.extend(h3_result.evidence or [])
    if h3_result.status == "failed":
        return ToolResult(
            tool_name="run_business_site_advice",
            status="failed",
            result={"place_type": target_label, "types": target_types, "keywords": target_keywords},
            evidence=evidence,
            warnings=warnings,
            error=h3_result.error or "h3_analysis_failed",
            artifacts={
                **(poi_result.artifacts or {}),
                "business_site_advice": {
                    "resolved": True,
                    "place_type": target_label,
                    "types": target_types,
                    "keywords": target_keywords,
                    "point_type": point_type,
                    "tool_statuses": tool_statuses,
                },
            },
        )
    artifacts.update(h3_result.artifacts or {})

    optional_steps = [
        (
            "compute_population_overview_from_scope",
            compute_population_overview_from_scope,
            {"coord_type": str(arguments.get("coord_type") or "gcj02")},
        ),
        (
            "compute_nightlight_overview_from_scope",
            compute_nightlight_overview_from_scope,
            {"coord_type": str(arguments.get("coord_type") or "gcj02"), "year": arguments.get("year")},
        ),
        (
            "compute_road_syntax_from_scope",
            compute_road_syntax_from_scope,
            {
                "mode": str(arguments.get("mode") or ""),
                "graph_model": str(arguments.get("graph_model") or ""),
                "highway_filter": str(arguments.get("highway_filter") or ""),
            },
        ),
    ]
    for tool_name, runner, child_arguments in optional_steps:
        result = await _run_child_tool(
            runner=runner,
            tool_name=tool_name,
            arguments=child_arguments,
            snapshot=snapshot,
            artifacts=artifacts,
            question=question,
        )
        tool_statuses.append(_child_status(result))
        evidence.extend(result.evidence or [])
        if result.status == "success":
            artifacts.update(result.artifacts or {})
        else:
            warnings.append(_friendly_optional_tool_warning(tool_name, result.error or ""))
        if result.status == "success":
            warnings.extend(result.warnings or [])

    business_site_advice = {
        "resolved": True,
        "place_type": target_label,
        "types": target_types,
        "keywords": target_keywords,
        "point_type": point_type,
        "tool_statuses": tool_statuses,
    }
    produced_artifacts = {
        "current_pois": artifacts.get("current_pois") or [],
        "current_poi_summary": artifacts.get("current_poi_summary") or {},
        "current_poi_h3": artifacts.get("current_poi_h3") or {},
        "current_poi_h3_grid": artifacts.get("current_poi_h3_grid") or {},
        "current_poi_h3_summary": artifacts.get("current_poi_h3_summary") or {},
        "current_poi_h3_charts": artifacts.get("current_poi_h3_charts") or {},
        "current_population": artifacts.get("current_population") or {},
        "current_population_summary": artifacts.get("current_population_summary") or {},
        "current_nightlight": artifacts.get("current_nightlight") or {},
        "current_nightlight_summary": artifacts.get("current_nightlight_summary") or {},
        "current_road": artifacts.get("current_road") or {},
        "current_road_summary": artifacts.get("current_road_summary") or {},
        "business_site_advice": business_site_advice,
    }
    return ToolResult(
        tool_name="run_business_site_advice",
        status="success",
        result={
            "place_type": target_label,
            "types": target_types,
            "keywords": target_keywords,
            "poi_count": (artifacts.get("current_poi_summary") or {}).get("total"),
            "h3_grid_count": (artifacts.get("current_poi_h3_summary") or {}).get("grid_count"),
        },
        evidence=evidence,
        warnings=warnings,
        artifacts=produced_artifacts,
    )
