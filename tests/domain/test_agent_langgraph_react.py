import json

from modules.agent.context_builder import build_context_bundle
from modules.agent.providers.langgraph_react import _initial_payload, _react_tool_result_payload
from modules.agent.providers.prompts import loop_system_prompt
from modules.agent.schemas import AnalysisSnapshot, ToolResult
from modules.agent.tools import get_tool_registry


def _snapshot_with_scope() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        scope={
            "polygon": [
                [116.38, 39.90],
                [116.39, 39.90],
                [116.39, 39.91],
                [116.38, 39.91],
                [116.38, 39.90],
            ]
        },
        poi_summary={"total": 2},
        pois=[{"name": "A"}, {"name": "B"}],
        road={"summary": {"node_count": 3, "edge_count": 2}},
    )


def test_loop_prompt_changes_with_thinking_mode():
    quick_prompt = loop_system_prompt(thinking_mode="quick")
    deep_prompt = loop_system_prompt(thinking_mode="deep")

    assert "quick 模式" in quick_prompt
    assert "deep 模式" in deep_prompt
    assert "固定栏目" in deep_prompt
    assert "城市空间与文旅商业策划分析顾问" in quick_prompt
    assert "空间现象、人的体验、策划影响、下一步动作" in quick_prompt


def test_langgraph_initial_payload_uses_digest_instead_of_full_snapshot():
    snapshot = AnalysisSnapshot(
        scope={"polygon": [[116.38, 39.90], [116.39, 39.90], [116.39, 39.91], [116.38, 39.90]]},
        poi_summary={"total": 1200},
        h3={
            "summary": {"grid_count": 3},
            "charts": {"huge_series": list(range(500))},
            "poi_h3_evidence": {"cells": [{"cell_id": f"cell-{index}", "poi_count": index} for index in range(120)]},
        },
        population={"summary": {"total_population": 10000}, "grid_evidence": {"cells": list(range(300))}},
        frontend_analysis={"poi": {"large": list(range(300))}, "h3": {"large": list(range(300))}},
        shared_grid={"cells": [{"cell_id": f"shared-{index}"} for index in range(200)]},
    )
    registry = get_tool_registry()
    payload = _initial_payload(
        question="这个区域怎么样",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        registry={"read_current_results": registry["read_current_results"]},
    )
    encoded = json.dumps(payload, ensure_ascii=False)

    assert "analysis_snapshot" not in payload
    assert "analysis_snapshot_digest" in payload
    assert "huge_series" not in encoded
    assert "shared-199" not in encoded
    assert "cell-119" not in encoded
    assert "frontend_analysis" in encoded


def test_langgraph_tool_result_payload_compacts_large_results_and_artifacts():
    result = ToolResult(
        tool_name="read_current_results",
        status="success",
        result={"rows": [{"id": index, "value": index} for index in range(80)], "total": 80},
        evidence=[{"field": f"metric.{index}", "value": index} for index in range(40)],
        artifacts={
            "current_poi_h3": {"grid": [{"cell_id": f"cell-{index}"} for index in range(200)]},
            "current_frontend_analysis": {"poi": {"large": list(range(200))}},
        },
    )
    payload = json.loads(_react_tool_result_payload(result))
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["result_summary"]
    assert payload["artifact_keys"] == ["current_poi_h3", "current_frontend_analysis"]
    assert "current_frontend_analysis" in encoded
    assert "cell-199" not in encoded
    assert "metric.39" not in encoded
    assert payload["result"]["rows"]["type"] == "array"
    assert payload["evidence"]["type"] == "array"
