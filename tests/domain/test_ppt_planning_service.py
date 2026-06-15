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
    _build_ppt_context_bundle,
    classify_ppt_source_groups,
    generate_deck_brief,
    generate_ppt_spec,
    regenerate_deck_brief_slide,
    regenerate_ppt_outline_section,
)
from modules.ppt_planning.metric_context import build_metric_context, validate_metric_assets


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
    return {
        "version": "ppt_ai_input_block_v1",
        "source_id": source_id,
        "title": title,
        "source_kind": source_kind,
        "included": included,
        "scope": scope,
        "metrics": metrics,
        "metric_gaps": metric_gaps,
        "evidence": evidence,
        "chart_specs": [],
        "excluded": excluded or [{"type": "raw_payload", "reason": "不传原始数据。"}],
        "counts": {
            "scope": 1 if scope else 0,
            "metrics": len(metrics),
            "metric_gaps": len(metric_gaps),
            "evidence": len(evidence),
            "chart_specs": 0,
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
    assert seen_payload["evidence_context"]["items"][0]["type"] == "package_summary"

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
            "source_summary": "已选择 1 个来源，包含联网研究",
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
    assert seen_payload["evidence_context"]["items"][0]["text"] == "政策要求完善公共服务设施。"
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
                "source_summary": "已选择 1 个来源，不包含联网研究",
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
                    "visual_plan": "区域底图与 POI 数量柱状图",
                    "required_sources": ["current:scope"],
                    "speaker_notes": "第一阶段先生成逐页指令，不直接生成 PPTX。",
                    "metric_claims": [
                        {
                            "claim_id": "c1",
                            "metric_id": poi_metric["metric_id"],
                            "text": "POI 共 120 个",
                            "value": 120,
                            "unit": "个",
                        }
                    ],
                    "chart_specs": [
                        {
                            "chart_id": "chart-poi",
                            "title": "POI 数量",
                            "chart_type": "bar",
                            "columns": [{"key": "label", "label": "指标"}, {"key": "value", "label": "数值"}],
                            "rows": [{"label": "POI 总数", "value": 120}],
                            "source_metric_ids": [poi_metric["metric_id"]],
                        }
                    ],
                }
            ],
            "source_summary": "已选择 1 个来源，不包含联网研究",
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
    assert "不直接生成 PPTX" in response.slides[0].speaker_notes
    assert response.slides[0].metric_claims[0]["value"] == 120
    assert response.slides[0].chart_specs[0]["rows"][0]["value"] == 120
    assert response.slides[0].chart_artifacts[0]["url"].endswith(".svg")
    assert seen_directive_payload["metric_context"]["metric_count"] >= 1
    assert "current" not in seen_directive_payload
    assert seen_directive_payload["sources"][0]["id"] == "package:poi:test"
    assert seen_directive_payload["evidence_context"]["item_count"] >= 1
    assert seen_directive_payload["source_manifest"][0]["transport_status"] in {"included", "selected_no_payload"}


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
            "visual_plan": "区位底图 + 夜光峰值指标卡",
            "required_sources": ["current:scope"],
            "speaker_notes": "强调本页不是最终 PPTX。",
            "metric_claims": [
                {"metric_id": nightlight_metric["metric_id"], "value": 9.8, "unit": "", "text": "夜光峰值 9.8"}
            ],
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)
    target = DeckSlideBrief(index=1, title="项目命题", purpose="建立汇报主线")
    outline_item = PptOutlineItem(id="page-1", page_no=1, theme="项目命题", purpose="建立汇报主线")
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
        outline=[outline_item],
        slides=[target],
        target=target,
        outline_item=outline_item,
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
    assert "current" not in seen_payload
    assert response.index == 1
    assert response.title == "项目命题重写"
    assert response.required_sources == ["current:scope"]
    assert response.metric_claims[0]["value"] == 9.8


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
    assets = validate_metric_assets({
        "metric_claims": [
            {"metric_id": valid_id, "value": metrics[0]["value"], "text": "有效声明"},
            {"metric_id": "analysis:h3:lq", "value": 2.5, "text": "缺失声明"},
            {"metric_id": "missing", "value": 999, "text": "无效声明"},
        ],
        "chart_specs": [
            {
                "title": "有效图表",
                "columns": [{"key": "label"}, {"key": "value"}],
                "rows": [{"label": "A", "value": 999999}],
                "source_metric_ids": [valid_id, "analysis:h3:lq", "missing"],
            }
        ],
    }, metric_context)
    assert len(assets["metric_claims"]) == 1
    assert assets["chart_specs"][0]["source_metric_ids"] == [valid_id]
    assert assets["chart_specs"][0]["rows"][0]["value"] == metrics[0]["value"]


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


def test_classify_ppt_source_groups_returns_normalized_groups(monkeypatch):
    monkeypatch.setattr("modules.ppt_planning.service.is_llm_enabled", lambda: True)

    async def fake_invoke(**kwargs):
        return {
            "groups": [
                {
                    "id": "group:vitality",
                    "title": "城市活力证据",
                    "source_ids": ["current:dataset:poi", "current:unknown", "current:dataset:poi"],
                    "meta": {"reason": "POI 用于解释活力。"},
                }
            ]
        }

    monkeypatch.setattr("modules.ppt_planning.service._invoke_json_role", fake_invoke)

    response = asyncio.run(classify_ppt_source_groups(PptSourceGroupClassifyRequest(
        sources=[
            {"id": "current:dataset:poi", "type": "data", "title": "POI 基础数据", "status": "ready"},
            {"id": "current:scope", "type": "data", "title": "当前等时圈范围", "status": "ready"},
        ],
    )))

    assert response.groups[0].id == "group:vitality"
    assert response.groups[0].source_ids == ["current:dataset:poi"]
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
