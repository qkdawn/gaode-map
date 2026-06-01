from __future__ import annotations

from typing import Any, Dict, List

from .analysis_extractors import is_target_supply_gap_ready
from .intent_signals import mentions_nightlight, mentions_population, mentions_road, mentions_summary, mentions_supply
from .llm_digest import tool_results_llm_digest
from .synthesis_evidence import build_analysis_evidence as _build_analysis_evidence_from_module
from .synthesis_metrics import build_summary_metrics as _build_summary_metrics_from_module
from .schemas import AgentEvidenceItem, AgentTurnOutput, AnalysisSnapshot, AuditResult, ToolResult

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


def _select_key_evidence(evidence: List[AgentEvidenceItem], *, question: str) -> List[Dict[str, Any]]:
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
    return [
        {
            "metric": item.metric,
            "headline": _evidence_headline(item),
            "value": item.value,
            "interpretation": item.interpretation,
            "source": item.source,
            "confidence": item.confidence,
            "limitation": item.limitation,
        }
        for item in ordered[:5]
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


def _business_profile_block(metrics: Dict[str, object]) -> Dict[str, Any]:
    portrait, reasons = _infer_business_portrait(metrics)
    return {
        "portrait": metrics.get("business_profile_portrait") or portrait,
        "type": metrics.get("business_profile_label") or portrait,
        "top_category_mix": metrics.get("poi_category_mix") or [],
        "functional_mix_score": metrics.get("functional_mix_score"),
        "reasons": reasons,
    }


def _spatial_structure_block(metrics: Dict[str, object]) -> Dict[str, Any]:
    return {
        "hotspot_mode": metrics.get("commercial_hotspot_mode"),
        "summary": metrics.get("commercial_hotspot_summary"),
        "core_zone_count": metrics.get("core_zone_count"),
        "opportunity_zone_count": metrics.get("opportunity_zone_count"),
    }


def _target_supply_gap_block(metrics: Dict[str, object]) -> Dict[str, Any]:
    return {
        "place_type": metrics.get("target_supply_gap_place_type"),
        "supply_gap_level": metrics.get("target_supply_gap_level"),
        "gap_mode": metrics.get("target_supply_gap_mode"),
        "summary": metrics.get("target_supply_gap_summary"),
        "candidate_zones": metrics.get("target_supply_gap_candidates") or [],
    }


def _compose_business_profile_summary(metrics: Dict[str, object], business_profile: Dict[str, Any]) -> str:
    portrait = _as_text(business_profile.get("portrait") or metrics.get("business_profile_portrait"))
    reasons = [str(item).strip() for item in (business_profile.get("reasons") or []) if str(item).strip()]
    hotspot_mode = _as_text(metrics.get("commercial_hotspot_mode"))
    functional_mix_score = metrics.get("functional_mix_score")
    parts: List[str] = []
    if portrait:
        parts.append(f"业态画像上，这里更接近{portrait}")
    if reasons:
        parts.append(reasons[0].rstrip("。"))
    if hotspot_mode:
        parts.append(f"整体空间组织偏{hotspot_mode}")
    if functional_mix_score not in (None, ""):
        parts.append(f"功能混合度约为 {functional_mix_score}")
    return "，".join([part for part in parts if part]).strip("，")


def _compose_spatial_structure_summary(metrics: Dict[str, object], spatial_structure: Dict[str, Any]) -> str:
    summary = _as_text(spatial_structure.get("summary") or metrics.get("commercial_hotspot_summary"))
    if summary:
        return summary
    core_zone_count = spatial_structure.get("core_zone_count")
    opportunity_zone_count = spatial_structure.get("opportunity_zone_count")
    hotspot_mode = _as_text(spatial_structure.get("hotspot_mode") or metrics.get("commercial_hotspot_mode"))
    parts: List[str] = []
    if hotspot_mode:
        parts.append(f"空间结构更接近{hotspot_mode}")
    if core_zone_count not in (None, ""):
        parts.append(f"内部形成 {core_zone_count} 个核心区")
    if opportunity_zone_count not in (None, ""):
        parts.append(f"并保留 {opportunity_zone_count} 个机会区")
    return "，".join([part for part in parts if part]).strip("，")


def _compose_population_vitality_summary(metrics: Dict[str, object]) -> str:
    parts: List[str] = []
    if metrics.get("population_total") not in (None, ""):
        parts.append(f"人口基盘约 {metrics.get('population_total')}")
    if metrics.get("nightlight_mean_radiance") not in (None, ""):
        parts.append(f"夜光均值约 {metrics.get('nightlight_mean_radiance')}")
    if metrics.get("road_node_count") not in (None, "") and metrics.get("road_edge_count") not in (None, ""):
        parts.append(f"路网节点/边段约为 {metrics.get('road_node_count')}/{metrics.get('road_edge_count')}")
    return "，".join([part for part in parts if part]).strip("，")


def _build_evidence_highlights(metrics: Dict[str, object], key_evidence: List[Dict[str, Any]]) -> List[str]:
    highlights: List[str] = []
    for item in key_evidence[:4]:
        headline = _as_text(item.get("headline"))
        interpretation = _as_text(item.get("interpretation"))
        if headline and interpretation:
            highlights.append(f"{headline}：{interpretation}")
        elif headline:
            highlights.append(headline)
    poi_mix = [item for item in (metrics.get("poi_category_mix") or []) if isinstance(item, dict)]
    if poi_mix:
        top_labels = "、".join(
            f"{item.get('label')} {item.get('ratio')}%"
            for item in poi_mix[:3]
            if _as_text(item.get("label")) and item.get("ratio") not in (None, "")
        )
        if top_labels:
            highlights.append(f"头部业态占比：{top_labels}")
    deduped: List[str] = []
    for item in highlights:
        text = str(item or "").strip()
        if text and text not in deduped:
            deduped.append(text)
    return deduped[:6]


def build_answer_evidence_payload(
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
    conflicts = _detect_conflicts(metrics, audit)
    interpretation_limits = _interpretation_limits(evidence, audit)
    business_profile = _business_profile_block(metrics)
    spatial_structure = _spatial_structure_block(metrics)
    target_supply_gap = _target_supply_gap_block(metrics)
    key_evidence = _select_key_evidence(evidence, question=question)
    base_payload = {
        "question": question,
        "tool_chain": [result.tool_name for result in tool_results if result.status == "success"],
        "metrics": metrics,
        "key_evidence": key_evidence,
        "interpretation_limits": interpretation_limits,
        "tool_results": tool_results_llm_digest(tool_results),
        "research_notes": list(research_notes or []),
        "audit_issues": [str(item) for item in audit.issues if str(item).strip()],
        "missing_evidence": list(audit.missing_evidence or []),
        "required_evidence": _required_evidence_labels(question, audit),
        "conflicting_evidence": conflicts,
        "business_profile": business_profile,
        "spatial_structure": spatial_structure,
        "target_supply_gap": target_supply_gap,
    }
    direct_answer_seed = _compose_direct_answer(question, base_payload)
    return {
        **base_payload,
        "direct_answer_seed": direct_answer_seed,
        "business_profile_summary": _compose_business_profile_summary(metrics, business_profile),
        "spatial_structure_summary": _compose_spatial_structure_summary(metrics, spatial_structure),
        "population_vitality_summary": _compose_population_vitality_summary(metrics),
        "evidence_highlights": _build_evidence_highlights(metrics, key_evidence),
    }


def _compose_direct_answer(question: str, payload: Dict[str, Any]) -> str:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    business_profile = payload.get("business_profile") if isinstance(payload.get("business_profile"), dict) else {}
    spatial_structure = payload.get("spatial_structure") if isinstance(payload.get("spatial_structure"), dict) else {}
    target_supply_gap = payload.get("target_supply_gap") if isinstance(payload.get("target_supply_gap"), dict) else {}
    mode = _infer_output_mode(question)

    if mode == "action":
        next_options = [item for item in (metrics.get("next_analysis_options") or []) if isinstance(item, dict)]
        if next_options:
            top = next_options[0]
            return f"下一步最值得优先做的是 {top.get('title') or '继续分析'}，因为{top.get('why') or '它最能补齐当前判断缺口'}。"
        if target_supply_gap.get("supply_gap_level") in {"medium", "high"}:
            place_type = _as_text(target_supply_gap.get("place_type"), "目标业态")
            return f"如果你的目标是继续推进选址或补位，当前更适合先围绕 {place_type} 的供给缺口做机会区预筛。"
        return "下一步更适合先补齐关键证据，再决定是否进入更细的选址或经营判断。"

    if mentions_supply(question) and target_supply_gap.get("supply_gap_level"):
        place_type = _as_text(target_supply_gap.get("place_type"), "目标业态")
        gap_level = _as_text(target_supply_gap.get("supply_gap_level"), "未明确")
        gap_mode = _as_text(target_supply_gap.get("gap_mode"))
        summary = _as_text(target_supply_gap.get("summary"))
        if summary:
            return summary
        if gap_mode:
            return f"从现有证据看，这里对 {place_type} 更像是存在 {gap_level} 级供给缺口，核心问题偏向 {gap_mode}。"
        return f"从现有证据看，这里对 {place_type} 仍存在 {gap_level} 级供给缺口。"

    if mode == "judgment" and mentions_road(question):
        road_summary = _as_text(metrics.get("road_pattern_summary"))
        if road_summary:
            return road_summary
        return "这里路网表现偏弱时，通常不是单一指标异常，而是可达性、连接度和与现有商业热点的衔接一起偏弱。"

    portrait = _as_text(business_profile.get("portrait")) or _as_text(metrics.get("business_profile_portrait"))
    hotspot_summary = _as_text(spatial_structure.get("summary"))
    if portrait and hotspot_summary:
        return f"整体看，这个区域更接近{portrait}，而且{hotspot_summary}"
    if portrait:
        return f"整体看，这个区域更接近{portrait}。"
    if hotspot_summary:
        return hotspot_summary
    return "当前证据可以支持方向性判断，但更适合先回答区域画像和结构特征，不适合外推出更细的经营结论。"


def build_answer_fallback(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, object],
    tool_results: List[ToolResult] | None = None,
    research_notes: List[str] | None = None,
    audit: AuditResult | None = None,
) -> str:
    audit = audit or AuditResult()
    payload = build_answer_evidence_payload(
        question=question,
        snapshot=snapshot,
        artifacts=artifacts,
        tool_results=list(tool_results or []),
        research_notes=list(research_notes or []),
        audit=audit,
    )
    mode = _infer_output_mode(question)
    direct_answer = _as_text(payload.get("direct_answer_seed") or _compose_direct_answer(question, payload))
    business_profile_summary = _as_text(payload.get("business_profile_summary"))
    spatial_structure_summary = _as_text(payload.get("spatial_structure_summary"))
    population_vitality_summary = _as_text(payload.get("population_vitality_summary"))
    key_evidence = [item for item in (payload.get("key_evidence") or []) if isinstance(item, dict)]
    conflicts = [str(item).strip() for item in (payload.get("conflicting_evidence") or []) if str(item).strip()]
    missing_evidence = [str(item).strip() for item in (payload.get("missing_evidence") or []) if str(item).strip()]
    interpretation_limits = [str(item).strip() for item in (payload.get("interpretation_limits") or []) if str(item).strip()]
    support_lines = [
        f"{_as_text(item.get('headline'), '证据')}：{_as_text(item.get('interpretation'))}"
        for item in key_evidence[:3]
        if _as_text(item.get("interpretation"))
    ]
    paragraphs: List[str] = []
    if mode == "action":
        if direct_answer:
            paragraphs.append(direct_answer)
        if support_lines:
            paragraphs.append("当前更主要的依据是" + "；".join(support_lines[:2]) + "。")
        if conflicts:
            paragraphs.append("需要注意的是" + conflicts[0].rstrip("。") + "。")
        elif missing_evidence:
            paragraphs.append("当前还缺少 " + "、".join(missing_evidence[:2]) + "，所以下一步更适合先补齐这些缺口。")
        else:
            target_gap = payload.get("target_supply_gap") if isinstance(payload.get("target_supply_gap"), dict) else {}
            if target_gap.get("candidate_zones"):
                paragraphs.append("下一步可优先查看 gap 较高的候选格，再结合实地条件继续筛选。")
    elif mode == "judgment":
        if direct_answer:
            paragraphs.append(direct_answer)
        if support_lines:
            paragraphs.append("主要依据是" + "；".join(support_lines[:2]) + "。")
        if conflicts:
            paragraphs.append("需要注意的是" + conflicts[0].rstrip("。") + "。")
        elif missing_evidence:
            paragraphs.append("当前还缺少 " + "、".join(missing_evidence[:2]) + "，所以这个判断更适合先停留在方向性层面。")
        elif interpretation_limits:
            paragraphs.append("解释边界上，" + interpretation_limits[0].rstrip("。") + "。")
    else:
        second_parts = [item.rstrip("。") for item in (business_profile_summary, spatial_structure_summary) if item]
        third_parts = [item.rstrip("。") for item in (population_vitality_summary,) if item]
        if support_lines:
            third_parts.append("主要依据是" + "；".join(support_lines[:3]))
        if direct_answer:
            paragraphs.append(direct_answer)
        if second_parts:
            paragraphs.append("；".join(second_parts) + "。")
        elif support_lines:
            paragraphs.append("主要依据是" + "；".join(support_lines[:2]) + "。")
        if conflicts:
            third_parts.append("需要注意的是" + conflicts[0].rstrip("。"))
        elif missing_evidence:
            third_parts.append("当前还缺少 " + "、".join(missing_evidence[:2]) + "，所以更适合做区域画像层面的判断")
        elif interpretation_limits:
            third_parts.append("解释边界上，" + interpretation_limits[0].rstrip("。"))
        if third_parts:
            paragraphs.append("；".join([part for part in third_parts if part]) + "。")
    answer = "\n\n".join([part.strip() for part in paragraphs if str(part).strip()]).strip()
    if answer:
        return answer

    required_labels = [str(item).strip() for item in _required_evidence_labels(question, audit) if str(item).strip()]
    if required_labels:
        return f"当前可以先做方向性判断，但还需要补充 {('、'.join(required_labels[:3]))} 相关证据，才能把结论说得更稳。"
    return "当前证据可以支持方向性回答，但还不适合外推出更细的经营结论。"


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
    if not _as_text(output.answer):
        output.answer = build_answer_fallback(
            question=question,
            snapshot=snapshot,
            artifacts=artifacts,
            tool_results=list(tool_results or []),
            research_notes=list(research_notes or []),
            audit=audit,
        )
    output.panel_payloads = build_summary_panel_payloads(question, snapshot, artifacts)
    return output
