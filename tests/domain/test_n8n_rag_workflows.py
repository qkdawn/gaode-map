from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
GENERATOR_ROOT = ROOT / "n8n" / "workflow-generators"


def _generated(module_name: str) -> dict:
    module_uri = (GENERATOR_ROOT / module_name).as_uri()
    script = f"import({json.dumps(module_uri)}).then(m => process.stdout.write(JSON.stringify(m.default)))"
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def _nodes(workflow: dict) -> dict[str, dict]:
    return {str(node["name"]): node for node in workflow["nodes"]}


def _targets(workflow: dict, source: str, output: int = 0) -> list[str]:
    main = workflow["connections"].get(source, {}).get("main", [])
    return [edge["node"] for edge in (main[output] if len(main) > output else [])]


def test_only_two_formal_generated_workflows_exist():
    generators = sorted(path.name for path in GENERATOR_ROOT.glob("*.workflow.mjs"))
    assert generators == ["public-knowledge-base.workflow.mjs", "urban-renewal-agent.workflow.mjs"]
    assert list((ROOT / "n8n" / "workflows").glob("*.json")) == []

    workflows = [_generated(name) for name in generators]
    assert {item["id"] for item in workflows} == {
        "urbanRenewalDecisionSupportAgent",
        "urbanRenewalPublicKnowledgeBase",
    }
    assert {item["name"] for item in workflows} == {"城市更新决策支持 Agent", "城市更新公共知识库"}
    for workflow in workflows:
        names = [node["name"] for node in workflow["nodes"]]
        assert len(names) == len(set(names))
        assert not any(node["type"] == "n8n-nodes-base.executeWorkflow" for node in workflow["nodes"])
        assert not any(name.startswith(("AN-", "KB-", "LLM-", "EMB-", "RAG-")) for name in names)
        known_names = set(names)
        for node in workflow["nodes"]:
            references = re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", json.dumps(node["parameters"], ensure_ascii=False))
            assert set(references) <= known_names, (node["name"], references)


