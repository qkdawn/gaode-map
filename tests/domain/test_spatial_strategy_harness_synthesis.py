from __future__ import annotations

import json

import pytest

from modules.spatial_strategy import harness_synthesis


def _chapter(unit_id: str, title: str) -> dict:
    return {
        "unit_id": unit_id,
        "title": title,
        "content": "明确判断。\n\n### 行动\n\n实施首期动作。",
        "citations": [],
    }


def test_chapter_schema_is_the_only_four_field_unit_contract():
    schema = json.loads(harness_synthesis.CHAPTER_SCHEMA_PATH.read_text(encoding="utf-8"))

    assert set(schema["properties"]) == {"unit_id", "title", "content", "citations"}
    assert set(schema["required"]) == {"unit_id", "title", "content", "citations"}
    assert schema["additionalProperties"] is False
    serialized = json.dumps(schema)
    assert "decision_result" not in serialized
    assert "decision_memo" not in serialized
    assert "report_blueprint" not in serialized


def test_harness_uses_codex_normalized_mcp_server_identifier():
    from modules.agent_harness import codex as codex_harness

    config = codex_harness._sdk_config(["project_context"])
    overrides = "\n".join(config.config_overrides)

    assert "mcp_servers.spatial_project.enabled_tools" in overrides
    assert "mcp_servers.spatial-project" not in overrides


def test_unit_writes_delivery_chapter_and_reads_only_declared_dependencies(monkeypatch):
    captured = {}

    def fake_run_codex(**kwargs):
        captured.update(kwargs)
        output = _chapter("audience_use", "客群与使用")
        calls = [{
            "name": "read_strategy_chapters",
            "arguments": {
                "run_id": "7b8ab959-c0e2-4d29-8168-9688cb4989bf",
                "unit_ids": ["supply_gap"],
            },
            "status": "completed",
            "result": {"chapters": [_chapter("supply_gap", "具名供给与服务空位")]},
        }]
        kwargs["tool_call_validator"](calls)
        kwargs["output_validator"](output, calls)
        return output

    monkeypatch.setattr(harness_synthesis, "run_codex", fake_run_codex)

    result = harness_synthesis.analyze_strategy_unit(
        run_id="7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        history_id="history-1",
        project_question="形成空间策略",
        decision_unit={
            "unit_id": "audience_use",
            "title": "客群与使用",
            "question": "优先服务谁",
            "depends_on": ["supply_gap"],
            "decision_output": "明确客群和使用情境",
            "evidence_focus": "人口与服务",
            "spatial_questions": ["日常服务关系如何"],
        },
    )

    assert result == _chapter("audience_use", "客群与使用")
    assert captured["schema_path"] == harness_synthesis.CHAPTER_SCHEMA_PATH
    assert "read_strategy_chapters" in captured["enabled_tools"]
    assert '["supply_gap"]' in captured["prompt"]
    assert "直接撰写可交付的 Markdown 章节正文" in captured["prompt"]
    assert "只写当前任务新增的判断" in captured["prompt"]
    assert "computed:population:summary" not in captured["prompt"]
    assert "市场流向" not in captured["prompt"]


def test_first_unit_cannot_read_other_chapters(monkeypatch):
    captured = {}

    def fake_run_codex(**kwargs):
        captured.update(kwargs)
        return _chapter("project_basis", "项目材料与项目基础")

    monkeypatch.setattr(harness_synthesis, "run_codex", fake_run_codex)
    harness_synthesis.analyze_strategy_unit(
        run_id="7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        history_id="history-1",
        project_question="形成空间策略",
        decision_unit={
            "unit_id": "project_basis",
            "title": "项目材料与项目基础",
            "question": "材料说明什么",
            "depends_on": [],
        },
    )

    assert "read_strategy_chapters" not in captured["enabled_tools"]
    assert "不要调用 read_strategy_chapters" in captured["prompt"]


