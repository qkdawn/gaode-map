from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.spatial_strategy.schemas import (
    KnowledgeBaseIngestAccepted,
    SpatialStrategyRunAccepted,
    SpatialStrategyRunDetail,
)
from modules.spatial_strategy.service import SpatialStrategyGatewayError
from router.domains import spatial_strategy
def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(spatial_strategy.router)
    return app


def _accepted() -> SpatialStrategyRunAccepted:
    return SpatialStrategyRunAccepted(
        accepted=True,
        run_id="00000000-0000-4000-8000-000000000001",
        status="准备中",
        message="分析任务已接收，正在准备项目资料。",
        status_url="/api/v1/analysis/spatial-strategy/runs/00000000-0000-4000-8000-000000000001",
    )


def _detail() -> SpatialStrategyRunDetail:
    now = datetime.now(timezone.utc)
    return SpatialStrategyRunDetail(
        run_id="00000000-0000-4000-8000-000000000001",
        status="分析中",
        message="正在分析第 3 章“市场与流动”，已完成 2 章。",
        created_at=now,
        updated_at=now,
        progress={"completed_chapters": 2, "total_chapters": 12},
        chapters=[],
    )


def test_submit_spatial_strategy_requires_tenant_header():
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-strategy/runs",
            json={"project_question": "判断项目定位"},
        )
    assert response.status_code == 422


def test_submit_spatial_strategy_forwards_identity_headers(monkeypatch):
    seen = {}

    async def fake_submit(payload, *, tenant_id, access_groups):
        seen.update(payload=payload, tenant_id=tenant_id, access_groups=access_groups)
        return _accepted()

    monkeypatch.setattr(spatial_strategy, "submit_spatial_strategy_run", fake_submit)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-strategy/runs",
            headers={"X-Tenant-Id": "tenant-1", "X-Access-Groups": "planning, planning, finance"},
            json={"project_question": "判断项目定位", "deliver_to_feishu": True},
        )

    assert response.status_code == 202
    assert response.json()["run_id"] == _accepted().run_id
    assert seen["tenant_id"] == "tenant-1"
    assert seen["access_groups"] == ["planning", "finance"]
    assert seen["payload"].project_question == "判断项目定位"
    assert seen["payload"].deliver_to_feishu is True


def test_submit_spatial_strategy_rejects_permission_fields_in_body():
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-strategy/runs",
            headers={"X-Tenant-Id": "tenant-1", "X-Access-Groups": "planning"},
            json={"project_question": "判断项目定位", "access_groups": ["client-supplied"]},
        )

    assert response.status_code == 422


def test_read_spatial_strategy_maps_not_found(monkeypatch):
    async def fake_read(_run_id, *, tenant_id):
        assert tenant_id == "tenant-1"
        raise SpatialStrategyGatewayError("analysis_run_not_found", status_code=404)

    monkeypatch.setattr(spatial_strategy, "get_spatial_strategy_run", fake_read)
    with TestClient(_app()) as client:
        response = client.get(
            "/api/v1/analysis/spatial-strategy/runs/00000000-0000-4000-8000-000000000001",
            headers={"X-Tenant-Id": "tenant-1"},
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "analysis_run_not_found"


def test_read_spatial_strategy_returns_detail(monkeypatch):
    async def fake_read(_run_id, *, tenant_id):
        assert tenant_id == "tenant-1"
        return _detail()

    monkeypatch.setattr(spatial_strategy, "get_spatial_strategy_run", fake_read)
    with TestClient(_app()) as client:
        response = client.get(
            "/api/v1/analysis/spatial-strategy/runs/00000000-0000-4000-8000-000000000001",
            headers={"X-Tenant-Id": "tenant-1"},
        )
    assert response.status_code == 200
    assert response.json()["progress"] == {"completed_chapters": 2, "total_chapters": 12}


def test_resume_spatial_strategy_uses_run_id_and_tenant(monkeypatch):
    seen = {}

    async def fake_resume(run_id, *, tenant_id):
        seen.update(run_id=str(run_id), tenant_id=tenant_id)
        return _accepted()

    monkeypatch.setattr(spatial_strategy, "resume_spatial_strategy_run", fake_resume)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-strategy/runs/00000000-0000-4000-8000-000000000001/resume",
            headers={"X-Tenant-Id": "tenant-1"},
        )

    assert response.status_code == 202
    assert seen == {
        "run_id": "00000000-0000-4000-8000-000000000001",
        "tenant_id": "tenant-1",
    }


