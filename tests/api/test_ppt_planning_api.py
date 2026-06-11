from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from sqlalchemy.exc import SQLAlchemyError

from modules.ppt_planning.schemas import (
    DeckBriefSlideRequest,
    DeckBriefResponse,
    DeckSlideBrief,
    PptDataPackageResponse,
    PptDataSourceSummary,
    PptOutlineItem,
    PptOutlineSectionRequest,
    PptPoiPoint,
    PptPoiQueryResponse,
    PptSource,
    PptSourceGroup,
    PptSourceGroupClassifyResponse,
    PptSpecResponse,
)
from router.domains import ppt_planning
from router.domains.ppt_planning import router


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_ppt_spec_api_returns_structured_json(monkeypatch):
    async def fake_generate(payload):
        return PptSpecResponse(
            title="长沙县政府原址城市更新目录",
            goal="形成政府评审汇报目录",
            audience=payload.audience,
            deck_type=payload.deck_type,
            page_count=payload.page_count,
            outline=[PptOutlineItem(id="page-1", page_no=1, theme="项目命题", purpose="建立汇报主线")],
            source_summary="已选择 2 个来源，包含联网研究",
            missing_inputs=[],
        )

    monkeypatch.setattr(ppt_planning, "generate_ppt_spec", fake_generate)

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
    assert payload["outline"][0]["theme"] == "项目命题"