def test_all_generated_code_nodes_compile_as_javascript():
    for module_name in ("public-knowledge-base.workflow.mjs", "urban-renewal-agent.workflow.mjs"):
        workflow = _generated(module_name)
        snippets = [
            node["parameters"]["jsCode"]
            for node in workflow["nodes"]
            if node["type"] == "n8n-nodes-base.code"
        ]
        payload = json.dumps(snippets, ensure_ascii=False)
        script = "const snippets=" + payload + "; for (const code of snippets) new Function(code);"
        subprocess.run(
            ["node", "-"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            input=script,
        )


def test_agent_has_submit_status_and_single_twelve_step_loop():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    nodes = _nodes(workflow)
    assert nodes["接收分析任务"]["parameters"]["path"] == "api/v1/n8n/spatial-strategy"
    assert nodes["接收任务状态查询"]["parameters"]["path"] == "api/v1/n8n/spatial-strategy/status"
    assert nodes["返回任务已接收"]["parameters"]["options"]["responseCode"] == "={{ $json.response_status ?? 202 }}"
    assert _targets(workflow, "返回任务已接收") == []
    assert _targets(workflow, "定时领取分析任务") == ["领取排队分析任务"]
    claim_query = nodes["领取排队分析任务"]["parameters"]["query"]
    assert "FOR UPDATE SKIP LOCKED" in claim_query
    assert "status = 'queued' OR (status = 'running' AND lease_expires_at < NOW())" in claim_query
    assert "lease_expires_at = NOW() + INTERVAL '15 minutes'" in claim_query
    assert "$('展开领取任务请求').first()?.json" in nodes["合并项目上下文"]["parameters"]["jsCode"]

    loops = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.splitInBatches"]
    assert [node["name"] for node in loops] == ["逐项执行分析方向"]
    assert loops[0]["parameters"]["batchSize"] == 1
    queue_code = nodes["建立十二步分析队列"]["parameters"]["jsCode"]
    assert queue_code.count("'step_") == 12
    assert _targets(workflow, "合并项目上下文") == ["构建整体研究框架"]
    assert _targets(workflow, "构建整体研究框架") == ["构建研究框架请求体"]
    assert _targets(workflow, "解析研究框架响应") == ["确认整体研究框架"]
    assert _targets(workflow, "确认整体研究框架") == ["建立十二步分析队列"]
    frame_code = nodes["构建整体研究框架"]["parameters"]["jsCode"]
    assert "真正需要作出的选择" in frame_code
    assert "不要为了形式凑假设" in frame_code
    assert "research_frame" in queue_code
    assert "research_brief" in queue_code
    assert "一期最值得验证谁，而不是给人群贴标签" in queue_code
    assert "客群之间的互补和冲突" in queue_code
    assert _targets(workflow, "逐项执行分析方向", 0) == ["读取完整分析状态"]
    assert _targets(workflow, "逐项执行分析方向", 1) == ["读取最新分析状态"]
    assert "逐项执行分析方向" in _targets(workflow, "完成当前分析方向")
    assert "逐项执行分析方向" in _targets(workflow, "复用已完成章节")


def test_agent_inlines_retrieval_responses_and_project_tools():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    nodes = _nodes(workflow)
    assert nodes["生成公共证据查询向量"]["parameters"]["url"] == "__EMBEDDING_API_BASE_URL__/api/embed"
    assert "hybrid_search_kb" in nodes["混合检索公共证据"]["parameters"]["query"]
    assert nodes["混合检索公共证据"]["alwaysOutputData"] is True
    assert _targets(workflow, "检索到候选证据？", 1) == ["跳过空证据重排"]
    assert "skipped-no-candidates" in nodes["跳过空证据重排"]["parameters"]["jsCode"]

    for name in ("请求重排模型", "请求章节分析模型", "请求深化分析模型", "请求图件设计模型", "请求报告叙事模型"):
        assert nodes[name]["parameters"]["url"] == "__CODEX_RELAY_BASE_URL__/responses"
        assert nodes[name]["parameters"]["options"]["timeout"] >= 300_000

    chapter_code = nodes["构建章节分析请求"]["parameters"]["jsCode"]
    follow_up = nodes["将项目工具结果交回模型"]["parameters"]["jsCode"]
    assert all(tool in chapter_code for tool in ("project_context", "query_data", "read_project_document"))
    assert "项目文档必须按需读取原文" in chapter_code
    assert "可以使用 Markdown 表格" in chapter_code
    assert "不强制每章使用" in chapter_code
    assert "提出可能成立的解释或路径" in chapter_code
    assert "替代解释" in chapter_code
    assert "decision_brief" in chapter_code
    assert "自由文本，不使用固定模板" in chapter_code
    assert "properties: { decision_brief:" in chapter_code
    assert "evidence_claims" not in chapter_code
    assert "context_budget" in follow_up
    assert "no_new_evidence" in follow_up
    assert "tool_errors" in follow_up
    assert "emergency_cap" not in follow_up
    assert "tool_choice: resolvedStopReason ? 'none' : undefined" in follow_up
    assert "const forceFinal = turn >= 6" not in follow_up
    assert "context_budget_tokens: 24000" in chapter_code
    assert "no_new_evidence_limit: 2" in chapter_code
    assert _targets(workflow, "解析章节模型响应") == ["章节模型请求工具？"]
    assert _targets(workflow, "章节模型请求工具？", 0) == ["准备项目工具调用"]
    assert _targets(workflow, "章节模型请求工具？", 1) == ["深化章节判断"]
    assert _targets(workflow, "深化章节判断") == ["构建深化请求体"]
    assert _targets(workflow, "解析深化分析响应") == ["校验章节正文"]
    deepen_code = nodes["深化章节判断"]["parameters"]["jsCode"]
    assert "另一种解释" in deepen_code
    assert "不做格式审计" in deepen_code
    assert "reasoning: { effort: 'high' }" in deepen_code
    assert "tools: []" in deepen_code
    assert _targets(workflow, "将项目工具结果交回模型") == ["刷新分析任务租约"]

    for name in ("构建整体研究框架", "请求研究框架模型", "确认整体研究框架", "校验当前分析方向", "构建章节分析请求", "请求章节分析模型", "深化章节判断", "请求深化分析模型", "校验章节正文", "保存章节与分析状态", "生成最终报告"):
        assert nodes[name]["onError"] == "continueErrorOutput"
        assert "记录任务失败" in _targets(workflow, name, 1)
    assert workflow["settings"]["executionTimeout"] == 14400
    assert "citations = COALESCE" in nodes["保存章节与分析状态"]["parameters"]["query"]
    assert "heartbeat_at = NOW()" in nodes["标记当前方向执行中"]["parameters"]["query"]
    follow_up_code = nodes["将项目工具结果交回模型"]["parameters"]["jsCode"]
    validation_code = nodes["校验章节正文"]["parameters"]["jsCode"]
    assert "prior.mcp_tool_name === 'read_project_document'" in follow_up_code
    assert "prior.mcp_tool_name === 'query_data'" in follow_up_code
    assert "tool_evidence: toolEvidence" in follow_up_code
    assert "response.tool_evidence" in validation_code
    assert "evidence_index:" in validation_code
    assert "decisionBrief" in validation_code
    assert "decision_brief: decisionBrief" in validation_code
    assert "reader_chapter_missing_evidence_context" not in validation_code
    assert "reader_chapter_missing_conditions" not in validation_code
    assert "刷新分析任务租约" in nodes
    assert "刷新报告阶段租约" in nodes
    assert _targets(workflow, "将项目工具结果交回模型") == ["刷新分析任务租约"]
    assert _targets(workflow, "刷新分析任务租约") == ["恢复章节工具上下文"]
    assert _targets(workflow, "恢复章节工具上下文") == ["构建章节模型请求体"]
    assert _targets(workflow, "刷新报告阶段租约") == ["恢复报告图件上下文"]
    assert _targets(workflow, "恢复报告图件上下文") == ["构建报告叙事请求"]


def test_agent_resume_status_persistence_and_report_contracts_remain_intact():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    nodes = _nodes(workflow)
    submit_code = nodes["校验并规范分析任务"]["parameters"]["jsCode"]
    queue_query = nodes["创建或恢复分析任务"]["parameters"]["query"]
    assert "resume_run_id must be a UUID" in submit_code
    assert "resumed AS" in queue_query and "status = 'failed'" in queue_query
    assert "\\nUNION ALL" not in queue_query
    assert "404" in queue_query and "409" in queue_query
    assert "analysis_run_not_found" in queue_query
    assert "analysis_run_not_resumable" in queue_query
    resumed_sql = queue_query.split("resumed AS", 1)[1].split("created AS", 1)[0]
    assert "decision_state" not in resumed_sql

    status_query = nodes["读取租户范围任务状态"]["parameters"]["query"]
    assert "FROM analysis_reports report WHERE report.run_id = r.id" in status_query
    assert "'markdown', report.markdown" in status_query
    assert "'asset_manifest', report.asset_manifest" in status_query
    assert "INSERT INTO analysis_reports" in nodes["完成分析任务"]["parameters"]["query"]
    assert _targets(workflow, "生成最终报告") == ["需要发送飞书？"]
    assert "/analysis/spatial-strategy/visuals" in nodes["生成项目数据图件"]["parameters"]["url"]
    assert "/analysis/spatial-strategy/reports/deliver" in nodes["生成 Word 报告并发送飞书"]["parameters"]["url"]
    editorial_code = nodes["构建报告叙事请求"]["parameters"]["jsCode"]
    assert "decision_brief" in editorial_code
    assert "不要按十二章顺序逐项摘要" in editorial_code
    assert "reasoning: { effort: 'medium' }" in editorial_code


def test_public_knowledge_base_rejects_project_documents_and_owns_embedding_publish():
    workflow = _generated("public-knowledge-base.workflow.mjs")
    nodes = _nodes(workflow)
    assert nodes["接收公共资料"]["parameters"]["path"] == "api/v1/n8n/kb/ingest"
    identity_code = nodes["校验公共资料身份与权限"]["parameters"]["jsCode"]
    parse_code = nodes["构建公共资料解析请求"]["parameters"]["jsCode"]
    assert "'knowledge_base'" in identity_code
    assert "project_document" in identity_code and "test_fixture" in identity_code
    assert "project_document" in parse_code and "test_fixture" in parse_code
    assert nodes["生成分块向量"]["parameters"]["url"] == "__EMBEDDING_API_BASE_URL__/api/embed"
    validation_code = nodes["校验分块向量"]["parameters"]["jsCode"]
    assert "embedding count mismatch" in validation_code
    assert "contains non-finite values" in validation_code
    assert "INSERT INTO kb_documents" in nodes["事务发布公共资料"]["parameters"]["query"]
    assert "INSERT INTO kb_chunks" in nodes["事务发布公共资料"]["parameters"]["query"]


def test_bootstrap_imports_generated_workflows_and_removes_only_known_legacy_ids():
    renderer = (ROOT / "n8n" / "bootstrap" / "render-bootstrap.mjs").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "n8n_bootstrap.ps1").read_text(encoding="utf-8")
    assert "endsWith('.workflow.mjs')" in renderer
    assert "N8N_MANAGEMENT_API_KEY" in script
    assert "/api/v1/workflows/$workflowId" in script
    assert "delete:workflow --all" not in script
    assert "ragDbSmoke000001" in script and "analysisSpatialStrategy1" in script
    assert "n8n execute --id=" not in script


