from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from modules.evidence_retrieval import EvidenceNode, evidence_node_payloads_from_nodes
from modules.ppt_planning.schemas import PptDataPackageResponse, PptSource, PptDataSourceSummary
from store.analysis_artifact_repo import analysis_artifact_repo
from store.history_repo import history_repo

PPT_DATABASE_ARTIFACT_TYPE = "ppt_database_package"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _compact_text(value: Any, limit: int = 900) -> str:
    return _clean_text(value)[:limit]


def _build_database_evidence_nodes(area_id: str) -> List[EvidenceNode]:
    detail = history_repo.get_detail(area_id, include_pois=False) or {}
    params = _safe_dict(detail.get("params"))
    pois = history_repo.get_pois(area_id) or {}
    poi_summary = _safe_dict(detail.get("poi_summary") or pois.get("poi_summary"))
    pois_by_year = _safe_list(detail.get("pois_by_year") or pois.get("pois_by_year"))

    nodes: List[EvidenceNode] = []
    if detail:
        content = _compact_text(json.dumps({
            "description": detail.get("description", ""),
            "params": params,
            "poi_summary": poi_summary,
        }, ensure_ascii=False, default=str))
        nodes.append(EvidenceNode(
            id=f"database:{area_id}:history:summary",
            source_id=f"database:{area_id}:history",
            source_type="database",
            title="当前分析区域详情",
            content=content,
            summary=content[:260],
            metadata={
                "history_id": _clean_text(detail.get("id")),
                "available_years": _safe_list(detail.get("available_years")),
                "selected_year": detail.get("selected_year"),
            },
            locator=f"analysis_history:{_clean_text(detail.get('id'))}",
            evidence_level="history_summary",
            citation=f"数据库历史记录 {_clean_text(detail.get('id'))}",
        ))

    if poi_summary:
        content = _compact_text(f"POI 总量 {poi_summary.get('total', 0)}，来源 {poi_summary.get('source', '')}，年份 {poi_summary.get('year', '')}。")
        nodes.append(EvidenceNode(
            id=f"database:{area_id}:poi:summary",
            source_id=f"database:{area_id}:poi",
            source_type="database",
            title="POI 基础数据摘要",
            content=content,
            summary=content[:260],
            metadata={
                "count": poi_summary.get("total"),
                "source": poi_summary.get("source"),
                "year": poi_summary.get("year"),
            },
            locator=f"poi_summary:{area_id}",
            evidence_level="poi_summary",
            citation="数据库 POI 基础数据",
        ))

    for index, item in enumerate(pois_by_year[:4], start=1):
        item_payload = _safe_dict(item)
        summary = _safe_dict(item_payload.get("summary"))
        year = _clean_text(item_payload.get("year")) or "未知年份"
        content = _compact_text(json.dumps({
            "year": item_payload.get("year"),
            "source": item_payload.get("source"),
            "summary": summary,
        }, ensure_ascii=False, default=str))
        nodes.append(EvidenceNode(
            id=f"database:{area_id}:pois_by_year:{year}:{index}",
            source_id=f"database:{area_id}:pois_by_year",
            source_type="database",
            title=f"{year} POI 摘要",
            content=content,
            summary=content[:260],
            metadata={
                "year": item_payload.get("year"),
                "source": item_payload.get("source"),
                "count": item_payload.get("count"),
            },
            locator=f"pois_by_year:{year}",
            evidence_level="poi_year_summary",
            citation=f"数据库分年 POI 记录 {year}",
        ))

    return nodes


def _database_locator_summary(area_id: str, evidence_count: int) -> str:
    normalized_area_id = _clean_text(area_id) or "global"
    return f"analysis_history:{normalized_area_id} / database evidence {evidence_count}"


def _database_availability(evidence_count: int) -> str:
    return "available" if evidence_count > 0 else "empty_evidence:database_empty"


