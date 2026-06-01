import json

from modules.agent.schemas import AgentTurnOutput, AnalysisSnapshot, AuditResult, ToolResult
from modules.agent.synthesizer import (
    build_analysis_evidence,
    build_answer_evidence_payload,
    build_answer_fallback,
    enrich_answer_output,
)


def _snapshot_with_decision_evidence() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        poi_summary={"total": 12},
        h3={"summary": {"grid_count": 8, "avg_density_poi_per_km2": 6.5}},
        population={"summary": {"total_population": 3200, "male_ratio": 0.49, "female_ratio": 0.51}},
        nightlight={"summary": {"total_radiance": 120.0, "mean_radiance": 3.2, "max_radiance": 9.5, "lit_pixel_ratio": 0.72}},
    )


def test_build_analysis_evidence_converts_metrics_to_evidence_items():
    evidence = build_analysis_evidence(_snapshot_with_decision_evidence(), {})

    evidence_by_metric = {item.metric: item for item in evidence}

    assert set(evidence_by_metric) >= {"poi_count", "h3_density", "population_profile", "nightlight_activity"}
    assert evidence_by_metric["poi_count"].value == 12
    assert "不能直接等同于客流" in evidence_by_metric["poi_count"].limitation
    assert evidence_by_metric["h3_density"].confidence == "moderate"


def test_build_answer_evidence_payload_includes_key_evidence_and_limits():
    payload = build_answer_evidence_payload(
        question="总结这个区域",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts={},
        tool_results=[ToolResult(tool_name="read_current_results", status="success")],
        research_notes=["已复用当前快照"],
        audit=AuditResult(),
    )

    assert payload["tool_chain"] == ["read_current_results"]
    assert payload["key_evidence"]
    assert any(item["metric"] == "poi_count" for item in payload["key_evidence"])
    assert any("客流" in item for item in payload["interpretation_limits"])
    assert payload["business_profile"]["portrait"] in {"poi_mix_unavailable", ""}
    assert payload["spatial_structure"]["hotspot_mode"] is None
    assert payload["research_notes"] == ["已复用当前快照"]
    assert "direct_answer_seed" not in payload
    assert "business_profile_summary" in payload
    assert "spatial_structure_summary" in payload
    assert "population_vitality_summary" in payload
    assert payload["evidence_highlights"]
    assert payload["spatial_narrative_guidance"]["structure_first"] is True
    assert "内圈/外圈" in payload["spatial_narrative_guidance"]["relationship_lenses"]
    assert "先说片区矛盾或机会" in payload["spatial_narrative_guidance"]["action_lenses"]
    assert "文创游逛停留" in payload["spatial_narrative_guidance"]["scenario_lenses"]
    assert "不要逐项翻译指标面板" in payload["spatial_narrative_guidance"]["anti_patterns"]
    assert "不要把行动建议写成工具流程" in payload["spatial_narrative_guidance"]["anti_patterns"]
    assert "place_anchors" not in json.dumps(payload["spatial_narrative_guidance"], ensure_ascii=False)
    assert payload["answer_depth_guidance"]["target_depth"] == "full"
    assert "至少 5 个展开段" in payload["answer_depth_guidance"]["suggested_shape"]


