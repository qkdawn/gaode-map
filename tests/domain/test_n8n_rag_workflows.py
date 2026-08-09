from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / "n8n" / "workflows"


def _workflow(file_name: str) -> dict:
    return json.loads((WORKFLOW_ROOT / file_name).read_text(encoding="utf-8"))


def _nodes_by_name(workflow: dict) -> dict[str, dict]:
    return {str(node["name"]): node for node in workflow["nodes"]}


def test_embedding_workflow_owns_model_api_and_dimension_validation():
    workflow = _workflow("05-cpu-embedding.json")
    nodes = _nodes_by_name(workflow)

    assert workflow["id"] == "ollamaEmbedding0001"
    assert nodes["Generate Embeddings"]["parameters"]["url"] == "__EMBEDDING_API_BASE_URL__/api/embed"
    request_code = nodes["Build Embedding Request"]["parameters"]["jsCode"]
    validation_code = nodes["Validate Embeddings"]["parameters"]["jsCode"]
    assert "__EMBEDDING_MODEL__" in request_code
    assert "__EMBEDDING_DIMENSIONS__" in request_code
    assert "embedding count mismatch" in validation_code
    assert "contains non-finite values" in validation_code


def test_publish_and_retrieve_always_generate_embeddings_inside_n8n():
    publish = _workflow("01-kb-publish-source.json")
    retrieve = _workflow("10-kb-hybrid-retrieve.json")
    publish_nodes = _nodes_by_name(publish)
    retrieve_nodes = _nodes_by_name(retrieve)

    assert publish_nodes["Embed Source Chunks"]["parameters"]["workflowId"]["value"] == "ollamaEmbedding0001"
    assert publish["connections"]["Validate Parsed Source"]["main"][0][0]["node"] == "Embed Source Chunks"
    assert publish["connections"]["Attach Chunk Embeddings"]["main"][0][0]["node"] == "Publish Source Transaction"

    assert retrieve_nodes["Embed Recall Query"]["parameters"]["workflowId"]["value"] == "ollamaEmbedding0001"
    assert retrieve["connections"]["Normalize Recall Request"]["main"][0][0]["node"] == "Embed Recall Query"
    assert retrieve["connections"]["Attach Query Embedding"]["main"][0][0]["node"] == "Hybrid Keyword Vector Recall"
    assert "input.embedding" not in retrieve_nodes["Normalize Recall Request"]["parameters"]["jsCode"]
    assert "embedding_literal" in retrieve_nodes["Attach Query Embedding"]["parameters"]["jsCode"]


def test_empty_recall_skips_model_rerank_and_returns_empty_citations():
    retrieve = _workflow("10-kb-hybrid-retrieve.json")
    nodes = _nodes_by_name(retrieve)

    assert nodes["Hybrid Keyword Vector Recall"]["alwaysOutputData"] is True
    assert nodes["Expand And Read Source Chunks"]["alwaysOutputData"] is True
    assert retrieve["connections"]["Recall Has Candidates"]["main"][1][0]["node"] == "Skip Empty Rerank"
    assert "skipped-no-candidates" in nodes["Skip Empty Rerank"]["parameters"]["jsCode"]
    assert "Prepare Context Expansion" in nodes["Return Cited Context"]["parameters"]["jsCode"]

    integration = _workflow("99-rag-integration-test.json")
    integration_nodes = _nodes_by_name(integration)
    unauthorized_code = integration_nodes["Build Unauthorized Recall"]["parameters"]["jsCode"]
    assertion_code = integration_nodes["Assert Permission Isolation"]["parameters"]["jsCode"]
    assert "unauthorized-audit-group" in unauthorized_code
    assert "permission filter leaked citations" in assertion_code


def test_codex_relay_timeout_allows_long_structured_decision_responses():
    relay = _nodes_by_name(_workflow("20-codex-relay-response.json"))

    request = relay["Call Codex Relay"]
    build_code = relay["Build Responses Request"]["parameters"]["jsCode"]
    assert request["parameters"]["options"]["timeout"] >= 300_000
    assert request["retryOnFail"] is True
    assert "parallel_tool_calls" in build_code
    assert "previous_response_id" not in build_code


