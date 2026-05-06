import asyncio
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

import httpx

from main import app
from modules.poi import service as poi_service


async def _request(method: str, url: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


def test_poi_multi_year_api_returns_stable_payload(monkeypatch):
    async def fake_fetch(payload):
        return {
            "years": [2020, 2024],
            "selected_year": 2024,
            "display_pois": [{"id": "poi-2024", "location": [112.9, 28.2], "type": "050000"}],
            "results_by_year": [
                {"year": 2020, "source": "local", "pois": [], "count": 0},
                {"year": 2024, "source": "local", "pois": [{"id": "poi-2024", "location": [112.9, 28.2], "type": "050000"}], "count": 1},
            ],
            "summary_by_year": [
                {"year": 2020, "source": "local", "count": 0, "category_counts": {"food": 0}},
                {"year": 2024, "source": "local", "count": 1, "category_counts": {"food": 1}},
            ],
            "category_summary": [{"id": "food", "name": "Food", "count": 1}],
            "errors": [],
            "history_id": "history-1",
        }

    monkeypatch.setattr(poi_service, "fetch_multi_year_pois", fake_fetch)

    resp = asyncio.run(
        _request(
            "POST",
            "/api/v1/analysis/pois/multi-year",
            json={
                "polygon": [[112.0, 28.0], [112.1, 28.0], [112.0, 28.1], [112.0, 28.0]],
                "years": [2020, 2024],
                "categories": [{"id": "food", "name": "Food", "types": "050000"}],
                "save_history": True,
            },
        )
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_year"] == 2024
    assert data["history_id"] == "history-1"
    assert data["category_summary"] == [{"id": "food", "name": "Food", "count": 1}]
