import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

sys.path.append(str(Path(__file__).resolve().parents[2]))

import router.domains.history as history_module


def test_history_pois_route_runs_in_threadpool(monkeypatch):
    captured = {}

    async def fake_run_in_threadpool(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"status": "threaded"}

    monkeypatch.setattr(history_module, "run_in_threadpool", fake_run_in_threadpool)

    response = asyncio.run(history_module.get_history_pois("history-1", year=2024))

    assert response == {"status": "threaded"}
    assert captured["func"] is history_module.history_service.get_history_pois_payload
    assert captured["args"] == ("history-1", history_module.history_repo)
    assert captured["kwargs"] == {"year": 2024}


def test_history_detail_route_runs_in_threadpool(monkeypatch):
    captured = {}

    async def fake_run_in_threadpool(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"status": "threaded"}

    monkeypatch.setattr(history_module, "run_in_threadpool", fake_run_in_threadpool)

    response = asyncio.run(history_module.get_history_detail("history-1", include_pois=False, year=2024))

    assert response == {"status": "threaded"}
    assert captured["func"] is history_module.history_service.get_history_detail_payload_for_year
    assert captured["args"] == ("history-1", False, 2024, history_module.history_repo)
    assert captured["kwargs"] == {}


def test_get_history_detail_without_pois_returns_lightweight_payload(monkeypatch):
    monkeypatch.setattr(
        history_module.history_repo,
        "get_detail",
        lambda history_id, include_pois=True: {
            "id": history_id,
            "description": "demo",
            "created_at": "2026-03-07T00:00:00",
            "params": {
                "center": [10.0, 20.0],
                "drawn_polygon": [[1.0, 2.0], [3.0, 4.0]],
            },
            "polygon": [[10.0, 20.0], [11.0, 21.0], [10.0, 20.0]],
            "polygon_wgs84": [[10.0, 20.0], [11.0, 21.0], [10.0, 20.0]],
            "poi_summary": {"total": 2},
            "poi_count": 2,
        } if include_pois is False else None,
    )
    monkeypatch.setattr(history_module.history_service, "wgs84_to_gcj02", lambda x, y: (x + 0.5, y + 0.25))

    response = asyncio.run(history_module.get_history_detail(7, include_pois=False))

    assert response["id"] == 7
    assert "pois" not in response
    assert response["poi_count"] == 2
    assert response["params"]["center"] == [10.5, 20.25]
    assert response["params"]["drawn_polygon"][0] == [1.5, 2.25]
    assert response["polygon"][0] == [10.5, 20.25]
    assert response["polygon_wgs84"][0] == [10.0, 20.0]


def test_get_history_detail_with_pois_keeps_existing_contract(monkeypatch):
    monkeypatch.setattr(
        history_module.history_repo,
        "get_detail",
        lambda history_id, include_pois=True: {
            "id": history_id,
            "description": "demo",
            "created_at": "2026-03-07T00:00:00",
            "params": {"center": [10.0, 20.0]},
            "polygon": [[10.0, 20.0], [11.0, 21.0], [10.0, 20.0]],
            "polygon_wgs84": [[10.0, 20.0], [11.0, 21.0], [10.0, 20.0]],
            "pois": [{"id": "p1", "location": [30.0, 40.0]}],
            "poi_summary": {"total": 1},
            "poi_count": 1,
        } if include_pois is True else None,
    )
    monkeypatch.setattr(history_module.history_service, "wgs84_to_gcj02", lambda x, y: (x + 1.0, y + 2.0))

    response = asyncio.run(history_module.get_history_detail(8, include_pois=True))

    assert response["pois"][0]["location"] == [31.0, 42.0]
    assert response["poi_count"] == 1
    assert response["polygon_wgs84"][0] == [10.0, 20.0]


def test_get_history_pois_returns_poi_only_payload(monkeypatch):
    monkeypatch.setattr(
        history_module.history_repo,
        "get_pois",
        lambda history_id: {
            "history_id": history_id,
            "pois": [{"id": "p1", "location": [100.0, 20.0]}],
            "poi_summary": {"total": 1},
            "count": 1,
        },
    )
    monkeypatch.setattr(history_module.history_service, "wgs84_to_gcj02", lambda x, y: (x + 0.1, y + 0.2))

    response = asyncio.run(history_module.get_history_pois(11))

    assert response["history_id"] == 11
    assert response["count"] == 1
    assert response["pois"][0]["location"] == [100.1, 20.2]


def test_get_history_detail_and_pois_raise_404_when_record_missing(monkeypatch):
    monkeypatch.setattr(history_module.history_repo, "get_detail", lambda history_id, include_pois=True: None)
    monkeypatch.setattr(history_module.history_repo, "get_pois", lambda history_id: None)

    with pytest.raises(HTTPException) as detail_exc:
        asyncio.run(history_module.get_history_detail(999, include_pois=False))
    with pytest.raises(HTTPException) as pois_exc:
        asyncio.run(history_module.get_history_pois(999))

    assert detail_exc.value.status_code == 404
    assert pois_exc.value.status_code == 404


def test_get_history_pois_reports_database_sort_memory_error(monkeypatch):
    def _raise_sort_memory(history_id, year=None):
        raise OperationalError(
            "select poi_results",
            {"history_id": history_id},
            Exception("1038 Out of sort memory, consider increasing server sort buffer size"),
        )

    monkeypatch.setattr(history_module.history_repo, "get_pois", _raise_sort_memory)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(history_module.get_history_pois("history-oos"))

    assert exc.value.status_code == 500
    assert "数据库排序内存不足" in exc.value.detail
