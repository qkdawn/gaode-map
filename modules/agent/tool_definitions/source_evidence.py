from __future__ import annotations

from typing import Any, Dict, List

from modules.documents import dossier_evidence_payloads
from modules.evidence_retrieval import EvidenceSearchRequest, SourceRecord, evidence_node_payload_from_node, search_evidence
from modules.evidence_index import EvidenceIndexService, EvidenceSearchQuery

from ..selected_sources import mapped_dataset_source_ids, source_items_from_artifacts, source_records_from_items, source_record_payload
from ..schemas import ToolResult
from .common import RegisteredTool, _register, _tool_spec
from .retrieval import EVIDENCE_NODE_SCHEMA


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _source_records_from_artifacts(artifacts: Dict[str, Any]) -> List[SourceRecord]:
    return source_records_from_items(source_items_from_artifacts(artifacts))


def _selected_source_context(artifacts: Dict[str, Any]) -> Dict[str, Any]:
    context = artifacts.get("selected_source_tool_context")
    return context if isinstance(context, dict) else {}


def _source_records_for_tool(artifacts: Dict[str, Any]) -> List[SourceRecord]:
    context = _selected_source_context(artifacts)
    records = context.get("records")
    if isinstance(records, list) and all(isinstance(item, SourceRecord) for item in records):
        return list(records)
    return _source_records_from_artifacts(artifacts)


def _cache_key(artifacts: Dict[str, Any]) -> str:
    return _as_text(_selected_source_context(artifacts).get("cache_key")) or "selected_source_evidence_node_cache"


def _requested_source_ids(arguments: Dict[str, Any]) -> List[str]:
    requested = [_as_text(item) for item in list(arguments.get("source_ids") or []) if _as_text(item)]
    single = _as_text(arguments.get("source_id"))
    if single and single not in requested:
        requested.append(single)
    return requested


def selected_source_tool_context(records: List[SourceRecord], *, include_mapped_dataset_ids: bool = False, cache_key: str = "selected_source_evidence_node_cache") -> Dict[str, Any]:
    return {
        "records": list(records or []),
        "include_mapped_dataset_ids": bool(include_mapped_dataset_ids),
        "cache_key": cache_key,
    }


async def list_selected_sources(*, arguments, snapshot, artifacts, question):
    del arguments, snapshot, question
    context = _selected_source_context(artifacts)
    include_mapped = bool(context.get("include_mapped_dataset_ids"))
    sources = [
        source_record_payload(source, mapped_dataset_source_ids(source.source_id) if include_mapped else None)
        for source in _source_records_for_tool(artifacts)
    ]
    warnings = [] if sources else ["本轮主 Agent 未收到已选分析来源上下文。"]
    return ToolResult(
        tool_name="list_selected_sources",
        result={"sources": sources, "source_ids": [item["source_id"] for item in sources], "warnings": warnings},
        warnings=warnings,
    )


