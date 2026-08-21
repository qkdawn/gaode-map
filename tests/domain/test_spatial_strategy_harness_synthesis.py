from __future__ import annotations

import json
import subprocess

import modules.spatial_strategy.harness_synthesis as harness_synthesis


def test_harness_synthesis_delegates_tool_loop_and_structured_output(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        output_path = command[command.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump({"recommended_position": "公共文化客厅"}, handle, ensure_ascii=False)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(harness_synthesis.shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(harness_synthesis.subprocess, "run", fake_run)

    result = harness_synthesis.synthesize_strategy_blueprint(
        run_id="7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        project_question="形成未来空间策略",
    )

    assert result == {"recommended_position": "公共文化客厅"}
    command = captured["command"]
    assert command[:4] == ["codex", "-a", "never", "exec"]
    assert "--ephemeral" in command
    assert "--output-schema" in command
    assert "tool_suggest" in command
    assert "mcp_servers.spatial-project.enabled_tools" in " ".join(command)
    assert "max_output_tokens" not in " ".join(command)
    assert "--model" not in command
    prompt = captured["kwargs"]["input"]
    assert "read_strategy_decisions" in prompt
    assert "具名 POI、道路、路径" in prompt
    assert "7b8ab959-c0e2-4d29-8168-9688cb4989bf" in prompt
    assert "decision_inputs" not in prompt
    assert "decision_memo" not in prompt
    assert "工具调用失败后重试" not in prompt


def test_harness_failure_is_a_run_failure(monkeypatch):
    monkeypatch.setattr(harness_synthesis.shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(
        harness_synthesis.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "network unavailable"),
    )

    try:
        harness_synthesis.synthesize_strategy_blueprint(run_id="run", project_question="task")
    except harness_synthesis.SpatialStrategyHarnessError as exc:
        assert "network unavailable" in str(exc)
    else:
        raise AssertionError("Codex failure must propagate")


def test_harness_output_directory_is_owned_by_project_runtime():
    assert harness_synthesis.HARNESS_RUNTIME_ROOT == harness_synthesis.PROJECT_ROOT / "runtime" / "codex-harness"


def test_blueprint_schema_contains_domain_output_without_unit_provenance():
    schema = json.loads(harness_synthesis.BLUEPRINT_SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["sections"]["minItems"] == 5
    section = schema["properties"]["sections"]["items"]
    assert "current_basis" in section["properties"]
    assert "future_goal" in section["properties"]
    assert "named_entities" in schema["properties"]
    named_entity = schema["$defs"]["named_entity"]
    assert named_entity["required"] == ["name", "entity_type", "relationship", "fact"]
    assert "source_unit_ids" not in section["properties"]
    assert "decision_state" not in json.dumps(schema)


def test_unit_and_report_prompts_keep_concrete_spatial_objects(monkeypatch):
    calls = []

    def fake_run_codex(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(harness_synthesis, "_run_codex", fake_run_codex)

    harness_synthesis.analyze_strategy_unit(
        run_id="7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        history_id="history-1",
        project_question="形成未来空间策略",
        decision_unit={"unit_id": "current_structure", "title": "现状结构"},
    )
    harness_synthesis.write_strategy_section(
        project_question="形成未来空间策略",
        solution={"named_entities": [{"name": "潘家坪路"}]},
        section={"section_id": "spatial_layout"},
    )
    harness_synthesis.design_strategy_visuals(
        project_question="形成未来空间策略",
        solution={"named_entities": [{"name": "潘家坪路"}]},
        available_datasets=[{"dataset_id": "poi"}, {"dataset_id": "road_edges"}],
    )

    assert "named_entities" in calls[0]["prompt"]
    assert "analyze_spatial_question" in calls[0]["prompt"]
    assert "analyze_spatial_question" in calls[0]["enabled_tools"]
    assert "analyze_spatial_evidence" not in calls[0]["enabled_tools"]
    assert "真实名称" in calls[0]["prompt"]
    assert "所在城市或区县 + 准确名称 + 待确认属性" in calls[0]["prompt"]
    assert "不逐个搜索无关对象" in calls[0]["prompt"]
    assert "不退化为只有方向和汇总数量" in calls[1]["prompt"]
    assert "至少设计一张 poi_access 或 context_full" in calls[2]["prompt"]


def test_decision_schema_preserves_named_objects_without_harness_state():
    schema = json.loads(harness_synthesis.DECISION_MEMO_SCHEMA_PATH.read_text(encoding="utf-8"))

    assert "named_entities" in schema["required"]
    named_entity = schema["$defs"]["named_entity"]
    assert named_entity["required"] == ["name", "entity_type", "relationship", "fact", "record_ref"]
    serialized = json.dumps(schema)
    for runtime_field in ("tool_name", "response_id", "call_id", "retry_count"):
        assert runtime_field not in serialized