def test_ppt_spec_section_api_returns_single_outline_item(monkeypatch):
    async def fake_generate(payload: PptOutlineSectionRequest):
        return PptOutlineItem(
            id=payload.target.id,
            page_no=payload.target.page_no,
            theme="空间问题诊断",
            purpose=payload.revision_note,
        )

    monkeypatch.setattr(ppt_planning, "regenerate_ppt_outline_section", fake_generate)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/spec/section",
            json={
                "area_id": "area-1",
                "outline": [{"id": "page-2", "page_no": 2, "theme": "空间证据", "purpose": "说明现状"}],
                "target": {"id": "page-2", "page_no": 2, "theme": "空间证据", "purpose": "说明现状"},
                "revision_note": "更像问题诊断",
                "source_ids": ["system:scope"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "page-2"
    assert payload["page_no"] == 2
    assert payload["theme"] == "空间问题诊断"
    assert payload["purpose"] == "更像问题诊断"


def test_deck_brief_api_returns_slide_brief_json(monkeypatch):
    async def fake_generate(payload):
        return DeckBriefResponse(
            status="draft",
            slides=[
                DeckSlideBrief(
                    index=1,
                    title="项目命题",
                    speaker_notes="第一阶段先生成逐页指令，不直接生成 PPTX。",
                )
            ],
            source_summary="已选择 1 个来源",
            missing_inputs=[],
        )

    monkeypatch.setattr(ppt_planning, "generate_deck_brief", fake_generate)

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
    assert payload["slides"][0]["title"] == "项目命题"
    assert "PPTX" in payload["slides"][0]["speaker_notes"]


def test_deck_brief_slide_api_returns_single_slide(monkeypatch):
    async def fake_generate(payload: DeckBriefSlideRequest):
        return DeckSlideBrief(
            index=payload.target.index,
            title="项目命题重写",
            purpose=payload.revision_note,
            key_message="说明为什么要更新",
            visual_plan="区域底图",
            required_sources=["system:scope"],
            speaker_notes="只生成单页指令。",
        )

    monkeypatch.setattr(ppt_planning, "regenerate_deck_brief_slide", fake_generate)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/deck-brief/slide",
            json={
                "area_id": "area-1",
                "outline": [{"id": "page-1", "page_no": 1, "theme": "项目命题", "purpose": "建立汇报主线"}],
                "slides": [{"index": 1, "title": "项目命题", "purpose": "建立汇报主线"}],
                "target": {"index": 1, "title": "项目命题", "purpose": "建立汇报主线"},
                "outline_item": {"id": "page-1", "page_no": 1, "theme": "项目命题", "purpose": "建立汇报主线"},
                "revision_note": "更强调更新必要性",
                "source_ids": ["system:scope"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["index"] == 1
    assert payload["title"] == "项目命题重写"
    assert payload["required_sources"] == ["system:scope"]


def test_ppt_data_sources_api_returns_source_statuses(monkeypatch):
    def fake_list(area_id):
        return [
            PptDataSourceSummary(
                id="system:poi",
                title="POI 基础数据",
                status="ready",
                summary="POI 2 条",
                count=2,
            )
        ]

    monkeypatch.setattr(ppt_planning, "list_ppt_sources", fake_list)

    with TestClient(_build_test_app()) as client:
        response = client.get("/api/v1/analysis/ppt/data/sources?area_id=area-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "system:poi"
    assert payload[0]["status"] == "ready"


def test_ppt_data_sources_api_maps_database_errors(monkeypatch):
    def fake_list(area_id):
        raise SQLAlchemyError("db down")

    monkeypatch.setattr(ppt_planning, "list_ppt_sources", fake_list)

    with TestClient(_build_test_app()) as client:
        response = client.get("/api/v1/analysis/ppt/data/sources?area_id=area-1")

    assert response.status_code == 503
    assert response.json()["detail"] == "ppt_database_unavailable"


def test_ppt_query_poi_points_api_returns_paginated_points(monkeypatch):
    def fake_query(payload):
        return PptPoiQueryResponse(
            area_id=payload.area_id,
            coordinate_system="WGS84",
            items=[PptPoiPoint(id="poi-1", name="长沙县政府原址", location=[112.9, 28.2])],
            total=1,
            limit=payload.limit,
            offset=payload.offset,
        )

    monkeypatch.setattr(ppt_planning, "query_poi_points", fake_query)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/data/query-poi-points",
            json={"area_id": "area-1", "limit": 10, "offset": 0},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coordinate_system"] == "WGS84"
    assert payload["items"][0]["name"] == "长沙县政府原址"
    assert payload["items"][0]["location"] == [112.9, 28.2]


def test_ppt_nearby_pois_api_returns_distance_sorted_points(monkeypatch):
    def fake_nearby(payload):
        return PptPoiQueryResponse(
            area_id=payload.area_id,
            coordinate_system="WGS84",
            items=[PptPoiPoint(id="poi-1", name="长沙县政府原址", location=[112.9, 28.2], distance_m=0)],
            total=1,
            limit=payload.limit,
            offset=0,
        )

    monkeypatch.setattr(ppt_planning, "query_nearby_poi_points", fake_nearby)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/data/nearby-pois",
            json={"area_id": "area-1", "center": [112.9, 28.2], "radius_m": 500, "limit": 10},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coordinate_system"] == "WGS84"
    assert payload["items"][0]["distance_m"] == 0


def test_ppt_data_package_api_returns_visible_source(monkeypatch):
    async def fake_package(payload):
        return PptDataPackageResponse(
            source=PptSource(
                id="package:poi:test",
                type="package",
                title="POI 资料包",
                status="ready",
                selected=True,
                meta={"label": "POI 1 条", "sourceKind": "package", "package": {"items": []}},
            ),
            summary="已整理 1 条 POI 样例。",
        )

    monkeypatch.setattr(ppt_planning, "create_ppt_data_package", fake_package)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/data/packages",
            json={"area_id": "area-1", "source_ids": ["system:poi"], "limit": 10},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["id"] == "package:poi:test"
    assert payload["source"]["selected"] is True


def test_ppt_data_package_api_returns_llm_unavailable_error(monkeypatch):
    async def fake_package(payload):
        raise ppt_planning.PptDataIntentLlmUnavailable("ppt_data_intent_llm_unavailable")

    monkeypatch.setattr(ppt_planning, "create_ppt_data_package", fake_package)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/data/packages",
            json={"area_id": "area-1", "source_ids": ["system:poi"], "package_mode": "evidence"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "ppt_data_intent_llm_unavailable"


def test_ppt_data_package_api_maps_provider_timeout(monkeypatch):
    async def fake_package(payload):
        raise httpx.ReadTimeout("provider timed out")

    monkeypatch.setattr(ppt_planning, "create_ppt_data_package", fake_package)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/data/packages",
            json={"area_id": "area-1", "source_ids": ["system:poi"], "package_mode": "evidence"},
        )

    assert response.status_code == 504
    assert response.json()["detail"] == "ppt_data_llm_timeout"


def test_ppt_source_group_classification_api_returns_groups(monkeypatch):
    async def fake_classify(payload):
        return PptSourceGroupClassifyResponse(
            groups=[
                PptSourceGroup(
                    id="group:vitality",
                    title="城市活力证据",
                    source_ids=["system:poi"],
                    meta={"reason": "POI 支撑活力判断。"},
                )
            ]
        )

    monkeypatch.setattr(ppt_planning, "classify_ppt_source_groups", fake_classify)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/source-groups/classify",
            json={
                "area_id": "area-1",
                "sources": [
                    {"id": "system:poi", "type": "data", "title": "POI 基础数据", "status": "ready"},
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["groups"][0]["id"] == "group:vitality"
    assert payload["groups"][0]["source_ids"] == ["system:poi"]


def test_ppt_source_group_classification_api_returns_llm_unavailable(monkeypatch):
    async def fake_classify(payload):
        raise ppt_planning.PptPlanningLlmUnavailable("llm_unavailable")

    monkeypatch.setattr(ppt_planning, "classify_ppt_source_groups", fake_classify)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/source-groups/classify",
            json={
                "sources": [
                    {"id": "system:poi", "type": "data", "title": "POI 基础数据", "status": "ready"},
                ],
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "ppt_planning_llm_unavailable"


def test_ppt_spec_api_maps_invalid_llm_response(monkeypatch):
    async def fake_generate(payload):
        raise ValueError("invalid_llm_json_output")

    monkeypatch.setattr(ppt_planning, "generate_ppt_spec", fake_generate)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/spec",
            json={
                "area_id": "area-1",
                "source_ids": ["summary", "scope"],
                "topic": "长沙县政府原址城市更新",
            },
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "ppt_planning_llm_invalid_response"
