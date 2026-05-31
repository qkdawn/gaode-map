import json

from modules.agent.schemas import AgentTurnOutput, AnalysisSnapshot, AuditResult, ToolResult
from modules.agent.synthesizer import build_analysis_evidence, build_cards, build_synthesis_payload, enrich_answer_output


def _snapshot_with_decision_evidence() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        poi_summary={"total": 12},
        h3={"summary": {"grid_count": 8, "avg_density_poi_per_km2": 6.5}},
        population={"summary": {"total_population": 3200, "male_ratio": 0.49, "female_ratio": 0.51}},
        nightlight={"summary": {"total_radiance": 120.0, "mean_radiance": 3.2, "max_radiance": 9.5, "lit_pixel_ratio": 0.72}},
    )


def test_build_analysis_evidence_converts_metrics_to_decision_evidence():
    evidence = build_analysis_evidence(_snapshot_with_decision_evidence(), {})

    evidence_by_metric = {item.metric: item for item in evidence}

    assert set(evidence_by_metric) >= {"poi_count", "h3_density", "population_profile", "nightlight_activity"}
    assert evidence_by_metric["poi_count"].value == 12
    assert "不能直接等同于客流" in evidence_by_metric["poi_count"].limitation
    assert evidence_by_metric["h3_density"].confidence == "moderate"


