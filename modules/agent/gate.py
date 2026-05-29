from __future__ import annotations

from typing import List

from modules.providers.amap.utils.get_type_info import infer_type_info_from_text

from .intent_signals import (
    mentions_next_analysis,
    mentions_nightlight,
    mentions_population,
    mentions_road,
    mentions_summary,
    mentions_supply,
)
from .schemas import AgentMessage, AnalysisSnapshot, GateDecision
from .tool_adapters.scope_tools import extract_scope_polygon


NEXT_STEP_TOKENS = ("下一步", "继续", "还可以", "做什么分析", "还能分析")
METRIC_TOKENS = ("poi", "POI", "h3", "H3", "网格", "热力", "密度", "供给", "缺口")
BUSINESS_ACTION_TOKENS = ("开店", "开一家", "选址", "补位", "补充", "适合开", "适合做")
BUSINESS_TARGET_TOKENS = ("餐饮", "零售", "咖啡", "购物", "便利店", "超市", "商场", "药店", "酒店", "餐厅")
HOTSPOT_STRUCTURE_TOKENS = ("核心", "热点", "集中", "分布", "偏空", "空白", "多核", "单核")
VAGUE_ANALYSIS_TOKENS = (
    "分析一下",
    "看一下",
    "看下",
    "看看",
    "这个怎么样",
    "这里怎么样",
    "评估一下",
    "判断一下",
)
AMBIGUOUS_DECISION_TOKENS = ("哪个好", "哪一个好", "哪个更好", "怎么优化", "如何优化", "优化一下")
DECISION_CONTEXT_TOKENS = (
    "对比",
    "比较",
    "相比",
    "方案",
    "商业",
    "业态",
    "人口",
    "路网",
    "夜光",
    "活力",
    "可达性",
    "餐饮",
    "零售",
    "咖啡",
    "H3",
    "h3",
    "POI",
    "poi",
)


def latest_user_message(messages: List[AgentMessage]) -> str:
    for message in reversed(messages or []):
        if str(message.role or "") == "user" and str(message.content or "").strip():
            return str(message.content or "").strip()
    return ""


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _has_business_target(text: str) -> bool:
    return bool(infer_type_info_from_text(text)) or _has_any(text, BUSINESS_TARGET_TOKENS)


def _mentions_metric_or_dimension(text: str) -> bool:
    return (
        mentions_population(text)
        or mentions_nightlight(text)
        or mentions_road(text)
        or _has_any(text, HOTSPOT_STRUCTURE_TOKENS)
        or _has_any(text, METRIC_TOKENS)
    )


def _is_actionable_question(text: str) -> bool:
    if mentions_summary(text) or _has_any(text, NEXT_STEP_TOKENS):
        return True
    if _mentions_metric_or_dimension(text):
        return True
    if (mentions_supply(text) or _has_any(text, BUSINESS_ACTION_TOKENS)) and _has_business_target(text):
        return True
    return False


def classify_question_type(text: str) -> str:
    normalized = str(text or "").strip()
    if mentions_next_analysis(normalized):
        return "next_analysis"
    if any(token in normalized for token in ("TOD", "tod", "站城", "轨交站", "地铁站")):
        return "tod"
    if any(token in normalized for token in ("宜居", "适宜居住", "居住适宜性")):
        return "livability"
    if any(token in normalized for token in ("更新优先级", "更新排序", "更新先后")):
        return "renewal_priority"
    if any(token in normalized for token in ("公服缺口", "服务缺口", "配置缺口")):
        return "facility_gap"
    if mentions_supply(text) or _has_any(text, BUSINESS_ACTION_TOKENS):
        return "site_selection"
    if mentions_population(text):
        return "population"
    if mentions_nightlight(text):
        return "vitality" if "活力" in normalized else "nightlight"
    if mentions_road(text):
        return "road"
    if mentions_summary(text):
        return "area_character"
    if _has_any(text, METRIC_TOKENS):
        return "metric"
    return "general"


