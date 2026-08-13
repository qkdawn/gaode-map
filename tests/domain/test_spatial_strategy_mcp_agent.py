import json

from modules.spatial_strategy.mcp_agent import _compact_project_context_for_agent, read_previous_chapter


def test_compact_project_context_preserves_decision_evidence_without_grid_payloads():
    dense_cells = [{"lng": 112.9 + index / 10000, "lat": 28.2, "score": index} for index in range(100)]
    context = {
        "schema_version": "spatial_records/v1",
        "project": {
            "history_id": "history-1",
            "name": "测试项目",
            "scope": [[112.9, 28.2], [113.0, 28.3], [113.1, 28.25]],
        },
        "documents": [
            {"document_id": f"doc-{index}", "title": f"项目文档 {index}", "status": "parsed"}
            for index in range(10)
        ],
        "datasets": [{"dataset_id": "poi", "total_count": 2_635, "operations": ["records", "aggregate"]}],
        "computed_results": [{
            "result_id": "result:poi.accessibility",
            "method": "network_analysis",
            "data": {
                "summary": "项目范围内可达性较强，但应核验入口与步行连续性。",
                "limitations": ["未包含现场步行障碍核验"],
                "structured_result": {"grid_cells": dense_cells},
            },
        }],
        "warnings": [],
    }

    compacted = _compact_project_context_for_agent(context)

    assert compacted["agent_context_mode"] == "decision_summary"
    assert compacted["project"]["scope"] == {
        "defined": True,
        "coordinate_pair_count": 3,
        "bounds": {"min_lng": 112.9, "min_lat": 28.2, "max_lng": 113.1, "max_lat": 28.3},
    }
    metric = compacted["computed_results"][0]
    assert len(compacted["documents"]) == 10
    assert compacted["documents"][-1]["document_id"] == "doc-9"
    assert metric["data"]["summary"] == context["computed_results"][0]["data"]["summary"]
    assert metric["data"]["limitations"] == ["未包含现场步行障碍核验"]
    grid_cells = metric["data"]["structured_result"]["grid_cells"]
    assert grid_cells["item_count"] == 100
    assert grid_cells["detail_omitted"] is True
    assert len(grid_cells["sample"]) == 8
    assert grid_cells["sample"][0] == {"lng": 112.9, "lat": 28.2, "score": 0}
    compacted_without_documents = {**compacted, "documents": []}
    context_without_documents = {**context, "documents": []}
    assert len(json.dumps(compacted_without_documents, ensure_ascii=False)) < len(json.dumps(context_without_documents, ensure_ascii=False)) / 4


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