def test_compose_and_hybrid_sql_keep_embedding_and_public_source_contracts():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "ollama" not in compose["services"]
    environment = compose["x-n8n-environment"]
    assert environment["EMBEDDING_API_BASE_URL"] == "${N8N_EMBEDDING_API_BASE_URL:-http://host.docker.internal:11435}"
    assert environment["EMBEDDING_DIMENSIONS"] == "${EMBEDDING_DIMENSIONS:-768}"

    sql = (ROOT / "docker" / "rag-db" / "init" / "002_hybrid_retrieval.sql").read_text(encoding="utf-8")
    assert "d.source_type <> 'project_document'" in sql
    assert "d.source_type <> 'test_fixture'" in sql
    assert "cardinality(c.decision_steps)" in sql


def test_schema_and_publish_contracts_are_tenant_scoped():
    base_schema = (ROOT / "docker" / "rag-db" / "init" / "001_schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "docker" / "rag-db" / "init" / "003_analysis_state.sql").read_text(encoding="utf-8")
    workflow = _generated("public-knowledge-base.workflow.mjs")
    publish_query = _nodes(workflow)["事务发布公共资料"]["parameters"]["query"]

    assert "UNIQUE (tenant_id, source_key, version)" in base_schema
    assert "UNIQUE (tenant_id, chunk_key)" in base_schema
    assert "UNIQUE (source_key, version)" not in base_schema
    assert "chunk_key TEXT NOT NULL UNIQUE" not in base_schema
    assert "DROP CONSTRAINT IF EXISTS kb_documents_source_key_version_key" in migration
    assert "DROP CONSTRAINT IF EXISTS kb_chunks_chunk_key_key" in migration
    assert "ON CONFLICT (tenant_id, source_key, version)" in publish_query
    conflict_update = publish_query.split("ON CONFLICT (tenant_id, source_key, version) DO UPDATE SET", 1)[1].split("RETURNING", 1)[0]
    assert "tenant_id = EXCLUDED.tenant_id" not in conflict_update
    assert "INSERT INTO kb_chunks (document_id, tenant_id, chunk_key" in publish_query


def test_analysis_state_migration_backfills_existing_running_leases():
    migration = (ROOT / "docker" / "rag-db" / "init" / "003_analysis_state.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ" in migration
    assert "ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ" in migration
    assert "lease_expires_at = COALESCE(lease_expires_at, updated_at + INTERVAL '15 minutes')" in migration
    assert "WHERE status = 'running'" in migration