async def search_selected_source_evidence(*, arguments, snapshot, artifacts, question):
    del snapshot
    records = _source_records_for_tool(artifacts)
    source_ids = {source.source_id for source in records if source.source_id}
    requested = _requested_source_ids(arguments)
    rejected = [item for item in requested if item not in source_ids]
    if rejected:
        warning = f"source_id_not_selected:{', '.join(rejected)}"
        return ToolResult(
            tool_name="search_selected_source_evidence",
            status="failed",
            result={"hits": [], "evidence_nodes": [], "warnings": [warning]},
            warnings=[warning],
            error="source_id_not_selected",
        )
    allowed = [item for item in requested if item in source_ids] or list(source_ids)
    if not allowed:
        return ToolResult(
            tool_name="search_selected_source_evidence",
            status="failed",
            result={"hits": [], "evidence_nodes": [], "warnings": ["本轮没有可检索的已选来源。"]},
            warnings=["本轮没有可检索的已选来源。"],
            error="selected_sources_missing",
        )
    response = await search_evidence(
        EvidenceSearchRequest(
            question=_as_text(arguments.get("query")) or _as_text(question),
            source_ids=allowed,
            sources=records,
            top_k=int(arguments.get("top_k") or 8),
        )
    )
    manifests = EvidenceIndexService().manifests(
        EvidenceSearchQuery(
            question=_as_text(arguments.get("query")) or _as_text(question),
            source_ids=allowed,
            sources=records,
            top_k=int(arguments.get("top_k") or 8),
        )
    )
    query = _as_text(arguments.get("query")) or _as_text(question)
    dossier_nodes = dossier_evidence_payloads(
        artifacts.get("project_evidence_dossier"),
        source_ids=allowed,
        question=query,
        limit=max(8, int(arguments.get("top_k") or 8)),
    )
    retrieved_nodes = [evidence_node_payload_from_node(node) for node in response.nodes]
    nodes = []
    seen_node_ids = set()
    for node in dossier_nodes + retrieved_nodes:
        node_id = _as_text(node.get("id"))
        if not node_id or node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        nodes.append(node)
    nodes = nodes[: max(8, int(arguments.get("top_k") or 8))]
    cache = artifacts.setdefault(_cache_key(artifacts), {})
    if isinstance(cache, dict):
        for node in nodes:
            cache[_as_text(node.get("id"))] = node
    hits = [
        {
            "node_id": node.get("id"),
            "source_id": node.get("source_id"),
            "source_type": node.get("source_type"),
            "title": node.get("title"),
            "summary": node.get("summary"),
            "locator": node.get("locator"),
            "citation": node.get("citation"),
            "evidence_node": node,
        }
        for node in nodes
    ]
    dossier = artifacts.get("project_evidence_dossier") if isinstance(artifacts.get("project_evidence_dossier"), dict) else {}
    warnings = [str(item).strip() for item in list(dossier.get("warnings") or []) if str(item).strip()]
    if not hits:
        warnings.append(f"已选来源 EvidenceNode 未命中：{query or '空查询'}。该提示只针对本轮手动选择的资料来源，不代表当前地图分析上下文没有证据。")
    return ToolResult(
        tool_name="search_selected_source_evidence",
        result={"hits": hits, "evidence_nodes": nodes, "warnings": warnings},
        evidence=nodes,
        warnings=warnings,
        artifacts={
            "selected_source_evidence_nodes": nodes,
            "selected_source_index_manifests": [manifest.model_dump(mode="json") for manifest in manifests],
        },
    )


async def read_selected_source_evidence_node(*, arguments, snapshot, artifacts, question):
    del snapshot, question
    node_id = _as_text(arguments.get("node_id"))
    if not node_id:
        return ToolResult(
            tool_name="read_selected_source_evidence_node",
            status="failed",
            result={"node_id": "", "source_id": "", "source_type": "", "evidence_node": None, "warnings": ["node_id_required"]},
            warnings=["node_id_required"],
            error="node_id_required",
        )
    cache = artifacts.get(_cache_key(artifacts))
    cached = cache.get(node_id) if isinstance(cache, dict) else None
    if isinstance(cached, dict):
        return ToolResult(
            tool_name="read_selected_source_evidence_node",
            result={
                "node_id": node_id,
                "source_id": _as_text(cached.get("source_id")),
                "source_type": _as_text(cached.get("source_type")),
                "evidence_node": cached,
                "warnings": [],
            },
            evidence=[cached],
            artifacts={"selected_source_evidence_nodes": [cached]},
        )
    records = _source_records_for_tool(artifacts)
    selected_source_ids = {source.source_id for source in records if source.source_id}
    requested = _requested_source_ids(arguments)
    rejected = [item for item in requested if item not in selected_source_ids]
    if rejected:
        warning = f"source_id_not_selected:{', '.join(rejected)}"
        return ToolResult(
            tool_name="read_selected_source_evidence_node",
            status="failed",
            result={"node_id": node_id, "source_id": "", "source_type": "", "evidence_node": None, "warnings": [warning]},
            warnings=[warning],
            error="source_id_not_selected",
        )
    allowed = [item for item in requested if item in selected_source_ids] or list(selected_source_ids)
    node = await EvidenceIndexService().read(
        node_id,
        EvidenceSearchQuery(
            question=_as_text(arguments.get("query")) or node_id,
            source_ids=allowed,
            sources=records,
            top_k=50,
        ),
    )
    if node is None:
        warning = f"未找到已选来源 EvidenceNode: {node_id}"
        return ToolResult(
            tool_name="read_selected_source_evidence_node",
            status="failed",
            result={"node_id": node_id, "source_id": "", "source_type": "", "evidence_node": None, "warnings": [warning]},
            warnings=[warning],
            error="evidence_node_not_found",
        )
    matched = evidence_node_payload_from_node(node)
    return ToolResult(
        tool_name="read_selected_source_evidence_node",
        result={
            "node_id": node_id,
            "source_id": _as_text(matched.get("source_id")),
            "source_type": _as_text(matched.get("source_type")),
            "evidence_node": matched,
            "warnings": [],
        },
        evidence=[matched],
        artifacts={"selected_source_evidence_nodes": [matched]},
    )


