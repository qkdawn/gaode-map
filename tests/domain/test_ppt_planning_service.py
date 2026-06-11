import asyncio
import json

import pytest

from modules.ppt_planning.schemas import (
    DeckBriefRequest,
    DeckBriefSlideRequest,
    DeckSlideBrief,
    PptOutlineItem,
    PptOutlineSectionRequest,
    PptSourceGroupClassifyRequest,
    PptSpecRequest,
    PptSpecResponse,
)
from modules.ppt_planning.service import (
    PptPlanningLlmUnavailable,
    classify_ppt_source_groups,
    generate_deck_brief,
    generate_ppt_spec,
    regenerate_deck_brief_slide,
    regenerate_ppt_outline_section,
)


def test_generate_ppt_spec_returns_ai_outline(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "title": "长沙县政府原址城市更新目录",
            "goal": "形成政府评审汇报目录",
            "audience": "政府评审",
            "deck_type": "城市更新概念策划",
            "page_count": 15,
            "outline": [
                {"id": "page-1", "page_no": 1, "theme": "项目命题", "purpose": "建立汇报主线"},
                {"id": "page-2", "page_no": 2, "theme": "空间证据", "purpose": "说明等时圈数据依据"},
            ],
            "source_summary": "已选择 2 个来源，包含联网研究",
            "missing_inputs": [],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)

    response = asyncio.run(generate_ppt_spec(
        PptSpecRequest(
            area_id="area-1",
            source_ids=["summary", "scope"],
            topic="长沙县政府原址城市更新",
            audience="政府评审",
            page_count=15,
            research_enabled=True,
        )
    ))

    assert response.page_count == 15
    assert response.audience == "政府评审"
    assert "PPT Spec" not in response.title
    assert response.outline[0].theme == "项目命题"
    assert response.missing_inputs == []


def test_generate_ppt_spec_fails_without_llm(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: False)
    with pytest.raises(PptPlanningLlmUnavailable):
        asyncio.run(generate_ppt_spec(PptSpecRequest()))


