from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from core.config import settings
from modules.agent.providers.llm_provider import _invoke_json_role, is_llm_enabled

from .prompts import (
    DECK_BRIEF_SLIDE_SYSTEM_PROMPT,
    DECK_BRIEF_SYSTEM_PROMPT,
    DECK_NARRATIVE_PLAN_SYSTEM_PROMPT,
    PPT_OUTLINE_SECTION_SYSTEM_PROMPT,
    PPT_SOURCE_GROUP_SYSTEM_PROMPT,
    PPT_SPEC_SYSTEM_PROMPT,
)
from .metric_context import (
    build_metric_context,
    compact_metric_context_for_llm,
    render_visual_artifacts,
    validate_visual_assets,
)
from .schemas import (
    DeckBriefSlideRequest,
    DeckBriefRequest,
    DeckBriefResponse,
    DeckNarrativePlanRequest,
    DeckNarrativePlanResponse,
    DeckNarrativeSlideRole,
    DeckSlideBrief,
    PptOutlineSectionRequest,
    PptOutlineItem,
    PptVisualArtifactRequest,
    PptVisualArtifactResponse,
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


logger = logging.getLogger(__name__)

LLM_PACKAGE_ITEM_LIMIT = 8
LLM_PACKAGE_GROUP_LIMIT = 8
LLM_CARRIER_LIMIT = 12
LLM_CARRIER_REPRESENTATIVE_POI_LIMIT = 3
LLM_EVIDENCE_REF_LIMIT = 20
LLM_WARNING_LIMIT = 6
LLM_CONTEXT_METRIC_LIMIT = 120
LLM_CONTEXT_EVIDENCE_LIMIT = 48
PPT_DEBUG_DIR = Path("runtime")


def _dump_generation_response(filename: str, payload: Dict[str, Any]) -> None:
    try:
        PPT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = PPT_DEBUG_DIR / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("PPT generation response dumped to %s", path.as_posix())
    except Exception:
        logger.debug("Failed to dump PPT generation response", exc_info=True)


async def _invoke_ppt_json_role(**kwargs: Any) -> Dict[str, Any]:
    return await _invoke_json_role(
        **kwargs,
        enable_thinking=False,
        stream=False,
        timeout_s=float(settings.ppt_llm_timeout_s),
    )


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
    document = meta.get("document") if isinstance(meta.get("document"), dict) else {}
    document_index_preview = _safe_list(meta.get("document_index_preview") or meta.get("documentIndexPreview"))[:8]
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
        "document": _copy_compact_keys(document, ["id", "title", "file_name", "file_type", "document_role", "status", "index_count"]),
        "document_index_preview": [
            _copy_compact_keys(_safe_dict(item), ["node_id", "parent_node_id", "title", "level", "summary", "page_start", "page_end"])
            for item in document_index_preview
        ],
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


def _visual_assets_from_request(request: DeckBriefRequest | DeckBriefSlideRequest) -> List[Dict[str, Any]]:
    current = _safe_dict(getattr(request, "current", {}))
    raw_assets = _safe_list(
        current.get("visual_assets")
        or current.get("visualAssets")
        or current.get("visual_snapshots")
        or current.get("visualSnapshots")
    )
    assets: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_assets, start=1):
        item = _safe_dict(raw)
        asset_id = _clean_text(item.get("asset_id") or item.get("assetId") or item.get("snapshot_id") or item.get("snapshotId")) or f"visual-asset-{index}"
        data_url = _clean_text(item.get("data_url") or item.get("dataUrl") or item.get("image_url") or item.get("imageUrl"))
        url = _clean_text(item.get("url"))
        assets.append({
            "asset_id": asset_id,
            "asset_kind": _clean_text(item.get("asset_kind") or item.get("assetKind") or item.get("kind")) or "map_snapshot",
            "source": _clean_text(item.get("source")) or _clean_text(item.get("kind")),
            "title": _clean_text(item.get("title")) or _clean_text(item.get("caption")) or f"可视化资产 {index}",
            "caption": _clean_text(item.get("caption") or item.get("title")),
            "url": url,
            "data_url": data_url,
            "captured_at": _clean_text(item.get("captured_at") or item.get("capturedAt")),
            "status": "ready" if (url or data_url) else "missing",
        })
    return assets


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
    ai_payload = _ai_payload_for_source(source)
    compact_meta = _copy_compact_keys(meta, ["label", "sourceKind", "areaId", "taskKey"])
    if ai_payload:
        counts = _safe_dict(ai_payload.get("counts"))
        compact_meta["aiPayload"] = {
            "version": ai_payload.get("version"),
            "included": _safe_list(ai_payload.get("included")),
            "counts": counts,
            "policy": _clean_text(ai_payload.get("policy")),
            "excluded": _safe_list(ai_payload.get("excluded")),
        }
    return {
        "id": source.id,
        "type": source.type,
        "title": source.title,
        "status": source.status,
        "selected": source.selected,
        "meta": compact_meta,
    }