def test_unit_without_spatial_questions_cannot_reopen_spatial_results(monkeypatch):
    captured = {}

    def fake_run_codex(**kwargs):
        captured.update(kwargs)
        return _chapter("positioning", "候选定位比较")

    monkeypatch.setattr(harness_synthesis, "run_codex", fake_run_codex)
    harness_synthesis.analyze_strategy_unit(
        run_id="7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        history_id="history-1",
        project_question="形成空间策略",
        decision_unit={
            "unit_id": "positioning",
            "title": "候选定位比较",
            "question": "选择哪个定位",
            "depends_on": ["regional_role", "supply_gap", "audience_use", "theme_resources"],
            "spatial_questions": [],
        },
    )

    assert "read_strategy_chapters" in captured["enabled_tools"]
    assert "analyze_spatial_question" not in captured["enabled_tools"]
    assert "read_spatial_evidence_result" not in captured["enabled_tools"]
    assert "本章没有新增空间问题" in captured["prompt"]
    assert "不在 citations 中复制 computed:population:summary" in captured["prompt"]


@pytest.mark.parametrize("status", ["invalid_request", "not_found", "unavailable", "partial", "failed", "data_source_unavailable"])
def test_completed_tool_failure_status_stops_the_strategy_run(status):
    with pytest.raises(
        harness_synthesis.SpatialStrategyHarnessError,
        match=rf"strategy_tool_failed:project_context:{status}:\$\.status",
    ):
        harness_synthesis._validate_strategy_tool_results(
            [{"name": "project_context", "status": "completed", "result": {"status": status}}]
        )


def test_nested_catalog_status_does_not_turn_a_successful_tool_call_into_failure():
    harness_synthesis._validate_strategy_tool_results(
        [{
            "name": "mcp__spatial_project__project_context",
            "status": "completed",
            "result": {
                "computed_results": [
                    {"status": "available"},
                    {"status": "not_found"},
                ]
            },
        }]
    )


def test_recovered_argument_validation_failure_is_ignored():
    harness_synthesis._validate_strategy_tool_results(
        [
            {
                "name": "analyze_spatial_question",
                "status": "failed",
                "result": {"status": "invalid_request"},
                "_recoverable_validation_failure": True,
            },
            {
                "name": "analyze_spatial_question",
                "status": "completed",
                "result": {"status": "available"},
            },
        ]
    )


def test_unrecovered_argument_validation_failure_stops_the_run():
    with pytest.raises(harness_synthesis.SpatialStrategyHarnessError, match="invalid_request"):
        harness_synthesis._validate_strategy_tool_results(
            [{
                "name": "analyze_spatial_question",
                "status": "failed",
                "result": {"status": "invalid_request"},
                "_recoverable_validation_failure": True,
            }]
        )


def test_chapter_identity_is_enforced():
    validator = harness_synthesis._chapter_output_validator("audience_use", "客群与使用")

    with pytest.raises(harness_synthesis.SpatialStrategyHarnessError, match="unit_id_mismatch"):
        validator(_chapter("supply_gap", "客群与使用"), [])
    with pytest.raises(harness_synthesis.SpatialStrategyHarnessError, match="title_mismatch"):
        validator(_chapter("audience_use", "其他标题"), [])


def test_only_audience_chapter_owns_demographic_summary_citation():
    citation = {
        "citation_id": "C1",
        "title": "人口汇总",
        "source_type": "project_dataset_summary",
        "source_locator": "computed:population:summary",
        "record_ref": "computed:population:summary",
    }
    audience = _chapter("audience_use", "客群与使用")
    audience["citations"] = [citation]
    harness_synthesis._chapter_output_validator("audience_use", "客群与使用")(
        audience, []
    )

    product = _chapter("product_mix", "场景与产品组合")
    product["citations"] = [citation]
    with pytest.raises(
        harness_synthesis.SpatialStrategyHarnessError,
        match="demographic_evidence_not_owned",
    ):
        harness_synthesis._chapter_output_validator(
            "product_mix", "场景与产品组合"
        )(product, [])


def test_population_spatial_evidence_remains_available_outside_audience_chapter():
    output = _chapter("supply_gap", "具名供给与服务空位")
    output["citations"] = [{
        "citation_id": "S1",
        "title": "人口与供给空间关系",
        "source_type": "spatial_evidence_result",
        "source_locator": "spatial:population-supply-gap",
        "record_ref": "spatial:population-supply-gap",
    }]

    harness_synthesis._chapter_output_validator(
        "supply_gap", "具名供给与服务空位"
    )(output, [])