def build_database_data_package(area_id: str, *, title: str = "") -> PptDataPackageResponse:
    normalized_area_id = _clean_text(area_id)
    if not normalized_area_id:
        raise ValueError("area_id_required")
    evidence_nodes = _build_database_evidence_nodes(normalized_area_id)
    evidence_node_payloads = evidence_node_payloads_from_nodes(evidence_nodes)
    package_title = _clean_text(title) or "数据库资料包"
    source_hash = _stable_hash({"area_id": normalized_area_id, "evidence_nodes": evidence_node_payloads})
    source_id = f"database:{normalized_area_id}:{source_hash}"
    ai_payload = {
        "version": "ppt_ai_input_block_v1",
        "source_id": source_id,
        "sourceId": source_id,
        "title": package_title,
        "source_kind": "database",
        "sourceKind": "database",
        "included": ["evidence"] if evidence_node_payloads else [],
        "scope": None,
        "metrics": [],
        "metric_gaps": [],
        "metricGaps": [],
        "evidence_nodes": evidence_node_payloads,
        "evidenceNodes": evidence_node_payloads,
        "visual_specs": [],
        "visualSpecs": [],
        "excluded": [{"type": "database_raw_records", "reason": "不传数据库原始明细，只传摘要和证据节点。"}],
        "counts": {"scope": 0, "metrics": 0, "metric_gaps": 0, "evidence": len(evidence_node_payloads), "visual_specs": 0},
        "policy": "数据库来源仅通过摘要和证据节点进入 LLM；不传原始记录和大表明细。",
    }
    source = PptSource(
        id=source_id,
        type="database",
        title=package_title,
        status="ready",
        selected=True,
        source_kind="database",
        summary=f"已整理 {len(evidence_node_payloads)} 条数据库证据。",
        evidence_count=len(evidence_node_payloads),
        locator_summary=_database_locator_summary(normalized_area_id, len(evidence_node_payloads)),
        availability=_database_availability(len(evidence_node_payloads)),
        meta={
            "label": f"数据库证据 {len(evidence_node_payloads)} 条",
            "sourceKind": "database",
            "areaId": normalized_area_id,
            "database": {
                "area_id": normalized_area_id,
                "source_count": len(evidence_node_payloads),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "aiPayload": ai_payload,
            "ai_payload": ai_payload,
        },
    )
    response = PptDataPackageResponse(
        source=source,
        summary=f"已整理 {len(evidence_node_payloads)} 条数据库证据。",
        items=evidence_node_payloads,
        evidence_refs=[_clean_text(item.get("id") or item.get("source_id")) for item in evidence_node_payloads],
        warnings=[],
    )
    analysis_artifact_repo.upsert(
        history_id=normalized_area_id,
        artifact_type=PPT_DATABASE_ARTIFACT_TYPE,
        params={"area_id": normalized_area_id, "title": package_title},
        payload=response.model_dump(mode="json"),
        summary={
            "id": source.id,
            "title": source.title,
            "label": source.meta.get("label"),
            "item_count": len(evidence_node_payloads),
        },
        data_version="v1",
    )
    return response


def list_persisted_database_sources(area_id: str) -> List[PptDataSourceSummary]:
    normalized_area_id = _clean_text(area_id)
    if not normalized_area_id:
        return []
    sources: List[PptDataSourceSummary] = []
    for artifact in analysis_artifact_repo.list(normalized_area_id, artifact_type=PPT_DATABASE_ARTIFACT_TYPE):
        payload = _safe_dict(artifact.get("payload"))
        source = _safe_dict(payload.get("source"))
        source_id = _clean_text(source.get("id"))
        if not source_id:
            continue
        meta = _safe_dict(source.get("meta"))
        database = _safe_dict(meta.get("database"))
        evidence_count = int(database.get("source_count") or len(_safe_list(payload.get("items"))) or 0)
        sources.append(
            PptDataSourceSummary(
                id=source_id,
                type=_clean_text(source.get("type")) or "database",
                title=_clean_text(source.get("title")) or "数据库资料",
                status="ready",
                summary=_clean_text(payload.get("summary")) or _clean_text(meta.get("label")) or "数据库资料包",
                count=evidence_count,
                source_kind="database",
                evidence_count=evidence_count,
                locator_summary=_clean_text(source.get("locator_summary") or source.get("locatorSummary"))
                or _database_locator_summary(normalized_area_id, evidence_count),
                availability=_clean_text(source.get("availability")) or _database_availability(evidence_count),
                meta={
                    **meta,
                    "label": _clean_text(meta.get("label")) or "数据库资料包",
                    "sourceKind": "database",
                    "areaId": normalized_area_id,
                    "persistedDatabase": True,
                    "database": {
                        **database,
                        "area_id": normalized_area_id,
                    },
                },
            )
        )
    return sources