def test_regenerate_ppt_outline_section_returns_single_item(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)
    seen_payload = {}

    async def fake_invoke(**kwargs):
        seen_payload.update(kwargs.get("user_payload") or {})
        return {
            "id": "page-2",
            "page_no": 99,
            "theme": "空间问题诊断",
            "purpose": "突出使用者不喜欢的小节修改方向",
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    target = PptOutlineItem(id="page-2", page_no=2, theme="空间证据", purpose="说明现状")

    response = asyncio.run(regenerate_ppt_outline_section(PptOutlineSectionRequest(
        area_id="area-1",
        spec=PptSpecResponse(
            title="更新策划目录",
            goal="形成政府评审汇报目录",
            audience="政府评审",
            deck_type="城市更新概念策划",
            page_count=15,
            outline=[target],
        ),
        outline=[target],
        target=target,
        revision_note="这一页要更像问题诊断",
        source_ids=["system:scope"],
    )))

    assert seen_payload["task"] == "ppt_outline_section_regeneration"
    assert seen_payload["revision_note"] == "这一页要更像问题诊断"
    assert response.id == "page-2"
    assert response.page_no == 2
    assert response.theme == "空间问题诊断"


def test_generate_ppt_spec_sends_compact_carrier_package_to_llm(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)

    seen_payload = {}

    async def fake_invoke(**kwargs):
        seen_payload.update(kwargs.get("user_payload") or {})
        return {
            "title": "空间载体策划目录",
            "goal": "形成政府评审汇报目录",
            "audience": "政府评审",
            "deck_type": "城市更新概念策划",
            "page_count": 15,
            "outline": [
                {"id": "page-1", "page_no": 1, "theme": "空间载体判断", "purpose": "说明载体类型"},
            ],
            "source_summary": "已选择 1 个来源，包含联网研究",
            "missing_inputs": [],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    representative_pois = [
        {
            "id": f"poi-{index}",
            "name": f"代表 POI {index}",
            "address": "很长的地址" * 50,
            "category": "餐饮服务",
            "subcategory": "中餐厅",
            "location": [112.0 + index * 0.001, 28.0],
            "raw_payload": {"should": "not reach llm"},
        }
        for index in range(1, 10)
    ]
    road_features = [
        {"id": f"road-{index}", "path": [[112.0, 28.0], [112.01, 28.01]], "choice_score": 0.7}
        for index in range(1, 40)
    ]
    package_payload = {
        "id": "package:poi-road-carriers:test",
        "title": "POI × 路网空间载体资料包",
        "summary": "已识别 1 个空间载体。",
        "package_mode": "evidence",
        "intent": "识别空间载体",
        "source_ids": ["system:poi", "system:road-syntax", "system:population", "system:nightlight"],
        "items": representative_pois,
        "road_context": {
            "type": "road_context",
            "source": "road_syntax.roads.features",
            "total": len(road_features),
            "included": len(road_features),
            "coverage": "complete",
            "features": road_features,
        },
        "carriers": [
            {
                "carrier_id": "corridor_01",
                "carrier_type": "corridor",
                "carrier_label": "商业活力廊道",
                "summary": "高分路段形成廊道轴线。",
                "road_metrics": {"road_count": 4, "choice_score": 0.72},
                "poi_metrics": {"total_related_poi_count": 128, "function_counts": {"commerce": 88}},
                "population_metrics": {"demand_strength": "强"},
                "nightlight_metrics": {"night_activity_level": "中"},
                "representative_pois": representative_pois,
                "geometry": {
                    "polygon": [[112.0, 28.0], [112.1, 28.0], [112.1, 28.1]],
                    "boundary": [[112.0, 28.0], [112.1, 28.1]],
                },
            }
        ],
    }

    asyncio.run(generate_ppt_spec(PptSpecRequest(
        area_id="area-1",
        source_ids=["package:poi-road-carriers:test"],
        topic="空间载体策划",
        sources=[{
            "id": "package:poi-road-carriers:test",
            "type": "package",
            "title": "POI × 路网空间载体资料包",
            "status": "ready",
            "selected": True,
            "meta": {"sourceKind": "package", "package": package_payload},
        }],
    )))

    llm_package = seen_payload["sources"][0]["meta"]["package"]
    assert "features" not in llm_package["road_context"]
    assert llm_package["road_context"]["omitted_feature_count"] == len(road_features)
    assert len(llm_package["items"]) == 8
    assert len(llm_package["carriers"][0]["representative_pois"]) == 3
    assert llm_package["carriers"][0]["geometry_omitted"] is True
    assert "geometry" not in llm_package["carriers"][0]

    serialized = json.dumps(seen_payload["sources"], ensure_ascii=False)
    assert "raw_payload" not in serialized
    assert "road-39" not in serialized
    assert "[112.1, 28.1]" not in serialized


def test_generate_deck_brief_returns_ai_directive_not_pptx(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)

    seen_directive_payload = {}

    async def fake_invoke(**kwargs):
        task = (kwargs.get("user_payload") or {}).get("task")
        if task == "ppt_outline_generation":
            return {
                "title": "更新策划目录",
                "goal": "形成政府评审汇报目录",
                "audience": "政府评审",
                "deck_type": "城市更新概念策划",
                "page_count": 15,
                "outline": [
                    {"id": "page-1", "page_no": 1, "theme": "项目命题", "purpose": "建立汇报主线"},
                ],
                "source_summary": "已选择 1 个来源，不包含联网研究",
                "missing_inputs": [],
            }
        seen_directive_payload.update(kwargs.get("user_payload") or {})
        return {
            "status": "draft",
            "slides": [
                {
                    "index": 1,
                    "title": "项目命题",
                    "purpose": "建立汇报主线",
                    "key_message": "说明为什么要更新",
                    "visual_plan": "区域底图与一句话判断",
                    "required_sources": ["system:scope"],
                    "speaker_notes": "第一阶段先生成逐页指令，不直接生成 PPTX。",
                }
            ],
            "source_summary": "已选择 1 个来源，不包含联网研究",
            "missing_inputs": [],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    spec = asyncio.run(generate_ppt_spec(PptSpecRequest(topic="更新策划", source_ids=["summary"], page_count=15)))
    response = asyncio.run(generate_deck_brief(DeckBriefRequest(
        spec=spec,
        source_ids=["package:poi:test"],
        sources=[{
            "id": "package:poi:test",
            "type": "package",
            "title": "POI 资料包",
            "status": "ready",
            "selected": True,
            "meta": {"package": {"summary": "POI 资料包"}},
        }],
        analysis_context={"scope": {"time_min": 35}},
        topic="更新策划",
    )))

    assert response.status == "draft"
    assert response.slides
    assert response.slides[0].title == "项目命题"
    assert "不直接生成 PPTX" in response.slides[0].speaker_notes
    assert seen_directive_payload["sources"][0]["id"] == "package:poi:test"
    assert seen_directive_payload["analysis_context"]["scope"]["time_min"] == 35


def test_regenerate_deck_brief_slide_returns_single_slide(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)
    seen_payload = {}

    async def fake_invoke(**kwargs):
        seen_payload.update(kwargs.get("user_payload") or {})
        return {
            "index": 99,
            "title": "项目命题重写",
            "purpose": "更聚焦评审关心的问题",
            "key_message": "更新必要性来自空间证据。",
            "visual_plan": "区位底图 + 诊断标签",
            "required_sources": ["system:scope"],
            "speaker_notes": "强调本页不是最终 PPTX。",
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    target = DeckSlideBrief(index=1, title="项目命题", purpose="建立汇报主线")
    outline_item = PptOutlineItem(id="page-1", page_no=1, theme="项目命题", purpose="建立汇报主线")

    response = asyncio.run(regenerate_deck_brief_slide(DeckBriefSlideRequest(
        area_id="area-1",
        outline=[outline_item],
        slides=[target],
        target=target,
        outline_item=outline_item,
        revision_note="更强调评审关注的问题",
        source_ids=["system:scope"],
    )))

    assert seen_payload["task"] == "ppt_directive_slide_regeneration"
    assert seen_payload["outline_item"]["page_no"] == 1
    assert response.index == 1
    assert response.title == "项目命题重写"
    assert response.required_sources == ["system:scope"]


def test_classify_ppt_source_groups_returns_normalized_groups(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "groups": [
                {
                    "id": "group:vitality",
                    "title": "城市活力证据",
                    "source_ids": ["system:poi", "system:unknown", "system:poi"],
                    "meta": {"reason": "POI 用于解释活力。"},
                }
            ]
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)

    response = asyncio.run(classify_ppt_source_groups(PptSourceGroupClassifyRequest(
        sources=[
            {"id": "system:poi", "type": "data", "title": "POI 基础数据", "status": "ready"},
            {"id": "system:scope", "type": "data", "title": "当前等时圈范围", "status": "ready"},
        ],
    )))

    assert response.groups[0].id == "group:vitality"
    assert response.groups[0].source_ids == ["system:poi"]
    assert response.groups[1].id == "group:uncategorized"
    assert response.groups[1].source_ids == ["system:scope"]


def test_classify_ppt_source_groups_fails_without_llm(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: False)
    with pytest.raises(PptPlanningLlmUnavailable):
        asyncio.run(classify_ppt_source_groups(PptSourceGroupClassifyRequest(
            sources=[
                {"id": "system:poi", "type": "data", "title": "POI 基础数据", "status": "ready"},
            ],
        )))