@pytest.mark.parametrize("content", [
    "无法生成本章节：空间工具执行失败。",
    "无法完成本章节：项目材料读取失败。",
])
def test_failure_explanation_is_not_a_deliverable_chapter(content):
    validator = harness_synthesis._chapter_output_validator("audience_use", "客群与使用")
    output = _chapter("audience_use", "客群与使用")
    output["content"] = content

    with pytest.raises(harness_synthesis.SpatialStrategyHarnessError, match="generation_failed"):
        validator(output, [])


def test_visual_design_reads_all_chapters_once_without_blueprint(monkeypatch):
    captured = {}

    def fake_run_codex(**kwargs):
        captured.update(kwargs)
        kwargs["tool_call_validator"]([{
            "name": "read_strategy_chapters",
            "arguments": {
                "run_id": "7b8ab959-c0e2-4d29-8168-9688cb4989bf",
                "unit_ids": list(harness_synthesis.STRATEGY_UNIT_IDS),
            },
            "status": "completed",
            "result": {"chapters": []},
        }])
        return {"visuals": []}

    monkeypatch.setattr(harness_synthesis, "run_codex", fake_run_codex)
    harness_synthesis.design_strategy_visuals(
        run_id="7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        project_question="形成空间策略",
        visual_task="设计图件",
    )

    assert captured["enabled_tools"].count("read_strategy_chapters") == 1
    assert "read_strategy_blueprint" not in captured["enabled_tools"]
    assert "read_strategy_decisions" not in captured["enabled_tools"]
    assert "这11个已完成章节" in captured["prompt"]
    assert "poi 图层，必须同时包含 road_edges 图层" in captured["prompt"]


def test_unit_dependency_reader_rejects_full_history_scope():
    validator = harness_synthesis._strategy_tool_validator(
        run_id="7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        required_chapter_ids=["supply_gap"],
    )
    with pytest.raises(harness_synthesis.SpatialStrategyHarnessError, match="scope_mismatch"):
        validator([{
            "name": "read_strategy_chapters",
            "arguments": {
                "run_id": "7b8ab959-c0e2-4d29-8168-9688cb4989bf",
                "unit_ids": list(harness_synthesis.STRATEGY_UNIT_IDS),
            },
            "status": "completed",
            "result": {"chapters": []},
        }])


def test_unit_rejects_project_tool_call_for_another_history():
    validator = harness_synthesis._strategy_tool_validator(
        run_id="7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        history_id="history-1",
        required_chapter_ids=[],
    )

    with pytest.raises(
        harness_synthesis.SpatialStrategyHarnessError,
        match="strategy_tool_history_scope_mismatch:project_context",
    ):
        validator([{
            "name": "mcp__spatial_project__project_context",
            "arguments": {"history_id": "wrong-history"},
            "status": "completed",
            "result": {"status": "not_found"},
        }])


def test_harness_preserves_domain_validation_failure_detail(monkeypatch, tmp_path):
    from modules.agent_harness import codex as codex_harness

    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps({"type": "object"}), encoding="utf-8")

    class FakeTurn:
        items = []
        final_response = "{}"

    class FakeThread:
        def run(self, *_args, **_kwargs):
            return FakeTurn()

    class FakeCodex:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def thread_start(self, **_kwargs):
            return FakeThread()

    monkeypatch.setattr(codex_harness, "Codex", FakeCodex)

    def reject(_calls):
        raise RuntimeError("strategy_tool_failed:read_project_document:not_found:$.status")

    with pytest.raises(
        codex_harness.CodexHarnessError,
        match=r"strategy_tool_failed:read_project_document:not_found:\$\.status",
    ):
        codex_harness.run_codex(
            prompt="task",
            schema_path=schema_path,
            enabled_tools=[],
            tool_call_validator=reject,
        )


def test_visual_schema_uses_strategy_unit_ids():
    schema = json.loads(harness_synthesis.VISUAL_DESIGN_SCHEMA_PATH.read_text(encoding="utf-8"))
    section_ids = schema["properties"]["visuals"]["items"]["properties"]["section_id"]["enum"]

    assert section_ids == list(harness_synthesis.STRATEGY_UNIT_IDS)
    assert "audience_use" in section_ids
