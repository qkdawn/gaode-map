from __future__ import annotations

from typing import Any, Dict, List

from modules.providers.amap.utils.get_type_info import infer_type_info_from_text

from .analysis_extractors import (
    build_h3_structure_analysis,
    build_nightlight_pattern_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
    is_h3_structure_ready,
    is_nightlight_pattern_ready,
    is_population_profile_ready,
    is_road_pattern_ready,
)
from .gate import classify_question_type
from .plan_steps import nightlight_step, population_step, results_step, road_step, scope_step
from .schemas import AnalysisSnapshot, PlanStep, PlanningResult, WorkingMemory


def _append_step(steps: List[PlanStep], step: PlanStep) -> None:
    key = (step.tool_name, tuple(sorted((step.arguments or {}).items())))
    existing = {
        (item.tool_name, tuple(sorted((item.arguments or {}).items())))
        for item in steps
    }
    if key not in existing:
        steps.append(step)


def _current_summary(snapshot: AnalysisSnapshot, memory: WorkingMemory, key: str) -> Dict[str, Any]:
    artifact_key = f"current_{key}_summary"
    if isinstance(memory.artifacts.get(artifact_key), dict):
        return dict(memory.artifacts.get(artifact_key) or {})
    source = getattr(snapshot, key, {})
    if isinstance(source, dict) and isinstance(source.get("summary"), dict):
        return dict(source.get("summary") or {})
    return {}


