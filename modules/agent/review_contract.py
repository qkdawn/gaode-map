from __future__ import annotations

from typing import Any, Dict, List

from .schemas import AnalysisSnapshot, AuditResult, ToolResult
from .synthesis_metrics import build_summary_metrics


REVIEW_CONTRACT_DIMENSIONS: List[Dict[str, str]] = [
    {
        "key": "spatial_consistency",
        "label": "空间自洽",
        "question": "人口、POI、夜光、路网、等时圈和边界是否互相支撑，哪里耦合、错位或无法证明。",
    },
    {
        "key": "evidence_status",
        "label": "证据状态",
        "question": "当前证据能证明什么，只能趋势推断什么，还缺什么。",
    },
    {
        "key": "planning_translation",
        "label": "策划转译",
        "question": "把空间和数据判断转成定位、客群、业态组合、空间组织、运营动作和风险。",
    },
    {
        "key": "report_expression",
        "label": "报告写回",
        "question": "整理成可写回报告的模块、风险边界和下一步追问。",
    },
]


def review_contract_prompt() -> str:
    lines = ["深度分析审查契约：后端必须按以下四个维度组织证据、审计和表达。"]
    for item in REVIEW_CONTRACT_DIMENSIONS:
        lines.append(f"- {item['label']}（{item['key']}）：{item['question']}")
    return "\n".join(lines)


def review_contract_schema_prompt() -> str:
    return (
        '"review_contract":{'
        '"spatial_consistency":{"status":"supported|partial|missing","summary":"...","evidence":["..."],"gaps":["..."],"next_question":"..."},'
        '"evidence_status":{"status":"supported|partial|missing","summary":"...","evidence":["..."],"gaps":["..."],"next_question":"..."},'
        '"planning_translation":{"status":"supported|partial|missing","summary":"...","evidence":["..."],"gaps":["..."],"next_question":"..."},'
        '"report_expression":{"status":"supported|partial|missing","summary":"...","evidence":["..."],"gaps":["..."],"next_question":"..."}}'
    )


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {}, False)


