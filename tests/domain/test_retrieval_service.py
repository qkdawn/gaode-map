import asyncio

from modules.agent.schemas import AnalysisSnapshot
from modules.agent.tools import get_tool_registry
from modules.agent.tool_adapters.retrieval_tools import (
    read_analysis_chunk,
    read_report_chunk,
    search_analysis_context,
    search_report_context,
)
from modules.retrieval.chunkers import build_analysis_chunks, build_report_chunks
from modules.retrieval.service import RetrievalService


def _snapshot() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        poi_summary={"total": 120},
        h3={"summary": {"grid_count": 12, "avg_density_poi_per_km2": 18.6}},
        road={"summary": {"node_count": 3682, "edge_count": 4089}},
        population={"summary": {"total_population": 54326.544, "male_ratio": 0.49, "female_ratio": 0.51}},
        nightlight={"summary": {"total_radiance": 1316.555, "mean_radiance": 3.15, "max_radiance": 9.8, "lit_pixel_ratio": 1.0}},
        frontend_analysis={
            "poi": {"category_stats": {"labels": ["餐饮", "购物"], "values": [1000, 565]}},
            "h3": {
                "derived_stats": {
                    "structureSummary": {
                        "rows": [{"h3_id": "a", "structure_signal": 2.1, "is_structure_signal": True, "density": 18.2, "poi_count": 60}]
                    },
                    "typingSummary": {
                        "rows": [{"h3_id": "a", "type_key": "high_mix", "is_opportunity": True, "density": 18.2}],
                        "opportunityCount": 1,
                        "recommendation": "优先排查高密-高混合网格",
                    },
                    "gapSummary": {
                        "rows": [{"h3_id": "a", "gap_zone_label": "高需求低供给", "gap_score": 0.42, "demand_pct": 0.85}],
                        "opportunityCount": 1,
                        "recommendation": "咖啡优先关注高需求低供给",
                    },
                },
                "target_category": "coffee",
                "target_category_label": "咖啡",
            },
            "population": {
                "age_distribution": [{"age_band_label": "25-34岁", "total": 12000}],
                "layer_summary": {"top_dominant_age_band_label": "25-34岁", "dominant_cell_ratio": 0.37},
            },
            "nightlight": {
                "analysis": {
                    "core_hotspot_count": 4,
                    "hotspot_cell_ratio": 0.33,
                    "economic_activity_summary_text": "基于夜间灯光亮度，等时圈内经济活动强度呈现中等偏上水平。",
                }
            },
            "road": {"regression": {"r2": 0.62}},
        },
    )


def _artifacts():
    return {
        "summary_pack": {
            "headline_judgment": {"summary": "片区活力弱，需要谨慎判断。"},
            "spatial_structure": {"title": "空间结构", "reasoning": "路网可达性一般，核心网格不连续。"},
            "consumption_vitality": {"title": "活力判断", "reasoning": "夜光均值较低，人口覆盖不足，因此报告判断活力偏弱。"},
            "evidence_refs": ["nightlight.mean_radiance", "population.total_population"],
        }
    }


def _map_search_artifacts():
    return {
        "frontend_map_search_context": {
            "place_anchors": {
                "groups": [
                    {
                        "key": "campus_culture",
                        "label": "校园与文教",
                        "items": [
                            {"name": "湖南师范大学", "type": "科教文化", "address": "岳麓区"},
                            {"name": "后湖国际艺术区", "type": "文化", "address": "后湖"},
                        ],
                    },
                    {
                        "key": "commercial_life",
                        "label": "商业与生活服务",
                        "items": [{"name": "后湖小吃街", "type": "餐饮", "address": "后湖"}],
                    },
                ],
                "names": ["湖南师范大学", "后湖国际艺术区", "后湖小吃街"],
            },
            "spatial_anchors": {
                "selected_point": {"name": "后湖", "lng": 112.96, "lat": 28.19},
                "h3": {"feature_count": 2, "top_cells": [{"h3_id": "h3-a", "poi_count": 12}]},
                "road": {"feature_count": 1, "metric_keys": ["choice_score"], "sample_segments": [{"id": "r1", "choice_score": 0.8}]},
                "population": {"cell_count": 1, "top_cells": [{"cell_id": "p1", "total_population": 900}]},
                "nightlight": {"cell_count": 1, "top_cells": [{"cell_id": "n1", "radiance": 42}]},
            },
        }
    }


def test_build_analysis_chunks_from_snapshot():
    chunks = build_analysis_chunks(_snapshot(), {})
    chunk_ids = {chunk.chunk_id for chunk in chunks}

    assert "session:current:analysis:h3.opportunity.top" in chunk_ids
    assert "session:current:analysis:poi.summary" in chunk_ids
    assert "session:current:analysis:population.summary" in chunk_ids
    assert "session:current:analysis:nightlight.summary" in chunk_ids
    assert "session:current:analysis:road.summary" in chunk_ids


