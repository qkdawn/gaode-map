from __future__ import annotations

import modules.spatial_strategy.project_data as project_data


def test_step_project_data_uses_existing_project_datasets_and_stable_citations(monkeypatch):
    project_data._QUERY_CACHE.clear()
    context = {
        "project": {"history_id": "history-1", "name": "测试项目"},
        "documents": [{"document_id": "doc-1", "title": "项目材料"}],
        "datasets": [{"dataset_id": "poi", "title": "项目 POI", "total_count": 2}],
        "computed_results": [{"result_id": "computed:poi:summary", "data": {"count": 2}}],
        "warnings": [],
    }
    calls = []

    class FakeData:
        def project_context(self, history_id):
            assert history_id == "history-1"
            return context

        def query_data(self, **kwargs):
            calls.append(kwargs)
            if kwargs["dataset_id"].startswith("document:"):
                return {
                    "complete": True,
                    "total_count": 1,
                    "snapshot_id": "snapshot:doc",
                    "dataset_checksum": "sha256:doc",
                    "records": [{"document_id": "doc-1", "filename": "项目材料.docx", "page": 2, "heading": "定位", "text": "项目原文"}],
                }
            if kwargs["operation"] == "aggregate":
                return {
                    "complete": True,
                    "total_count": 1,
                    "snapshot_id": "snapshot:poi",
                    "dataset_checksum": "sha256:poi",
                    "computed_results": [{"group": {"category": "文化"}, "poi_count": 2}],
                    "method": ["database"],
                }
            return {
                "complete": True,
                "total_count": 2,
                "snapshot_id": "snapshot:poi",
                "dataset_checksum": "sha256:poi",
                "records": [{"poi_id": "p-1", "name": "甲"}, {"poi_id": "p-2", "name": "乙"}],
            }

    monkeypatch.setattr(project_data, "_DATA", FakeData())
    result = project_data.read_step_project_data(history_id="history-1", step_key="project_basis", project_context=context)

    assert result["status"] == "success"
    assert {item["dataset_id"] for item in result["citations"]} == {"computed", "poi"}
    assert not any(item["source_type"] == "project_document" for item in result["citations"])
    assert any(item["source_type"] == "project_computed_result" for item in result["citations"])
    assert len([item for item in result["citations"] if item["source_type"] == "project_data_record"]) == 2
    assert any(item.get("operation") == "aggregate" for item in result["citations"])
    assert all(item["citation_id"].startswith("project:") for item in result["citations"])
    assert any(call["operation"] == "aggregate" and call["dataset_id"] == "poi" for call in calls)

    initial_call_count = len(calls)
    project_data.read_step_project_data(history_id="history-1", step_key="supply_gap", project_context=context)
    assert len(calls) == initial_call_count


def test_large_dataset_keeps_aggregate_and_does_not_emit_partial_records(monkeypatch):
    project_data._QUERY_CACHE.clear()
    context = {
        "project": {"history_id": "history-1"},
        "datasets": [{"dataset_id": "poi", "title": "POI", "total_count": 201}],
        "computed_results": [],
        "warnings": [],
    }

    class FakeData:
        def query_data(self, **kwargs):
            assert kwargs["operation"] == "aggregate"
            return {"complete": True, "total_count": 3, "computed_results": [{"poi_count": 201}]}

    monkeypatch.setattr(project_data, "_DATA", FakeData())
    result = project_data.read_step_project_data(history_id="history-1", step_key="supply_gap", project_context=context)

    assert len(result["citations"]) == 1
    assert result["citations"][0]["operation"] == "aggregate"
    assert any("超过200条" in warning for warning in result["warnings"])
