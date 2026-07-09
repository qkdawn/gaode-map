import os
import sys
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
os.environ.setdefault("AMAP_JS_API_KEY", "test-key")

import modules.agent.analysis_quick_answer_service as quick_service

_AGENT_ROUTE_PATH = ROOT_DIR / "router" / "domains" / "agent.py"
_AGENT_ROUTE_SPEC = importlib.util.spec_from_file_location("test_agent_context_ask_route_module", _AGENT_ROUTE_PATH)
agent_router_module = importlib.util.module_from_spec(_AGENT_ROUTE_SPEC)
assert _AGENT_ROUTE_SPEC and _AGENT_ROUTE_SPEC.loader
_AGENT_ROUTE_SPEC.loader.exec_module(agent_router_module)
agent_router = agent_router_module.router


def _build_test_app():
    app = FastAPI()
    app.include_router(agent_router)
    return app


def _payload(question="为什么这么判断？"):
    return {
        "conversation_id": "agent-1",
        "history_id": "history-1",
        "question": question,
        "analysis_snapshot": {"context": {"scope_label": "测试区域"}},
        "target": {
            "type": "report_section",
            "id": "headline",
            "title": "核心判断",
            "source": "report",
            "summary": "该区域商业活力较强。",
            "evidence": [{"metric": "poi_count", "value": 120}],
            "artifact_refs": ["summary_pack.headline"],
            "payload": {"section_key": "headline"},
        },
    }


def test_context_ask_returns_fallback_when_ai_disabled(monkeypatch):
    import modules.agent.context_ask_service as service

    monkeypatch.setattr(service, "is_llm_enabled", lambda: False)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "核心判断" in data["answer"]
    assert data["evidence"]
    assert data["citations"] == ["summary_pack.headline"]
    assert data["warnings"]


def test_context_ask_analysis_sources_fallback_uses_structured_markdown(monkeypatch):
    import modules.agent.context_ask_service as service

    payload = _payload(question="下一步做什么分析")
    payload["target"] = {
        "type": "analysis_sources",
        "id": "analysis-selected-sources",
        "title": "已选分析来源",
        "source": "analysis",
        "summary": "已选择 2 个来源。",
        "evidence": [{"source_id": "current:scope", "title": "当前范围"}],
        "payload": {"sources": [{"source_id": "current:scope", "title": "当前范围"}]},
    }

    monkeypatch.setattr(service, "is_llm_enabled", lambda: False)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "证据边界" in data["answer"]
    assert "继续核对" in data["answer"]
    assert "current:dataset" in data["answer"]
    assert "## 当前可判断的内容" not in data["answer"]
    assert "## 证据和限制" not in data["answer"]
    assert "## 建议继续核对" not in data["answer"]
    assert "## 总体判断" not in data["answer"]
    assert "直接回答：" not in data["answer"]


def test_context_ask_rejects_empty_question():
    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=_payload(question=""))

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "invalid_question"


def test_context_ask_invalid_target_type_returns_validation_error():
    payload = _payload()
    payload["target"]["type"] = "unknown"

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 422


def test_context_ask_ai_provider_exception_falls_back(monkeypatch):
    import modules.agent.context_ask_service as service

    class BrokenClient:
        async def chat_json(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: BrokenClient())

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "AI 调用失败" in "；".join(data["warnings"])


def test_context_ask_require_ai_fails_when_ai_disabled(monkeypatch):
    import modules.agent.context_ask_service as service

    payload = _payload()
    payload["require_ai"] = True
    monkeypatch.setattr(service, "is_llm_enabled", lambda: False)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "ai_unavailable"
    assert data["answer"] == ""


def test_context_ask_require_ai_provider_exception_fails(monkeypatch):
    import modules.agent.context_ask_service as service

    class BrokenClient:
        async def chat_json(self, **kwargs):
            raise RuntimeError("boom")

    payload = _payload()
    payload["require_ai"] = True
    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: BrokenClient())

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "ai_call_failed"
    assert data["answer"] == ""


