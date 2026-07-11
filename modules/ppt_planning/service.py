from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from core.config import settings
from modules.agent.providers.llm_provider import _invoke_json_role, is_llm_enabled
from modules.agent.providers.chat_parser import LlmJsonParseError, extract_json_object
from modules.evidence_retrieval import SourceRecord, evidence_node_from_node_payload

from .prompts import (
    DECK_BRIEF_SLIDE_SYSTEM_PROMPT,
    DECK_BRIEF_SYSTEM_PROMPT,
    DECK_NARRATIVE_PLAN_SYSTEM_PROMPT,
    PPT_OUTLINE_SECTION_SYSTEM_PROMPT,
    PPT_JSON_REPAIR_SYSTEM_PROMPT,
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
    DeckBriefJobCreateResponse,
    DeckBriefJobStatusResponse,
    DeckBriefRequest,
    DeckBriefResponse,
    DeckNarrativeChapter,
    DeckNarrativeEvidenceBucket,
    DeckNarrativePlanRequest,
    DeckNarrativePlanResponse,
    DeckNarrativeSlideRole,
    DeckNarrativeVisualStrategy,
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
    def __init__(self, message: str = "ppt_planning_invalid_ai_response", detail: Dict[str, Any] | None = None):
        super().__init__(message)
        self.detail = detail or {}


logger = logging.getLogger(__name__)

LLM_PACKAGE_ITEM_LIMIT = 8
LLM_PACKAGE_GROUP_LIMIT = 8
LLM_CARRIER_LIMIT = 12
LLM_CARRIER_REPRESENTATIVE_POI_LIMIT = 3
LLM_EVIDENCE_REF_LIMIT = 20
LLM_WARNING_LIMIT = 6
LLM_CONTEXT_METRIC_LIMIT = 120
LLM_PAGE_CONTEXT_METRIC_LIMIT = 36
LLM_PAGE_CONTEXT_EVIDENCE_LIMIT = 12
LLM_CONTEXT_EVIDENCE_LIMIT = 48
PPT_DEBUG_DIR = Path("runtime")
DECK_BRIEF_JOB_TTL_SECONDS = 60 * 60

_deck_brief_jobs: Dict[str, Dict[str, Any]] = {}
_deck_brief_job_lock = asyncio.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_job_error(exc: Exception) -> Dict[str, Any]:
    code = "ppt_deck_brief_job_failed"
    if isinstance(exc, PptPlanningInvalidResponse):
        code = str(exc) or "ppt_planning_invalid_ai_response"
    elif isinstance(exc, PptPlanningLlmUnavailable):
        code = "ppt_planning_llm_unavailable"
    elif isinstance(exc, ValueError):
        code = "ppt_planning_llm_invalid_response"
    return {
        "code": code,
        "message": str(exc) or code,
        "detail": exc.detail if isinstance(exc, PptPlanningInvalidResponse) else {},
    }


async def _prune_deck_brief_jobs(now: float | None = None) -> None:
    current = now if now is not None else time.time()
    expired: List[str] = []
    for job_id, job in _deck_brief_jobs.items():
        created_ts = float(job.get("created_ts") or current)
        if current - created_ts > DECK_BRIEF_JOB_TTL_SECONDS:
            expired.append(job_id)
    for job_id in expired:
        _deck_brief_jobs.pop(job_id, None)


def _deck_brief_job_response(job: Dict[str, Any]) -> DeckBriefJobStatusResponse:
    result = job.get("result")
    if result is not None and not isinstance(result, DeckBriefResponse):
        result = DeckBriefResponse.model_validate(result)
    return DeckBriefJobStatusResponse(
        job_id=str(job.get("job_id") or ""),
        status=str(job.get("status") or "queued"),
        progress=dict(job.get("progress") or {}),
        result=result,
        error=dict(job.get("error") or {}),
        created_at=str(job.get("created_at") or ""),
        updated_at=str(job.get("updated_at") or ""),
    )


async def _run_deck_brief_job(job_id: str, request: DeckBriefRequest) -> None:
    async with _deck_brief_job_lock:
        job = _deck_brief_jobs.get(job_id)
        if not job:
            return
        job.update({
            "status": "running",
            "updated_at": _utc_now_iso(),
            "progress": {"stage": "running", "message": "正在生成 brief"},
        })
    try:
        result = await generate_deck_brief(request)
        async with _deck_brief_job_lock:
            job = _deck_brief_jobs.get(job_id)
            if job:
                job.update({
                    "status": "completed",
                    "result": result,
                    "error": {},
                    "updated_at": _utc_now_iso(),
                    "progress": {
                        "stage": "completed",
                        "message": "brief 已生成",
                        "slide_count": len(result.slides),
                    },
                })
    except Exception as exc:
        logger.warning("PPT deck brief job failed", extra={"ppt_deck_brief_job": {"job_id": job_id}}, exc_info=exc)
        async with _deck_brief_job_lock:
            job = _deck_brief_jobs.get(job_id)
            if job:
                job.update({
                    "status": "failed",
                    "result": None,
                    "error": _safe_job_error(exc),
                    "updated_at": _utc_now_iso(),
                    "progress": {"stage": "failed", "message": "brief 生成失败"},
                })


def _dump_generation_response(filename: str, payload: Dict[str, Any]) -> None:
    try:
        PPT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = PPT_DEBUG_DIR / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("PPT generation response dumped to %s", path.as_posix())
    except Exception:
        logger.debug("Failed to dump PPT generation response", exc_info=True)


def _json_error_summary(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, LlmJsonParseError):
        return exc.summary
    if isinstance(exc, json.JSONDecodeError):
        return {
            "message": exc.msg,
            "line": exc.lineno,
            "column": exc.colno,
            "char": exc.pos,
            "snippet": str(exc.doc or "")[max(0, exc.pos - 120):exc.pos + 120],
        }
    return {"message": str(exc)}


async def _invoke_ppt_json_role(**kwargs: Any) -> Dict[str, Any]:
    return await _invoke_json_role(
        **kwargs,
        enable_thinking=False,
        stream=False,
        timeout_s=float(settings.ppt_llm_timeout_s),
    )


async def _repair_ppt_json_object(
    *,
    bad_json: str,
    parse_error: Dict[str, Any],
    schema_summary: Dict[str, Any],
    reasoning_id: str,
) -> Dict[str, Any]:
    repaired = await _invoke_ppt_json_role(
        system_prompt=PPT_JSON_REPAIR_SYSTEM_PROMPT,
        user_payload={
            "task": "repair_invalid_json",
            "parse_error": parse_error,
            "schema_summary": schema_summary,
            "invalid_json": bad_json,
        },
        emit=None,
        phase="ppt_json_repair",
        title="修复 PPT JSON",
        reasoning_id=reasoning_id,
    )
    return extract_json_object(json.dumps(repaired, ensure_ascii=False))


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _truncated_text(value: Any, limit: int = 180) -> str:
    text = _clean_text(value)
    return text[:limit]


def _compact_insight_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[。！？!?；;\n]+", text) if part.strip()]
    compact = "。".join(parts[:3]).strip("。")
    return _truncated_text(compact or text, 220)


def _compact_evidence_explanation(value: Any) -> List[str]:
    raw_items = value if isinstance(value, list) else [value]
    items: List[str] = []
    for raw in raw_items:
        if isinstance(raw, dict):
            text = _clean_text(raw.get("text") or raw.get("description") or raw.get("source") or raw.get("method"))
        else:
            text = _clean_text(raw)
        if not text:
            continue
        parts = [part.strip() for part in re.split(r"[\n；;]+", text) if part.strip()]
        for part in parts:
            compact = re.sub(r"^[\-\*\d\.\)、\s]+", "", part).strip()
            if compact:
                items.append(_truncated_text(compact, 120))
            if len(items) >= 3:
                return items
    return items


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
        "source_kind": _clean_text(source.source_kind),
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
        for raw_source_id in raw_group.get("source_ids") or []:
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


def _source_summary(source_ids: List[str], web_sources_enabled: bool) -> str:
    selected_count = len([item for item in source_ids if item])
    research_note = "包含联网来源" if web_sources_enabled else "不包含联网来源"
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
    source_ids = [_clean_text(item) for item in _safe_list(metric.get("source_ids")) if _clean_text(item)]
    source_id = _clean_text(metric.get("source_id"))
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


def _compact_evidence_node(node: Any) -> Dict[str, Any]:
    payload = node.model_dump(mode="python") if hasattr(node, "model_dump") else _safe_dict(node)
    metadata = _safe_dict(payload.get("metadata"))
    return {
        "id": _clean_text(payload.get("id")),
        "source_id": _clean_text(payload.get("source_id")),
        "source_type": _clean_text(payload.get("source_type")),
        "title": _truncated_text(payload.get("title"), 120),
        "content": _truncated_text(payload.get("content"), 700),
        "summary": _truncated_text(payload.get("summary"), 260),
        "locator": _truncated_text(payload.get("locator"), 160),
        "evidence_level": _clean_text(payload.get("evidence_level")),
        "citation": _truncated_text(payload.get("citation"), 160),
        "warnings": _safe_list(payload.get("warnings"))[:4],
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key in {
                "domain",
                "page",
                "page_no",
                "url",
                "record_id",
                "record_type",
                "confidence",
                "locator",
                "node_id",
                "carrier_id",
                "run_id",
                "source_run_id",
                "artifact_id",
                "content_digest",
                "artifact_version",
            }
        },
    }


