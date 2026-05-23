import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

sys.path.append(str(Path(__file__).resolve().parents[2]))

import modules.history.service as history_service


def test_history_keys_are_stable_for_equivalent_params():
    params = {
        "center": [112.0, 28.0],
        "time_min": 15,
        "keywords": "餐饮",
        "mode": "walking",
        "source": "local",
    }
    assert history_service.build_history_overwrite_key(params) == history_service.build_history_overwrite_key(dict(params))
    assert history_service.build_history_list_dedupe_key("demo", params) == history_service.build_history_list_dedupe_key("demo", dict(params))


def test_convert_history_detail_to_gcj02_restores_center_polygon_and_pois(monkeypatch):
    monkeypatch.setattr(history_service, "wgs84_to_gcj02", lambda x, y: (x + 0.1, y + 0.2))
    payload = {
        "params": {
            "center": [100.0, 20.0],
            "drawn_polygon": [[100.0, 20.0], [100.1, 20.1]],
        },
        "polygon": [[100.0, 20.0], [100.1, 20.1], [100.0, 20.0]],
        "pois": [{"id": "p1", "location": [100.2, 20.2]}],
    }
    result = history_service.convert_history_detail_to_gcj02(payload, include_pois=True)
    assert result["params"]["center"] == [100.1, 20.2]
    assert result["params"]["drawn_polygon"][0] == [100.1, 20.2]
    assert result["polygon"][0] == [100.1, 20.2]
    assert result["pois"][0]["location"] == [100.3, 20.4]


def test_get_history_list_payload_surfaces_database_errors():
    class _Repo:
        def get_list(self, limit):
            raise SQLAlchemyError("db down")

    with pytest.raises(HTTPException) as exc:
        history_service.get_history_list_payload(100, _Repo())

    assert exc.value.status_code == 503
    assert "MySQL" in exc.value.detail
