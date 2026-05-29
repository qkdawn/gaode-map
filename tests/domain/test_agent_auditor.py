from modules.agent.auditor import audit_execution
from modules.agent.context_builder import build_context_bundle
from modules.agent.schemas import AnalysisSnapshot, WorkingMemory


def _snapshot_with_scope(**kwargs) -> AnalysisSnapshot:
    payload = {
        "scope": {
            "polygon": [
                [112.98, 28.19],
                [112.99, 28.19],
                [112.99, 28.20],
                [112.98, 28.20],
                [112.98, 28.19],
            ]
        }
    }
    payload.update(kwargs)
    return AnalysisSnapshot(**payload)


def test_auditor_requires_business_profile_for_commercial_summary():
    snapshot = _snapshot_with_scope(
        poi_summary={"total": 8},
        h3={"summary": {"grid_count": 3, "avg_density_poi_per_km2": 2.1}},
        population={"summary": {"total_population": 1000}},
        nightlight={"summary": {"max_radiance": 4.2}},
        road={"summary": {"node_count": 8, "edge_count": 10}},
    )
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_pois": [{"id": "poi-1"}],
            "current_poi_summary": {"total": 8},
            "current_poi_h3_summary": {"grid_count": 3, "avg_density_poi_per_km2": 2.1},
            "current_population_summary": {"total_population": 1000},
            "current_nightlight_summary": {"max_radiance": 4.2},
            "current_road_summary": {"node_count": 8, "edge_count": 10},
        }
    )

    result = audit_execution(
        question="总结这个区域的商业特征",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=memory,
    )

    assert result.passed is False
    assert "商业画像分析" in result.required_evidence
    assert "商业画像分析" in result.missing_evidence
    assert result.followup_plan == []


def test_auditor_accepts_analysis_artifacts_for_commercial_summary():
    snapshot = _snapshot_with_scope()
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_poi_structure_analysis": {"dominant_categories": ["餐饮"], "summary_text": "POI 结构完整"},
            "current_h3_structure_analysis": {"distribution_pattern": "single_core", "summary_text": "H3 结构完整"},
            "current_population_profile_analysis": {"total_population": 1000, "summary_text": "人口画像完整"},
            "current_nightlight_pattern_analysis": {"total_radiance": 12.3, "summary_text": "夜光画像完整"},
            "current_road_pattern_analysis": {"node_count": 8, "summary_text": "路网画像完整"},
            "current_business_profile": {"business_profile": "生活消费主导", "summary_text": "画像完整"},
        }
    )

    result = audit_execution(
        question="总结这个区域的商业特征",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=memory,
    )

    assert result.passed is True
    assert result.missing_evidence == []
    assert "商业画像分析" in result.required_evidence


def test_auditor_treats_empty_analysis_artifacts_as_missing_evidence():
    snapshot = _snapshot_with_scope()
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_poi_structure_analysis": {"summary_text": "当前缺少可直接利用的 POI 类别结构结果。", "data_status": "empty", "evidence_ready": False},
            "current_h3_structure_analysis": {"distribution_pattern": "weak_signal", "summary_text": "当前缺少可直接利用的 H3 结构化诊断结果。", "data_status": "empty", "evidence_ready": False},
            "current_population_profile_analysis": {"summary_text": "当前缺少可直接利用的人口结构结果。", "data_status": "empty", "evidence_ready": False},
            "current_nightlight_pattern_analysis": {"summary_text": "当前缺少可直接利用的夜光结构结果。", "data_status": "empty", "evidence_ready": False},
            "current_road_pattern_analysis": {"summary_text": "当前缺少可直接利用的路网结构结果。", "data_status": "empty", "evidence_ready": False},
        }
    )

    result = audit_execution(
        question="总结这个区域的商业特征",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=memory,
    )

    assert result.passed is False
    assert "POI H3 密度证据" in result.missing_evidence
    assert "人口概览" in result.missing_evidence
    assert "夜光概览" in result.missing_evidence
    assert "路网概览" in result.missing_evidence


def test_auditor_keeps_poi_raster_and_poi_h3_evidence_separate():
    snapshot = _snapshot_with_scope(
        poi_summary={"total": 8},
        population={"summary": {"total_population": 1000}},
        nightlight={"summary": {"max_radiance": 4.2}},
        road={"summary": {"node_count": 8, "edge_count": 10}},
    )
    raster_only = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_pois": [{"id": "poi-1"}],
            "current_poi_summary": {"total": 8},
            "current_poi_raster_summary": {"grid_count": 6, "assigned_poi_count": 8},
            "current_poi_raster_evidence": {"cell_id_source": "population_nightlight_shared_cell_id"},
            "current_population_summary": {"total_population": 1000},
            "current_nightlight_summary": {"max_radiance": 4.2},
            "current_road_summary": {"node_count": 8, "edge_count": 10},
            "current_business_profile": {"business_profile": "生活消费主导"},
        }
    )

    raster_result = audit_execution(
        question="总结这个区域的商业特征",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=raster_only,
    )

    assert raster_result.passed is False
    assert "POI H3 密度证据" in raster_result.required_evidence
    assert "POI H3 密度证据" in raster_result.missing_evidence

    poi_h3_only = WorkingMemory(
        artifacts={
            **raster_only.artifacts,
            "current_poi_h3_summary": {"grid_count": 3, "avg_density_poi_per_km2": 2.1},
        }
    )

    h3_result = audit_execution(
        question="总结这个区域的商业特征",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=poi_h3_only,
    )

    assert "POI H3 密度证据" not in h3_result.missing_evidence


