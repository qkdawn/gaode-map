import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

import router.domains.history as history_module
from modules.history.artifact_service import AnalysisArtifactUpsertRequest
from modules.poi.schemas import HistoryPoiYearResult, HistorySaveRequest


def test_save_history_ignores_h3_and_road_snapshots(monkeypatch):
    captured = {}

    def fake_create_record(params, polygon, pois, desc, *, preferred_history_id="", poi_results_by_year=None):
        captured["params"] = params
        captured["polygon"] = polygon
        captured["pois"] = pois
        captured["desc"] = desc
        captured["preferred_history_id"] = preferred_history_id
        captured["poi_results_by_year"] = poi_results_by_year
        return 42

    monkeypatch.setattr(history_module.history_repo, "create_record", fake_create_record)

    payload = HistorySaveRequest(
        center=[112.0, 28.0],
        polygon=[[112.0, 28.0], [112.1, 28.1], [112.0, 28.0]],
        drawn_polygon=[[112.0, 28.0], [112.1, 28.1], [112.0, 28.0]],
        pois=[],
        keywords="餐饮",
        mode="walking",
        time_min=15,
        location_name="test",
        source="local",
        h3_result={"grid": {"features": [{"id": "h3-1"}]}},
        road_result={"roads": {"features": [{"id": "road-1"}]}},
    )

    response = asyncio.run(history_module.save_history_manually(payload))

    assert response["status"] == "ok"
    assert response["history_id"] == 42
    assert "h3_result" not in captured["params"]
    assert "road_result" not in captured["params"]
    assert captured["preferred_history_id"] == ""
    assert captured["poi_results_by_year"] == [{"source": "local", "year": None, "pois": []}]


def test_save_history_prefers_original_wgs84_polygon_when_reusing_history(monkeypatch):
    captured = {}

    def fake_create_record(params, polygon, pois, desc, *, preferred_history_id="", poi_results_by_year=None):
        captured["polygon"] = polygon
        captured["preferred_history_id"] = preferred_history_id
        captured["poi_results_by_year"] = poi_results_by_year
        return preferred_history_id or "unexpected"

    monkeypatch.setattr(history_module.history_repo, "create_record", fake_create_record)

    payload = HistorySaveRequest(
        history_id="history-fixed",
        center=[112.0, 28.0],
        polygon=[[112.1, 28.1], [112.2, 28.2], [112.1, 28.1]],
        polygon_wgs84=[[120.1, 30.1], [120.2, 30.2], [120.1, 30.1]],
        pois=[],
        keywords="餐饮",
        mode="walking",
        time_min=15,
        location_name="test",
        source="local",
    )

    response = asyncio.run(history_module.save_history_manually(payload))

    assert response["history_id"] == "history-fixed"
    assert captured["preferred_history_id"] == "history-fixed"
    assert captured["polygon"] == [[120.1, 30.1], [120.2, 30.2], [120.1, 30.1]]


def test_save_history_passes_multi_year_snapshots(monkeypatch):
    captured = {}

    def fake_create_record(params, polygon, pois, desc, *, preferred_history_id="", poi_results_by_year=None):
        captured["params"] = params
        captured["poi_results_by_year"] = poi_results_by_year
        return "history-multi"

    monkeypatch.setattr(history_module.history_repo, "create_record", fake_create_record)

    payload = HistorySaveRequest(
        history_id="history-multi",
        center=[112.0, 28.0],
        polygon=[[112.1, 28.1], [112.2, 28.2], [112.1, 28.1]],
        pois=[],
        keywords="餐饮",
        mode="walking",
        time_min=15,
        location_name="test",
        source="local",
        year=2024,
        years=[2022, 2024],
        poi_results_by_year=[
            HistoryPoiYearResult(year=2022, source="local", pois=[]),
            HistoryPoiYearResult(year=2024, source="local", pois=[]),
        ],
    )

    response = asyncio.run(history_module.save_history_manually(payload))

    assert response["history_id"] == "history-multi"
    assert captured["params"]["years"] == [2022, 2024]
    assert [item["year"] for item in captured["poi_results_by_year"]] == [2022, 2024]


def test_history_artifact_api_upserts_and_lists(monkeypatch):
    calls = {}

    class FakeRepo:
        def upsert(self, **kwargs):
            calls["upsert"] = kwargs
            return {"history_id": kwargs["history_id"], "artifact_type": kwargs["artifact_type"], "params_hash": "hash"}

        def list(self, history_id, *, artifact_type="", params_hash=""):
            calls["list"] = {"history_id": history_id, "artifact_type": artifact_type, "params_hash": params_hash}
            return [{"history_id": history_id, "artifact_type": artifact_type or "scope"}]

    payload = AnalysisArtifactUpsertRequest(
        artifact_type="scope",
        params={"mode": "walking"},
        payload={"polygon": []},
        summary={"has_polygon": False},
        scope_fingerprint="scope-a",
    )

    response = history_module.upsert_history_artifact("history-1", payload, repo=FakeRepo())
    listed = history_module.list_history_artifacts("history-1", artifact_type="scope", repo=FakeRepo())

    assert response["artifact_type"] == "scope"
    assert calls["upsert"]["params"] == {"mode": "walking"}
    assert listed[0]["artifact_type"] == "scope"
    assert calls["list"]["history_id"] == "history-1"