def test_decision_steps_compact_prior_state_and_bound_source_context():
    workflow = _workflow("30-analysis-decision-step.json")
    decision = _nodes_by_name(workflow)
    request_code = decision["Build Structured Decision Request"]["parameters"]["jsCode"]
    follow_up_code = decision["Build MCP Agent Follow-up"]["parameters"]["jsCode"]
    attach_code = decision["Attach Project Data To Retrieval"]["parameters"]["jsCode"]

    assert "slice(0, 12)" in request_code
    assert "slice(0, 2500)" in request_code
    assert "reader_chapter" in request_code
    assert "不套固定短摘要模板" in request_code
    assert "普通读者能理解" in request_code
    assert "候选路径之间的取舍" in request_code
    assert "不得输出引用 ID" in request_code
    assert "不要把条件性判断改写成确定事实" in request_code
    assert "不要另附审计数据" in request_code
    assert "output: value" not in request_code
    assert "max_output_tokens: 5000" in request_code
    assert "reasoning: { effort: 'medium' }" in request_code
    assert "type: 'function'" in request_code
    assert "project_context" in request_code
    assert "query_data" in request_code
    assert "agent_turn: 0" in request_code
    assert "conversation_items" in request_code
    assert "parallel_tool_calls: false" in request_code
    assert "...responseItems" in follow_up_code
    assert "type: 'function_call_output'" in follow_up_code
    assert "toolResult.structured_content ?? toolResult.content ?? toolResult" in follow_up_code
    assert "normalizedToolResult" in follow_up_code
    assert "JSON.stringify(toolResult)" not in follow_up_code
    assert "String(prior.input" not in follow_up_code
    assert "工具背后通过 MCP 读取项目数据" in request_code
    assert "projectCitations" in attach_code
    assert "contexts: [...projectContexts, ...existingContexts]" in attach_code
    assert workflow["connections"]["Retrieve Cited Source Text"]["main"][0][0]["node"] == "Attach Project Data To Retrieval"
    assert workflow["connections"]["Attach Project Data To Retrieval"]["main"][0][0]["node"] == "Prioritize Project Data Contexts"
    priority_code = decision["Prioritize Project Data Contexts"]["parameters"]["jsCode"]
    assert "project_data: 0" in priority_code
    assert workflow["connections"]["Prioritize Project Data Contexts"]["main"][0][0]["node"] == "Build Structured Decision Request"
    assert "Agent Has Tool Calls" in decision
    assert "Prepare MCP Agent Tool Call" in decision
    assert "Call Spatial MCP Tool" in decision
    assert "Build MCP Agent Follow-up" in decision
    assert workflow["connections"]["Call Codex For Decision"]["main"][0][0]["node"] == "Agent Has Tool Calls"
    assert workflow["connections"]["Agent Has Tool Calls"]["main"][0][0]["node"] == "Prepare MCP Agent Tool Call"
    assert workflow["connections"]["Agent Has Tool Calls"]["main"][1][0]["node"] == "Validate Decision Output"
    assert workflow["connections"]["Build MCP Agent Follow-up"]["main"][0][0]["node"] == "Call Codex For Decision"


def test_decision_output_requires_reader_chapter_and_rejects_internal_terms():
    decision = _nodes_by_name(_workflow("30-analysis-decision-step.json"))
    quality_code = decision["Validate Decision Output"]["parameters"]["jsCode"]

    assert "parsed.reader_chapter" in quality_code
    assert "reader_chapter_contains_internal_terms" in quality_code
    assert "reader_chapter_missing_evidence_context" in quality_code
    assert "reader_chapter_missing_conditions" in quality_code
    assert "output.findings" not in quality_code
    assert "options" not in quality_code
    assert "deliverable" not in quality_code
    assert "quality_gate: {}" not in quality_code


def test_decision_steps_are_idempotent_and_parent_retries_transient_failures():
    decision = _workflow("30-analysis-decision-step.json")
    nodes = _nodes_by_name(decision)

    assert decision["connections"]["Validate Step Request"]["main"][0][0]["node"] == "Step Already Completed"
    assert decision["connections"]["Step Already Completed"]["main"][0][0]["node"] == "Return Existing Step Result"
    assert "quality_gate: {}" not in nodes["Return Existing Step Result"]["parameters"]["jsCode"]
    skip_expression = nodes["Step Already Completed"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
    assert "prototype" not in skip_expression

    generator = (ROOT / "n8n" / "workflow-generators" / "31-analysis-spatial-strategy.mjs").read_text(encoding="utf-8")
    assert "retryOnFail: true" in generator
    assert "maxTries: 2" in generator
    codex_node = nodes["Call Codex For Decision"]
    assert codex_node["retryOnFail"] is True
    assert codex_node["maxTries"] == 2
    assert "UPDATE analysis_step_outputs AS step" in generator
    assert "SET status = 'failed'" in generator


def test_spatial_strategy_webhook_can_resume_failed_run_without_losing_state():
    webhook = _nodes_by_name(_workflow("32-analysis-spatial-strategy-webhook.json"))
    normalize = webhook["Normalize Trusted Request"]["parameters"]["jsCode"]
    queue_query = webhook["Create Queued Analysis Run"]["parameters"]["query"]

    assert "resume_run_id" in normalize
    assert "resume_run_id must be a UUID" in normalize
    assert "resumed AS" in queue_query
    assert "status = 'failed'" in queue_query
    assert "error = ''" in queue_query
    assert "decision_state" not in queue_query.split("resumed AS", 1)[1].split("created AS", 1)[0]
    assert "request = payload.value" not in queue_query.split("resumed AS", 1)[1].split("created AS", 1)[0]
    build_request = webhook["Build Orchestration Request"]["parameters"]["jsCode"]
    assert "run.request" in build_request
    assert "analysis_run_not_resumable" in build_request


def test_spatial_strategy_status_returns_persisted_report():
    status = _nodes_by_name(_workflow("33-analysis-spatial-strategy-status.json"))
    query = status["Read Tenant Scoped Run"]["parameters"]["query"]

    assert "FROM analysis_reports report WHERE report.run_id = r.id" in query
    assert "'markdown', report.markdown" in query
    assert "'citations', report.citations" in query
    assert "'asset_manifest', report.asset_manifest" in query


def test_n8n_rag_does_not_reference_legacy_evidence_or_page_indexes():
    contents = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(WORKFLOW_ROOT.glob("*.json"))
    ).lower()

    assert "evidencenode" not in contents
    assert "evidence_node" not in contents
    assert "pageindex" not in contents
    assert "page_index" not in contents


