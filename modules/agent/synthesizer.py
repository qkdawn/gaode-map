from __future__ import annotations

from typing import Any, Dict, List

from .analysis_extractors import is_target_supply_gap_ready
from .intent_signals import mentions_nightlight, mentions_population, mentions_road, mentions_summary, mentions_supply
from .llm_digest import answer_tool_results_digest
from .reasoning_rubric import FINAL_SYNTHESIS_REASONING_INSTRUCTIONS, reasoning_rubric_payload
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


def _answer_depth_guidance(question: str) -> Dict[str, Any]:
    text = str(question or "")
    concise_tokens = (
        "是什么意思",
        "什么含义",
        "定义",
        "多少",
        "几个",
        "是否完成",
        "完成了吗",
        "状态",
        "单项",
        "均值",
        "总量",
    )
    full_tokens = (
        "总结",
        "商业特征",
        "下一步",
        "继续",
        "行动",
        "方案",
        "建议",
        "选址",
        "补位",
        "空间结构",
        "空间关系",
        "规划",
        "研判",
        "为什么",
        "分析一下",
    )
    is_concise = any(token in text for token in concise_tokens)
    is_full = any(token in text for token in full_tokens)
    target_depth = "concise" if is_concise and not is_full else ("full" if is_full else "balanced")
    if target_depth == "full":
        guidance = "高价值问题要充分展开：围绕用户问题选择自然结构，说明空间关系、主要矛盾或机会、证据支撑、替代解释、边界和后续验证；商业总结应按证据价值覆盖 POI/H3/路网/人口/夜光，不要求固定标题或固定段数；生成结论前必须按 Evidence-Aware Reasoning 五步法检查 Observation、Mechanism、Alternative、Evidence Quality、Implication。"
        suggested_shape = "内容驱动的自然段或小标题，覆盖必要证据、判断边界和验证动作"
    elif target_depth == "concise":
        guidance = "简单问题保持短答：只回答关键结论、必要证据和解释边界，不扩展成报告，也不强制展开五步法。"
        suggested_shape = "一个直接结论 + 1 到 2 个必要说明"
    else:
        guidance = "按证据复杂度自然展开，避免过短的指标转述，也避免无证据长篇；涉及判断时检查替代解释和证据质量。"
        suggested_shape = "按问题自然组织若干段"
    return {
        "target_depth": target_depth,
        "reason": guidance,
        "suggested_shape": suggested_shape,
        "reasoning_skill": "evidence_aware_reasoning" if target_depth != "concise" else "optional_for_concise",
        "reasoning_instructions": FINAL_SYNTHESIS_REASONING_INSTRUCTIONS if target_depth != "concise" else [],
        "full_depth_triggers": ["总结", "商业特征", "下一步", "行动方案", "选址/补位", "空间结构", "规划式分析"],
        "concise_triggers": ["单项指标", "定义", "状态", "数量", "是否完成", "某个数字含义"],
    }


def _evidence_headline(item: AgentEvidenceItem) -> str:
    if item.metric == "next_analysis_options" and isinstance(item.value, dict):
        options = [option for option in (item.value.get("options") or []) if isinstance(option, dict)]
        if options:
            return f"next_analysis_option={options[0].get('title') or '-'}"
        return "next_analysis_options_available"
    if item.metric == "business_profile" and isinstance(item.value, dict):
        return f"poi_mix_signal={item.value.get('poi_mix_signal') or item.value.get('business_profile') or '-'}"
    if item.metric == "commercial_hotspots" and isinstance(item.value, dict):
        return f"hotspot_mode={item.value.get('hotspot_mode') or '-'}; core_zone_count={item.value.get('core_zone_count') or 0}"
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
            conflicts.append("nightlight_mean_ge_3_population_lt_2000")
    except (TypeError, ValueError):
        pass
    try:
        if poi_count not in (None, "") and road_nodes not in (None, "") and int(poi_count) >= 20 and int(road_nodes) <= 40:
            conflicts.append("poi_count_ge_20_road_nodes_le_40")
    except (TypeError, ValueError):
        pass
    if density not in (None, "") and metrics.get("target_supply_gap_level") in {"medium", "high"}:
        conflicts.append("density_available_target_gap_medium_or_high")
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
        return "poi_mix_unavailable", []

    top_labels = {str(item.get("label") or ""): float(item.get("ratio") or 0.0) for item in mix}
    ordered = [f"{item.get('label')} {item.get('count')} 个" for item in mix[:3]]
    dining_ratio = top_labels.get("餐饮", 0.0)
    shopping_ratio = top_labels.get("购物", 0.0)
    lodging_ratio = top_labels.get("住宿", 0.0)
    office_ratio = top_labels.get("公司", 0.0) + top_labels.get("商务住宅", 0.0)
    culture_ratio = top_labels.get("科教文化", 0.0)

    signal_parts: List[str] = []
    if dining_ratio + shopping_ratio >= 0.45:
        signal_parts.append("dining_shopping_ratio_ge_0_45")
    if lodging_ratio >= 0.12:
        signal_parts.append("lodging_ratio_ge_0_12")
    if office_ratio >= 0.18:
        signal_parts.append("office_ratio_ge_0_18")
    if culture_ratio >= 0.1:
        signal_parts.append("culture_ratio_ge_0_10")
    portrait = ",".join(signal_parts) or "no_ratio_threshold_hit"

    reasons: List[str] = []
    if ordered:
        reasons.append(f"top_categories={'/'.join(ordered)}")
    if culture_ratio >= 0.1:
        reasons.append("culture_ratio_ge_0_10")
    if office_ratio >= 0.12:
        reasons.append("office_ratio_ge_0_12")
    if lodging_ratio >= 0.08:
        reasons.append("lodging_ratio_ge_0_08")
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
        "portrait": portrait,
        "type": "poi_mix_raw_signal" if portrait != "poi_mix_unavailable" else portrait,
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
        parts.append(f"poi_mix_signal={portrait}")
    if reasons:
        parts.append(reasons[0].rstrip("。"))
    if hotspot_mode:
        parts.append(f"hotspot_mode={hotspot_mode}")
    if functional_mix_score not in (None, ""):
        parts.append(f"functional_mix_score={functional_mix_score}")
    return "; ".join([part for part in parts if part])


