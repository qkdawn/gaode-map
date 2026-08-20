from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml
ROOT = Path(__file__).resolve().parents[2]
CORE_AGENT_PROMPT = "基于已有项目材料和空间数据完成用户任务，给出明确判断及行动建议。不要虚构信息；无法完成时直接说明原因。"
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


def test_report_section_validator_executes_with_request_state():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    code = _nodes(workflow)["校验报告章节正文"]["parameters"]["jsCode"]
    request = {
        "run_id": "37a0ff5a-f861-4338-9439-76467bbe1006",
        "tenant_id": "default",
        "section_order": 1,
        "section": {"section_id": "section_01", "title": "功能结构判断"},
        "state": {"report_sections": []},
    }
    response = {
        "section_id": "section_01",
        "title": "功能结构判断",
        "content": "北部与南部各有一个高密度集聚，形成双中心结构。",
    }
    script = f"""
const code = {json.dumps(code, ensure_ascii=False)};
const request = {json.dumps(request, ensure_ascii=False)};
const response = {json.dumps(response, ensure_ascii=False)};
const $input = {{ first: () => ({{ json: response }}) }};
const $ = () => ({{ first: () => ({{ json: request }}) }});
const result = new Function('$input', '$', code)($input, $);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-"], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", input=script,
    )
    result = json.loads(completed.stdout)
    section = result[0]["json"]["decision_state"]["report_sections"][0]
    assert section["section_id"] == "section_01"
    assert "source_unit_ids" not in section


def test_report_section_validator_rejects_missing_domain_output():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    code = _nodes(workflow)["校验报告章节正文"]["parameters"]["jsCode"]
    request = {"section": {"section_id": "section_01", "title": "功能结构判断"}, "state": {"report_sections": []}}
    script = f"""