def test_build_analysis_chunks_from_frontend_map_search_context():
    chunks = build_analysis_chunks(_snapshot(), _map_search_artifacts())
    chunk_ids = {chunk.chunk_id for chunk in chunks}

    assert "session:current:analysis:poi.place_anchors" in chunk_ids
    assert "session:current:analysis:h3.spatial_anchors" in chunk_ids
    assert "session:current:analysis:road.metric_anchors" in chunk_ids
    assert "session:current:analysis:population.cell_anchors" in chunk_ids
    assert "session:current:analysis:nightlight.cell_anchors" in chunk_ids


def test_search_analysis_context_hits_opportunity_evidence():
    service = RetrievalService(snapshot=_snapshot(), artifacts={})
    hits = service.search_analysis_context(
        query="咖啡店 机会网格 人口 夜光 POI 缺口",
        domains=["h3", "poi", "population", "nightlight"],
        top_k=8,
    )

    assert hits
    assert any(hit.chunk_id == "session:current:analysis:h3.opportunity.top" for hit in hits)


def test_search_analysis_context_hits_frontend_place_anchor_chunk():
    service = RetrievalService(snapshot=_snapshot(), artifacts=_map_search_artifacts())
    hits = service.search_analysis_context(
        query="后湖 湖南师大 商业特征",
        domains=["poi", "h3", "road", "population", "nightlight"],
        top_k=8,
    )

    assert hits
    assert hits[0].chunk_id == "session:current:analysis:poi.place_anchors"


def test_read_analysis_chunk_returns_metrics_and_warnings():
    result = asyncio.run(
        read_analysis_chunk(
            arguments={"chunk_id": "session:current:analysis:nightlight.summary"},
            snapshot=_snapshot(),
            artifacts={},
            question="活力依据是什么",
        )
    )

    assert result.status == "success"
    assert result.result["metrics"]["mean_radiance"] == 3.15
    assert "夜光仅作为活力 proxy" in result.result["warnings"][0]


def test_read_analysis_chunk_returns_frontend_map_anchor_limits():
    result = asyncio.run(
        read_analysis_chunk(
            arguments={"chunk_id": "session:current:analysis:poi.place_anchors"},
            snapshot=_snapshot(),
            artifacts=_map_search_artifacts(),
            question="总结后湖周边商业特征",
        )
    )

    assert result.status == "success"
    assert "湖南师范大学" in result.result["content"]
    assert result.result["source_artifacts"] == ["frontend_map_search_context"]
    assert any("不能扩展成完整地名数据库" in warning for warning in result.result["warnings"])


def test_report_context_search_and_read():
    snapshot = _snapshot()
    artifacts = _artifacts()

    chunks = build_report_chunks(snapshot, artifacts)
    assert any(chunk.chunk_id == "session:current:report:section.consumption_vitality" for chunk in chunks)

    search = asyncio.run(
        search_report_context(
            arguments={"query": "活力弱 夜光 人口 路网 依据", "top_k": 5},
            snapshot=snapshot,
            artifacts=artifacts,
            question="刚才报告里说活力弱依据是什么",
        )
    )
    assert search.status == "success"
    assert search.result["hits"]

    read = asyncio.run(
        read_report_chunk(
            arguments={"chunk_id": "session:current:report:section.consumption_vitality"},
            snapshot=snapshot,
            artifacts=artifacts,
            question="读报告段落",
        )
    )
    assert read.status == "success"
    assert "夜光均值较低" in read.result["content"]


def test_missing_chunk_returns_chunk_not_found():
    result = asyncio.run(
        read_analysis_chunk(
            arguments={"chunk_id": "session:current:analysis:missing"},
            snapshot=_snapshot(),
            artifacts={},
            question="读不存在的 chunk",
        )
    )

    assert result.status == "failed"
    assert result.error == "chunk_not_found"


def test_search_analysis_tool_shape():
    result = asyncio.run(
        search_analysis_context(
            arguments={"query": "咖啡 机会网格", "domains": ["h3"], "top_k": 3},
            snapshot=_snapshot(),
            artifacts={},
            question="哪些网格适合开咖啡店",
        )
    )

    assert result.status == "success"
    assert set(result.result["hits"][0]) == {"chunk_id", "title", "domain", "snippet", "evidence_level", "score"}


def test_retrieval_tools_are_registered_with_expected_contracts():
    registry = get_tool_registry()

    assert registry["search_analysis_context"].spec.readonly is True
    assert registry["search_analysis_context"].spec.input_schema["required"] == ["query"]
    assert registry["read_analysis_chunk"].spec.input_schema["required"] == ["chunk_id"]
    assert registry["search_report_context"].spec.output_schema["properties"]["hits"]["type"] == "array"
    assert registry["read_report_chunk"].spec.output_schema["required"] == [
        "title",
        "content",
        "metrics",
        "source_artifacts",
        "warnings",
    ]


def test_retrieval_tools_are_available_to_main_agent_loop():
    registry = get_tool_registry()
    assert {
        "search_analysis_context",
        "read_analysis_chunk",
        "search_report_context",
        "read_report_chunk",
    }.issubset(set(registry.keys()))