def _compose_spatial_structure_summary(metrics: Dict[str, object], spatial_structure: Dict[str, Any]) -> str:
    summary = _as_text(spatial_structure.get("summary") or metrics.get("commercial_hotspot_summary"))
    if summary:
        return summary
    core_zone_count = spatial_structure.get("core_zone_count")
    opportunity_zone_count = spatial_structure.get("opportunity_zone_count")
    hotspot_mode = _as_text(spatial_structure.get("hotspot_mode") or metrics.get("commercial_hotspot_mode"))
    parts: List[str] = []
    if hotspot_mode:
        parts.append(f"hotspot_mode={hotspot_mode}")
    if core_zone_count not in (None, ""):
        parts.append(f"core_zone_count={core_zone_count}")
    if opportunity_zone_count not in (None, ""):
        parts.append(f"opportunity_zone_count={opportunity_zone_count}")
    return "; ".join([part for part in parts if part])


def _compose_population_vitality_summary(metrics: Dict[str, object]) -> str:
    parts: List[str] = []
    if metrics.get("population_total") not in (None, ""):
        parts.append(f"population_total={metrics.get('population_total')}")
    if metrics.get("nightlight_mean_radiance") not in (None, ""):
        parts.append(f"nightlight_mean_radiance={metrics.get('nightlight_mean_radiance')}")
    if metrics.get("road_node_count") not in (None, "") and metrics.get("road_edge_count") not in (None, ""):
        parts.append(f"road_node_edge_count={metrics.get('road_node_count')}/{metrics.get('road_edge_count')}")
    return "; ".join([part for part in parts if part])


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


def _frontend_visual_snapshot_block(artifacts: Dict[str, object], research_notes: List[str]) -> Dict[str, Any]:
    snapshots = artifacts.get("visual_snapshots") if isinstance(artifacts, dict) else []
    available: List[Dict[str, Any]] = []
    if isinstance(snapshots, list):
        for item in snapshots[:12]:
            if not isinstance(item, dict):
                continue
            available.append(
                {
                    "snapshot_id": _as_text(item.get("snapshot_id")),
                    "kind": _as_text(item.get("kind")),
                    "title": _as_text(item.get("title")),
                    "source": _as_text(item.get("source")) or "frontend_map",
                    "captured_at": _as_text(item.get("captured_at")),
                    "bounds": item.get("bounds") if isinstance(item.get("bounds"), dict) else {},
                    "warnings": [str(warning) for warning in (item.get("warnings") or []) if str(warning).strip()],
                }
            )
    warning_notes = [
        str(note).strip()
        for note in (research_notes or [])
        if str(note).strip() and ("快照" in str(note) or "图片" in str(note))
    ]
    return {
        "available": available,
        "skipped_or_warnings": warning_notes[:8],
        "evidence_rule": "这些是前端自动截取的可见地图图层，只能作为视觉观察证据，不能当作后端计算指标。",
    }


def _spatial_narrative_guidance() -> Dict[str, Any]:
    return {
        "structure_first": True,
        "goal": "先提炼区域空间主结构，再让 POI、H3、路网、人口和夜光指标支撑这个结构。",
        "relationship_lenses": ["主结构", "内圈/外圈", "锚点关系", "学生/社区/游逛动线", "界面", "串联", "夹持", "承托", "连续发生"],
        "action_lenses": ["先说片区矛盾或机会", "再说动作为什么重要", "最后说用什么证据筛掉伪机会"],
        "scenario_lenses": ["学生高频低客单", "社区晚间刚需", "文创游逛停留", "夜间社交消费", "外来目的性到访"],
        "anti_patterns": ["不要逐项翻译指标面板", "不要只罗列地名", "不要把行动建议写成工具流程", "不要把未读取 EvidenceNode 的地名或空间对象写进结论"],
        "evidence_rule": "具体地名和空间对象仍只能来自已读取的 read_analysis_evidence_node EvidenceNode；本指南只约束叙事组织方式。",
    }