def _current_poi_h3_summary(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> Dict[str, Any]:
    artifact = memory.artifacts.get("current_poi_h3_summary")
    if isinstance(artifact, dict):
        return dict(artifact or {})
    source = snapshot.h3 if isinstance(snapshot.h3, dict) else {}
    if isinstance(source.get("summary"), dict):
        return dict(source.get("summary") or {})
    return {}


def _has_scope(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> bool:
    if memory.artifacts.get("scope_polygon"):
        return True
    scope = snapshot.scope if isinstance(snapshot.scope, dict) else {}
    return bool(scope.get("polygon") or scope.get("drawn_polygon") or scope.get("isochrone_feature"))


def _has_pois(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> bool:
    return bool(
        memory.artifacts.get("current_pois")
        or snapshot.pois
        or (memory.artifacts.get("current_poi_summary") or {}).get("total")
        or (snapshot.poi_summary or {}).get("total")
    )


def _has_target_poi_evidence(snapshot: AnalysisSnapshot, memory: WorkingMemory, question: str) -> bool:
    target = infer_type_info_from_text(question)
    if not target:
        return _has_pois(snapshot, memory)
    summary = memory.artifacts.get("current_poi_summary") if isinstance(memory.artifacts.get("current_poi_summary"), dict) else snapshot.poi_summary
    if not _has_pois(snapshot, memory) or not isinstance(summary, dict):
        return False
    summary_types = set(part for part in str(summary.get("types") or "").split("|") if part)
    target_types = set(part for part in str(target.get("types") or "").split("|") if part)
    if summary_types and target_types and summary_types.intersection(target_types):
        return True
    summary_keywords = str(summary.get("keywords") or "")
    target_keywords = str(target.get("keywords") or "")
    target_label = str(target.get("label") or "")
    return bool(summary_keywords and (summary_keywords == target_keywords or target_label in summary_keywords))


def _needs_business_summary_dimensions(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> List[str]:
    missing: List[str] = []
    if not _has_pois(snapshot, memory):
        missing.append("poi")
    if not _current_poi_h3_summary(snapshot, memory):
        missing.append("h3")
    if not _current_summary(snapshot, memory, "population"):
        missing.append("population")
    if not _current_summary(snapshot, memory, "nightlight"):
        missing.append("nightlight")
    if not _current_summary(snapshot, memory, "road"):
        missing.append("road")
    return missing


def _h3_structure_ready(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> bool:
    payload = (
        dict(memory.artifacts.get("current_h3_structure_analysis"))
        if isinstance(memory.artifacts.get("current_h3_structure_analysis"), dict)
        else build_h3_structure_analysis(snapshot, memory.artifacts)
    )
    return is_h3_structure_ready(payload)


def _population_profile_ready(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> bool:
    payload = (
        dict(memory.artifacts.get("current_population_profile_analysis"))
        if isinstance(memory.artifacts.get("current_population_profile_analysis"), dict)
        else build_population_profile_analysis(snapshot, memory.artifacts)
    )
    return is_population_profile_ready(payload)


def _nightlight_pattern_ready(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> bool:
    payload = (
        dict(memory.artifacts.get("current_nightlight_pattern_analysis"))
        if isinstance(memory.artifacts.get("current_nightlight_pattern_analysis"), dict)
        else build_nightlight_pattern_analysis(snapshot, memory.artifacts)
    )
    return is_nightlight_pattern_ready(payload)


def _road_pattern_ready(snapshot: AnalysisSnapshot, memory: WorkingMemory) -> bool:
    payload = (
        dict(memory.artifacts.get("current_road_pattern_analysis"))
        if isinstance(memory.artifacts.get("current_road_pattern_analysis"), dict)
        else build_road_pattern_analysis(snapshot, memory.artifacts)
    )
    return is_road_pattern_ready(payload)


def _analysis_step(tool_name: str, reason: str, evidence_goal: str, expected_artifacts: List[str], *, arguments: Dict[str, Any] | None = None) -> PlanStep:
    return PlanStep(
        tool_name=tool_name,
        arguments=arguments or {},
        reason=reason,
        evidence_goal=evidence_goal,
        expected_artifacts=expected_artifacts,
    )


def _is_hotspot_question(question: str) -> bool:
    tokens = ("核心", "热点", "集中", "分布", "偏空", "空白", "多核", "单核")
    return any(token in question for token in tokens)


def _mentions_uploaded_attachment(question: str) -> bool:
    tokens = ("附件", "文件", "图片", "图纸", "上传", "这份", "这个表", "表格", "报告", "PDF", "pdf", "文档")
    return any(token in str(question or "") for token in tokens)


def build_planning_fallback(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    memory: WorkingMemory,
    audit_feedback: Dict[str, Any] | None = None,
) -> PlanningResult:
    question_type = classify_question_type(question)
    feedback = dict(audit_feedback or {})
    steps: List[PlanStep] = []

    if _has_scope(snapshot, memory):
        _append_step(steps, scope_step())
    _append_step(steps, results_step("先读取当前已有结果，避免重复计算。"))
    if _mentions_uploaded_attachment(question) and memory.artifacts.get("uploaded_attachment_ids"):
        _append_step(
            steps,
            _analysis_step(
                "search_uploaded_attachment_context",
                "用户问题涉及上传附件，先检索附件证据。",
                "上传附件相关证据",
                ["uploaded_attachment_hits"],
                arguments={"query": question, "top_k": 5},
            ),
        )

    summary = "优先复用现有结果，再按缺失证据补齐关键分析维度。"
    evidence_focus: List[str] = []

    missing_evidence = [str(item) for item in (feedback.get("missing_evidence") or []) if str(item).strip()]

    if question_type == "next_analysis":
        summary = "这是下一步分析建议题，先复用当前结果，再基于证据就绪状态推荐最值得继续的应用分析方向。"
        evidence_focus = ["当前结果就绪状态", "下一步分析方向", "可应用场景"]
        _append_step(
            steps,
            _analysis_step(
                "rank_next_analysis_options",
                "基于当前证据链完整度，排序下一步分析方向。",
                "下一步分析方向",
                ["current_next_analysis_options"],
            ),
        )
    elif question_type == "area_character":
        summary = "这是区域画像/调性判断题，默认优先走场景工具包，统一串联商业供给、空间分布、人口、夜间活力和路网证据。"
        evidence_focus = ["POI 业态结构", "POI H3 空间分布", "人口基础", "夜间活力", "路网可达性"]
        _append_step(
            steps,
            PlanStep(
                tool_name="run_area_character_pack",
                arguments={"policy_key": "district_summary", "analysis_mode": "district_summary"},
                reason="优先调用区域调性场景工具包，统一输出标签、主导功能和证据链。",
                evidence_goal="区域调性与证据链",
                expected_artifacts=["area_character_pack", "current_area_character_labels"],
            ),
        )
    elif question_type == "site_selection":
        target = infer_type_info_from_text(question)
        evidence_focus = ["目标业态供给", "候选区排序", "供给缺口判断", "可达性与活力"]
        summary = "这是建店选址/补位题，默认优先走场景工具包，统一输出候选点排名、优劣势和证据链。"
        _append_step(
            steps,
            PlanStep(
                tool_name="run_site_selection_pack",
                arguments={"place_type": str((target or {}).get("label") or "") if target else "", "policy_key": "business_catchment_1km"},
                reason="优先调用选址场景工具包，统一完成目标解析、候选区筛选和排序。",
                evidence_goal="候选点排序与证据链",
                expected_artifacts=["site_selection_pack", "current_site_candidate_scores", "current_target_supply_gap"],
            ),
        )
    elif question_type == "population":
        evidence_focus = ["人口画像"]
        if not _current_summary(snapshot, memory, "population") and not _population_profile_ready(snapshot, memory):
            _append_step(
                steps,
                population_step("补齐人口概览，回答区域人口基础问题。").model_copy(update={"evidence_goal": "人口概览"})
            )
        if _population_profile_ready(snapshot, memory):
            _append_step(
                steps,
                _analysis_step(
                    "read_population_profile_analysis",
                    "读取人口画像结果，直接回答人口结构问题。",
                    "人口画像",
                    ["current_population_profile_analysis"],
                ),
            )
    elif question_type in {"nightlight", "vitality"}:
        evidence_focus = ["夜光结构"]
        if not _current_summary(snapshot, memory, "nightlight") and not _nightlight_pattern_ready(snapshot, memory):
            _append_step(
                steps,
                nightlight_step("补齐夜光概览，回答区域夜间活力问题。").model_copy(update={"evidence_goal": "夜光概览"})
            )
        if _nightlight_pattern_ready(snapshot, memory):
            _append_step(
                steps,
                _analysis_step(
                    "read_nightlight_pattern_analysis",
                    "读取夜光结构结果，直接回答夜间活力问题。",
                    "夜光结构",
                    ["current_nightlight_pattern_analysis"],
                ),
            )
    elif question_type == "road":
        evidence_focus = ["路网结构"]
        if not _current_summary(snapshot, memory, "road") and not _road_pattern_ready(snapshot, memory):
            _append_step(
                steps,
                road_step("补跑路网句法分析，回答可达性与路网结构问题。").model_copy(update={"evidence_goal": "路网概览"})
            )
        if _road_pattern_ready(snapshot, memory):
            _append_step(
                steps,
                _analysis_step(
                    "read_road_pattern_analysis",
                    "读取路网结构模式结果，直接回答可达性问题。",
                    "路网结构",
                    ["current_road_pattern_analysis"],
                ),
            )
    else:
        evidence_focus = ["当前已有结果"]
        if _is_hotspot_question(question):
            summary = "这是空间结构/热点题，优先补齐 POI H3 密度底座并识别商业核心与机会区。"
            evidence_focus = ["POI H3 空间结构", "商业热点区"]
            if not _current_poi_h3_summary(snapshot, memory):
                _append_step(
                    steps,
                    PlanStep(
                        tool_name="compute_h3_metrics_from_scope_and_pois",
                        reason="缺少 POI H3 密度底座，先补齐网格密度结果。",
                        evidence_goal="POI H3 密度",
                        expected_artifacts=["current_poi_h3", "current_poi_h3_summary", "current_poi_h3_grid", "current_poi_h3_charts"],
                    ),
                )
            _append_step(
                steps,
                _analysis_step(
                    "read_h3_structure_analysis",
                    "读取 POI H3 结构结果。",
                    "POI H3 空间结构",
                    ["current_h3_structure_analysis"],
                ),
            )
            _append_step(
                steps,
                _analysis_step(
                    "detect_commercial_hotspots",
                    "识别核心区、次核心区和机会区。",
                    "商业热点区",
                    ["current_commercial_hotspots"],
                ),
            )

    return PlanningResult(
        goal=question,
        question_type=question_type,
        summary=summary,
        requires_tools=bool(steps),
        stop_condition="关键证据足以回答用户问题，且审计通过。",
        evidence_focus=evidence_focus,
        steps=steps,
    )