def _evidence_nodes_from_ai_payload(source_id: str, title: str, source_kind: str, ai_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    source = SourceRecord.model_validate({
        "id": source_id,
        "title": title,
        "source_kind": source_kind,
        "status": "ready",
        "meta": {"aiPayload": ai_payload, "sourceKind": source_kind},
    })
    nodes: List[Dict[str, Any]] = []
    explicit_nodes = _safe_list(ai_payload.get("evidence_nodes"))
    for index, item in enumerate(explicit_nodes, start=1):
        node = evidence_node_from_node_payload("", source, item, index=index)
        if node is not None:
            nodes.append(_compact_evidence_node(node))
    return nodes


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
    evidence_nodes: List[Dict[str, Any]] = []
    scopes: List[Dict[str, Any]] = []

    for source_id in source_ids:
        source = next((item for item in sources if _clean_text(item.id) == source_id), None)
        title = (source.title if source else "") or source_id
        meta = _safe_dict(source.meta if source else {})
        ai_payload = _ai_payload_for_source(source)
        source_kind = _clean_text(source.source_kind if source else "") or ("document" if source_id.startswith("document:") else "package" if source_id.startswith("package:") else "system")
        source_metrics = [metric for metric in all_metrics if source_id in _metric_source_ids(metric) or _clean_text(metric.get("source_id")) == source_id]
        source_evidence_nodes = _evidence_nodes_from_ai_payload(source_id, title, source_kind, ai_payload)
        source_scope = _safe_dict(ai_payload.get("scope"))
        if source_scope:
            scopes.append({"source_id": source_id, "title": title, **source_scope})
        if source_evidence_nodes:
            evidence_nodes.extend(source_evidence_nodes)
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
            "metric_gap_count": int(counts.get("metric_gaps") or 0),
            "evidence_count": len(source_evidence_nodes),
            "visual_spec_count": int(counts.get("visual_specs") or 0),
            "excluded": _safe_list(ai_payload.get("excluded")),
            "policy": _clean_text(ai_payload.get("policy")) or "数字来自 aiPayload.metrics；文本/样本来自 EvidenceNode；完整原始数据不传给 LLM。",
        })

    evidence_nodes = evidence_nodes[:LLM_CONTEXT_EVIDENCE_LIMIT]
    included_source_ids = {item.get("source_id") for item in evidence_nodes}
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
            "policy": "只传所选来源的紧凑 EvidenceNode；文档使用 PageIndex 节点，资料包/current 分析使用轻量节点。",
            "items": evidence_nodes,
            "item_count": len(evidence_nodes),
        },
        "evidence_node_context": {
            "items": evidence_nodes,
            "item_count": len(evidence_nodes),
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
                insight=_compact_insight_text(item.get("insight")),
                evidence_explanation=_compact_evidence_explanation(item.get("evidence_explanation") or item.get("evidenceExplanation")),
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
        and _clean_text(spec.get("visual_type")) in {"figure", "table", "metric_card", "diagram", "matrix", "existing_asset"}
    ]
    return PptVisualArtifactResponse(
        slide_index=request.slide_index,
        visual_specs=metric_assets["visual_specs"],
        visual_artifacts=render_visual_artifacts(renderable_specs),
    )