def test_publish_document_to_knowledge_base_forwards_tenant_and_groups(monkeypatch):
    seen = {}

    async def fake_ingest(payload, *, tenant_id, access_groups):
        seen.update(payload=payload, tenant_id=tenant_id, access_groups=access_groups)
        return KnowledgeBaseIngestAccepted(
            accepted=True,
            status="published",
            document_id=payload.document_id,
            tenant_id=tenant_id,
            result={"chunk_count": 3},
        )

    monkeypatch.setattr(spatial_strategy, "ingest_document_to_knowledge_base", fake_ingest)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/knowledge-base/documents",
            headers={"X-Tenant-Id": "tenant-1", "X-Access-Groups": "planning,finance"},
            json={"document_id": "doc-1", "visibility": "restricted", "source_type": "knowledge_base"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    assert seen["tenant_id"] == "tenant-1"
    assert seen["access_groups"] == ["planning", "finance"]
    assert seen["payload"].source_type == "knowledge_base"


def test_public_knowledge_base_rejects_project_document_source_type():
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/knowledge-base/documents",
            headers={"X-Tenant-Id": "tenant-1"},
            json={"document_id": "doc-1", "source_type": "project_document"},
        )

    assert response.status_code == 422


def test_project_context_endpoint_requires_internal_n8n_key(monkeypatch):
    monkeypatch.setattr(spatial_strategy.settings, "n8n_webhook_api_key", "internal-key")
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-strategy/project-data/context",
            json={"history_id": "history-1"},
        )

    assert response.status_code == 422


def test_project_data_endpoint_reads_history_bound_existing_datasets(monkeypatch):
    seen = {}

    def fake_read(*, history_id, step_key, project_context):
        seen.update(history_id=history_id, step_key=step_key, project_context=project_context)
        return {
            "status": "success",
            "history_id": history_id,
            "step_key": step_key,
            "queries": [{"dataset_id": "poi", "operation": "aggregate", "complete": True}],
            "citations": [{"citation_id": "project:1", "dataset_id": "poi"}],
            "warnings": [],
        }

    monkeypatch.setattr(spatial_strategy.settings, "n8n_webhook_api_key", "internal-key")
    monkeypatch.setattr(spatial_strategy, "get_project_data_for_step", fake_read)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-strategy/project-data/step",
            headers={"X-N8N-Client-Key": "internal-key"},
            json={
                "history_id": "history-1",
                "step_key": "step_04_supply_gap",
                "project_context": {"project": {"history_id": "history-1"}},
            },
        )

    assert response.status_code == 200
    assert response.json()["queries"][0]["dataset_id"] == "poi"
    assert seen == {
        "history_id": "history-1",
        "step_key": "step_04_supply_gap",
        "project_context": {"project": {"history_id": "history-1"}},
    }


def test_legacy_graphrag_endpoint_is_removed(monkeypatch):
    monkeypatch.setattr(spatial_strategy.settings, "n8n_webhook_api_key", "internal-key")
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-strategy/knowledge/graphrag/query",
            headers={"X-N8N-Client-Key": "internal-key"},
            json={"query": "Historic Urban Landscape 的操作化方法", "method": "global"},
        )

    assert response.status_code == 404


def test_harness_synthesis_endpoint_forwards_only_domain_task(monkeypatch):
    seen = {}

    def fake_synthesize(*, run_id, project_question):
        seen.update(run_id=run_id, project_question=project_question)
        return {"recommended_position": "公共文化客厅"}

    monkeypatch.setattr(spatial_strategy.settings, "n8n_webhook_api_key", "internal-key")
    monkeypatch.setattr(spatial_strategy, "synthesize_strategy_blueprint", fake_synthesize)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/analysis/spatial-strategy/harness/synthesize",
            headers={"X-N8N-Client-Key": "internal-key"},
            json={
                "run_id": "7b8ab959-c0e2-4d29-8168-9688cb4989bf",
                "project_question": "形成未来空间策略",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"recommended_position": "公共文化客厅"}
    assert seen == {
        "run_id": "7b8ab959-c0e2-4d29-8168-9688cb4989bf",
        "project_question": "形成未来空间策略",
    }
