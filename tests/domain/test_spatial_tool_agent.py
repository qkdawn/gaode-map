from __future__ import annotations

import json

import pytest

import modules.spatial_action.spatial_tool_agent as spatial_tool_agent
from modules.agent_harness import CodexHarnessError


def test_spatial_tool_agent_uses_only_deterministic_spatial_computation(monkeypatch):
    captured = []
    plan = {
        "question": "主要公共使用来源和空间联系集中在哪些方向？",
        "subquestions": [
            {
                "question": "人口、设施、夜光与路网的方向分布如何？",
                "analysis": "direction",
                "fact_domains": ["population", "poi", "nightlight", "road"],
                "evidence_dimensions": [
                    "population.scale", "poi.supply", "nightlight.intensity", "road.to_movement",
                ],
            },
            {
                "question": "人口与设施高值是否共同出现？",
                "analysis": "relationship",
                "fact_domains": ["population", "poi"],
                "evidence_dimensions": ["population.scale", "poi.supply"],
            },
        ],
    }
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
        captured.append(kwargs)
        return plan if len(captured) == 1 else expected

    monkeypatch.setattr(spatial_tool_agent, "run_codex", fake_run_codex)

    result = spatial_tool_agent.analyze_spatial_question(
        history_id="history-1",
        question="主要公共使用来源和空间联系集中在哪些方向？",
    )

    assert result == expected
    assert len(captured) == 2
    assert captured[0]["enabled_tools"] == []
    assert captured[1]["enabled_tools"] == ["compute_spatial_evidence", "compute_spatial_evidence_batch"]
    assert callable(captured[1]["tool_call_validator"])
    assert callable(captured[1]["output_validator"])
    assert "拆成必要的空间子问题" in captured[0]["prompt"]
    assert "不要选择或枚举底层指标" in captured[0]["prompt"]
    assert "population_age_5_19" not in captured[0]["prompt"]
    assert "夜光只描述保存等时圈内的亮度构成及空间差异" in captured[0]["prompt"]
    assert "路网结构描述连接、到达潜力和穿行潜力，不等于实际交通量" in captured[0]["prompt"]
    assert "具名地点或道路" in captured[1]["prompt"]
    assert "已有record_ref调用inspect" in captured[1]["prompt"]
    assert "彼此独立且不依赖 record_refs" in captured[1]["prompt"]
    assert "history-1" in captured[1]["prompt"]
    assert "问题拆解计划" in captured[1]["prompt"]
    assert captured[0]["schema_path"] == spatial_tool_agent.SPATIAL_PLAN_SCHEMA_PATH
    assert captured[1]["schema_path"] == spatial_tool_agent.SPATIAL_ANALYSIS_SCHEMA_PATH


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


def test_deterministic_plan_preserves_requested_named_poi_roles():
    plan = spatial_tool_agent._deterministic_plan(
        "请求 regional_anchor 和 daily_service 具名POI候选，比较设施节点。"
    )

    assert plan[0]["named_poi_roles"] == ["regional_anchor", "daily_service"]


def test_spatial_tool_agent_propagates_harness_failure_as_domain_failure(monkeypatch):
    def unavailable(**_kwargs):
        raise CodexHarnessError("data_source_unavailable")

    monkeypatch.setattr(spatial_tool_agent, "run_codex", unavailable)

    with pytest.raises(spatial_tool_agent.SpatialToolAgentError, match="data_source_unavailable"):
        spatial_tool_agent.analyze_spatial_question(history_id="history-1", question="方向如何？")


def test_spatial_plan_is_bounded_and_drops_unresolvable_record_placeholders():
    plan = {
        "question": "区域角色",
        "subquestions": [
            {"question": f"问题 {index}", "analysis": "scope", "fact_domains": ["poi"], "evidence_dimensions": ["poi.supply"], "record_refs": ["regional_anchor_candidates"]}
            for index in range(spatial_tool_agent.MAX_SPATIAL_SUBQUESTIONS + 2)
        ],
    }

    bounded = spatial_tool_agent._bound_spatial_plan(plan)

    assert len(bounded["subquestions"]) == spatial_tool_agent.MAX_SPATIAL_SUBQUESTIONS
    assert bounded["subquestions"][0]["record_refs"] == []


def _planned_rank():
    return {
        "question": "人口最多的两个网格是哪些？",
        "subquestions": [{
            "question": "人口网格按人数从高到低如何排列？",
            "analysis": "rank",
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.scale"],
            "selectors": [{"dimension": "population.measure", "values": ["count"]}],
            "rank_order": "highest",
            "top_k": 2,
        }],
    }


def _rank_call(*, result_id="spatial:rank-real", top_k=2):
    return {
        "name": "compute_spatial_evidence",
        "arguments": {
            "history_id": "history-1",
            "analysis": "rank",
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.scale"],
            "selectors": [{"dimension": "population.measure", "values": ["count"]}],
            "rank_order": "highest",
            "top_k": top_k,
        },
        "status": "completed",
        "result": {"result_id": result_id, "status": "available"},
    }


def test_plan_tool_call_validator_enforces_planned_parameters():
    validator = spatial_tool_agent._plan_tool_call_validator(_planned_rank(), history_id="history-1")

    validator([_rank_call()])

    with pytest.raises(spatial_tool_agent.SpatialToolAgentError, match="spatial_plan_parameter_mismatch:top_k"):
        validator([_rank_call(top_k=5)])
    with pytest.raises(spatial_tool_agent.SpatialToolAgentError, match="spatial_plan_without_tool_call"):
        validator([])