def test_context_ask_accepts_analysis_sources_and_sends_target_payload(monkeypatch):
    import modules.agent.context_ask_service as service

    captured = {}

    class FakeClient:
        async def chat_json(self, **kwargs):
            captured.update(kwargs)
            return {
                "answer": "已基于已选分析来源回答。",
                "evidence": [{"source_id": "current:scope"}],
                "citations": ["current:scope"],
                "warnings": [],
            }

    payload = _payload()
    payload["require_ai"] = True
    payload["target"] = {
        "type": "analysis_sources",
        "id": "analysis-selected-sources",
        "title": "已选分析来源",
        "source": "analysis",
        "summary": "已选择 1 个来源。",
        "evidence": [{"source_id": "current:scope", "title": "当前等时圈范围", "text": "范围摘要"}],
        "payload": {
            "sources": [{
                "source_id": "current:scope",
                "title": "当前等时圈范围",
                "included": ["scope", "evidence"],
                "scope": {"has_polygon": True},
                "evidence_nodes": [{
                    "id": "current:scope:evidence:1",
                    "source_id": "current:scope",
                    "source_type": "system",
                    "title": "范围",
                    "content": "当前区域",
                }],
            }],
        },
    }
    class SkippedSourceQa:
        status = "skipped"
        answer = ""
        evidence = []
        citations = []
        warnings = []
        used_tools = []
        error = "test_force_context_fallback"

    async def fake_source_qa_loop(_payload):
        return SkippedSourceQa()

    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: FakeClient())
    monkeypatch.setattr(quick_service, "run_source_qa_loop", fake_source_qa_loop)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["answer"] == "已基于已选分析来源回答。"
    target = captured["user_payload"]["target"]
    assert target["type"] == "analysis_sources"
    assert target["source"] == "analysis"
    assert target["evidence"][0]["source_id"] == "current:scope"
    assert target["payload"]["sources"][0]["source_id"] == "current:scope"
    assert captured["user_payload"]["selected_sources_summary"]["source_count"] == 1
    assert captured["user_payload"]["selected_sources_summary"]["sources"][0]["source_id"] == "current:scope"
    assert captured["user_payload"]["selected_sources_summary"]["sources"][0]["evidence_count"] == 1
    assert captured["user_payload"]["selected_sources_summary"]["sources"][0]["evidence_nodes"][0]["id"] == "current:scope:evidence:1"
    assert captured["user_payload"]["scoped_dataset_context"]["datasets"] == {}


def test_context_ask_uses_source_qa_loop_for_analysis_sources(monkeypatch):
    import modules.agent.context_ask_service as service

    class SourceQa:
        status = "success"
        answer = "已通过来源工具回答。"
        evidence = [{"source_id": "current:dataset:road", "citation": "当前范围路网，2024 年"}]
        citations = ["当前范围路网，2024 年"]
        warnings = []
        used_tools = ["list_scope_datasets", "query_scope_dataset"]
        error = ""

    class FakeClient:
        async def chat_json(self, **kwargs):
            raise AssertionError("ppt source QA should not fall back to chat_json")

    payload = _payload(question="为什么这里路网较差")
    payload["require_ai"] = True
    payload["target"] = {
        "type": "analysis_sources",
        "id": "analysis-selected-sources",
        "title": "已选分析来源",
        "source": "analysis",
        "payload": {"sources": [{"source_id": "current:analysis:road"}]},
    }

    async def fake_source_qa_loop(_payload):
        return SourceQa()

    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: FakeClient())
    monkeypatch.setattr(quick_service, "run_source_qa_loop", fake_source_qa_loop)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["answer"] == "已通过来源工具回答。"
    assert data["evidence"][0]["source_id"] == "current:dataset:road"
    assert data["citations"] == ["当前范围路网，2024 年"]
    assert any("query_scope_dataset" in item for item in data["warnings"])


def test_context_ask_keeps_long_markdown_source_qa_answer(monkeypatch):
    import modules.agent.context_ask_service as service

    long_answer = (
        "## 路网组织判断\n"
        "当前范围内部显示，路网问题不是单一指标偏低，而是局部连接、整合与可读性共同造成的空间组织压力。\n\n"
        "## 低连接样本证据\n"
        "来源问答工具读取了当前范围路网明细，并将低连接度、低整合度和高深度样本作为判断依据。\n\n"
        "## 对游逛转化的影响\n"
        "这意味着部分路段可能难以承担连续游逛和商业界面串联，热区之间的转化效率需要进一步核验。\n\n"
        "## 证据边界和下一步\n"
        "没有外部基准时，只能说当前范围内部排序提示局部短板；下一步应叠加 POI 与人流场景验证。"
    )

    class SourceQa:
        status = "success"
        answer = long_answer
        evidence = []
        citations = []
        warnings = []
        used_tools = ["list_scope_datasets", "query_scope_dataset"]
        error = ""

    class FakeClient:
        async def chat_json(self, **kwargs):
            raise AssertionError("ppt source QA should not fall back to chat_json")

    payload = _payload(question="为什么这里路网较差")
    payload["require_ai"] = True
    payload["target"] = {
        "type": "analysis_sources",
        "id": "analysis-selected-sources",
        "title": "已选分析来源",
        "source": "analysis",
        "payload": {"sources": [{"source_id": "current:analysis:road"}]},
    }

    async def fake_source_qa_loop(_payload):
        return SourceQa()

    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: FakeClient())
    monkeypatch.setattr(quick_service, "run_source_qa_loop", fake_source_qa_loop)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["answer"] == long_answer
    assert "## 路网组织判断" in data["answer"]
    assert "## 证据边界和下一步" in data["answer"]


