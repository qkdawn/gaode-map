from store.analysis_artifact_repo import AnalysisArtifactRepo, compute_params_hash, normalize_scope_fingerprint
from store.artifact_identity import build_artifact_slot_key


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def filter(self, *_args):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        matches = self.all()
        return matches[0] if matches else None

    def all(self):
        result = []
        for row in self.rows:
            if all(getattr(row, key) == value for key, value in self.filters.items()):
                result.append(row)
        return result


class FakeSession:
    def __init__(self):
        self.rows = []
        self.next_id = 1

    def query(self, _model):
        return FakeQuery(self.rows)

    def get(self, _model, record_id):
        for row in self.rows:
            if row.id == record_id:
                return row
        return None

    def add(self, record):
        record.id = self.next_id
        self.next_id += 1
        self.rows.append(record)

    def delete(self, record):
        self.rows = [row for row in self.rows if row is not record]

    def commit(self):
        pass

    def refresh(self, _record):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_params_hash_is_canonical_and_changes_with_params():
    assert compute_params_hash({"year": 2024, "source": "local"}) == compute_params_hash({"source": "local", "year": 2024})
    assert compute_params_hash({"year": 2024}) != compute_params_hash({"year": 2025})


def test_scope_fingerprint_keeps_short_keys_and_hashes_scope_payloads():
    raw_scope = '{"polygon":[[112.1,28.1],[112.2,28.2]],"mode":"walking","time_min":30}'

    assert normalize_scope_fingerprint("scope-a") == "scope-a"
    assert normalize_scope_fingerprint(raw_scope).startswith("scope:")
    assert len(normalize_scope_fingerprint(raw_scope)) == 70
    assert normalize_scope_fingerprint(raw_scope) == normalize_scope_fingerprint(raw_scope)


def test_artifact_repo_upserts_by_identity(monkeypatch):
    fake_session = FakeSession()
    monkeypatch.setattr("store.analysis_artifact_repo.SessionLocal", lambda: fake_session)
    monkeypatch.setattr("store.analysis_artifact_repo._history_scope_fingerprint", lambda *_args: "scope:history-wgs84")
    repo = AnalysisArtifactRepo()

    first = repo.upsert(
        history_id="history-1",
        artifact_type="poi_h3_grid",
        params={"resolution": 10, "year": 2024},
        payload={"grid": {"features": [1]}},
        summary={"grid_count": 1},
    )
    second = repo.upsert(
        history_id="history-1",
        artifact_type="poi_h3_grid",
        params={"resolution": 11, "year": 2024},
        payload={"grid": {"features": [1, 2]}},
        summary={"grid_count": 2},
    )
    third = repo.upsert(
        history_id="history-1",
        artifact_type="poi_h3_grid",
        params={"resolution": 10, "year": 2020},
        payload={"grid": {"features": [3]}},
        summary={"grid_count": 1},
    )

    assert first["id"] == second["id"]
    assert second["summary"]["grid_count"] == 2
    assert third["id"] != first["id"]
    assert first["slot_key"] == "year:2024"
    assert first["scope_fingerprint"] == "scope:history-wgs84"
    assert len(repo.list("history-1", artifact_type="poi_h3_grid")) == 2
    assert [item["slot_key"] for item in repo.list("history-1", artifact_type="poi_h3_grid")] == ["year:2024", "year:2020"]
    assert repo.list("other-history") == []


def test_artifact_repo_deletes_by_payload_source_id(monkeypatch):
    fake_session = FakeSession()
    monkeypatch.setattr("store.analysis_artifact_repo.SessionLocal", lambda: fake_session)
    monkeypatch.setattr("store.analysis_artifact_repo._history_scope_fingerprint", lambda *_args: "scope:history-wgs84")
    repo = AnalysisArtifactRepo()

    repo.upsert(
        history_id="history-1",
        artifact_type="ppt_data_package",
        params={"intent": "a"},
        payload={"source": {"id": "package:history-1:a"}},
    )
    repo.upsert(
        history_id="history-1",
        artifact_type="ppt_web_source",
        params={"intent": "b"},
        payload={"source": {"id": "web:history-1:b"}},
    )

    deleted = repo.delete_by_source_id(
        "history-1",
        source_id="package:history-1:a",
        artifact_types=["ppt_data_package", "ppt_web_source"],
    )

    assert deleted == 1
    remaining = repo.list("history-1")
    assert [item["payload"]["source"]["id"] for item in remaining] == ["web:history-1:b"]


def test_artifact_slot_key_uses_year_only_for_spatial_time_data():
    assert build_artifact_slot_key("population", {"year": "2026", "view": "density"}) == "year:2026"
    assert build_artifact_slot_key("population", {"year": 2026, "view": "gender"}) == "year:2026"
    assert build_artifact_slot_key("road_syntax", {"metric": "choice"}) == "current"
