from modules.evidence_index import SOURCE_INDEX_MANIFEST_ARTIFACT_TYPE, attach_index_manifest, build_source_index_manifest_payload, list_source_index_manifests, persist_source_index_manifest
from modules.evidence_retrieval.schemas import SourceRecord


class FakeManifestRepo:
    def __init__(self):
        self.upserts = []

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        return {"id": len(self.upserts), **kwargs}


def test_persist_source_index_manifest_writes_history_scoped_artifact():
    manifest = build_source_index_manifest_payload(
        source_id="web:area-1",
        source_kind="web",
        native_index_kind="webpage_index",
        node_count=2,
        retrieval_modes=["keyword"],
        read_modes=["node_id", "url"],
        storage_ref={"artifact_id": "artifact-1"},
    )
    ai_payload = attach_index_manifest({"evidence_nodes": []}, manifest)
    source = SourceRecord.model_validate(
        {
            "id": "web:area-1",
            "title": "网页资料",
            "source_kind": "web",
            "status": "ready",
            "meta": {"aiPayload": ai_payload},
        }
    )
    repo = FakeManifestRepo()

    artifact = persist_source_index_manifest("history-1", source, repo=repo)

    assert artifact is not None
    assert repo.upserts[0]["history_id"] == "history-1"
    assert repo.upserts[0]["artifact_type"] == SOURCE_INDEX_MANIFEST_ARTIFACT_TYPE
    assert repo.upserts[0]["params"] == {"source_id": "web:area-1"}
    assert repo.upserts[0]["payload"]["manifest"]["native_index_kind"] == "webpage_index"
    assert repo.upserts[0]["payload"]["source"]["id"] == "web:area-1"
    assert repo.upserts[0]["summary"]["node_count"] == 2


def test_persist_source_index_manifest_ignores_sources_without_manifest():
    repo = FakeManifestRepo()
    source = SourceRecord.model_validate({"id": "web:area-1", "source_kind": "web", "status": "ready"})

    artifact = persist_source_index_manifest("history-1", source, repo=repo)

    assert artifact is None
    assert repo.upserts == []


def test_list_source_index_manifests_reads_manifest_artifacts():
    class FakeListRepo:
        def list(self, history_id, artifact_type=""):
            assert history_id == "history-1"
            assert artifact_type == SOURCE_INDEX_MANIFEST_ARTIFACT_TYPE
            return [
                {"payload": {"manifest": build_source_index_manifest_payload(source_id="web:area-1", source_kind="web", native_index_kind="webpage_index", node_count=1)}},
                {"payload": {"manifest": {"source_id": ""}}},
                {"payload": {}},
            ]

    manifests = list_source_index_manifests("history-1", repo=FakeListRepo())

    assert len(manifests) == 1
    assert manifests[0].source_id == "web:area-1"
    assert manifests[0].native_index_kind == "webpage_index"