def _needs_clarification_for_ambiguous_intent(text: str) -> str:
    if _has_any(text, BUSINESS_ACTION_TOKENS) and not _has_business_target(text):
        return "你想评估哪类业态？请补充目标业态，例如咖啡、餐饮、零售或便利店。"
    if _has_any(text, AMBIGUOUS_DECISION_TOKENS) and not _has_any(text, DECISION_CONTEXT_TOKENS):
        return "请补充要比较或优化的对象和目标，例如比较哪两个区域/方案，或要优化商业、人口、路网还是夜间活力。"
    if _has_any(text, VAGUE_ANALYSIS_TOKENS):
        return "你想重点分析哪个方向？可以选择商业/业态补位、人口、夜光活力、路网可达性或 POI H3 空间结构。"
    return ""


def _clarification_options(text: str, snapshot: AnalysisSnapshot) -> List[str]:
    if not text:
        return [
            "总结这个区域的商业特征",
            "哪里适合补充餐饮",
            "为什么这里路网差",
            "下一步做什么分析",
        ]
    if not extract_scope_polygon(snapshot):
        return [
            "我先画一个范围再继续",
            "基于当前等时圈总结这个区域",
            "帮我看看这里适合补充什么业态",
        ]
    if _has_any(text, BUSINESS_ACTION_TOKENS) and not _has_business_target(text):
        return [
            "哪里适合补充咖啡",
            "哪里适合补充餐饮",
            "哪里适合补充便利店",
            "哪里适合补充零售",
        ]
    if _has_any(text, AMBIGUOUS_DECISION_TOKENS) and not _has_any(text, DECISION_CONTEXT_TOKENS):
        return [
            "对比这两个区域的商业特征",
            "优化这个区域的商业补位方向",
            "比较人口、路网和夜间活力哪个更弱",
        ]
    if _has_any(text, VAGUE_ANALYSIS_TOKENS):
        return [
            "总结这个区域的商业特征",
            "哪里适合补充餐饮",
            "为什么这里夜间活力强",
            "为什么这里路网差",
        ]
    return []


def run_gate(messages: List[AgentMessage], snapshot: AnalysisSnapshot) -> GateDecision:
    latest = latest_user_message(messages)
    if not latest:
        return GateDecision(
            status="clarify",
            question_type="general",
            summary="用户尚未给出明确问题。",
            missing_information=["问题目标"],
            clarification_questions=["请先说清楚你想解决的问题，例如“总结这个区域”或“哪里适合补充餐饮”。"],
            clarification_question="请先说清楚你想解决的问题，例如“总结这个区域”或“哪里适合补充餐饮”。",
            clarification_options=_clarification_options(latest, snapshot),
        )
    if not extract_scope_polygon(snapshot):
        return GateDecision(
            status="clarify",
            question_type=classify_question_type(latest),
            summary="当前缺少分析范围，暂时不能进入执行。",
            missing_information=["分析范围"],
            clarification_questions=["当前 analysis snapshot 里没有可用分析范围，请先提供 scope / isochrone / polygon。"],
            clarification_question="当前 analysis snapshot 里没有可用分析范围，请先提供 scope / isochrone / polygon。",
            clarification_options=_clarification_options(latest, snapshot),
        )
    if not _is_actionable_question(latest):
        clarification_question = _needs_clarification_for_ambiguous_intent(latest)
        if clarification_question:
            return GateDecision(
                status="clarify",
                question_type=classify_question_type(latest),
                summary="用户问题还不够明确，建议先补齐关键意图。",
                clarification_questions=[clarification_question],
                clarification_question=clarification_question,
                clarification_options=_clarification_options(latest, snapshot),
            )
    return GateDecision(
        status="pass",
        question_type=classify_question_type(latest),
        summary="问题与范围满足进入规划阶段的最低条件。",
    )
