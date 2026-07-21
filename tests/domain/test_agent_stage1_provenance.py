from modules.agent.evidence_verification import verify_evidence_nodes
from modules.agent.schemas import AnalysisSnapshot
from modules.agent.stage1_data_quality import assess_stage1_data_quality
from modules.agent.stage1_provenance import (
    assess_provenance_bindings,
    bind_evidence_to_artifacts,
    build_provenance_registry,
)
from modules.documents import (
    EvidenceItem,
    EvidenceStatus,
    ProjectEvidenceDossier,
)
from modules.documents.schemas import DocumentRole


def document_dossier():
    return ProjectEvidenceDossier(
        status="ready",
        document_ids=["brief"],
        readable_document_ids=["brief"],
        evidence=[
            EvidenceItem(
                id="document:brief:project-evidence:node-12",
                source_id="document:brief",
                document_id="brief",
                document_title="项目摘要",
                document_role=DocumentRole.PROJECT_BRIEF,
                status=EvidenceStatus.CONFIRMED,
                category="building_scale",
                title="建筑现状",
                content="项目包含历史建筑院落。",
                node_id="node-12",
                page_start=12,
                page_end=12,
                locator="pageindex:node-12:p.12",
                citation="项目摘要 p.12 / 建筑现状",
            )
        ],
    )


def ambiguous_document_dossier():
    dossier = document_dossier()
    dossier.evidence.append(
        EvidenceItem(
            id="document:brief:project-evidence:node-18",
            source_id="document:brief",
            document_id="brief",
            document_title="项目摘要",
            document_role=DocumentRole.PROJECT_BRIEF,
            status=EvidenceStatus.CONFIRMED,
            category="analysis_scope",
            title="分析范围",
            content="分析范围以随附图件为准。",
            node_id="node-18",
            page_start=18,
            page_end=18,
            locator="pageindex:node-18:p.18",
            citation="项目摘要 p.18 / 更新范围",
        )
    )
    return dossier


def evidence(**overrides):
    node = {
        "id": "evidence-1",
        "claim": "项目包含历史建筑院落",
        "evidence_type": "F",
        "status": "verified",
        "source_ref": "项目摘要 p.9",
        "source_artifact_id": "node-12",
        "source_date": "2026-01-01",
        "source_locator": "pageindex:node-12:p.9",
        "scope": "分析范围",
        "method": "document_read",
        "comparison_baseline": "",
        "confidence": "high",
        "limitation": "仍需现场核验",
    }
    node.update(overrides)
    return node


def test_document_binding_corrects_page_and_preserves_unverified_source_date():
    registry = build_provenance_registry(
        selected_sources=[{"source_id": "document:brief", "title": "项目摘要"}],
        snapshot=AnalysisSnapshot(),
        dossier=document_dossier(),
    )

    ledger, bindings = bind_evidence_to_artifacts([evidence()], registry=registry)

    assert bindings[0].status == "corrected"
    assert bindings[0].artifact_id == "document:brief:project-evidence:node-12"
    assert set(bindings[0].corrected_fields) == {
        "source_artifact_id",
        "source_locator",
    }
    assert bindings[0].unverified_fields == ["source_date"]
    assert ledger[0]["source_locator"] == "pageindex:node-12:p.12"
    assert ledger[0]["provenance_unverified_fields"] == ["source_date"]


def test_page_alias_selects_the_specific_document_node():
    registry = build_provenance_registry(
        selected_sources=[],
        snapshot=AnalysisSnapshot(),
        dossier=ambiguous_document_dossier(),
    )

    ledger, bindings = bind_evidence_to_artifacts(
        [
            evidence(
                source_ref="项目摘要 p.12",
                source_artifact_id="",
                source_locator="",
                source_date="unknown",
            )
        ],
        registry=registry,
    )

    assert bindings[0].status == "corrected"
    assert bindings[0].artifact_id == "document:brief:project-evidence:node-12"
    assert ledger[0]["source_locator"] == "pageindex:node-12:p.12"


def test_broad_document_title_is_reported_as_ambiguous():
    registry = build_provenance_registry(
        selected_sources=[],
        snapshot=AnalysisSnapshot(),
        dossier=ambiguous_document_dossier(),
    )

    _, bindings = bind_evidence_to_artifacts(
        [
            evidence(
                source_ref="项目摘要",
                source_artifact_id="",
                source_locator="",
                source_date="unknown",
            )
        ],
        registry=registry,
    )
    summary = assess_provenance_bindings(bindings, critical_evidence_ids={"evidence-1"})

    assert bindings[0].status == "conflicting"
    assert bindings[0].discrepancies == []
    assert summary.blocking_issues[0].code == "artifact_binding_ambiguous"


def test_exact_artifact_id_resolves_a_broad_document_title():
    registry = build_provenance_registry(
        selected_sources=[],
        snapshot=AnalysisSnapshot(),
        dossier=ambiguous_document_dossier(),
    )

    _, bindings = bind_evidence_to_artifacts(
        [
            evidence(
                source_ref="项目摘要",
                source_artifact_id="document:brief:project-evidence:node-18",
                source_locator="pageindex:node-18:p.18",
                source_date="unknown",
            )
        ],
        registry=registry,
    )

    assert bindings[0].status == "verified"
    assert bindings[0].artifact_id == "document:brief:project-evidence:node-18"


