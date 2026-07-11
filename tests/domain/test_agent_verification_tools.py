from datetime import date

from modules.agent.evidence_verification import verify_evidence_ledger
from modules.agent.schemas import AnalysisSnapshot
from modules.agent.verification_tools import list_verification_tools


def road_snapshot(**summary):
    payload = {
        "avg_integration_global": 0.63,
        "avg_connectivity": 2.55,
        "avg_intelligibility": 0.22,
        "avg_intelligibility_r2": 0.05,
        "node_count": 120,
    }
    payload.update(summary)
    return AnalysisSnapshot(
        road={
            "summary": payload,
            "diagnostics": {
                "regression": {
                    "r": payload["avg_intelligibility"],
                    "r2": payload["avg_intelligibility_r2"],
                    "n": 120,
                }
            },
        }
    )


def road_evidence(claim, **overrides):
    item = {
        "id": "road-1",
        "claim": claim,
        "evidence_type": "G",
        "status": "verified",
        "source_ref": "analysis_snapshot.road",
        "source_artifact_id": "road-analysis-1",
        "scope": "项目周边路网",
        "method": "space_syntax",
        "metric": "network_metric",
        "value": None,
        "comparison_baseline": "",
        "confidence": "high",
        "limitation": "",
        "next_action": "",
        "executor": "agent",
    }
    item.update(overrides)
    return item


def verify(item, snapshot=None):
    return verify_evidence_ledger(
        [item],
        selected_sources=[],
        snapshot=snapshot or road_snapshot(),
        as_of=date(2026, 7, 12),
    )


def test_verification_tool_registry_declares_claim_capabilities():
    tools = list_verification_tools()

    assert [tool.tool_id for tool in tools] == [
        "verify_road_analysis_claim",
        "verify_proxy_indicator_claim",
    ]
    assert "network_intelligibility" in tools[0].verifies
    assert tools[0].required_inputs == ("road_analysis_snapshot",)
    assert "derived_metrics" in tools[0].produces
    assert "multi_proxy_conclusion" in tools[1].verifies
    assert tools[1].required_inputs == ("matching_analysis_snapshot",)
    assert "proxy_boundaries" in tools[1].produces


def test_intelligibility_check_recomputes_r_squared_and_keeps_relative_claim_inferred():
    ledger, summary = verify(
        road_evidence(
            "可理解度0.22（R²=0.05）属于极低水平",
            metric="network_intelligibility",
            value=0.22,
        )
    )

    assert ledger[0]["status"] == "inferred"
    assert ledger[0]["derived_values"]["intelligibility_r2_recomputed"] == 0.0484
    assert ledger[0]["derived_values"]["intelligibility_r2_reported"] == 0.05
    assert ledger[0]["confidence"] == "medium"
    assert summary.automated_checks[0].tool_id == "verify_road_analysis_claim"
    assert summary.automated_checks[0].outcome == "passed_with_gaps"
    assert any("数学一致" in item for item in summary.automated_checks[0].diagnostics)
    assert any(
        "不能把 r 或 R²直接定性" in item
        for item in summary.automated_checks[0].diagnostics
    )


def test_inconsistent_r_and_r_squared_blocks_claim_until_raw_metrics_are_fixed():
    ledger, summary = verify(
        road_evidence(
            "可理解度r=0.22且R²=0.25",
            metric="network_intelligibility",
            value=0.22,
        ),
        snapshot=road_snapshot(avg_intelligibility_r2=0.25),
    )

    assert ledger[0]["status"] == "blocked"
    assert summary.automated_checks[0].outcome == "blocked"
    assert any("指标不一致" in item for item in summary.automated_checks[0].diagnostics)
    assert summary.tasks[0].executor == "agent"


