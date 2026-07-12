from modules.agent.capability_intent import resolve_capability_intent


def test_explicit_capability_request_opens_configuration_without_guessing_execution():
    resolution = resolve_capability_intent("请基于当前项目生成空间功能策划决策矩阵")

    assert resolution.matched is True
    assert resolution.capability_id == "spatial-programming-matrix"
    assert resolution.action == "open_configuration"
    assert resolution.matched_phrase == "生成空间功能策划决策矩阵"


def test_unavailable_capability_intent_returns_authoritative_explanation():
    resolution = resolve_capability_intent("现在生成 RSIR 商业分析")

    assert resolution.matched is True
    assert resolution.capability_id == "rsir-business-analysis"
    assert resolution.action == "explain_unavailable"
    assert "不能用普通 Agent 代替执行" in resolution.reason


def test_ordinary_questions_stay_in_conversation():
    resolution = resolve_capability_intent("PPT 的证据引用应该怎么组织？")

    assert resolution.matched is False
    assert resolution.action == "none"
    assert resolution.capability_id == ""