def test_context_ask_enriches_analysis_road_sources_with_scoped_dataset(monkeypatch):
    import modules.agent.context_ask_service as service
    import modules.agent.context_ask_datasets as datasets

    captured = {}

    class FakeScopeDatasetService:
        def list_scope_datasets(self, history_id):
            assert history_id == "history-1"
            return {
                "datasets": [{
                    "source_id": "current:dataset:road",
                    "record_count": 2,
                    "time_scope": {"years": [2024], "label": "2024 年"},
                    "query_capabilities": {"sort_fields": ["choice", "connectivity", "depth", "integration"]},
                }],
                "warnings": [],
            }

        def aggregate_scope_dataset(self, **kwargs):
            assert kwargs["history_id"] == "history-1"
            assert kwargs["source_id"] == "current:dataset:road"
            return {
                "source_id": "current:dataset:road",
                "rows": [{
                    "group": "all",
                    "count": 2,
                    "min_connectivity": 1,
                    "avg_connectivity": 2,
                    "max_connectivity": 3,
                    "min_integration": 0.1,
                    "avg_integration": 0.2,
                    "max_integration": 0.3,
                }],
                "warnings": [],
            }

        def query_scope_dataset(self, **kwargs):
            assert kwargs["history_id"] == "history-1"
            assert kwargs["source_id"] == "current:dataset:road"
            assert kwargs["filters"] == {"feature_kind": "road"}
            field = kwargs["sort"]["field"]
            return {
                "source_id": "current:dataset:road",
                "total_count": 2,
                "limit": 5,
                "offset": 0,
                "has_more": False,
                "records": [{
                    "record_id": f"road-{field}",
                    "source_id": "current:dataset:road",
                    "properties": {"feature_kind": "road", field: 0.1},
                    "time_scope": {"year": 2024},
                    "locator": f"current:dataset:road/road-{field}",
                    "citation": "当前范围路网，2024 年",
                }],
                "evidence_nodes": [{
                    "id": f"current:dataset:road:record:road-{field}",
                    "source_id": "current:dataset:road",
                    "source_type": "system",
                    "title": f"road-{field}",
                    "content": "路网路段样本",
                    "metadata": {"time_scope": {"year": 2024}},
                    "locator": f"current:dataset:road/road-{field}",
                    "citation": "当前范围路网，2024 年",
                }],
                "warnings": [],
            }

    class FakeClient:
        async def chat_json(self, **kwargs):
            captured.update(kwargs)
            return {
                "answer": "已基于当前范围数据检索回答。",
                "evidence": [],
                "citations": [],
                "warnings": [],
            }

    payload = _payload(question="为什么这里路网较差")
    payload["require_ai"] = True
    payload["target"] = {
        "type": "analysis_sources",
        "id": "analysis-selected-sources",
        "title": "已选分析来源",
        "source": "analysis",
        "summary": "已选择路网来源。",
        "payload": {
            "sources": [{
                "source_id": "current:analysis:road",
                "title": "路网与可达性分析",
                "included": ["metrics"],
            }],
        },
    }

    monkeypatch.setattr(datasets, "ScopeDatasetService", FakeScopeDatasetService)
    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: FakeClient())

    class SkippedSourceQa:
        status = "skipped"
        answer = ""
        evidence = []
        citations = []
        warnings = []
        used_tools = []
        error = "test_fallback"

    async def fake_source_qa_loop(_payload):
        return SkippedSourceQa()

    monkeypatch.setattr(quick_service, "run_source_qa_loop", fake_source_qa_loop)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    scoped = captured["user_payload"]["scoped_dataset_context"]
    assert "current:dataset:road" in scoped["datasets"]
    road_context = scoped["datasets"]["current:dataset:road"]
    assert road_context["aggregate"]["rows"][0]["avg_connectivity"] == 2
    assert len(road_context["examples"]) == 4
    assert road_context["examples"][0]["evidence_nodes"][0]["citation"] == "当前范围路网，2024 年"
    assert data["evidence"][0]["source_id"] == "current:dataset:road"
    assert data["citations"] == ["当前范围路网，2024 年"]


def test_context_ask_warns_when_analysis_dataset_source_has_no_history_id(monkeypatch):
    import modules.agent.context_ask_service as service

    captured = {}

    class FakeClient:
        async def chat_json(self, **kwargs):
            captured.update(kwargs)
            return {
                "answer": "缺少 history_id。",
                "evidence": [],
                "citations": [],
                "warnings": [],
            }

    payload = _payload()
    payload["history_id"] = ""
    payload["require_ai"] = True
    payload["target"] = {
        "type": "analysis_sources",
        "id": "analysis-selected-sources",
        "title": "已选分析来源",
        "source": "analysis",
        "payload": {"sources": [{"source_id": "current:dataset:population"}]},
    }

    monkeypatch.setattr(service, "is_llm_enabled", lambda: True)
    monkeypatch.setattr(service, "get_llm_provider_client", lambda: FakeClient())

    class FailedSourceQa:
        status = "failed"
        answer = ""
        evidence = []
        citations = []
        warnings = ["已选来源包含当前范围数据源，但缺少 history_id，无法执行来源工具检索。"]
        used_tools = []
        error = "history_id_required"

    async def fake_source_qa_loop(_payload):
        return FailedSourceQa()

    monkeypatch.setattr(quick_service, "run_source_qa_loop", fake_source_qa_loop)

    with TestClient(_build_test_app()) as client:
        response = client.post("/api/v1/analysis/agent/context-ask", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert captured["user_payload"]["scoped_dataset_context"]["datasets"] == {}
    assert any("history_id" in item for item in data["warnings"])
