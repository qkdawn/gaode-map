from __future__ import annotations

import asyncio
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from docx import Document
from docx.oxml.ns import qn

from modules.spatial_strategy.reporting import (
    FeishuConfig,
    FeishuReportSender,
    SpatialStrategyReportStore,
    build_spatial_strategy_report,
    compose_spatial_strategy_report,
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
        {
            "citation_id": "project:source-1",
            "title": "项目材料原文",
            "source_type": "project_document",
            "source_locator": "项目材料：第 1 页",
            "dataset_id": "document:1",
            "snapshot_id": "snapshot-1",
        },
        {"citation_id": "project:source-2", "title": "空间查询", "source_type": "project_data"},
    ]
    return SpatialStrategyReportFinalizeRequest(
        run_id=RUN_ID,
        history_id="history-1",
        project_question="判断项目空间策略",
        project_context={"project": {"name": "测试项目"}},
        editorial_narrative="项目应以社区日常使用为底盘，以文化协作为增量，先形成连续可达的公共空间骨架。",
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
        },
    )


def test_report_renders_adaptive_steps_and_deduplicated_citation():
    report = build_spatial_strategy_report(_request())

    assert report["title"] == "测试项目空间策略与行动方案"
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
    assert report["summary"] == "项目应以社区日常使用为底盘，以文化协作为增量，先形成连续可达的公共空间骨架。"


def test_report_uses_project_question_when_saved_scope_name_is_generic():
    request = _request().model_copy(deep=True)
    request.project_context["project"]["name"] = "15min - 112.9863,28.2208 - 2635 POIs"
    request.project_question = "完成长沙县人民政府原址城市更新项目的综合空间分析。"

    report = build_spatial_strategy_report(request)

    assert report["title"] == "长沙县人民政府原址城市更新项目空间策略与行动方案"
    assert report["markdown"].startswith("# 长沙县人民政府原址城市更新项目空间策略与行动方案")


def test_report_preserves_strategy_and_specific_implementation_conditions():
    request = _request().model_copy(deep=True)
    request.editorial_narrative = "现有空间关系支持优先改善北侧连接；历史建筑采用可逆改造，消防条件在具体设计中核定。"

    report = build_spatial_strategy_report(request)

    assert "现有空间关系支持优先改善北侧连接" in report["markdown"]
    assert "历史建筑采用可逆改造" in report["summary"]
    assert "消防条件在具体设计中核定" in report["summary"]


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
    markdown.write_text(
        "# 报告\n\n## 判断\n\n项目材料支持**该方向**。\n\n"
        "1. **条件一**：先核验。\n2. 条件二：再测试。\n\n"
        "新的清单：\n\n1. 新条件一。\n\n"
        "| 类型 | 行动 |\n|---|---|\n| 公共服务 | 先测试 |\n",
        encoding="utf-8",
    )

    output = write_markdown_docx(markdown, tmp_path / "report.docx")

    assert output.is_file()
    assert output.stat().st_size > 1000
    with ZipFile(output) as archive:
        settings_xml = archive.read("word/settings.xml").decode("utf-8")
    assert 'w:val="bestFit"' in settings_xml
    assert 'w:percent="100"' in settings_xml
    document = Document(output)
    paragraphs = [paragraph for paragraph in document.paragraphs if paragraph.text]
    assert all("**" not in paragraph.text for paragraph in paragraphs)
    assert any(run.text == "该方向" and run.bold for paragraph in paragraphs for run in paragraph.runs)
    assert any(run.text == "条件一" and run.bold for paragraph in paragraphs for run in paragraph.runs)
    numbered = [paragraph for paragraph in paragraphs if paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None]
    assert len(numbered) == 3
    first_num_id = numbered[0]._p.pPr.numPr.numId.val
    assert numbered[1]._p.pPr.numPr.numId.val == first_num_id
    assert numbered[2]._p.pPr.numPr.numId.val != first_num_id
    table = document.tables[0]
    assert table.rows[0]._tr.trPr.find(qn("w:tblHeader")) is not None
    assert all(row._tr.trPr.find(qn("w:cantSplit")) is not None for row in table.rows)


def test_compose_report_requires_markdown_and_docx_artifacts(tmp_path):
    store = SpatialStrategyReportStore(tmp_path)

    result = asyncio.run(compose_spatial_strategy_report(_request(), store=store))

    directory = tmp_path / str(RUN_ID)
    assert (directory / "spatial-strategy-report.md").is_file()
    assert (directory / "spatial-strategy-report.docx").is_file()
    assert result["asset_manifest"]["kind"] == "docx_report"
    assert result["asset_manifest"]["filename"] == "spatial-strategy-report.docx"
    assert result["asset_manifest"]["markdown_filename"] == "spatial-strategy-report.md"


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
