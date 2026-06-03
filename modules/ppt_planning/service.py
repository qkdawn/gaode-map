from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List

from modules.agent.providers.llm_provider import _invoke_json_role, is_llm_enabled

from .prompts import DECK_BRIEF_SYSTEM_PROMPT, PPT_SOURCE_GROUP_SYSTEM_PROMPT, PPT_SPEC_SYSTEM_PROMPT
from .schemas import (
    DeckBriefRequest,
    DeckBriefResponse,
    DeckSlideBrief,
    PptOutlineItem,
    PptSource,
    PptSourceGroup,
    PptSourceGroupClassifyRequest,
    PptSourceGroupClassifyResponse,
    PptSpecRequest,
    PptSpecResponse,
)


class PptPlanningLlmUnavailable(RuntimeError):
    pass


class PptPlanningInvalidResponse(RuntimeError):
    pass


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_group_id(title: str, source_ids: List[str], index: int) -> str:
    raw = _clean_text(title).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if slug:
        return f"group:{slug[:40]}"
    digest = hashlib.sha256(
        json.dumps({"title": title, "source_ids": source_ids, "index": index}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:8]
    return f"group:auto-{digest}"


def _compact_source_for_grouping(source: PptSource) -> Dict[str, Any]:
    meta = source.meta if isinstance(source.meta, dict) else {}
    package = meta.get("package") if isinstance(meta.get("package"), dict) else {}
    return {
        "id": source.id,
        "type": source.type,
        "title": source.title,
        "status": source.status,
        "label": _clean_text(meta.get("label")),
        "source_kind": _clean_text(meta.get("sourceKind")),
        "task_key": _clean_text(meta.get("taskKey")),
        "package_summary": _clean_text(package.get("summary"))[:300],
        "package_mode": _clean_text(package.get("package_mode")),
    }


def _normalize_source_groups(raw_groups: Any, sources: List[PptSource]) -> List[PptSourceGroup]:
    source_ids = [_clean_text(item.id) for item in sources if _clean_text(item.id)]
    allowed_ids = set(source_ids)
    seen_source_ids: set[str] = set()
    normalized: List[PptSourceGroup] = []
    groups = raw_groups if isinstance(raw_groups, list) else []

    for index, raw_group in enumerate(groups, start=1):
        if not isinstance(raw_group, dict):
            continue
        group_source_ids: List[str] = []
        for raw_source_id in raw_group.get("source_ids") or raw_group.get("sourceIds") or []:
            source_id = _clean_text(raw_source_id)
            if source_id and source_id in allowed_ids and source_id not in seen_source_ids:
                group_source_ids.append(source_id)
                seen_source_ids.add(source_id)
        if not group_source_ids:
            continue
        title = _clean_text(raw_group.get("title")) or "来源分组"
        group_id = _clean_text(raw_group.get("id")) or _stable_group_id(title, group_source_ids, index)
        if not group_id.startswith("group:"):
            group_id = f"group:{group_id}"
        normalized.append(
            PptSourceGroup(
                id=group_id,
                title=title,
                emoji=_clean_text(raw_group.get("emoji")),
                source_ids=group_source_ids,
                collapsed=bool(raw_group.get("collapsed")),
                meta=raw_group.get("meta") if isinstance(raw_group.get("meta"), dict) else {},
            )
        )

    missing_source_ids = [source_id for source_id in source_ids if source_id not in seen_source_ids]
    if missing_source_ids:
        normalized.append(
            PptSourceGroup(
                id="group:uncategorized",
                title="未分类来源",
                emoji="",
                source_ids=missing_source_ids,
                collapsed=False,
                meta={"reason": "模型未归类或来源刚刚加入。"},
            )
        )
    return normalized


def _source_summary(source_ids: List[str], research_enabled: bool) -> str:
    selected_count = len([item for item in source_ids if item])
    research_note = "包含联网研究" if research_enabled else "不包含联网研究"
    if selected_count <= 0:
        return f"暂未选择来源，{research_note}"
    return f"已选择 {selected_count} 个来源，{research_note}"


def _selected_sources_payload(request: PptSpecRequest | DeckBriefRequest) -> List[Dict[str, Any]]:
    source_ids = set(request.source_ids or [])
    sources = getattr(request, "sources", []) or []
    return [
        item.model_dump(mode="json")
        for item in sources
        if item.id in source_ids
    ]


def _missing_inputs_for_spec(request: PptSpecRequest) -> List[str]:
    missing_inputs: List[str] = []
    if not request.topic.strip():
        missing_inputs.append("topic")
    if not request.source_ids:
        missing_inputs.append("source_ids")
    return missing_inputs


def _validate_outline(raw_outline: Any, page_count: int) -> List[PptOutlineItem]:
    if not isinstance(raw_outline, list):
        return []
    outline: List[PptOutlineItem] = []
    for index, item in enumerate(raw_outline[:page_count], start=1):
        if not isinstance(item, dict):
            continue
        theme = _clean_text(item.get("theme") or item.get("title"))
        if not theme:
            continue
        page_no = int(item.get("page_no") or item.get("pageNo") or index)
        outline.append(
            PptOutlineItem(
                id=_clean_text(item.get("id")) or f"outline-{page_no}",
                page_no=page_no,
                theme=theme,
                purpose=_clean_text(item.get("purpose")),
            )
        )
    return outline


def _validate_slides(raw_slides: Any, page_count: int) -> List[DeckSlideBrief]:
    if not isinstance(raw_slides, list):
        return []
    slides: List[DeckSlideBrief] = []
    for index, item in enumerate(raw_slides[:page_count], start=1):
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        if not title:
            continue
        required_sources = item.get("required_sources") or item.get("requiredSources") or []
        if not isinstance(required_sources, list):
            required_sources = []
        slides.append(
            DeckSlideBrief(
                index=int(item.get("index") or index),
                title=title,
                purpose=_clean_text(item.get("purpose")),
                key_message=_clean_text(item.get("key_message") or item.get("keyMessage")),
                visual_plan=_clean_text(item.get("visual_plan") or item.get("visualPlan")),
                required_sources=[_clean_text(source) for source in required_sources if _clean_text(source)],
                speaker_notes=_clean_text(item.get("speaker_notes") or item.get("speakerNotes")),
            )
        )
    return slides


def _ensure_llm_enabled() -> None:
    if not is_llm_enabled():
        raise PptPlanningLlmUnavailable("llm_unavailable")


async def classify_ppt_source_groups(request: PptSourceGroupClassifyRequest) -> PptSourceGroupClassifyResponse:
    sources = [source for source in request.sources if _clean_text(source.id)]
    if not sources:
        return PptSourceGroupClassifyResponse(groups=[])
    _ensure_llm_enabled()
    raw = await _invoke_json_role(
        system_prompt=PPT_SOURCE_GROUP_SYSTEM_PROMPT,
        user_payload={
            "task": "ppt_source_group_classification",
            "area_id": request.area_id,
            "sources": [_compact_source_for_grouping(source) for source in sources],
            "analysis_context": request.analysis_context,
            "previous_groups": [group.model_dump(mode="json") for group in request.previous_groups],
        },
        emit=None,
        phase="ppt_source_group_classification",
        title="重新为来源加标签",
        reasoning_id="ppt-source-group-classification",
    )
    return PptSourceGroupClassifyResponse(groups=_normalize_source_groups(raw.get("groups"), sources))


async def generate_ppt_spec(request: PptSpecRequest) -> PptSpecResponse:
    _ensure_llm_enabled()
    user_payload = {
        "task": "ppt_outline_generation",
        "area_id": request.area_id,
        "topic": request.topic,
        "audience": request.audience,
        "deck_type": request.deck_type,
        "page_count": request.page_count,
        "research_enabled": request.research_enabled,
        "source_ids": request.source_ids,
        "sources": _selected_sources_payload(request),
        "source_summary": _source_summary(request.source_ids, request.research_enabled),
        "analysis_context": request.analysis_context,
        "missing_inputs_from_request": _missing_inputs_for_spec(request),
    }
    raw = await _invoke_json_role(
        system_prompt=PPT_SPEC_SYSTEM_PROMPT,
        user_payload=user_payload,
        emit=None,
        phase="ppt_outline_generation",
        title="生成 PPT 目录",
        reasoning_id="ppt-outline-generation",
    )
    outline = _validate_outline(raw.get("outline"), request.page_count)
    if not outline:
        raise PptPlanningInvalidResponse("invalid_ppt_outline")
    missing_inputs = raw.get("missing_inputs")
    if not isinstance(missing_inputs, list):
        missing_inputs = _missing_inputs_for_spec(request)
    return PptSpecResponse(
        title=_clean_text(raw.get("title")) or request.topic or "PPT 目录",
        goal=_clean_text(raw.get("goal")) or "形成可继续生成逐页指令的汇报目录。",
        audience=_clean_text(raw.get("audience")) or request.audience,
        deck_type=_clean_text(raw.get("deck_type")) or request.deck_type,
        page_count=int(raw.get("page_count") or request.page_count),
        outline=outline,
        source_summary=_clean_text(raw.get("source_summary")) or _source_summary(request.source_ids, request.research_enabled),
        missing_inputs=[_clean_text(item) for item in missing_inputs if _clean_text(item)],
    )


async def generate_deck_brief(request: DeckBriefRequest) -> DeckBriefResponse:
    _ensure_llm_enabled()
    page_count = request.spec.page_count if request.spec else request.page_count
    user_payload = {
        "task": "ppt_directive_generation",
        "area_id": request.area_id,
        "topic": request.topic,
        "audience": request.audience,
        "deck_type": request.deck_type,
        "page_count": page_count,
        "research_enabled": request.research_enabled,
        "source_ids": request.source_ids,
        "sources": _selected_sources_payload(request),
        "source_summary": _source_summary(request.source_ids, request.research_enabled),
        "analysis_context": request.analysis_context,
        "spec": request.spec.model_dump(mode="json") if request.spec else None,
    }
    raw = await _invoke_json_role(
        system_prompt=DECK_BRIEF_SYSTEM_PROMPT,
        user_payload=user_payload,
        emit=None,
        phase="ppt_directive_generation",
        title="生成 PPT 逐页指令",
        reasoning_id="ppt-directive-generation",
    )
    slides = _validate_slides(raw.get("slides"), page_count)
    if not slides:
        raise PptPlanningInvalidResponse("invalid_deck_brief")
    missing_inputs = raw.get("missing_inputs")
    if not isinstance(missing_inputs, list):
        missing_inputs = [] if request.topic or request.spec else ["topic"]
    return DeckBriefResponse(
        status="draft",
        slides=slides,
        source_summary=_clean_text(raw.get("source_summary")) or _source_summary(request.source_ids, request.research_enabled),
        missing_inputs=[_clean_text(item) for item in missing_inputs if _clean_text(item)],
    )