def _append_unique(items: List[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _dimension(
    *,
    key: str,
    status: str,
    summary: str,
    evidence: List[str] | None = None,
    gaps: List[str] | None = None,
    next_question: str = "",
) -> Dict[str, Any]:
    config = next((item for item in REVIEW_CONTRACT_DIMENSIONS if item["key"] == key), {})
    return {
        "key": key,
        "label": str(config.get("label") or key),
        "status": status if status in {"supported", "partial", "missing"} else "partial",
        "summary": summary,
        "evidence": [str(item) for item in (evidence or []) if str(item).strip()][:6],
        "gaps": [str(item) for item in (gaps or []) if str(item).strip()][:6],
        "next_question": next_question,
    }


def build_review_contract(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    tool_results: List[ToolResult] | None = None,
    audit: AuditResult | None = None,
    decision_summary: str = "",
) -> Dict[str, Any]:
    del question
    audit = audit or AuditResult()
    metrics = build_summary_metrics(snapshot, artifacts)
    tool_names = [result.tool_name for result in (tool_results or []) if getattr(result, "status", "") == "success"]
    evidence: List[str] = []
    gaps = list(audit.missing_evidence or [])

    if _has_value(metrics.get("poi_count")):
        _append_unique(evidence, f"POI 样本量 {metrics.get('poi_count')}")
    if _has_value(metrics.get("h3_grid_count")):
        _append_unique(evidence, f"POI H3 网格 {metrics.get('h3_grid_count')} 个")
    if _has_value(metrics.get("population_total")):
        _append_unique(evidence, f"人口总量 {metrics.get('population_total')}")
    if _has_value(metrics.get("nightlight_mean_radiance")):
        _append_unique(evidence, f"夜光均值 {metrics.get('nightlight_mean_radiance')}")
    if _has_value(metrics.get("road_node_count")) or _has_value(metrics.get("road_edge_count")):
        _append_unique(evidence, f"路网节点/边段 {metrics.get('road_node_count') or 0}/{metrics.get('road_edge_count') or 0}")
    if _has_value(metrics.get("unified_spatial_cell_count")):
        _append_unique(
            evidence,
            f"统一空间格网 {metrics.get('unified_spatial_cell_count')} 个，POI/夜光/路网覆盖 {metrics.get('unified_active_poi_cell_count') or 0}/{metrics.get('unified_lit_cell_count') or 0}/{metrics.get('unified_road_covered_cell_count') or 0}",
        )
    for summary_key in (
        "poi_structure_summary",
        "h3_structure_summary",
        "population_profile_summary",
        "nightlight_pattern_summary",
        "road_pattern_summary",
        "business_profile_summary",
        "commercial_hotspot_summary",
        "target_supply_gap_summary",
    ):
        if _has_value(metrics.get(summary_key)):
            _append_unique(evidence, str(metrics.get(summary_key)))

    spatial_inputs = [
        metrics.get("poi_count"),
        metrics.get("h3_grid_count"),
        metrics.get("population_total"),
        metrics.get("nightlight_mean_radiance"),
        metrics.get("road_node_count"),
        metrics.get("unified_spatial_cell_count"),
    ]
    spatial_count = sum(1 for value in spatial_inputs if _has_value(value))
    spatial_status = "supported" if spatial_count >= 4 else ("partial" if spatial_count >= 2 else "missing")
    spatial_gaps = []
    if not _has_value(metrics.get("population_total")):
        spatial_gaps.append("人口概览")
    if not _has_value(metrics.get("nightlight_mean_radiance")):
        spatial_gaps.append("夜光概览")
    if not (_has_value(metrics.get("road_node_count")) or _has_value(metrics.get("road_edge_count"))):
        spatial_gaps.append("路网概览")
    if not _has_value(metrics.get("h3_grid_count")):
        spatial_gaps.append("POI H3 密度")

    evidence_status = "supported" if not gaps and evidence else ("partial" if evidence else "missing")
    planning_signals = [
        metrics.get("business_profile_summary"),
        metrics.get("target_supply_gap_summary"),
        metrics.get("commercial_hotspot_summary"),
        metrics.get("business_place_type"),
        metrics.get("unified_spatial_cell_count"),
    ]
    planning_count = sum(1 for value in planning_signals if _has_value(value))
    planning_status = "supported" if planning_count >= 2 else ("partial" if planning_count == 1 or evidence else "missing")
    planning_gaps = []
    if not _has_value(metrics.get("business_profile_summary")):
        planning_gaps.append("定位与客群画像")
    if not _has_value(metrics.get("target_supply_gap_summary")):
        planning_gaps.append("业态缺口或补位证据")
    if not _has_value(metrics.get("commercial_hotspot_summary")):
        planning_gaps.append("空间组织与热点结构")

    report_status = "supported" if decision_summary and evidence_status != "missing" else ("partial" if decision_summary or evidence else "missing")
    report_gaps = []
    if not decision_summary:
        report_gaps.append("可写回报告的核心判断")
    if gaps:
        report_gaps.append("缺失证据边界说明")

    return {
        "version": "review_contract_v1",
        "dimensions": REVIEW_CONTRACT_DIMENSIONS,
        "tool_chain": tool_names,
        "spatial_consistency": _dimension(
            key="spatial_consistency",
            status=spatial_status,
            summary="已对照 POI、H3、人口、夜光和路网信号。" if spatial_status == "supported" else "空间自洽检查只能部分成立，仍有关键维度缺口。",
            evidence=evidence,
            gaps=spatial_gaps,
            next_question="人口、夜光、路网与 POI 热点是否在同一空间单元上重合或错位？",
        ),
        "evidence_status": _dimension(
            key="evidence_status",
            status=evidence_status,
            summary="当前证据可支撑方向性判断。" if evidence_status == "supported" else "当前证据只能支撑有限推断，需要标注缺口。",
            evidence=evidence,
            gaps=gaps,
            next_question="哪些结论是已有证据能证明的，哪些只是趋势推断？",
        ),
        "planning_translation": _dimension(
            key="planning_translation",
            status=planning_status,
            summary="已有信号可转译为定位、业态或空间组织建议。" if planning_status == "supported" else "策划转译仍偏粗，需要补齐定位、业态或空间组织证据。",
            evidence=evidence,
            gaps=planning_gaps,
            next_question="这些空间信号应转成什么定位、客群、业态组合和运营动作？",
        ),
        "report_expression": _dimension(
            key="report_expression",
            status=report_status,
            summary=decision_summary or "尚未形成稳定的报告写回模块。",
            evidence=evidence[:4],
            gaps=report_gaps,
            next_question="这一轮结论应写回报告的哪个模块，还需要追问什么？",
        ),
    }