def _metric_source_ids(metric: Dict[str, Any]) -> List[str]:
    source_ids = [_clean_text(item) for item in _safe_list(metric.get("source_ids") or metric.get("sourceIds")) if _clean_text(item)]
    source_id = _clean_text(metric.get("source_id") or metric.get("sourceId"))
    if source_id and source_id not in source_ids:
        source_ids.append(source_id)
    return source_ids


def _ai_payload_for_source(source: PptSource | None) -> Dict[str, Any]:
    if not source:
        return {}
    meta = _safe_dict(source.meta)
    payload = _safe_dict(meta.get("aiPayload") or meta.get("ai_payload"))
    if _clean_text(payload.get("version")) != "ppt_ai_input_block_v1":
        return {}
    return payload


def _compact_metric_for_transport(metric: Dict[str, Any]) -> Dict[str, Any]:
    return _copy_compact_keys(metric, [
        "metric_id",
        "domain",
        "label",
        "value",
        "unit",
        "scope",
        "source_id",
        "source_ids",
        "source_path",
        "calculation_method",
        "method",
        "status",
        "description",
        "display_text",
    ])


def _compact_evidence_item(*, source_id: str, source_title: str, evidence_type: str, title: str, text: str, citation: str = "", payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    item = {
        "source_id": source_id,
        "source_title": source_title,
        "type": evidence_type,
        "title": _truncated_text(title, 120),
        "text": _truncated_text(text, 700),
        "citation": _truncated_text(citation, 160),
    }
    extra = _safe_dict(payload)
    if extra:
        item["payload"] = extra
    return {key: value for key, value in item.items() if value not in ("", [], {})}


def _build_ppt_context_bundle(
    request: PptSpecRequest | PptOutlineSectionRequest | DeckNarrativePlanRequest | DeckBriefRequest | DeckBriefSlideRequest,
    metric_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    request_source_ids = getattr(request, "source_ids", None)
    if request_source_ids is None:
        request_source_ids = [_clean_text(source.id) for source in (getattr(request, "sources", []) or []) if _clean_text(source.id)]
    source_ids = [_clean_text(item) for item in (request_source_ids or []) if _clean_text(item)]
    selected = set(source_ids)
    sources = [source for source in (getattr(request, "sources", []) or []) if _clean_text(source.id) in selected]
    metric_context = metric_context or build_metric_context(sources=sources, source_ids=source_ids, current={})
    compact_metrics = compact_metric_context_for_llm(metric_context, limit=LLM_CONTEXT_METRIC_LIMIT)
    all_metrics = _safe_list(metric_context.get("metrics"))
    source_manifest: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    scopes: List[Dict[str, Any]] = []

    for source_id in source_ids:
        source = next((item for item in sources if _clean_text(item.id) == source_id), None)
        title = (source.title if source else "") or source_id
        meta = _safe_dict(source.meta if source else {})
        ai_payload = _ai_payload_for_source(source)
        source_kind = _clean_text(meta.get("sourceKind")) or ("document" if source_id.startswith("document:") else "package" if source_id.startswith("package:") else "system")
        source_metrics = [metric for metric in all_metrics if source_id in _metric_source_ids(metric) or _clean_text(metric.get("source_id")) == source_id]
        source_evidence = _safe_list(ai_payload.get("evidence"))
        source_scope = _safe_dict(ai_payload.get("scope"))
        if source_scope:
            scopes.append({"source_id": source_id, "title": title, **source_scope})
        if source_evidence:
            evidence.extend(source_evidence)
        included_types = _safe_list(ai_payload.get("included"))
        counts = _safe_dict(ai_payload.get("counts"))
        source_manifest.append({
            "source_id": source_id,
            "title": title,
            "source_kind": source_kind,
            "transport_status": "included" if included_types else "selected_no_payload",
            "included": included_types,
            "scope_count": int(counts.get("scope") or (1 if source_scope else 0)),
            "metric_count": len(source_metrics),
            "metric_gap_count": int(counts.get("metric_gaps") or counts.get("metricGaps") or 0),
            "evidence_count": len(source_evidence),
            "visual_spec_count": int(counts.get("visual_specs") or counts.get("visualSpecs") or 0),
            "excluded": _safe_list(ai_payload.get("excluded")),
            "policy": _clean_text(ai_payload.get("policy")) or "数字来自 aiPayload.metrics；文本/样本来自 aiPayload.evidence；完整原始数据不传给 LLM。",
        })

    evidence = evidence[:LLM_CONTEXT_EVIDENCE_LIMIT]
    included_source_ids = {item.get("source_id") for item in evidence}
    for item in source_manifest:
        if "evidence" in item["included"] and item["source_id"] not in included_source_ids and item["evidence_count"] > 0:
            item["evidence_omitted_by_limit"] = True

    bundle = {
        "version": "ppt_llm_context_bundle_v1",
        "scope_brief": scopes[0] if scopes else {},
        "scope_context": {"items": scopes, "item_count": len(scopes)},
        "source_manifest": source_manifest,
        "metric_context": compact_metrics,
        "evidence_context": {
            "policy": "只传所选来源 aiPayload.evidence；文档使用 PageIndex 章节摘要，资料包/current 分析使用轻量索引。",
            "items": evidence,
            "item_count": len(evidence),
        },
        "omitted_payloads": [
            "current.datasets.poi.items",
            "current.datasets.h3.features",
            "current.analysis.*.features",
            "package full items/geometries",
            "document full text",
        ],
    }
    return bundle


def _selected_sources_payload(request: PptSpecRequest | PptOutlineSectionRequest | DeckNarrativePlanRequest | DeckBriefRequest | DeckBriefSlideRequest) -> List[Dict[str, Any]]:
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


def _validate_slides(raw_slides: Any, page_count: int, metric_context: Dict[str, Any] | None = None, visual_assets: List[Dict[str, Any]] | None = None) -> List[DeckSlideBrief]:
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
        metric_assets = validate_visual_assets(item, metric_context or {}, visual_assets)
        slides.append(
            DeckSlideBrief(
                index=int(item.get("index") or index),
                title=title,
                purpose=_clean_text(item.get("purpose")),
                key_message=_clean_text(item.get("key_message") or item.get("keyMessage")),
                visual_plan=_clean_text(item.get("visual_plan") or item.get("visualPlan")),
                required_sources=[_clean_text(source) for source in required_sources if _clean_text(source)],
                metric_claims=metric_assets["metric_claims"],
                metric_gaps=metric_assets["metric_gaps"],
                visual_specs=metric_assets["visual_specs"],
                visual_artifacts=[],
            )
        )
    return slides


def generate_visual_artifacts_for_slide(request: PptVisualArtifactRequest) -> PptVisualArtifactResponse:
    metric_assets = validate_visual_assets(
        {"visual_specs": request.visual_specs},
        request.metric_context or {},
        request.existing_assets,
    )
    renderable_specs = [
        spec
        for spec in metric_assets["visual_specs"]
        if _clean_text(spec.get("status")) == "renderable"
        and _clean_text(spec.get("visual_type")) in {"figure", "table", "metric_card"}
    ]
    return PptVisualArtifactResponse(
        slide_index=request.slide_index,
        visual_artifacts=render_visual_artifacts(renderable_specs),
    )


def _has_slide_brief_content(slide: DeckSlideBrief) -> bool:
    return bool(
        _clean_text(slide.key_message)
        or _clean_text(slide.visual_plan)
        or slide.required_sources
        or slide.metric_claims
        or slide.metric_gaps
        or slide.visual_specs
        or slide.visual_artifacts
    )


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


def _outline_for_narrative_request(request: DeckNarrativePlanRequest) -> List[PptOutlineItem]:
    outline = request.spec.outline if request.spec and request.spec.outline else request.outline
    return _validate_outline([item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in outline], request.spec.page_count if request.spec else request.page_count)


def _validate_narrative_slide_roles(raw_roles: Any, outline: List[PptOutlineItem]) -> List[DeckNarrativeSlideRole]:
    if not outline:
        return []
    raw_items = raw_roles if isinstance(raw_roles, list) else []
    roles_by_page: Dict[int, Dict[str, Any]] = {}
    for index, raw in enumerate(raw_items, start=1):
        item = _safe_dict(raw)
        if not item:
            continue
        page_no = int(item.get("page_no") or item.get("pageNo") or index)
        roles_by_page[page_no] = item

    roles: List[DeckNarrativeSlideRole] = []
    for outline_item in outline:
        raw = roles_by_page.get(outline_item.page_no, {})
        evidence_focus = raw.get("evidence_focus") or raw.get("evidenceFocus") or []
        if not isinstance(evidence_focus, list):
            evidence_focus = [_clean_text(evidence_focus)] if _clean_text(evidence_focus) else []
        roles.append(
            DeckNarrativeSlideRole(
                page_no=outline_item.page_no,
                role=_clean_text(raw.get("role")) or outline_item.theme,
                objective=_clean_text(raw.get("objective")) or outline_item.purpose,
                evidence_focus=[_clean_text(item) for item in evidence_focus if _clean_text(item)],
                visual_direction=_clean_text(raw.get("visual_direction") or raw.get("visualDirection")),
                chart_intent=_clean_text(raw.get("chart_intent") or raw.get("chartIntent")),
                transition_note=_clean_text(raw.get("transition_note") or raw.get("transitionNote")),
            )
        )
    return roles


def _find_outline_context(outline: List[PptOutlineItem], page_no: int) -> Dict[str, Any]:
    index = next((idx for idx, item in enumerate(outline) if item.page_no == page_no), -1)
    if index < 0:
        return {"previous_outline_item": None, "next_outline_item": None}
    previous_item = outline[index - 1] if index > 0 else None
    next_item = outline[index + 1] if index + 1 < len(outline) else None
    return {
        "previous_outline_item": previous_item.model_dump(mode="json") if previous_item else None,
        "next_outline_item": next_item.model_dump(mode="json") if next_item else None,
    }


def _find_slide_context(slides: List[DeckSlideBrief], page_no: int) -> Dict[str, Any]:
    previous_slide = next((slide for slide in slides if slide.index == page_no - 1), None)
    next_slide = next((slide for slide in slides if slide.index == page_no + 1), None)
    return {
        "previous_slide": previous_slide.model_dump(mode="json") if previous_slide else None,
        "next_slide": next_slide.model_dump(mode="json") if next_slide else None,
    }


def _find_narrative_role(plan: DeckNarrativePlanResponse | None, page_no: int) -> Dict[str, Any] | None:
    if not plan:
        return None
    role = next((item for item in plan.slide_roles if item.page_no == page_no), None)
    return role.model_dump(mode="json") if role else None


def _validate_slide_section(raw: Any, fallback: DeckSlideBrief, metric_context: Dict[str, Any] | None = None, visual_assets: List[Dict[str, Any]] | None = None) -> DeckSlideBrief | None:
    item = _safe_dict(raw.get("slide")) if isinstance(raw, dict) and isinstance(raw.get("slide"), dict) else _safe_dict(raw)
    index = int(item.get("index") or fallback.index)
    slides = _validate_slides([{**fallback.model_dump(mode="json"), **item, "index": index}], index, metric_context=metric_context, visual_assets=visual_assets)
    if not slides:
        return None
    normalized = slides[0]
    if not _has_slide_brief_content(normalized):
        return None
    return DeckSlideBrief(
        index=fallback.index,
        title=normalized.title,
        purpose=normalized.purpose,
        key_message=normalized.key_message,
        visual_plan=normalized.visual_plan,
        required_sources=normalized.required_sources,
        metric_claims=normalized.metric_claims,
        metric_gaps=normalized.metric_gaps,
        visual_specs=normalized.visual_specs,
        visual_artifacts=normalized.visual_artifacts,
    )


def _ensure_llm_enabled() -> None:
    if not is_llm_enabled():
        raise PptPlanningLlmUnavailable("llm_unavailable")


async def classify_ppt_source_groups(request: PptSourceGroupClassifyRequest) -> PptSourceGroupClassifyResponse:
    sources = [source for source in request.sources if _clean_text(source.id)]
    if not sources:
        return PptSourceGroupClassifyResponse(groups=[])
    _ensure_llm_enabled()
    context_bundle = _build_ppt_context_bundle(request)
    raw = await _invoke_ppt_json_role(
        system_prompt=PPT_SOURCE_GROUP_SYSTEM_PROMPT,
        user_payload={
            "task": "ppt_source_group_classification",
            "area_id": request.area_id,
            "sources": [_compact_source_for_grouping(source) for source in sources],
            "context_bundle": {
                "scope_brief": context_bundle["scope_brief"],
                "source_manifest": context_bundle["source_manifest"],
            },
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
    request_id = uuid.uuid4().hex[:10]
    total_started = time.perf_counter()
    metrics: Dict[str, float | int | str] = {
        "request_id": request_id,
        "area_id": request.area_id,
        "source_count": len(request.source_ids or []),
        "page_count": request.page_count,
    }
    context_bundle = _build_ppt_context_bundle(request)
    context_ready = time.perf_counter()
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
        "scope_brief": context_bundle["scope_brief"],
        "metric_context": context_bundle["metric_context"],
        "evidence_context": context_bundle["evidence_context"],
        "source_manifest": context_bundle["source_manifest"],
        "omitted_payloads": context_bundle["omitted_payloads"],
        "missing_inputs_from_request": _missing_inputs_for_spec(request),
    }
    payload_ready = time.perf_counter()
    metrics["context_bundle_ms"] = round((context_ready - total_started) * 1000, 2)
    metrics["payload_prepare_ms"] = round((payload_ready - context_ready) * 1000, 2)
    metrics["payload_bytes"] = len(json.dumps(user_payload, ensure_ascii=False).encode("utf-8"))
    try:
        raw = await _invoke_ppt_json_role(
            system_prompt=PPT_SPEC_SYSTEM_PROMPT,
            user_payload=user_payload,
            emit=None,
            phase="ppt_outline_generation",
            title="生成 PPT 目录",
            reasoning_id="ppt-outline-generation",
        )
        llm_ready = time.perf_counter()
        outline = _validate_outline(raw.get("outline"), request.page_count)
        if not outline:
            raise PptPlanningInvalidResponse("invalid_ppt_outline")
        missing_inputs = raw.get("missing_inputs")
        if not isinstance(missing_inputs, list):
            missing_inputs = _missing_inputs_for_spec(request)
        response = PptSpecResponse(
            title=_clean_text(raw.get("title")) or request.topic or "PPT 目录",
            goal=_clean_text(raw.get("goal")) or "形成可继续生成逐页指令的汇报目录。",
            audience=_clean_text(raw.get("audience")) or request.audience,
            deck_type=_clean_text(raw.get("deck_type")) or request.deck_type,
            page_count=int(raw.get("page_count") or request.page_count),
            outline=outline,
            source_summary=_clean_text(raw.get("source_summary")) or _source_summary(request.source_ids, request.research_enabled),
            missing_inputs=[_clean_text(item) for item in missing_inputs if _clean_text(item)],
            context_manifest=context_bundle,
        )
        done = time.perf_counter()
        metrics["llm_ms"] = round((llm_ready - payload_ready) * 1000, 2)
        metrics["validate_ms"] = round((done - llm_ready) * 1000, 2)
        metrics["total_ms"] = round((done - total_started) * 1000, 2)
        metrics["outline_count"] = len(outline)
        _dump_generation_response("_last_ppt_spec_response.json", response.model_dump(mode="json"))
        logger.info("PPT outline generation completed %s", metrics)
        return response
    except Exception:
        failed = time.perf_counter()
        metrics["total_ms"] = round((failed - total_started) * 1000, 2)
        if "llm_ms" not in metrics:
            metrics["llm_ms"] = round((failed - payload_ready) * 1000, 2)
        logger.warning("PPT outline generation failed %s", metrics, exc_info=True)
        raise


async def regenerate_ppt_outline_section(request: PptOutlineSectionRequest) -> PptOutlineItem:
    _ensure_llm_enabled()
    context_bundle = _build_ppt_context_bundle(request)
    raw = await _invoke_ppt_json_role(
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
            "scope_brief": context_bundle["scope_brief"],
            "metric_context": context_bundle["metric_context"],
            "evidence_context": context_bundle["evidence_context"],
            "source_manifest": context_bundle["source_manifest"],
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


async def generate_narrative_plan(request: DeckNarrativePlanRequest) -> DeckNarrativePlanResponse:
    _ensure_llm_enabled()
    outline = _outline_for_narrative_request(request)
    if not outline:
        raise PptPlanningInvalidResponse("invalid_ppt_outline")
    page_count = request.spec.page_count if request.spec else request.page_count
    metric_context = build_metric_context(
        sources=request.sources,
        source_ids=request.source_ids,
        current={},
    )
    context_bundle = _build_ppt_context_bundle(request, metric_context=metric_context)
    raw = await _invoke_ppt_json_role(
        system_prompt=DECK_NARRATIVE_PLAN_SYSTEM_PROMPT,
        user_payload={
            "task": "ppt_narrative_plan_generation",
            "area_id": request.area_id,
            "topic": request.topic or (request.spec.title if request.spec else ""),
            "audience": request.audience,
            "deck_type": request.deck_type,
            "page_count": page_count,
            "research_enabled": request.research_enabled,
            "source_ids": request.source_ids,
            "sources": _selected_sources_payload(request),
            "source_summary": _source_summary(request.source_ids, request.research_enabled),
            "scope_brief": context_bundle["scope_brief"],
            "metric_context": context_bundle["metric_context"],
            "evidence_context": context_bundle["evidence_context"],
            "source_manifest": context_bundle["source_manifest"],
            "omitted_payloads": context_bundle["omitted_payloads"],
            "spec": request.spec.model_dump(mode="json") if request.spec else None,
            "outline": [item.model_dump(mode="json") for item in outline],
        },
        emit=None,
        phase="ppt_narrative_plan_generation",
        title="生成 PPT 叙事方案",
        reasoning_id="ppt-narrative-plan-generation",
    )
    slide_roles = _validate_narrative_slide_roles(raw.get("slide_roles") or raw.get("slideRoles"), outline)
    if len(slide_roles) != len(outline):
        raise PptPlanningInvalidResponse("invalid_ppt_narrative_slide_roles")
    missing_inputs = raw.get("missing_inputs")
    if not isinstance(missing_inputs, list):
        missing_inputs = []
    response = DeckNarrativePlanResponse(
        storyline=_clean_text(raw.get("storyline")),
        style_guide=_clean_text(raw.get("style_guide") or raw.get("styleGuide")),
        evidence_strategy=_clean_text(raw.get("evidence_strategy") or raw.get("evidenceStrategy")),
        chart_strategy=_clean_text(raw.get("chart_strategy") or raw.get("chartStrategy")),
        slide_roles=slide_roles,
        missing_inputs=[_clean_text(item) for item in missing_inputs if _clean_text(item)],
        context_manifest=context_bundle,
    )
    _dump_generation_response("_last_ppt_narrative_plan_response.json", response.model_dump(mode="json"))
    return response


async def generate_deck_brief(request: DeckBriefRequest) -> DeckBriefResponse:
    _ensure_llm_enabled()
    page_count = request.spec.page_count if request.spec else request.page_count
    metric_context = build_metric_context(
        sources=request.sources,
        source_ids=request.source_ids,
        current={},
    )
    context_bundle = _build_ppt_context_bundle(request, metric_context=metric_context)
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
        "scope_brief": context_bundle["scope_brief"],
        "metric_context": context_bundle["metric_context"],
        "evidence_context": context_bundle["evidence_context"],
        "source_manifest": context_bundle["source_manifest"],
        "omitted_payloads": context_bundle["omitted_payloads"],
        "spec": request.spec.model_dump(mode="json") if request.spec else None,
    }
    raw = await _invoke_ppt_json_role(
        system_prompt=DECK_BRIEF_SYSTEM_PROMPT,
        user_payload=user_payload,
        emit=None,
        phase="ppt_directive_generation",
        title="生成 PPT 逐页指令",
        reasoning_id="ppt-directive-generation",
    )
    slides = _validate_slides(raw.get("slides"), page_count, metric_context=metric_context, visual_assets=_visual_assets_from_request(request))
    if not slides:
        raise PptPlanningInvalidResponse("invalid_deck_brief")
    missing_inputs = raw.get("missing_inputs")
    if not isinstance(missing_inputs, list):
        missing_inputs = [] if request.topic or request.spec else ["topic"]
    response = DeckBriefResponse(
        status="draft",
        slides=slides,
        source_summary=_clean_text(raw.get("source_summary")) or _source_summary(request.source_ids, request.research_enabled),
        missing_inputs=[_clean_text(item) for item in missing_inputs if _clean_text(item)],
        context_manifest=context_bundle,
    )
    _dump_generation_response("_last_ppt_deck_brief_response.json", response.model_dump(mode="json"))
    return response


async def regenerate_deck_brief_slide(request: DeckBriefSlideRequest) -> DeckSlideBrief:
    _ensure_llm_enabled()
    metric_context = build_metric_context(
        sources=request.sources,
        source_ids=request.source_ids,
        current={},
    )
    context_bundle = _build_ppt_context_bundle(request, metric_context=metric_context)
    outline = _validate_outline([item.model_dump(mode="json") for item in request.outline], request.spec.page_count if request.spec else request.page_count)
    page_no = int(request.outline_item.page_no if request.outline_item else request.target.index)
    outline_context = _find_outline_context(outline, page_no)
    slide_context = _find_slide_context(request.slides, page_no)
    target_slide_role = _find_narrative_role(request.narrative_plan, page_no)
    user_payload = {
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
        "scope_brief": context_bundle["scope_brief"],
        "metric_context": context_bundle["metric_context"],
        "evidence_context": context_bundle["evidence_context"],
        "source_manifest": context_bundle["source_manifest"],
        "spec": request.spec.model_dump(mode="json") if request.spec else None,
        "outline": [item.model_dump(mode="json") for item in request.outline],
        "slides": [item.model_dump(mode="json") for item in request.slides],
        "outline_item": request.outline_item.model_dump(mode="json") if request.outline_item else None,
        "previous_outline_item": outline_context["previous_outline_item"],
        "next_outline_item": outline_context["next_outline_item"],
        "previous_slide": slide_context["previous_slide"],
        "next_slide": slide_context["next_slide"],
        "narrative_plan": request.narrative_plan.model_dump(mode="json") if request.narrative_plan else None,
        "target_slide_role": target_slide_role,
        "target": request.target.model_dump(mode="json"),
    }
    raw: Dict[str, Any] = {}
    for attempt in range(2):
        try:
            raw = await _invoke_ppt_json_role(
                system_prompt=DECK_BRIEF_SLIDE_SYSTEM_PROMPT,
                user_payload={
                    **user_payload,
                    **({"retry_instruction": "上一轮返回不是合法 JSON。请只返回一个严格 JSON 对象，不要包含注释、尾随逗号、markdown 或解释文字。"} if attempt else {}),
                },
                emit=None,
                phase="ppt_directive_slide_regeneration",
                title="重生成 PPT 指令页",
                reasoning_id=f"ppt-directive-slide-{request.target.index}",
            )
            break
        except json.JSONDecodeError:
            if attempt >= 1:
                raise
            logger.warning(
                "PPT directive slide returned invalid JSON; retrying once page=%s",
                request.target.index,
                exc_info=True,
            )
    slide = _validate_slide_section(raw, request.target, metric_context=metric_context, visual_assets=_visual_assets_from_request(request))
    if not slide:
        raise PptPlanningInvalidResponse("invalid_deck_brief_slide")
    return slide
