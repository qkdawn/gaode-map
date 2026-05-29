from store.analysis_artifact_repo import AnalysisArtifactRepo, compute_params_hash


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
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

    def add(self, record):
        record.id = self.next_id
        self.next_id += 1
        self.rows.append(record)

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


def test_artifact_repo_upserts_by_identity(monkeypatch):
    fake_session = FakeSession()
    monkeypatch.setattr("store.analysis_artifact_repo.SessionLocal", lambda: fake_session)
    repo = AnalysisArtifactRepo()

    first = repo.upsert(
        history_id="history-1",
        artifact_type="poi_h3_grid",
        params={"resolution": 10},
        scope_fingerprint="scope-a",
        payload={"grid": {"features": [1]}},
        summary={"grid_count": 1},
    )
    second = repo.upsert(
        history_id="history-1",
        artifact_type="poi_h3_grid",
        params={"resolution": 10},
        scope_fingerprint="scope-a",
        payload={"grid": {"features": [1, 2]}},
        summary={"grid_count": 2},
    )
    third = repo.upsert(
        history_id="history-1",
        artifact_type="poi_h3_grid",
        params={"resolution": 11},
        scope_fingerprint="scope-a",
        payload={"grid": {"features": [3]}},
        summary={"grid_count": 1},
    )

    assert first["id"] == second["id"]
    assert second["summary"]["grid_count"] == 2
    assert third["id"] != first["id"]
    assert len(repo.list("history-1", artifact_type="poi_h3_grid")) == 2
    assert repo.list("other-history") == []
