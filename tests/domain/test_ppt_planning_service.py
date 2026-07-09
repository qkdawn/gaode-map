import asyncio
import json

import pytest

from modules.ppt_planning.schemas import (
    DeckBriefRequest,
    PptVisualArtifactRequest,
    DeckBriefSlideRequest,
    DeckNarrativePlanRequest,
    DeckNarrativePlanResponse,
    DeckNarrativeEvidenceBucket,
    DeckNarrativeSlideRole,
    DeckNarrativeVisualStrategy,
    DeckSlideBrief,
    PptOutlineItem,
    PptOutlineSectionRequest,
    PptSourceGroupClassifyRequest,
    PptSpecRequest,
    PptSpecResponse,
)
from modules.ppt_planning.service import (
    PptPlanningInvalidResponse,
    PptPlanningLlmUnavailable,
    _build_ppt_context_bundle,
    classify_ppt_source_groups,
    generate_deck_brief,
    generate_narrative_plan,
    generate_ppt_spec,
    regenerate_deck_brief_slide,
    regenerate_ppt_outline_section,
)
from modules.agent.providers.chat_parser import LlmJsonParseError
from modules.ppt_planning.metric_context import build_metric_context, validate_visual_assets


def _ai_payload(
    source_id="current:analysis:poi_h3",
    *,
    title="POI / H3 空间结构分析",
    source_kind="system",
    scope=None,
    metrics=None,
    metric_gaps=None,
    evidence=None,
    excluded=None,
):
    metrics = metrics or []
    metric_gaps = metric_gaps or []
    evidence = evidence or []
    included = []
    if scope:
        included.append("scope")
    if metrics:
        included.append("metrics")
    if metric_gaps:
        included.append("metric_gaps")
    if evidence:
        included.append("evidence")
    evidence_nodes = []
    for index, item in enumerate(evidence, start=1):
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        node_source_id = item.get("source_id") or payload.get("source_id") or source_id
        node_type = item.get("type") or item.get("evidence_level") or "source_evidence"
        evidence_nodes.append({
            "id": item.get("id") or payload.get("evidence_node_id") or f"{node_source_id}:evidence:{index}",
            "source_id": node_source_id,
            "source_type": payload.get("source_type") or source_kind,
            "title": item.get("title") or title,
            "content": item.get("content") or item.get("text") or item.get("summary") or "",
            "summary": item.get("summary") or item.get("text") or item.get("content") or "",
            "metadata": payload,
            "locator": item.get("locator") or payload.get("locator") or "",
            "score": item.get("score") or 0,
            "evidence_level": node_type,
            "warnings": item.get("warnings") or [],
            "citation": item.get("citation") or "",
        })
    return {
        "version": "ppt_ai_input_block_v1",
        "source_id": source_id,
        "title": title,
        "source_kind": source_kind,
        "included": included,
        "scope": scope,
        "metrics": metrics,
        "metric_gaps": metric_gaps,
        "evidence_nodes": evidence_nodes,
        "evidenceNodes": evidence_nodes,
        "visual_specs": [],
        "excluded": excluded or [{"type": "raw_payload", "reason": "不传原始数据。"}],
        "counts": {
            "scope": 1 if scope else 0,
            "metrics": len(metrics),
            "metric_gaps": len(metric_gaps),
            "evidence": len(evidence),
            "visual_specs": 0,
        },
        "policy": "test ai payload only",
    }


def test_generate_ppt_spec_returns_ai_outline(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)
    seen_kwargs = {}

    async def fake_invoke(**kwargs):
        seen_kwargs.update(kwargs)
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
            "source_summary": "已选择 2 个来源，包含联网来源",
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
            web_sources_enabled=True,
        )
    ))

    assert response.page_count == 15
    assert response.audience == "政府评审"
    assert "PPT Spec" not in response.title
    assert response.outline[0].theme == "项目命题"
    assert response.missing_inputs == []
    assert seen_kwargs["stream"] is False
    assert seen_kwargs["enable_thinking"] is False
    assert seen_kwargs["timeout_s"] == 0.0


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
        source_ids=["current:scope"],
    )))

    assert seen_payload["task"] == "ppt_outline_section_regeneration"
    assert seen_payload["revision_note"] == "这一页要更像问题诊断"
    assert response.id == "page-2"
    assert response.page_no == 2
    assert response.theme == "空间问题诊断"