def test_snapshot_param_bundles_supply_real_year_coordinate_and_sample_metadata():
    snapshot = AnalysisSnapshot(
        h3={"summary": {"grid_count": 35}},
        population={"summary": {}},
        param_bundles={
            "poi_h3_grid": {
                "params": {"poi_year": 2025, "poi_coord_type": "gcj02"},
                "result_refs": {"h3_counts": {"grid_count": 35}},
            },
            "population": {
                "params": {"year": "2020"},
                "result_refs": {"grid_count": 81},
            },
        },
    )

    registry = build_provenance_registry(
        selected_sources=[], snapshot=snapshot, dossier=None
    )
    records = {item.artifact_id: item for item in registry}

    assert records["analysis_snapshot.h3"].metadata == {
        "source_date": "2025",
        "sample_size": 35,
        "coordinate_system": "gcj02",
    }
    assert records["analysis_snapshot.population"].metadata == {
        "source_date": "2020",
        "sample_size": 81,
    }


def test_snapshot_road_binding_corrects_declared_analysis_metadata():
    snapshot = AnalysisSnapshot(
        road={
            "analysis_date": "2026-07-10",
            "coordinate_system": "EPSG:4490",
            "missing_count": 0,
            "duplicate_count": 1,
            "anomaly_count": 2,
            "summary": {"node_count": 48},
        }
    )
    registry = build_provenance_registry(
        selected_sources=[], snapshot=snapshot, dossier=None
    )
    road_evidence = evidence(
        evidence_type="G",
        source_ref="analysis_snapshot.road",
        source_artifact_id="analysis_snapshot.road",
        source_date="unknown",
        source_locator="road-result",
        analysis_date="2025-01-01",
        sample_size=99,
        missing_count=5,
        duplicate_count=0,
        anomaly_count=0,
        coordinate_system="GCJ-02",
        coordinate_transform="GCJ-02->WGS84",
    )

    ledger, bindings = bind_evidence_to_artifacts([road_evidence], registry=registry)

    assert bindings[0].status == "corrected"
    assert set(bindings[0].corrected_fields) >= {
        "source_locator",
        "analysis_date",
        "sample_size",
        "missing_count",
        "duplicate_count",
        "anomaly_count",
        "coordinate_system",
    }
    assert ledger[0]["analysis_date"] == "2026-07-10"
    assert ledger[0]["sample_size"] == 48
    assert ledger[0]["coordinate_system"] == "EPSG:4490"
    assert "coordinate_transform" in bindings[0].unverified_fields


def test_unknown_artifact_is_unverifiable_and_direct_claim_is_downgraded():
    ledger, bindings = bind_evidence_to_artifacts(
        [evidence(source_ref="未知报告", source_artifact_id="missing-node")],
        registry=[],
    )

    verified_ledger, verification = verify_evidence_nodes(
        ledger,
        selected_sources=[],
        snapshot=AnalysisSnapshot(),
    )

    assert bindings[0].status == "unverifiable"
    assert verified_ledger[0]["status"] == "inferred"
    assert verification.status == "passed_with_gaps"
    assert any("真实数据资产" in note for note in verification.notes)


def test_conflicting_authoritative_artifacts_block_critical_delivery():
    snapshot = AnalysisSnapshot(
        road={"coordinate_system": "GCJ-02", "summary": {"node_count": 20}}
    )
    registry = build_provenance_registry(
        selected_sources=[
            {
                "source_id": "road",
                "title": "路网分析",
                "coordinate_system": "EPSG:4490",
                "sample_size": 18,
            }
        ],
        snapshot=snapshot,
        dossier=None,
    )
    _, bindings = bind_evidence_to_artifacts(
        [
            evidence(
                evidence_type="G",
                source_ref="road",
                source_artifact_id="",
            )
        ],
        registry=registry,
    )

    summary = assess_provenance_bindings(bindings, critical_evidence_ids={"evidence-1"})

    assert bindings[0].status == "conflicting"
    assert summary.status == "failed"
    assert summary.blocking_issues[0].code == "artifact_metadata_conflicting"


def test_noncritical_unverifiable_artifact_is_warning_only():
    _, bindings = bind_evidence_to_artifacts([evidence()], registry=[])

    summary = assess_provenance_bindings(bindings)

    assert summary.status == "passed_with_gaps"
    assert summary.issues[0].severity == "warning"


def test_data_quality_does_not_trust_model_only_metadata():
    ledger, _ = bind_evidence_to_artifacts([evidence()], registry=[])

    summary = assess_stage1_data_quality(ledger, critical_evidence_ids={"evidence-1"})

    assert summary.status == "failed"
    assert summary.coverage["source_date"] == 0
    assert summary.coverage["source_locator"] == 0
    assert {item.code for item in summary.blocking_issues} == {
        "source_date_missing",
        "source_locator_missing",
    }
