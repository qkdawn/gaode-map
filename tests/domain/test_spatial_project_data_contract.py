from types import SimpleNamespace

import pytest

import modules.spatial_projects.data_contract as contract_module
from modules.spatial_projects.data_contract import ProjectDataContractService


class FakeRecord:
    def __init__(self, record_id, payload):
        self.record_id = record_id
        self.payload = payload

    def as_payload(self):
        return dict(self.payload)


class FakeDatasets:
    def __init__(self):
        self.records = [
            FakeRecord(
                f"poi-{index}",
                {
                    "record_id": f"poi-{index}",
                    "properties": {
                        "poi_id": f"poi-{index}",
                        "name": f"POI {index}",
                        "location": [112.0 + index / 1000, 28.0],
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [112.0 + index / 1000, 28.0],
                    },
                },
            )
            for index in range(5)
        ]

    def load_scope_records(self, *, history_id, source_id):
        assert history_id == "history-1"
        assert source_id == "current:dataset:poi"
        return list(self.records), [2024], 2024

    def query_scope_dataset(self, *, limit, offset, **kwargs):
        values = [record.as_payload() for record in self.records]
        return {
            "records": values[offset:offset + limit],
            "total_count": len(values),
            "warnings": [],
            "spatial_diagnostics": {},
        }

    def aggregate_scope_dataset(self, **kwargs):
        assert kwargs["top_k"] is None
        return {
            "rows": [{"group": {"category": "体育休闲"}, "count": 5}],
            "metric_methods": [{"op": "count", "field": "*"}],
            "spatial_summary": {},
            "warnings": [],
        }


class FakeProjects:
    def __init__(self):
        self.datasets = FakeDatasets()

    def read_history_project(self, history_id):
        assert history_id == "history-1"
        return {"project_name": "测试项目", "description": "完整数据", "created_at": "2026-07-30", "scope": {"type": "Polygon", "coordinates": []}}

    def list_history_project_datasets(self, history_id):
        return {
            "datasets": [{
                "source_id": "current:dataset:poi",
                "title": "POI",
                "record_count": 5,
                "selected_year": 2024,
                "status": "ready",
                "summary": {"category_counts": {"体育休闲": 5}},
            }],
            "warnings": [],
        }

    def list_history_project_documents(self, history_id):
        assert history_id == "history-1"
        return [{"document_id": "doc-1", "title": "项目文档", "file_name": "project.docx", "status": "parsed"}]


@pytest.fixture
def service(monkeypatch):
    blocks = SimpleNamespace(
        document=SimpleNamespace(file_name="project.docx"),
        blocks=[
            SimpleNamespace(id=11, pageIndex=0, blockIndex=0, blockType="title", text="现状建筑", sectionTitle=""),
            SimpleNamespace(id=12, pageIndex=0, blockIndex=1, blockType="paragraph", text="第一页原文", sectionTitle="现状建筑"),
            SimpleNamespace(id=13, pageIndex=3, blockIndex=2, blockType="paragraph", text="第四页原文", sectionTitle="运营要求"),
        ],
    )
    monkeypatch.setattr(contract_module, "list_document_blocks", lambda document_id: blocks)
    return ProjectDataContractService(
        projects=FakeProjects(),
        metric_results=lambda **kwargs: {"result": {"results": [{"result_id": "metric:direction", "data": {"directions": 8}}]}},
    )


def test_context_separates_raw_datasets_and_computed_results(service):
    result = service.project_context("history-1")

    assert result["schema_version"] == "spatial_records/v1"
    assert result["project"]["coord_type"] == "wgs84"
    datasets = {item["dataset_id"]: item for item in result["datasets"]}
    assert datasets["poi"]["total_count"] == 5
    assert datasets["poi"]["coord_type"] == "wgs84"
    assert "continuation" not in datasets["poi"]
    assert "pagination" not in datasets["poi"]
    assert datasets["poi"]["operations"] == ["records", "aggregate"]
    assert datasets["poi"]["query_capabilities"]["input_coord_types"] == ["wgs84"]
    assert result["documents"] == [{
        "document_id": "doc-1",
        "title": "项目文档",
        "file_name": "project.docx",
        "document_role": "",
        "status": "parsed",
        "original_resource_uri": "spatial-document://history-1/doc-1/original",
    }]
    assert {item["result_id"] for item in result["computed_results"]} == {"computed:poi:summary", "metric:direction"}