def test_generate_narrative_plan_aligns_roles_to_outline(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "storyline": "问题到证据",
            "chapters": [
                {"name": "开篇定调", "page_range": "01", "job": "建立问题", "output": "明确主线"},
            ],
            "evidence_buckets": [
                {"id": "scope", "label": "范围", "allowed_sources": ["current:scope"]},
                {"id": "metrics", "label": "指标", "allowed_sources": ["current:scope"]},
            ],
            "slide_roles": [
                {"page_no": 1, "role": "开题", "job": "建立问题", "evidence_bucket": "scope", "visual_family": "existing_map_layer"},
                {"page_no": 2, "role": "证据", "job": "说明判断", "evidence_bucket": "metrics", "visual_family": "dashboard"},
            ],
            "visual_rules": {
                "spatial_first": True,
                "numeric_charts_require_data": True,
                "diagram_for_strategy_pages": True,
                "no_fallback_bar": True,
            },
            "missing_inputs": [],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    outline = [
        PptOutlineItem(id="page-1", page_no=1, theme="开题", purpose="建立问题"),
        PptOutlineItem(id="page-2", page_no=2, theme="证据", purpose="说明判断"),
    ]

    response = asyncio.run(generate_narrative_plan(DeckNarrativePlanRequest(
        area_id="area-1",
        spec=PptSpecResponse(
            title="测试目录",
            goal="测试",
            audience="政府评审",
            deck_type="城市更新概念策划",
            page_count=2,
            outline=outline,
        ),
        outline=outline,
        source_ids=["current:scope"],
    )))

    assert response.storyline == "问题到证据"
    assert [role.page_no for role in response.slide_roles] == [1, 2]
    assert response.slide_roles[1].visual_family == "dashboard"
    assert response.slide_roles[1].evidence_bucket == "metrics"
    assert response.evidence_buckets[1].id == "metrics"
    assert response.visual_rules.no_fallback_bar is True


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
            "source_summary": "已选择 1 个来源，包含联网来源",
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
        "source_ids": ["current:dataset:poi", "current:analysis:road", "current:analysis:population", "current:analysis:nightlight"],
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

    package_source_id = "package:poi-road-carriers:test"
    package_ai_payload = _ai_payload(
        package_source_id,
        title="POI × 路网空间载体资料包",
        source_kind="package",
        evidence=[
            {
                "source_id": package_source_id,
                "type": "package_summary",
                "title": "POI × 路网空间载体资料包",
                "text": package_payload["summary"],
                "payload": {"package_mode": "evidence", "intent": "识别空间载体"},
            },
            {
                "source_id": package_source_id,
                "type": "package_carrier",
                "title": "商业活力廊道",
                "text": "高分路段形成廊道轴线。",
                "payload": {"carrier_id": "corridor_01", "road_metrics": {"road_count": 4, "choice_score": 0.72}},
            },
        ],
        excluded=[
            {"type": "package_full_items", "reason": "不传完整 POI 明细。", "count": len(representative_pois)},
            {"type": "package_carrier_geometries", "reason": "不传载体 geometry。", "count": 1},
        ],
    )

    asyncio.run(generate_ppt_spec(PptSpecRequest(
        area_id="area-1",
        source_ids=[package_source_id],
        topic="空间载体策划",
        sources=[{
            "id": package_source_id,
            "type": "package",
            "title": "POI × 路网空间载体资料包",
            "status": "ready",
            "selected": True,
            "meta": {"sourceKind": "package", "package": package_payload, "aiPayload": package_ai_payload},
        }],
    )))

    source_meta = seen_payload["sources"][0]["meta"]
    assert "package" not in source_meta
    assert source_meta["aiPayload"]["counts"]["evidence"] == 2
    assert seen_payload["source_manifest"][0]["excluded"][0]["type"] == "package_full_items"
    assert seen_payload["evidence_context"]["items"][0]["evidence_level"] == "package_summary"
    assert seen_payload["evidence_context"]["items"][0]["source_type"] == "package"
    assert seen_payload["evidence_node_context"]["items"][1]["metadata"]["carrier_id"] == "corridor_01"

    serialized = json.dumps(seen_payload["sources"], ensure_ascii=False)
    assert "raw_payload" not in serialized
    assert "road-39" not in serialized
    assert "[112.1, 28.1]" not in serialized


def test_generate_ppt_spec_sends_document_index_preview_to_llm(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)

    seen_payload = {}

    async def fake_invoke(**kwargs):
        seen_payload.update(kwargs.get("user_payload") or {})
        return {
            "title": "政策证据策划目录",
            "goal": "形成政府评审汇报目录",
            "audience": "政府评审",
            "deck_type": "城市更新概念策划",
            "page_count": 15,
            "outline": [
                {"id": "page-1", "page_no": 1, "theme": "政策要求", "purpose": "说明政策依据"},
            ],
            "source_summary": "已选择 1 个来源，包含联网来源",
            "missing_inputs": [],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)

    document_ai_payload = _ai_payload(
        "document:doc-1",
        title="更新政策研究",
        source_kind="document",
        evidence=[{
            "source_id": "document:doc-1",
            "type": "pageindex_node",
            "title": "政策要求",
            "text": "政策要求完善公共服务设施。",
            "payload": {"node_id": "0001", "level": 1, "page_start": 3, "page_end": 3},
        }],
        excluded=[{"type": "document_full_text", "reason": "不传文档全文。"}],
    )

    asyncio.run(generate_ppt_spec(PptSpecRequest(
        area_id="area-1",
        source_ids=["document:doc-1"],
        topic="政策导向策划",
        sources=[{
            "id": "document:doc-1",
            "type": "document",
            "title": "更新政策研究",
            "status": "ready",
            "selected": True,
            "meta": {
                "label": "章节 1 个",
                "sourceKind": "document",
                "document": {
                    "id": "doc-1",
                    "title": "更新政策研究",
                    "file_name": "policy.pdf",
                    "file_type": "pdf",
                    "document_role": "policy_document",
                    "status": "parsed",
                    "index_count": 1,
                },
                "document_index_preview": [
                    {
                        "node_id": "0001",
                        "parent_node_id": "root",
                        "title": "政策要求",
                        "level": 1,
                        "summary": "政策要求完善公共服务设施。",
                        "page_start": 3,
                        "page_end": 3,
                        "text": "不应进入 LLM 的长原文",
                    }
                ],
                "aiPayload": document_ai_payload,
            },
        }],
    )))

    source_payload = seen_payload["sources"][0]
    assert source_payload["type"] == "document"
    assert "document" not in source_payload["meta"]
    assert "document_index_preview" not in source_payload["meta"]
    assert seen_payload["evidence_context"]["items"][0]["content"] == "政策要求完善公共服务设施。"
    assert seen_payload["evidence_context"]["items"][0]["source_type"] == "document"
    assert seen_payload["evidence_node_context"]["items"][0]["id"] == "document:doc-1:evidence:1"
    serialized = json.dumps(source_payload, ensure_ascii=False)
    assert "不应进入 LLM 的长原文" not in serialized


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
                "source_summary": "已选择 1 个来源，不包含联网来源",
                "missing_inputs": [],
            }
        seen_directive_payload.update(kwargs.get("user_payload") or {})
        poi_metric = next(
            item for item in seen_directive_payload["metric_context"]["metrics"]
            if item.get("source_id") == "current:dataset:poi" and item.get("label") == "POI 数量"
        )
        return {
            "status": "draft",
            "slides": [
                {
                    "index": 1,
                    "title": "项目命题",
                    "purpose": "建立汇报主线",
                    "key_message": "说明为什么要更新，POI 共 120 个。",
                    "insight": "片区具备成片承接条件。",
                    "evidence_explanation": ["POI 计数来自当前范围去重统计", "仅使用 ready 指标，不读取原始明细"],
                    "visual_plan": "区域底图与 POI 数量柱状图",
                    "required_sources": ["current:scope"],
                    "metric_claims": [
                        {
                            "claim_id": "c1",
                            "metric_id": poi_metric["metric_id"],
                            "text": "POI 共 120 个",
                            "value": 120,
                            "unit": "个",
                        }
                    ],
                    "visual_specs": [
                        {
                            "visual_id": "visual-poi",
                            "visual_type": "figure",
                            "status": "renderable",
                            "title": "POI 数量",
                            "data": {
                                "columns": [{"key": "label", "label": "指标"}, {"key": "value", "label": "数值"}],
                                "rows": [{"label": "POI 总数", "value": 120}],
                            },
                            "source_metric_ids": [poi_metric["metric_id"]],
                        }
                    ],
                }
            ],
            "source_summary": "已选择 1 个来源，不包含联网来源",
            "missing_inputs": [],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    spec = asyncio.run(generate_ppt_spec(PptSpecRequest(topic="更新策划", source_ids=["summary"], page_count=15)))
    poi_metric_payload = {
        "metric_id": "analysis:poi:poi_count",
        "domain": "poi",
        "label": "POI 数量",
        "value": 120,
        "unit": "个",
        "scope": "35分钟",
        "source_id": "current:dataset:poi",
        "source_ids": ["current:dataset:poi"],
        "source_path": "allPoisDetails.length",
        "calculation_method": "当前范围内已抓取 POI 明细去重计数。",
        "status": "ready",
        "description": "POI 数量 120 个",
    }
    response = asyncio.run(generate_deck_brief(DeckBriefRequest(
        spec=spec,
        source_ids=["package:poi:test", "current:dataset:poi"],
        sources=[
            {
                "id": "package:poi:test",
                "type": "package",
                "title": "POI 资料包",
                "status": "ready",
                "selected": True,
                "meta": {"aiPayload": _ai_payload("package:poi:test", title="POI 资料包", source_kind="package", evidence=[{"title": "资料包摘要", "text": "POI 资料包"}])},
            },
            {
                "id": "current:dataset:poi",
                "type": "data",
                "title": "POI 基础数据",
                "status": "ready",
                "selected": True,
                "meta": {
                    "sourceKind": "system",
                    "aiPayload": _ai_payload(
                        "current:dataset:poi",
                        title="POI 基础数据",
                        source_kind="system",
                        metrics=[poi_metric_payload],
                        evidence=[{"source_id": "current:dataset:poi", "type": "dataset_summary", "title": "POI 基础数据", "text": "POI 共 120 个。"}],
                    ),
                },
            },
        ],
        topic="更新策划",
    )))

    assert response.status == "draft"
    assert response.slides
    assert response.slides[0].title == "项目命题"
    assert response.slides[0].key_message == "说明为什么要更新，POI 共 120 个。"
    assert response.slides[0].insight == "片区具备成片承接条件"
    assert response.slides[0].evidence_explanation == ["POI 计数来自当前范围去重统计", "仅使用 ready 指标，不读取原始明细"]
    assert response.slides[0].metric_claims[0]["value"] == 120
    assert response.slides[0].visual_specs[0]["data"]["rows"][0]["value"] == 120
    assert response.slides[0].visual_artifacts == []
    assert seen_directive_payload["metric_context"]["metric_count"] >= 1
    assert "current" not in seen_directive_payload
    assert seen_directive_payload["sources"][0]["id"] == "package:poi:test"
    assert seen_directive_payload["evidence_context"]["item_count"] >= 1
    assert seen_directive_payload["source_manifest"][0]["transport_status"] in {"included", "selected_no_payload"}


def test_generate_visual_artifacts_for_slide_renders_supported_visuals():
    from modules.ppt_planning.service import generate_visual_artifacts_for_slide

    response = generate_visual_artifacts_for_slide(PptVisualArtifactRequest(
        slide_index=1,
        visual_specs=[
            {
                "visual_id": "visual-poi",
                "visual_type": "figure",
                "status": "renderable",
                "title": "POI 数量",
                "source_metric_ids": ["poi:total"],
                "data": {
                    "columns": [{"key": "label", "label": "指标"}, {"key": "value", "label": "数值"}],
                    "rows": [{"label": "POI 总数", "value": 120, "metric_id": "poi:total"}],
                },
            },
            {
                "visual_id": "visual-framework",
                "visual_type": "diagram",
                "status": "renderable",
                "title": "策略框架",
                "nodes": [{"id": "a", "label": "现状"}, {"id": "b", "label": "行动"}],
                "links": [{"source": "a", "target": "b"}],
            },
            {
                "visual_id": "visual-matrix",
                "visual_type": "matrix",
                "status": "renderable",
                "title": "诊断矩阵",
                "data": {
                    "rows": [{"id": "产权干扰", "label": "产权干扰"}, {"id": "功能补位", "label": "功能补位"}],
                    "columns": [{"id": "痛点维度", "label": "痛点维度"}, {"id": "更新策略", "label": "更新策略"}],
                    "cells": [
                        {"row": "产权干扰", "column": "痛点维度", "label": "边界复杂"},
                        {"row": "产权干扰", "column": "更新策略", "label": "分期协商"},
                        {"row": "功能补位", "column": "痛点维度", "label": "公共服务不足"},
                        {"row": "功能补位", "column": "更新策略", "label": "优先补短板"},
                    ],
                },
            },
            {
                "visual_id": "visual-map",
                "visual_type": "existing_asset",
                "status": "needs_existing_asset",
                "title": "空间图",
                "asset_id": "missing-map",
            },
        ],
        metric_context={
            "metrics": [{
                "metric_id": "poi:total",
                "source_id": "current:analysis:poi",
                "domain": "poi",
                "label": "POI 总数",
                "value": 120,
                "unit": "个",
                "status": "ready",
            }],
        },
    ))

    assert response.slide_index == 1
    assert len(response.visual_artifacts) == 3
    assert [artifact["visual_id"] for artifact in response.visual_artifacts] == ["visual-poi", "visual-framework", "visual-matrix"]
    assert all(artifact["url"].endswith(".svg") for artifact in response.visual_artifacts)


def test_generate_visual_artifacts_for_slide_skips_unstructured_diagram_and_matrix():
    from modules.ppt_planning.metric_context import validate_visual_assets
    from modules.ppt_planning.service import generate_visual_artifacts_for_slide

    assets = validate_visual_assets({
        "visual_specs": [
            {
                "visual_id": "loose-diagram",
                "visual_type": "diagram",
                "title": "空间载体分级诊断框架",
                "nodes": [{"id": "a", "label": "夜间消费街区"}],
            },
            {
                "visual_id": "empty-matrix",
                "visual_type": "matrix",
                "title": "现状痛点与应对策略矩阵",
                "data": {
                    "rows": [{"id": "产权干扰", "label": "产权干扰"}],
                    "columns": [{"id": "痛点维度", "label": "痛点维度"}],
                    "cells": [],
                },
            },
        ],
    }, {}, [])

    assert assets["visual_specs"][0]["status"] == "missing_data"
    assert "无意义框图" in assets["visual_specs"][0]["data"]["reason"]
    assert assets["visual_specs"][1]["status"] == "missing_data"
    assert "未生成空彩块" in assets["visual_specs"][1]["data"]["reason"]

    response = generate_visual_artifacts_for_slide(PptVisualArtifactRequest(
        slide_index=1,
        visual_specs=assets["visual_specs"],
        metric_context={},
    ))

    assert response.visual_artifacts == []


def test_visual_assets_require_ready_metric_ids_for_numeric_rendering():
    from modules.ppt_planning.metric_context import validate_visual_assets

    assets = validate_visual_assets({
        "visual_specs": [{
            "visual_id": "unbound-bar",
            "visual_type": "figure",
            "title": "POI 对比",
            "data": {
                "columns": [{"key": "label"}, {"key": "value"}],
                "rows": [{"label": "餐饮", "value": 120}],
            },
        }],
    }, {"metrics": []}, [])

    assert assets["visual_specs"][0]["status"] == "missing_data"
    assert "ready metric_id" in assets["visual_specs"][0]["data"]["reason"]


def test_generate_visual_artifacts_for_slide_does_not_fallback_unknown_to_bar():
    from modules.ppt_planning.service import generate_visual_artifacts_for_slide

    response = generate_visual_artifacts_for_slide(PptVisualArtifactRequest(
        slide_index=1,
        visual_specs=[
            {
                "visual_id": "visual-map-overlay",
                "visual_type": "map_overlay",
                "status": "renderable",
                "title": "等时圈叠加",
                "data": {
                    "columns": [{"key": "label"}, {"key": "value"}],
                    "rows": [{"label": "范围", "value": 1}],
                },
            }
        ],
        metric_context={},
    ))

    assert response.visual_artifacts == []


def test_regenerate_deck_brief_slide_returns_single_slide(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)
    seen_payload = {}

    async def fake_invoke(**kwargs):
        seen_payload.update(kwargs.get("user_payload") or {})
        nightlight_metric = next(
            item for item in seen_payload["metric_context"]["metrics"]
            if item.get("source_id") == "current:analysis:nightlight" and item.get("label") == "夜光峰值"
        )
        return {
            "index": 99,
            "title": "项目命题重写",
            "purpose": "更聚焦评审关心的问题",
            "key_message": "更新必要性来自夜光峰值 9.8。",
            "insight": "夜光峰值集中在核心片区边缘，说明空间冲突具有方向性。",
            "evidence_explanation": ["夜光峰值来自当前分析范围汇总", "未用原始像元明细直接判断"],
            "visual_plan": "区位底图 + 夜光峰值指标卡",
            "required_sources": ["current:scope"],
            "metric_claims": [
                {"metric_id": nightlight_metric["metric_id"], "value": 9.8, "unit": "", "text": "夜光峰值 9.8"}
            ],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    target = DeckSlideBrief(index=1, title="项目命题", purpose="建立汇报主线")
    outline_item = PptOutlineItem(id="page-1", page_no=1, theme="项目命题", purpose="建立汇报主线")
    next_outline_item = PptOutlineItem(id="page-2", page_no=2, theme="空间证据", purpose="承接判断")
    nightlight_metric_payload = {
        "metric_id": "analysis:nightlight:max_radiance",
        "domain": "nightlight",
        "label": "夜光峰值",
        "value": 9.8,
        "unit": "",
        "scope": "当前分析范围",
        "source_id": "current:analysis:nightlight",
        "source_ids": ["current:analysis:nightlight"],
        "source_path": "nightlightOverview.summary.max_radiance",
        "calculation_method": "夜光峰值来自当前范围夜光分析汇总。",
        "status": "ready",
        "description": "夜光峰值 9.8",
    }

    response = asyncio.run(regenerate_deck_brief_slide(DeckBriefSlideRequest(
        area_id="area-1",
        outline=[outline_item, next_outline_item],
        slides=[target],
        target=target,
        outline_item=outline_item,
        narrative_plan=DeckNarrativePlanResponse(
            storyline="问题到证据",
            slide_roles=[
                DeckNarrativeSlideRole(page_no=1, role="开题", job="建立问题"),
                DeckNarrativeSlideRole(page_no=2, role="证据", job="承接判断"),
            ],
        ),
        revision_note="更强调评审关注的问题",
        source_ids=["current:analysis:nightlight"],
        sources=[{
            "id": "current:analysis:nightlight",
            "type": "data",
            "title": "夜光强度分析",
            "status": "ready",
            "selected": True,
            "meta": {
                "sourceKind": "system",
                "aiPayload": _ai_payload(
                    "current:analysis:nightlight",
                    title="夜光强度分析",
                    source_kind="system",
                    metrics=[nightlight_metric_payload],
                ),
            },
        }],
    )))

    assert seen_payload["task"] == "ppt_directive_slide_regeneration"
    assert seen_payload["outline_item"]["page_no"] == 1
    assert seen_payload["next_outline_summary"]["page_no"] == 2
    assert "slides" not in seen_payload
    assert seen_payload["brief_generation_context"]["page_context_packet"]["page_no"] == 1
    assert seen_payload["narrative_plan"]["slide_roles"][0]["page_no"] == 1
    assert seen_payload["target_slide_role"]["role"] == "开题"
    assert "current" not in seen_payload
    assert response.index == 1
    assert response.title == "项目命题重写"
    assert response.insight == "夜光峰值集中在核心片区边缘，说明空间冲突具有方向性"
    assert response.evidence_explanation == ["夜光峰值来自当前分析范围汇总", "未用原始像元明细直接判断"]
    assert response.required_sources == ["current:scope"]
    assert response.metric_claims[0]["value"] == 9.8


def test_regenerate_deck_brief_slide_repairs_invalid_json(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)
    calls = []
    invalid_json = '{"index":1,"title":"策略页","purpose":"说明路径","key_message":"形成分期路径","visual_plan":"路径图","required_sources":["current:scope"],"metric_claims":[],"metric_gaps":[],"visual_specs":[{"visual_type":"diagram","title":"路径图","status":"needs_design_render","data":{"groups":[{"id":"timeline"},{"id":"financing"},"links":[]}}]}'

    async def fake_invoke(**kwargs):
        calls.append(kwargs)
        payload = kwargs.get("user_payload") or {}
        if payload.get("task") == "repair_invalid_json":
            return {
                "index": 1,
                "title": "策略页",
                "purpose": "说明路径",
                "key_message": "形成分期路径",
                "visual_plan": "路径图",
                "required_sources": ["current:scope"],
                "metric_claims": [],
                "metric_gaps": [],
                "visual_specs": [{
                    "visual_type": "diagram",
                    "title": "路径图",
                    "status": "needs_design_render",
                    "data": {
                        "groups": [{"id": "timeline"}, {"id": "financing"}],
                        "links": [],
                    },
                }],
            }
        raise LlmJsonParseError(json.JSONDecodeError("Expecting ',' delimiter", invalid_json, 220), invalid_json)

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    target = DeckSlideBrief(index=1, title="策略页", purpose="说明路径")
    outline_item = PptOutlineItem(id="page-1", page_no=1, theme=target.title, purpose=target.purpose)

    response = asyncio.run(regenerate_deck_brief_slide(DeckBriefSlideRequest(
        area_id="area-1",
        outline=[outline_item],
        slides=[],
        target=target,
        outline_item=outline_item,
        narrative_plan=DeckNarrativePlanResponse(
            storyline="问题到证据",
            slide_roles=[DeckNarrativeSlideRole(page_no=1, role="策略", job="说明路径")],
        ),
        revision_note="按已确认目录和叙事方案生成这一页 brief。",
        source_ids=["current:scope"],
    )))

    assert response.index == 1
    assert response.visual_artifacts == []
    assert response.visual_specs[0]["data"]["groups"][1]["id"] == "financing"
    assert [call["user_payload"]["task"] for call in calls] == [
        "ppt_directive_slide_regeneration",
        "repair_invalid_json",
    ]


def test_regenerate_deck_brief_slide_reports_json_error_after_repair_and_retry_fail(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)
    invalid_json = '{"index":1,"title":"坏 JSON","visual_specs":[{"data":{"groups":[{"id":"a"},"links":[]}}]}'

    async def fake_invoke(**kwargs):
        raise LlmJsonParseError(json.JSONDecodeError("Expecting ',' delimiter", invalid_json, 70), invalid_json)

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    target = DeckSlideBrief(index=1, title="坏 JSON", purpose="说明路径")
    outline_item = PptOutlineItem(id="page-1", page_no=1, theme=target.title, purpose=target.purpose)

    with pytest.raises(PptPlanningInvalidResponse) as exc_info:
        asyncio.run(regenerate_deck_brief_slide(DeckBriefSlideRequest(
            area_id="area-1",
            outline=[outline_item],
            slides=[],
            target=target,
            outline_item=outline_item,
            narrative_plan=DeckNarrativePlanResponse(
                storyline="问题到证据",
                slide_roles=[DeckNarrativeSlideRole(page_no=1, role="策略", job="说明路径")],
            ),
            revision_note="按已确认目录和叙事方案生成这一页 brief。",
            source_ids=["current:scope"],
        )))

    assert str(exc_info.value) == "ppt_planning_llm_invalid_response"
    assert exc_info.value.detail["page_no"] == 1
    assert exc_info.value.detail["json_error"]["line"] == 1


def test_regenerate_deck_brief_slide_rejects_outline_only_response(monkeypatch, caplog):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "index": 1,
            "title": "封面与汇报主旨",
            "purpose": "确立项目名称、评审对象与核心汇报逻辑。",
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    target = DeckSlideBrief(index=1, title="封面与汇报主旨", purpose="确立项目名称、评审对象与核心汇报逻辑。")
    outline_item = PptOutlineItem(id="page-1", page_no=1, theme=target.title, purpose=target.purpose)

    with pytest.raises(PptPlanningInvalidResponse, match="invalid_deck_brief_slide") as exc_info:
        asyncio.run(regenerate_deck_brief_slide(DeckBriefSlideRequest(
            area_id="area-1",
            outline=[outline_item],
            slides=[target],
            target=target,
            outline_item=outline_item,
            narrative_plan=DeckNarrativePlanResponse(
                storyline="问题到证据",
                slide_roles=[DeckNarrativeSlideRole(page_no=1, role="开题", job="建立问题")],
            ),
            revision_note="按已确认目录和叙事方案生成这一页 brief。",
            source_ids=["current:scope"],
        )))

    assert exc_info.value.detail["code"] == "invalid_deck_brief_slide"
    assert exc_info.value.detail["page_no"] == 1
    assert exc_info.value.detail["reason"] == "missing_required_brief_content"
    assert exc_info.value.detail["content_retried"] is True
    assert "key_message" in exc_info.value.detail["missing_fields"]
    assert exc_info.value.detail["payload_bytes"] > 0
    assert any(
        record.message.startswith("PPT directive slide validation failed")
        and isinstance(record.args, dict)
        and record.args.get("page_no") == 1
        and record.args.get("error_kind") == "missing_required_brief_content"
        and record.args.get("content_retried") is True
        for record in caplog.records
    )


def test_regenerate_deck_brief_slide_retries_incomplete_content_with_page_context(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)
    calls = []

    async def fake_invoke(**kwargs):
        calls.append(kwargs["user_payload"])
        if len(calls) == 1:
            return {
                "index": 2,
                "title": "证据页",
                "purpose": "说明判断",
            }
        return {
            "index": 2,
            "title": "证据页",
            "purpose": "说明判断",
            "key_message": "核心空间证据支持该判断。",
            "visual_plan": "使用指标卡和空间证据说明。",
            "required_sources": ["current:scope"],
            "metric_claims": [],
            "metric_gaps": [{"text": "缺少可复核指标"}],
            "visual_specs": [{"visual_type": "metric_card", "title": "证据指标卡", "intent": "提示证据缺口", "status": "missing_data", "source_ids": ["current:scope"], "data": {}}],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    outline = [
        PptOutlineItem(id="page-1", page_no=1, theme="开场", purpose="建立问题"),
        PptOutlineItem(id="page-2", page_no=2, theme="证据页", purpose="说明判断"),
    ]
    previous = DeckSlideBrief(
        index=1,
        title="开场",
        purpose="建立问题",
        key_message="说明为什么要更新。",
        visual_plan="封面图",
        required_sources=["current:scope"],
    )
    target = DeckSlideBrief(index=2, title="证据页", purpose="说明判断")

    slide = asyncio.run(regenerate_deck_brief_slide(DeckBriefSlideRequest(
        area_id="area-1",
        context_id="ctx-1",
        page_no=2,
        outline=outline,
        slides=[previous],
        target=target,
        outline_item=outline[1],
        narrative_plan=DeckNarrativePlanResponse(
            storyline="问题到证据",
            slide_roles=[
                DeckNarrativeSlideRole(page_no=1, role="开题", job="建立问题"),
                DeckNarrativeSlideRole(page_no=2, role="证据", job="说明判断", visual_family="map_metric_card"),
            ],
        ),
        previous_slide_summary={"index": 1, "title": "开场", "key_message": "说明为什么要更新。"},
        revision_note="按已确认目录和叙事方案生成这一页 brief。",
        source_ids=["current:scope"],
    )))

    assert slide.index == 2
    assert slide.key_message == "核心空间证据支持该判断。"
    assert len(calls) == 2
    assert "slides" not in calls[0]
    assert calls[0]["brief_generation_context"]["context_id"] == "ctx-1"
    assert calls[0]["brief_generation_context"]["page_context_packet"]["page_no"] == 2
    assert calls[1]["retry_instruction"].startswith("上一轮 JSON 合法但缺少逐页 brief 必要内容")


def test_ppt_metric_context_extracts_metrics_and_filters_unknown_claims():
    ready_metric = {
        "metric_id": "analysis:h3:avg_density_poi_per_km2",
        "domain": "h3",
        "label": "平均 POI 密度",
        "value": 18.2,
        "unit": "个/km²",
        "scope": "当前分析范围",
        "source_id": "current:analysis:poi_h3",
        "source_ids": ["current:dataset:h3", "current:analysis:poi_h3"],
        "source_path": "h3AnalysisSummary.avg_density_poi_per_km2",
        "calculation_method": "平均 POI 密度来自 POI H3 空间分析汇总。",
        "status": "ready",
        "description": "平均 POI 密度 18.2 个/km²",
    }
    gap_metric = {
        "metric_id": "analysis:h3:lq",
        "domain": "h3",
        "label": "区位商 LQ",
        "value": None,
        "unit": "",
        "scope": "当前分析范围",
        "source_id": "current:analysis:poi_h3",
        "source_ids": ["current:analysis:poi_h3"],
        "source_path": "h3AnalysisGridFeatures",
        "calculation_method": "",
        "status": "missing",
        "description": "当前 H3 汇总未提供 LQ 结果。",
    }
    metric_context = build_metric_context(
        sources=[
            {
                "id": "current:analysis:poi_h3",
                "type": "sheet",
                "title": "POI / H3 空间结构分析",
                "status": "ready",
                "selected": True,
                "meta": {
                    "sourceKind": "system",
                    "aiPayload": _ai_payload(
                        metrics=[ready_metric],
                        metric_gaps=[gap_metric],
                    ),
                },
            },
        ],
        source_ids=["current:analysis:poi_h3"],
        current={},
    )
    metrics = metric_context["metrics"]
    metric_ids = [item["metric_id"] for item in metrics]
    assert any(item["domain"] == "h3" and item["label"] == "平均 POI 密度" for item in metrics)
    assert not any(item["metric_id"] == "analysis:h3:lq" for item in metrics)
    assert metric_context["missing_metric_count"] == 1

    valid_id = metric_ids[0]
    assets = validate_visual_assets({
        "metric_claims": [
            {"metric_id": valid_id, "value": metrics[0]["value"], "text": "有效声明"},
            {"metric_id": "analysis:h3:lq", "value": 2.5, "text": "缺失声明"},
            {"metric_id": "missing", "value": 999, "text": "无效声明"},
        ],
        "visual_specs": [
            {
                "title": "有效图表",
                "visual_type": "figure",
                "status": "renderable",
                "data": {
                    "columns": [{"key": "label"}, {"key": "value"}],
                    "rows": [{"label": "A", "value": 999999}],
                },
                "source_metric_ids": [valid_id, "analysis:h3:lq", "missing"],
            }
        ],
    }, metric_context)
    assert len(assets["metric_claims"]) == 1
    assert assets["visual_specs"][0]["source_metric_ids"] == [valid_id]
    assert assets["visual_specs"][0]["data"]["rows"][0]["value"] == metrics[0]["value"]


def test_visual_assets_resolve_metric_ids_from_semantic_titles():
    metrics = [
        {
            "metric_id": "analysis:population:total_population",
            "domain": "population",
            "label": "总人口",
            "value": 12000,
            "unit": "人",
            "source_id": "current:analysis:population",
            "source_ids": ["current:analysis:population"],
            "source_path": "populationOverview.summary.total_population",
            "status": "ready",
            "description": "总人口 12000 人",
        },
        {
            "metric_id": "analysis:population:population_density",
            "domain": "population",
            "label": "人口密度",
            "value": 8000,
            "unit": "人/km²",
            "source_id": "current:analysis:population",
            "source_ids": ["current:analysis:population"],
            "source_path": "populationLayer.summary.average_density_per_km2",
            "status": "ready",
            "description": "人口密度 8000 人/km²",
        },
        {
            "metric_id": "analysis:population:age_structure",
            "domain": "population",
            "label": "年龄结构",
            "value": 35,
            "unit": "%",
            "source_id": "current:analysis:population",
            "source_ids": ["current:analysis:population"],
            "source_path": "populationOverview.age_distribution",
            "status": "ready",
            "description": "主导年龄段占比 35%",
        },
    ]
    metric_context = {"metrics": metrics}

    assets = validate_visual_assets({
        "visual_specs": [
            {
                "visual_type": "metric_card",
                "title": "研究范围总人口",
                "intent": "展示消费基本盘规模",
                "source_ids": ["current:analysis:population"],
                "data": {},
            },
            {
                "visual_type": "metric_card",
                "title": "人口密度",
                "intent": "展示空间居住性与活动密集度",
                "source_ids": ["current:analysis:population"],
                "data": {},
            },
            {
                "visual_type": "metric_card",
                "title": "主导年龄段占比",
                "intent": "展示核心消费群体画像",
                "source_ids": ["current:analysis:population"],
                "data": {},
            },
        ],
    }, metric_context)

    assert len(assets["visual_specs"]) == 1
    visual = assets["visual_specs"][0]
    assert visual["status"] == "needs_existing_asset"
    assert visual["visual_type"] == "existing_asset"
    assert visual["data"]["composition"] == "map_snapshot_request"
    assert visual["data"]["map_request"]["composition"] == "population"
    assert visual["source_metric_ids"] == [
        "analysis:population:total_population",
        "analysis:population:population_density",
        "analysis:population:age_structure",
    ]
    assert visual["data"]["metric_overlays"][2]["value"] == 35


def test_visual_assets_semantic_resolver_covers_h3_road_and_nightlight():
    metrics = [
        {
            "metric_id": "analysis:h3:grid_count",
            "domain": "h3",
            "label": "网格数量",
            "value": 42,
            "unit": "个",
            "source_id": "current:analysis:poi_h3",
            "source_ids": ["current:dataset:h3", "current:analysis:poi_h3"],
            "source_path": "h3AnalysisSummary.grid_count",
            "status": "ready",
        },
        {
            "metric_id": "analysis:road:node_count",
            "domain": "road",
            "label": "路网节点数",
            "value": 80,
            "unit": "个",
            "source_id": "current:analysis:road",
            "source_ids": ["current:analysis:road"],
            "source_path": "roadSyntaxSummary.node_count",
            "status": "ready",
        },
        {
            "metric_id": "analysis:road:edge_count",
            "domain": "road",
            "label": "路网边数",
            "value": 120,
            "unit": "条",
            "source_id": "current:analysis:road",
            "source_ids": ["current:analysis:road"],
            "source_path": "roadSyntaxSummary.edge_count",
            "status": "ready",
        },
        {
            "metric_id": "analysis:nightlight:max_radiance",
            "domain": "nightlight",
            "label": "夜光峰值",
            "value": 9.8,
            "unit": "",
            "source_id": "current:analysis:nightlight",
            "source_ids": ["current:analysis:nightlight"],
            "source_path": "nightlight.summary.max_radiance",
            "status": "ready",
        },
    ]
    assets = validate_visual_assets({
        "visual_specs": [
            {"visual_type": "metric_card", "title": "H3共享网格数量", "source_ids": ["current:dataset:h3"], "data": {}},
            {"visual_type": "metric_card", "title": "路网节点数量", "source_ids": ["current:analysis:road"], "data": {}},
            {"visual_type": "metric_card", "title": "路网边数量", "source_ids": ["current:analysis:road"], "data": {}},
            {"visual_type": "metric_card", "title": "夜光峰值", "source_ids": ["current:analysis:nightlight"], "data": {}},
        ],
    }, {"metrics": metrics})

    assert [item["source_metric_ids"] for item in assets["visual_specs"]] == [
        ["analysis:h3:grid_count"],
        ["analysis:road:node_count", "analysis:road:edge_count"],
        ["analysis:nightlight:max_radiance"],
    ]
    assert [item["data"]["composition"] for item in assets["visual_specs"]] == [
        "map_snapshot_request",
        "map_snapshot_request",
        "map_snapshot_request",
    ]
    assert [item["data"]["map_request"]["composition"] for item in assets["visual_specs"]] == ["h3", "road", "nightlight"]


def test_visual_assets_keep_missing_data_when_semantic_metric_is_not_ready_or_wrong_source():
    metrics = [
        {
            "metric_id": "analysis:population:total_population",
            "domain": "population",
            "label": "总人口",
            "value": 12000,
            "unit": "人",
            "source_id": "current:analysis:population",
            "source_ids": ["current:analysis:population"],
            "source_path": "populationOverview.summary.total_population",
            "status": "ready",
        },
        {
            "metric_id": "analysis:road:node_count",
            "domain": "road",
            "label": "路网节点数",
            "value": 80,
            "unit": "个",
            "source_id": "current:analysis:road",
            "source_ids": ["current:analysis:road"],
            "source_path": "roadSyntaxSummary.node_count",
            "status": "missing",
        },
    ]
    assets = validate_visual_assets({
        "visual_specs": [
            {"visual_type": "metric_card", "title": "研究范围总人口", "source_ids": ["current:analysis:road"], "data": {}},
            {"visual_type": "metric_card", "title": "路网节点数量", "source_ids": ["current:analysis:road"], "data": {}},
        ],
    }, {"metrics": metrics})

    assert [item["status"] for item in assets["visual_specs"]] == ["missing_data", "missing_data"]
    assert all(item["source_metric_ids"] == [] for item in assets["visual_specs"])


def test_visual_assets_semantic_resolver_requires_visual_source_ids():
    assets = validate_visual_assets({
        "visual_specs": [
            {"visual_type": "metric_card", "title": "研究范围总人口", "data": {}},
        ],
    }, {"metrics": [{
        "metric_id": "analysis:population:total_population",
        "domain": "population",
        "label": "总人口",
        "value": 12000,
        "unit": "人",
        "source_id": "current:analysis:population",
        "source_ids": ["current:analysis:population"],
        "source_path": "populationOverview.summary.total_population",
        "status": "ready",
    }]})

    assert assets["visual_specs"][0]["status"] == "missing_data"
    assert assets["visual_specs"][0]["source_metric_ids"] == []


def test_visual_assets_reuse_existing_spatial_snapshot_for_map_like_metric_visual():
    assets = validate_visual_assets({
        "visual_specs": [
            {
                "visual_id": "population-density",
                "visual_type": "metric_card",
                "title": "人口密度",
                "intent": "复用地图展示空间居住性与活动密集度",
                "source_ids": ["current:analysis:population"],
                "data": {},
            },
        ],
    }, {"metrics": [{
        "metric_id": "analysis:population:population_density",
        "domain": "population",
        "label": "人口密度",
        "value": 8000,
        "unit": "人/km²",
        "source_id": "current:analysis:population",
        "source_ids": ["current:analysis:population"],
        "source_path": "populationLayer.summary.average_density_per_km2",
        "status": "ready",
    }]}, [{
        "asset_id": "population-map-1",
        "asset_kind": "population_map",
        "source": "population_map",
        "title": "人口分析图层",
        "data_url": "data:image/png;base64,population",
        "status": "ready",
    }])

    visual = assets["visual_specs"][0]
    assert visual["visual_type"] == "existing_asset"
    assert visual["status"] == "renderable"
    assert visual["asset_id"] == "population-map-1"
    assert visual["asset"]["data_url"] == "data:image/png;base64,population"


def test_generate_visual_artifacts_for_slide_returns_existing_asset_image():
    from modules.ppt_planning.service import generate_visual_artifacts_for_slide

    response = generate_visual_artifacts_for_slide(PptVisualArtifactRequest(
        slide_index=1,
        visual_specs=[
            {
                "visual_id": "population-density",
                "visual_type": "metric_card",
                "title": "人口密度",
                "intent": "复用地图展示空间居住性与活动密集度",
                "source_ids": ["current:analysis:population"],
                "data": {},
            },
        ],
        metric_context={
            "metrics": [{
                "metric_id": "analysis:population:population_density",
                "domain": "population",
                "label": "人口密度",
                "value": 8000,
                "unit": "人/km²",
                "source_id": "current:analysis:population",
                "source_ids": ["current:analysis:population"],
                "source_path": "populationLayer.summary.average_density_per_km2",
                "status": "ready",
            }],
        },
        existing_assets=[{
            "asset_id": "population-map-1",
            "asset_kind": "population_map",
            "source": "population_map",
            "title": "人口分析图层",
            "data_url": "data:image/png;base64,population",
            "status": "ready",
        }],
    ))

    assert response.slide_index == 1
    assert len(response.visual_artifacts) == 1
    artifact = response.visual_artifacts[0]
    assert artifact["visual_id"] == "population-density"
    assert artifact["visual_type"] == "existing_asset"
    assert artifact["asset_id"] == "population-map-1"
    assert artifact["url"] == "data:image/png;base64,population"


def test_generate_visual_artifacts_for_slide_renders_diagram_with_orthogonal_links():
    from modules.ppt_planning.metric_context import _diagram_svg

    svg = _diagram_svg({
        "visual_type": "diagram",
        "title": "产业导入与混合运营机制路径",
        "intent": "证明从产业锚定到资金引入再到运营分成的闭环逻辑。",
        "steps": [
            {"title": "主导产业锚定与基金设立"},
            {"title": "硬件改造与产权梳理"},
            {"title": "统一招商与品牌孵化"},
            {"title": "品牌输出与生态拓展"},
        ],
    })

    assert "C " not in svg
    assert svg.index("<path") < svg.index("<rect")
    assert "主导产业锚定" in svg


def test_generate_visual_artifacts_for_slide_binds_frontend_map_snapshot_request_asset():
    from modules.ppt_planning.service import generate_visual_artifacts_for_slide

    map_request = {
        "version": "ppt_map_request_v1",
        "composition": "population",
        "title": "人口密度与客群结构诊断",
        "layers": [
            {"layer_type": "scope_boundary", "source": "current:scope"},
            {"layer_type": "population_grid", "source": "current:analysis:population"},
        ],
    }
    response = generate_visual_artifacts_for_slide(PptVisualArtifactRequest(
        slide_index=3,
        visual_specs=[{
            "visual_id": "visual-population-map",
            "visual_type": "existing_asset",
            "title": "人口密度与客群结构诊断",
            "intent": "用地图位置关系解释同源指标诊断。",
            "status": "needs_existing_asset",
            "source_ids": ["current:analysis:population"],
            "data": {
                "composition": "map_snapshot_request",
                "map_request": map_request,
                "metric_overlays": [{"label": "人口密度", "value": 8671.694, "unit": "人/km²", "metric_id": "analysis:population:population_density"}],
            },
        }],
        metric_context={"metrics": []},
        existing_assets=[{
            "asset_id": "ppt-map-snapshot-population-test",
            "asset_kind": "map_snapshot",
            "source": "frontend_map_snapshot_request",
            "title": "人口密度与客群结构诊断",
            "data_url": "data:image/png;base64,population-map",
            "status": "ready",
            "data": {
                "composition": "map_snapshot",
                "map_request": map_request,
            },
        }],
    ))

    assert response.visual_specs[0]["status"] == "renderable"
    assert response.visual_specs[0]["asset_id"] == "ppt-map-snapshot-population-test"
    assert response.visual_artifacts[0]["url"] == "data:image/png;base64,population-map"


def test_generate_visual_artifacts_for_slide_requests_carrier_package_snapshot_without_asset():
    from modules.ppt_planning.service import generate_visual_artifacts_for_slide

    response = generate_visual_artifacts_for_slide(PptVisualArtifactRequest(
        slide_index=2,
        visual_specs=[{
            "visual_id": "visual-carrier-map",
            "visual_type": "existing_asset",
            "title": "核心空间载体分布图",
            "intent": "展示 POI、路网、人口和夜光共同识别出的空间载体。",
            "status": "needs_existing_asset",
            "source_ids": ["package:poi-road-carriers:test"],
            "data": {},
        }],
        metric_context={"metrics": []},
        existing_assets=[],
    ))

    visual = response.visual_specs[0]
    assert visual["status"] == "needs_existing_asset"
    assert visual["visual_type"] == "existing_asset"
    assert visual["data"]["composition"] == "carrier_snapshot_request"
    assert visual["data"]["package_source_id"] == "package:poi-road-carriers:test"
    assert visual["data"]["carrier_snapshot_request"]["package_source_id"] == "package:poi-road-carriers:test"
    assert visual["data"]["carrier_snapshot_request"]["extent_mode"] == "all"


def test_generate_visual_artifacts_for_slide_binds_frontend_carrier_snapshot_asset():
    from modules.ppt_planning.service import generate_visual_artifacts_for_slide

    response = generate_visual_artifacts_for_slide(PptVisualArtifactRequest(
        slide_index=2,
        visual_specs=[{
            "visual_id": "visual-carrier-map",
            "visual_type": "existing_asset",
            "title": "核心空间载体分布图",
            "intent": "展示 POI、路网、人口和夜光共同识别出的空间载体。",
            "status": "needs_existing_asset",
            "source_ids": ["package:poi-road-carriers:test"],
            "data": {
                "composition": "carrier_snapshot_request",
                "package_source_id": "package:poi-road-carriers:test",
                "carrier_snapshot_request": {
                    "version": "ppt_carrier_snapshot_request_v1",
                    "composition": "carrier_snapshot",
                    "package_source_id": "package:poi-road-carriers:test",
                },
            },
        }],
        metric_context={"metrics": []},
        existing_assets=[{
            "asset_id": "ppt-carrier-snapshot-test",
            "asset_kind": "map_snapshot",
            "source": "frontend_carrier_package_snapshot",
            "title": "核心空间载体分布图",
            "data_url": "data:image/svg+xml;base64,carrier",
            "status": "ready",
            "data": {
                "composition": "carrier_snapshot",
                "package_source_id": "package:poi-road-carriers:test",
            },
        }],
    ))

    visual = response.visual_specs[0]
    assert visual["status"] == "renderable"
    assert visual["asset_id"] == "ppt-carrier-snapshot-test"
    assert response.visual_artifacts[0]["url"] == "data:image/svg+xml;base64,carrier"
    assert response.visual_artifacts[0]["data"]["package_source_id"] == "package:poi-road-carriers:test"


def test_generate_visual_artifacts_for_slide_drops_stale_map_capture_error():
    from modules.ppt_planning.service import generate_visual_artifacts_for_slide

    map_request = {
        "version": "ppt_map_request_v1",
        "composition": "h3",
        "title": "POI-H3空间结构与混合度诊断",
        "layers": [
            {"layer_type": "h3_grid", "source": "current:analysis:poi_h3"},
        ],
    }
    response = generate_visual_artifacts_for_slide(PptVisualArtifactRequest(
        slide_index=1,
        visual_specs=[{
            "visual_id": "visual-h3-map",
            "visual_type": "existing_asset",
            "title": "POI-H3空间结构与混合度诊断",
            "intent": "用地图位置关系解释同源指标诊断。",
            "status": "needs_existing_asset",
            "source_ids": ["current:analysis:poi_h3"],
            "data": {
                "composition": "map_snapshot_request",
                "capture_error": {"code": "ppt_map_snapshot_capture_failed", "message": "旧错误"},
                "captureError": {"code": "legacy_error"},
                "map_request": map_request,
            },
        }],
        metric_context={"metrics": []},
        existing_assets=[],
    ))

    visual = response.visual_specs[0]
    assert visual["status"] == "needs_existing_asset"
    assert visual["data"]["composition"] == "map_snapshot_request"
    assert visual["data"]["map_request"]["composition"] == "h3"
    assert "capture_error" not in visual["data"]
    assert "captureError" not in visual["data"]


def test_visual_assets_consolidate_spatial_metrics_into_map_overlay():
    metrics = [
        {
            "metric_id": "analysis:nightlight:max_radiance",
            "domain": "nightlight",
            "label": "夜光峰值",
            "value": 52.006,
            "unit": "",
            "source_id": "current:analysis:nightlight",
            "source_ids": ["current:analysis:nightlight"],
            "status": "ready",
        },
        {
            "metric_id": "analysis:nightlight:core_hotspot_count",
            "domain": "nightlight",
            "label": "核心热点数",
            "value": 106,
            "unit": "个",
            "source_id": "current:analysis:nightlight",
            "source_ids": ["current:analysis:nightlight"],
            "status": "ready",
        },
        {
            "metric_id": "analysis:nightlight:gradient_decay",
            "domain": "nightlight",
            "label": "峰边比",
            "value": 2.981,
            "unit": "",
            "source_id": "current:analysis:nightlight",
            "source_ids": ["current:analysis:nightlight"],
            "status": "ready",
        },
    ]
    assets = validate_visual_assets({
        "visual_specs": [
            {"visual_type": "metric_card", "title": "夜光峰值", "source_ids": ["current:analysis:nightlight"], "data": {}},
            {"visual_type": "table", "title": "核心热点数", "source_ids": ["current:analysis:nightlight"], "data": {}},
            {"visual_type": "figure", "title": "峰边比", "source_ids": ["current:analysis:nightlight"], "data": {}},
        ],
    }, {"metrics": metrics}, [{
        "asset_id": "nightlight-map-1",
        "asset_kind": "nightlight_map",
        "source": "nightlight_map",
        "title": "夜光分析图层",
        "data_url": "data:image/png;base64,nightlight",
        "status": "ready",
    }])

    assert len(assets["visual_specs"]) == 1
    visual = assets["visual_specs"][0]
    assert visual["visual_type"] == "existing_asset"
    assert visual["asset_id"] == "nightlight-map-1"
    assert visual["title"] == "夜间活力分布与热点诊断"
    assert visual["source_metric_ids"] == [
        "analysis:nightlight:max_radiance",
        "analysis:nightlight:core_hotspot_count",
        "analysis:nightlight:gradient_decay",
    ]
    assert visual["data"]["composition"] == "map_with_metric_overlays"
    assert [item["label"] for item in visual["data"]["metric_overlays"]] == ["夜光峰值", "核心热点数", "峰边比"]


def test_visual_assets_consolidate_spatial_metrics_into_map_request_without_asset():
    metrics = [
        {
            "metric_id": "analysis:road:node_count",
            "domain": "road",
            "label": "路网节点数",
            "value": 210,
            "unit": "个",
            "source_id": "current:analysis:road",
            "source_ids": ["current:analysis:road"],
            "status": "ready",
        },
        {
            "metric_id": "analysis:road:edge_count",
            "domain": "road",
            "label": "路网边数",
            "value": 320,
            "unit": "条",
            "source_id": "current:analysis:road",
            "source_ids": ["current:analysis:road"],
            "status": "ready",
        },
    ]
    assets = validate_visual_assets({
        "visual_specs": [
            {"visual_type": "metric_card", "title": "路网节点数量", "source_ids": ["current:analysis:road"], "data": {}},
            {"visual_type": "metric_card", "title": "路网边数量", "source_ids": ["current:analysis:road"], "data": {}},
        ],
    }, {"metrics": metrics})

    assert len(assets["visual_specs"]) == 1
    visual = assets["visual_specs"][0]
    assert visual["visual_type"] == "existing_asset"
    assert visual["status"] == "needs_existing_asset"
    assert visual["title"] == "路网可达性与句法结构诊断"
    assert visual["data"]["composition"] == "map_snapshot_request"
    assert visual["data"]["map_request"]["composition"] == "road"
    assert [layer["layer_type"] for layer in visual["data"]["map_request"]["layers"]] == ["scope_boundary", "road_syntax"]
    assert [item["metric_id"] for item in visual["data"]["metric_overlays"]] == [
        "analysis:road:node_count",
        "analysis:road:edge_count",
    ]


def test_visual_assets_create_scope_overview_map_request_without_asset():
    assets = validate_visual_assets({
        "visual_specs": [
            {
                "visual_type": "existing_asset",
                "title": "空间边界与基底概貌",
                "intent": "明确空间分析边界与现状土地利用/建筑基底概貌。",
                "source_ids": ["current:scope"],
                "data": {},
            },
        ],
    }, {"metrics": []})

    visual = assets["visual_specs"][0]
    assert visual["visual_type"] == "existing_asset"
    assert visual["status"] == "needs_existing_asset"
    assert visual["data"]["composition"] == "map_snapshot_request"
    assert visual["data"]["map_request"]["composition"] == "overview"
    assert [layer["layer_type"] for layer in visual["data"]["map_request"]["layers"]] == ["scope_boundary"]


def test_visual_assets_spatial_consolidation_keeps_non_numeric_visuals():
    metrics = [{
        "metric_id": "analysis:population:total_population",
        "domain": "population",
        "label": "总人口",
        "value": 12000,
        "unit": "人",
        "source_id": "current:analysis:population",
        "source_ids": ["current:analysis:population"],
        "status": "ready",
    }]
    assets = validate_visual_assets({
        "visual_specs": [
            {
                "visual_type": "matrix",
                "title": "诊断矩阵",
                "source_ids": ["current:analysis:population"],
                "data": {
                    "rows": [{"id": "r1", "label": "承载高"}, {"id": "r2", "label": "承载低"}],
                    "columns": [{"id": "c1", "label": "活力高"}, {"id": "c2", "label": "活力低"}],
                    "cells": [{"row": "r1", "column": "c1", "label": "优先巩固"}],
                },
            },
            {"visual_type": "metric_card", "title": "研究范围总人口", "source_ids": ["current:analysis:population"], "data": {}},
        ],
    }, {"metrics": metrics})

    assert [item["visual_type"] for item in assets["visual_specs"]] == ["matrix", "existing_asset"]
    assert assets["visual_specs"][0]["title"] == "诊断矩阵"
    assert assets["visual_specs"][1]["data"]["composition"] == "map_snapshot_request"
    assert assets["visual_specs"][1]["status"] == "needs_existing_asset"


def test_visual_assets_fill_rows_and_columns_for_explicit_metric_ids():
    metric_id = "analysis:population:total_population"
    assets = validate_visual_assets({
        "visual_specs": [
            {
                "visual_type": "metric_card",
                "title": "研究范围总人口",
                "source_ids": ["current:analysis:population"],
                "source_metric_ids": [metric_id],
                "data": {},
            },
        ],
    }, {"metrics": [{
        "metric_id": metric_id,
        "domain": "population",
        "label": "总人口",
        "value": 12000,
        "unit": "人",
        "source_id": "current:analysis:population",
        "source_ids": ["current:analysis:population"],
        "source_path": "populationOverview.summary.total_population",
        "status": "ready",
    }]})

    visual = assets["visual_specs"][0]
    assert visual["status"] == "needs_existing_asset"
    assert visual["visual_type"] == "existing_asset"
    assert visual["data"]["metric_overlays"] == [{"label": "总人口", "value": 12000, "unit": "人", "metric_id": metric_id}]
    assert visual["data"]["map_request"]["composition"] == "population"
    assert visual["data"]["columns"] == [
        {"key": "label", "label": "指标"},
        {"key": "value", "label": "数值"},
        {"key": "unit", "label": "单位"},
    ]


def test_ppt_metric_context_adds_selected_carrier_package_metrics():
    package_source = {
        "id": "package:poi-road-carriers:test",
        "type": "package",
        "title": "POI × 路网空间载体资料包",
        "status": "ready",
        "selected": True,
        "meta": {
            "sourceKind": "package",
            "package": {
                "carriers": [
                    {
                        "carrier_id": "corridor_01",
                        "carrier_type": "corridor",
                        "carrier_label": "商业活力廊道",
                        "poi_metrics": {"poi_density_per_km2": 128.5},
                        "nightlight_metrics": {"mean_radiance": 8.6},
                        "road_metrics": {"choice_score": 0.72, "integration_score": 0.81},
                    },
                ],
            },
        },
    }

    metric_context = build_metric_context(
        sources=[package_source],
        source_ids=["package:poi-road-carriers:test"],
        current={},
    )

    metrics = metric_context["metrics"]
    labels = {item["label"]: item for item in metrics}
    assert labels["商业活力廊道 / corridor_01 POI 密度"]["value"] == 128.5
    assert labels["商业活力廊道 / corridor_01 夜光均值"]["value"] == 8.6
    assert labels["商业活力廊道 / corridor_01 choice"]["value"] == 0.72
    assert labels["商业活力廊道 / corridor_01 integration"]["value"] == 0.81
    assert all(item["domain"] == "carrier" for item in metrics)
    assert all(item["status"] == "ready" for item in metrics)
    assert all(item["source_id"] == "package:poi-road-carriers:test" for item in metrics)
    assert all(item["scope"] == "商业活力廊道 / corridor_01" for item in metrics)

    unselected_context = build_metric_context(
        sources=[package_source],
        source_ids=["current:analysis:road"],
        current={},
    )
    assert unselected_context["metrics"] == []


def test_ppt_context_bundle_includes_source_manifest_and_excludes_full_current():
    ready_metric = {
        "metric_id": "analysis:h3:avg_density_poi_per_km2",
        "domain": "h3",
        "label": "平均 POI 密度",
        "value": 18.2,
        "unit": "个/km²",
        "scope": "当前分析范围",
        "source_id": "current:analysis:poi_h3",
        "source_ids": ["current:analysis:poi_h3"],
        "source_path": "h3AnalysisSummary.avg_density_poi_per_km2",
        "calculation_method": "平均 POI 密度来自 POI H3 空间分析汇总。",
        "status": "ready",
    }
    source = {
        "id": "current:analysis:poi_h3",
        "type": "sheet",
        "title": "POI / H3 空间结构分析",
        "status": "ready",
        "selected": True,
        "meta": {
            "sourceKind": "system",
            "aiPayload": _ai_payload(
                metrics=[ready_metric],
                evidence=[{
                    "source_id": "current:analysis:poi_h3",
                    "type": "analysis_summary",
                    "title": "POI / H3 空间结构分析",
                    "text": "平均 POI 密度 18.2 个/km²。",
                }],
                excluded=[{"type": "current.analysis.poi_h3", "reason": "不传完整分析明细。"}],
            ),
        },
    }
    metric_context = build_metric_context(
        sources=[source],
        source_ids=["current:analysis:poi_h3"],
        current={},
    )
    bundle = _build_ppt_context_bundle(
        DeckBriefRequest(
            source_ids=["current:analysis:poi_h3"],
            sources=[source],
        ),
        metric_context=metric_context,
    )
    assert bundle["source_manifest"][0]["source_id"] == "current:analysis:poi_h3"
    assert bundle["source_manifest"][0]["transport_status"] == "included"
    assert bundle["source_manifest"][0]["metric_count"] == 1
    assert bundle["evidence_context"]["item_count"] == 1
    assert "current.datasets.poi.items" in bundle["omitted_payloads"]


def test_ppt_context_bundle_ignores_legacy_ai_payload_aliases():
    source = {
        "id": "current:analysis:poi_h3",
        "type": "sheet",
        "title": "POI / H3 空间结构分析",
        "status": "ready",
        "selected": True,
        "meta": {
            "sourceKind": "system",
            "aiPayload": {
                "version": "ppt_ai_input_block_v1",
                "source_id": "current:analysis:poi_h3",
                "source_kind": "system",
                "included": ["evidence", "metric_gaps", "visual_specs"],
                "evidenceNodes": [{
                    "id": "legacy-node",
                    "sourceId": "current:analysis:poi_h3",
                    "sourceType": "system",
                    "title": "旧证据",
                    "content": "旧 camel evidenceNodes 不应进入 bundle。",
                }],
                "counts": {
                    "metricGaps": 3,
                    "visualSpecs": 2,
                    "evidence": 1,
                },
            },
        },
    }

    bundle = _build_ppt_context_bundle(PptSpecRequest(
        area_id="history-1",
        source_ids=["current:analysis:poi_h3"],
        sources=[source],
    ))

    manifest = bundle["source_manifest"][0]
    assert bundle["evidence_context"]["items"] == []
    assert manifest["metric_gap_count"] == 0
    assert manifest["visual_spec_count"] == 0


def test_ppt_metric_context_filters_current_metrics_by_selected_source_ids():
    h3_metric = {
        "metric_id": "analysis:h3:avg_density_poi_per_km2",
        "domain": "h3",
        "label": "平均 POI 密度",
        "value": 18.2,
        "unit": "个/km²",
        "scope": "当前分析范围",
        "source_id": "current:analysis:poi_h3",
        "source_ids": ["current:dataset:h3", "current:analysis:poi_h3"],
        "source_path": "h3AnalysisSummary.avg_density_poi_per_km2",
        "calculation_method": "平均 POI 密度来自 POI H3 空间分析汇总。",
        "status": "ready",
        "description": "平均 POI 密度 18.2 个/km²",
    }
    road_metric = {
        "metric_id": "analysis:road:avg_integration",
        "domain": "road",
        "label": "平均整合度",
        "value": 1.4,
        "unit": "",
        "scope": "当前分析范围",
        "source_id": "current:analysis:road",
        "source_ids": ["current:analysis:road"],
        "source_path": "roadSyntaxSummary.avg_integration",
        "calculation_method": "平均整合度来自路网句法分析。",
        "status": "ready",
        "description": "平均整合度 1.4",
    }
    gap_metric = {
        "metric_id": "analysis:h3:lq",
        "domain": "h3",
        "label": "区位商 LQ",
        "value": None,
        "unit": "",
        "scope": "当前分析范围",
        "source_id": "current:analysis:poi_h3",
        "source_ids": ["current:dataset:h3", "current:analysis:poi_h3"],
        "source_path": "h3AnalysisGridFeatures",
        "calculation_method": "",
        "status": "missing",
        "description": "当前 H3 汇总未提供 LQ 结果。",
    }
    metric_context = build_metric_context(
        sources=[
            {
                "id": "current:dataset:h3",
                "type": "sheet",
                "title": "H3 / 共享网格",
                "status": "ready",
                "selected": True,
                "meta": {"sourceKind": "system", "aiPayload": _ai_payload("current:dataset:h3", metrics=[h3_metric], metric_gaps=[gap_metric])},
            },
            {
                "id": "current:analysis:road",
                "type": "data",
                "title": "路网与可达性分析",
                "status": "ready",
                "selected": True,
                "meta": {"sourceKind": "system", "aiPayload": _ai_payload("current:analysis:road", metrics=[road_metric])},
            },
        ],
        source_ids=["current:dataset:h3"],
        current={},
    )

    metric_ids = [item["metric_id"] for item in metric_context["metrics"]]
    gap_ids = [item["metric_id"] for item in metric_context["missing_metrics"]]
    assert metric_ids == ["analysis:h3:avg_density_poi_per_km2"]
    assert "analysis:road:avg_integration" not in metric_ids
    assert gap_ids == ["analysis:h3:lq"]


def test_ppt_metric_context_ignores_legacy_visual_and_gap_aliases():
    ready_metric = {
        "metric_id": "analysis:h3:avg_density_poi_per_km2",
        "domain": "h3",
        "label": "平均 POI 密度",
        "value": 18.2,
        "unit": "个/km²",
        "scope": "当前分析范围",
        "sourceId": "current:legacy",
        "sourceIds": ["current:legacy"],
        "source_path": "h3AnalysisSummary.avg_density_poi_per_km2",
        "status": "ready",
    }
    gap_metric = {
        "metric_id": "analysis:h3:lq",
        "domain": "h3",
        "label": "区位商 LQ",
        "sourceId": "current:legacy",
        "sourceIds": ["current:legacy"],
        "status": "missing",
        "description": "旧 camel 缺口不应进入上下文。",
    }
    metric_context = build_metric_context(
        sources=[{
            "id": "current:analysis:poi_h3",
            "type": "sheet",
            "title": "POI / H3 空间结构分析",
            "status": "ready",
            "selected": True,
            "meta": {
                "sourceKind": "system",
                "aiPayload": {
                    "source_id": "current:analysis:poi_h3",
                    "source_kind": "system",
                    "included": ["metrics", "metric_gaps"],
                    "metrics": [ready_metric],
                    "metricGaps": [gap_metric],
                },
            },
        }],
        source_ids=["current:analysis:poi_h3"],
        current={},
    )

    assets = validate_visual_assets({
        "visualSpecs": [{
            "title": "旧图表",
            "visualType": "figure",
            "sourceIds": ["current:legacy"],
            "sourceMetricIds": ["analysis:h3:avg_density_poi_per_km2"],
        }],
    }, metric_context)

    assert metric_context["metrics"] == []
    assert metric_context["missing_metrics"] == []
    assert assets["visual_specs"] == []


def test_classify_ppt_source_groups_returns_normalized_groups(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)
    seen_payload = {}

    async def fake_invoke(**kwargs):
        seen_payload.update(kwargs.get("user_payload") or {})
        return {
            "groups": [
                {
                    "id": "group:vitality",
                    "title": "城市活力证据",
                    "source_ids": ["package:poi", "current:unknown", "package:poi"],
                    "meta": {"reason": "POI 用于解释活力。"},
                }
            ]
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)

    response = asyncio.run(classify_ppt_source_groups(PptSourceGroupClassifyRequest(
        sources=[
            {"id": "package:poi", "type": "data", "title": "POI 基础数据", "status": "ready", "source_kind": "package"},
            {"id": "current:scope", "type": "data", "title": "当前等时圈范围", "status": "ready"},
        ],
    )))

    assert seen_payload["sources"][0]["source_kind"] == "package"
    assert response.groups[0].id == "group:vitality"
    assert response.groups[0].source_ids == ["package:poi"]
    assert response.groups[1].id == "group:uncategorized"
    assert response.groups[1].source_ids == ["current:scope"]


def test_classify_ppt_source_groups_fails_without_llm(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: False)
    with pytest.raises(PptPlanningLlmUnavailable):
        asyncio.run(classify_ppt_source_groups(PptSourceGroupClassifyRequest(
            sources=[
                {"id": "current:dataset:poi", "type": "data", "title": "POI 基础数据", "status": "ready"},
            ],
        )))
