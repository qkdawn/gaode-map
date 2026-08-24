from __future__ import annotations

from copy import deepcopy

import pytest

from modules.spatial_action.spatial_evidence_results import (
    SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE,
    SpatialEvidenceResultStore,
)
from store.analysis_artifact_repo import compute_params_hash


class _Repo:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self.list_calls = 0

    def list(self, history_id: str, *, artifact_type: str = "", params_hash: str = "") -> list[dict]:
        self.list_calls += 1
        return [
            deepcopy(record)
            for record in self.records
            if record["history_id"] == history_id and record["artifact_type"] == artifact_type
        ]

    def get_by_params_hash(self, history_id: str, *, artifact_type: str, params_hash: str):
        return next(
            (
                deepcopy(record)
                for record in self.records
                if record["history_id"] == history_id
                and record["artifact_type"] == artifact_type
                and record.get("params_hash") == params_hash
            ),
            None,
        )

    def upsert(self, **kwargs) -> dict:
        record = deepcopy(kwargs)
        record["params_hash"] = compute_params_hash(record.get("params"))
        self.records.append(record)
        return record

    def list_summaries(self, history_id: str, *, artifact_type: str, limit: int) -> list[dict]:
        return [
            {
                "params": deepcopy(record.get("params") or {}),
                "summary": deepcopy(record.get("summary") or {}),
            }
            for record in reversed(self.records)
            if record["history_id"] == history_id and record["artifact_type"] == artifact_type
        ][:limit]


def _result(**overrides) -> dict:
    return {
        "schema_version": "spatial_evidence/v6",
        "result_id": "spatial:test-result",
        "status": "available",
        "analysis": "rank",
        "fact_domains": [{"domain": "road"}],
        "evidence_dimensions": [{"dimension": "road.to_movement"}],
        "used_metric_ids": ["road.nain"],
        **overrides,
    }


def test_spatial_evidence_result_is_persisted_and_read_without_recomputation():
    repo = _Repo()
    store = SpatialEvidenceResultStore(repo=repo)
    expected = _result()

    assert store.persist(history_id="history-1", result=expected) == expected
    assert store.read(history_id="history-1", result_id="spatial:test-result") == expected
    assert repo.records[0]["artifact_type"] == SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE
    assert repo.records[0]["params"] == {"result_id": "spatial:test-result"}


def test_spatial_evidence_result_read_uses_indexed_identity_lookup():
    repo = _Repo()
    store = SpatialEvidenceResultStore(repo=repo)
    store.persist(history_id="history-1", result=_result())

    assert store.read(history_id="history-1", result_id="spatial:test-result")["result_id"] == "spatial:test-result"
    assert repo.list_calls == 0


def test_spatial_evidence_result_lists_only_lightweight_references():
    repo = _Repo()
    store = SpatialEvidenceResultStore(repo=repo)
    store.persist(history_id="history-1", result=_result())

    assert store.list_references(history_id="history-1") == [{
        "result_id": "spatial:test-result",
        "status": "available",
        "analysis": "rank",
        "fact_domains": [{"domain": "road"}],
        "evidence_dimensions": [{"dimension": "road.to_movement"}],
    }]


def test_spatial_evidence_result_rejects_cross_history_reads_and_mutation():
    store = SpatialEvidenceResultStore(repo=_Repo())
    store.persist(history_id="history-1", result=_result())

    with pytest.raises(LookupError, match="spatial_evidence_result_not_found"):
        store.read(history_id="history-2", result_id="spatial:test-result")
    with pytest.raises(ValueError, match="spatial_evidence_result_immutable"):
        store.persist(history_id="history-1", result=_result(status="unavailable"))


def test_machine_float_noise_does_not_create_a_new_result():
    repo = _Repo()
    store = SpatialEvidenceResultStore(repo=repo)
    original = _result(
        domain_results=[{"groups": [{"values": {"to_movement": 1.0611344928649915}}]}]
    )
    repeated = deepcopy(original)
    repeated["domain_results"][0]["groups"][0]["values"]["to_movement"] = 1.0611344928649917

    first = store.persist(history_id="history-1", result=original)
    second = store.persist(history_id="history-1", result=repeated)

    assert first == second
    assert second["domain_results"][0]["groups"][0]["values"]["to_movement"] == 1.061134492865
    assert len(repo.records) == 1


def test_spatial_evidence_result_requires_spatial_result_id():
    store = SpatialEvidenceResultStore(repo=_Repo())

    with pytest.raises(ValueError, match="spatial_evidence_result_id_invalid"):
        store.persist(history_id="history-1", result=_result(result_id="metric:test"))
