from __future__ import annotations

import json

import pytest

import modules.spatial_action.spatial_tool_agent as spatial_tool_agent
from modules.agent_harness import CodexHarnessError


def test_spatial_tool_agent_uses_only_deterministic_spatial_computation(monkeypatch):
    captured = {}
    expected = {
        "question": "主要公共使用来源和空间联系集中在哪些方向？",
        "subquestions": [
            {
                "question": "人口、设施、夜光与路网的方向分布如何？",
                "analysis": "direction",
                "fact_domains": ["population", "poi", "nightlight", "road"],
                "evidence_dimensions": [
                    "population.scale", "poi.supply", "nightlight.intensity", "road.to_movement",
                ],
                "finding": "北侧人口和路网较强，南侧设施较集中。",
                "computation_refs": ["spatial:test-direction"],
            },
            {
                "question": "人口与设施高值是否共同出现？",
                "analysis": "relationship",
                "fact_domains": ["population", "poi"],
                "evidence_dimensions": ["population.scale", "poi.supply"],
                "finding": "共同高值单元有限。",
                "computation_refs": ["spatial:test-relationship"],
            },
        ],
        "synthesis": "主要联系方向并不单一。",
        "spatial_implications": ["分别组织北侧联系和南侧服务承接。"],
        "unresolved": [],
    }

    def fake_run_codex(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(spatial_tool_agent, "run_codex", fake_run_codex)

    result = spatial_tool_agent.analyze_spatial_question(
        history_id="history-1",
        question="主要公共使用来源和空间联系集中在哪些方向？",
    )

    assert result == expected
    assert captured["enabled_tools"] == ["compute_spatial_evidence"]
    assert "拆成必要的空间子问题" in captured["prompt"]
    assert "复杂问题应拆分并进行多次互补计算" in captured["prompt"]
    assert "不要选择或枚举底层指标" in captured["prompt"]
    assert "population_age_5_19" not in captured["prompt"]
    assert "夜光描述夜间活动背景，不替代客流、消费或具体业态" in captured["prompt"]
    assert "路网结构描述连接、到达潜力和穿行潜力，不等于实际交通量" in captured["prompt"]
    assert "不要用scope总量回答方向、可达性或局部关系问题" in captured["prompt"]
    assert "具名对象" in captured["prompt"]
    assert "已有record_ref调用inspect" in captured["prompt"]
    assert "history-1" in captured["prompt"]
    assert captured["schema_path"] == spatial_tool_agent.SPATIAL_ANALYSIS_SCHEMA_PATH


def test_spatial_tool_agent_schema_separates_computation_from_synthesis():
    schema = json.loads(spatial_tool_agent.SPATIAL_ANALYSIS_SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["required"] == ["question", "subquestions", "synthesis", "spatial_implications", "unresolved"]
    subquestion = schema["$defs"]["subquestion"]
    assert set(subquestion["required"]) == {
        "question", "analysis", "fact_domains", "evidence_dimensions", "finding", "computation_refs",
    }
    assert "metric_ids" not in json.dumps(schema)
    assert "evidence_domains" not in json.dumps(schema)
    assert set(subquestion["properties"]["fact_domains"]["items"]["enum"]) == {
        "poi", "population", "nightlight", "road",
    }
    assert subquestion["properties"]["computation_refs"]["items"]["pattern"] == "^spatial:.+"
    assert subquestion["properties"]["computation_refs"]["minItems"] == 1


def test_spatial_tool_agent_schema_avoids_gateway_incompatible_unique_items():
    schema_text = spatial_tool_agent.SPATIAL_ANALYSIS_SCHEMA_PATH.read_text(encoding="utf-8")

    assert "uniqueItems" not in schema_text


def test_spatial_tool_agent_rejects_empty_inputs_before_harness():
    with pytest.raises(ValueError, match="history_id_required"):
        spatial_tool_agent.analyze_spatial_question(history_id="", question="方向如何？")
    with pytest.raises(ValueError, match="question_required"):
        spatial_tool_agent.analyze_spatial_question(history_id="history-1", question="  ")


def test_spatial_tool_agent_propagates_harness_failure_as_domain_failure(monkeypatch):
    def unavailable(**_kwargs):
        raise CodexHarnessError("data_source_unavailable")

    monkeypatch.setattr(spatial_tool_agent, "run_codex", unavailable)

    with pytest.raises(spatial_tool_agent.SpatialToolAgentError, match="data_source_unavailable"):
        spatial_tool_agent.analyze_spatial_question(history_id="history-1", question="方向如何？")
