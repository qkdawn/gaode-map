from __future__ import annotations

from typing import List

from .schemas import (
    DeckBriefRequest,
    DeckBriefResponse,
    DeckSlideBrief,
    PptSpecRequest,
    PptSpecResponse,
)


DEFAULT_OUTLINE = [
    "项目命题与汇报目标",
    "区位价值与城市关系",
    "现状诊断与核心矛盾",
    "更新目标与总体策略",
    "空间结构、功能组合与实施路径",
]


def _source_summary(source_ids: List[str], research_enabled: bool) -> str:
    selected_count = len([item for item in source_ids if item])
    research_note = "包含联网研究" if research_enabled else "不包含联网研究"
    if selected_count <= 0:
        return f"暂未选择来源，{research_note}"
    return f"已选择 {selected_count} 个来源，{research_note}"


def generate_ppt_spec(request: PptSpecRequest) -> PptSpecResponse:
    topic = request.topic.strip() or "待输入主题"
    missing_inputs = []
    if not request.topic.strip():
        missing_inputs.append("topic")
    if not request.source_ids:
        missing_inputs.append("source_ids")

    return PptSpecResponse(
        title=f"{topic} - PPT Spec",
        goal="形成面向评审的专业策划汇报结构，先沉淀可编辑 spec，再生成逐页 page brief。",
        audience=request.audience,
        deck_type=request.deck_type,
        page_count=request.page_count,
        outline=DEFAULT_OUTLINE,
        source_summary=_source_summary(request.source_ids, request.research_enabled),
        missing_inputs=missing_inputs,
    )


def generate_deck_brief(request: DeckBriefRequest) -> DeckBriefResponse:
    page_count = request.spec.page_count if request.spec else request.page_count
    source_ids = request.source_ids or ["summary", "scope", "evidence"]
    base_slides = [
        ("封面", "建立项目命题", "明确本次汇报要回答的问题", "项目名、区域底图、关键判断"),
        ("区位判断", "解释区域价值", "从城市关系、交通和资源识别机会", "区位图、圈层关系、交通节点"),
        ("现状诊断", "识别核心矛盾", "用数据证据归纳空间和功能问题", "指标图、热力图、问题清单"),
        ("更新策略", "提出方向", "把诊断转化为功能、空间和运营策略", "策略分区、功能组合、空间结构"),
        ("实施路径", "支撑落地", "用分期和行动清单连接近期实施", "时间轴、责任矩阵、近期行动"),
    ]
    slides = []
    for index, item in enumerate(base_slides[: min(page_count, len(base_slides))], start=1):
        title, purpose, key_message, visual_plan = item
        slides.append(
            DeckSlideBrief(
                index=index,
                title=title,
                purpose=purpose,
                key_message=key_message,
                visual_plan=visual_plan,
                required_sources=source_ids[:3],
                speaker_notes="第一阶段生成 page brief，不直接生成 PPTX。",
            )
        )
    return DeckBriefResponse(
        status="draft",
        slides=slides,
        source_summary=_source_summary(source_ids, request.research_enabled),
        missing_inputs=[] if request.topic or request.spec else ["topic"],
    )