def test_integration_without_baseline_does_not_become_real_traffic_accessibility():
    ledger, summary = verify(
        road_evidence(
            "平均整合度0.63较高，因此项目外部交通可达性强",
            metric="network_integration",
            value=0.63,
        )
    )

    assert ledger[0]["status"] == "inferred"
    diagnostics = summary.automated_checks[0].diagnostics
    assert any("比较基准" in item for item in diagnostics)
    assert any("不等同于现实交通" in item for item in diagnostics)


def test_connectivity_cannot_directly_prove_commercial_frontage():
    ledger, summary = verify(
        road_evidence(
            "平均连接度2.55说明商业界面不连续",
            metric="network_connectivity",
            value=2.55,
        )
    )

    assert ledger[0]["status"] == "hypothesis"
    assert ledger[0]["confidence"] == "low"
    assert any(
        "不能单独证明商业界面连续性" in item
        for item in summary.automated_checks[0].diagnostics
    )


def test_before_after_claim_without_proposed_geometry_creates_agent_task():
    ledger, summary = verify(
        road_evidence(
            "一路设计已经改善内部路网短板",
            metric="before_after_network_change",
        )
    )

    assert ledger[0]["status"] == "blocked"
    assert summary.tasks[0].executor == "agent"
    assert summary.tasks[0].missing_input == "改造后路网或内部路径中心线数据"
    assert "前后路网对比" in summary.tasks[0].next_action


def test_road_claim_without_analysis_snapshot_is_blocked_for_agent_not_user_guesswork():
    ledger, summary = verify(
        road_evidence("路网整合度较高", metric="network_integration"),
        snapshot=AnalysisSnapshot(),
    )

    assert ledger[0]["status"] == "blocked"
    assert summary.tasks[0].executor == "agent"
    assert "road analysis snapshot" in summary.tasks[0].missing_input
    assert len(summary.tasks) == 1


def proxy_snapshot(**overrides):
    payload = {
        "poi_summary": {"total": 18},
        "population": {"summary": {"total_population": 12500}},
        "nightlight": {"summary": {"mean_radiance": 3.25, "cell_count": 42}},
        "h3": {"summary": {"average_gap_score": 0.31}, "grid_count": 24},
    }
    payload.update(overrides)
    return AnalysisSnapshot(**payload)


def proxy_evidence(claim, *, source_ref, **overrides):
    item = {
        "id": "proxy-1",
        "claim": claim,
        "evidence_type": "G",
        "status": "verified",
        "source_ref": source_ref,
        "source_artifact_id": "analysis-proxy-1",
        "scope": "项目周边研究范围",
        "method": "spatial_proxy_analysis",
        "metric": "proxy_metric",
        "value": None,
        "comparison_baseline": "",
        "confidence": "high",
        "limitation": "",
        "next_action": "",
        "executor": "agent",
    }
    item.update(overrides)
    return item


def test_poi_supply_proxy_cannot_claim_actual_demand_or_revenue():
    ledger, summary = verify(
        proxy_evidence(
            "POI密度说明真实需求旺盛且营业额较高",
            source_ref="analysis_snapshot.poi_summary",
            metric="poi_density",
        ),
        snapshot=proxy_snapshot(),
    )

    assert ledger[0]["status"] == "hypothesis"
    assert ledger[0]["confidence"] == "low"
    assert ledger[0]["derived_values"]["poi_record_count"] == 18
    check = summary.automated_checks[0]
    assert check.tool_id == "verify_proxy_indicator_claim"
    assert check.derived_values["poi_record_count"] == 18
    assert any("不能直接证明真实需求" in item for item in check.diagnostics)


def test_population_structure_cannot_prove_consumption_preference():
    ledger, summary = verify(
        proxy_evidence(
            "周边年龄结构已经证明目标客群具有明确消费偏好",
            source_ref="analysis_snapshot.population",
            metric="population_age_structure",
        ),
        snapshot=proxy_snapshot(),
    )

    assert ledger[0]["status"] == "hypothesis"
    assert ledger[0]["derived_values"]["population_total"] == 12500
    assert any(
        "不能直接证明项目客流、消费偏好" in item
        for item in summary.automated_checks[0].diagnostics
    )


