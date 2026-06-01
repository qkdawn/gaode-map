from fastapi import FastAPI
from fastapi.testclient import TestClient

from router.domains.ppt_planning import router


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_ppt_spec_api_returns_structured_json():
    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/spec",
            json={
                "area_id": "area-1",
                "source_ids": ["summary", "scope"],
                "topic": "长沙县政府原址城市更新",
                "audience": "政府评审",
                "deck_type": "城市更新概念策划",
                "page_count": 15,
                "research_enabled": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page_count"] == 15
    assert payload["audience"] == "政府评审"
    assert payload["outline"]


def test_deck_brief_api_returns_slide_brief_json():
    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/deck-brief",
            json={
                "source_ids": ["summary"],
                "topic": "更新策划",
                "page_count": 15,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["slides"][0]["title"] == "封面"
    assert "PPTX" in payload["slides"][0]["speaker_notes"]
