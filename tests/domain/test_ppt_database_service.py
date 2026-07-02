from modules.ppt_database import service


def test_build_database_data_package_creates_database_source(monkeypatch):
    detail_payload = {
        "id": "history-1",
        "description": "区域分析",
        "params": {"center": [112.9, 28.2]},
        "poi_summary": {"total": 12, "source": "local", "year": 2026},
        "available_years": [2026],
        "selected_year": 2026,
        "pois_by_year": [{"year": 2026, "source": "local", "count": 12, "summary": {"total": 12}}],
    }

    monkeypatch.setattr(service.history_repo, "get_detail", lambda area_id, include_pois=False: detail_payload)
    monkeypatch.setattr(service.history_repo, "get_pois", lambda area_id: {"poi_summary": detail_payload["poi_summary"]})
    captured = {}
    monkeypatch.setattr(service.analysis_artifact_repo, "upsert", lambda **kwargs: captured.setdefault("artifact", kwargs))

    response = service.build_database_data_package("history-1", title="数据库资料")

    assert response.source.meta["sourceKind"] == "database"
    assert response.source.id.startswith("database:history-1:")
    assert response.source.source_kind == "database"
    assert response.source.evidence_count == 3
    assert response.source.availability == "available"
    assert response.source.locator_summary == "analysis_history:history-1 / database evidence 3"
    assert response.source.meta["aiPayload"]["sourceKind"] == "database"
    assert response.source.meta["aiPayload"]["evidence_nodes"][0]["source_type"] == "database"
    assert response.source.meta["aiPayload"]["evidence_nodes"][0]["id"].startswith("database:history-1:")
    assert "evidence" not in response.source.meta["aiPayload"]
    assert response.items
    assert response.items[0]["id"].startswith("database:history-1:")
    assert response.items[0]["source_type"] == "database"
    assert captured["artifact"]["artifact_type"] == "ppt_database_package"


def test_list_persisted_database_sources_reads_database_artifacts(monkeypatch):
    monkeypatch.setattr(
        service.analysis_artifact_repo,
        "list",
        lambda area_id, artifact_type="": [
            {
                "payload": {
                    "source": {
                        "id": "database:history-1:abc",
                        "type": "database",
                        "title": "数据库资料",
                        "meta": {
                            "sourceKind": "database",
                            "database": {"source_count": 2},
                            "label": "数据库证据 2 条",
                        },
                    },
                    "summary": "数据库证据 2 条",
                    "items": [{"title": "A"}, {"title": "B"}],
                }
            }
        ],
    )

    sources = service.list_persisted_database_sources("history-1")

    assert len(sources) == 1
    assert sources[0].meta["sourceKind"] == "database"
    assert sources[0].id == "database:history-1:abc"
    assert sources[0].source_kind == "database"
    assert sources[0].evidence_count == 2
    assert sources[0].availability == "available"
    assert sources[0].locator_summary == "analysis_history:history-1 / database evidence 2"