def test_build_answer_evidence_payload_keeps_simple_metric_questions_concise():
    payload = build_answer_evidence_payload(
        question="夜光均值是什么意思",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts={},
        tool_results=[ToolResult(tool_name="read_current_results", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert payload["answer_depth_guidance"]["target_depth"] == "concise"
    assert "不扩展成报告" in payload["answer_depth_guidance"]["reason"]


def test_build_answer_evidence_payload_uses_compact_tool_result_digest():
    huge_points = [{"id": f"poi-{index}", "lng": 112.98 + index * 0.001, "lat": 28.19} for index in range(300)]
    huge_h3_features = [
        {"id": f"h3-{index}", "properties": {"poi_count": index, "label": f"cell-{index}"}}
        for index in range(300)
    ]

    payload = build_answer_evidence_payload(
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


def test_build_answer_evidence_payload_tracks_missing_evidence_and_required_labels():
    audit = AuditResult(missing_evidence=["路网概览", "夜光概览"])
    payload = build_answer_evidence_payload(
        question="这里值不值得继续做商业选址研究",
        snapshot=AnalysisSnapshot(poi_summary={"total": 6}),
        artifacts={},
        tool_results=[ToolResult(tool_name="read_current_results", status="success")],
        research_notes=[],
        audit=audit,
    )

    assert payload["missing_evidence"] == ["路网概览", "夜光概览"]
    assert payload["required_evidence"][:2] == ["路网概览", "夜光概览"]


def test_build_answer_evidence_payload_explains_conflicts_and_target_gap():
    artifacts = {
        "current_target_supply_gap": {
            "place_type": "咖啡厅",
            "supply_gap_level": "high",
            "gap_mode": "spatial_mismatch",
            "summary_text": "咖啡厅供给缺口等级为 high，模式为 spatial_mismatch。",
            "candidate_zones": [{"h3_id": "8928308280fffff", "approx_address": "人民路附近", "display_title": "候选：人民路附近"}],
        }
    }
    payload = build_answer_evidence_payload(
        question="为什么这里夜间活动看起来强，但不一定适合直接开店",
        snapshot=AnalysisSnapshot(
            poi_summary={"total": 28},
            population={"summary": {"total_population": 1200, "male_ratio": 0.48, "female_ratio": 0.52}},
            nightlight={"summary": {"total_radiance": 188.0, "mean_radiance": 4.3, "max_radiance": 11.5, "lit_pixel_ratio": 0.81}},
            road={"summary": {"node_count": 26, "edge_count": 33}},
            h3={"summary": {"grid_count": 10, "avg_density_poi_per_km2": 8.1}},
        ),
        artifacts=artifacts,
        tool_results=[ToolResult(tool_name="analyze_target_supply_gap", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert payload["conflicting_evidence"]
    assert payload["target_supply_gap"]["place_type"] == "咖啡厅"
    assert payload["target_supply_gap"]["candidate_zones"][0]["approx_address"] == "人民路附近"


def test_build_answer_evidence_payload_expands_key_evidence_for_summary_questions():
    payload = build_answer_evidence_payload(
        question="总结这个区域的商业特征",
        snapshot=AnalysisSnapshot(
            poi_summary={"total": 28},
            population={"summary": {"total_population": 1200, "male_ratio": 0.48, "female_ratio": 0.52}},
            nightlight={"summary": {"total_radiance": 188.0, "mean_radiance": 4.3, "max_radiance": 11.5, "lit_pixel_ratio": 0.81}},
            road={"summary": {"node_count": 26, "edge_count": 33}},
            h3={"summary": {"grid_count": 10, "avg_density_poi_per_km2": 8.1}},
        ),
        artifacts={
            "current_business_profile": {
                "business_profile": "生活消费主导",
                "portrait": "该区域更偏生活消费导向。",
            },
            "current_commercial_hotspots": {
                "hotspot_mode": "multi_core",
                "core_zone_count": 2,
                "opportunity_zone_count": 3,
                "summary_text": "商业热点呈多核心分布。",
            },
        },
        tool_results=[ToolResult(tool_name="run_area_character_pack", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert 3 <= len(payload["key_evidence"]) <= 5
    assert payload["evidence_highlights"]


def test_build_answer_fallback_only_reports_translation_or_evidence_gap():
    answer = build_answer_fallback(
        question="这里适合补充咖啡吗",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts={
            "current_target_supply_gap": {
                "place_type": "咖啡厅",
                "supply_gap_level": "high",
                "gap_mode": "spatial_mismatch",
                "summary_text": "咖啡厅供给缺口等级为 high，模式为 spatial_mismatch。",
            }
        },
        tool_results=[ToolResult(tool_name="analyze_target_supply_gap", status="success")],
        research_notes=[],
        audit=AuditResult(missing_evidence=["路网概览"]),
    )

    assert "AI 转译暂不可用" in answer
    assert "路网概览" in answer
    assert "咖啡厅" not in answer


def test_build_answer_fallback_does_not_generate_planning_prose():
    answer = build_answer_fallback(
        question="总结这个区域的商业特征",
        snapshot=AnalysisSnapshot(
            poi_summary={"total": 28},
            population={"summary": {"total_population": 91000, "male_ratio": 0.48, "female_ratio": 0.52}},
            nightlight={"summary": {"total_radiance": 188.0, "mean_radiance": 30.97, "max_radiance": 11.5, "lit_pixel_ratio": 0.81}},
            road={"summary": {"node_count": 260, "edge_count": 330}},
            h3={"summary": {"grid_count": 10, "avg_density_poi_per_km2": 8.1}},
        ),
        artifacts={
            "current_business_profile": {
                "business_profile": "生活消费主导",
                "portrait": "生活消费主导的社区级综合商业区。",
            },
            "current_commercial_hotspots": {
                "hotspot_mode": "multi_core",
                "core_zone_count": 10,
                "opportunity_zone_count": 127,
                "summary_text": "空间结构上表现为多核心格局，内部分布多个商业核心区与机会区。",
            },
        },
        tool_results=[ToolResult(tool_name="run_area_character_pack", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    paragraphs = [item for item in answer.split("\n\n") if item.strip()]
    assert len(paragraphs) == 1
    assert "AI 转译暂不可用" in answer
    assert "整体看" not in answer
    assert "多核心格局" not in answer


def test_enrich_answer_output_sets_fallback_answer_and_h3_panel_payload():
    output = enrich_answer_output(
        output=AgentTurnOutput(answer=""),
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

    assert output.answer
    assert output.panel_payloads["h3_result"]["summary"]["grid_count"] == 1


def test_build_answer_evidence_payload_ignores_empty_analysis_placeholders_and_falls_back_to_summary():
    artifacts = {
        "current_poi_h3_summary": {"grid_count": 8, "avg_density_poi_per_km2": 6.5},
        "current_h3_structure_analysis": {
            "distribution_pattern": "weak_signal",
            "summary_text": "当前缺少可直接利用的 H3 结构化诊断结果。",
            "data_status": "empty",
            "evidence_ready": False,
        },
    }

    payload = build_answer_evidence_payload(
        question="总结这个区域的商业特征",
        snapshot=_snapshot_with_decision_evidence(),
        artifacts=artifacts,
        tool_results=[ToolResult(tool_name="compute_h3_metrics_from_scope_and_pois", status="success")],
        research_notes=[],
        audit=AuditResult(),
    )

    assert payload["metrics"]["h3_structure_summary"] is None
    assert any(item["metric"] == "h3_density" for item in payload["key_evidence"])
