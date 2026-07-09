from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.ops import polygonize, unary_union
from shapely.prepared import prep

from modules.evidence_retrieval import (
    attachment_source_id,
    attachment_source_kind,
    evidence_node_from_attachment_chunk,
    evidence_node_from_document_index_node,
    evidence_node_payloads_from_nodes,
    evidence_nodes_from_package,
)
from modules.evidence_index import SOURCE_INDEX_MANIFEST_ARTIFACT_TYPE, attach_index_manifest, build_source_index_manifest_payload, persist_source_index_manifest
from modules.agent.providers.llm_provider import _invoke_json_role, is_llm_enabled
from modules.population.service import get_population_grid
from modules.ppt_database.service import list_persisted_database_sources
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84, wgs84_to_gcj02
from modules.retrieval.attachments import list_attachments, read_attachment_chunks
from modules.retrieval.schemas import AttachmentRecord
from store.ai_database import SessionLocal as AiSessionLocal
from store.ai_models import Document, DocumentIndexNode
from store.analysis_artifact_repo import analysis_artifact_repo
from store.history_repo import history_repo

from .schemas import (
    PptDataPackageRequest,
    PptDataPackageResponse,
    PptDataSourceSummary,
    PptEvidenceIntentGroup,
    PptEvidenceIntentPlan,
    PptEvidenceQuery,
    PptPoiNearbyRequest,
    PptPoiPoint,
    PptPoiQueryRequest,
    PptPoiQueryResponse,
    PptSource,
)


class PptDataAreaNotFound(RuntimeError):
    pass


class PptDataSourceNotFound(RuntimeError):
    pass


class PptDataIntentLlmUnavailable(RuntimeError):
    pass


class PptDataInvalidIntentPlan(RuntimeError):
    pass


logger = logging.getLogger(__name__)
PPT_DATA_PACKAGE_DIR = Path("runtime") / "ppt-data-packages"
PPT_DATA_PACKAGE_ARTIFACT_TYPE = "ppt_data_package"
PPT_WEB_SOURCE_ARTIFACT_TYPE = "ppt_web_source"
PPT_DATABASE_ARTIFACT_TYPE = "ppt_database_package"


def _safe_filename(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return "unknown"
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in text)[:96].strip("-") or "unknown"


def _normalize_ppt_package_response_for_artifact(request: PptDataPackageRequest, response: PptDataPackageResponse) -> PptDataPackageResponse:
    payload = response.model_dump(mode="json")
    source = _safe_dict(payload.get("source"))
    meta = _safe_dict(source.get("meta"))
    package = _safe_dict(meta.get("package"))
    area_id = _clean_text(request.area_id)
    package_version = _clean_text(request.package_version or package.get("package_version") or meta.get("packageVersion"))
    package = {
        **package,
        "area_id": area_id,
        "package_version": package_version,
    }
    meta = {
        **meta,
        "sourceKind": "package",
        "areaId": area_id,
        "packageVersion": package_version,
        "package": package,
    }
    source = {
        **source,
        "status": _clean_text(source.get("status")) or "ready",
        "selected": bool(source.get("selected", True)),
        "meta": meta,
    }
    payload["source"] = source
    return PptDataPackageResponse.model_validate(payload)


def _ppt_package_artifact_params(request: PptDataPackageRequest, response: PptDataPackageResponse) -> Dict[str, Any]:
    package = _safe_dict(_safe_dict(response.source.meta).get("package"))
    source_ids = sorted(_clean_text(item) for item in _safe_list(package.get("source_ids") or request.source_ids) if _clean_text(item))
    return {
        "package_mode": _clean_text(package.get("package_mode") or request.package_mode) or "evidence",
        "intent": _clean_text(package.get("intent") or request.intent),
        "source_ids": source_ids,
        "package_version": _clean_text(package.get("package_version") or request.package_version),
    }


def _ppt_package_artifact_summary(response: PptDataPackageResponse) -> Dict[str, Any]:
    source = response.source
    meta = _safe_dict(source.meta)
    package = _safe_dict(meta.get("package"))
    source_payload = source.model_dump(mode="json")
    return {
        "id": _clean_text(source.id),
        "title": _clean_text(source.title or package.get("title")),
        "label": _clean_text(meta.get("label") or response.summary),
        "source_ids": [_clean_text(item) for item in _safe_list(package.get("source_ids")) if _clean_text(item)],
        "package_version": _clean_text(package.get("package_version") or meta.get("packageVersion")),
        "item_count": int(package.get("total") or source_payload.get("count") or len(response.items) or 0),
    }


def _persist_ppt_data_package_response(request: PptDataPackageRequest, response: PptDataPackageResponse) -> PptDataPackageResponse:
    response = _normalize_ppt_package_response_for_artifact(request, response)
    payload = response.model_dump(mode="json")
    area_id = _clean_text(request.area_id)
    if area_id:
        try:
            analysis_artifact_repo.upsert(
                history_id=area_id,
                artifact_type=PPT_DATA_PACKAGE_ARTIFACT_TYPE,
                params=_ppt_package_artifact_params(request, response),
                payload=payload,
                summary=_ppt_package_artifact_summary(response),
                data_version="v1",
            )
            persist_source_index_manifest(area_id, response.source)
        except Exception:
            logger.exception("PPT data package artifact persist failed")
    return response


def _write_ppt_data_package_debug_dump(response: PptDataPackageResponse) -> PptDataPackageResponse:
    try:
        payload = response.model_dump(mode="json")
        source = _safe_dict(payload.get("source"))
        meta = _safe_dict(source.get("meta"))
        package = _safe_dict(meta.get("package"))
        area_id = _clean_text(package.get("area_id"))
        source_id = _clean_text(source.get("id") or package.get("id"))
        package_mode = _clean_text(package.get("package_mode")) or "package"
        if not source_id:
            return response
        area_dir = PPT_DATA_PACKAGE_DIR / _safe_filename(area_id or "global")
        area_dir.mkdir(parents=True, exist_ok=True)
        package_path = area_dir / f"{_safe_filename(source_id)}.json"
        package_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        latest_path = area_dir / f"_latest_{_safe_filename(package_mode)}.json"
        latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("PPT data package persisted to %s", package_path.as_posix())
    except Exception:
        pass
    return response


SYSTEM_SOURCE_TITLES = {
    "current:scope": "当前等时圈范围",
    "current:dataset:h3": "H3 / 共享网格",
    "current:dataset:poi": "POI 基础数据",
    "current:analysis:poi_h3": "POI / H3 空间结构分析",
    "current:analysis:nightlight": "夜光强度分析",
    "current:analysis:population": "人口结构分析",
    "current:analysis:road": "路网与可达性分析",
}

ARTIFACT_SOURCE_TYPES = {
    "current:dataset:h3": "poi_h3_grid",
    "current:analysis:poi_h3": "poi_h3_grid",
    "current:analysis:population": "population",
    "current:analysis:nightlight": "nightlight",
    "current:analysis:road": "road_syntax",
}

TYPE_MAP_PATH = Path(__file__).resolve().parents[2] / "share" / "type_map.json"
_TYPE_CODE_LABELS: Dict[str, Dict[str, str]] | None = None
DEFAULT_EVIDENCE_INTENT = "为 PPT 指令生成整理当前区域代表性 POI 资料"
NIGHTLIFE_EVIDENCE_INTENT = "整理夜生活与夜间消费相关 POI，并与夜光格子对应"
CARRIER_EVIDENCE_INTENT = "识别当前区域 POI、路网、人口、夜光共同支撑的空间载体"
CARRIER_REQUIRED_SOURCE_IDS = {"current:dataset:poi", "current:analysis:road", "current:analysis:population", "current:analysis:nightlight"}
CARRIER_PACKAGE_TITLE = "POI × 路网空间载体资料包"
CARRIER_BOUNDARY_BUFFER_M = 50.0
BLOCK_LOOP_MIN_AREA_KM2 = 0.002
BLOCK_LOOP_MAX_AREA_KM2 = 8.0
CARRIER_MAX_BLOCK_LOOPS = 8
CARRIER_MAX_CORRIDORS = 6
CARRIER_MAX_SEGMENTS = 8
CARRIER_REPRESENTATIVE_POI_LIMIT = 3
CARRIER_MIN_BLOCK_LOOP_ROADS = 4
CARRIER_MIN_CORRIDOR_ROADS = 2
CARRIER_MIN_CORRIDOR_LENGTH_M = 160.0
CARRIER_MIN_COMPACTNESS = 0.04
CARRIER_MIN_SHORT_AXIS_M = 35.0
NIGHTLIFE_QUERY_TERMS = [
    "酒吧",
    "夜店",
    "KTV",
    "影院",
    "电影院",
    "剧场",
    "夜宵",
    "烧烤",
    "火锅",
    "餐吧",
    "茶馆",
    "咖啡",
    "娱乐",
    "网吧",
    "足浴",
    "按摩",
]
NIGHTLIFE_CATEGORY_LABELS = ["餐饮", "体育", "购物", "生活服务"]
NIGHTLIFE_CORE_TYPECODES = ["080300", "080500", "080600", "050500", "050600", "050700", "061000", "060200"]
NIGHTLIFE_STRONG_TERMS = [
    "酒吧",
    "夜店",
    "KTV",
    "ktv",
    "影院",
    "电影院",
    "影城",
    "剧场",
    "夜宵",
    "烧烤",
    "烤肉",
    "火锅",
    "餐吧",
    "清吧",
    "茶馆",
    "茶艺",
    "茶饮",
    "奶茶",
    "咖啡",
    "网吧",
    "棋牌",
    "桌游",
    "足浴",
    "按摩",
    "24小时",
    "24h",
]
NIGHTLIFE_EXCLUDED_TERMS = [
    "五金",
    "建材",
    "批发",
    "专卖店",
    "土鸡土鸭",
    "大闸蟹",
    "生鲜",
    "菜市场",
    "综合市场",
    "超级市场",
]
NIGHTLIFE_NEAREST_CELL_TOLERANCE_M = 30.0
PPT_DOCUMENT_INDEX_PREVIEW_LIMIT = 10


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _ai_payload_evidence_count(ai_payload: Dict[str, Any]) -> int:
    payload = _safe_dict(ai_payload)
    evidence_nodes = _safe_list(payload.get("evidence_nodes"))
    return len(evidence_nodes)


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _normalize_type_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def _typecode_matches(point_typecode: Any, filter_typecode: Any) -> bool:
    point_code = _normalize_type_code(point_typecode)
    filter_code = _normalize_type_code(filter_typecode)
    if not point_code or not filter_code:
        return False
    if point_code.startswith(filter_code):
        return True
    if len(filter_code) == 6 and filter_code.endswith("00"):
        return point_code.startswith(filter_code[:4])
    return False