def register_source_evidence_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["list_selected_sources"] = _register(
        _tool_spec(
            name="list_selected_sources",
            description="列出本轮主 Agent 收到的已选分析来源清单、来源类型和证据数量。分析来源时先用它确认边界。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["selected_sources.manifest"],
            applicable_scenarios=["确认本轮允许使用哪些已选来源"],
            cautions=["只返回本轮已选来源，不能代表未选来源或全库"],
            produces=["selected_sources"],
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            output_schema={"type": "object", "properties": {"sources": {"type": "array"}, "source_ids": {"type": "array"}, "warnings": {"type": "array"}}, "required": ["sources", "source_ids", "warnings"], "additionalProperties": False},
            readonly=True,
            cacheable=True,
        ),
        list_selected_sources,
    )
    registry["search_selected_source_evidence"] = _register(
        _tool_spec(
            name="search_selected_source_evidence",
            description="只在本轮已选分析来源内搜索 EvidenceNode，覆盖文档、网页、图片、资料包和系统来源。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["selected_source.evidence_nodes"],
            applicable_scenarios=["分析来源依据、政策章节、网页摘要、图片 OCR/解读、资料包样本"],
            cautions=["source_ids 只能来自 list_selected_sources；搜索不到时必须说明证据缺口"],
            produces=["selected_source_evidence_nodes"],
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {"hits": {"type": "array"}, "evidence_nodes": {"type": "array", "items": EVIDENCE_NODE_SCHEMA}, "warnings": {"type": "array"}}, "required": ["hits", "evidence_nodes", "warnings"], "additionalProperties": False},
            readonly=True,
            cacheable=True,
        ),
        search_selected_source_evidence,
    )
    registry["read_selected_source_evidence_node"] = _register(
        _tool_spec(
            name="read_selected_source_evidence_node",
            description="按 node_id 读取本轮已选来源 EvidenceNode。node_id 应来自 search_selected_source_evidence 的命中结果。",
            category="information",
            layer="L1",
            ui_tier="foundation",
            data_domain="general",
            capability_type="fetch",
            llm_exposure="primary",
            evidence_contract=["selected_source.evidence_node"],
            applicable_scenarios=["最终回答需要引用某个已选来源的完整证据节点"],
            cautions=["不能读取未选来源；不要猜 node_id"],
            produces=["selected_source_evidence_nodes"],
            input_schema={
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "query": {"type": "string"},
                    "source_id": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["node_id"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {"node_id": {"type": "string"}, "source_id": {"type": "string"}, "source_type": {"type": "string"}, "evidence_node": {"anyOf": [EVIDENCE_NODE_SCHEMA, {"type": "null"}]}, "warnings": {"type": "array"}}, "required": ["node_id", "source_id", "source_type", "evidence_node", "warnings"], "additionalProperties": False},
            readonly=True,
            cacheable=True,
        ),
        read_selected_source_evidence_node,
    )