def test_compose_points_n8n_at_the_cpu_embedding_service():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert "ollama" not in services
    environment = compose["x-n8n-environment"]
    assert environment["EMBEDDING_API_BASE_URL"] == "${N8N_EMBEDDING_API_BASE_URL:-http://host.docker.internal:11435}"
    assert environment["EMBEDDING_MODEL"] == "${EMBEDDING_MODEL:-jinaai/jina-embeddings-v2-base-zh}"
    assert environment["EMBEDDING_DIMENSIONS"] == "${EMBEDDING_DIMENSIONS:-768}"


def test_spatial_strategy_orchestrator_queries_history_bound_project_data():
    generator = (ROOT / "n8n" / "workflow-generators" / "31-analysis-spatial-strategy.mjs").read_text(
        encoding="utf-8"
    )
    bootstrap = (ROOT / "n8n" / "bootstrap" / "render-bootstrap.mjs").read_text(encoding="utf-8")

    assert "Load Project Context" in generator
    assert "/analysis/spatial-strategy/project-data/context" in generator
    assert "/analysis/spatial-strategy/project-data/step" in generator
    assert "project_context: $json.project_context" in generator
    assert "project_data: projectData" in generator
    assert "n8n-webhook-client" in generator
    assert "__SPATIAL_API_BASE_URL__" in bootstrap


def test_spatial_strategy_orchestrator_finishes_with_report_delivery_and_persistence():
    generator = (ROOT / "n8n" / "workflow-generators" / "31-analysis-spatial-strategy.mjs").read_text(
        encoding="utf-8"
    )
    assert "编排空间策略报告" in generator
    assert "生成项目数据图件 Agent" in generator
    assert "analysisVisualAgent01" not in generator
    assert "Build Visual Agent Request" in generator
    assert "Validate Visual Design" in generator
    assert "Render Designed Data Visuals" in generator
    assert "const request = $('Validate Visual Design').first().json" in generator
    assert "{ ...request, ...rendered" in generator
    assert "Build Report Editorial Request" in generator
    assert "生成决策叙事 Agent" in generator
    assert "Validate Report Editorial" in generator
    assert "项目甲方、政府决策者或投资人" in generator
    assert "不得新增事实、数字、案例、承诺或因果关系" in generator
    assert "editorial_narrative: $json.editorial_narrative" in generator
    assert "[{ node: 'Build Report Editorial Request', type: 'main', index: 0 }]" in generator
    assert "[{ node: '编排空间策略报告', type: 'main', index: 0 }]" in generator
    assert "codexRelayResponse1" in generator
    assert "不是从固定模板中选图" in generator
    assert "完整项目数据包" in generator
    assert "/analysis/spatial-strategy/visuals" in generator
    assert not (WORKFLOW_ROOT / "34-analysis-visual-agent.json").exists()
    assert "/analysis/spatial-strategy/reports/compose" in generator
    assert "发送报告到飞书" in generator
    assert "发送报告到飞书？" in generator
    assert "deliver_to_feishu === true" in generator
    assert "[{ node: '发送报告到飞书', type: 'main', index: 0 }]" in generator
    assert "[{ node: 'Complete Analysis Run', type: 'main', index: 0 }]" in generator
    assert "/analysis/spatial-strategy/reports/deliver" in generator
    assert "visual_assets: $json.visual_assets ?? []" in generator
    assert "INSERT INTO analysis_reports" in generator
    assert "Complete Analysis Run" in generator


def test_hybrid_filter_treats_unclassified_chunks_as_general_material():
    sql = (ROOT / "docker" / "rag-db" / "init" / "002_hybrid_retrieval.sql").read_text(
        encoding="utf-8"
    )

    assert "cardinality(c.decision_steps)" in sql
    assert "cardinality(c.project_types)" in sql
    assert "cardinality(c.geography)" in sql
    assert "d.source_type <> 'test_fixture'" in sql

    integration = _nodes_by_name(_workflow("99-rag-integration-test.json"))
    source_code = integration["Build Test Source"]["parameters"]["jsCode"]
    recall_code = integration["Build Recall Request"]["parameters"]["jsCode"]
    assert "decision_steps: []" in source_code
    assert "decision_steps: ['step_09_spatial_layout']" in recall_code
