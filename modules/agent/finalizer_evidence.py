from __future__ import annotations

from typing import Any, Dict, List

from modules.evidence_retrieval import evidence_node_from_knowledge_chunk
from modules.retrieval import RetrievalService

from .schemas import AnalysisSnapshot

_FULL_DEPTH_DOMAINS = ["poi", "h3", "road", "population", "nightlight"]
_MAX_SEARCHES = 4
_MAX_READS = 8
_COVERAGE_QUERIES = {
    "poi": "POI 结构 餐饮 科教文化 购物 业态占比 商业供给",
    "h3": "H3 网格 多核心 热点 机会区 空间结构",
    "road": "路网 句法 集成度 连接度 可达性 动线",
    "population": "人口画像 人口总量 年龄 密度 客群",
    "nightlight": "夜光 活力 夜间 均值 峰值 热点",
}


def _node_id_from_chunk(chunk: Any) -> str:
    node = evidence_node_from_knowledge_chunk(chunk)
    return node.id


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
        broad_query = {"query": text, "domains": domains, "top_k": 6}
    if "poi" in available_domains:
        queries.append({"query": f"{text} 地名 锚点 商业 校园 社区 后湖", "domains": ["poi"], "top_k": 4})
    if "road" in available_domains:
        queries.append({"query": f"{text} 路网 动线 可达性 主路 支路 可读性", "domains": ["road"], "top_k": 4})
    vitality_domains = [domain for domain in ("population", "nightlight", "h3") if domain in available_domains]
    if vitality_domains:
        queries.append({"query": f"{text} 人口 夜光 H3 热点 活力 格网", "domains": vitality_domains, "top_k": 4})
    if domains:
        queries.append(broad_query)

    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for item in queries:
        key = f"{item['query']}|{','.join(item['domains'])}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:_MAX_SEARCHES]


def _coverage_plan(available_domains: List[str]) -> List[Dict[str, Any]]:
    return [
        {"query": _COVERAGE_QUERIES[domain], "domains": [domain], "top_k": 3, "coverage_domain": domain}
        for domain in _FULL_DEPTH_DOMAINS
        if domain in available_domains
    ]


def build_finalizer_evidence_pack(
    *,
    question: str,
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    answer_evidence_payload: Dict[str, Any],
) -> Dict[str, Any]:
    service = RetrievalService(snapshot=snapshot, artifacts=artifacts or {})
    available_domains = _available_domains(service)
    dossier = answer_evidence_payload.get("project_evidence_dossier")
    dossier = dossier if isinstance(dossier, dict) else {}
    document_evidence_nodes = [item for item in list(dossier.get("evidence") or []) if isinstance(item, dict)]
    dossier_warnings = [str(item).strip() for item in list(dossier.get("warnings") or []) if str(item).strip()]
    pack: Dict[str, Any] = {
        "status": "ready" if document_evidence_nodes else "skipped",
        "reason": "project_document_evidence" if document_evidence_nodes else "not_required",
        "available_domains": available_domains,
        "search_queries": [],
        "document_evidence_nodes": document_evidence_nodes,
        "document_conflicts": [item for item in list(dossier.get("conflicts") or []) if isinstance(item, dict)],
        "document_status": str(dossier.get("status") or "empty"),
        "evidence_nodes": [],
        "coverage_domains": [],
        "missing_coverage_domains": [],
        "warnings": dossier_warnings[:8],
        "evidence_limits": [
            "项目事实先使用 document_evidence_nodes，并遵守 project_brief > design_vision > reference_document 的证据顺序。",
            "design_vision 只能表述为设计意图；pending_verification/conflicting 不得改写成确认事实。",
            "最终回答只能引用 evidence_nodes 中实际读取到的具体地名、H3 格子、路网线段、人口/夜光 cell。",
            "地图快照可支持视觉观察，但不能替代结构化 EvidenceNode。",
        ],
    }
    if dossier.get("has_project_anchor") and not dossier.get("has_readable_project_anchor"):
        pack["status"] = "failed"
        pack["reason"] = "core_project_document_unreadable"
        return pack
    if not available_domains:
        pack["reason"] = "project_document_only" if document_evidence_nodes else "no_analysis_context_sources"
        if dossier.get("status") == "partial" and dossier.get("has_project_anchor"):
            pack["status"] = "partial" if document_evidence_nodes else "failed"
        return pack
    if not _needs_finalizer_retrieval(question, answer_evidence_payload):
        return pack

    pack["status"] = "ready"
    pack["reason"] = "project_and_spatial_evidence" if document_evidence_nodes else "high_value_spatial_question"
    read_ids: set[str] = set()
    evidence_nodes: List[Dict[str, Any]] = []
    warnings: List[str] = list(dossier_warnings)
    coverage_domains: List[str] = []
    for planned in _coverage_plan(available_domains) + _query_plan(question, answer_evidence_payload, available_domains):
        hits = service.search_analysis_context(
            query=_as_text(planned.get("query")),
            domains=[_as_text(item) for item in planned.get("domains") or []],
            top_k=int(planned.get("top_k") or 6),
        )
        chunks_by_id: Dict[str, Any] = {}
        for hit in hits[:4]:
            chunk = service.read_analysis_chunk(hit.chunk_id)
            if chunk is not None:
                chunks_by_id[hit.chunk_id] = chunk
        search_node_ids = [_node_id_from_chunk(chunk) for chunk in chunks_by_id.values()]
        pack["search_queries"].append(
            {
                "query": _as_text(planned.get("query")),
                "domains": list(planned.get("domains") or []),
                "coverage_domain": _as_text(planned.get("coverage_domain")),
                "hit_count": len(hits),
                "node_ids": search_node_ids,
            }
        )
        if not hits:
            warnings.append(f"未命中：{_as_text(planned.get('query'))}")
        for hit in hits:
            if len(evidence_nodes) >= _MAX_READS:
                break
            if hit.chunk_id in read_ids:
                continue
            chunk = chunks_by_id.get(hit.chunk_id)
            if chunk is None:
                chunk = service.read_analysis_chunk(hit.chunk_id)
            if chunk is None:
                warnings.append(f"evidence_node_not_found: {_as_text(hit.title) or 'unknown_node'}")
                continue
            read_ids.add(hit.chunk_id)
            evidence_nodes.append(evidence_node_from_knowledge_chunk(chunk).model_dump(mode="python"))
            coverage_domain = _as_text(planned.get("coverage_domain"))
            if coverage_domain and coverage_domain not in coverage_domains:
                coverage_domains.append(coverage_domain)
            if coverage_domain:
                break
        if len(evidence_nodes) >= _MAX_READS:
            break

    if not evidence_nodes:
        pack["status"] = "empty"
        warnings.append("最终证据检索未读取到可用 EvidenceNode，最终回答需保持保守。")
    pack["evidence_nodes"] = evidence_nodes
    pack["coverage_domains"] = coverage_domains
    pack["missing_coverage_domains"] = [domain for domain in _FULL_DEPTH_DOMAINS if domain in available_domains and domain not in coverage_domains]
    pack["warnings"] = warnings[:8]
    return pack
