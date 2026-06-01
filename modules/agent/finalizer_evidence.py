from __future__ import annotations

from typing import Any, Dict, List

from modules.retrieval import KnowledgeChunk, RetrievalService

from .schemas import AnalysisSnapshot

_FULL_DEPTH_DOMAINS = ["poi", "h3", "road", "population", "nightlight"]
_MAX_SEARCHES = 4
_MAX_READS = 8


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _is_full_depth(payload: Dict[str, Any]) -> bool:
    guidance = payload.get("answer_depth_guidance") if isinstance(payload.get("answer_depth_guidance"), dict) else {}
    return _as_text(guidance.get("target_depth")) == "full"


def _needs_finalizer_retrieval(question: str, payload: Dict[str, Any]) -> bool:
    if not _is_full_depth(payload):
        return False
    text = _as_text(question)
    high_value_tokens = (
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
        "山水",
        "校园",
        "道路",
        "节点",
    )
    return any(token in text for token in high_value_tokens)


def _available_domains(service: RetrievalService) -> List[str]:
    domains: List[str] = []
    for source in service.available_context_sources():
        if not source.startswith("analysis:"):
            continue
        domain = source.split(":", 1)[1].strip()
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _query_plan(question: str, payload: Dict[str, Any], available_domains: List[str]) -> List[Dict[str, Any]]:
    text = _as_text(question)
    domains = [domain for domain in _FULL_DEPTH_DOMAINS if domain in available_domains]
    if not domains:
        domains = [domain for domain in available_domains if domain][:5]
    queries: List[Dict[str, Any]] = []
    if domains:
        queries.append({"query": text, "domains": domains, "top_k": 6})
    if "poi" in available_domains:
        queries.append({"query": f"{text} 地名 锚点 商业 校园 社区 后湖", "domains": ["poi"], "top_k": 4})
    if "road" in available_domains:
        queries.append({"query": f"{text} 路网 动线 可达性 主路 支路 可读性", "domains": ["road"], "top_k": 4})
    vitality_domains = [domain for domain in ("population", "nightlight", "h3") if domain in available_domains]
    if vitality_domains:
        queries.append({"query": f"{text} 人口 夜光 H3 热点 活力 格网", "domains": vitality_domains, "top_k": 4})

    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for item in queries:
        key = f"{item['query']}|{','.join(item['domains'])}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:_MAX_SEARCHES]


def _chunk_payload(chunk: KnowledgeChunk) -> Dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "domain": chunk.domain,
        "title": chunk.title,
        "content": chunk.content,
        "metrics": dict(chunk.metrics or {}),
        "source_artifacts": list(chunk.source_artifacts or []),
        "warnings": list(chunk.warnings or []),
        "evidence_level": chunk.evidence_level,
    }


def build_finalizer_evidence_pack(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    answer_evidence_payload: Dict[str, Any],
) -> Dict[str, Any]:
    service = RetrievalService(snapshot=snapshot, artifacts=artifacts or {})
    available_domains = _available_domains(service)
    pack: Dict[str, Any] = {
        "status": "skipped",
        "reason": "not_required",
        "available_domains": available_domains,
        "search_queries": [],
        "read_chunks": [],
        "warnings": [],
        "evidence_limits": [
            "最终回答只能引用 read_chunks 中实际读取到的具体地名、H3 格子、路网线段、人口/夜光 cell。",
            "地图快照可支持视觉观察，但不能替代结构化 chunk。",
        ],
    }
    if not available_domains:
        pack["reason"] = "no_analysis_context_sources"
        return pack
    if not _needs_finalizer_retrieval(question, answer_evidence_payload):
        return pack

    pack["status"] = "ready"
    pack["reason"] = "high_value_spatial_question"
    read_ids: set[str] = set()
    read_chunks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for planned in _query_plan(question, answer_evidence_payload, available_domains):
        hits = service.search_analysis_context(
            query=_as_text(planned.get("query")),
            domains=[_as_text(item) for item in planned.get("domains") or []],
            top_k=int(planned.get("top_k") or 6),
        )
        pack["search_queries"].append(
            {
                "query": _as_text(planned.get("query")),
                "domains": list(planned.get("domains") or []),
                "hit_count": len(hits),
                "hit_ids": [hit.chunk_id for hit in hits[:4]],
            }
        )
        if not hits:
            warnings.append(f"未命中：{_as_text(planned.get('query'))}")
        for hit in hits:
            if len(read_chunks) >= _MAX_READS:
                break
            if hit.chunk_id in read_ids:
                continue
            chunk = service.read_analysis_chunk(hit.chunk_id)
            if chunk is None:
                warnings.append(f"chunk_not_found: {hit.chunk_id}")
                continue
            read_ids.add(hit.chunk_id)
            read_chunks.append(_chunk_payload(chunk))
        if len(read_chunks) >= _MAX_READS:
            break

    if not read_chunks:
        pack["status"] = "empty"
        warnings.append("最终证据检索未读取到可用 chunk，最终回答需保持保守。")
    pack["read_chunks"] = read_chunks
    pack["warnings"] = warnings[:8]
    return pack
