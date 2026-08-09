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
from modules.spatial_strategy.schemas import SpatialStrategyReportFinalizeRequest


RUN_ID = UUID("31d81c16-1bfc-4bf6-a9e8-cfa36d0a4df2")


def _request() -> SpatialStrategyReportFinalizeRequest:
    steps = {}
    for index, key in enumerate(
        (
            "step_01_policy_site",
            "step_02_regional_role",
            "step_03_market_flow",
            "step_04_supply_gap",
            "step_05_audience_use",
            "step_06_theme_resources",
            "step_07_positioning",
            "step_08_product_mix",
            "step_09_spatial_layout",
            "step_10_operating_model",
            "step_11_financial_check",
            "step_12_phasing",
        ),
        1,
    ):
        steps[key] = {
            "title": key,
            "reader_chapter": f"第 {index} 个章节说明项目材料、项目数据和空间数据支持的判断。当前条件尚未完全闭合，需要现场核验后再决定下一步。" * 2,
        }
    return SpatialStrategyReportFinalizeRequest(
        run_id=RUN_ID,
        history_id="history-1",
        project_question="判断项目空间策略",
        project_context={"project": {"name": "测试项目"}},
        editorial_narrative="项目应以可验证的空间策略形成首期行动，并以运营反馈决定后续投入。",
        decision_state={
            "steps": steps,
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


def test_report_contains_all_twelve_steps_and_deduplicated_citation():
    report = build_spatial_strategy_report(_request())

    assert report["title"] == "测试项目空间分析报告"
    assert sum(line.startswith("## ") for line in report["markdown"].splitlines()) == 13
    assert "## 总判断" in report["markdown"]
    assert report["markdown"].index("## 总判断") < report["markdown"].index("## 1. 政策与场地")
    assert "第 1 个章节说明项目材料" in report["markdown"]
    assert "### " not in report["markdown"]
    assert report["citations"] == []
    assert report["summary"] == "项目应以可验证的空间策略形成首期行动，并以运营反馈决定后续投入。"


def test_report_store_writes_run_scoped_markdown(tmp_path):
    store = SpatialStrategyReportStore(tmp_path)
    path = store.write({"run_id": str(RUN_ID), "markdown": "# 报告\n"})

    assert path == tmp_path / str(RUN_ID) / "spatial-strategy-report.md"
    assert path.read_text(encoding="utf-8") == "# 报告\n"


def test_report_embeds_generated_visual_assets():
    request = _request().model_copy(
        update={
            "visual_assets": [
                {"kind": "image", "title": "路网与 POI 复合图", "relative_path": "visuals/road-poi-composite.png"},
                {"kind": "table", "title": "项目数据汇总", "markdown": "| 数据集 | 数量 |\n|---|---:|\n| POI | 2 |"},
            ]
        }
    )
    report = build_spatial_strategy_report(request)

    assert "## 项目数据图件" in report["markdown"]
    assert "![路网与 POI 复合图](visuals/road-poi-composite.png)" in report["markdown"]
    assert "| POI | 2 |" in report["markdown"]


def test_report_rejects_reader_chapter_internal_language():
    request = _request().model_copy(deep=True)
    request.decision_state["steps"]["step_04_supply_gap"]["reader_chapter"] = (
        "step_04_supply_gap 使用 decision_state 和 E001。项目材料尚未闭合，需要现场核验。"
    )

    with pytest.raises(ValueError, match="contains_internal_terms"):
        build_spatial_strategy_report(request)


def test_feishu_sender_sends_summary_then_markdown_file(tmp_path):
    markdown = tmp_path / "spatial-strategy-report.md"
    markdown.write_text("# 报告\n", encoding="utf-8")
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
        )
    )

    assert result["summary_message_id"] == "summary-id"
    assert result["file_message_id"] == "file-id"
    assert client.post.await_count == 4