def test_auditor_population_question_accepts_population_profile_analysis():
    snapshot = _snapshot_with_scope()
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_population_profile_analysis": {"total_population": 1000, "top_age_band": "25-34岁", "summary_text": "人口画像完整"},
        }
    )

    result = audit_execution(
        question="这个区域人口怎么样",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=memory,
    )

    assert result.passed is True
    assert result.required_evidence == ["人口概览"]
    assert result.missing_evidence == []


def test_auditor_hotspot_question_requires_spatial_hotspot_analysis():
    snapshot = _snapshot_with_scope(h3={"summary": {"grid_count": 4, "avg_density_poi_per_km2": 5.6}})
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_poi_h3_summary": {"grid_count": 4, "avg_density_poi_per_km2": 5.6},
            "current_h3_structure_analysis": {"distribution_pattern": "multi_core", "summary_text": "H3 结构完整"},
        }
    )

    result = audit_execution(
        question="这个区域的商业核心集中在哪",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=memory,
    )

    assert result.passed is False
    assert "空间热点分析" in result.required_evidence
    assert "空间热点分析" in result.missing_evidence


def test_auditor_supply_question_accepts_target_supply_gap_analysis():
    snapshot = _snapshot_with_scope()
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_pois": [{"id": "coffee-1"}],
            "current_poi_summary": {"total": 5, "types": "050500|050501|050502|050503|050504", "keywords": "咖啡厅"},
            "current_h3_structure_analysis": {"distribution_pattern": "single_core", "opportunity_count": 2, "summary_text": "H3 结构完整"},
            "current_target_supply_gap": {
                "place_type": "咖啡厅",
                "supply_gap_level": "medium",
                "gap_mode": "spatial_mismatch",
                "candidate_zones": [{"h3_id": "8928308280fffff", "approx_address": "人民路附近"}],
            },
            "current_population_profile_analysis": {"total_population": 1200, "summary_text": "人口画像"},
            "current_nightlight_pattern_analysis": {"total_radiance": 20.0, "summary_text": "夜光画像"},
            "current_road_pattern_analysis": {"node_count": 10, "summary_text": "路网画像"},
        }
    )

    result = audit_execution(
        question="我想在这里开一家咖啡店，给我建议",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=memory,
    )

    assert result.passed is True
    assert "目标业态补位分析" in result.required_evidence
    assert result.missing_evidence == []


def test_auditor_supply_question_requires_candidate_zones_for_delivery():
    snapshot = _snapshot_with_scope()
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_pois": [{"id": "coffee-1"}],
            "current_poi_summary": {"total": 5, "types": "050500|050501|050502|050503|050504", "keywords": "咖啡厅"},
            "current_h3_structure_analysis": {"distribution_pattern": "single_core", "opportunity_count": 2, "summary_text": "H3 结构完整"},
            "current_target_supply_gap": {"place_type": "咖啡厅", "supply_gap_level": "medium", "gap_mode": "spatial_mismatch"},
            "current_population_profile_analysis": {"total_population": 1200, "summary_text": "人口画像"},
            "current_nightlight_pattern_analysis": {"total_radiance": 20.0, "summary_text": "夜光画像"},
            "current_road_pattern_analysis": {"node_count": 10, "summary_text": "路网画像"},
        }
    )

    result = audit_execution(
        question="我想在这里开一家咖啡店，给我建议",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=memory,
    )

    assert result.passed is False
    assert "候选格子列表" in result.required_evidence
    assert "候选格子列表" in result.missing_evidence


def test_auditor_flags_boundary_risk_for_revenue_inference():
    snapshot = _snapshot_with_scope(
        population={"summary": {"total_population": 1000}},
        nightlight={"summary": {"max_radiance": 10.0}},
    )
    memory = WorkingMemory(
        artifacts={
            "scope_polygon": snapshot.scope["polygon"],
            "current_population_summary": {"total_population": 1000},
            "current_nightlight_summary": {"max_radiance": 10.0},
        }
    )

    result = audit_execution(
        question="这个区域能不能推断营业额和消费能力",
        snapshot=snapshot,
        context=build_context_bundle(snapshot),
        memory=memory,
    )

    assert result.followup_plan == []
    assert any("经营收益" in issue or "消费能力" in issue for issue in result.issues)
