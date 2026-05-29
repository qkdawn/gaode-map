from __future__ import annotations

from typing import Any, Dict, List

from .analysis_extractors import is_target_supply_gap_ready
from .intent_signals import mentions_nightlight, mentions_population, mentions_road, mentions_summary, mentions_supply
from .review_contract import build_review_contract
from .synthesis_evidence import build_analysis_evidence as _build_analysis_evidence_from_module
from .synthesis_metrics import build_summary_metrics as _build_summary_metrics_from_module
from .schemas import (
    AgentEvidenceItem,
    AgentTurnOutput,
    AnalysisSnapshot,
    AssistantCard,
    AuditResult,
    DecisionActionItem,
    DecisionBoundaryItem,
    DecisionCounterpointItem,
    DecisionEvidenceItem,
    DecisionPayload,
    ToolResult,
)

_ALL_BUSINESS_EVIDENCE = ["POI 供给证据", "POI H3 密度证据", "人口概览", "夜光概览", "路网概览"]


def _summary_metrics(snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> Dict[str, object]:
    return _build_summary_metrics_from_module(snapshot, artifacts)


def build_analysis_evidence(snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> List[AgentEvidenceItem]:
    return _build_analysis_evidence_from_module(snapshot, artifacts)


def _as_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _infer_output_mode(question: str) -> str:
    text = str(question or "")
    if any(token in text for token in ("下一步", "怎么做", "怎么补", "建议", "行动", "选址")):
        return "action"
    if any(token in text for token in ("适合", "值不值得", "是否", "可不可以", "能不能", "为什么")):
        return "judgment"
    return "cognition"


def _evidence_headline(item: AgentEvidenceItem) -> str:
    if item.metric == "next_analysis_options" and isinstance(item.value, dict):
        options = [option for option in (item.value.get("options") or []) if isinstance(option, dict)]
        if options:
            return f"推荐下一步：{options[0].get('title') or '继续分析'}"
        return "已评估下一步分析方向"
    if item.metric == "business_profile" and isinstance(item.value, dict):
        return f"商业画像偏向 {item.value.get('business_profile') or '未明确'}"
    if item.metric == "commercial_hotspots" and isinstance(item.value, dict):
        return f"商业热点结构为 {item.value.get('hotspot_mode') or '未明确'}，核心区 {item.value.get('core_zone_count') or 0} 个"
    if item.metric == "target_supply_gap" and isinstance(item.value, dict):
        return f"{item.value.get('place_type') or '目标业态'}供给缺口 {item.value.get('supply_gap_level') or 'unknown'}"
    if item.metric == "business_site_advice" and isinstance(item.value, dict):
        return f"目标业态：{item.value.get('place_type') or '未指定'}"
    if item.metric == "poi_count":
        return f"POI 样本量 {item.value}"
    if item.metric == "h3_density" and isinstance(item.value, dict):
        density = item.value.get("avg_density_poi_per_km2")
        return f"POI H3 网格 {item.value.get('grid_count') or 0} 个，平均密度 {density if density is not None else '未提供'}"
    if item.metric == "road_structure" and isinstance(item.value, dict):
        return f"路网节点 {item.value.get('node_count') or 0}、边段 {item.value.get('edge_count') or 0}"
    if item.metric == "population_profile" and isinstance(item.value, dict):
        total = item.value.get("total_population")
        return f"人口总量约 {total if total is not None else '未提供'}"
    if item.metric == "nightlight_activity" and isinstance(item.value, dict):
        mean_value = item.value.get("mean_radiance")
        peak_value = item.value.get("peak_radiance")
        return f"夜光均值 {mean_value if mean_value is not None else '未提供'}，峰值 {peak_value if peak_value is not None else '未提供'}"
    return item.metric


def _decision_strength(evidence: List[AgentEvidenceItem], audit: AuditResult) -> str:
    if audit.missing_evidence or audit.issues:
        return "weak"
    if len(evidence) >= 4:
        return "strong"
    if len(evidence) >= 2:
        return "moderate"
    return "weak"


def _interpretation_limits(evidence: List[AgentEvidenceItem], audit: AuditResult) -> List[str]:
    limits = ["不能直接从 GIS 指标推断客流、消费能力、营业额或经营收益。"]
    limits.extend([item.limitation for item in evidence if item.limitation])
    limits.extend([str(item) for item in audit.issues if str(item).strip()])
    deduped: List[str] = []
    for item in limits:
        text = str(item or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped


def _detect_conflicts(metrics: Dict[str, object], audit: AuditResult) -> List[str]:
    conflicts: List[str] = []
    population_total = metrics.get("population_total")
    nightlight_mean = metrics.get("nightlight_mean_radiance")
    poi_count = metrics.get("poi_count")
    road_nodes = metrics.get("road_node_count")
    density = metrics.get("avg_density_poi_per_km2")

    try:
        if nightlight_mean not in (None, "") and population_total not in (None, "") and float(nightlight_mean) >= 3.0 and float(population_total) < 2000:
            conflicts.append("夜光活力信号较强，但人口基础偏弱，活动可能更依赖局部目的地或流动活动。")
    except (TypeError, ValueError):
        pass
    try:
        if poi_count not in (None, "") and road_nodes not in (None, "") and int(poi_count) >= 20 and int(road_nodes) <= 40:
            conflicts.append("POI 供给量不低，但路网支撑偏弱，商业分布不一定能转化为高可达性。")
    except (TypeError, ValueError):
        pass
    if density not in (None, "") and metrics.get("target_supply_gap_level") in {"medium", "high"}:
        conflicts.append("空间密度不低，但目标业态仍存在缺口，问题更可能是结构错配而不是单纯总量不足。")
    for item in audit.issues or []:
        text = str(item).strip()
        if text and text not in conflicts:
            conflicts.append(text)
    return conflicts


def _select_key_evidence(evidence: List[AgentEvidenceItem], *, question: str) -> List[DecisionEvidenceItem]:
    if any(token in question for token in ("下一步", "继续", "还可以", "做什么分析", "还能分析")):
        preferred_order = ["next_analysis_options", "poi_count", "h3_density", "population_profile", "nightlight_activity", "road_structure"]
    elif mentions_supply(question):
        preferred_order = ["target_supply_gap", "business_site_advice", "commercial_hotspots", "h3_density", "road_structure"]
    elif mentions_nightlight(question):
        preferred_order = ["nightlight_activity", "population_profile", "road_structure", "poi_count"]
    elif mentions_population(question):
        preferred_order = ["population_profile", "poi_count", "nightlight_activity", "road_structure"]
    elif mentions_road(question):
        preferred_order = ["road_structure", "commercial_hotspots", "poi_count", "population_profile"]
    else:
        preferred_order = ["business_profile", "commercial_hotspots", "poi_count", "h3_density", "population_profile", "nightlight_activity", "road_structure"]
    ranking = {name: index for index, name in enumerate(preferred_order)}
    ordered = sorted(evidence, key=lambda item: (ranking.get(item.metric, 99), {"strong": 0, "moderate": 1, "weak": 2}.get(item.confidence, 2)))
    decision_key = "actionability" if _infer_output_mode(question) == "action" else "core_judgment"
    return [
        DecisionEvidenceItem(
            key=item.metric,
            metric=item.metric,
            headline=_evidence_headline(item),
            value=item.value,
            interpretation=item.interpretation,
            source=item.source,
            confidence=item.confidence,
            limitation=item.limitation,
            supports=[decision_key],
            is_key=True,
        )
        for item in ordered[:3]
    ]


def _infer_business_portrait(metrics: Dict[str, object]) -> tuple[str, List[str]]:
    mix = [item for item in (metrics.get("poi_category_mix") or []) if isinstance(item, dict)]
    if not mix:
        return "综合商业画像仍需更多业态结构信息", []

    top_labels = {str(item.get("label") or ""): float(item.get("ratio") or 0.0) for item in mix}
    ordered = [f"{item.get('label')} {item.get('count')} 个" for item in mix[:3]]
    dining_ratio = top_labels.get("餐饮", 0.0)
    shopping_ratio = top_labels.get("购物", 0.0)
    lodging_ratio = top_labels.get("住宿", 0.0)
    office_ratio = top_labels.get("公司", 0.0) + top_labels.get("商务住宅", 0.0)
    culture_ratio = top_labels.get("科教文化", 0.0)

    if dining_ratio + shopping_ratio >= 0.45:
        portrait = "生活消费主导的综合商业区"
    elif lodging_ratio >= 0.12:
        portrait = "住宿接待功能较强的复合片区"
    elif office_ratio >= 0.18:
        portrait = "商务与日常消费复合片区"
    else:
        portrait = "多业态混合的综合服务片区"

    reasons: List[str] = []
    if ordered:
        reasons.append(f"头部业态为 {'、'.join(ordered)}。")
    if culture_ratio >= 0.1:
        reasons.append("科教文化设施占比不低，说明公共服务或教育配套参与度较高。")
    if office_ratio >= 0.12:
        reasons.append("公司与商务住宅占比有一定体量，商业功能不只是纯生活配套。")
    if lodging_ratio >= 0.08:
        reasons.append("住宿设施占比不低，说明区域对流动人口或短停留活动有承接能力。")
    return portrait, reasons


def _build_decision_summary(
    *,
    question: str,
    metrics: Dict[str, object],
    decision_strength: str,
    conflicts: List[str],
    missing_evidence: List[str],
) -> str:
    portrait, _ = _infer_business_portrait(metrics)
    strength_label = {"strong": "较强", "moderate": "中等", "weak": "偏弱"}.get(decision_strength, "偏弱")
    base = _as_text(metrics.get("business_profile_portrait")) or f"当前更接近{portrait}。"
    if _infer_output_mode(question) == "action":
        if decision_strength == "strong" and not missing_evidence:
            text = f"{base} 当前证据强度{strength_label}，可以继续做方向性判断和下一步预筛。"
        else:
            text = f"{base} 但当前证据强度{strength_label}，更适合做预研判断，不适合直接拍板。"
    else:
        text = f"{base} 当前证据强度{strength_label}。"
    if metrics.get("commercial_hotspot_summary"):
        text = f"{text} {metrics['commercial_hotspot_summary']}"
    if mentions_supply(question) and metrics.get("target_supply_gap_summary"):
        text = f"{text} {metrics['target_supply_gap_summary']}"
    if conflicts:
        text = f"{text} 不过{conflicts[0]}"
    elif missing_evidence:
        text = f"{text} 仍需补充 {'、'.join(missing_evidence[:2])} 后再做更强结论。"
    return text


def _build_counterpoints(*, conflicts: List[str], missing_evidence: List[str], limits: List[str]) -> List[DecisionCounterpointItem]:
    items: List[DecisionCounterpointItem] = []
    for detail in conflicts[:3]:
        items.append(DecisionCounterpointItem(kind="conflict", title="冲突证据", detail=detail))
    for detail in missing_evidence[:3]:
        items.append(DecisionCounterpointItem(kind="missing", title="仍缺证据", detail=f"当前仍缺少 {detail}。"))
    for detail in limits[:2]:
        items.append(DecisionCounterpointItem(kind="boundary", title="解释边界", detail=detail))
    return items


def _build_boundary_items(limits: List[str]) -> List[DecisionBoundaryItem]:
    return [DecisionBoundaryItem(title="适用边界", detail=item) for item in limits[:4]]


def _build_action_items(*, question: str, metrics: Dict[str, object], audit: AuditResult, decision_strength: str) -> List[DecisionActionItem]:
    items: List[DecisionActionItem] = []
    next_options = [item for item in (metrics.get("next_analysis_options") or []) if isinstance(item, dict)]
    if next_options:
        for option in next_options[:3]:
            items.append(
                DecisionActionItem(
                    title=str(option.get("title") or "下一步分析"),
                    detail=str(option.get("why") or ""),
                    condition=str(option.get("application") or "当你要继续推进当前分析时"),
                    target="next_analysis",
                    prompt=str(option.get("prompt") or option.get("title") or ""),
                )
            )
        return items
    if metrics.get("target_supply_gap_level") in {"medium", "high"}:
        place_type = _as_text(metrics.get("target_supply_gap_place_type"), "目标业态")
        items.append(
            DecisionActionItem(
                title="优先查看缺口候选格",
                detail="先看 gap 较高的候选格，再结合实地条件缩小范围。",
                condition="当目标是做补位或选址预筛时",
                target="site_selection",
                prompt=f"基于当前结果，继续细化候选格并比较{place_type}的机会区",
            )
        )
    if audit.missing_evidence:
        missing_text = "、".join(audit.missing_evidence[:2])
        items.append(
            DecisionActionItem(
                title="先补齐关键证据",
                detail=f"优先补齐 {missing_text}，再提高判断强度。",
                condition="当你需要更强结论时",
                target="evidence_gap",
                prompt=f"请补齐{missing_text}，再重新判断这个区域是否值得继续研究",
            )
        )
    if mentions_nightlight(question) or metrics.get("nightlight_mean_radiance") is not None:
        items.append(
            DecisionActionItem(
                title="核查夜光与业态是否一致",
                detail="把夜光热点与餐饮、休闲类 POI 分布对照，判断夜间活力是否可转化为商业机会。",
                condition="当你关心夜间消费或活动时",
                target="vitality_check",
                prompt="对比夜光热点与餐饮休闲 POI 的空间重合，判断夜间活力是否支撑商业机会",
            )
        )
    if not items:
        items.append(
            DecisionActionItem(
                title="继续收敛问题",
                detail="把问题收敛到区域画像、选址预筛或活力判断中的一个，再进入下一轮分析。",
                condition="当当前问题仍偏宽泛时",
                target="clarify_goal",
                prompt="基于当前结果，告诉我下一步最值得继续的分析方向",
            )
        )
    if decision_strength == "strong" and len(items) > 1:
        return items[:3]
    return items[:2]


def _recommendation_layers(question: str, audit: AuditResult, decision_strength: str, metrics: Dict[str, object]) -> Dict[str, List[str]]:
    can_act_now = ["可以基于当前证据做方向性判断，优先使用证据较完整的指标作为依据。"]
    needs_more_analysis: List[str] = []
    if metrics.get("commercial_hotspot_mode") == "multi_core":
        can_act_now.append("可以按多核心结构分别审视核心区、次核心区和机会区，不要把整个范围当成单一板块。")
    if metrics.get("target_supply_gap_level") in {"medium", "high"}:
        can_act_now.append("可以优先排查 H3 gap 较高的机会区，再结合现场条件做二次筛选。")
    if audit.missing_evidence:
        needs_more_analysis.append(f"需要补充 {'、'.join(audit.missing_evidence)} 后再做强结论。")
    if decision_strength == "weak":
        needs_more_analysis.append("当前证据强度偏弱，建议先补齐关键数据再给具体选址或业态判断。")
    if mentions_supply(question):
        needs_more_analysis.append("如需具体补位建议，应继续比较目标业态 POI 密度、竞品分布和可达性。")
    do_not_infer = ["不建议直接推断客流、消费能力、营业额或收益。"]
    return {"can_act_now": can_act_now, "needs_more_analysis": needs_more_analysis, "do_not_infer": do_not_infer}


def _required_evidence_labels(question: str, audit: AuditResult) -> List[str]:
    required: List[str] = []
    for item in list(audit.required_evidence or []) + list(audit.missing_evidence or []):
        text = str(item or "").strip()
        if text and text not in required:
            required.append(text)
    if required:
        return required
    if mentions_summary(question) or mentions_supply(question):
        return list(_ALL_BUSINESS_EVIDENCE)
    if mentions_population(question):
        return ["人口概览"]
    if mentions_nightlight(question):
        return ["夜光概览"]
    if mentions_road(question):
        return ["路网概览"]
    return []


def _metric_items_for_question(question: str, audit: AuditResult, metrics: Dict[str, object]) -> List[str]:
    items: List[str] = []
    if metrics.get("business_profile_label"):
        items.append(f"区域画像：{metrics['business_profile_label']}")
    if metrics.get("business_profile_portrait"):
        items.append(f"画像说明：{metrics['business_profile_portrait']}")
    if metrics.get("commercial_hotspot_mode"):
        items.append(f"空间结构：{metrics['commercial_hotspot_mode']}")
    if metrics.get("target_supply_gap_level"):
        items.append(
            f"目标业态缺口：{metrics.get('target_supply_gap_place_type') or '未指定'} / "
            f"{metrics['target_supply_gap_level']} / {metrics.get('target_supply_gap_mode') or 'unclear'}"
        )
    next_options = [item for item in (metrics.get("next_analysis_options") or []) if isinstance(item, dict)]
    if next_options:
        items.append("下一步分析方向：" + "、".join(str(item.get("title") or "") for item in next_options[:3] if str(item.get("title") or "").strip()))
    candidate_zones = metrics.get("target_supply_gap_candidates") or []
    if candidate_zones:
        items.append(f"候选格子：{len(candidate_zones)} 个")
    if metrics.get("business_place_type"):
        items.append(f"目标业态：{metrics['business_place_type']}")
        if metrics.get("business_types"):
            items.append(f"POI 类型：{metrics['business_types']}")
        if metrics.get("business_keywords"):
            items.append(f"关键词：{metrics['business_keywords']}")
    if metrics.get("poi_count") is not None:
        items.append(f"POI 样本量：{metrics['poi_count']}")
    if metrics.get("h3_grid_count") or metrics.get("avg_density_poi_per_km2") is not None:
        density = metrics.get("avg_density_poi_per_km2")
        items.append(f"POI H3 网格：{metrics.get('h3_grid_count') or 0} 个，平均密度：{density if density is not None else '未提供'}")
    if metrics.get("population_total") is not None:
        items.append(f"人口总量：{metrics['population_total']}")
    if metrics.get("nightlight_mean_radiance") is not None:
        items.append(f"夜光均值：{metrics['nightlight_mean_radiance']}")
    if metrics.get("road_node_count") or metrics.get("road_edge_count"):
        items.append(f"路网节点/边段：{metrics.get('road_node_count') or 0}/{metrics.get('road_edge_count') or 0}")
    return items


def _build_structured_output(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    tool_results: List[ToolResult],
    research_notes: List[str],
    audit: AuditResult,
) -> Dict[str, Any]:
    metrics = _summary_metrics(snapshot, artifacts)
    evidence = build_analysis_evidence(snapshot, artifacts)
    decision_strength = _decision_strength(evidence, audit)
    conflicts = _detect_conflicts(metrics, audit)
    limits = _interpretation_limits(evidence, audit)
    support = _select_key_evidence(evidence, question=question)
    decision = DecisionPayload(
        summary=_build_decision_summary(
            question=question,
            metrics=metrics,
            decision_strength=decision_strength,
            conflicts=conflicts,
            missing_evidence=list(audit.missing_evidence or []),
        ),
        mode=_infer_output_mode(question),
        strength=decision_strength,
        can_act=decision_strength != "weak" and not bool(audit.missing_evidence),
    )
    return {
        "metrics": metrics,
        "evidence": evidence,
        "decision_strength": decision_strength,
        "conflicts": conflicts,
        "limits": limits,
        "decision": decision,
        "support": support,
        "counterpoints": _build_counterpoints(
            conflicts=conflicts,
            missing_evidence=list(audit.missing_evidence or []),
            limits=limits,
        ),
        "actions": _build_action_items(
            question=question,
            metrics=metrics,
            audit=audit,
            decision_strength=decision_strength,
        ),
        "boundary": _build_boundary_items(limits),
        "review_contract": build_review_contract(
            question=question,
            snapshot=snapshot,
            artifacts=artifacts,
            tool_results=tool_results,
            audit=audit,
            decision_summary=decision.summary,
        ),
        "research_notes": list(research_notes or []),
        "tool_chain": [result.tool_name for result in tool_results if result.status == "success"],
    }


def build_cards(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    tool_results: List[ToolResult],
    research_notes: List[str],
    audit: AuditResult,
) -> List[AssistantCard]:
    structured = _build_structured_output(
        question=question,
        snapshot=snapshot,
        artifacts=artifacts,
        tool_results=tool_results,
        research_notes=research_notes,
        audit=audit,
    )
    metrics = structured["metrics"]
    support = structured["support"]
    decision = structured["decision"]
    counterpoints = structured["counterpoints"]
    actions = structured["actions"]
    used_tool_names = structured["tool_chain"]
    strength_label = {"strong": "较强", "moderate": "中等", "weak": "偏弱"}.get(decision.strength, "偏弱")
    metric_items = _metric_items_for_question(question, audit, metrics)
    evidence_items = [f"{item.headline}；解释：{item.interpretation}；置信度：{item.confidence}" for item in support]

    recommendation_layers = _recommendation_layers(question, audit, decision.strength, metrics)
    recommendation_items: List[Any] = []
    recommendation_items.extend(_build_candidate_card_items(metrics.get("target_supply_gap_candidates") or []))
    recommendation_items.extend([f"下一步动作：{item.title} - {item.detail}" for item in actions])
    recommendation_items.extend([f"可以直接采取：{item}" for item in recommendation_layers["can_act_now"]])
    recommendation_items.extend([f"需补充后判断：{item}" for item in recommendation_layers["needs_more_analysis"]])
    recommendation_items.extend([f"不建议直接推断：{item}" for item in recommendation_layers["do_not_infer"]])
    recommendation_items.extend([f"{item.title}：{item.detail}" for item in counterpoints])
    recommendation_items.extend(list(research_notes or []))
    recommendation_items.extend([str(item) for item in audit.issues if str(item).strip()])
    suggestion = actions[0].detail if actions else "可以先基于当前证据做方向性判断，再补齐关键缺口。"
    return [
        AssistantCard(
            type="summary",
            title="核心判断",
            content=f"{decision.summary} 证据强度：{strength_label}。",
            items=[f"执行链：{' -> '.join(used_tool_names) or '无'}"],
        ),
        AssistantCard(
            type="evidence",
            title="证据依据",
            content="当前回答基于以下结构化证据，而不是只复述工具执行状态。",
            items=metric_items + evidence_items,
        ),
        AssistantCard(type="recommendation", title="下一步建议", content=suggestion, items=recommendation_items),
    ]


def build_synthesis_payload(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    tool_results: List[ToolResult],
    research_notes: List[str],
    audit: AuditResult,
) -> Dict[str, Any]:
    structured = _build_structured_output(
        question=question,
        snapshot=snapshot,
        artifacts=artifacts,
        tool_results=tool_results,
        research_notes=research_notes,
        audit=audit,
    )
    metrics = structured["metrics"]
    evidence = structured["evidence"]
    tool_result_digest = [
        {
            "tool_name": result.tool_name,
            "status": result.status,
            "result": dict(result.result or {}),
            "warnings": list(result.warnings or []),
        }
        for result in tool_results
    ]
    evidence_items = _metric_items_for_question(question, audit, metrics)
    return {
        "question": question,
        "tool_chain": structured["tool_chain"],
        "metrics": metrics,
        "decision": structured["decision"].model_dump(mode="json"),
        "support": [item.model_dump(mode="json") for item in structured["support"]],
        "counterpoints": [item.model_dump(mode="json") for item in structured["counterpoints"]],
        "actions": [item.model_dump(mode="json") for item in structured["actions"]],
        "boundary": [item.model_dump(mode="json") for item in structured["boundary"]],
        "review_contract": structured["review_contract"],
        "business_profile": {
            "portrait": metrics.get("business_profile_portrait") or _infer_business_portrait(metrics)[0],
            "type": metrics.get("business_profile_label") or _infer_business_portrait(metrics)[0],
            "top_category_mix": metrics.get("poi_category_mix") or [],
            "functional_mix_score": metrics.get("functional_mix_score"),
        },
        "spatial_structure": {
            "hotspot_mode": metrics.get("commercial_hotspot_mode"),
            "summary": metrics.get("commercial_hotspot_summary"),
            "core_zone_count": metrics.get("core_zone_count"),
            "opportunity_zone_count": metrics.get("opportunity_zone_count"),
        },
        "target_supply_gap": {
            "place_type": metrics.get("target_supply_gap_place_type"),
            "supply_gap_level": metrics.get("target_supply_gap_level"),
            "gap_mode": metrics.get("target_supply_gap_mode"),
            "summary": metrics.get("target_supply_gap_summary"),
            "candidate_zones": metrics.get("target_supply_gap_candidates") or [],
        },
        "evidence_matrix": [item.model_dump(mode="json") for item in evidence],
        "decision_strength": structured["decision_strength"],
        "interpretation_limits": structured["limits"],
        "recommendation_layers": _recommendation_layers(question, audit, structured["decision_strength"], metrics),
        "evidence_items": evidence_items,
        "tool_results": tool_result_digest,
        "research_notes": list(research_notes or []),
        "audit_issues": [str(item) for item in audit.issues if str(item).strip()],
        "missing_evidence": list(audit.missing_evidence or []),
        "required_evidence": _required_evidence_labels(question, audit),
    }


def build_next_suggestions(question: str, audit: AuditResult) -> List[str]:
    suggestions: List[str] = []
    if audit.missing_evidence:
        suggestions.append(f"如需更完整结论，可以继续补充 {'、'.join(audit.missing_evidence)} 相关分析。")
    if mentions_population(question):
        suggestions.append("继续追问年龄结构或与周边商业供给的匹配关系。")
    return suggestions


def build_citations(snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> List[str]:
    citations: List[str] = []
    if artifacts.get("current_poi_h3_summary") or (snapshot.h3 or {}).get("summary"):
        citations.append("analysis_snapshot.h3.summary")
    if artifacts.get("current_road_summary") or (snapshot.road or {}).get("summary"):
        citations.append("analysis_snapshot.road.summary")
    if artifacts.get("current_population_summary") or (snapshot.population or {}).get("summary"):
        citations.append("analysis_snapshot.population.summary")
    if artifacts.get("current_nightlight_summary") or (snapshot.nightlight or {}).get("summary"):
        citations.append("analysis_snapshot.nightlight.summary")
    if artifacts.get("current_pois") or snapshot.pois or snapshot.poi_summary:
        citations.append("analysis_snapshot.pois")
    for key in ("business_site_advice", "current_business_profile", "current_commercial_hotspots", "current_target_supply_gap", "current_next_analysis_options"):
        if artifacts.get(key):
            citations.append(key)
    return citations


def _build_candidate_card_items(candidate_zones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for zone in candidate_zones[:3]:
        h3_id = str(zone.get("h3_id") or "").strip()
        label = str(zone.get("display_title") or zone.get("approx_address") or zone.get("label") or "候选格").strip()
        reason = str(zone.get("reason_summary") or "").strip()
        gap_score = zone.get("gap_score")
        if gap_score is not None:
            label = f"{label} - 缺口分数 {float(gap_score):.2f}"
        items.append(
            {
                "type": "h3_candidate",
                "label": label,
                "text": f"{label}{(' - 判断：' + reason) if reason else ''}",
                "h3_id": h3_id,
                "approx_address": str(zone.get("approx_address") or "").strip(),
                "reason_summary": reason,
                "center_point": dict(zone.get("center_point") or {}) if isinstance(zone.get("center_point"), dict) else {},
            }
        )
    return items


def build_panel_payloads(question: str, snapshot: AnalysisSnapshot, artifacts: Dict[str, object]) -> Dict[str, Any]:
    payloads: Dict[str, Any] = {}
    metrics = _summary_metrics(snapshot, artifacts)
    one_line_conclusion = {
        "type_tag": str(metrics.get("business_profile_label") or "待补充"),
        "structure_desc": str(metrics.get("commercial_hotspot_summary") or metrics.get("h3_structure_summary") or "待补充"),
        "value_judgment": str(metrics.get("target_supply_gap_summary") or metrics.get("business_profile_summary") or "待补充"),
    }
    icsc_tags = (
        [str(item).strip() for item in (metrics.get("business_types") or []) if str(item).strip()]
        if isinstance(metrics.get("business_types"), list)
        else []
    )
    if not icsc_tags:
        icsc_tags = (
            [str(item).strip() for item in (metrics.get("poi_structure_tags") or []) if str(item).strip()]
            if isinstance(metrics.get("poi_structure_tags"), list)
            else []
        )
    evidence_refs = build_citations(snapshot, artifacts)
    payloads["summary_pack"] = {
        "one_line_conclusion": one_line_conclusion,
        "icsc_tags": icsc_tags,
        "key_metrics": {
            "poi_structure": {"poi_count": metrics.get("poi_count"), "summary": metrics.get("poi_structure_summary") or "暂无 POI 结构摘要"},
            "population_structure": {"population_total": metrics.get("population_total"), "summary": metrics.get("population_profile_summary") or "暂无人口结构摘要"},
            "nightlight_data": {"nightlight_mean_radiance": metrics.get("nightlight_mean_radiance"), "summary": metrics.get("nightlight_pattern_summary") or "暂无夜光结构摘要"},
            "road_accessibility": {
                "road_node_count": metrics.get("road_node_count"),
                "road_edge_count": metrics.get("road_edge_count"),
                "summary": metrics.get("road_pattern_summary") or "暂无路网可达性摘要",
            },
        },
        "behavior_inference": {
            "user_profile": metrics.get("business_profile_portrait") or metrics.get("business_profile_label") or "待补充",
            "consumption_features": metrics.get("business_profile_summary") or metrics.get("target_supply_gap_summary") or "待补充",
            "time_features": metrics.get("nightlight_pattern_summary") or "待补充",
        },
        "evidence_refs": evidence_refs,
        "confidence": "moderate" if len(evidence_refs) >= 2 else "weak",
    }
    if not (mentions_supply(question) or mentions_summary(question) or "current_poi_h3" in artifacts or "current_poi_h3_grid" in artifacts):
        return payloads
    poi_h3_payload = artifacts.get("current_poi_h3") if isinstance(artifacts.get("current_poi_h3"), dict) else {}
    current_poi_h3_grid = artifacts.get("current_poi_h3_grid") if isinstance(artifacts.get("current_poi_h3_grid"), dict) else {}
    current_poi_h3_summary = artifacts.get("current_poi_h3_summary") if isinstance(artifacts.get("current_poi_h3_summary"), dict) else {}
    current_poi_h3_charts = artifacts.get("current_poi_h3_charts") if isinstance(artifacts.get("current_poi_h3_charts"), dict) else {}
    target_supply_gap = artifacts.get("current_target_supply_gap") if isinstance(artifacts.get("current_target_supply_gap"), dict) else {}
    h3_structure = artifacts.get("current_h3_structure_analysis") if isinstance(artifacts.get("current_h3_structure_analysis"), dict) else {}
    grid = current_poi_h3_grid or (poi_h3_payload.get("grid") if isinstance(poi_h3_payload.get("grid"), dict) else {})
    summary = current_poi_h3_summary or (poi_h3_payload.get("summary") if isinstance(poi_h3_payload.get("summary"), dict) else {})
    charts = current_poi_h3_charts or (poi_h3_payload.get("charts") if isinstance(poi_h3_payload.get("charts"), dict) else {})
    has_h3_payload = bool((grid or {}).get("features")) or bool(summary)
    if has_h3_payload:
        payloads["h3_result"] = {
            "grid": grid,
            "summary": summary,
            "charts": charts,
            "ui": {
                "main_stage": "evaluate" if is_target_supply_gap_ready(target_supply_gap) else "analysis",
                "sub_tab": "gap" if is_target_supply_gap_ready(target_supply_gap) else "metric_map",
                "target_category": str(h3_structure.get("target_category") or "").strip(),
            },
        }
    return payloads


def build_summary_panel_payloads(
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    *,
    summary_pack: Dict[str, Any] | None = None,
    summary_status: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payloads = build_panel_payloads(question, snapshot, artifacts)
    payloads.pop("summary_pack", None)
    if isinstance(summary_status, dict):
        payloads["summary_status"] = dict(summary_status)
    if isinstance(summary_pack, dict) and summary_pack:
        payloads["summary_pack"] = dict(summary_pack)
    return payloads


def enrich_answer_output(
    *,
    output: AgentTurnOutput,
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    tool_results: List[ToolResult] | None = None,
    research_notes: List[str] | None = None,
    audit: AuditResult | None = None,
) -> AgentTurnOutput:
    audit = audit or AuditResult()
    structured = _build_structured_output(
        question=question,
        snapshot=snapshot,
        artifacts=artifacts,
        tool_results=list(tool_results or []),
        research_notes=list(research_notes or []),
        audit=audit,
    )
    cards = [AssistantCard.model_validate(item) if not isinstance(item, AssistantCard) else item for item in (output.cards or [])]
    target_supply_gap = artifacts.get("current_target_supply_gap") if isinstance(artifacts.get("current_target_supply_gap"), dict) else {}
    candidate_items = _build_candidate_card_items(list(target_supply_gap.get("candidate_zones") or []))
    if candidate_items and mentions_supply(question):
        summary = next((card for card in cards if card.type == "summary"), None)
        if summary is not None and "候选" not in str(summary.content or ""):
            summary.content = f"{summary.content} 可优先查看前 3 个候选格。".strip()
    if candidate_items:
        recommendation = next((card for card in cards if card.type == "recommendation"), None)
        if recommendation is None:
            recommendation = AssistantCard(type="recommendation", title="下一步建议", content="", items=[])
            cards.append(recommendation)
        existing_candidate_ids = {
            str(item.get("h3_id") or "").strip()
            for item in recommendation.items
            if isinstance(item, dict) and str(item.get("type") or "").strip() == "h3_candidate"
        }
        for item in candidate_items:
            h3_id = str(item.get("h3_id") or "").strip()
            if h3_id and h3_id in existing_candidate_ids:
                continue
            recommendation.items.append(item)
        if not recommendation.content and mentions_supply(question):
            recommendation.content = "可先查看下面的候选格，再结合实地租金、竞品质量和动线做最终判断。"
    output.cards = cards
    if not getattr(output, "decision", None) or not str(output.decision.summary or "").strip():
        output.decision = structured["decision"]
    if not list(output.support or []):
        output.support = structured["support"]
    if not list(output.counterpoints or []):
        output.counterpoints = structured["counterpoints"]
    if not list(output.actions or []):
        output.actions = structured["actions"]
    if not list(output.boundary or []):
        output.boundary = structured["boundary"]
    output.review_contract = structured["review_contract"]
    output.panel_payloads = build_summary_panel_payloads(question, snapshot, artifacts)
    return output
