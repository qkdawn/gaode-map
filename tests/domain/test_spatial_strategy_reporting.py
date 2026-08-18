from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from modules.spatial_strategy.reporting import (
    FeishuConfig,
    FeishuReportSender,
    SpatialStrategyReportStore,
    build_spatial_strategy_report,
)
from modules.spatial_strategy.docx_export import write_markdown_docx
from modules.spatial_strategy.schemas import SpatialStrategyReportFinalizeRequest


RUN_ID = UUID("31d81c16-1bfc-4bf6-a9e8-cfa36d0a4df2")


def _request() -> SpatialStrategyReportFinalizeRequest:
    steps = {
        "site_role": {
            "title": "项目与区域角色",
            "decision_memo": {"decision": "项目承担节点连接角色。"},
        },
        "named_connections": {
            "title": "具名节点连接",
            "decision_memo": {"decision": "连接具名设施和道路。"},
        },
    }
    steps["site_role"]["citations"] = [
        {
            "citation_id": "project:source-1",
            "title": "项目材料原文",
            "content": "这是项目材料中的可复核原文。",
            "source_type": "project_document",
            "source_locator": "项目材料：第 1 页",
            "dataset_id": "document:1",
            "snapshot_id": "snapshot-1",
        }
    ]
    steps["named_connections"]["citations"] = [
        {"citation_id": "project:source-1", "source_type": "project_document"},
        {"citation_id": "project:source-2", "title": "空间查询", "source_type": "project_data"},
    ]
    return SpatialStrategyReportFinalizeRequest(
        run_id=RUN_ID,
        history_id="history-1",
        project_question="判断项目空间策略",
        project_context={"project": {"name": "测试项目"}},
        editorial_narrative="项目应以可验证的空间策略形成首期行动，并以运营反馈决定后续投入。",
        decision_state={
            "steps": steps,
            "report_sections": [
                {
                    "section_id": "regional_role",
                    "section_order": 1,
                    "title": "区域角色",
                    "source_unit_ids": ["site_role"],
                    "content": "项目材料与空间数据共同表明，项目应承担区域节点连接角色。",
                },
                {
                    "section_id": "named_connections",
                    "section_order": 2,
                    "title": "具名连接关系",
                    "source_unit_ids": ["named_connections"],
                    "content": "具名设施与道路关系把区域判断落实到具体连接对象。",
                },
                {
                    "section_id": "first_actions",
                    "section_order": 3,
                    "title": "首期行动",
                    "source_unit_ids": ["site_role", "named_connections"],
                    "content": "首期行动围绕上述连接关系形成可执行组合。",
                },
            ],
            "evidence_index": {
                "project:source-1": {
                    "citation_id": "project:source-1",
                    "title": "项目材料原文",
                    "content": "这是项目材料中的可复核原文。",
                    "source_type": "project_document",
                    "source_locator": "项目材料：第 1 页",
                    "dataset_id": "document:1",
                    "snapshot_id": "snapshot-1",
                }
            },
        },
    )


def test_report_renders_adaptive_steps_and_deduplicated_citation():
    report = build_spatial_strategy_report(_request())

    assert report["title"] == "测试项目空间分析报告"
    assert sum(line.startswith("## ") for line in report["markdown"].splitlines()) == 4
    assert "## 总判断" in report["markdown"]
    assert report["markdown"].index("## 总判断") < report["markdown"].index("## 1. 区域角色")
    assert "项目应承担区域节点连接角色" in report["markdown"]
    assert "### " not in report["markdown"]
    assert [citation["citation_id"] for citation in report["citations"]] == [
        "project:source-1",
        "project:source-2",
    ]
    assert report["citations"][0]["title"] == "项目材料原文"
    assert report["citations"][1]["title"] == "空间查询"
    assert report["summary"] == "项目应以可验证的空间策略形成首期行动，并以运营反馈决定后续投入。"


def test_report_removes_requests_for_unavailable_evidence():
    request = _request().model_copy(deep=True)
    request.editorial_narrative = (
        "现有空间关系支持优先改善北侧连接。游客来源和运营数据尚未取得。"
    )

    report = build_spatial_strategy_report(request)

    assert "现有空间关系支持优先改善北侧连接。" in report["markdown"]
    assert "游客来源" not in report["summary"]
    assert "运营数据" not in report["summary"]


