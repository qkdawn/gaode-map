from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from sqlalchemy.exc import SQLAlchemyError

from modules.ppt_planning.schemas import (
    DeckBriefSlideRequest,
    DeckBriefResponse,
    DeckNarrativeChapter,
    DeckNarrativeEvidenceBucket,
    DeckNarrativePlanResponse,
    DeckNarrativeSlideRole,
    DeckNarrativeVisualStrategy,
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
    PptVisualArtifactResponse,
)
from router.domains import ppt_planning, ppt_web_source
from router.domains.ppt_planning import router


def _build_test_app():
    app = FastAPI()
    app.include_router(router)
    app.include_router(ppt_web_source.router)
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
            source_summary="已选择 2 个来源，包含联网来源",
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
                "web_sources_enabled": True,
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
                "source_ids": ["current:scope"],
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
    assert "speaker_notes" not in payload["slides"][0]


def test_narrative_plan_api_returns_slide_roles(monkeypatch):
    async def fake_generate(payload):
        return DeckNarrativePlanResponse(
            storyline="问题到证据",
            chapters=[DeckNarrativeChapter(name="开篇定调", page_range="01", job="建立问题", output="明确主线")],
            evidence_buckets=[
                DeckNarrativeEvidenceBucket(id="scope", label="范围", allowed_sources=["current:scope"]),
                DeckNarrativeEvidenceBucket(id="metrics", label="指标", allowed_sources=["current:scope"]),
            ],
            slide_roles=[
                DeckNarrativeSlideRole(page_no=1, role="开题", job="建立问题", evidence_bucket="scope", visual_family="existing_map_layer"),
                DeckNarrativeSlideRole(page_no=2, role="证据", job="说明判断", evidence_bucket="metrics", visual_family="map_metric_card"),
            ],
            visual_rules=DeckNarrativeVisualStrategy(spatial_first=True, numeric_charts_require_data=True, diagram_for_strategy_pages=True, no_fallback_bar=True),
            missing_inputs=[],
        )

    monkeypatch.setattr(ppt_planning, "generate_narrative_plan", fake_generate)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/narrative-plan",
            json={
                "area_id": "area-1",
                "outline": [
                    {"id": "page-1", "page_no": 1, "theme": "开题", "purpose": "建立问题"},
                    {"id": "page-2", "page_no": 2, "theme": "证据", "purpose": "说明判断"},
                ],
                "source_ids": ["current:scope"],
                "topic": "更新策划",
                "page_count": 2,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["storyline"] == "问题到证据"
    assert [item["page_no"] for item in payload["slide_roles"]] == [1, 2]
    assert payload["slide_roles"][1]["visual_family"] == "map_metric_card"
    assert payload["slide_roles"][1]["evidence_bucket"] == "metrics"
    assert "style_guide" not in payload


def test_deck_brief_slide_api_returns_single_slide(monkeypatch):
    async def fake_generate(payload: DeckBriefSlideRequest):
        return DeckSlideBrief(
            index=payload.target.index,
            title="项目命题重写",
            purpose=payload.revision_note,
            key_message="说明为什么要更新",
            insight="这说明更新必要性已经具备可解释依据。",
            evidence_explanation=["范围口径来自当前等时圈", "可信度取决于已选择来源"],
            visual_plan="区域底图",
            required_sources=["current:scope"],
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
                "source_ids": ["current:scope"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["index"] == 1
    assert payload["title"] == "项目命题重写"
    assert payload["insight"] == "这说明更新必要性已经具备可解释依据。"
    assert payload["evidence_explanation"] == ["范围口径来自当前等时圈", "可信度取决于已选择来源"]
    assert payload["required_sources"] == ["current:scope"]


def test_deck_brief_slide_api_returns_structured_invalid_detail(monkeypatch):
    async def fake_generate(_payload: DeckBriefSlideRequest):
        raise ppt_planning.PptPlanningInvalidResponse(
            "invalid_deck_brief_slide",
            detail={
                "code": "invalid_deck_brief_slide",
                "page_no": 2,
                "reason": "missing_required_brief_content",
                "missing_fields": ["key_message"],
                "payload_bytes": 1024,
                "repaired": False,
                "retried": False,
                "content_retried": True,
            },
        )

    monkeypatch.setattr(ppt_planning, "regenerate_deck_brief_slide", fake_generate)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/deck-brief/slide",
            json={
                "area_id": "area-1",
                "outline": [{"id": "page-2", "page_no": 2, "theme": "证据", "purpose": "说明判断"}],
                "slides": [],
                "target": {"index": 2, "title": "证据", "purpose": "说明判断"},
                "outline_item": {"id": "page-2", "page_no": 2, "theme": "证据", "purpose": "说明判断"},
                "revision_note": "生成第二页",
                "source_ids": ["current:scope"],
            },
        )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "invalid_deck_brief_slide",
        "page_no": 2,
        "reason": "missing_required_brief_content",
        "missing_fields": ["key_message"],
        "payload_bytes": 1024,
        "repaired": False,
        "retried": False,
        "content_retried": True,
    }


def test_ppt_visual_artifacts_api_returns_slide_artifacts(monkeypatch):
    def fake_generate(payload):
        assert payload.slide_index == 2
        assert payload.visual_specs[0]["visual_id"] == "visual-1"
        return PptVisualArtifactResponse(
            slide_index=payload.slide_index,
            visual_specs=[{"visual_id": "visual-1", "visual_type": "figure", "status": "renderable"}],
            visual_artifacts=[{"visual_id": "visual-1", "url": "/download/visual-1.svg"}],
        )

    monkeypatch.setattr(ppt_planning, "generate_visual_artifacts_for_slide", fake_generate)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/visual-artifacts",
            json={
                "slide_index": 2,
                "visual_specs": [{"visual_id": "visual-1", "visual_type": "figure", "status": "renderable"}],
                "source_ids": ["current:dataset:poi"],
                "metric_context": {"metrics": []},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["slide_index"] == 2
    assert payload["visual_specs"][0]["status"] == "renderable"
    assert payload["visual_artifacts"][0]["url"] == "/download/visual-1.svg"


def test_ppt_visual_artifact_cleanup_api_deletes_only_safe_files(tmp_path, monkeypatch):
    from modules.charting import storage

    monkeypatch.setattr(storage, "CHART_DIR_PATH", tmp_path)
    visual_file = tmp_path / "visual-1.svg"
    visual_file.write_text("<svg></svg>", encoding="utf-8")

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/visual-artifacts/cleanup",
            json={"filenames": ["visual-1.svg", "missing.svg", "../escape.svg", "notes.txt"]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == ["visual-1.svg"]
    assert payload["missing"] == ["missing.svg"]
    assert payload["skipped"] == ["../escape.svg", "notes.txt"]
    assert not visual_file.exists()


def test_ppt_data_sources_api_returns_source_statuses(monkeypatch):
    captured = {}

    def fake_list(area_id, conversation_id=""):
        captured["area_id"] = area_id
        captured["conversation_id"] = conversation_id
        return [
            PptDataSourceSummary(
                id="current:dataset:poi",
                title="POI 基础数据",
                status="ready",
                summary="POI 2 条",
                count=2,
            )
        ]

    monkeypatch.setattr(ppt_planning, "list_ppt_sources", fake_list)

    with TestClient(_build_test_app()) as client:
        response = client.get("/api/v1/analysis/ppt/data/sources?area_id=area-1&conversation_id=ppt-tab-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "current:dataset:poi"
    assert payload[0]["status"] == "ready"
    assert captured == {"area_id": "area-1", "conversation_id": "ppt-tab-1"}


def test_ppt_source_manifest_api_returns_lightweight_sources(monkeypatch):
    captured = {}

    def fake_manifest(area_id, conversation_id=""):
        captured["area_id"] = area_id
        captured["conversation_id"] = conversation_id
        return [
            PptDataSourceSummary(
                id="document:doc-1",
                type="document",
                title="规划文本",
                status="ready",
                summary="PageIndex 12 项",
                count=12,
                source_kind="document",
                evidence_count=12,
                meta={
                    "label": "PageIndex 12 项",
                    "sourceKind": "document",
                    "document": {"id": "doc-1", "file_name": "plan.pdf"},
                    "document_index_preview": [{"node_id": "n1", "summary": "heavy"}],
                    "aiPayload": {"version": "ppt_ai_input_block_v1"},
                    "ai_payload": {"version": "ppt_ai_input_block_v1"},
                },
            )
        ]

    monkeypatch.setattr(ppt_planning, "list_ppt_source_manifest", fake_manifest)

    with TestClient(_build_test_app()) as client:
        response = client.get("/api/v1/analysis/ppt/data/source-manifest?area_id=area-1&conversation_id=ppt-tab-1")

    assert response.status_code == 200
    payload = response.json()
    assert captured == {"area_id": "area-1", "conversation_id": "ppt-tab-1"}
    assert payload[0]["id"] == "document:doc-1"
    assert payload[0]["source_kind"] == "document"
    assert payload[0]["meta"]["sourceKind"] == "document"
    assert "document_index_preview" not in payload[0]["meta"]
    assert "aiPayload" not in payload[0]["meta"]
    assert "ai_payload" not in payload[0]["meta"]


def test_ppt_data_sources_api_maps_database_errors(monkeypatch):
    def fake_list(area_id, conversation_id=""):
        raise SQLAlchemyError("db down")

    monkeypatch.setattr(ppt_planning, "list_ppt_sources", fake_list)

    with TestClient(_build_test_app()) as client:
        response = client.get("/api/v1/analysis/ppt/data/sources?area_id=area-1")

    assert response.status_code == 503
    assert response.json()["detail"] == "ppt_database_unavailable"


def test_ppt_data_source_delete_api_removes_persisted_source(monkeypatch):
    deleted = {}

    def fake_delete(area_id, source_id):
        deleted["area_id"] = area_id
        deleted["source_id"] = source_id
        return {"area_id": area_id, "source_id": source_id, "deleted": 1}

    monkeypatch.setattr(ppt_planning, "delete_ppt_persisted_source", fake_delete)

    with TestClient(_build_test_app()) as client:
        response = client.delete(
            "/api/v1/analysis/ppt/data/sources",
            params={"area_id": "area-1", "source_id": "package:area-1:abc"},
        )

    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    assert deleted == {"area_id": "area-1", "source_id": "package:area-1:abc"}


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
            json={"area_id": "area-1", "source_ids": ["current:dataset:poi"], "limit": 10},
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
            json={"area_id": "area-1", "source_ids": ["current:dataset:poi"], "package_mode": "evidence"},
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
            json={"area_id": "area-1", "source_ids": ["current:dataset:poi"], "package_mode": "evidence"},
        )

    assert response.status_code == 504
    assert response.json()["detail"] == "ppt_data_llm_timeout"


def test_ppt_web_source_preview_api_returns_candidate(monkeypatch):
    from modules.ppt_planning.schemas import PptDataPackageResponse, PptSource
    from router.domains import ppt_web_source

    async def fake_preview(payload):
        return PptDataPackageResponse(
            source=PptSource(
                id="web:area-1:abc",
                type="web",
                title="地区资料",
                status="ready",
                selected=True,
                meta={"sourceKind": "web"},
            ),
            summary="预览完成",
            items=[{"title": "网页", "url": "https://gov.cn/demo", "parse_status": "parsed"}],
        )

    monkeypatch.setattr(ppt_web_source, "preview_ppt_web_source", fake_preview)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/web-sources/preview",
            json={"area_id": "area-1", "region_name": "岳麓区", "topic": "文旅"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["id"] == "web:area-1:abc"
    assert payload["items"][0]["parse_status"] == "parsed"


def test_ppt_web_source_preview_api_maps_searxng_unavailable(monkeypatch):
    from router.domains import ppt_web_source

    async def fake_preview(payload):
        raise ppt_web_source.PptWebSourceSearchUnavailable("searxng_unavailable")

    monkeypatch.setattr(ppt_web_source, "preview_ppt_web_source", fake_preview)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/web-sources/preview",
            json={"area_id": "area-1", "region_name": "岳麓区", "topic": "文旅"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "searxng_unavailable"


def test_ppt_web_source_commit_api_returns_persisted_source(monkeypatch):
    from modules.ppt_planning.schemas import PptDataPackageResponse, PptSource
    from router.domains import ppt_web_source

    def fake_commit(payload):
        return PptDataPackageResponse(
            source=PptSource(
                id="web:area-1:abc",
                type="web",
                title="地区资料",
                status="ready",
                selected=True,
                meta={"sourceKind": "web", "persistedWebSource": True},
            ),
            summary="已添加",
            items=[],
        )

    monkeypatch.setattr(ppt_web_source, "commit_ppt_web_source", fake_commit)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/web-sources/commit",
            json={"area_id": "area-1", "preview": {"source": {"id": "web:area-1:abc", "title": "地区资料"}}},
        )

    assert response.status_code == 200
    assert response.json()["source"]["meta"]["persistedWebSource"] is True


def test_ppt_source_group_classification_api_returns_groups(monkeypatch):
    async def fake_classify(payload):
        return PptSourceGroupClassifyResponse(
            groups=[
                PptSourceGroup(
                    id="group:vitality",
                    title="城市活力证据",
                    source_ids=["current:dataset:poi"],
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
                    {"id": "current:dataset:poi", "type": "data", "title": "POI 基础数据", "status": "ready"},
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["groups"][0]["id"] == "group:vitality"
    assert payload["groups"][0]["source_ids"] == ["current:dataset:poi"]


def test_ppt_source_group_classification_api_returns_llm_unavailable(monkeypatch):
    async def fake_classify(payload):
        raise ppt_planning.PptPlanningLlmUnavailable("llm_unavailable")

    monkeypatch.setattr(ppt_planning, "classify_ppt_source_groups", fake_classify)

    with TestClient(_build_test_app()) as client:
        response = client.post(
            "/api/v1/analysis/ppt/source-groups/classify",
            json={
                "sources": [
                    {"id": "current:dataset:poi", "type": "data", "title": "POI 基础数据", "status": "ready"},
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
    assert response.json()["detail"] == "ppt_outline_invalid_response"


def test_ppt_spec_api_maps_outline_timeout(monkeypatch):
    async def fake_generate(payload):
        raise httpx.TimeoutException("timed out")

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

    assert response.status_code == 504
    assert response.json()["detail"] == "ppt_outline_llm_timeout"
