from __future__ import annotations

from modules.spatial_strategy.reader_result import project_run_detail


def _payload(status: str = "running") -> dict:
    decision_units = [
        {
            "unit_id": "site_role",
            "title": "项目与区域角色",
            "question": "项目在区域中应承担什么角色？",
            "depends_on": [],
            "decision_output": "确定区域角色",
            "evidence_focus": "项目文档与周边空间关系",
        },
        {
            "unit_id": "named_connections",
            "title": "具名节点连接",
            "question": "应连接哪些具体设施和道路？",
            "depends_on": ["site_role"],
            "decision_output": "确定连接对象",
            "evidence_focus": "具名 POI、道路和节点关系",
        },
        {
            "unit_id": "first_actions",
            "title": "首期行动",
            "question": "首期如何形成最小闭环？",
            "depends_on": ["named_connections"],
            "decision_output": "形成首期行动组合",
            "evidence_focus": "前序判断及项目条件",
        },
    ]
    steps = [
        {
            "step": "site_role",
            "step_order": 1,
            "status": "completed",
            "output": {
                "title": "项目与区域角色",
                "decision_memo": {
                    "decision": "项目应作为区域节点之间的连接载体。",
                    "reasoning": "项目文档和空间数据支持该判断。",
                },
            },
            "updated_at": "2026-08-09T08:00:00Z",
        },
    ]
    return {
        "run_id": "00000000-0000-4000-8000-000000000001",
        "status": status,
        "current_step": "named_connections",
        "created_at": "2026-08-09T08:00:00Z",
        "updated_at": "2026-08-09T08:01:00Z",
        "progress": {"completed_steps": 1, "total_steps": 3},
        "decision_state": {"decision_units": decision_units},
        "steps": steps,
        "report": {
            "status": "ready",
            "markdown": "# 测试项目空间分析报告\n\n## 总判断\n先连接具名节点，再组织首期行动。\n\n## 1. 区域角色\n正文。\n",
            "citations": [{"citation_id": "project:abc123", "source_type": "project_document"}],
            "asset_manifest": {"visual_assets": []},
        },
    }


def test_reader_projection_uses_dynamic_decision_units():
    result = project_run_detail(_payload())
    data = result.model_dump()

    assert data["status"] == "分析中"
    assert data["message"] == "正在分析第 2 个决策单元“具名节点连接”，已完成 1 / 3 个分析单元。"
    assert data["progress"] == {"completed_chapters": 1, "total_chapters": 3}
    assert data["chapters"][0]["status"] == "已完成"
    assert data["chapters"][0]["content"].startswith("项目应作为区域节点")
    assert data["chapters"][1]["title"] == "具名节点连接"
    assert data["current_chapter"] == {"number": 2, "title": "具名节点连接"}
    assert "decision_state" not in data
    assert "current_step" not in data
    assert data["report"]["summary"] == "先连接具名节点，再组织首期行动。"


def test_reader_projection_turns_failed_unit_into_actionable_message():
    result = project_run_detail(_payload("failed"))

    assert result.status == "需要处理"
    assert result.message == "第 2 个决策单元“具名节点连接”暂时未完成，前面的结果已保留，可从这里继续。"
    assert result.chapters[1].status == "需要处理"


def test_reader_projection_distinguishes_report_failure_after_all_units():
    payload = _payload("failed")
    payload["progress"]["completed_steps"] = 3
    result = project_run_detail(payload)

    assert result.message == "决策单元已经完成，但报告整理暂时未通过检查，可从这里继续。"


def test_reader_projection_has_no_fixed_twelve_unit_fallback():
    payload = _payload()
    payload["decision_state"] = {}
    payload["steps"] = []
    payload["current_step"] = "planning"
    payload["progress"] = {"completed_steps": 0, "total_steps": 1}

    result = project_run_detail(payload)

    assert result.chapters == []
    assert result.current_chapter is None
    assert result.progress.total_chapters == 1