def test_build_synthesis_payload_includes_evidence_matrix_and_decision_layers():
    payload = build_synthesis_payload(
        question="总结这个区域",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts={},
        tool_results=[ToolResult(tool_name="read_current_results", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert payload["decision_strength"] == "strong"
    assert payload["decision"]["strength"] == "strong"
    assert payload["decision"]["can_act"] is True
    assert payload["support"]
    assert payload["actions"]
    assert payload["boundary"]
    assert any(item["metric"] == "poi_count" for item in payload["evidence_matrix"])
    assert payload["recommendation_layers"]["can_act_now"]
    assert payload["recommendation_layers"]["do_not_infer"]
    assert any("客流" in item for item in payload["interpretation_limits"])


def test_build_synthesis_payload_uses_compact_tool_result_digest():
    huge_points = [{"id": f"poi-{index}", "lng": 112.98 + index * 0.001, "lat": 28.19} for index in range(300)]
    huge_h3_features = [
        {"id": f"h3-{index}", "properties": {"poi_count": index, "label": f"cell-{index}"}}
        for index in range(300)
    ]

    payload = build_synthesis_payload(
        question="总结这个区域",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts={},
        tool_results=[
            ToolResult(
                tool_name="read_current_results",
                status="success",
                result={"poi_count": 300, "raw_points": huge_points},
                evidence=[{"field": f"poi.{index}", "value": f"evidence-{index}"} for index in range(20)],
                warnings=[f"warning-{index}" for index in range(12)],
                artifacts={
                    "current_pois": huge_points,
                    "current_poi_h3_grid": {"features": huge_h3_features, "summary": {"grid_count": 300}},
                    "current_frontend_analysis": {
                        "poi": {"raw_points": huge_points},
                        "h3": {"features": huge_h3_features},
                    },
                },
            )
        ],
        research_notes=[],
        audit=AuditResult(),
    )

    tool_digest = payload["tool_results"][0]
    encoded = json.dumps(payload, ensure_ascii=False)

    assert "result" not in tool_digest
    assert "evidence" not in tool_digest
    assert "artifacts" not in tool_digest
    assert "poi-299" not in encoded
    assert "h3-299" not in encoded
    assert "evidence-19" not in encoded
    assert tool_digest["result_summary"] == "poi_count=300"
    assert tool_digest["result_shape"] == {"type": "object", "key_count": 2, "keys": ["poi_count", "raw_points"]}
    assert len(tool_digest["evidence_sample"]) == 8
    assert tool_digest["evidence_count"] == 20
    assert tool_digest["warnings"] == [f"warning-{index}" for index in range(8)]
    assert tool_digest["artifact_keys"] == ["current_pois", "current_poi_h3_grid", "current_frontend_analysis"]
    assert tool_digest["artifact_shapes"]["current_pois"] == {"type": "array", "count": 300}
    assert tool_digest["artifact_shapes"]["current_poi_h3_grid"]["keys"] == ["features", "summary"]


def test_build_cards_uses_decision_oriented_titles_and_layers():
    audit = AuditResult(missing_evidence=["路网概览"], issues=["路网证据不足。"])
    cards = build_cards(
        question="这个区域适合补充餐饮吗",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts={},
        tool_results=[ToolResult(tool_name="read_current_results", status="success")],
        research_notes=[],
        audit=audit,
    )

    assert [card.title for card in cards] == ["核心判断", "证据依据", "下一步建议"]
    assert "证据强度" in cards[0].content
    assert any(str(item).startswith("需补充后判断") for item in cards[2].items)
    assert any(str(item).startswith("不建议直接推断") for item in cards[2].items)


def test_build_synthesis_payload_marks_missing_evidence_as_non_actionable():
    audit = AuditResult(missing_evidence=["路网概览", "夜光概览"])
    payload = build_synthesis_payload(
        question="这里值不值得继续做商业选址研究",
        snapshot=AnalysisSnapshot(poi_summary={"total": 6}),
        artifacts={},
        tool_results=[ToolResult(tool_name="read_current_results", status="success")],
        research_notes=[],
        audit=audit,
    )

    assert payload["decision"]["strength"] == "weak"
    assert payload["decision"]["can_act"] is False
    assert any(item["kind"] == "missing" for item in payload["counterpoints"])
    assert any("路网概览" in item["detail"] for item in payload["counterpoints"])


def test_build_synthesis_payload_explains_conflicts_in_output():
    payload = build_synthesis_payload(
        question="为什么这里夜间活动看起来强，但不一定适合直接开店",
        snapshot=AnalysisSnapshot(
            poi_summary={"total": 28},
            population={"summary": {"total_population": 1200, "male_ratio": 0.48, "female_ratio": 0.52}},
            nightlight={"summary": {"total_radiance": 188.0, "mean_radiance": 4.3, "max_radiance": 11.5, "lit_pixel_ratio": 0.81}},
            road={"summary": {"node_count": 26, "edge_count": 33}},
            h3={"summary": {"grid_count": 10, "avg_density_poi_per_km2": 8.1}},
        ),
        artifacts={},
        tool_results=[ToolResult(tool_name="read_current_results", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert any(item["kind"] == "conflict" for item in payload["counterpoints"])
    assert "不过" in payload["decision"]["summary"]
    assert payload["actions"]


def test_build_cards_includes_business_site_advice_target():
    artifacts = {
        "business_site_advice": {
            "place_type": "咖啡厅",
            "types": "050500|050501|050502|050503|050504",
            "keywords": "咖啡厅",
        },
        "current_poi_summary": {"total": 2, "types": "050500|050501|050502|050503|050504", "keywords": "咖啡厅"},
        "current_poi_h3_summary": {"grid_count": 8, "avg_density_poi_per_km2": 6.5},
    }
    cards = build_cards(
        question="我想在这里开一家咖啡店，给我建议",
        snapshot=AnalysisSnapshot(),
        artifacts=artifacts,
        tool_results=[ToolResult(tool_name="run_business_site_advice", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )
    payload = build_synthesis_payload(
        question="我想在这里开一家咖啡店，给我建议",
        snapshot=AnalysisSnapshot(),
        artifacts=artifacts,
        tool_results=[ToolResult(tool_name="run_business_site_advice", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    evidence_card = next(card for card in cards if card.type == "evidence")
    assert "目标业态：咖啡厅" in evidence_card.items
    assert "POI 类型：050500|050501|050502|050503|050504" in evidence_card.items
    assert payload["metrics"]["business_place_type"] == "咖啡厅"
    assert any(item["metric"] == "business_site_advice" for item in payload["evidence_matrix"])


def test_build_cards_prioritize_business_profile_and_hotspots_when_available():
    artifacts = {
        "current_business_profile": {
            "business_profile": "生活消费主导",
            "portrait": "这个区域更像一个生活消费主导的综合商业区。",
            "functional_mix_score": 76.5,
            "summary_text": "生活消费主导",
        },
        "current_commercial_hotspots": {
            "hotspot_mode": "multi_core",
            "core_zone_count": 2,
            "opportunity_zone_count": 3,
            "summary_text": "商业热点结构为 multi_core，核心区 2 个，机会区 3 个。",
        },
        "current_poi_structure_analysis": {
            "summary_text": "POI 结构完整",
        },
    }

    cards = build_cards(
        question="总结这个区域的商业特征",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts=artifacts,
        tool_results=[ToolResult(tool_name="analyze_poi_mix_from_scope", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )
    payload = build_synthesis_payload(
        question="总结这个区域的商业特征",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts=artifacts,
        tool_results=[ToolResult(tool_name="analyze_poi_mix_from_scope", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert "生活消费主导" in cards[0].content
    assert "multi_core" in cards[0].content
    assert payload["business_profile"]["type"] == "生活消费主导"
    assert payload["spatial_structure"]["hotspot_mode"] == "multi_core"


def test_build_synthesis_payload_includes_target_supply_gap_artifact():
    artifacts = {
        "current_target_supply_gap": {
            "place_type": "咖啡厅",
            "supply_gap_level": "high",
            "gap_mode": "spatial_mismatch",
            "summary_text": "咖啡厅供给缺口等级为 high，模式为 spatial_mismatch。",
            "candidate_zones": [{"h3_id": "8928308280fffff", "approx_address": "人民路附近", "display_title": "候选：人民路附近"}],
        }
    }

    payload = build_synthesis_payload(
        question="这里适合补充咖啡吗",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts=artifacts,
        tool_results=[ToolResult(tool_name="analyze_target_supply_gap", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert payload["target_supply_gap"]["place_type"] == "咖啡厅"
    assert payload["target_supply_gap"]["supply_gap_level"] == "high"
    assert payload["target_supply_gap"]["candidate_zones"][0]["approx_address"] == "人民路附近"
    assert any(item["metric"] == "target_supply_gap" for item in payload["evidence_matrix"])


def test_enrich_answer_output_appends_candidate_items_and_h3_panel_payload():
    output = enrich_answer_output(
        output=AgentTurnOutput(cards=[], next_suggestions=[]),
        question="哪里适合补一家咖啡店",
        snapshot=AnalysisSnapshot(),
        artifacts={
            "current_target_supply_gap": {
                "place_type": "咖啡厅",
                "supply_gap_level": "high",
                "gap_mode": "spatial_mismatch",
                "candidate_zones": [
                    {
                        "h3_id": "8928308280fffff",
                        "approx_address": "人民路附近",
                        "display_title": "候选：人民路附近",
                        "reason_summary": "缺口分 0.42，需求分位 85%",
                        "gap_score": 0.42,
                        "center_point": {"lng": 112.98, "lat": 28.19},
                    }
                ],
            },
            "current_poi_h3": {
                "grid": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"h3_id": "8928308280fffff"}}], "count": 1},
                "summary": {"grid_count": 1},
                "charts": {"density_hist": []},
            },
        },
    )

    recommendation = next(card for card in output.cards if card.type == "recommendation")
    assert isinstance(recommendation.items[0], dict)
    assert recommendation.items[0]["type"] == "h3_candidate"
    assert output.panel_payloads["h3_result"]["summary"]["grid_count"] == 1


def test_build_synthesis_payload_ignores_empty_analysis_placeholders_and_falls_back_to_summary():
    artifacts = {
        "current_poi_h3_summary": {"grid_count": 8, "avg_density_poi_per_km2": 6.5},
        "current_h3_structure_analysis": {
            "distribution_pattern": "weak_signal",
            "summary_text": "当前缺少可直接利用的 H3 结构化诊断结果。",
            "data_status": "empty",
            "evidence_ready": False,
        },
    }

    payload = build_synthesis_payload(
        question="总结这个区域的商业特征",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts=artifacts,
        tool_results=[ToolResult(tool_name="compute_h3_metrics_from_scope_and_pois", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert payload["metrics"]["h3_structure_summary"] is None
    assert any(item["metric"] == "h3_density" for item in payload["evidence_matrix"])
