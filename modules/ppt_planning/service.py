from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List

from modules.agent.providers.llm_provider import _invoke_json_role, is_llm_enabled

from .prompts import (
    DECK_BRIEF_SLIDE_SYSTEM_PROMPT,
    DECK_BRIEF_SYSTEM_PROMPT,
    PPT_OUTLINE_SECTION_SYSTEM_PROMPT,
    PPT_SOURCE_GROUP_SYSTEM_PROMPT,
    PPT_SPEC_SYSTEM_PROMPT,
)
from .schemas import (
    DeckBriefSlideRequest,
    DeckBriefRequest,
    DeckBriefResponse,
    DeckSlideBrief,
    PptOutlineSectionRequest,
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


LLM_PACKAGE_ITEM_LIMIT = 8
LLM_PACKAGE_GROUP_LIMIT = 8
LLM_CARRIER_LIMIT = 12
LLM_CARRIER_REPRESENTATIVE_POI_LIMIT = 3
LLM_EVIDENCE_REF_LIMIT = 20
LLM_WARNING_LIMIT = 6


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _truncated_text(value: Any, limit: int = 180) -> str:
    text = _clean_text(value)
    return text[:limit]


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


def _copy_compact_keys(payload: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value
    return compact


def _compact_warning_list(items: Any, limit: int = LLM_WARNING_LIMIT) -> List[str]:
    return [_truncated_text(item, 220) for item in _safe_list(items)[:limit] if _clean_text(item)]


def _compact_evidence_refs(items: Any, limit: int = LLM_EVIDENCE_REF_LIMIT) -> List[str]:
    return [_truncated_text(item, 120) for item in _safe_list(items)[:limit] if _clean_text(item)]


def _compact_poi_item(item: Any) -> Dict[str, Any]:
    point = _safe_dict(item)
    compact = _copy_compact_keys(point, [
        "id",
        "name",
        "category",
        "subcategory",
        "typecode",
        "year",
        "source",
        "distance_m",
        "carrier_id",
        "carrier_type",
        "carrier_label",
        "cell_id",
        "alignment_status",
        "cell_match_distance_m",
    ])
    if point.get("address"):
        compact["address"] = _truncated_text(point.get("address"), 80)
    nightlight_cell = _safe_dict(point.get("nightlight_cell"))
    if nightlight_cell:
        compact["nightlight_cell"] = _copy_compact_keys(nightlight_cell, [
            "cell_id",
            "radiance",
            "class_key",
            "class_label",
            "has_data",
        ])
    return compact


def _compact_package_items(items: Any, limit: int = LLM_PACKAGE_ITEM_LIMIT) -> List[Dict[str, Any]]:
    return [_compact_poi_item(item) for item in _safe_list(items)[:limit]]


def _compact_road_context_for_llm(road_context: Any) -> Dict[str, Any]:
    context = _safe_dict(road_context)
    if not context:
        return {}
    compact = _copy_compact_keys(context, ["type", "source", "total", "included", "coverage"])
    features = _safe_list(context.get("features"))
    if features:
        compact["omitted_feature_count"] = len(features)
    return compact


def _compact_carrier_for_llm(carrier: Any) -> Dict[str, Any]:
    item = _safe_dict(carrier)
    compact = _copy_compact_keys(item, [
        "carrier_id",
        "carrier_type",
        "carrier_label",
        "summary",
        "road_metrics",
        "poi_metrics",
        "population_metrics",
        "nightlight_metrics",
    ])
    representatives = _compact_package_items(
        item.get("representative_pois"),
        limit=LLM_CARRIER_REPRESENTATIVE_POI_LIMIT,
    )
    if representatives:
        compact["representative_pois"] = representatives
        raw_representatives = _safe_list(item.get("representative_pois"))
        if len(raw_representatives) > len(representatives):
            compact["omitted_representative_poi_count"] = len(raw_representatives) - len(representatives)
    if item.get("evidence_refs"):
        compact["evidence_refs"] = _compact_evidence_refs(item.get("evidence_refs"), limit=4)
    if item.get("geometry"):
        compact["geometry_omitted"] = True
    return compact


def _compact_group_for_llm(group: Any) -> Dict[str, Any]:
    item = _safe_dict(group)
    compact = _copy_compact_keys(item, [
        "name",
        "purpose",
        "filters",
        "target_count",
        "total",
        "unique_total",
        "category_summary",
        "subcategory_summary",
        "plan_repair",
    ])
    if item.get("queries"):
        compact["queries"] = _safe_list(item.get("queries"))[:LLM_PACKAGE_GROUP_LIMIT]
    compact_items = _compact_package_items(item.get("items"), limit=LLM_PACKAGE_ITEM_LIMIT)
    if compact_items:
        compact["items"] = compact_items
        raw_items = _safe_list(item.get("items"))
        if len(raw_items) > len(compact_items):
            compact["omitted_item_count"] = len(raw_items) - len(compact_items)
    if item.get("warnings"):
        compact["warnings"] = _compact_warning_list(item.get("warnings"))
    return compact


def _compact_package_for_llm(package: Any) -> Dict[str, Any]:
    payload = _safe_dict(package)
    compact = _copy_compact_keys(payload, [
        "id",
        "title",
        "summary",
        "coordinate_system",
        "package_mode",
        "intent",
        "source_ids",
        "filters",
        "total",
        "category_summary",
        "subcategory_summary",
        "carrier_summary",
        "alignment",
        "selection_reason",
    ])
    items = _compact_package_items(payload.get("items"), limit=LLM_PACKAGE_ITEM_LIMIT)
    if items:
        compact["items"] = items
        raw_items = _safe_list(payload.get("items"))
        if len(raw_items) > len(items):
            compact["omitted_item_count"] = len(raw_items) - len(items)

    carriers = _safe_list(payload.get("carriers"))
    if carriers:
        compact["carriers"] = [_compact_carrier_for_llm(item) for item in carriers[:LLM_CARRIER_LIMIT]]
        if len(carriers) > LLM_CARRIER_LIMIT:
            compact["omitted_carrier_count"] = len(carriers) - LLM_CARRIER_LIMIT

    road_context = _compact_road_context_for_llm(payload.get("road_context") or payload.get("roadContext"))
    if road_context:
        compact["road_context"] = road_context

    groups = _safe_list(payload.get("groups"))
    if groups:
        compact["groups"] = [_compact_group_for_llm(item) for item in groups[:LLM_PACKAGE_GROUP_LIMIT]]
        if len(groups) > LLM_PACKAGE_GROUP_LIMIT:
            compact["omitted_group_count"] = len(groups) - LLM_PACKAGE_GROUP_LIMIT

    if payload.get("intent_plan"):
        plan = _safe_dict(payload.get("intent_plan"))
        compact["intent_plan"] = _copy_compact_keys(plan, [
            "package_title",
            "selection_reason",
            "query_terms",
            "categories",
            "subcategories",
            "typecodes",
            "nearby_required",
            "radius_m",
        ])
        plan_groups = _safe_list(plan.get("evidence_groups"))
        if plan_groups:
            compact["intent_plan"]["evidence_groups"] = [
                _copy_compact_keys(_safe_dict(item), [
                    "name",
                    "purpose",
                    "query_terms",
                    "categories",
                    "subcategories",
                    "typecodes",
                    "nearby_required",
                    "radius_m",
                    "target_count",
                ])
                for item in plan_groups[:LLM_PACKAGE_GROUP_LIMIT]
            ]

    if payload.get("evidence_refs"):
        compact["evidence_refs"] = _compact_evidence_refs(payload.get("evidence_refs"))
    if payload.get("warnings"):
        compact["warnings"] = _compact_warning_list(payload.get("warnings"))
    compact["detail_policy"] = (
        "LLM 输入仅保留资料包摘要、指标和少量代表性 POI；"
        "完整 road_context.features、carrier.geometry 和 POI 明细只用于前端预览，不传给模型。"
    )
    return compact


def _compact_source_for_llm(source: PptSource) -> Dict[str, Any]:
    meta = _safe_dict(source.meta)
    compact_meta = _copy_compact_keys(meta, ["label", "sourceKind", "areaId", "taskKey"])
    package = _compact_package_for_llm(meta.get("package")) if isinstance(meta.get("package"), dict) else {}
    if package:
        compact_meta["package"] = package
    return {
        "id": source.id,
        "type": source.type,
        "title": source.title,
        "status": source.status,
        "selected": source.selected,
        "meta": compact_meta,
    }


def _selected_sources_payload(request: PptSpecRequest | DeckBriefRequest) -> List[Dict[str, Any]]:
    source_ids = set(request.source_ids or [])
    sources = getattr(request, "sources", []) or []
    return [
        _compact_source_for_llm(item)
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


def _validate_outline_section(raw: Any, fallback: PptOutlineItem) -> PptOutlineItem | None:
    item = _safe_dict(raw.get("item")) if isinstance(raw, dict) and isinstance(raw.get("item"), dict) else _safe_dict(raw)
    page_no = int(item.get("page_no") or item.get("pageNo") or fallback.page_no)
    outline = _validate_outline([{**fallback.model_dump(mode="json"), **item, "page_no": page_no}], page_no)
    if not outline:
        return None
    normalized = outline[0]
    return PptOutlineItem(
        id=normalized.id or fallback.id,
        page_no=fallback.page_no,
        theme=normalized.theme,
        purpose=normalized.purpose,
    )


def _validate_slide_section(raw: Any, fallback: DeckSlideBrief) -> DeckSlideBrief | None:
    item = _safe_dict(raw.get("slide")) if isinstance(raw, dict) and isinstance(raw.get("slide"), dict) else _safe_dict(raw)
    index = int(item.get("index") or fallback.index)
    slides = _validate_slides([{**fallback.model_dump(mode="json"), **item, "index": index}], index)
    if not slides:
        return None
    normalized = slides[0]
    return DeckSlideBrief(
        index=fallback.index,
        title=normalized.title,
        purpose=normalized.purpose,
        key_message=normalized.key_message,
        visual_plan=normalized.visual_plan,
        required_sources=normalized.required_sources,
        speaker_notes=normalized.speaker_notes,
    )


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


async def regenerate_ppt_outline_section(request: PptOutlineSectionRequest) -> PptOutlineItem:
    _ensure_llm_enabled()
    raw = await _invoke_json_role(
        system_prompt=PPT_OUTLINE_SECTION_SYSTEM_PROMPT,
        user_payload={
            "task": "ppt_outline_section_regeneration",
            "area_id": request.area_id,
            "revision_note": request.revision_note,
            "topic": request.topic or (request.spec.title if request.spec else ""),
            "audience": request.audience,
            "deck_type": request.deck_type,
            "page_count": request.spec.page_count if request.spec else request.page_count,
            "source_ids": request.source_ids,
            "sources": _selected_sources_payload(request),
            "source_summary": _source_summary(request.source_ids, request.research_enabled),
            "analysis_context": request.analysis_context,
            "spec": request.spec.model_dump(mode="json") if request.spec else None,
            "outline": [item.model_dump(mode="json") for item in request.outline],
            "target": request.target.model_dump(mode="json"),
        },
        emit=None,
        phase="ppt_outline_section_regeneration",
        title="重生成 PPT 目录小节",
        reasoning_id=f"ppt-outline-section-{request.target.page_no}",
    )
    section = _validate_outline_section(raw, request.target)
    if not section:
        raise PptPlanningInvalidResponse("invalid_ppt_outline_section")
    return section


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


async def regenerate_deck_brief_slide(request: DeckBriefSlideRequest) -> DeckSlideBrief:
    _ensure_llm_enabled()
    raw = await _invoke_json_role(
        system_prompt=DECK_BRIEF_SLIDE_SYSTEM_PROMPT,
        user_payload={
            "task": "ppt_directive_slide_regeneration",
            "area_id": request.area_id,
            "revision_note": request.revision_note,
            "topic": request.topic,
            "audience": request.audience,
            "deck_type": request.deck_type,
            "page_count": request.spec.page_count if request.spec else request.page_count,
            "source_ids": request.source_ids,
            "sources": _selected_sources_payload(request),
            "source_summary": _source_summary(request.source_ids, request.research_enabled),
            "analysis_context": request.analysis_context,
            "spec": request.spec.model_dump(mode="json") if request.spec else None,
            "outline": [item.model_dump(mode="json") for item in request.outline],
            "slides": [item.model_dump(mode="json") for item in request.slides],
            "outline_item": request.outline_item.model_dump(mode="json") if request.outline_item else None,
            "target": request.target.model_dump(mode="json"),
        },
        emit=None,
        phase="ppt_directive_slide_regeneration",
        title="重生成 PPT 指令页",
        reasoning_id=f"ppt-directive-slide-{request.target.index}",
    )
    slide = _validate_slide_section(raw, request.target)
    if not slide:
        raise PptPlanningInvalidResponse("invalid_deck_brief_slide")
    return slide
