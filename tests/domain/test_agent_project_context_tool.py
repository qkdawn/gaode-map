from __future__ import annotations

import asyncio

from modules.agent.schemas import AnalysisSnapshot
from modules.agent.tool_adapters.project_tools import read_project_context


def test_read_project_context_combines_documents_history_scope_and_results():
    result = asyncio.run(
        read_project_context(
            arguments={},
            snapshot=AnalysisSnapshot(
                context={"history_id": "history-1"},
                scope={"polygon": [[[112.9, 28.1], [112.91, 28.1], [112.9, 28.1]]]},
                poi_summary={"total": 12},
                h3={"summary": {"cell_count": 4}},
            ),
            artifacts={
                "selected_sources_context": {
                    "sources": [
                        {
                            "source_id": "document:brief-1",
                            "title": "项目任务书",
                            "source_kind": "document",
                            "document_role": "project_brief",
                            "evidence_nodes": [{"id": "evidence-1"}],
                        }
                    ]
                },
                "project_evidence_dossier": {
                    "status": "ready",
                    "evidence": [
                        {
                            "id": "evidence-1",
                            "title": "项目定位",
                            "content": "形成公共服务与更新功能。",
                            "status": "confirmed",
                            "category": "project_positioning",
                            "citation": "项目任务书 p.1",
                            "locator": "pageindex:position:p.1",
                        }
                    ],
                    "warnings": [],
                    "conflicts": [],
                },
            },
            question="分析这个项目",
        )
    )

    assert result.status == "success"
    assert result.result["history_id"] == "history-1"
    assert result.result["documents"][0]["document_role"] == "project_brief"
    assert result.result["project_evidence"][0]["citation"] == "项目任务书 p.1"
    assert result.result["analysis_results"]["poi_summary"]["total"] == 12


def test_read_project_context_blocks_gis_only_project_reading():
    result = asyncio.run(
        read_project_context(
            arguments={},
            snapshot=AnalysisSnapshot(context={"history_id": "history-1"}, poi_summary={"total": 12}),
            artifacts={},
            question="分析这个项目",
        )
    )

    assert result.status == "failed"
    assert result.error == "project_context_incomplete"
    assert any("不能替代项目任务书" in warning for warning in result.warnings)