def test_nightlight_proxy_is_typed_as_proxy_and_cannot_claim_footfall_or_payment_power():
    ledger, summary = verify(
        proxy_evidence(
            "夜光强度证明实际客流高且支付能力强",
            source_ref="analysis_snapshot.nightlight",
            metric="nightlight_mean_radiance",
        ),
        snapshot=proxy_snapshot(),
    )

    assert ledger[0]["status"] == "hypothesis"
    assert ledger[0]["evidence_type"] == "P"
    assert ledger[0]["derived_values"] == {
        "nightlight_average": 3.25,
        "nightlight_sample_count": 42,
    }
    assert any(
        "不能等同于客流" in item for item in summary.automated_checks[0].diagnostics
    )


def test_h3_gap_proxy_is_typed_as_proxy_and_cannot_claim_store_success():
    ledger, summary = verify(
        proxy_evidence(
            "H3 gap_score为0.31，说明开店成功概率很高",
            source_ref="analysis_snapshot.h3",
            metric="h3_gap_score",
        ),
        snapshot=proxy_snapshot(),
    )

    assert ledger[0]["status"] == "hypothesis"
    assert ledger[0]["evidence_type"] == "P"
    assert ledger[0]["derived_values"] == {
        "h3_gap_score": 0.31,
        "h3_cell_count": 24,
    }
    assert any(
        "不能解释为开店成功概率" in item
        for item in summary.automated_checks[0].diagnostics
    )


def test_multiple_proxy_signals_do_not_become_a_high_confidence_fact():
    ledger, summary = verify(
        proxy_evidence(
            "POI密度与夜光活跃相互印证，片区机会已得到验证",
            source_ref="analysis_snapshot.poi_summary；analysis_snapshot.nightlight",
            metric="poi_density_and_nightlight",
        ),
        snapshot=proxy_snapshot(),
    )

    assert ledger[0]["status"] == "inferred"
    assert ledger[0]["confidence"] == "medium"
    assert "multi_proxy_conclusion" in summary.automated_checks[0].claim_types
    assert any(
        "不能自动升级为高置信度事实" in item
        for item in summary.automated_checks[0].diagnostics
    )


def test_relative_proxy_claim_without_baseline_remains_inferred():
    ledger, summary = verify(
        proxy_evidence(
            "研究范围内POI密度较高",
            source_ref="analysis_snapshot.poi_summary",
            metric="poi_density",
        ),
        snapshot=proxy_snapshot(),
    )

    assert ledger[0]["status"] == "inferred"
    assert ledger[0]["confidence"] == "medium"
    assert any("比较基准" in item for item in summary.automated_checks[0].diagnostics)


def test_missing_proxy_snapshot_creates_one_agent_owned_task():
    ledger, summary = verify(
        proxy_evidence(
            "POI密度较高",
            source_ref="analysis_snapshot.poi_summary",
            metric="poi_density",
        ),
        snapshot=AnalysisSnapshot(),
    )

    assert ledger[0]["status"] == "blocked"
    assert len(summary.tasks) == 1
    assert summary.tasks[0].executor == "agent"
    assert summary.tasks[0].missing_input == "POI分析快照及其口径、范围和年份"
    assert "先运行POI分析" in summary.tasks[0].next_action


def test_poi_summary_without_count_does_not_emit_a_false_zero():
    ledger, summary = verify(
        proxy_evidence(
            "POI业态数量已完成统计",
            source_ref="analysis_snapshot.poi_summary",
            metric="poi_count",
        ),
        snapshot=proxy_snapshot(poi_summary={"source": "gaode"}),
    )

    assert ledger[0]["status"] == "cross_checked"
    assert "derived_values" not in ledger[0]
    assert summary.automated_checks[0].derived_values == {}