def test_report_reads_current_step_grouped_evidence_index_without_audit_references():
    request = _request().model_copy(deep=True)
    for step in request.decision_state["steps"].values():
        step.pop("citations", None)
    request.decision_state["evidence_index"] = {
        "supply_gap": [
            {
                "citation_id": "project:gap-query",
                "title": "周边设施空间查询",
                "source_type": "project_data",
                "source_locator": "poi:aggregate",
            }
        ]
    }

    report = build_spatial_strategy_report(request)

    assert report["citations"] == [
        {
            "label": "E001",
            "citation_id": "project:gap-query",
            "title": "周边设施空间查询",
            "source_type": "project_data",
            "source_locator": "poi:aggregate",
        }
    ]


def test_report_requires_completed_report_sections():
    request = _request().model_copy(deep=True)
    request.decision_state["report_sections"] = []

    with pytest.raises(ValueError, match="report_requires_completed_sections"):
        build_spatial_strategy_report(request)


def test_report_store_writes_run_scoped_markdown(tmp_path):
    store = SpatialStrategyReportStore(tmp_path)
    path = store.write({"run_id": str(RUN_ID), "markdown": "# 报告\n"})

    assert path == tmp_path / str(RUN_ID) / "spatial-strategy-report.md"
    assert path.read_text(encoding="utf-8") == "# 报告\n"


def test_markdown_report_can_be_rendered_as_docx(tmp_path):
    markdown = tmp_path / "report.md"
    markdown.write_text("# 报告\n\n## 判断\n\n项目材料支持该方向。\n\n- 条件一\n", encoding="utf-8")

    output = write_markdown_docx(markdown, tmp_path / "report.docx")

    assert output.is_file()
    assert output.stat().st_size > 1000


def test_report_embeds_generated_visual_assets():
    request = _request().model_copy(
        update={
            "visual_assets": [
                {
                    "kind": "image",
                    "title": "路网与 POI 复合图",
                    "relative_path": "visuals/road-poi-composite.png",
                    "design": {"caption": "道路与设施关系支持优先改善连接，而不是复制普通商业。"},
                },
                {"kind": "table", "title": "项目数据汇总", "markdown": "| 数据集 | 数量 |\n|---|---:|\n| POI | 2 |"},
            ]
        }
    )
    report = build_spatial_strategy_report(request)

    assert "## 项目数据图件" in report["markdown"]
    assert "![路网与 POI 复合图](visuals/road-poi-composite.png)" in report["markdown"]
    assert "图注：道路与设施关系支持优先改善连接，而不是复制普通商业。" in report["markdown"]
    assert "| POI | 2 |" in report["markdown"]


def test_report_rejects_report_section_internal_language():
    request = _request().model_copy(deep=True)
    request.decision_state["report_sections"][1]["content"] = (
        "step_04_supply_gap 使用 decision_state 和 E001。项目材料尚未闭合，需要现场核验。"
    )

    with pytest.raises(ValueError, match="contains_internal_terms"):
        build_spatial_strategy_report(request)


def test_report_allows_real_g_numbered_road_names():
    request = _request().model_copy(deep=True)
    request.decision_state["report_sections"][0]["content"] = (
        "项目沿 G318 国道形成东西向联系，应结合现有路口组织慢行接驳。"
    )

    report = build_spatial_strategy_report(request)

    assert "G318 国道" in report["markdown"]


def test_feishu_sender_sends_summary_then_word_file(tmp_path):
    markdown = tmp_path / "spatial-strategy-report.md"
    markdown.write_text("# 报告\n", encoding="utf-8")
    document = tmp_path / "spatial-strategy-report.docx"
    document.write_bytes(b"docx")
    response = lambda payload: httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "https://open.feishu.cn/open-apis"),
    )
    client = AsyncMock()
    client.post.side_effect = [
        response({"code": 0, "tenant_access_token": "token"}),
        response({"code": 0, "data": {"message_id": "summary-id"}}),
        response({"code": 0, "data": {"file_key": "file-key"}}),
        response({"code": 0, "data": {"message_id": "file-id"}}),
    ]
    sender = FeishuReportSender(
        FeishuConfig("app", "secret", "chat", "https://open.feishu.cn/open-apis"),
        client=client,
    )

    result = asyncio.run(
        sender.deliver(
            report={"title": "测试报告", "summary": "结论", "citations": [{}]},
            markdown_path=markdown,
            document_path=document,
        )
    )

    assert result["summary_message_id"] == "summary-id"
    assert result["file_message_id"] == "file-id"
    assert result["file_name"] == "spatial-strategy-report.docx"
    assert client.post.call_args_list[2].kwargs["data"]["file_name"] == "spatial-strategy-report.docx"
    assert client.post.await_count == 4
