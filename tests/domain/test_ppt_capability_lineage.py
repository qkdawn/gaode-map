from modules.ppt_planning.service import _compact_evidence_node


def test_compact_ppt_evidence_preserves_capability_artifact_lineage():
    compact = _compact_evidence_node(
        {
            "id": "node-1",
            "source_id": "package:stage1-run:run-1",
            "source_type": "package",
            "title": "第一阶段报告",
            "content": "审定结论",
            "metadata": {
                "run_id": "run-1",
                "source_run_id": "run-1",
                "artifact_id": "stage1-report",
                "content_digest": "sha256:abc",
                "artifact_version": "v1",
                "internal_runtime_path": "runtime/should-not-leak.json",
            },
        }
    )

    assert compact["metadata"] == {
        "run_id": "run-1",
        "source_run_id": "run-1",
        "artifact_id": "stage1-report",
        "content_digest": "sha256:abc",
        "artifact_version": "v1",
    }