def test_records_can_be_exhausted_with_snapshot_bound_continuation(service, monkeypatch):
    monkeypatch.setattr(contract_module, "MAX_RESULT_SIZE", 2)
    first = service.query_data(history_id="history-1", dataset_id="poi")
    second = service.query_data(history_id="history-1", dataset_id="poi", continue_token=first["continue_token"])
    third = service.query_data(history_id="history-1", dataset_id="poi", continue_token=second["continue_token"])

    records = first["records"] + second["records"] + third["records"]
    assert [item["poi_id"] for item in records] == [f"poi-{index}" for index in range(5)]
    assert first["dataset_checksum"] == second["dataset_checksum"] == third["dataset_checksum"]
    assert first["total_count"] == 5
    assert first["complete"] is False
    assert second["complete"] is False
    assert third["complete"] is True
    assert third["continue_token"] is None
    assert all(
        "next_cursor" not in result
        and "page_checksum" not in result
        and "returned_count" not in result
        for result in (first, second, third)
    )

    with pytest.raises(ValueError, match="continue_token_query_mismatch"):
        service.query_data(history_id="history-1", dataset_id="poi", filters={"name": "other"}, continue_token=first["continue_token"])


def test_project_document_reader_keeps_docling_text_structure(service):
    page = service.read_project_document(history_id="history-1", document_id="doc-1")

    assert page["blocks"][1] == {
        "page": 1,
        "heading": "现状建筑",
        "text": "第一页原文",
        "block_type": "paragraph",
    }
    assert page["blocks"][2]["page"] == 4
    assert page["complete"] is True
    assert page["next_start_block"] is None
    assert page["text"] == "现状建筑\n\n第一页原文\n\n第四页原文"
    assert not {
        "history_id",
        "content_mode",
        "original_resource_uri",
        "document_checksum",
        "selection_checksum",
        "returned_characters",
        "total_characters",
        "continuation_reason",
        "continuation_hint",
        "warnings",
    }.intersection(page)


def test_project_document_reader_applies_internal_character_budget(service, monkeypatch):
    monkeypatch.setattr(contract_module, "MAX_DOCUMENT_CHARACTERS", 5)

    page = service.read_project_document(history_id="history-1", document_id="doc-1")

    assert page["text"] == "现状建筑"
    assert page["returned_blocks"] == 1
    assert page["complete"] is False
    assert page["next_start_block"] == 1


def test_project_document_reader_supports_explicit_continuation(service):
    first = service.read_project_document(history_id="history-1", document_id="doc-1", max_blocks=2)
    second = service.read_project_document(
        history_id="history-1",
        document_id="doc-1",
        start_block=first["next_start_block"],
        max_blocks=2,
    )

    assert first["total_blocks"] == 3
    assert first["complete"] is False
    assert first["next_start_block"] == 2
    assert second["complete"] is True
    assert second["blocks"][0]["text"] == "第四页原文"


def test_query_data_rejects_document_dataset_contract(service):
    with pytest.raises(ValueError, match="dataset_not_found"):
        service.query_data(history_id="history-1", dataset_id="document:doc-1")


def test_document_dataset_rejects_old_query_contract_even_with_continuation(service):
    with pytest.raises(ValueError, match="dataset_not_found"):
        service.query_data(
            history_id="history-1",
            dataset_id="document:doc-1",
            continue_token="unused-for-complete-documents",
        )


def test_aggregate_returns_computed_results_not_raw_records(service):
    result = service.query_data(
        history_id="history-1",
        dataset_id="poi",
        operation="aggregate",
        group_by=["category"],
        metrics=[{"op": "count", "field": "*", "as": "count"}],
    )

    assert result["records"] == []
    assert result["computed_results"] == [{"group": {"category": "体育休闲"}, "count": 5}]
    assert result["total_count"] == 1


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"filters": {"private_field": "value"}}, "unsupported_filter_field:private_field"),
        ({"sort": {"field": "private_field", "direction": "asc"}}, "unsupported_sort_field:private_field"),
        ({"operation": "aggregate", "group_by": ["private_field"]}, "unsupported_group_by_field:private_field"),
        (
            {"operation": "aggregate", "metrics": [{"op": "sum", "field": "private_field", "as": "total"}]},
            "unsupported_metric_field:private_field",
        ),
    ],
)
def test_query_contract_rejects_fields_outside_public_dataset_schema(service, kwargs, error):
    with pytest.raises(ValueError, match=error):
        service.query_data(history_id="history-1", dataset_id="poi", **kwargs)


def test_non_wgs84_spatial_query_is_rejected(service):
    with pytest.raises(ValueError, match="spatial_coord_type_must_be_wgs84"):
        service.query_data(
            history_id="history-1",
            dataset_id="poi",
            spatial={"relation": "nearest", "point": [112, 28], "coord_type": "gcj02"},
        )