def _has_slide_brief_content(slide: DeckSlideBrief) -> bool:
    return bool(
        _clean_text(slide.key_message)
        or _clean_text(slide.insight)
        or slide.evidence_explanation
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


NARRATIVE_VIUAL_FAMILIES = {
    "map_metric_card",
    "dashboard",
    "existing_map_layer",
    "diagram",
    "matrix",
    "timeline",
    "decision_list",
}


def _truncate_by_chars(value: Any, limit: int) -> str:
    return _clean_text(value)[:limit]


def _validate_narrative_slide_roles(raw_roles: Any, outline: List[PptOutlineItem], bucket_ids: set[str]) -> List[DeckNarrativeSlideRole]:
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
        evidence_bucket = _clean_text(raw.get("evidence_bucket") or raw.get("evidenceBucket"))
        if evidence_bucket and bucket_ids and evidence_bucket not in bucket_ids:
            evidence_bucket = ""
        visual_family = _clean_text(raw.get("visual_family") or raw.get("visualFamily"))
        if visual_family not in NARRATIVE_VIUAL_FAMILIES:
            visual_family = ""
        roles.append(
            DeckNarrativeSlideRole(
                page_no=outline_item.page_no,
                role=_clean_text(raw.get("role")) or outline_item.theme,
                job=_truncate_by_chars(raw.get("job") or raw.get("objective") or outline_item.purpose, 30),
                evidence_bucket=evidence_bucket,
                visual_family=visual_family,
                transition_note=_clean_text(raw.get("transition_note") or raw.get("transitionNote")),
            )
        )
    return roles


def _validate_narrative_chapters(raw_chapters: Any) -> List[DeckNarrativeChapter]:
    allowed_sections = {
        "开篇定调",
        "空间与人口底座",
        "结构诊断",
        "活力诊断",
        "痛点提炼",
        "愿景与定位",
        "落位与实施",
    }
    chapters: List[DeckNarrativeChapter] = []
    for raw in _safe_list(raw_chapters)[:7]:
        item = _safe_dict(raw)
        name = _clean_text(item.get("name") or item.get("section"))
        if name not in allowed_sections:
            continue
        chapters.append(DeckNarrativeChapter(
            name=name,
            page_range=_clean_text(item.get("page_range") or item.get("pageRange")),
            job=_truncate_by_chars(item.get("job") or item.get("objective"), 30),
            output=_truncate_by_chars(item.get("output") or item.get("output_conclusion") or item.get("outputConclusion"), 30),
        ))
    return chapters


def _validate_narrative_evidence_buckets(raw_buckets: Any) -> List[DeckNarrativeEvidenceBucket]:
    buckets: List[DeckNarrativeEvidenceBucket] = []
    for raw in _safe_list(raw_buckets):
        item = _safe_dict(raw)
        bucket_id = _clean_text(item.get("id"))
        if not bucket_id:
            continue
        buckets.append(DeckNarrativeEvidenceBucket(
            id=bucket_id,
            label=_clean_text(item.get("label")),
            allowed_sources=[_clean_text(value) for value in _safe_list(item.get("allowed_sources") or item.get("allowedSources")) if _clean_text(value)],
        ))
    return buckets


def _validate_narrative_visual_rules(raw_strategy: Any) -> DeckNarrativeVisualStrategy:
    item = _safe_dict(raw_strategy)
    return DeckNarrativeVisualStrategy(
        spatial_first=bool(item.get("spatial_first") if item.get("spatial_first") is not None else item.get("spatialFirst")),
        numeric_charts_require_data=bool(item.get("numeric_charts_require_data") if item.get("numeric_charts_require_data") is not None else item.get("numericChartsRequireData", True)),
        diagram_for_strategy_pages=bool(item.get("diagram_for_strategy_pages") if item.get("diagram_for_strategy_pages") is not None else item.get("diagramForStrategyPages", True)),
        no_fallback_bar=bool(item.get("no_fallback_bar") if item.get("no_fallback_bar") is not None else item.get("noFallbackBar", True)),
    )


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


def _summary_from_slide(slide: DeckSlideBrief | None) -> Dict[str, Any]:
    if not slide:
        return {}
    return {
        "index": slide.index,
        "title": _truncated_text(slide.title, 100),
        "purpose": _truncated_text(slide.purpose, 180),
        "key_message": _truncated_text(slide.key_message, 220),
        "insight": _truncated_text(slide.insight, 260),
        "evidence_explanation": slide.evidence_explanation[:3],
        "visual_plan": _truncated_text(slide.visual_plan, 180),
        "required_sources": slide.required_sources[:8],
    }


def _request_previous_slide_summary(request: DeckBriefSlideRequest, page_no: int) -> Dict[str, Any]:
    summary = _safe_dict(getattr(request, "previous_slide_summary", {}))
    if summary:
        return summary
    previous = next((slide for slide in request.slides if slide.index == page_no - 1), None)
    return _summary_from_slide(previous)


def _request_next_outline_summary(request: DeckBriefSlideRequest, outline: List[PptOutlineItem], page_no: int) -> Dict[str, Any]:
    summary = _safe_dict(getattr(request, "next_outline_summary", {}))
    if summary:
        return summary
    outline_context = _find_outline_context(outline, page_no)
    return _safe_dict(outline_context.get("next_outline_item"))


def _deck_progress_summary(request: DeckBriefSlideRequest, page_no: int, outline: List[PptOutlineItem]) -> Dict[str, Any]:
    summary = _safe_dict(getattr(request, "deck_progress_summary", {}))
    if summary:
        return summary
    generated_pages = sorted({int(slide.index) for slide in request.slides if int(slide.index or 0) > 0})
    total = len(outline) or int((request.spec.page_count if request.spec else request.page_count) or 0)
    return {
        "page_no": page_no,
        "page_count": total,
        "generated_pages": generated_pages[:80],
        "ready_count": len(generated_pages),
        "pending_count": max(total - len(generated_pages), 0) if total else 0,
    }


def _keyword_tokens(*values: Any) -> List[str]:
    text = " ".join(_clean_text(value) for value in values if _clean_text(value)).lower()
    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", text)
    seen: set[str] = set()
    result: List[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result[:80]


def _text_matches_tokens(value: Any, tokens: List[str]) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()
    return any(token and token in text for token in tokens)


def _filter_page_metric_context(metric_context: Dict[str, Any], packet: Dict[str, Any], source_ids: List[str]) -> Dict[str, Any]:
    tokens = _keyword_tokens(
        packet.get("outline_item"),
        packet.get("narrative_role"),
        packet.get("visual_family"),
    )
    selected_sources = set(source_ids)
    metrics = []
    for metric in _safe_list(metric_context.get("metrics")):
        metric_sources = set(_metric_source_ids(metric))
        source_match = bool(selected_sources and metric_sources.intersection(selected_sources))
        text_match = _text_matches_tokens(metric, tokens)
        if source_match or text_match:
            metrics.append(metric)
    if not metrics:
        metrics = _safe_list(metric_context.get("metrics"))[:LLM_PAGE_CONTEXT_METRIC_LIMIT]
    gaps = [
        gap for gap in _safe_list(metric_context.get("metric_gaps"))
        if _text_matches_tokens(gap, tokens) or not tokens
    ][:12]
    return {
        "version": metric_context.get("version"),
        "metric_count": len(metrics),
        "metrics": metrics[:LLM_PAGE_CONTEXT_METRIC_LIMIT],
        "metric_gaps": gaps,
        "missing_metric_count": metric_context.get("missing_metric_count", 0),
        "policy": metric_context.get("policy"),
    }


def _filter_page_evidence_context(context_bundle: Dict[str, Any], packet: Dict[str, Any], source_ids: List[str]) -> Dict[str, Any]:
    tokens = _keyword_tokens(
        packet.get("outline_item"),
        packet.get("narrative_role"),
        packet.get("visual_family"),
    )
    selected_sources = set(source_ids)
    selected: List[Dict[str, Any]] = []
    fallback: List[Dict[str, Any]] = []
    for item in _safe_list(_safe_dict(context_bundle.get("evidence_context")).get("items")):
        source_id = _clean_text(item.get("source_id"))
        if selected_sources and source_id in selected_sources:
            fallback.append(item)
        if (selected_sources and source_id in selected_sources) or _text_matches_tokens(item, tokens):
            selected.append(item)
    if not selected:
        selected = fallback or _safe_list(_safe_dict(context_bundle.get("evidence_context")).get("items"))
    return {
        "policy": "只传目标页命中的轻量证据；不得从自然语言里推断精确数字。",
        "items": selected[:LLM_PAGE_CONTEXT_EVIDENCE_LIMIT],
        "item_count": min(len(selected), LLM_PAGE_CONTEXT_EVIDENCE_LIMIT),
        "available_item_count": len(selected),
    }


def _filter_page_source_manifest(context_bundle: Dict[str, Any], source_ids: List[str]) -> List[Dict[str, Any]]:
    selected = set(source_ids)
    manifest = _safe_list(context_bundle.get("source_manifest"))
    if not selected:
        return manifest[:20]
    result = [item for item in manifest if _clean_text(item.get("source_id")) in selected]
    return result or manifest[:20]


def _recommended_source_ids_for_page(request: DeckBriefSlideRequest, role: Dict[str, Any] | None, context_bundle: Dict[str, Any], outline_item: PptOutlineItem | None) -> List[str]:
    source_ids = [_clean_text(item) for item in request.source_ids if _clean_text(item)]
    if not source_ids:
        return []
    tokens = _keyword_tokens(
        outline_item.model_dump(mode="json") if outline_item else {},
        role or {},
    )
    evidence_context = _safe_dict(context_bundle.get("evidence_context"))
    matched: List[str] = []
    for item in _safe_list(evidence_context.get("items")):
        source_id = _clean_text(item.get("source_id"))
        if source_id in source_ids and _text_matches_tokens(item, tokens):
            matched.append(source_id)
    role_sources = [
        source_id for source_id in source_ids
        if _text_matches_tokens(source_id, tokens) or _text_matches_tokens(next((manifest for manifest in _safe_list(context_bundle.get("source_manifest")) if _clean_text(manifest.get("source_id")) == source_id), {}), tokens)
    ]
    ordered = []
    for source_id in [*matched, *role_sources, *source_ids]:
        if source_id and source_id not in ordered:
            ordered.append(source_id)
    return ordered[:8]


def _build_brief_generation_context(
    request: DeckBriefSlideRequest,
    *,
    outline: List[PptOutlineItem],
    page_no: int,
    context_bundle: Dict[str, Any],
    metric_context: Dict[str, Any],
) -> Dict[str, Any]:
    outline_item = next((item for item in outline if item.page_no == page_no), None)
    role = _find_narrative_role(request.narrative_plan, page_no)
    source_ids = _recommended_source_ids_for_page(request, role, context_bundle, outline_item)
    packet = {
        "page_no": page_no,
        "outline_item": outline_item.model_dump(mode="json") if outline_item else _safe_dict(request.outline_item.model_dump(mode="json") if request.outline_item else {}),
        "narrative_role": role,
        "recommended_source_ids": source_ids,
        "previous_slide_summary": _request_previous_slide_summary(request, page_no),
        "next_outline_summary": _request_next_outline_summary(request, outline, page_no),
        "visual_family": _clean_text((role or {}).get("visual_family")),
    }
    page_metric_context = _filter_page_metric_context(metric_context, packet, source_ids)
    packet["recommended_metric_ids"] = [
        _clean_text(metric.get("metric_id") or metric.get("metricId"))
        for metric in _safe_list(page_metric_context.get("metrics"))
        if _clean_text(metric.get("metric_id") or metric.get("metricId"))
    ][:20]
    page_evidence_context = _filter_page_evidence_context(context_bundle, packet, source_ids)
    packet["recommended_evidence_ids"] = [
        _clean_text(item.get("id") or item.get("evidence_id") or item.get("title"))
        for item in _safe_list(page_evidence_context.get("items"))
        if _clean_text(item.get("id") or item.get("evidence_id") or item.get("title"))
    ][:20]
    page_count = len(outline) or int((request.spec.page_count if request.spec else request.page_count) or 0)
    context_id = _clean_text(request.context_id) or hashlib.sha1(json.dumps({
        "area_id": request.area_id,
        "page_count": page_count,
        "outline": [item.model_dump(mode="json") for item in outline],
        "sources": request.source_ids,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return {
        "deck_id": _clean_text(request.area_id) or context_id,
        "context_id": context_id,
        "page_count": page_count,
        "outline_map": {str(item.page_no): item.model_dump(mode="json") for item in outline},
        "slide_role_map": {str(role_item.page_no): role_item.model_dump(mode="json") for role_item in (request.narrative_plan.slide_roles if request.narrative_plan else [])},
        "page_context_packets": {str(page_no): packet},
        "page_context_packet": packet,
        "deck_progress_summary": _deck_progress_summary(request, page_no, outline),
        "metric_index": {
            "metric_count": len(_safe_list(page_metric_context.get("metrics"))),
            "metric_ids": packet["recommended_metric_ids"],
        },
        "evidence_index": {
            "evidence_count": len(_safe_list(page_evidence_context.get("items"))),
            "evidence_ids": packet["recommended_evidence_ids"],
        },
        "metric_context": page_metric_context,
        "evidence_context": page_evidence_context,
        "evidence_node_context": page_evidence_context,
        "source_manifest": _filter_page_source_manifest(context_bundle, source_ids),
    }


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
        insight=normalized.insight,
        evidence_explanation=normalized.evidence_explanation,
        visual_plan=normalized.visual_plan,
        required_sources=normalized.required_sources,
        metric_claims=normalized.metric_claims,
        metric_gaps=normalized.metric_gaps,
        visual_specs=normalized.visual_specs,
        visual_artifacts=normalized.visual_artifacts,
    )


def _raw_slide_validation_summary(raw: Any, fallback: DeckSlideBrief) -> Dict[str, Any]:
    item = _safe_dict(raw.get("slide")) if isinstance(raw, dict) and isinstance(raw.get("slide"), dict) else _safe_dict(raw)
    visual_specs = item.get("visual_specs") or []
    required_sources = item.get("required_sources") or item.get("requiredSources") or []
    return {
        "raw_keys": list(item.keys())[:16],
        "has_key_message": bool(_clean_text(item.get("key_message") or item.get("keyMessage"))),
        "has_insight": bool(_clean_text(item.get("insight"))),
        "evidence_explanation_count": len(_compact_evidence_explanation(item.get("evidence_explanation") or item.get("evidenceExplanation"))),
        "has_visual_plan": bool(_clean_text(item.get("visual_plan") or item.get("visualPlan"))),
        "required_sources_count": len(required_sources) if isinstance(required_sources, list) else 0,
        "visual_specs_count": len(visual_specs) if isinstance(visual_specs, list) else 0,
        "target_index": int(fallback.index or 0),
    }


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
        "web_sources_enabled": request.web_sources_enabled,
        "source_ids": request.source_ids,
        "sources": _selected_sources_payload(request),
        "source_summary": _source_summary(request.source_ids, request.web_sources_enabled),
        "scope_brief": context_bundle["scope_brief"],
        "metric_context": context_bundle["metric_context"],
        "evidence_context": context_bundle["evidence_context"],
        "evidence_node_context": context_bundle["evidence_node_context"],
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
            source_summary=_clean_text(raw.get("source_summary")) or _source_summary(request.source_ids, request.web_sources_enabled),
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
            "source_summary": _source_summary(request.source_ids, request.web_sources_enabled),
            "scope_brief": context_bundle["scope_brief"],
            "metric_context": context_bundle["metric_context"],
            "evidence_context": context_bundle["evidence_context"],
            "evidence_node_context": context_bundle["evidence_node_context"],
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
            "web_sources_enabled": request.web_sources_enabled,
            "source_ids": request.source_ids,
            "sources": _selected_sources_payload(request),
            "source_summary": _source_summary(request.source_ids, request.web_sources_enabled),
            "scope_brief": context_bundle["scope_brief"],
            "metric_context": context_bundle["metric_context"],
            "evidence_context": context_bundle["evidence_context"],
            "evidence_node_context": context_bundle["evidence_node_context"],
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
    evidence_buckets = _validate_narrative_evidence_buckets(raw.get("evidence_buckets") or raw.get("evidenceBuckets"))
    bucket_ids = {bucket.id for bucket in evidence_buckets if bucket.id}
    slide_roles = _validate_narrative_slide_roles(raw.get("slide_roles") or raw.get("slideRoles"), outline, bucket_ids)
    if len(slide_roles) != len(outline):
        raise PptPlanningInvalidResponse("invalid_ppt_narrative_slide_roles")
    for role in slide_roles:
        if role.evidence_bucket and role.evidence_bucket not in bucket_ids:
            raise PptPlanningInvalidResponse("invalid_ppt_narrative_slide_roles")
    missing_inputs = raw.get("missing_inputs")
    if not isinstance(missing_inputs, list):
        missing_inputs = []
    response = DeckNarrativePlanResponse(
        storyline=_truncate_by_chars(raw.get("storyline"), 80),
        chapters=_validate_narrative_chapters(raw.get("chapters")),
        evidence_buckets=evidence_buckets,
        slide_roles=slide_roles,
        visual_rules=_validate_narrative_visual_rules(raw.get("visual_rules") or raw.get("visualRules")),
        missing_inputs=[_clean_text(item) for item in missing_inputs if _clean_text(item)],
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
        "web_sources_enabled": request.web_sources_enabled,
        "source_ids": request.source_ids,
        "sources": _selected_sources_payload(request),
        "source_summary": _source_summary(request.source_ids, request.web_sources_enabled),
        "scope_brief": context_bundle["scope_brief"],
        "metric_context": context_bundle["metric_context"],
        "evidence_context": context_bundle["evidence_context"],
        "evidence_node_context": context_bundle["evidence_node_context"],
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
        source_summary=_clean_text(raw.get("source_summary")) or _source_summary(request.source_ids, request.web_sources_enabled),
        missing_inputs=[_clean_text(item) for item in missing_inputs if _clean_text(item)],
        context_manifest=context_bundle,
    )
    _dump_generation_response("_last_ppt_deck_brief_response.json", response.model_dump(mode="json"))
    return response


async def create_deck_brief_job(request: DeckBriefRequest) -> DeckBriefJobCreateResponse:
    await _prune_deck_brief_jobs()
    job_id = f"ppt-deck-brief-{uuid.uuid4().hex[:12]}"
    now_iso = _utc_now_iso()
    async with _deck_brief_job_lock:
        _deck_brief_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": {"stage": "queued", "message": "brief 任务已创建"},
            "result": None,
            "error": {},
            "created_at": now_iso,
            "updated_at": now_iso,
            "created_ts": time.time(),
        }
    asyncio.create_task(_run_deck_brief_job(job_id, request))
    return DeckBriefJobCreateResponse(job_id=job_id, status="queued")


async def get_deck_brief_job(job_id: str) -> DeckBriefJobStatusResponse:
    await _prune_deck_brief_jobs()
    async with _deck_brief_job_lock:
        job = _deck_brief_jobs.get(str(job_id or ""))
        if not job:
            raise PptPlanningInvalidResponse("deck_brief_job_not_found", {
                "code": "deck_brief_job_not_found",
                "job_id": str(job_id or ""),
            })
        return _deck_brief_job_response(job)


async def regenerate_deck_brief_slide(request: DeckBriefSlideRequest) -> DeckSlideBrief:
    total_started = time.perf_counter()
    _ensure_llm_enabled()
    metric_context = build_metric_context(
        sources=request.sources,
        source_ids=request.source_ids,
        current={},
    )
    context_bundle = _build_ppt_context_bundle(request, metric_context=metric_context)
    outline = _validate_outline([item.model_dump(mode="json") for item in request.outline], request.spec.page_count if request.spec else request.page_count)
    page_no = int(request.page_no or (request.outline_item.page_no if request.outline_item else request.target.index))
    target_slide_role = _find_narrative_role(request.narrative_plan, page_no)
    brief_generation_context = _build_brief_generation_context(
        request,
        outline=outline,
        page_no=page_no,
        context_bundle=context_bundle,
        metric_context=metric_context,
    )
    page_context_packet = _safe_dict(brief_generation_context.get("page_context_packet"))
    user_payload = {
        "task": "ppt_directive_slide_regeneration",
        "area_id": request.area_id,
        "context_id": brief_generation_context["context_id"],
        "page_no": page_no,
        "revision_note": request.revision_note,
        "topic": request.topic,
        "audience": request.audience,
        "deck_type": request.deck_type,
        "page_count": brief_generation_context["page_count"],
        "source_ids": page_context_packet.get("recommended_source_ids") or request.source_ids,
        "sources": _selected_sources_payload(request),
        "source_summary": _source_summary(request.source_ids, request.web_sources_enabled),
        "scope_brief": context_bundle["scope_brief"],
        "metric_context": brief_generation_context["metric_context"],
        "evidence_context": brief_generation_context["evidence_context"],
        "evidence_node_context": brief_generation_context["evidence_node_context"],
        "source_manifest": brief_generation_context["source_manifest"],
        "brief_generation_context": {
            "deck_id": brief_generation_context["deck_id"],
            "context_id": brief_generation_context["context_id"],
            "page_count": brief_generation_context["page_count"],
            "deck_progress_summary": brief_generation_context["deck_progress_summary"],
            "metric_index": brief_generation_context["metric_index"],
            "evidence_index": brief_generation_context["evidence_index"],
            "page_context_packet": page_context_packet,
        },
        "spec": request.spec.model_dump(mode="json") if request.spec else None,
        "outline": [item.model_dump(mode="json") for item in request.outline],
        "outline_item": request.outline_item.model_dump(mode="json") if request.outline_item else None,
        "previous_slide_summary": page_context_packet.get("previous_slide_summary") or {},
        "next_outline_summary": page_context_packet.get("next_outline_summary") or {},
        "narrative_plan": request.narrative_plan.model_dump(mode="json") if request.narrative_plan else None,
        "target_slide_role": target_slide_role,
        "target": request.target.model_dump(mode="json"),
    }
    raw: Dict[str, Any] = {}
    payload_bytes = len(json.dumps(user_payload, ensure_ascii=False).encode("utf-8"))
    last_json_error: Dict[str, Any] = {}
    repaired_once = False
    retried_generation = False
    for attempt in range(2):
        attempt_started = time.perf_counter()
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
            logger.info(
                "PPT directive slide LLM completed %s",
                {
                    "page_no": page_no,
                    "attempt": attempt + 1,
                    "payload_bytes": payload_bytes,
                    "llm_ms": round((time.perf_counter() - attempt_started) * 1000, 2),
                    "retried_generation": retried_generation,
                    "repaired_once": repaired_once,
                    "result": "ok",
                },
            )
            break
        except json.JSONDecodeError as exc:
            last_json_error = _json_error_summary(exc)
            bad_json = str(getattr(exc, "text", "") or getattr(exc, "doc", "") or "")
            if not repaired_once and bad_json.strip():
                repair_started = time.perf_counter()
                try:
                    raw = await _repair_ppt_json_object(
                        bad_json=bad_json,
                        parse_error=last_json_error,
                        schema_summary={
                            "required_fields": [
                                "index",
                                "title",
                                "purpose",
                                "key_message",
                                "insight",
                                "evidence_explanation",
                                "visual_plan",
                                "required_sources",
                                "metric_claims",
                                "metric_gaps",
                                "visual_specs",
                            ],
                            "visual_types": ["figure", "diagram", "matrix", "existing_asset", "table", "metric_card"],
                        },
                        reasoning_id=f"ppt-directive-slide-{request.target.index}-json-repair",
                    )
                    repaired_once = True
                    logger.info(
                        "PPT directive slide JSON repaired %s",
                        {
                            "page_no": page_no,
                            "attempt": attempt + 1,
                            "repair_ms": round((time.perf_counter() - repair_started) * 1000, 2),
                            "json_error": {k: v for k, v in last_json_error.items() if k != "snippet"},
                            "result": "repaired",
                        },
                    )
                    break
                except Exception as repair_exc:
                    last_json_error = {
                        **last_json_error,
                        "repair_error": str(repair_exc),
                    }
                    logger.warning(
                        "PPT directive slide JSON repair failed page=%s",
                        page_no,
                        extra={"ppt_json_error": {k: v for k, v in last_json_error.items() if k != "snippet"}},
                        exc_info=True,
                    )
            if attempt >= 1:
                raise PptPlanningInvalidResponse(
                    "ppt_planning_llm_invalid_response",
                    detail={
                        "code": "ppt_planning_llm_invalid_response",
                        "page_no": page_no,
                        "json_error": last_json_error,
                        "repaired": repaired_once,
                        "retried": retried_generation,
                    },
                ) from exc
            retried_generation = True
            logger.warning(
                "PPT directive slide returned invalid JSON; retrying once page=%s",
                request.target.index,
                exc_info=True,
            )
    validate_started = time.perf_counter()
    slide = _validate_slide_section(raw, request.target, metric_context=metric_context, visual_assets=_visual_assets_from_request(request))
    content_retry_attempted = False
    content_retry_ms = 0.0
    if not slide:
        validation_summary = _raw_slide_validation_summary(raw, request.target)
        retry_started = time.perf_counter()
        content_retry_attempted = True
        try:
            raw = await _invoke_ppt_json_role(
                system_prompt=DECK_BRIEF_SLIDE_SYSTEM_PROMPT,
                user_payload={
                    **user_payload,
                    "retry_instruction": (
                        "上一轮 JSON 合法但缺少逐页 brief 必要内容。请只基于 brief_generation_context.page_context_packet "
                        "补齐目标页，不要输出目录半成品；必须包含 key_message、insight、evidence_explanation、visual_plan、required_sources，"
                        "并按需要给出 metric_claims/metric_gaps/visual_specs。"
                    ),
                    "invalid_response_summary": validation_summary,
                },
                emit=None,
                phase="ppt_directive_slide_content_retry",
                title="补齐 PPT 指令页",
                reasoning_id=f"ppt-directive-slide-{request.target.index}-content-retry",
            )
            content_retry_ms = (time.perf_counter() - retry_started) * 1000
            slide = _validate_slide_section(raw, request.target, metric_context=metric_context, visual_assets=_visual_assets_from_request(request))
        except json.JSONDecodeError as exc:
            content_retry_ms = (time.perf_counter() - retry_started) * 1000
            last_json_error = _json_error_summary(exc)
        if slide:
            logger.info(
                "PPT directive slide content retry completed %s",
                {
                    "page_no": page_no,
                    "payload_bytes": payload_bytes,
                    "retry_ms": round(content_retry_ms, 2),
                    "result": "ok",
                },
            )
        else:
            retry_summary = _raw_slide_validation_summary(raw, request.target)
            missing_fields = []
            if not retry_summary.get("has_key_message"):
                missing_fields.append("key_message")
            if not retry_summary.get("has_insight"):
                missing_fields.append("insight")
            if not retry_summary.get("has_visual_plan"):
                missing_fields.append("visual_plan")
            if retry_summary.get("required_sources_count", 0) <= 0:
                missing_fields.append("required_sources")
            if retry_summary.get("visual_specs_count", 0) <= 0:
                missing_fields.append("visual_specs")
            logger.warning(
                "PPT directive slide validation failed %s",
                {
                    "page_no": page_no,
                    "payload_bytes": payload_bytes,
                    "error_kind": "missing_required_brief_content",
                    "repaired": repaired_once,
                    "retried": retried_generation,
                    "content_retried": content_retry_attempted,
                    "content_retry_ms": round(content_retry_ms, 2),
                    **retry_summary,
                },
            )
            raise PptPlanningInvalidResponse(
                "invalid_deck_brief_slide",
                detail={
                    "code": "invalid_deck_brief_slide",
                    "page_no": page_no,
                    "reason": "missing_required_brief_content",
                    "missing_fields": missing_fields,
                    "payload_bytes": payload_bytes,
                    "repaired": repaired_once,
                    "retried": retried_generation,
                    "content_retried": content_retry_attempted,
                },
            )
    logger.info(
        "PPT directive slide validated %s",
        {
            "page_no": page_no,
            "payload_bytes": payload_bytes,
            "validate_ms": round((time.perf_counter() - validate_started) * 1000, 2),
            "total_ms": round((time.perf_counter() - total_started) * 1000, 2),
            "repaired": repaired_once,
            "retried": retried_generation,
            "result": "ok",
        },
    )
    return slide