const code = {json.dumps(code, ensure_ascii=False)};
const request = {json.dumps(request, ensure_ascii=False)};
const $input = {{ first: () => ({{ json: {{}} }}) }};
const $ = () => ({{ first: () => ({{ json: request }}) }});
try {{ new Function('$input', '$', code)($input, $); }}
catch (error) {{ process.stdout.write(String(error.message)); }}
"""
    completed = subprocess.run(
        ["node", "-"], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", input=script,
    )
    assert completed.stdout == "report_section_identity_mismatch"


def test_agent_has_submit_status_and_fixed_decision_chain():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    nodes = _nodes(workflow)
    assert nodes["接收分析任务"]["parameters"]["path"] == "api/v1/n8n/spatial-strategy"
    assert nodes["接收任务状态查询"]["parameters"]["path"] == "api/v1/n8n/spatial-strategy/status"
    assert _targets(workflow, "定时领取分析任务") == ["领取排队分析任务"]
    claim_query = nodes["领取排队分析任务"]["parameters"]["query"]
    assert "FOR UPDATE SKIP LOCKED" in claim_query
    assert "status = 'queued' OR (status = 'running' AND lease_expires_at < NOW())" in claim_query
    assert "lease_expires_at = NOW() + INTERVAL '6 hours'" in claim_query

    loops = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.splitInBatches"]
    assert [node["name"] for node in loops] == ["逐项执行分析方向", "逐节生成统一报告"]
    frame_code = nodes["构建整体研究框架"]["parameters"]["jsCode"]
    validator = nodes["确认整体研究框架"]["parameters"]["jsCode"]
    expected = (
        "current_structure", "future_role", "users_and_scenarios", "spatial_mechanisms",
        "product_and_operation", "first_phase_actions", "phasing",
    )
    for unit_id in expected:
        assert unit_id in frame_code
    assert "decision_units_must_follow_strategy_chain" in validator
    assert _targets(workflow, "合并项目上下文") == ["构建整体研究框架"]
    assert _targets(workflow, "构建整体研究框架") == ["确认整体研究框架"]
    assert _targets(workflow, "确认整体研究框架") == ["建立自适应分析队列"]
    assert _targets(workflow, "逐项执行分析方向", 0) == ["读取完整分析状态"]
    assert _targets(workflow, "逐项执行分析方向", 1) == ["读取最新分析状态"]


def test_agent_delegates_model_and_tool_runtime_to_codex_harness():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    nodes = _nodes(workflow)
    removed = {
        "构建证据路由请求", "请求证据路由模型", "校验证据路由决策", "路由 Agent 请求工具？",
        "准备证据路由工具调用", "执行证据工具", "更新证据简报", "证据路由需要修正？",
        "请求章节研究模型", "请求报告章节写作模型", "请求图件设计模型",
    }
    assert removed.isdisjoint(nodes)
    assert _targets(workflow, "标记当前方向执行中") == ["调用 Codex Harness 分析单元"]

    endpoints = {
        "调用 Codex Harness 分析单元": "harness/analyze-unit",
        "调用 Codex Harness 综合方案": "harness/synthesize",
        "调用 Codex Harness 撰写章节": "harness/write-section",
        "调用 Codex Harness 设计图件": "harness/design-visuals",
    }
    for name, endpoint in endpoints.items():
        node = nodes[name]
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert endpoint in node["parameters"]["url"]
        assert node["parameters"]["options"]["timeout"] == 3_600_000
        assert node.get("retryOnFail") is not True

    unit_body = nodes["调用 Codex Harness 分析单元"]["parameters"]["jsonBody"]
    assert all(field in unit_body for field in ("run_id", "history_id", "project_question", "decision_unit"))
    assert all(field not in unit_body for field in ("tool_calls", "response_id", "conversation_items", "retry"))
    synthesis_body = nodes["调用 Codex Harness 综合方案"]["parameters"]["jsonBody"]
    assert "run_id" in synthesis_body and "project_question" in synthesis_body
    assert "decision_state" not in synthesis_body
    assert not (ROOT / "n8n" / "workflow-components" / "responses.json").exists()
    assert "codexRelayResponse1" not in (ROOT / "scripts" / "n8n_bootstrap.ps1").read_text(encoding="utf-8")


def test_agent_prompts_use_one_minimal_domain_contract():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    workflow_text = json.dumps(workflow, ensure_ascii=False)
    harness_source = (ROOT / "modules" / "spatial_strategy" / "harness_synthesis.py").read_text(encoding="utf-8")
    assert CORE_AGENT_PROMPT in harness_source
    assert "max_output_tokens" not in workflow_text
    assert "function_call_output" not in workflow_text
    assert "事实—代理—未知" not in harness_source
    assert "完整披露" not in harness_source
    assert "输出前自检" not in harness_source
    assert "逐字继承" not in harness_source

    section_request = _nodes(workflow)["构建报告章节写作请求"]["parameters"]["jsCode"]
    assert "solution" in section_request and "current_section" in section_request
    assert all(term not in section_request for term in ("source_unit_ids", "memo.reasoning", "tool_name", "node_id"))
    summary_code = _nodes(workflow)["准备报告总判断"]["parameters"]["jsCode"]
    assert "blueprint.executive_summary" in summary_code


def test_n8n_execution_history_keeps_failures_for_seven_days_only():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["x-n8n-environment"]

    assert environment["EXECUTIONS_DATA_SAVE_ON_SUCCESS"] == "${N8N_EXECUTIONS_DATA_SAVE_ON_SUCCESS:-none}"
    assert environment["EXECUTIONS_DATA_SAVE_ON_ERROR"] == "${N8N_EXECUTIONS_DATA_SAVE_ON_ERROR:-all}"
    assert environment["EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS"] == "${N8N_EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS:-false}"
    assert environment["EXECUTIONS_DATA_SAVE_ON_PROGRESS"] == "${N8N_EXECUTIONS_DATA_SAVE_ON_PROGRESS:-false}"
    assert environment["EXECUTIONS_DATA_PRUNE"] == "${N8N_EXECUTIONS_DATA_PRUNE:-true}"
    assert environment["EXECUTIONS_DATA_MAX_AGE"] == "${N8N_EXECUTIONS_DATA_MAX_AGE:-168}"


def test_agent_resume_status_persistence_and_report_contracts_remain_intact():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    nodes = _nodes(workflow)
    submit_code = nodes["校验并规范分析任务"]["parameters"]["jsCode"]
    queue_query = nodes["创建或恢复分析任务"]["parameters"]["query"]
    assert "resume_run_id must be a UUID" in submit_code
    assert "resumed AS" in queue_query and "status = 'failed'" in queue_query
    assert "jsonb_build_object('steps', '{}'::jsonb)" in queue_query
    assert "heartbeat_at = NULL" in queue_query
    assert "lease_expires_at = NULL" in queue_query
    assert "DELETE FROM analysis_step_outputs" not in queue_query

    completed_condition = nodes["当前方向已完成？"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
    assert "decision_state.steps[$json.step_key] !== undefined" in completed_condition
    assert _targets(workflow, "当前方向已完成？", 0) == ["复用已完成章节"]
    assert _targets(workflow, "当前方向已完成？", 1) == ["标记当前方向执行中"]
    assert "step.status = 'completed'" in nodes["读取最新分析状态"]["parameters"]["query"]
    assert "ON CONFLICT (run_id, step) DO UPDATE" in nodes["标记当前方向执行中"]["parameters"]["query"]
    assert _targets(workflow, "读取完整分析状态") == ["检查综合方案恢复状态"]
    assert _targets(workflow, "综合方案已完成？", 0) == ["检查报告章节恢复状态"]
    assert _targets(workflow, "综合方案已完成？", 1) == ["构建跨单元综合请求"]
    assert _targets(workflow, "报告章节已完成？", 0) == ["构建图件设计请求"]
    assert _targets(workflow, "报告章节已完成？", 1) == ["展开报告章节队列"]
    assert "!completedIds.has" in nodes["展开报告章节队列"]["parameters"]["jsCode"]

    status_query = nodes["读取租户范围任务状态"]["parameters"]["query"]
    assert "FROM analysis_reports report WHERE report.run_id = r.id" in status_query
    assert "'markdown', report.markdown" in status_query
    assert "INSERT INTO analysis_reports" in nodes["完成分析任务"]["parameters"]["query"]
    assert _targets(workflow, "生成最终报告") == ["规范化最终报告响应"]
    normalize_report_code = nodes["规范化最终报告响应"]["parameters"]["jsCode"]
    assert "final_report_markdown_missing" in normalize_report_code
    assert "final_report_docx_missing" in normalize_report_code
    assert "current.body" not in normalize_report_code and "current.data" not in normalize_report_code

    section_writer_code = nodes["构建报告章节写作请求"]["parameters"]["jsCode"]
    for field in ("judgment:", "current_basis:", "future_goal:", "actions:", "intended_effect:"):
        assert field in section_writer_code
    for internal in ("source_analyses", "sourceMemos", "memo.reasoning", "source_unit_ids", "completed_sections"):
        assert internal not in section_writer_code
    assert "named_entities: Array.isArray(blueprint.named_entities)" in section_writer_code
    section_body = nodes["调用 Codex Harness 撰写章节"]["parameters"]["jsonBody"]
    assert "project_question" in section_body and "solution" in section_body and "section" in section_body
    assert "decision_state" not in section_body
    assert "report_section_identity_mismatch" in nodes["校验报告章节正文"]["parameters"]["jsCode"]

    assert "/analysis/spatial-strategy/visuals" in nodes["生成项目数据图件"]["parameters"]["url"]
    assert "/analysis/spatial-strategy/reports/deliver" in nodes["生成 Word 报告并发送飞书"]["parameters"]["url"]
    visual_code = nodes["构建图件设计请求"]["parameters"]["jsCode"]
    assert "solution:" in visual_code
    assert "action_plan: blueprint.action_plan" in visual_code
    assert "named_entities: Array.isArray(blueprint.named_entities)" in visual_code
    assert "decision_memos" not in visual_code
    assert "String(item.dataset_id ?? '') !== 'road_nodes'" in visual_code
    visual_validation_code = nodes["校验图件设计"]["parameters"]["jsCode"]
    assert "Array.isArray(response.visuals)" in visual_validation_code
    assert "visuals.length < 3 || visuals.length > 5" in visual_validation_code


def test_public_knowledge_base_rejects_project_documents_and_owns_embedding_publish():
    workflow = _generated("public-knowledge-base.workflow.mjs")
    nodes = _nodes(workflow)
    assert nodes["接收公共资料"]["parameters"]["path"] == "api/v1/n8n/kb/ingest"
    identity_code = nodes["校验公共资料身份与权限"]["parameters"]["jsCode"]
    parse_code = nodes["构建公共资料解析请求"]["parameters"]["jsCode"]
    assert "'knowledge_base'" in identity_code
    assert "project_document" in identity_code and "test_fixture" in identity_code
    assert "project_document" in parse_code and "test_fixture" in parse_code
    assert nodes["生成分块向量"]["parameters"]["url"] == "__EMBEDDING_API_BASE_URL__/v1/embeddings"
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
