from __future__ import annotations

from modules.spatial_strategy.reader_result import project_run_detail


def _payload(status: str = "running") -> dict:
    steps = [
        {
            "step": "step_01_policy_site",
            "step_order": 1,
            "status": "completed",
            "output": {
                "title": "政策与场地",
                "reader_chapter": "项目材料与项目数据共同表明，当前应先完成安全和权属核验。现有条件尚未闭合，需要现场核验后再决定开放范围。",
            },
            "updated_at": "2026-08-09T08:00:00Z",
        },
    ]
    return {
        "run_id": "00000000-0000-4000-8000-000000000001",
        "history_id": "internal-history",
        "status": status,
        "current_step": "step_02_regional_role",
        "error": "internal_error_code",
        "created_at": "2026-08-09T08:00:00Z",
        "updated_at": "2026-08-09T08:01:00Z",
        "progress": {"completed_steps": 1, "total_steps": 12},
        "decision_state": {"steps": {}, "evidence_index": {"project:abc123": {}}},
        "steps": steps,
        "report": {
            "status": "ready",
            "markdown": "# 测试项目空间分析报告\n\n## 总判断\n先核验，再试运营。\n\n## 1. 政策与场地\n正文。\n",
            "citations": [{"citation_id": "project:abc123", "source_type": "project_document"}],
            "asset_manifest": {"visual_assets": []},
        },
    }


def test_reader_projection_hides_internal_run_fields_and_maps_chapters():
    result = project_run_detail(_payload())
    data = result.model_dump()

    assert data["status"] == "分析中"
    assert data["message"] == "正在分析第 2 章“区域角色”，已完成 1 章。"
    assert data["progress"] == {"completed_chapters": 1, "total_chapters": 12}
    assert data["chapters"][0]["status"] == "已完成"
    assert data["chapters"][0]["content"].startswith("项目材料与项目数据")
    assert data["chapters"][1]["title"] == "区域角色"
    assert "decision_state" not in data
    assert "current_step" not in data
    assert "error" not in data
    assert data["report"]["summary"] == "先核验，再试运营。"
    assert data["report"]["evidence_labels"] == ["项目材料"]


def test_reader_projection_turns_failed_run_into_actionable_message():
    result = project_run_detail(_payload("failed"))

    assert result.status == "需要处理"
    assert result.message == "第 2 章“区域角色”暂时未完成，前面的结果已保留，可从这里继续。"
    assert result.chapters[1].status == "需要处理"


def test_reader_projection_distinguishes_report_failure_after_all_chapters():
    payload = _payload("failed")
    payload["progress"]["completed_steps"] = 12
    result = project_run_detail(payload)

    assert result.message == "十二章已经完成，但报告整理暂时未通过检查，可从这里继续。"


def test_reader_projection_uses_adaptive_research_plan():
    payload = _payload()
    payload["decision_state"] = {
        "research_plan": [
            {"step_key": "decision_01", "title": "核心矛盾", "question": "项目真正要改变什么？"},
            {"step_key": "decision_02", "title": "客群机制", "question": "谁会使用并持续参与？"},
            {"step_key": "decision_03", "title": "一期验证", "question": "怎样用小规模行动改判？"},
        ]
    }
    payload["current_step"] = "decision_02"
    payload["progress"] = {"completed_steps": 1, "total_steps": 3}
    payload["steps"] = [
        {"step": "decision_01", "step_order": 1, "status": "completed", "output": {"title": "核心矛盾", "reader_chapter": "已完成。"}},
    ]

    result = project_run_detail(payload)

    assert result.progress.model_dump() == {"completed_chapters": 1, "total_chapters": 3}
    assert [chapter.title for chapter in result.chapters] == ["核心矛盾", "客群机制", "一期验证"]
    assert result.current_chapter.model_dump() == {"number": 2, "title": "客群机制"}
