from __future__ import annotations

from copy import deepcopy

import pytest

from modules.spatial_action.spatial_evidence_results import (
    SPATIAL_EVIDENCE_RESULT_ARTIFACT_TYPE,
    SpatialEvidenceResultStore,
)


class _Repo:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def list(self, history_id: str, *, artifact_type: str = "", params_hash: str = "") -> list[dict]:
        return [
            deepcopy(record)
            for record in self.records
            if record["history_id"] == history_id and record["artifact_type"] == artifact_type
        ]

    def upsert(self, **kwargs) -> dict:
        record = deepcopy(kwargs)
        self.records.append(record)
        return record


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


def test_spatial_evidence_result_rejects_cross_history_reads_and_mutation():
    store = SpatialEvidenceResultStore(repo=_Repo())
    store.persist(history_id="history-1", result=_result())

    with pytest.raises(LookupError, match="spatial_evidence_result_not_found"):
        store.read(history_id="history-2", result_id="spatial:test-result")
    with pytest.raises(ValueError, match="spatial_evidence_result_immutable"):
        store.persist(history_id="history-1", result=_result(status="unavailable"))


def test_spatial_evidence_result_requires_spatial_result_id():
    store = SpatialEvidenceResultStore(repo=_Repo())

    with pytest.raises(ValueError, match="spatial_evidence_result_id_invalid"):
        store.persist(history_id="history-1", result=_result(result_id="metric:test"))
