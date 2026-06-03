import asyncio

import pytest

from modules.ppt_planning.schemas import DeckBriefRequest, PptSourceGroupClassifyRequest, PptSpecRequest
from modules.ppt_planning.service import (
    PptPlanningLlmUnavailable,
    classify_ppt_source_groups,
    generate_deck_brief,
    generate_ppt_spec,
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