def test_plan_tool_call_validator_rejects_unplanned_non_default_parameters():
    plan = _planned_rank()
    subquestion = dict(plan["subquestions"][0])
    subquestion.pop("top_k")
    subquestion.pop("rank_order")
    plan["subquestions"] = [subquestion]
    validator = spatial_tool_agent._plan_tool_call_validator(plan, history_id="history-1")
    call = _rank_call(top_k=10)
    call["arguments"].pop("rank_order")

    validator([call])

    call["arguments"]["top_k"] = 5
    with pytest.raises(spatial_tool_agent.SpatialToolAgentError, match="spatial_plan_parameter_mismatch:top_k"):
        validator([call])


@pytest.mark.parametrize(
    ("field", "planned", "changed"),
    [
        (
            "selectors",
            [{"dimension": "population.measure", "values": ["count"]}],
            [{"dimension": "population.measure", "values": ["density"]}],
        ),
        ("travel_time_bands_min", [[0, 5], [5, 10]], [[0, 10]]),
        ("neighbor_steps", 1, 2),
        ("rank_order", "highest", "lowest"),
        ("top_k", 2, 5),
        ("record_refs", ["population/cell-1"], ["population/cell-2"]),
    ],
)
def test_plan_tool_call_validator_enforces_every_planned_parameter(field, planned, changed):
    subquestion = {
        "question": "核对计划参数",
        "analysis": "rank",
        "fact_domains": ["population"],
        "evidence_dimensions": ["population.scale"],
        field: planned,
    }
    plan = {"question": "核对计划参数", "subquestions": [subquestion]}
    arguments = {
        "history_id": "history-1",
        "analysis": "rank",
        "fact_domains": ["population"],
        "evidence_dimensions": ["population.scale"],
        field: planned,
    }
    call = {
        "name": "compute_spatial_evidence",
        "arguments": arguments,
        "status": "completed",
        "result": {"result_id": "spatial:parameter-test", "status": "available"},
    }
    validator = spatial_tool_agent._plan_tool_call_validator(plan, history_id="history-1")

    validator([call])
    call["arguments"][field] = changed
    with pytest.raises(
        spatial_tool_agent.SpatialToolAgentError,
        match=f"spatial_plan_parameter_mismatch:{field}",
    ):
        validator([call])


def test_plan_tool_call_validator_matches_same_semantics_independent_of_call_order():
    plan = {
        "question": "分别返回前三和前五个人口网格",
        "subquestions": [
            {**_planned_rank()["subquestions"][0], "top_k": 3},
            {**_planned_rank()["subquestions"][0], "top_k": 5},
        ],
    }
    validator = spatial_tool_agent._plan_tool_call_validator(plan, history_id="history-1")

    validator([_rank_call(top_k=5), _rank_call(top_k=3)])


def test_plan_tool_call_validator_accepts_one_batch_for_independent_subquestions():
    plan = {
        "question": "比较人口和设施",
        "subquestions": [
            {
                "question": "人口范围",
                "analysis": "scope",
                "fact_domains": ["population"],
                "evidence_dimensions": ["population.scale"],
                "selectors": [],
                "travel_time_bands_min": None,
                "neighbor_steps": 1,
                "rank_order": "highest",
                "top_k": 10,
                "record_refs": [],
            },
            {
                "question": "设施范围",
                "analysis": "scope",
                "fact_domains": ["poi"],
                "evidence_dimensions": ["poi.supply"],
                "selectors": [],
                "travel_time_bands_min": None,
                "neighbor_steps": 1,
                "rank_order": "highest",
                "top_k": 10,
                "record_refs": [],
            },
        ],
    }
    requests = [dict(item) for item in plan["subquestions"]]
    call = {
        "name": "compute_spatial_evidence_batch",
        "arguments": {"history_id": "history-1", "requests": requests},
        "status": "completed",
        "result": {
            "status": "available",
            "results": [
                {"result_id": "spatial:population", "status": "available"},
                {"result_id": "spatial:poi", "status": "available"},
            ],
        },
    }

    validator = spatial_tool_agent._plan_tool_call_validator(plan, history_id="history-1")
    validator([call])


def test_computation_refs_must_come_from_matching_tool_result():
    plan = _planned_rank()
    output = {
        "question": plan["question"],
        "subquestions": [{
            "question": plan["subquestions"][0]["question"],
            "analysis": "rank",
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.scale"],
            "finding": "两个网格的人口数已返回。",
            "computation_refs": ["spatial:rank-real"],
        }],
        "synthesis": "人口较多网格可供后续检查。",
        "spatial_implications": [],
        "unresolved": [],
    }

    spatial_tool_agent._validate_plan_execution(plan, output)
    spatial_tool_agent._validate_computation_refs(plan, output, [_rank_call()])

    output["subquestions"][0]["computation_refs"] = ["spatial:invented"]
    with pytest.raises(spatial_tool_agent.SpatialToolAgentError, match="spatial_computation_ref_mismatch:0"):
        spatial_tool_agent._validate_computation_refs(plan, output, [_rank_call()])
