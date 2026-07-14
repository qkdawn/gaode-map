import asyncio

import modules.agent.tool_adapters.current_poi_tools as current_poi_tools
from modules.agent.schemas import AnalysisSnapshot
from modules.agent.tools import get_tool_registry


def _poi_snapshot() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        pois=[
            {
                "name": "长沙市实验小学",
                "type": "科教文化服务;学校;小学",
                "category": "科教文化",
                "address": "人民路 1 号",
                "lng": 112.981,
                "lat": 28.191,
            },
            {
                "name": "湖南大学",
                "type": "科教文化服务;学校;高等院校",
                "category": "科教文化",
                "address": "麓山路",
                "lng": 112.944,
                "lat": 28.179,
            },
            {
                "name": "五一路咖啡",
                "type": "餐饮服务;咖啡厅",
                "category": "餐饮",
                "address": "五一路",
                "lng": 112.976,
                "lat": 28.194,
            },
        ]
    )


def _dataset_record(name, poi_type, category="", address="", lng=None, lat=None):
    props = {"name": name, "type": poi_type, "category": category, "address": address, "lng": lng, "lat": lat}
    return {"record_id": name, "title": name, "properties": props}


def _patch_scope_dataset_service(monkeypatch, rows):
    seen = []

    class FakeScopeDatasetService:
        def query_scope_dataset(self, **kwargs):
            seen.append(kwargs)
            offset = int(kwargs.get("offset") or 0)
            limit = int(kwargs.get("limit") or 100)
            page = rows[offset : offset + limit]
            return {
                "source_id": "current:dataset:poi",
                "total_count": len(rows),
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < len(rows),
                "records": page,
                "warnings": [],
            }

    monkeypatch.setattr(current_poi_tools, "ScopeDatasetService", FakeScopeDatasetService)
    return seen


def test_query_current_pois_requires_saved_scope_dataset_instead_of_snapshot_pois():
    registry = get_tool_registry()

    result = asyncio.run(
        registry["query_current_pois"].runner(
            arguments={"keyword": "学校", "limit": 10},
            snapshot=_poi_snapshot(),
            artifacts={},
            question="范围内所有学校有哪些",
        )
    )

    assert result.status == "success"
    assert result.result["total"] == 0
    assert result.result["has_more"] is False
    assert result.result["rows"] == []
    assert result.result["data_source"] == "scope_dataset"
    assert "history_id" in result.warnings[0]


def test_query_current_pois_queries_saved_scope_dataset_by_history_id(monkeypatch):
    seen = _patch_scope_dataset_service(monkeypatch, [
        _dataset_record("长沙市实验小学", "科教文化服务;学校;小学", "科教文化", "人民路 1 号", 112.981, 28.191),
        _dataset_record("五一路咖啡", "餐饮服务;咖啡厅", "餐饮"),
        _dataset_record("湖南大学", "科教文化服务;学校;高等院校", "科教文化", "麓山路", 112.944, 28.179),
    ])
    registry = get_tool_registry()

    result = asyncio.run(
        registry["query_current_pois"].runner(
            arguments={"keyword": "学校", "limit": 10},
            snapshot=AnalysisSnapshot(context={"history_id": "history-1"}, pois=[]),
            artifacts={},
            question="范围内所有学校有哪些",
        )
    )

    assert seen[0]["history_id"] == "history-1"
    assert seen[0]["source_id"] == "current:dataset:poi"
    assert result.result["data_source"] == "scope_dataset"
    assert result.result["total"] == 2
    assert [row["name"] for row in result.result["rows"]] == ["长沙市实验小学", "湖南大学"]
    assert "保存的当前范围 POI 数据集" in result.warnings[0]


def test_query_current_pois_paginates_current_poi_matches(monkeypatch):
    _patch_scope_dataset_service(monkeypatch, [
        _dataset_record("长沙市实验小学", "科教文化服务;学校;小学", "科教文化"),
        _dataset_record("五一路咖啡", "餐饮服务;咖啡厅", "餐饮"),
        _dataset_record("湖南大学", "科教文化服务;学校;高等院校", "科教文化"),
    ])
    registry = get_tool_registry()

    first_page = asyncio.run(
        registry["query_current_pois"].runner(
            arguments={"keyword": "学校", "limit": 1, "offset": 0},
            snapshot=AnalysisSnapshot(context={"history_id": "history-1"}),
            artifacts={},
            question="列出学校",
        )
    )
    second_page = asyncio.run(
        registry["query_current_pois"].runner(
            arguments={"keyword": "学校", "limit": 1, "offset": 1},
            snapshot=AnalysisSnapshot(context={"history_id": "history-1"}),
            artifacts={},
            question="列出学校",
        )
    )

    assert first_page.result["total"] == 2
    assert first_page.result["has_more"] is True
    assert [row["name"] for row in first_page.result["rows"]] == ["长沙市实验小学"]
    assert second_page.result["total"] == 2
    assert second_page.result["has_more"] is False
    assert [row["name"] for row in second_page.result["rows"]] == ["湖南大学"]


def test_query_current_pois_reports_missing_current_pois():
    registry = get_tool_registry()

    result = asyncio.run(
        registry["query_current_pois"].runner(
            arguments={"keyword": "学校"},
            snapshot=AnalysisSnapshot(),
            artifacts={},
            question="范围内有哪些学校",
        )
    )

    assert result.status == "success"
    assert result.result["total"] == 0
    assert result.result["rows"] == []
    assert "history_id" in result.warnings[0]


def test_query_current_pois_reports_missing_saved_dataset(monkeypatch):
    _patch_scope_dataset_service(monkeypatch, [])
    registry = get_tool_registry()

    result = asyncio.run(
        registry["query_current_pois"].runner(
            arguments={"keyword": "学校"},
            snapshot=AnalysisSnapshot(context={"history_id": "history-1"}),
            artifacts={},
            question="范围内有哪些学校",
        )
    )

    assert result.status == "success"
    assert result.result["total"] == 0
    assert result.result["rows"] == []
    assert "保存的 POI 数据集" in result.warnings[0]