def _load_type_code_labels() -> Dict[str, Dict[str, str]]:
    global _TYPE_CODE_LABELS
    if _TYPE_CODE_LABELS is not None:
        return _TYPE_CODE_LABELS
    labels: Dict[str, Dict[str, str]] = {}
    try:
        payload = json.loads(TYPE_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        _TYPE_CODE_LABELS = labels
        return labels
    for group in _safe_list(_safe_dict(payload).get("groups")):
        group_payload = _safe_dict(group)
        category = _clean_text(group_payload.get("title"))
        for item in _safe_list(group_payload.get("items")):
            item_payload = _safe_dict(item)
            subcategory = _clean_text(item_payload.get("label"))
            for raw_code in _clean_text(item_payload.get("types")).replace("|", ",").split(","):
                code = _normalize_type_code(raw_code)
                if code:
                    labels[code] = {
                        "category": category,
                        "subcategory": subcategory,
                    }
    _TYPE_CODE_LABELS = labels
    return labels


def _resolve_type_labels(typecode: str) -> Dict[str, str]:
    normalized = _normalize_type_code(typecode)
    if not normalized:
        return {}
    labels = _load_type_code_labels()
    if normalized in labels:
        return labels[normalized]
    for code, payload in labels.items():
        if normalized.startswith(code) or normalized[:2] == code[:2]:
            return payload
    return {}


def _available_category_payload() -> Dict[str, List[str]]:
    labels = _load_type_code_labels()
    categories = sorted({payload.get("category", "") for payload in labels.values() if payload.get("category")})
    subcategories = sorted({payload.get("subcategory", "") for payload in labels.values() if payload.get("subcategory")})
    return {
        "categories": categories,
        "subcategories": subcategories,
    }


def _normalize_taxonomy_values(values: List[str], available_values: List[str]) -> tuple[List[str], List[Dict[str, str]]]:
    available = [_clean_text(item) for item in available_values if _clean_text(item)]
    normalized: List[str] = []
    repairs: List[Dict[str, str]] = []
    for raw_value in values:
        value = _clean_text(raw_value)
        if not value:
            continue
        match = next((item for item in available if item == value), "")
        if not match:
            match = next((item for item in available if item in value or value in item), "")
        if match:
            if match not in normalized:
                normalized.append(match)
            if match != value:
                repairs.append({"from": value, "to": match})
    return normalized, repairs


def _haversine_meters(a: List[float], b: List[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return math.inf
    lng1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lng2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    d_lng = lng2 - lng1
    d_lat = lat2 - lat1
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _normalize_lng_lat_pair(value: Any) -> List[float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return []
    try:
        lng = float(value[0])
        lat = float(value[1])
    except (TypeError, ValueError):
        return []
    if not math.isfinite(lng) or not math.isfinite(lat):
        return []
    if lng < -180 or lng > 180 or lat < -90 or lat > 90:
        return []
    return [lng, lat]


def _normalize_history_center(value: Any, coord_type: str = "") -> List[float]:
    center = _normalize_lng_lat_pair(value)
    if not center:
        return []
    normalized_type = _clean_text(coord_type).lower()
    if normalized_type in {"gcj02", "gcj-02", "amap", "gaode"}:
        try:
            lng, lat = gcj02_to_wgs84(center[0], center[1])
            return [float(lng), float(lat)]
        except Exception:
            return center
    return center


def _normalize_package_request_center(request: PptDataPackageRequest) -> PptDataPackageRequest:
    center = _normalize_history_center(request.center, request.center_coord_type)
    if center == list(request.center or []) and _clean_text(request.center_coord_type).lower() == "wgs84":
        return request
    return request.model_copy(update={
        "center": center,
        "center_coord_type": "wgs84" if center else "",
    })


def _load_history_detail(area_id: str) -> Dict[str, Any]:
    normalized = _clean_text(area_id)
    if not normalized:
        raise PptDataAreaNotFound("area_id_required")
    detail = history_repo.get_detail(normalized, include_pois=False)
    if not detail:
        raise PptDataAreaNotFound("area_not_found")
    return detail


def _load_history_pois(area_id: str, year: Optional[int] = None) -> Dict[str, Any]:
    normalized = _clean_text(area_id)
    if not normalized:
        raise PptDataAreaNotFound("area_id_required")
    payload = history_repo.get_pois(normalized, year=year)
    if not payload:
        raise PptDataAreaNotFound("area_not_found")
    return payload


def _latest_artifact(area_id: str, artifact_type: str) -> Dict[str, Any]:
    artifacts = analysis_artifact_repo.list(area_id, artifact_type=artifact_type)
    if not artifacts:
        return {}
    return _safe_dict(artifacts[0])


def _latest_artifact_payload(area_id: str, artifact_type: str) -> Dict[str, Any]:
    return _safe_dict(_latest_artifact(area_id, artifact_type).get("payload"))


def _artifact_ready(area_id: str, source_id: str) -> bool:
    artifact_type = ARTIFACT_SOURCE_TYPES.get(source_id)
    if not artifact_type:
        return False
    return bool(analysis_artifact_repo.list(area_id, artifact_type=artifact_type))


def _source_label(source_id: str, ready: bool, count: int = 0) -> str:
    if source_id == "current:dataset:poi" and count:
        return f"POI {count} 条"
    return "已生成" if ready else "待生成"


def _document_source_status(document: Document) -> str:
    status = _clean_text(document.status)
    if status == "failed":
        return "failed"
    if status == "parsed":
        return "ready"
    return "pending"


def _document_source_label(document: Document, index_count: int = 0) -> str:
    status = _clean_text(document.status)
    if index_count > 0:
        return f"章节 {index_count} 个"
    if status == "failed":
        return "解析失败"
    if status in {"uploaded", "parsing"}:
        return "待解析"
    if status == "parsed":
        return "待生成结构"
    return "待处理"


def _document_source_availability(status: str, index_count: int = 0) -> str:
    normalized = _clean_text(status)
    if normalized == "failed":
        return "failed:document_parse_failed"
    if normalized in {"uploaded", "parsing"}:
        return "building:document_parse_pending"
    if normalized == "parsed" and index_count <= 0:
        return "empty_evidence:pageindex_empty"
    if normalized == "parsed":
        return "available"
    return "pending:document_not_ready"


def _document_locator_summary(document: Document, index_preview: List[Dict[str, Any]], index_count: int = 0) -> str:
    file_name = _clean_text(document.file_name)
    page_values = [
        int(item.get("page_start") or 0)
        for item in index_preview
        if int(item.get("page_start") or 0) > 0
    ]
    if page_values:
        return f"{file_name or '文档'} / 第 {min(page_values)}-{max(page_values)} 页 / PageIndex {index_count} 节"
    if index_count > 0:
        return f"{file_name or '文档'} / PageIndex {index_count} 节"
    return file_name or "文档"


def _package_locator_summary(package: Dict[str, Any], fallback: str = "") -> str:
    source_ids = [_clean_text(item) for item in _safe_list(package.get("source_ids")) if _clean_text(item)]
    version = _clean_text(package.get("package_version"))
    total = package.get("total")
    parts = []
    if version:
        parts.append(version)
    if source_ids:
        parts.append(f"依赖来源 {len(source_ids)} 个")
    if total not in (None, ""):
        parts.append(f"结果 {total} 条")
    return " / ".join(parts) or _clean_text(fallback)


def _evidence_availability(status: str, evidence_count: int, *, empty_reason: str = "empty_evidence") -> str:
    normalized = _clean_text(status)
    if normalized == "failed":
        return "failed"
    if normalized in {"pending", "generating"}:
        return "building" if normalized == "generating" else "pending"
    if evidence_count <= 0:
        return empty_reason
    return "available"


def _compact_document_index_node(node: DocumentIndexNode) -> Dict[str, Any]:
    return {
        "node_id": _clean_text(node.node_id),
        "parent_node_id": _clean_text(node.parent_node_id),
        "title": _clean_text(node.title),
        "level": int(node.level or 0),
        "summary": _clean_text(node.summary)[:320],
        "text": _clean_text(node.text)[:1200],
        "page_start": int(node.page_start or 1),
        "page_end": int(node.page_end or node.page_start or 1),
    }


def _document_ai_payload(source_id: str, title: str, index_preview: List[Dict[str, Any]], *, count: int = 0) -> Dict[str, Any]:
    nodes = [
        evidence_node
        for index, item in enumerate(index_preview[:40], start=1)
        for evidence_node in [evidence_node_from_document_index_node(source_id, title, item, index=index)]
        if evidence_node is not None
    ]
    evidence_nodes = evidence_node_payloads_from_nodes(nodes)
    payload = {
        "version": "ppt_ai_input_block_v1",
        "source_id": source_id,
        "title": title,
        "source_kind": "document",
        "included": ["evidence"] if evidence_nodes else [],
        "scope": None,
        "metrics": [],
        "metric_gaps": [],
        "evidence_nodes": evidence_nodes,
        "visual_specs": [],
        "excluded": [{"type": "document_full_text", "reason": "不传文档全文，只传 PageIndex 节点/章节摘要。", "count": int(count or len(index_preview) or 0)}],
        "counts": {"scope": 0, "metrics": 0, "metric_gaps": 0, "evidence": len(evidence_nodes), "visual_specs": 0},
        "policy": "文档来源只通过 PageIndex 节点/章节摘要进入 evidence；不从全文临时抽取。",
    }
    return attach_index_manifest(
        payload,
        build_source_index_manifest_payload(
            source_id=source_id,
            source_kind="document",
            native_index_kind="pageindex",
            node_count=len(evidence_nodes),
            retrieval_modes=["structure", "keyword"],
            read_modes=["node_id", "page"],
            storage_ref={"source_id": source_id, "index_preview_count": len(index_preview), "pageindex_count": int(count or len(index_preview) or 0)},
            model_versions={"parser": "docling", "indexer": "pageindex"},
        ),
    )


def _package_ai_payload(source_id: str, title: str, package: Dict[str, Any]) -> Dict[str, Any]:
    nodes = evidence_nodes_from_package(source_id, title, package)
    evidence_nodes = evidence_node_payloads_from_nodes(nodes)
    payload = {
        "version": "ppt_ai_input_block_v1",
        "source_id": source_id,
        "title": title,
        "source_kind": "package",
        "included": ["evidence"] if evidence_nodes else [],
        "scope": None,
        "metrics": [],
        "metric_gaps": [],
        "evidence_nodes": evidence_nodes,
        "visual_specs": [],
        "excluded": [
            {"type": "package_full_items", "reason": "不传资料包完整 POI 明细，只传摘要和代表样本。", "count": len(_safe_list(package.get("items")))},
            {"type": "package_carrier_geometries", "reason": "不传载体完整 geometry，只传载体摘要和指标摘要。", "count": len(_safe_list(package.get("carriers")))},
        ],
        "counts": {"scope": 0, "metrics": 0, "metric_gaps": 0, "evidence": len(evidence_nodes), "visual_specs": 0},
        "policy": "资料包来源只通过 EvidenceNode 派生的摘要、代表样本、载体摘要进入 evidence；不传完整明细。",
    }
    return attach_index_manifest(
        payload,
        build_source_index_manifest_payload(
            source_id=source_id,
            source_kind="package",
            native_index_kind="spatial_package_index",
            node_count=len(evidence_nodes),
            retrieval_modes=["keyword", "structured"],
            read_modes=["node_id", "carrier_id", "item_id", "locator"],
            storage_ref={"package_id": _clean_text(package.get("id")) or source_id, "package_mode": _clean_text(package.get("package_mode"))},
            diagnostics=[] if evidence_nodes else ["package_evidence_empty"],
        ),
    )


def _image_attachment_status(record: AttachmentRecord) -> str:
    status = _clean_text(record.status)
    if status == "ready":
        return "ready"
    if status == "failed":
        return "failed"
    if status == "processing":
        return "generating"
    return "pending"


def _image_attachment_availability(record: AttachmentRecord, evidence_count: int = 0) -> str:
    status = _clean_text(record.status)
    if status == "ready" and evidence_count > 0:
        return "available"
    if status == "ready":
        return "empty_evidence:image_parse_empty"
    if status == "failed":
        return f"failed:{_clean_text(record.error) or 'image_parse_failed'}"
    if status == "processing":
        return "building:image_parse_pending"
    return "pending:image_uploaded"


def _image_attachment_ai_payload(record: AttachmentRecord, source_id: str, title: str) -> Dict[str, Any]:
    chunks = [
        chunk
        for chunk in read_attachment_chunks(record)
        if attachment_source_kind(chunk.filename, _safe_dict(chunk.metadata).get("mime_type") or record.mime_type) == "image"
    ]
    nodes = [evidence_node_from_attachment_chunk(chunk, source_id=source_id) for chunk in chunks[:40]]
    evidence_nodes = evidence_node_payloads_from_nodes(nodes)
    payload = {
        "version": "ppt_ai_input_block_v1",
        "source_id": source_id,
        "title": title,
        "source_kind": "image",
        "included": ["evidence"] if evidence_nodes else [],
        "scope": None,
        "metrics": [],
        "metric_gaps": [],
        "evidence_nodes": evidence_nodes,
        "visual_specs": [],
        "excluded": [{"type": "image_binary", "reason": "不直接传图片二进制，只传 OCR、图像描述和视觉理解生成的证据节点。"}],
        "counts": {"scope": 0, "metrics": 0, "metric_gaps": 0, "evidence": len(evidence_nodes), "visual_specs": 0},
        "policy": "图片来源只通过 OCR、caption、visual_analysis 等 EvidenceNode 进入生成；视觉判断需保留来源和置信度。",
    }
    return attach_index_manifest(
        payload,
        build_source_index_manifest_payload(
            source_id=source_id,
            source_kind="image",
            native_index_kind="image_visual_index",
            node_count=len(evidence_nodes),
            retrieval_modes=["keyword", "vector"],
            read_modes=["node_id", "attachment_id", "locator", "bbox"],
            storage_ref={"attachment_id": record.attachment_id, "working_dir": record.working_dir},
            model_versions={"ocr_layout": "paddleocr_ppstructure_target", "image_text_embedding": "openclip_target", "vector_store": "qdrant_target"},
            diagnostics=[] if evidence_nodes else ["image_evidence_empty"],
        ),
    )


def _attach_package_ai_payload(source: PptSource) -> PptSource:
    meta = _safe_dict(source.meta)
    package = _safe_dict(meta.get("package"))
    ai_payload = _package_ai_payload(source.id, source.title, package)
    source.meta = {
        **meta,
        "aiPayload": ai_payload,
        "ai_payload": ai_payload,
    }
    source.source_kind = "package"
    source.summary = source.summary or _clean_text(package.get("summary") or meta.get("label"))
    source.evidence_count = _ai_payload_evidence_count(ai_payload)
    source.locator_summary = _package_locator_summary(package, _clean_text(meta.get("label")))
    source.availability = _evidence_availability(source.status, source.evidence_count, empty_reason="empty_evidence:package_empty")
    return source


def _list_document_ppt_sources() -> List[PptDataSourceSummary]:
    try:
        session = AiSessionLocal()
    except Exception:
        return []
    try:
        documents = (
            session.query(Document)
            .order_by(Document.upload_time.desc(), Document.id.desc())
            .all()
        )
        sources: List[PptDataSourceSummary] = []
        for document in documents:
            index_rows = (
                session.query(DocumentIndexNode)
                .filter_by(document_id=document.id)
                .order_by(DocumentIndexNode.ordinal.asc(), DocumentIndexNode.id.asc())
                .all()
            )
            index_count = len([node for node in index_rows if _clean_text(node.node_id) != "root"])
            status = _document_source_status(document)
            label = _document_source_label(document, index_count)
            index_preview = [
                _compact_document_index_node(node)
                for node in index_rows
                if _clean_text(node.node_id) != "root"
            ][:PPT_DOCUMENT_INDEX_PREVIEW_LIMIT]
            source_id = f"document:{document.id}"
            title = _clean_text(document.title) or _clean_text(document.file_name) or "文档资料"
            ai_payload = _document_ai_payload(source_id, title, index_preview, count=index_count) if status == "ready" else {}
            evidence_count = _ai_payload_evidence_count(ai_payload)
            sources.append(
                PptDataSourceSummary(
                    id=source_id,
                    type="document",
                    title=title,
                    status=status,
                    summary=label,
                    count=index_count,
                    source_kind="document",
                    evidence_count=evidence_count,
                    locator_summary=_document_locator_summary(document, index_preview, index_count),
                    availability=_document_source_availability(_clean_text(document.status), evidence_count),
                    meta={
                        "label": label,
                        "sourceKind": "document",
                        "document": {
                            "id": _clean_text(document.id),
                            "title": _clean_text(document.title),
                            "file_name": _clean_text(document.file_name),
                            "file_type": _clean_text(document.file_type),
                            "document_role": _clean_text(document.document_role),
                            "status": _clean_text(document.status),
                            "index_count": index_count,
                        },
                        "document_index_preview": index_preview,
                        "aiPayload": ai_payload,
                        "ai_payload": ai_payload,
                    },
                )
            )
        return sources
    except Exception:
        return []
    finally:
        session.close()


def _list_persisted_ppt_package_sources(area_id: str) -> List[PptDataSourceSummary]:
    sources: List[PptDataSourceSummary] = []
    seen: set[str] = set()
    for artifact in analysis_artifact_repo.list(area_id, artifact_type=PPT_DATA_PACKAGE_ARTIFACT_TYPE):
        payload = _safe_dict(artifact.get("payload"))
        source = _safe_dict(payload.get("source"))
        source_id = _clean_text(source.get("id"))
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        meta = _safe_dict(source.get("meta"))
        package = _safe_dict(meta.get("package"))
        package_version = _clean_text(package.get("package_version") or meta.get("packageVersion"))
        label = _clean_text(meta.get("label") or package.get("label") or payload.get("summary")) or "已构建资料包"
        count = int(package.get("item_count") or source.get("count") or len(_safe_list(payload.get("items"))) or 0)
        title = _clean_text(source.get("title") or package.get("title") or package.get("package_title")) or "资料包"
        package = {
            **package,
            "area_id": _clean_text(area_id),
            "package_version": package_version,
        }
        ai_payload = _package_ai_payload(source_id, title, package)
        evidence_count = _ai_payload_evidence_count(ai_payload)
        sources.append(
            PptDataSourceSummary(
                id=source_id,
                type=_clean_text(source.get("type")) or "package",
                title=title,
                status="ready",
                summary=label,
                count=count,
                source_kind="package",
                evidence_count=evidence_count,
                locator_summary=_package_locator_summary(package, label),
                availability=_evidence_availability("ready", evidence_count, empty_reason="empty_evidence:package_empty"),
                meta={
                    **meta,
                    "label": label,
                    "sourceKind": "package",
                    "areaId": _clean_text(area_id),
                    "packageVersion": package_version,
                    "persistedPackage": True,
                    "package": package,
                    "aiPayload": ai_payload,
                    "ai_payload": ai_payload,
                },
            )
        )
    return sources


def _list_persisted_database_ppt_sources(area_id: str) -> List[PptDataSourceSummary]:
    return [PptDataSourceSummary.model_validate(item) for item in list_persisted_database_sources(area_id)]


def _list_image_attachment_ppt_sources(conversation_id: str) -> List[PptDataSourceSummary]:
    normalized_conversation_id = _clean_text(conversation_id)
    if not normalized_conversation_id:
        return []
    sources: List[PptDataSourceSummary] = []
    for record in list_attachments(normalized_conversation_id):
        if attachment_source_kind(record.filename, record.mime_type) != "image":
            continue
        source_id = attachment_source_id(record.attachment_id, record.filename, record.mime_type)
        title = _clean_text(record.filename) or "图片来源"
        status = _image_attachment_status(record)
        ai_payload = _image_attachment_ai_payload(record, source_id, title) if status == "ready" else {}
        evidence_count = _ai_payload_evidence_count(ai_payload)
        sources.append(
            PptDataSourceSummary(
                id=source_id,
                type="image",
                title=title,
                status=status,
                summary=_clean_text(record.summary) or ("图片解析完成" if status == "ready" else "图片解析中"),
                count=evidence_count,
                source_kind="image",
                evidence_count=evidence_count,
                locator_summary=f"{title} / {record.mime_type or 'image'}",
                availability=_image_attachment_availability(record, evidence_count),
                meta={
                    "label": _clean_text(record.summary) or ("图片解析完成" if status == "ready" else "图片解析中"),
                    "sourceKind": "image",
                    "conversationId": normalized_conversation_id,
                    "attachmentId": record.attachment_id,
                    "fileName": record.filename,
                    "mimeType": record.mime_type,
                    "image": {
                        "attachment_id": record.attachment_id,
                        "conversation_id": normalized_conversation_id,
                        "history_id": record.history_id,
                        "filename": record.filename,
                        "mime_type": record.mime_type,
                        "size_bytes": record.size_bytes,
                        "status": record.status,
                        "warnings": list(record.warnings or []),
                        "error": record.error,
                    },
                    "aiPayload": ai_payload,
                    "ai_payload": ai_payload,
                },
            )
        )
    return sources


def _lightweight_source_manifest_item(source: PptDataSourceSummary) -> PptDataSourceSummary:
    meta = _safe_dict(source.meta)
    source_kind = _clean_text(source.source_kind) or "unknown"
    lightweight_meta: Dict[str, Any] = {
        "label": _clean_text(meta.get("label") or source.summary),
        "sourceKind": source_kind,
    }
    for key in ("areaId", "area_id", "conversationId", "attachmentId", "fileName", "mimeType", "packageVersion"):
        value = meta.get(key)
        if value not in (None, ""):
            lightweight_meta[key] = value
    return PptDataSourceSummary(
        id=source.id,
        type=source.type,
        title=source.title,
        status=source.status,
        summary=source.summary,
        count=source.count,
        source_kind=source_kind,
        evidence_count=source.evidence_count,
        locator_summary=source.locator_summary,
        availability=source.availability,
        meta=lightweight_meta,
    )


def list_ppt_source_manifest(area_id: str, conversation_id: str = "") -> List[PptDataSourceSummary]:
    return [
        _lightweight_source_manifest_item(source)
        for source in list_ppt_sources(area_id, conversation_id=conversation_id)
        if _clean_text(source.source_kind) != "system"
    ]


def list_ppt_sources(area_id: str, conversation_id: str = "") -> List[PptDataSourceSummary]:
    from modules.ppt_web_source.service import list_persisted_web_sources

    detail = _load_history_detail(area_id)
    poi_payload = _load_history_pois(area_id)
    poi_count = int(poi_payload.get("count") or len(_safe_list(poi_payload.get("pois"))))
    params = _safe_dict(detail.get("params"))
    scope_ready = bool(detail.get("polygon") or params.get("drawn_polygon") or params.get("center"))

    sources: List[PptDataSourceSummary] = []
    for source_id, title in SYSTEM_SOURCE_TITLES.items():
        if source_id == "current:scope":
            ready = scope_ready
            count = 1 if ready else 0
        elif source_id == "current:dataset:poi":
            ready = poi_count > 0
            count = poi_count
        else:
            ready = _artifact_ready(area_id, source_id)
            count = 1 if ready else 0
        sources.append(
            PptDataSourceSummary(
                id=source_id,
                type="data",
                title=title,
                status="ready" if ready else "pending",
                summary=_source_label(source_id, ready, count),
                count=count,
                source_kind="system",
                evidence_count=count,
                locator_summary="当前分析范围" if source_id == "current:scope" else f"analysis:{source_id}",
                availability="available" if ready else "pending:analysis_not_ready",
                meta={
                    "label": _source_label(source_id, ready, count),
                    "sourceKind": "system",
                    "areaId": _clean_text(area_id),
                },
            )
        )
    sources.extend(_list_document_ppt_sources())
    sources.extend(_list_persisted_ppt_package_sources(area_id))
    sources.extend(_list_persisted_database_ppt_sources(area_id))
    sources.extend(PptDataSourceSummary.model_validate(item) for item in list_persisted_web_sources(area_id))
    sources.extend(_list_image_attachment_ppt_sources(conversation_id))
    return sources


def delete_ppt_persisted_source(area_id: str, source_id: str) -> Dict[str, Any]:
    normalized_area_id = _clean_text(area_id)
    normalized_source_id = _clean_text(source_id)
    if not normalized_area_id:
        raise PptDataAreaNotFound("area_id_required")
    if not normalized_source_id:
        raise PptDataSourceNotFound("source_id_required")
    deleted = analysis_artifact_repo.delete_by_source_id(
        normalized_area_id,
        source_id=normalized_source_id,
        artifact_types=[PPT_DATA_PACKAGE_ARTIFACT_TYPE, PPT_WEB_SOURCE_ARTIFACT_TYPE, PPT_DATABASE_ARTIFACT_TYPE, SOURCE_INDEX_MANIFEST_ARTIFACT_TYPE],
    )
    if not deleted:
        raise PptDataSourceNotFound("source_not_found")
    return {"area_id": normalized_area_id, "source_id": normalized_source_id, "deleted": deleted}


def read_ppt_source_summary(area_id: str, source_id: str) -> PptDataSourceSummary:
    normalized_source = _clean_text(source_id)
    summaries = {item.id: item for item in list_ppt_sources(area_id)}
    if normalized_source not in summaries:
        raise PptDataSourceNotFound("source_not_found")
    return summaries[normalized_source]


def _first_text(poi: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        value = poi.get(key)
        if value is not None and _clean_text(value):
            return _clean_text(value)
    return ""


def _parse_location(value: Any, poi: Dict[str, Any]) -> List[float]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if len(parts) >= 2:
            try:
                return [float(parts[0]), float(parts[1])]
            except (TypeError, ValueError):
                return []
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return [float(value[0]), float(value[1])]
        except (TypeError, ValueError):
            return []
    lng = poi.get("lng", poi.get("longitude", poi.get("lon")))
    lat = poi.get("lat", poi.get("latitude"))
    if lng is not None and lat is not None:
        try:
            return [float(lng), float(lat)]
        except (TypeError, ValueError):
            return []
    return []


def _normalize_poi(poi: Any, index: int, *, year: Optional[int], source: str) -> PptPoiPoint:
    item = _safe_dict(poi)
    name = _first_text(item, ["name", "title", "名称"])
    raw_type = _first_text(item, ["type"])
    raw_typecode = _first_text(item, ["typecode", "type_code"])
    typecode = raw_typecode or (raw_type if raw_type.replace(";", "").replace("|", "").isdigit() else "")
    type_labels = _resolve_type_labels(typecode)
    category = _first_text(item, ["category", "type_name", "类别", "中类", "大类"]) or _clean_text(type_labels.get("category"))
    subcategory = _first_text(item, ["subcategory", "sub_category", "小类"]) or _clean_text(type_labels.get("subcategory"))
    if not category and raw_type and not typecode:
        category = raw_type
    return PptPoiPoint(
        id=_first_text(item, ["id", "uid", "poiid"]) or f"poi-{index + 1}",
        name=name or f"POI {index + 1}",
        location=_parse_location(item.get("location"), item),
        address=_first_text(item, ["address", "addr", "地址", "adname"]),
        category=category,
        subcategory=subcategory,
        typecode=typecode,
        year=year if year is not None else item.get("year"),
        source=source or _clean_text(item.get("source")),
    )


def _poi_matches(point: PptPoiPoint, query: str, filters: Dict[str, Any]) -> bool:
    normalized_query = _clean_text(query).lower()
    query_terms = [
        _clean_text(item).lower()
        for item in _safe_list(filters.get("query_terms"))
        if _clean_text(item)
    ]
    if normalized_query:
        query_terms.append(normalized_query)
    category = _clean_text(filters.get("category")).lower()
    if category and category not in point.category.lower():
        return False
    categories = [
        _clean_text(item).lower()
        for item in _safe_list(filters.get("categories"))
        if _clean_text(item)
    ]
    if categories and not any(item in point.category.lower() or point.category.lower() in item for item in categories):
        return False
    subcategory = _clean_text(filters.get("subcategory")).lower()
    if subcategory and subcategory not in point.subcategory.lower():
        return False
    subcategories = [
        _clean_text(item).lower()
        for item in _safe_list(filters.get("subcategories"))
        if _clean_text(item)
    ]
    if subcategories and not any(item in point.subcategory.lower() or point.subcategory.lower() in item for item in subcategories):
        return False
    typecode = _normalize_type_code(filters.get("typecode"))
    if typecode and not _typecode_matches(point.typecode, typecode):
        return False
    typecodes = [
        _normalize_type_code(item)
        for item in _safe_list(filters.get("typecodes"))
        if _normalize_type_code(item)
    ]
    if typecodes and not any(_typecode_matches(point.typecode, item) for item in typecodes):
        return False
    if not query_terms:
        return True
    haystack = " ".join([point.name, point.address, point.category, point.subcategory, point.typecode]).lower()
    return any(item in haystack for item in query_terms)


def _filtered_poi_points(area_id: str, filters: Dict[str, Any]) -> tuple[List[PptPoiPoint], Dict[str, Any], List[str]]:
    filters = _safe_dict(filters)
    year = filters.get("year")
    try:
        normalized_year = int(year) if year is not None and _clean_text(year) else None
    except (TypeError, ValueError):
        normalized_year = None
    poi_payload = _load_history_pois(area_id, year=normalized_year)
    raw_pois = _safe_list(poi_payload.get("pois"))
    selected_year = poi_payload.get("selected_year")
    source = _clean_text(_safe_dict(poi_payload.get("params")).get("source"))
    query = _clean_text(filters.get("query"))
    points = [
        _normalize_poi(poi, index, year=selected_year, source=source)
        for index, poi in enumerate(raw_pois)
    ]
    filtered = [point for point in points if _poi_matches(point, query, filters)]
    warnings: List[str] = []
    if not raw_pois:
        warnings.append("当前区域没有可用 POI 明细。")
    elif not filtered:
        warnings.append("没有匹配筛选条件的 POI。")
    return filtered, poi_payload, warnings


def query_poi_points(request: PptPoiQueryRequest) -> PptPoiQueryResponse:
    filters = _safe_dict(request.filters)
    filtered, poi_payload, warnings = _filtered_poi_points(request.area_id, filters)
    selected_year = poi_payload.get("selected_year")
    start = min(max(0, request.offset), len(filtered))
    end = min(len(filtered), start + request.limit)
    return PptPoiQueryResponse(
        area_id=_clean_text(request.area_id),
        coordinate_system="WGS84",
        items=filtered[start:end],
        total=len(filtered),
        limit=request.limit,
        offset=request.offset,
        available_years=[int(item) for item in _safe_list(poi_payload.get("available_years")) if isinstance(item, int)],
        selected_year=selected_year,
        warnings=warnings,
    )


def query_nearby_poi_points(request: PptPoiNearbyRequest) -> PptPoiQueryResponse:
    center = _normalize_history_center(request.center, request.center_coord_type)
    if len(center) < 2:
        return PptPoiQueryResponse(
            area_id=_clean_text(request.area_id),
            coordinate_system="WGS84",
            limit=request.limit,
            warnings=["nearby 查询缺少中心点。"],
        )
    points, poi_payload, warnings = _filtered_poi_points(request.area_id, request.filters)
    matched: List[PptPoiPoint] = []
    for point in points:
        distance = _haversine_meters(center, point.location)
        if math.isfinite(distance) and distance <= request.radius_m:
            matched.append(point.model_copy(update={"distance_m": round(distance, 2)}))
    matched.sort(key=lambda item: float(item.distance_m or 0))
    if not matched and not warnings:
        warnings.append("中心点半径范围内没有匹配 POI。")
    return PptPoiQueryResponse(
        area_id=_clean_text(request.area_id),
        coordinate_system="WGS84",
        items=matched[:request.limit],
        total=len(matched),
        limit=request.limit,
        offset=0,
        available_years=[int(item) for item in _safe_list(poi_payload.get("available_years")) if isinstance(item, int)],
        selected_year=poi_payload.get("selected_year"),
        warnings=warnings,
    )


def _category_summary(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for item in items:
        category = _clean_text(item.get("category")) or "未分类"
        counts[category] = counts.get(category, 0) + 1
    return [
        {"category": category, "count": count}
        for category, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    ]


def _subcategory_summary(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for item in items:
        subcategory = _clean_text(item.get("subcategory")) or "未分类"
        counts[subcategory] = counts.get(subcategory, 0) + 1
    return [
        {"subcategory": subcategory, "count": count}
        for subcategory, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    ]


def _point_key(point: PptPoiPoint) -> str:
    return _clean_text(point.id) or f"{point.name}:{point.location}"


def _diverse_sample_points(points: List[PptPoiPoint], target_count: int, *, excluded: Optional[set[str]] = None) -> List[PptPoiPoint]:
    target = max(1, int(target_count or 1))
    excluded = excluded or set()
    subcategory_cap = max(1, math.ceil(target / 3))
    selected: List[PptPoiPoint] = []
    selected_keys: set[str] = set()
    subcategory_counts: Dict[str, int] = {}

    for point in points:
        key = _point_key(point)
        if key in excluded or key in selected_keys:
            continue
        subcategory = _clean_text(point.subcategory) or "未分类"
        if subcategory_counts.get(subcategory, 0) >= subcategory_cap:
            continue
        selected.append(point)
        selected_keys.add(key)
        subcategory_counts[subcategory] = subcategory_counts.get(subcategory, 0) + 1
        if len(selected) >= target:
            return selected

    for point in points:
        key = _point_key(point)
        if key in excluded or key in selected_keys:
            continue
        selected.append(point)
        selected_keys.add(key)
        if len(selected) >= target:
            return selected

    return selected


def _is_nightlife_point(point: PptPoiPoint) -> bool:
    haystack = " ".join([
        point.name,
        point.address,
        point.category,
        point.subcategory,
        point.typecode,
    ]).lower()
    if any(_clean_text(term).lower() in haystack for term in NIGHTLIFE_EXCLUDED_TERMS):
        return False
    if any(_clean_text(term).lower() in haystack for term in NIGHTLIFE_STRONG_TERMS):
        return True
    return any(_typecode_matches(point.typecode, typecode) for typecode in NIGHTLIFE_CORE_TYPECODES)


def _nightlife_evidence_plan(limit: int) -> PptEvidenceIntentPlan:
    target = max(1, min(50, int(limit or 50)))
    base = max(1, target // 4)
    remainder = max(0, target - base * 4)

    def count(index: int) -> int:
        return base + (1 if index < remainder else 0)

    return PptEvidenceIntentPlan(
        package_title="夜生活 POI × 夜光格子资料包",
        selection_reason="按夜间社交娱乐、夜宵轻餐、夜间商业节点和夜间生活配套分组整理代表性 POI，并与夜光格子对齐。",
        evidence_groups=[
            PptEvidenceIntentGroup(
                name="夜间社交娱乐",
                purpose="识别晚上停留和社交活动的核心场所。",
                categories=["体育"],
                subcategories=["娱乐场所", "休闲场所", "影剧院"],
                query_terms=["酒吧", "KTV", "影院", "影城", "剧场", "棋牌", "桌游", "网吧", "娱乐"],
                typecodes=["080300", "080500", "080600"],
                target_count=count(0),
            ),
            PptEvidenceIntentGroup(
                name="夜宵与轻餐饮",
                purpose="识别更可能承载夜间消费的餐饮点位。",
                target_count=count(1),
                queries=[
                    PptEvidenceQuery(
                        name="夜宵关键词",
                        categories=["餐饮"],
                        query_terms=["夜宵", "烧烤", "烤肉", "火锅", "餐吧", "清吧"],
                        target_count=max(1, count(1) // 2),
                    ),
                    PptEvidenceQuery(
                        name="轻餐茶饮",
                        categories=["餐饮"],
                        subcategories=["休闲餐饮场所", "咖啡厅", "茶艺馆", "冷饮店", "甜品店"],
                        typecodes=["050400", "050500", "050600", "050700", "050900"],
                        target_count=max(1, count(1) - max(1, count(1) // 2)),
                    ),
                ],
            ),
            PptEvidenceIntentGroup(
                name="夜间商业节点",
                purpose="识别夜间可形成聚集感的商业街区和复合消费节点。",
                categories=["购物"],
                subcategories=["特色商业街", "商场"],
                query_terms=["商业街", "夜市", "街区", "广场", "mall", "购物中心"],
                typecodes=["061000", "060100"],
                target_count=count(2),
            ),
            PptEvidenceIntentGroup(
                name="夜间生活配套",
                purpose="识别可能支撑晚间停留的即时消费与服务点位。",
                categories=["购物", "生活服务"],
                subcategories=["便民商店/便利店"],
                query_terms=["便利店", "24小时", "24h", "足浴", "按摩"],
                typecodes=["060200"],
                target_count=count(3),
            ),
        ],
    )


def _point_gcj02_candidates(point: PptPoiPoint) -> List[Point]:
    if len(point.location) < 2:
        return []
    try:
        lng = float(point.location[0])
        lat = float(point.location[1])
    except (TypeError, ValueError):
        return []
    candidates = [Point(lng, lat)]
    try:
        gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
        if abs(gcj_lng - lng) > 1e-9 or abs(gcj_lat - lat) > 1e-9:
            candidates.append(Point(gcj_lng, gcj_lat))
    except Exception:
        pass
    return candidates


def _history_polygon_gcj02(detail: Dict[str, Any]) -> List[Any]:
    params = _safe_dict(detail.get("params"))
    polygon = detail.get("polygon") or params.get("polygon") or params.get("drawn_polygon")
    return _safe_list(polygon)


def _load_shared_grid_features(area_id: str, detail: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    poi_raster_payload = _latest_artifact_payload(area_id, "poi_raster_grid")
    grid = _safe_dict(poi_raster_payload.get("grid"))
    features = _safe_list(grid.get("features"))
    if features:
        return features, warnings
    polygon = _history_polygon_gcj02(detail)
    if not polygon:
        return [], ["缺少范围 polygon，无法把 POI 精确对应到夜光格子。"]
    try:
        population_grid = get_population_grid(polygon, "gcj02")
        features = _safe_list(population_grid.get("features"))
        return features, warnings
    except Exception:
        return [], ["共享格子加载失败，夜生活 POI 只能作为点位证据使用。"]


def _prepared_grid_cells(features: List[Dict[str, Any]]) -> List[tuple[str, Any, Any]]:
    cells: List[tuple[str, Any, Any]] = []
    for feature in features:
        props = _safe_dict(_safe_dict(feature).get("properties"))
        cell_id = _clean_text(props.get("cell_id") or props.get("h3_id"))
        if not cell_id:
            continue
        try:
            geom = shape(_safe_dict(feature).get("geometry") or {})
        except Exception:
            continue
        if geom.is_empty:
            continue
        cells.append((cell_id, geom, prep(geom)))
    return cells


def _approx_distance_meters(a: Point, b: Point) -> float:
    lat = math.radians((float(a.y) + float(b.y)) / 2)
    dx = (float(a.x) - float(b.x)) * 111320 * math.cos(lat)
    dy = (float(a.y) - float(b.y)) * 111320
    return math.hypot(dx, dy)


def _match_point_cell(point: PptPoiPoint, prepared_cells: List[tuple[str, Any, Any]]) -> Dict[str, Any]:
    candidate_points = _point_gcj02_candidates(point)
    if not candidate_points:
        return {"cell_id": "", "status": "unmatched", "distance_m": None}
    nearest: Dict[str, Any] = {"cell_id": "", "status": "unmatched", "distance_m": None}
    for cell_id, geom, prepared in prepared_cells:
        for gcj02_point in candidate_points:
            if prepared.contains(gcj02_point) or geom.touches(gcj02_point):
                return {"cell_id": cell_id, "status": "matched_cell", "distance_m": 0.0}
            nearest_points = geom.boundary.interpolate(geom.boundary.project(gcj02_point))
            distance_m = _approx_distance_meters(gcj02_point, nearest_points)
            if nearest["distance_m"] is None or distance_m < float(nearest["distance_m"]):
                nearest = {"cell_id": cell_id, "status": "matched_nearest_cell", "distance_m": round(distance_m, 2)}
    if nearest["cell_id"] and float(nearest["distance_m"] or 0) <= NIGHTLIFE_NEAREST_CELL_TOLERANCE_M:
        return nearest
    return {"cell_id": "", "status": "unmatched", "distance_m": nearest["distance_m"]}


def _latest_nightlight_cells(area_id: str) -> Dict[str, Dict[str, Any]]:
    payload = _latest_artifact_payload(area_id, "nightlight")
    layer = _safe_dict(payload.get("layer"))
    cells = _safe_list(layer.get("cells"))
    return {
        _clean_text(cell.get("cell_id")): _safe_dict(cell)
        for cell in cells
        if isinstance(cell, dict) and _clean_text(cell.get("cell_id"))
    }


def _nightlight_value(cell: Dict[str, Any]) -> float:
    for key in ("display_value", "value", "raw_value", "radiance", "mean_radiance"):
        try:
            number = float(cell.get(key))
            if math.isfinite(number):
                return number
        except (TypeError, ValueError):
            continue
    return 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _mean(values: List[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return 0.0
    return sum(finite) / float(len(finite))


def _lng_lat_area_km2(geom: Any) -> float:
    if not geom or geom.is_empty:
        return 0.0
    area_deg2 = float(getattr(geom, "area", 0.0) or 0.0)
    centroid = geom.centroid
    mean_lat = math.radians(float(centroid.y))
    return abs(area_deg2) * 111.32 * 111.32 * max(0.1, math.cos(mean_lat))


def _lng_lat_length_m(geom: Any) -> float:
    if not geom or geom.is_empty:
        return 0.0
    if geom.geom_type == "MultiLineString":
        return sum(_lng_lat_length_m(part) for part in geom.geoms)
    coords = list(getattr(geom, "coords", []) or [])
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(coords, coords[1:]):
        total += _haversine_meters([float(a[0]), float(a[1])], [float(b[0]), float(b[1])])
    return total


def _meters_to_degree_buffer(geom: Any, meters: float) -> float:
    lat = math.radians(float(getattr(getattr(geom, "centroid", None), "y", 0.0) or 0.0))
    x_scale = 111320.0 * max(0.1, math.cos(lat))
    y_scale = 111320.0
    return max(0.0, float(meters or 0.0)) / min(x_scale, y_scale)


def _line_feature_geometry(feature: Dict[str, Any]) -> LineString | None:
    geometry = _safe_dict(feature.get("geometry"))
    if geometry.get("type") != "LineString":
        return None
    coords: List[tuple[float, float]] = []
    for raw in _safe_list(geometry.get("coordinates")):
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        try:
            coords.append((float(raw[0]), float(raw[1])))
        except (TypeError, ValueError):
            continue
    if len(coords) < 2:
        return None
    line = LineString(coords)
    return line if not line.is_empty and line.length > 0 else None


def _road_metric(props: Dict[str, Any], key: str) -> float:
    if key == "choice":
        return _safe_float(props.get("choice_score", props.get("choice_global")), 0.0)
    if key == "integration":
        return _safe_float(props.get("integration_score", props.get("integration_global", props.get("accessibility_score"))), 0.0)
    return _safe_float(props.get(f"{key}_score", props.get(key)), 0.0)


def _road_skeleton_score(props: Dict[str, Any]) -> float:
    return max(0.0, min(1.0, (
        0.45 * _road_metric(props, "choice")
        + 0.40 * _road_metric(props, "integration")
        + 0.15 * _road_metric(props, "connectivity")
    )))


def _load_road_syntax_payload(area_id: str) -> Dict[str, Any]:
    return _latest_artifact_payload(area_id, "road_syntax")


def _carrier_population_evidence(area_id: str) -> Dict[str, Any]:
    artifact = _latest_artifact(area_id, "population")
    payload = _safe_dict(artifact.get("payload"))
    layer = _safe_dict(payload.get("layer"))
    params = _safe_dict(artifact.get("params"))
    selected = _safe_dict(layer.get("selected") or payload.get("selected"))
    legend = _safe_dict(layer.get("legend") or payload.get("legend"))
    view = (_clean_text(selected.get("view")) or _clean_text(layer.get("view")) or _clean_text(payload.get("view")) or _clean_text(params.get("view"))).lower()
    view_label = (
        _clean_text(selected.get("view_label"))
        or _clean_text(layer.get("view_label"))
        or _clean_text(payload.get("view_label"))
        or _clean_text(legend.get("title"))
        or ("总人口" if view == "overview" else ("人口密度" if view in {"density", "sex"} else "人口图层"))
    )
    unit = (
        _clean_text(selected.get("unit"))
        or _clean_text(layer.get("unit"))
        or _clean_text(payload.get("unit"))
        or _clean_text(legend.get("unit"))
        or ("人口" if view == "overview" else ("人/平方公里" if view in {"density", "sex"} else ("%" if view == "age" else "")))
    )
    cells = _safe_list(layer.get("cells"))
    return {
        "view": view,
        "view_label": view_label,
        "unit": unit,
        "summary": _safe_dict(payload.get("summary") or artifact.get("summary")),
        "cells_by_id": {
            _clean_text(cell.get("cell_id")): _safe_dict(cell)
            for cell in cells
            if isinstance(cell, dict) and _clean_text(cell.get("cell_id"))
        },
    }


def _cell_numeric_value(cell: Dict[str, Any], keys: List[str]) -> float:
    for key in keys:
        number = _safe_float(cell.get(key), math.nan)
        if math.isfinite(number):
            return number
    return 0.0


def _optional_cell_numeric_value(cell: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        number = _safe_float(cell.get(key), math.nan)
        if math.isfinite(number):
            return number
    return None


def _road_feature_rows(road_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    features = _safe_list(_safe_dict(road_payload.get("roads")).get("features"))
    rows: List[Dict[str, Any]] = []
    for index, feature in enumerate(features):
        feature_payload = _safe_dict(feature)
        line = _line_feature_geometry(feature_payload)
        if line is None:
            continue
        props = _safe_dict(feature_payload.get("properties"))
        length_m = _safe_float(props.get("length_m"), 0.0) or _lng_lat_length_m(line)
        score = _road_skeleton_score(props)
        rows.append({
            "id": _clean_text(props.get("id") or props.get("road_id") or props.get("name")) or f"road-{index + 1}",
            "feature": feature_payload,
            "line": line,
            "length_m": max(0.0, length_m),
            "skeleton_score": score,
            "choice": _road_metric(props, "choice"),
            "integration": _road_metric(props, "integration"),
            "connectivity": _road_metric(props, "connectivity"),
            "control": _road_metric(props, "control"),
            "depth": _road_metric(props, "depth"),
            "intelligibility": _road_metric(props, "intelligibility"),
            "is_skeleton": bool(props.get("is_skeleton_choice_top20") or props.get("is_skeleton_integration_top20")),
        })
    return rows


def _selected_carrier_skeleton_roads(roads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not roads:
        return []
    sorted_scores = sorted(float(row.get("skeleton_score") or 0.0) for row in roads)
    threshold_index = max(0, int(math.floor(len(sorted_scores) * 0.70)) - 1)
    score_threshold = sorted_scores[threshold_index] if sorted_scores else 0.0
    selected = [
        row for row in roads
        if row.get("is_skeleton")
        or float(row.get("choice") or 0.0) >= 0.72
        or float(row.get("integration") or 0.0) >= 0.72
        or float(row.get("skeleton_score") or 0.0) >= score_threshold
    ]
    if len(selected) < 4:
        selected = sorted(roads, key=lambda row: float(row.get("skeleton_score") or 0.0), reverse=True)[: min(len(roads), 12)]
    return selected


def _shape_short_axis_m(geom: Any) -> float:
    if not geom or geom.is_empty:
        return 0.0
    min_x, min_y, max_x, max_y = geom.bounds
    lat = math.radians(float((min_y + max_y) / 2))
    width_m = abs(float(max_x - min_x)) * 111320.0 * max(0.1, math.cos(lat))
    height_m = abs(float(max_y - min_y)) * 111320.0
    return min(width_m, height_m)


def _shape_compactness(area_km2: float, perimeter_m: float) -> float:
    if area_km2 <= 0 or perimeter_m <= 0:
        return 0.0
    return max(0.0, min(1.0, (4.0 * math.pi * area_km2 * 1_000_000.0) / (perimeter_m * perimeter_m)))


def _line_buffer_polygon(line: Any, meters: float = CARRIER_BOUNDARY_BUFFER_M) -> Any:
    if not line or line.is_empty:
        return None
    return line.buffer(_meters_to_degree_buffer(line, meters))


def _block_loop_candidates(skeleton_roads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lines = [row["line"] for row in skeleton_roads if row.get("line") is not None]
    if len(lines) < 3:
        return []
    try:
        network = unary_union(lines)
        polygons = list(polygonize(network))
    except Exception:
        return []

    candidates: List[Dict[str, Any]] = []
    for polygon in polygons:
        if polygon.is_empty:
            continue
        area_km2 = _lng_lat_area_km2(polygon)
        if area_km2 < BLOCK_LOOP_MIN_AREA_KM2 or area_km2 > BLOCK_LOOP_MAX_AREA_KM2:
            continue
        boundary = polygon.boundary
        boundary_length_m = _lng_lat_length_m(boundary)
        if boundary_length_m <= 1:
            continue
        matched_roads = [
            row for row in skeleton_roads
            if row["line"].distance(boundary) <= _meters_to_degree_buffer(boundary, 35.0)
        ]
        if len(matched_roads) < CARRIER_MIN_BLOCK_LOOP_ROADS:
            continue
        coverage_length = sum(float(row.get("length_m") or 0.0) for row in matched_roads)
        continuity = max(0.0, min(1.0, coverage_length / max(boundary_length_m, 1.0)))
        compactness = _shape_compactness(area_km2, boundary_length_m)
        short_axis_m = _shape_short_axis_m(polygon)
        if continuity < 0.55 or compactness < CARRIER_MIN_COMPACTNESS or short_axis_m < CARRIER_MIN_SHORT_AXIS_M:
            continue
        candidates.append({
            "status": "block_loop",
            "carrier_type": "block_loop",
            "polygon": polygon,
            "boundary": boundary,
            "roads": matched_roads,
            "area_km2": area_km2,
            "boundary_length_m": boundary_length_m,
            "continuity": continuity,
            "compactness": compactness,
            "short_axis_m": short_axis_m,
        })
    candidates.sort(key=lambda item: (
        -float(item.get("continuity") or 0.0),
        -_mean([float(row.get("skeleton_score") or 0.0) for row in _safe_list(item.get("roads"))]),
        float(item.get("area_km2") or 0.0),
    ))
    return candidates


def _connected_road_components(roads: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    adjacency: Dict[tuple[float, float], List[int]] = {}
    for index, row in enumerate(roads):
        coords = list(row["line"].coords)
        if len(coords) < 2:
            continue
        for point in (coords[0], coords[-1]):
            adjacency.setdefault(_snap_key(point), []).append(index)

    visited: set[int] = set()
    components: List[List[Dict[str, Any]]] = []
    for start_index in range(len(roads)):
        if start_index in visited:
            continue
        stack = [start_index]
        component_ids: set[int] = set()
        while stack:
            current = stack.pop()
            if current in component_ids:
                continue
            component_ids.add(current)
            coords = list(roads[current]["line"].coords)
            if len(coords) < 2:
                continue
            for point in (coords[0], coords[-1]):
                for neighbor in adjacency.get(_snap_key(point), []):
                    if neighbor not in component_ids:
                        stack.append(neighbor)
        visited.update(component_ids)
        components.append([roads[index] for index in sorted(component_ids)])
    return components


def _corridor_candidates(skeleton_roads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for component in _connected_road_components(skeleton_roads):
        if len(component) < CARRIER_MIN_CORRIDOR_ROADS:
            continue
        component_length_m = sum(float(row.get("length_m") or 0.0) for row in component)
        if component_length_m < CARRIER_MIN_CORRIDOR_LENGTH_M:
            continue
        merged = unary_union([row["line"] for row in component])
        boundary = merged if isinstance(merged, (LineString, MultiLineString)) else MultiLineString([row["line"] for row in component])
        polygon = _line_buffer_polygon(boundary)
        if polygon is None or polygon.is_empty:
            continue
        candidates.append({
            "status": "corridor",
            "carrier_type": "corridor",
            "polygon": polygon,
            "boundary": boundary,
            "roads": component,
            "area_km2": _lng_lat_area_km2(polygon),
            "boundary_length_m": component_length_m,
            "continuity": 1.0,
            "compactness": _shape_compactness(_lng_lat_area_km2(polygon), max(component_length_m, 1.0)),
            "short_axis_m": _shape_short_axis_m(polygon),
        })
    candidates.sort(key=lambda item: (
        -_mean([float(row.get("skeleton_score") or 0.0) for row in _safe_list(item.get("roads"))]),
        -float(item.get("boundary_length_m") or 0.0),
    ))
    return candidates[:CARRIER_MAX_CORRIDORS]


def _segment_candidates(road_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    ranked_roads = sorted(
        road_rows,
        key=lambda row: (
            -float(row.get("skeleton_score") or 0.0),
            -float(row.get("choice") or 0.0),
            -float(row.get("integration") or 0.0),
            _clean_text(row.get("id")),
        ),
    )
    for row in ranked_roads[:CARRIER_MAX_SEGMENTS]:
        line = row.get("line")
        polygon = _line_buffer_polygon(line)
        if polygon is None or polygon.is_empty:
            continue
        length_m = float(row.get("length_m") or 0.0) or _lng_lat_length_m(line)
        candidates.append({
            "status": "segment",
            "carrier_type": "segment",
            "polygon": polygon,
            "boundary": line,
            "roads": [row],
            "area_km2": _lng_lat_area_km2(polygon),
            "boundary_length_m": length_m,
            "continuity": 1.0,
            "compactness": 0.0,
            "short_axis_m": _shape_short_axis_m(polygon),
        })
    return candidates


def _snap_key(point: tuple[float, float], digits: int = 5) -> tuple[float, float]:
    return (round(float(point[0]), digits), round(float(point[1]), digits))


def _point_intersects_any(candidates: List[Point], geom: Any) -> bool:
    return any(geom.contains(point) or geom.touches(point) for point in candidates)


def _poi_function_group(point: PptPoiPoint) -> str:
    text = " ".join([point.name, point.category, point.subcategory, point.typecode])
    if _is_nightlife_point(point):
        return "nightlife"
    if any(term in text for term in ("餐饮", "购物", "商场", "商业", "便利店", "超市", "生活服务")):
        return "commerce"
    if any(term in text for term in ("科教", "文化", "学校", "博物馆", "展览", "图书", "公园", "风景")):
        return "culture"
    if any(term in text for term in ("医疗", "医院", "诊所", "社区", "政府", "公共", "教育")):
        return "community"
    return "other"


def _category_counts_for_points(points: List[PptPoiPoint]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for point in points:
        key = _clean_text(point.category) or "未分类"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _select_carrier_representative_pois(points: List[PptPoiPoint], limit: int = CARRIER_REPRESENTATIVE_POI_LIMIT) -> List[PptPoiPoint]:
    target = max(1, int(limit or CARRIER_REPRESENTATIVE_POI_LIMIT))
    unique_points: List[PptPoiPoint] = []
    seen_keys: set[str] = set()
    for point in points:
        key = _point_key(point)
        if key and key not in seen_keys:
            seen_keys.add(key)
            unique_points.append(point)

    function_counts: Dict[str, int] = {}
    category_counts: Dict[str, int] = {}
    subcategory_counts: Dict[str, int] = {}
    for point in unique_points:
        function = _poi_function_group(point)
        category = _clean_text(point.category) or "未分类"
        subcategory = _clean_text(point.subcategory) or "未分类"
        function_counts[function] = function_counts.get(function, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        subcategory_counts[subcategory] = subcategory_counts.get(subcategory, 0) + 1

    function_order = {"nightlife": 0, "commerce": 1, "culture": 2, "community": 3, "other": 4}
    ranked = sorted(unique_points, key=lambda point: (
        -function_counts.get(_poi_function_group(point), 0),
        -category_counts.get(_clean_text(point.category) or "未分类", 0),
        -subcategory_counts.get(_clean_text(point.subcategory) or "未分类", 0),
        function_order.get(_poi_function_group(point), 9),
        _clean_text(point.name),
    ))
    return _diverse_sample_points(ranked, target)


def _carrier_poi_metrics(carrier: Dict[str, Any], points: List[PptPoiPoint]) -> Dict[str, Any]:
    polygon = carrier["polygon"]
    boundary = carrier["boundary"]
    boundary_buffer = boundary.buffer(_meters_to_degree_buffer(boundary, CARRIER_BOUNDARY_BUFFER_M))
    boundary_points: List[PptPoiPoint] = []
    inside_points: List[PptPoiPoint] = []
    for point in points:
        candidates = _point_gcj02_candidates(point)
        if not candidates:
            continue
        if _point_intersects_any(candidates, boundary_buffer):
            boundary_points.append(point)
        if _point_intersects_any(candidates, polygon):
            inside_points.append(point)
    unique_points: List[PptPoiPoint] = []
    unique_keys: set[str] = set()
    for point in boundary_points + inside_points:
        key = _point_key(point)
        if key and key not in unique_keys:
            unique_keys.add(key)
            unique_points.append(point)
    function_counts: Dict[str, int] = {}
    for point in unique_points:
        group = _poi_function_group(point)
        function_counts[group] = function_counts.get(group, 0) + 1
    representative = _select_carrier_representative_pois(unique_points)
    category_counts = _category_counts_for_points(unique_points)
    dominant_categories = [
        {"category": category, "count": count}
        for category, count in sorted(category_counts.items(), key=lambda row: (-row[1], row[0]))[:5]
    ]
    total = len(unique_points)
    entropy = 0.0
    if category_counts:
        values = [float(value) for value in category_counts.values() if value > 0]
        base = sum(values)
        entropy = sum(-(value / base) * math.log(value / base) for value in values) if base > 0 else 0.0
    return {
        "boundary_poi_count": len(boundary_points),
        "inside_poi_count": len(inside_points),
        "total_related_poi_count": total,
        "poi_density_per_km2": round(total / max(float(carrier.get("area_km2") or 0.0), 1e-6), 3),
        "category_mix_score": round(min(1.0, entropy / 2.2), 3),
        "function_counts": function_counts,
        "dominant_categories": dominant_categories,
        "representative_pois": [point.model_dump(mode="json") for point in representative],
    }


def _carrier_cell_metrics(
    carrier: Dict[str, Any],
    prepared_cells: List[tuple[str, Any, Any]],
    population_evidence: Dict[str, Any],
    nightlight_by_cell: Dict[str, Dict[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    polygon = carrier["polygon"]
    boundary = carrier["boundary"]
    boundary_buffer = boundary.buffer(_meters_to_degree_buffer(boundary, CARRIER_BOUNDARY_BUFFER_M))
    inside_cell_ids: List[str] = []
    boundary_cell_ids: List[str] = []
    for cell_id, geom, _prepared in prepared_cells:
        if polygon.intersects(geom):
            inside_cell_ids.append(cell_id)
        if boundary_buffer.intersects(geom):
            boundary_cell_ids.append(cell_id)

    cell_ids = sorted(set(inside_cell_ids + boundary_cell_ids))
    population_by_cell = _safe_dict(population_evidence.get("cells_by_id"))
    population_view = _clean_text(population_evidence.get("view"))
    population_label = _clean_text(population_evidence.get("view_label")) or "人口图层"
    population_unit = _clean_text(population_evidence.get("unit"))
    explicit_population_values: List[float] = []
    layer_values: List[float] = []
    for cell_id in cell_ids:
        population_cell = _safe_dict(population_by_cell.get(cell_id))
        explicit_value = _optional_cell_numeric_value(population_cell, ["total_population", "population"])
        if explicit_value is not None:
            explicit_population_values.append(explicit_value)
        elif population_view == "overview":
            explicit_population_values.append(_cell_numeric_value(population_cell, ["value", "display_value", "raw_value"]))
        layer_value = _optional_cell_numeric_value(population_cell, ["value", "display_value", "density", "raw_value"])
        if layer_value is not None:
            layer_values.append(layer_value)
    nightlight_values = [_nightlight_value(nightlight_by_cell.get(cell_id, {})) for cell_id in cell_ids]
    has_population_count = bool(explicit_population_values)
    total_population = sum(explicit_population_values) if has_population_count else None
    mean_population = _mean(explicit_population_values) if has_population_count else None
    mean_cell_value = _mean(layer_values)
    max_cell_value = max(layer_values) if layer_values else 0.0
    mean_nightlight = _mean(nightlight_values)
    max_nightlight = max(nightlight_values) if nightlight_values else 0.0
    hotspot_count = sum(
        1 for cell_id in cell_ids
        if _clean_text(nightlight_by_cell.get(cell_id, {}).get("class_key")) in {"core_hotspot", "secondary_hotspot", "emerging_hotspot"}
        or _clean_text(nightlight_by_cell.get(cell_id, {}).get("class_label")) in {"核心热点", "次级热点", "新兴热点"}
    )
    if has_population_count:
        demand_strength = "强" if float(total_population or 0.0) >= 1500 else ("中" if float(total_population or 0.0) >= 500 else "弱")
        population_density_level = "高" if float(mean_population or 0.0) >= 150 else ("中" if float(mean_population or 0.0) >= 50 else "低")
        population_value_mode = "count"
        demand_basis = "population_count"
    else:
        is_density_view = population_view in {"density", "sex"} or "密度" in population_label or "平方公里" in population_unit
        high_threshold = 12000.0 if is_density_view else 60.0
        mid_threshold = 4500.0 if is_density_view else 20.0
        demand_strength = "强" if mean_cell_value >= high_threshold else ("中" if mean_cell_value >= mid_threshold else "弱")
        population_density_level = demand_strength if is_density_view else "未知"
        population_value_mode = "density_or_layer_value"
        demand_basis = "population_layer_value"
    return (
        {
            "inside_cell_count": len(set(inside_cell_ids)),
            "boundary_cell_count": len(set(boundary_cell_ids)),
            "cell_count": len(cell_ids),
            "source_view": population_view,
            "view_label": population_label,
            "unit": population_unit,
            "population_value_mode": population_value_mode,
            "total_population": round(float(total_population), 3) if total_population is not None else None,
            "mean_cell_population": round(float(mean_population), 3) if mean_population is not None else None,
            "mean_cell_value": round(mean_cell_value, 3),
            "max_cell_value": round(max_cell_value, 3),
            "population_density_level": population_density_level,
            "demand_strength": demand_strength,
            "demand_basis": demand_basis,
        },
        {
            "inside_cell_count": len(set(inside_cell_ids)),
            "boundary_cell_count": len(set(boundary_cell_ids)),
            "cell_count": len(cell_ids),
            "mean_radiance": round(mean_nightlight, 6),
            "max_radiance": round(max_nightlight, 6),
            "hotspot_cell_count": hotspot_count,
            "night_activity_level": "强" if hotspot_count >= 1 or mean_nightlight >= 20 else ("中" if mean_nightlight > 0 else "弱"),
        },
    )


def _carrier_road_metrics(carrier: Dict[str, Any]) -> Dict[str, Any]:
    roads = _safe_list(carrier.get("roads"))
    return {
        "road_count": len(roads),
        "choice_score": round(_mean([float(row.get("choice") or 0.0) for row in roads]), 3),
        "integration_score": round(_mean([float(row.get("integration") or 0.0) for row in roads]), 3),
        "connectivity_score": round(_mean([float(row.get("connectivity") or 0.0) for row in roads]), 3),
        "control_score": round(_mean([float(row.get("control") or 0.0) for row in roads]), 3),
        "depth_score": round(_mean([float(row.get("depth") or 0.0) for row in roads]), 3),
        "intelligibility_score": round(_mean([float(row.get("intelligibility") or 0.0) for row in roads]), 3),
        "skeleton_score": round(_mean([float(row.get("skeleton_score") or 0.0) for row in roads]), 3),
        "continuity": round(float(carrier.get("continuity") or 0.0), 3),
        "boundary_length_m": round(float(carrier.get("boundary_length_m") or 0.0), 2),
        "area_km2": round(float(carrier.get("area_km2") or 0.0), 4),
        "compactness": round(float(carrier.get("compactness") or 0.0), 3),
        "short_axis_m": round(float(carrier.get("short_axis_m") or 0.0), 2),
    }


def _carrier_label(
    *,
    carrier_type: str,
    road_metrics: Dict[str, Any],
    poi_metrics: Dict[str, Any],
    population_metrics: Dict[str, Any],
    nightlight_metrics: Dict[str, Any],
) -> str:
    functions = _safe_dict(poi_metrics.get("function_counts"))
    commerce = int(functions.get("commerce") or 0)
    nightlife = int(functions.get("nightlife") or 0)
    culture = int(functions.get("culture") or 0)
    community = int(functions.get("community") or 0)
    total_poi = int(poi_metrics.get("total_related_poi_count") or 0)
    choice = _safe_float(road_metrics.get("choice_score"), 0.0)
    integration = _safe_float(road_metrics.get("integration_score"), 0.0)
    connectivity = _safe_float(road_metrics.get("connectivity_score"), 0.0)
    depth = _safe_float(road_metrics.get("depth_score"), 0.0)
    road_potential = 0.5 * choice + 0.5 * integration
    demand = _safe_float(population_metrics.get("total_population"), 0.0)
    demand_strength = _clean_text(population_metrics.get("demand_strength"))
    has_demand_support = demand_strength in {"中", "强"} or demand >= 500
    night = _safe_float(nightlight_metrics.get("mean_radiance"), 0.0)
    hotspots = int(nightlight_metrics.get("hotspot_cell_count") or 0)

    if carrier_type == "segment":
        if choice >= 0.65 and integration >= 0.65:
            return "重要通达路段"
        if choice >= 0.68:
            return "高 choice 穿行路段"
        if integration >= 0.68:
            return "高 integration 到达路段"
        if connectivity < 0.28 or depth >= 0.65:
            return "隐蔽连接段"
        return "高潜力路段"

    if carrier_type == "corridor":
        if nightlife >= 2 and (hotspots >= 1 or night >= 15) and road_potential >= 0.45:
            return "夜间消费廊道"
        if total_poi >= 6 and commerce >= max(2, culture + community) and road_potential >= 0.50:
            return "商业活力廊道"
        if choice >= integration + 0.08:
            return "穿行骨架廊道"
        if integration >= choice + 0.08:
            return "到达通达廊道"
        return "高分通达廊道"

    if nightlife >= 2 and (hotspots >= 1 or night >= 15) and road_potential >= 0.45:
        return "夜间消费街区"
    if total_poi >= 6 and commerce >= max(2, culture + community) and road_potential >= 0.55 and has_demand_support:
        return "成熟商业街区"
    if culture >= 2 and culture >= commerce and integration >= 0.45:
        return "文教游逛街区"
    if community >= 2 and (demand_strength == "强" or demand >= 800) and connectivity >= 0.35:
        return "社区生活街区"
    if road_potential >= 0.58 and (has_demand_support or night > 0) and total_poi < 6:
        return "潜力激活街区"
    if commerce >= 2:
        return "成熟商业街区"
    return "潜力激活街区"


def _carrier_population_phrase(population_metrics: Dict[str, Any]) -> str:
    total_population = population_metrics.get("total_population")
    if total_population is not None:
        return f"服务人口约 {total_population}"
    value = population_metrics.get("mean_cell_value")
    label = _clean_text(population_metrics.get("view_label")) or "人口图层"
    unit = _clean_text(population_metrics.get("unit"))
    unit_text = f" {unit}" if unit else ""
    return f"{label}均值 {value}{unit_text}"


def _carrier_summary_text(
    label: str,
    carrier_type: str,
    road_metrics: Dict[str, Any],
    poi_metrics: Dict[str, Any],
    population_metrics: Dict[str, Any],
    nightlight_metrics: Dict[str, Any],
) -> str:
    road_count = int(road_metrics.get("road_count") or 0)
    metric_phrase = (
        f"choice {road_metrics.get('choice_score')} / integration {road_metrics.get('integration_score')}，"
        f"关联 POI {poi_metrics.get('total_related_poi_count')} 个，"
        f"{_carrier_population_phrase(population_metrics)}，"
        f"夜光均值 {nightlight_metrics.get('mean_radiance')}。"
    )
    if carrier_type == "block_loop":
        return f"{label}：{road_count} 条路段 polygonize 成街区围合面，{metric_phrase}"
    if carrier_type == "corridor":
        return f"{label}：连续 {road_count} 条高分路段形成廊道轴线，{metric_phrase}"
    return f"{label}：单条 road feature 作为路段载体，{metric_phrase}"


def _serialize_carrier_geometry(carrier: Dict[str, Any]) -> Dict[str, Any]:
    polygon = carrier.get("polygon")
    boundary = carrier.get("boundary")
    polygon_coords: List[List[float]] = []
    if polygon and not polygon.is_empty and getattr(polygon, "exterior", None):
        polygon_coords = [[round(float(x), 6), round(float(y), 6)] for x, y in list(polygon.exterior.coords)[:120]]
    boundary_coords: List[List[float]] = []
    if isinstance(boundary, LineString):
        boundary_coords = [[round(float(x), 6), round(float(y), 6)] for x, y in list(boundary.coords)[:160]]
    elif isinstance(boundary, MultiLineString):
        for part in boundary.geoms:
            boundary_coords.extend([[round(float(x), 6), round(float(y), 6)] for x, y in list(part.coords)[:80]])
            if len(boundary_coords) >= 160:
                boundary_coords = boundary_coords[:160]
                break
    return {
        "type": "carrier_geometry",
        "polygon": polygon_coords,
        "boundary": boundary_coords,
    }


def _serialize_line_path(line: Any, coord_limit: int = 80) -> List[List[float]]:
    if isinstance(line, LineString):
        return [[round(float(x), 6), round(float(y), 6)] for x, y in list(line.coords)[:coord_limit]]
    if isinstance(line, MultiLineString):
        coords: List[List[float]] = []
        for part in line.geoms:
            coords.extend([[round(float(x), 6), round(float(y), 6)] for x, y in list(part.coords)[:coord_limit]])
            if len(coords) >= coord_limit:
                return coords[:coord_limit]
    return []


def _serialize_road_context(road_rows: List[Dict[str, Any]], skeleton_roads: List[Dict[str, Any]]) -> Dict[str, Any]:
    skeleton_object_ids = {id(row) for row in skeleton_roads}
    features: List[Dict[str, Any]] = []
    for original_index, row in enumerate(road_rows):
        path = _serialize_line_path(row.get("line"))
        if len(path) < 2:
            continue
        is_skeleton = id(row) in skeleton_object_ids or bool(row.get("is_skeleton"))
        features.append({
            "id": _clean_text(row.get("id")) or f"road-{original_index + 1}",
            "path": path,
            "skeleton_score": round(float(row.get("skeleton_score") or 0.0), 3),
            "choice_score": round(float(row.get("choice") or 0.0), 3),
            "integration_score": round(float(row.get("integration") or 0.0), 3),
            "connectivity_score": round(float(row.get("connectivity") or 0.0), 3),
            "is_skeleton": is_skeleton,
        })
    return {
        "type": "road_context",
        "source": "road_syntax.roads.features",
        "total": len(road_rows),
        "included": len(features),
        "coverage": "complete",
        "features": features,
    }


def _build_poi_road_population_nightlight_carrier_package(request: PptDataPackageRequest, selected_sources: set[str]) -> PptDataPackageResponse:
    missing_sources = sorted(source_id for source_id in CARRIER_REQUIRED_SOURCE_IDS if source_id not in selected_sources)
    if missing_sources:
        raise PptDataSourceNotFound(f"carrier_package_missing_sources:{','.join(missing_sources)}")

    detail = _load_history_detail(request.area_id)
    road_payload = _load_road_syntax_payload(request.area_id)
    road_rows = _road_feature_rows(road_payload)
    population_evidence = _carrier_population_evidence(request.area_id)
    population_by_cell = _safe_dict(population_evidence.get("cells_by_id"))
    nightlight_by_cell = _latest_nightlight_cells(request.area_id)
    if not road_rows:
        raise PptDataSourceNotFound("carrier_package_missing_road_syntax")
    if not population_by_cell:
        raise PptDataSourceNotFound("carrier_package_missing_population")
    if not nightlight_by_cell:
        raise PptDataSourceNotFound("carrier_package_missing_nightlight")

    poi_payload = _load_history_pois(request.area_id)
    selected_year = poi_payload.get("selected_year")
    poi_source = _clean_text(_safe_dict(poi_payload.get("params")).get("source"))
    points = [
        _normalize_poi(poi, index, year=selected_year, source=poi_source)
        for index, poi in enumerate(_safe_list(poi_payload.get("pois")))
    ]
    grid_features, grid_warnings = _load_shared_grid_features(request.area_id, detail)
    prepared_cells = _prepared_grid_cells(grid_features)
    if not prepared_cells:
        raise PptDataSourceNotFound("carrier_package_missing_shared_grid")

    skeleton_roads = _selected_carrier_skeleton_roads(road_rows)
    block_loop_candidates = _block_loop_candidates(skeleton_roads)[:CARRIER_MAX_BLOCK_LOOPS]
    loop_road_object_ids = {
        id(row)
        for candidate in block_loop_candidates
        for row in _safe_list(candidate.get("roads"))
    }
    corridor_source_roads = [row for row in skeleton_roads if id(row) not in loop_road_object_ids]
    corridor_candidates = _corridor_candidates(corridor_source_roads)
    corridor_road_object_ids = {
        id(row)
        for candidate in corridor_candidates
        for row in _safe_list(candidate.get("roads"))
    }
    segment_candidates = _segment_candidates([
        row for row in road_rows
        if id(row) not in loop_road_object_ids and id(row) not in corridor_road_object_ids
    ])
    raw_carriers = block_loop_candidates + corridor_candidates + segment_candidates
    road_context = _serialize_road_context(road_rows, skeleton_roads)

    carriers: List[Dict[str, Any]] = []
    representative_items: List[Dict[str, Any]] = []
    seen_poi_keys: set[str] = set()
    type_indexes: Dict[str, int] = {}
    for candidate in raw_carriers:
        road_metrics = _carrier_road_metrics(candidate)
        poi_metrics = _carrier_poi_metrics(candidate, points)
        population_metrics, nightlight_metrics = _carrier_cell_metrics(candidate, prepared_cells, population_evidence, nightlight_by_cell)
        carrier_type = _clean_text(candidate.get("carrier_type") or candidate.get("status")) or "segment"
        type_indexes[carrier_type] = type_indexes.get(carrier_type, 0) + 1
        label = _carrier_label(
            carrier_type=carrier_type,
            road_metrics=road_metrics,
            poi_metrics=poi_metrics,
            population_metrics=population_metrics,
            nightlight_metrics=nightlight_metrics,
        )
        carrier_id = f"{carrier_type}_{type_indexes[carrier_type]:02d}"
        carrier_refs = [
            f"carrier:{carrier_id}:road",
            f"carrier:{carrier_id}:poi",
            f"carrier:{carrier_id}:population",
            f"carrier:{carrier_id}:nightlight",
        ]
        representatives = _safe_list(poi_metrics.get("representative_pois"))
        for item in representatives:
            key = _clean_text(item.get("id")) or _clean_text(item.get("name"))
            if key and key not in seen_poi_keys and len(representative_items) < request.limit:
                seen_poi_keys.add(key)
                item["carrier_id"] = carrier_id
                item["carrier_type"] = carrier_type
                item["carrier_label"] = label
                representative_items.append(item)
        carriers.append({
            "carrier_id": carrier_id,
            "carrier_type": carrier_type,
            "carrier_label": label,
            "summary": _carrier_summary_text(label, carrier_type, road_metrics, poi_metrics, population_metrics, nightlight_metrics),
            "road_metrics": road_metrics,
            "poi_metrics": {key: value for key, value in poi_metrics.items() if key != "representative_pois"},
            "population_metrics": population_metrics,
            "nightlight_metrics": nightlight_metrics,
            "representative_pois": representatives,
            "geometry": _serialize_carrier_geometry(candidate),
            "evidence_refs": carrier_refs,
        })

    label_counts: Dict[str, int] = {}
    type_counts: Dict[str, int] = {"segment": 0, "corridor": 0, "block_loop": 0}
    for carrier in carriers:
        carrier_type = _clean_text(carrier.get("carrier_type")) or "segment"
        type_counts[carrier_type] = type_counts.get(carrier_type, 0) + 1
        label = _clean_text(carrier.get("carrier_label")) or "空间载体"
        label_counts[label] = label_counts.get(label, 0) + 1
    top_carrier = carriers[0] if carriers else {}
    evidence_refs = [
        ref
        for carrier in carriers
        for ref in _safe_list(carrier.get("evidence_refs"))
    ]
    warnings = list(grid_warnings)
    if not carriers:
        warnings.append("未形成稳定空间载体：路网骨架没有构成可解释的街区 / 廊道 / 路段候选。")
    package_payload = {
        "area_id": _clean_text(request.area_id),
        "source_ids": sorted(selected_sources),
        "package_mode": "evidence",
        "intent": _clean_text(request.intent) or CARRIER_EVIDENCE_INTENT,
        "package_version": _clean_text(request.package_version),
        "carrier_count": len(carriers),
        "road_feature_count": len(road_rows),
        "skeleton_road_count": len(skeleton_roads),
        "road_context": road_context,
        "carriers": carriers,
    }
    package_id = f"package:poi-road-carriers:{_stable_hash(package_payload)}"
    summary = (
        f"已识别 {len(carriers)} 个空间载体："
        f"街区 / loop {type_counts.get('block_loop', 0)} 个、"
        f"廊道 {type_counts.get('corridor', 0)} 个、"
        f"路段 {type_counts.get('segment', 0)} 个。"
    )
    package_meta = {
        "id": package_id,
        "title": CARRIER_PACKAGE_TITLE,
        "summary": summary,
        "coordinate_system": "GCJ02",
        "package_mode": "evidence",
        "intent": _clean_text(request.intent) or CARRIER_EVIDENCE_INTENT,
        "area_id": _clean_text(request.area_id),
        "package_version": _clean_text(request.package_version),
        "source_ids": sorted(selected_sources),
        "evidence_layers": ["road_syntax", "poi", "population", "nightlight"],
        "filters": {
            "intent_type": "poi_road_population_nightlight_carrier_evidence",
            "carrier_types": ["segment", "corridor", "block_loop"],
            "boundary_buffer_m": CARRIER_BOUNDARY_BUFFER_M,
        },
        "total": len(carriers),
        "items": representative_items,
        "carriers": carriers,
        "road_context": road_context,
        "carrier_summary": {
            "carrier_count": len(carriers),
            "segment_count": type_counts.get("segment", 0),
            "corridor_count": type_counts.get("corridor", 0),
            "block_loop_count": type_counts.get("block_loop", 0),
            "label_counts": label_counts,
            "top_carrier_id": _clean_text(top_carrier.get("carrier_id")),
            "top_carrier_label": _clean_text(top_carrier.get("carrier_label")),
            "top_carrier_type": _clean_text(top_carrier.get("carrier_type")),
        },
        "alignment": {
            "grid_type": "shared_raster",
            "join_key": "cell_id",
            "grid_cell_count": len(grid_features),
            "population_cell_count": len(population_by_cell),
            "nightlight_cell_count": len(nightlight_by_cell),
            "alignment_level": "carrier_geometry_to_shared_cell_intersection",
        },
        "evidence_refs": evidence_refs,
        "warnings": warnings,
    }
    source = PptSource(
        id=package_id,
        type="package",
        title=CARRIER_PACKAGE_TITLE,
        status="ready",
        selected=True,
        meta={
            "label": f"空间载体 {len(carriers)} 个",
            "sourceKind": "package",
            "package": package_meta,
        },
    )
    source = _attach_package_ai_payload(source)
    return PptDataPackageResponse(
        source=source,
        summary=summary,
        items=representative_items,
        evidence_refs=evidence_refs,
        warnings=warnings,
    )


def _build_nightlife_poi_nightlight_package(
    *,
    request: PptDataPackageRequest,
    selected_sources: set[str],
    plan: PptEvidenceIntentPlan,
    group_payloads: List[Dict[str, Any]],
    repaired_groups: List[tuple[PptEvidenceIntentGroup, List[Dict[str, str]]]],
) -> PptDataPackageResponse:
    detail = _load_history_detail(request.area_id)
    selected_points_by_key: Dict[str, PptPoiPoint] = {}
    for group_payload in group_payloads:
        for item in _safe_list(group_payload.get("items")):
            point = PptPoiPoint(**_safe_dict(item))
            key = _point_key(point)
            if key and key not in selected_points_by_key and _is_nightlife_point(point):
                selected_points_by_key[key] = point
    nightlife_points = list(selected_points_by_key.values())
    features, grid_warnings = _load_shared_grid_features(request.area_id, detail)
    prepared_cells = _prepared_grid_cells(features)
    nightlight_by_cell = _latest_nightlight_cells(request.area_id)

    aligned_items: List[Dict[str, Any]] = []
    for point in nightlife_points:
        match = _match_point_cell(point, prepared_cells)
        cell_id = _clean_text(match.get("cell_id"))
        nightlight_cell = nightlight_by_cell.get(cell_id) if cell_id else {}
        item = point.model_dump(mode="json")
        item["cell_id"] = cell_id
        item["cell_match_distance_m"] = match.get("distance_m")
        item["nightlight_cell"] = {
            "cell_id": cell_id,
            "radiance": round(_nightlight_value(nightlight_cell), 6),
            "class_key": _clean_text(nightlight_cell.get("class_key")),
            "class_label": _clean_text(nightlight_cell.get("class_label") or nightlight_cell.get("label")),
            "has_data": bool(nightlight_cell.get("has_data")) if nightlight_cell else False,
            "label": _clean_text(nightlight_cell.get("label")),
        } if cell_id else {}
        if cell_id and nightlight_cell:
            item["alignment_status"] = _clean_text(match.get("status")) or "matched_cell"
        elif cell_id:
            item["alignment_status"] = "matched_grid_without_nightlight"
        else:
            item["alignment_status"] = "unmatched"
        aligned_items.append(item)

    aligned_items.sort(key=lambda item: (
        0 if item.get("alignment_status") == "matched_cell" else (1 if item.get("alignment_status") == "matched_nearest_cell" else 2),
        -float(_safe_dict(item.get("nightlight_cell")).get("radiance") or 0),
        _clean_text(item.get("name")),
    ))
    limited_items = aligned_items[: request.limit]
    matched_items = [item for item in limited_items if item.get("alignment_status") in {"matched_cell", "matched_nearest_cell"}]
    strict_matched_items = [item for item in limited_items if item.get("alignment_status") == "matched_cell"]
    nearest_matched_items = [item for item in limited_items if item.get("alignment_status") == "matched_nearest_cell"]
    evidence_refs = [
        f"poi_nightlight:{item.get('id') or index + 1}:{item.get('cell_id') or 'unmatched'}"
        for index, item in enumerate(limited_items)
    ]
    filters = {
        "intent_type": "nightlife_poi_nightlight_alignment",
        "evidence_groups": [
            {
                "name": group.name,
                "queries": [_query_filters(query) for query in _group_queries(group)],
            }
            for group, _repairs in repaired_groups
        ],
        "query_terms": NIGHTLIFE_QUERY_TERMS,
        "categories": NIGHTLIFE_CATEGORY_LABELS,
        "typecodes": NIGHTLIFE_CORE_TYPECODES,
        "cell_id_source": "population_nightlight_shared_cell_id",
    }
    package_payload = {
        "area_id": _clean_text(request.area_id),
        "source_ids": sorted(selected_sources),
        "package_mode": "evidence",
        "intent": _clean_text(request.intent) or NIGHTLIFE_EVIDENCE_INTENT,
        "package_version": _clean_text(request.package_version),
        "filters": filters,
        "limit": request.limit,
        "items": limited_items,
        "alignment": {
            "grid_type": "shared_raster",
            "join_key": "cell_id",
            "grid_cell_count": len(features),
            "nightlight_cell_count": len(nightlight_by_cell),
            "matched_item_count": len(matched_items),
            "strict_matched_item_count": len(strict_matched_items),
            "nearest_matched_item_count": len(nearest_matched_items),
            "nearest_match_tolerance_m": NIGHTLIFE_NEAREST_CELL_TOLERANCE_M,
            "alignment_level": "cell_id_overlap" if matched_items else "poi_only_or_missing_nightlight_cells",
        },
    }
    package_id = f"package:poi-nightlife:{_stable_hash(package_payload)}"
    summary = f"已整理 {len(limited_items)} 个夜生活 POI，其中 {len(matched_items)} 个已对应夜光格子。"
    warnings = [
        warning
        for group_payload in group_payloads
        for warning in _safe_list(group_payload.get("warnings"))
        if _clean_text(warning)
    ] + list(grid_warnings)
    if not limited_items:
        warnings.append("按夜生活意图分组后没有找到高置信 POI，未使用普通餐饮/超市兜底。")
    if not nightlight_by_cell:
        warnings.append("未读取到夜光格子 artifact，已保留 POI 与共享格子的对应状态。")
    package_meta = {
        "id": package_id,
        "title": "夜生活 POI × 夜光格子资料包",
        "summary": summary,
        "coordinate_system": "WGS84",
        "package_mode": "evidence",
        "intent": _clean_text(request.intent) or NIGHTLIFE_EVIDENCE_INTENT,
        "area_id": _clean_text(request.area_id),
        "package_version": _clean_text(request.package_version),
        "source_ids": sorted(selected_sources),
        "filters": filters,
        "total": len(nightlife_points),
        "items": limited_items,
        "alignment": package_payload["alignment"],
        "category_summary": _category_summary(limited_items),
        "evidence_refs": evidence_refs,
        "intent_plan": plan.model_dump(mode="json"),
        "selection_reason": _clean_text(plan.selection_reason),
        "groups": group_payloads,
        "warnings": warnings,
    }
    source = PptSource(
        id=package_id,
        type="package",
        title="夜生活 POI × 夜光格子资料包",
        status="ready",
        selected=True,
        meta={
            "label": f"POI {len(limited_items)} 条 / 夜光格 {len({item.get('cell_id') for item in matched_items if item.get('cell_id')})} 个",
            "sourceKind": "package",
            "package": package_meta,
        },
    )
    source = _attach_package_ai_payload(source)
    return PptDataPackageResponse(
        source=source,
        summary=summary,
        items=limited_items,
        evidence_refs=evidence_refs,
        warnings=warnings,
    )


def _group_filters(group: PptEvidenceIntentGroup) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if group.query_terms:
        filters["query_terms"] = list(group.query_terms)
    if group.categories:
        filters["categories"] = list(group.categories)
    if group.subcategories:
        filters["subcategories"] = list(group.subcategories)
    if group.typecodes:
        filters["typecodes"] = list(group.typecodes)
    return filters


def _query_filters(query: PptEvidenceQuery) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if query.query_terms:
        filters["query_terms"] = list(query.query_terms)
    if query.categories:
        filters["categories"] = list(query.categories)
    if query.subcategories:
        filters["subcategories"] = list(query.subcategories)
    if query.typecodes:
        filters["typecodes"] = list(query.typecodes)
    return filters


def _repair_evidence_query(query: PptEvidenceQuery, available_categories: Dict[str, List[str]]) -> tuple[PptEvidenceQuery, List[Dict[str, str]]]:
    categories, category_repairs = _normalize_taxonomy_values(query.categories, available_categories.get("categories", []))
    subcategories, subcategory_repairs = _normalize_taxonomy_values(query.subcategories, available_categories.get("subcategories", []))
    repairs = [
        {"field": "categories", **repair}
        for repair in category_repairs
    ] + [
        {"field": "subcategories", **repair}
        for repair in subcategory_repairs
    ]
    repaired = query.model_copy(update={
        "categories": categories,
        "subcategories": subcategories,
    })
    return repaired, repairs


def _group_queries(group: PptEvidenceIntentGroup) -> List[PptEvidenceQuery]:
    if group.queries:
        return list(group.queries)
    return [
        PptEvidenceQuery(
            name=_clean_text(group.name) or "POI 子查询",
            purpose=_clean_text(group.purpose),
            query_terms=list(group.query_terms),
            categories=list(group.categories),
            subcategories=list(group.subcategories),
            typecodes=list(group.typecodes),
            nearby_required=bool(group.nearby_required),
            radius_m=group.radius_m,
            target_count=group.target_count,
        )
    ]


def _repair_evidence_group(group: PptEvidenceIntentGroup, available_categories: Dict[str, List[str]]) -> tuple[PptEvidenceIntentGroup, List[Dict[str, str]]]:
    repaired_queries: List[PptEvidenceQuery] = []
    repairs: List[Dict[str, str]] = []
    for query in _group_queries(group):
        repaired_query, query_repairs = _repair_evidence_query(query, available_categories)
        repaired_queries.append(repaired_query)
        repairs.extend([
            {"query": _clean_text(query.name), **repair}
            for repair in query_repairs
        ])
    return group.model_copy(update={"queries": repaired_queries}), repairs


def _plan_groups(plan: PptEvidenceIntentPlan, fallback_limit: int) -> List[PptEvidenceIntentGroup]:
    groups = list(plan.evidence_groups or [])
    if groups:
        limit = max(1, int(fallback_limit or len(groups)))
        if sum(int(group.target_count or 0) for group in groups) <= limit:
            return groups
        base = max(1, limit // len(groups))
        remainder = max(0, limit - base * len(groups))
        adjusted: List[PptEvidenceIntentGroup] = []
        for index, group in enumerate(groups):
            target_count = base + (1 if index < remainder else 0)
            adjusted.append(group.model_copy(update={"target_count": target_count}))
        return adjusted
    return [
        PptEvidenceIntentGroup(
            name=_clean_text(plan.package_title) or "POI 证据",
            purpose=_clean_text(plan.selection_reason),
            query_terms=list(plan.query_terms),
            categories=list(plan.categories),
            subcategories=list(plan.subcategories),
            typecodes=list(plan.typecodes),
            nearby_required=bool(plan.nearby_required),
            radius_m=plan.radius_m,
            target_count=max(1, min(50, int(fallback_limit or 6))),
        )
    ]


def _execute_evidence_group(
    *,
    request: PptDataPackageRequest,
    group: PptEvidenceIntentGroup,
    excluded_keys: set[str],
    repairs: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    query_payloads: List[Dict[str, Any]] = []
    candidates_by_key: Dict[str, PptPoiPoint] = {}
    total = 0
    warnings: List[str] = []
    for query in _group_queries(group):
        query_payload = _execute_evidence_query(request=request, query=query)
        query_payloads.append(query_payload)
        total += int(query_payload.get("total") or 0)
        warnings.extend([_clean_text(item) for item in _safe_list(query_payload.get("warnings")) if _clean_text(item)])
        for item in _safe_list(query_payload.get("candidates")):
            point = PptPoiPoint(**_safe_dict(item))
            key = _point_key(point)
            if key and key not in candidates_by_key:
                candidates_by_key[key] = point
    candidates = list(candidates_by_key.values())
    selected = _diverse_sample_points(candidates, group.target_count, excluded=excluded_keys)
    for point in selected:
        excluded_keys.add(_point_key(point))
    selected_items = [item.model_dump(mode="json") for item in selected]
    candidate_items = [item.model_dump(mode="json") for item in candidates]
    return {
        "name": _clean_text(group.name) or "POI 证据",
        "purpose": _clean_text(group.purpose),
        "filters": {"queries": [_query_filters(query) for query in _group_queries(group)]},
        "queries": [
            {
                key: value
                for key, value in query_payload.items()
                if key != "candidates"
            }
            for query_payload in query_payloads
        ],
        "target_count": group.target_count,
        "plan_repair": repairs or [],
        "total": total,
        "unique_total": len(candidates),
        "category_summary": _category_summary(candidate_items),
        "subcategory_summary": _subcategory_summary(candidate_items),
        "items": selected_items,
        "warnings": warnings,
    }


def _execute_evidence_query(*, request: PptDataPackageRequest, query: PptEvidenceQuery) -> Dict[str, Any]:
    filters = _query_filters(query)
    if query.nearby_required and request.center:
        result = query_nearby_poi_points(
            PptPoiNearbyRequest(
                area_id=request.area_id,
                center=list(request.center),
                center_coord_type=request.center_coord_type,
                radius_m=query.radius_m or request.radius_m or 1000,
                filters=filters,
                limit=200,
            )
        )
        candidates = list(result.items)
    else:
        candidates, poi_payload, warnings = _filtered_poi_points(request.area_id, filters)
        result = PptPoiQueryResponse(
            area_id=_clean_text(request.area_id),
            coordinate_system="WGS84",
            total=len(candidates),
            limit=200,
            offset=0,
            available_years=[int(item) for item in _safe_list(poi_payload.get("available_years")) if isinstance(item, int)],
            selected_year=poi_payload.get("selected_year"),
            warnings=warnings,
        )
    return {
        "name": _clean_text(query.name) or "POI 子查询",
        "purpose": _clean_text(query.purpose),
        "filters": filters,
        "nearby_required": bool(query.nearby_required),
        "radius_m": query.radius_m,
        "target_count": query.target_count,
        "total": result.total,
        "category_summary": _category_summary([item.model_dump(mode="json") for item in candidates]),
        "subcategory_summary": _subcategory_summary([item.model_dump(mode="json") for item in candidates]),
        "candidates": [item.model_dump(mode="json") for item in candidates[:200]],
        "warnings": list(result.warnings),
    }


async def parse_ppt_evidence_intent_with_llm(
    *,
    intent: str,
    available_categories: Dict[str, List[str]],
    area_context: Dict[str, Any],
) -> PptEvidenceIntentPlan:
    if not is_llm_enabled():
        raise PptDataIntentLlmUnavailable("ppt_data_intent_llm_unavailable")
    raw = await _invoke_json_role(
        system_prompt=(
            "你是城市空间分析 PPT 的资料检索规划器。"
            "你的任务是把用户的 PPT 页面资料意图解析成 POI 检索计划。"
            "只输出 JSON，不要输出解释。"
            "不得编造 POI 数据；只选择检索关键词、分类和半径等条件。"
        ),
        user_payload={
            "task": "ppt_poi_evidence_intent_parse",
            "intent": _clean_text(intent) or DEFAULT_EVIDENCE_INTENT,
            "available_categories": available_categories,
            "area_context": area_context,
            "output_schema": {
                "package_title": "资料包标题",
                "selection_reason": "为什么这样检索",
                "evidence_groups": [
                    {
                        "name": "证据组名称，例如餐饮密度",
                        "purpose": "这组证据服务的 PPT 论点",
                        "target_count": 6,
                        "queries": [
                            {
                                "name": "子查询名称，例如酒吧/KTV/娱乐",
                                "purpose": "这个子查询服务的证据角度",
                                "query_terms": ["关键词"],
                                "categories": ["中文大类"],
                                "subcategories": ["中文小类"],
                                "typecodes": ["POI typecode"],
                                "nearby_required": False,
                                "radius_m": 1000,
                                "target_count": 3,
                            }
                        ],
                    }
                ],
            },
        },
        emit=None,
        phase="ppt_poi_evidence_intent_parse",
        title="解析 PPT POI 资料意图",
        reasoning_id="ppt-poi-evidence-intent-parse",
    )
    if not isinstance(raw, dict):
        raise PptDataInvalidIntentPlan("ppt_data_invalid_intent_plan")
    plan = PptEvidenceIntentPlan(**raw)
    valid_groups = [
        group for group in plan.evidence_groups
        if group.query_terms or group.categories or group.subcategories or group.typecodes or group.nearby_required or any(
            query.query_terms or query.categories or query.subcategories or query.typecodes or query.nearby_required
            for query in group.queries
        )
    ]
    if plan.evidence_groups and not valid_groups:
        raise PptDataInvalidIntentPlan("ppt_data_empty_intent_plan")
    if not (
        plan.query_terms
        or plan.categories
        or plan.subcategories
        or plan.typecodes
        or plan.nearby_required
        or valid_groups
    ):
        raise PptDataInvalidIntentPlan("ppt_data_empty_intent_plan")
    if valid_groups != plan.evidence_groups:
        plan = plan.model_copy(update={"evidence_groups": valid_groups})
    return plan


def _build_poi_package_response(
    *,
    request: PptDataPackageRequest,
    poi_result: PptPoiQueryResponse,
    selected_sources: set[str],
    package_mode: str,
    filters: Dict[str, Any],
    title: str,
    intent: str = "",
    intent_plan: Optional[PptEvidenceIntentPlan] = None,
    selection_reason: str = "",
    package_groups: Optional[List[Dict[str, Any]]] = None,
) -> PptDataPackageResponse:
    items = [item.model_dump(mode="json") for item in poi_result.items]
    package_payload = {
        "area_id": _clean_text(request.area_id),
        "coordinate_system": "WGS84",
        "source_ids": sorted(selected_sources),
        "package_mode": package_mode,
        "intent": _clean_text(intent),
        "package_version": _clean_text(request.package_version),
        "query": _clean_text(request.query),
        "limit": request.limit,
        "filters": filters,
        "center": list(request.center),
        "center_coord_type": request.center_coord_type,
        "radius_m": request.radius_m,
        "intent_plan": intent_plan.model_dump(mode="json") if intent_plan else None,
        "total": poi_result.total,
        "items": items,
        "groups": package_groups or [],
    }
    package_id = f"package:poi:{_stable_hash(package_payload)}"
    item_count = len(items)
    summary = f"已整理 {item_count} 条 POI 样例，共 {poi_result.total} 条匹配结果。"
    evidence_refs = [f"poi:{item.get('id') or index + 1}" for index, item in enumerate(items)]
    package_meta = {
        "id": package_id,
        "title": title,
        "summary": summary,
        "coordinate_system": "WGS84",
        "package_mode": package_mode,
        "intent": _clean_text(intent),
        "area_id": _clean_text(request.area_id),
        "package_version": _clean_text(request.package_version),
        "query": _clean_text(request.query),
        "source_ids": sorted(selected_sources),
        "filters": filters,
        "center": list(request.center),
        "center_coord_type": request.center_coord_type,
        "radius_m": request.radius_m,
        "total": poi_result.total,
        "category_summary": _category_summary(items),
        "items": items,
        "groups": package_groups or [],
        "evidence_refs": evidence_refs,
        "warnings": list(poi_result.warnings),
    }
    if intent_plan:
        package_meta["intent_plan"] = intent_plan.model_dump(mode="json")
    if selection_reason:
        package_meta["selection_reason"] = selection_reason
    source = PptSource(
        id=package_id,
        type="package",
        title=title,
        status="ready",
        selected=True,
        meta={
            "label": f"POI {item_count} 条",
            "sourceKind": "package",
            "package": package_meta,
        },
    )
    source = _attach_package_ai_payload(source)
    return PptDataPackageResponse(
        source=source,
        summary=summary,
        items=items,
        evidence_refs=evidence_refs,
        warnings=list(poi_result.warnings),
    )


def _build_evidence_filters(plan: PptEvidenceIntentPlan) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    if plan.query_terms:
        filters["query_terms"] = list(plan.query_terms)
    if plan.categories:
        filters["categories"] = list(plan.categories)
    if plan.subcategories:
        filters["subcategories"] = list(plan.subcategories)
    if plan.typecodes:
        filters["typecodes"] = list(plan.typecodes)
    return filters


async def create_ppt_data_package(request: PptDataPackageRequest) -> PptDataPackageResponse:
    request = _normalize_package_request_center(request)
    selected_sources = {_clean_text(item) for item in request.source_ids if _clean_text(item)}
    include_poi = not selected_sources or "current:dataset:poi" in selected_sources
    intent_text = _clean_text(request.intent)
    include_nightlight = "current:analysis:nightlight" in selected_sources
    package_mode = (_clean_text(request.package_mode) or "evidence").lower()
    wants_carrier_package = package_mode == "evidence" and CARRIER_REQUIRED_SOURCE_IDS.issubset(selected_sources) and any(
        keyword in intent_text
        for keyword in (
            "空间载体",
            "路段",
            "廊道",
            "街区",
            "block_loop",
            "corridor",
            "segment",
            "共同支撑",
        )
    )
    wants_nightlife_alignment = include_nightlight and any(
        keyword in intent_text
        for keyword in ("夜生活", "夜间消费", "夜间活力", "夜光格子", "夜光")
    )
    if wants_carrier_package:
        return _persist_ppt_data_package_response(request, _build_poi_road_population_nightlight_carrier_package(request, selected_sources))
    if not include_poi:
        poi_result = PptPoiQueryResponse(area_id=request.area_id, warnings=["第一版资料包仅支持 POI 来源。"])
        return _persist_ppt_data_package_response(request, _build_poi_package_response(
            request=request,
            poi_result=poi_result,
            selected_sources=selected_sources,
            package_mode=_clean_text(request.package_mode) or "query",
            filters={},
            title="资料包",
        ))

    filters = dict(_safe_dict(request.filters))
    if request.query:
        filters["query"] = request.query

    if package_mode == "nearby":
        poi_result = query_nearby_poi_points(
            PptPoiNearbyRequest(
                area_id=request.area_id,
                center=list(request.center),
                center_coord_type=request.center_coord_type,
                radius_m=request.radius_m or 1000,
                filters=filters,
                limit=request.limit,
            )
        )
        return _persist_ppt_data_package_response(request, _build_poi_package_response(
            request=request,
            poi_result=poi_result,
            selected_sources=selected_sources,
            package_mode="nearby",
            filters=filters,
            title="附近 POI 资料包",
        ))

    if package_mode == "evidence":
        detail = _load_history_detail(request.area_id)
        params = _safe_dict(detail.get("params"))
        context_center = list(request.center) if request.center else _normalize_history_center(params.get("center"), "wgs84")
        area_context = {
            "area_id": _clean_text(request.area_id),
            "center": context_center,
            "center_coord_type": "wgs84" if context_center else "",
            "center_source": "request_current_isochrone_center" if request.center else "history_params",
            "radius_m": request.radius_m,
            "time_min": params.get("time_min") or params.get("duration") or params.get("minutes"),
            "source_ids": sorted(selected_sources),
        }
        available_categories = _available_category_payload()
        plan = _nightlife_evidence_plan(request.limit) if wants_nightlife_alignment else await parse_ppt_evidence_intent_with_llm(
            intent=request.intent,
            available_categories=available_categories,
            area_context=area_context,
        )
        raw_groups = _plan_groups(plan, request.limit)
        repaired_groups: List[tuple[PptEvidenceIntentGroup, List[Dict[str, str]]]] = [
            _repair_evidence_group(group, available_categories)
            for group in raw_groups
        ]
        excluded_keys: set[str] = set()
        group_payloads = [
            _execute_evidence_group(request=request, group=group, excluded_keys=excluded_keys, repairs=repairs)
            for group, repairs in repaired_groups
        ]
        if wants_nightlife_alignment:
            return _persist_ppt_data_package_response(request, _build_nightlife_poi_nightlight_package(
                request=request,
                selected_sources=selected_sources,
                plan=plan,
                group_payloads=group_payloads,
                repaired_groups=repaired_groups,
            ))
        flat_items = [
            item
            for group_payload in group_payloads
            for item in _safe_list(group_payload.get("items"))
        ]
        poi_result = PptPoiQueryResponse(
            area_id=_clean_text(request.area_id),
            coordinate_system="WGS84",
            items=[PptPoiPoint(**item) for item in flat_items[: request.limit]],
            total=sum(int(group_payload.get("total") or 0) for group_payload in group_payloads),
            limit=request.limit,
            offset=0,
            warnings=[
                warning
                for group_payload in group_payloads
                for warning in _safe_list(group_payload.get("warnings"))
                if _clean_text(warning)
            ],
        )
        return _persist_ppt_data_package_response(request, _build_poi_package_response(
            request=request,
            poi_result=poi_result,
            selected_sources=selected_sources,
            package_mode="evidence",
            filters={
                "evidence_groups": [
                    {
                        "name": group.name,
                        "queries": [_query_filters(query) for query in _group_queries(group)],
                    }
                    for group, _repairs in repaired_groups
                ]
            },
            title=_clean_text(plan.package_title) or "POI 资料包",
            intent=_clean_text(request.intent) or DEFAULT_EVIDENCE_INTENT,
            intent_plan=plan,
            selection_reason=_clean_text(plan.selection_reason),
            package_groups=group_payloads,
        ))

    poi_result = query_poi_points(
        PptPoiQueryRequest(
            area_id=request.area_id,
            filters=filters,
            limit=request.limit,
            offset=0,
        )
    )
    return _persist_ppt_data_package_response(request, _build_poi_package_response(
        request=request,
        poi_result=poi_result,
        selected_sources=selected_sources,
        package_mode="query",
        filters=filters,
        title="POI 资料包",
    ))
