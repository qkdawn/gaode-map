from modules.spatial_strategy.mcp_agent import _ALLOWED_TOOLS, read_previous_chapter


def test_spatial_strategy_agent_allows_project_and_public_web_tools():
    assert _ALLOWED_TOOLS == {
        "analyze_spatial_evidence",
        "read_project_document",
        "read_previous_chapter",
        "search_literature_evidence",
        "search_public_web",
        "fetch_public_web_page",
    }


def test_read_previous_chapter_returns_decision_memory_with_full_text():
    result = read_previous_chapter(
        decision_state={
            "steps": {
                "step_05_audience_use": {
                    "step_key": "step_05_audience_use",
                    "step_order": 5,
                    "title": "客群与使用",
                    "research_brief": "比较候选客群及其使用机制。",
                    "decision_brief": "一期先验证本地家庭与青年共同使用，游客是条件性增量。",
                    "reader_chapter": "完整客群分析正文。",
                }
            }
        },
        current_step_order=8,
        step_key="step_05_audience_use",
    )

    assert result["decision_brief"] == "一期先验证本地家庭与青年共同使用，游客是条件性增量。"
    assert result["research_brief"] == "比较候选客群及其使用机制。"
    assert result["reader_chapter"] == "完整客群分析正文。"