def _business_analyst_skeleton_block(artifacts: Dict[str, object]) -> Dict[str, Any]:
    context = artifacts.get("business_analyst_skeleton") if isinstance(artifacts, dict) else {}
    if not isinstance(context, dict) or not context:
        return {"status": "skipped", "reason": "no_business_analyst_skeleton"}
    selected_skill = context.get("selected_skill") if isinstance(context.get("selected_skill"), dict) else {}
    model_graph = context.get("model_graph") if isinstance(context.get("model_graph"), dict) else {}
    return {
        "status": str(context.get("status") or "skipped"),
        "reason": str(context.get("reason") or ""),
        "selected_skill": {
            "skill_id": str(selected_skill.get("skill_id") or ""),
            "title": str(selected_skill.get("title") or ""),
            "purpose": str(selected_skill.get("purpose") or ""),
            "uses_model_graph": str(selected_skill.get("uses_model_graph") or ""),
            "agent_autonomy": selected_skill.get("agent_autonomy") if isinstance(selected_skill.get("agent_autonomy"), dict) else {},
        },
        "recommended_path": list(context.get("recommended_path") or [])[:8],
        "path_relations": list(context.get("path_relations") or [])[:8],
        "optional_branches": context.get("optional_branches") if isinstance(context.get("optional_branches"), dict) else {},
        "model_tool_map": context.get("model_tool_map") if isinstance(context.get("model_tool_map"), dict) else {},
        "skip_conditions": context.get("skip_conditions") if isinstance(context.get("skip_conditions"), dict) else {},
        "guardrails": list(context.get("guardrails") or [])[:12],
        "missing_evidence_defaults": list(context.get("missing_evidence_defaults") or [])[:8],
        "answer_guidance": list(context.get("answer_guidance") or [])[:8],
        "model_graph": {
            "graph_id": str(model_graph.get("graph_id") or ""),
            "entry_nodes": list(model_graph.get("entry_nodes") or []),
            "target_nodes": list(model_graph.get("target_nodes") or []),
            "nodes": model_graph.get("nodes") if isinstance(model_graph.get("nodes"), dict) else {},
        },
    }


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
    business_analyst_skeleton = _business_analyst_skeleton_block(artifacts)
    base_payload = {
        "question": question,
        "tool_chain": [result.tool_name for result in tool_results if result.status == "success"],
        "metrics": metrics,
        "key_evidence": key_evidence,
        "interpretation_limits": interpretation_limits,
        "tool_results": answer_tool_results_digest(tool_results),
        "research_notes": list(research_notes or []),
        "audit_issues": [str(item) for item in audit.issues if str(item).strip()],
        "missing_evidence": list(audit.missing_evidence or []),
        "required_evidence": _required_evidence_labels(question, audit),
        "conflicting_evidence": conflicts,
        "business_profile": business_profile,
        "spatial_structure": spatial_structure,
        "target_supply_gap": target_supply_gap,
        "frontend_visual_snapshots": _frontend_visual_snapshot_block(artifacts, research_notes),
        "map_search_context": {
            "available": bool((artifacts or {}).get("frontend_map_search_context")),
            "artifact_key": "frontend_map_search_context" if (artifacts or {}).get("frontend_map_search_context") else "",
            "evidence_rule": "具体地名、H3 格子、路网线段、人口/夜光 cell 只有通过 search_analysis_context 命中并 read_analysis_evidence_node 读取 EvidenceNode 后，才能在最终回答中引用。",
        },
        "business_analyst_skeleton": business_analyst_skeleton,
        "spatial_narrative_guidance": _spatial_narrative_guidance(),
        "answer_depth_guidance": _answer_depth_guidance(question),
        "reasoning_rubric": reasoning_rubric_payload(),
    }
    return {
        **base_payload,
        "business_profile_summary": _compose_business_profile_summary(metrics, business_profile),
        "spatial_structure_summary": _compose_spatial_structure_summary(metrics, spatial_structure),
        "population_vitality_summary": _compose_population_vitality_summary(metrics),
        "evidence_highlights": _build_evidence_highlights(metrics, key_evidence),
    }


def _compose_direct_answer(question: str, payload: Dict[str, Any]) -> str:
    del question, payload
    return ""


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
    missing_evidence = [str(item).strip() for item in (payload.get("missing_evidence") or []) if str(item).strip()]
    required_labels = [str(item).strip() for item in _required_evidence_labels(question, audit) if str(item).strip()]
    missing = missing_evidence or required_labels
    if missing:
        return "AI 转译暂不可用；当前缺少关键证据：" + "、".join(missing[:3]) + "。"
    return "AI 转译暂不可用；当前仅返回原始证据，未生成策划解释。"


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
