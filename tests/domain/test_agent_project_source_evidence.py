import asyncio

import modules.agent.tool_definitions.source_evidence as source_evidence_tools
from modules.agent.schemas import AnalysisSnapshot
from modules.agent.tool_definitions.source_evidence import (
    read_selected_source_evidence_node,
    search_selected_source_evidence,
)
from modules.evidence_retrieval.schemas import EvidenceSearchResponse, SourceRecord


def test_project_dossier_nodes_are_searchable_and_readable(monkeypatch):
    async def empty_native_search(request):
        return EvidenceSearchResponse(nodes=[])

    monkeypatch.setattr(source_evidence_tools, "search_evidence", empty_native_search)
    source = SourceRecord(
        source_id="document:brief",
        title="项目基本情况",
        source_kind="document",
        status="ready",
    )
    node_id = "document:brief:project-evidence:residents"
    artifacts = {
        "selected_source_tool_context": {"records": [source]},
        "project_evidence_dossier": {
            "status": "ready",
            "question": "分析这个项目",
            "document_ids": ["brief"],
            "document_roles": {"brief": "project_brief"},
            "evidence": [
                {
                    "id": node_id,
                    "source_id": "document:brief",
                    "document_id": "brief",
                    "document_title": "项目基本情况",
                    "document_role": "project_brief",
                    "status": "pending_verification",
                    "category": "resident_stakeholders",
                    "title": "居民情况",
                    "content": "三栋住宅约102户居民继续居住并参与共建共管。",
                    "summary": "约102户居民留存并参与共建共管。",
                    "node_id": "residents",
                    "page_start": 2,
                    "page_end": 2,
                    "locator": "pageindex:residents:p.2",
                    "citation": "项目基本情况 p.2 / 居民情况",
                }
            ],
            "conflicts": [],
            "warnings": [],
        },
    }

    search_result = asyncio.run(
        search_selected_source_evidence(
            arguments={"query": "分析这个项目", "top_k": 8},
            snapshot=AnalysisSnapshot(),
            artifacts=artifacts,
            question="分析这个项目",
        )
    )
    read_result = asyncio.run(
        read_selected_source_evidence_node(
            arguments={"node_id": node_id},
            snapshot=AnalysisSnapshot(),
            artifacts=artifacts,
            question="分析这个项目",
        )
    )

    assert search_result.status == "success"
    assert search_result.result["evidence_nodes"][0]["id"] == node_id
    assert search_result.result["evidence_nodes"][0]["metadata"]["document_role"] == "project_brief"
    assert read_result.status == "success"
    assert read_result.result["evidence_node"]["id"] == node_id
