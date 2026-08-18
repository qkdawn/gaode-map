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
        "section": {
            "section_id": "section_01",
            "title": "功能结构判断",
            "source_unit_ids": ["du_01"],
            "owns_claims": ["形成双中心结构"],
            "must_include_facts": ["北部与南部各有一个高密度集聚"],
            "must_include_named_entities": [],
        },
        "state": {"report_sections": []},
    }
    response = {
        "output_text": json.dumps(
            {
                "section_id": "section_01",
                "title": "功能结构判断",
                "content": "北部与南部各有一个高密度集聚，形成双中心结构。",
            },
            ensure_ascii=False,
        )
    }
    script = f"""
const code = {json.dumps(code, ensure_ascii=False)};
const request = {json.dumps(request, ensure_ascii=False)};
const response = {json.dumps(response, ensure_ascii=False)};
const $input = {{ first: () => ({{ json: response }}) }};
const $ = (name) => ({{
  first: () => name === '构建报告章节写作请求' ? {{ json: request }} : {{ json: {{}} }},
}});
const result = new Function('$input', '$', code)($input, $);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=script,
    )
    result = json.loads(completed.stdout)

    assert result[0]["json"]["decision_state"]["report_sections"][0]["section_id"] == "section_01"


def test_agent_has_submit_status_and_adaptive_decision_loop():
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
    assert "lease_expires_at = NOW() + INTERVAL '45 minutes'" in claim_query
    assert "$('展开领取任务请求').first()?.json" in nodes["合并项目上下文"]["parameters"]["jsCode"]

    loops = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.splitInBatches"]
    assert [node["name"] for node in loops] == ["逐项执行分析方向", "逐节生成统一报告"]
    assert loops[0]["parameters"]["batchSize"] == 1
    queue_code = nodes["建立自适应分析队列"]["parameters"]["jsCode"]
    assert "candidateUnits" in queue_code
    assert "fallbackSteps" not in queue_code
    assert "if (!adaptiveSteps.length) throw new Error('decision_units_empty')" in queue_code
    assert "if (adaptiveSteps.length > 32) throw new Error('decision_units_exceed_safety_limit')" in queue_code
    assert ".slice(0, 32)" not in queue_code
    assert "decision_units" in queue_code
    validate_frame_code = nodes["确认整体研究框架"]["parameters"]["jsCode"]
    assert "decision_units_exceed_safety_limit" in validate_frame_code
    assert "decision_unit_decision_output_duplicate" not in validate_frame_code
    assert "map(normalizeUnit).slice(0, 32)" not in validate_frame_code
    assert _targets(workflow, "合并项目上下文") == ["构建整体研究框架"]
    assert _targets(workflow, "构建整体研究框架") == ["复用已有研究框架？"]
    assert _targets(workflow, "复用已有研究框架？", 0) == ["确认整体研究框架"]
    assert _targets(workflow, "复用已有研究框架？", 1) == ["构建研究框架请求体"]
    assert _targets(workflow, "解析研究框架响应") == ["确认整体研究框架"]
    assert _targets(workflow, "确认整体研究框架") == ["建立自适应分析队列"]
    frame_code = nodes["构建整体研究框架"]["parameters"]["jsCode"]
    assert "model: 'gpt-5.6-terra'" in frame_code
    assert CORE_AGENT_PROMPT in frame_code
    assert "每个单元只回答一个会改变项目行动的判断" in frame_code
    assert "固定章节" in frame_code
    assert "输出前自检" not in frame_code
    assert "缺失信息" not in frame_code
    assert "reuse_research_frame" in frame_code
    assert "research_frame" in queue_code
    assert "research_brief" in queue_code
    assert _targets(workflow, "逐项执行分析方向", 0) == ["读取完整分析状态"]
    assert _targets(workflow, "逐项执行分析方向", 1) == ["读取最新分析状态"]
    assert "逐项执行分析方向" in _targets(workflow, "完成当前决策单元")
    assert "逐项执行分析方向" in _targets(workflow, "复用已完成章节")
    assert "'planning'" in nodes["领取排队分析任务"]["parameters"]["query"]
    assert "'step_01_policy_site'" not in nodes["领取排队分析任务"]["parameters"]["query"]


def test_agent_uses_independent_on_demand_evidence_tools():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    nodes = _nodes(workflow)
    assert not any(name in nodes for name in (
        "构建公共证据检索请求",
        "检索公共证据原文",
        "构建 GraphRAG 文献问题",
        "调用 GraphRAG 文献检索",
        "整理 GraphRAG 文献证据",
    ))
    assert _targets(workflow, "标记当前方向执行中") == ["构建证据路由请求"]
    assert not any(name in nodes for name in (
        "选择首个项目文档",
        "存在项目文档？",
        "预读项目文档正文",
        "注入项目文档正文",
    ))

    for name in ("请求章节研究模型", "请求跨单元综合模型", "请求报告章节写作模型", "请求图件设计模型", "请求报告叙事模型"):
        assert nodes[name]["parameters"]["url"] == "__CODEX_RELAY_BASE_URL__/responses"
        assert nodes[name]["parameters"]["options"]["timeout"] >= 300_000
    assert nodes["请求证据路由模型"]["parameters"]["url"] == "__CODEX_RELAY_BASE_URL__/responses"
    assert nodes["请求证据路由模型"]["parameters"]["options"]["timeout"] == 120_000
    assert nodes["请求证据路由模型"]["maxTries"] == 2

    chapter_code = nodes["构建证据路由请求"]["parameters"]["jsCode"]
    assert "const state = $('校验当前分析方向').first().json" in chapter_code
    assert "model: 'gpt-5.6-terra'" in chapter_code
    follow_up = nodes["更新证据简报"]["parameters"]["jsCode"]
    route_validation_code = nodes["校验证据路由决策"]["parameters"]["jsCode"]
    assert all(tool in chapter_code for tool in (
        "search_literature_evidence",
        "analyze_spatial_evidence",
        "read_project_document",
        "search_public_web",
        "fetch_public_web_page",
    ))
    assert "project_context'" not in chapter_code
    assert "query_data'" not in chapter_code
    assert "project_documents" in chapter_code
    assert "project_document_prefetch" not in chapter_code
    assert "tool_choice: { type: 'function'" not in chapter_code
    assert CORE_AGENT_PROMPT in chapter_code
    assert "根据当前问题选择项目原文、空间分析、规划文献或公开网页查询" in chapter_code
    assert "research_frame:" in chapter_code
    assert "decision_unit: decisionUnit" in chapter_code
    assert "previous_decision_memos: previousDecisionMemos" in chapter_code
    assert "poi.count" in chapter_code
    assert "population.total" in chapter_code
    assert "road.network_size" in chapter_code
    assert "nightlight.mean_radiance" in chapter_code
    assert "真实客流" not in chapter_code
    assert "付费意愿" not in chapter_code
    assert "运营商承诺" not in chapter_code
    assert "不为了遍历工具而调用" in chapter_code
    assert "research_summary" not in chapter_code
    assert "key_findings" not in chapter_code
    assert "tensions" not in chapter_code
    assert "ready_to_write" not in chapter_code
    assert "decision: { type: 'string', enum: ['continue', 'finish'] }" in chapter_code
    assert "name: 'evidence_route'" in chapter_code
    assert "enum: ['scope', 'accessibility', 'direction', 'neighborhood', 'rank', 'relationship', 'inspect']" in chapter_code
    assert "initial_context_items" in chapter_code
    assert "working_research_brief" in chapter_code
    assert "research_result_store" in chapter_code
    assert "evidence_claims" not in chapter_code
    assert "context_budget" in follow_up
    assert "no_new_evidence" in follow_up
    assert "evidence_tool_execution_failed" in follow_up
    assert "tool_errors" not in follow_up
    assert "emergency_cap" not in follow_up
    assert "tool_choice: 'none'" in follow_up
    assert "tool_call_limit" in follow_up
    assert "next_tools: { type: 'array', maxItems: 3" in chapter_code
    assert "execution_budget" in chapter_code
    assert "batch_index" in follow_up
    assert "需要前序结果才能确定参数的查询留到下一轮" in chapter_code
    assert "record_refs 只允许出现在 neighborhood 或 inspect" in route_validation_code
    assert "relationship再inspect" not in chapter_code
    assert "evidence_route_continue_after_stop" not in route_validation_code
    assert "tool_acquisition_stopped" not in route_validation_code
    assert nodes["执行证据工具"]["onError"] == "continueErrorOutput"
    assert _targets(workflow, "执行证据工具", 0) == ["更新证据简报"]
    assert _targets(workflow, "执行证据工具", 1) == ["记录任务失败"]
    assert "记录项目工具调用失败" not in nodes
    assert "duplicate_request" in follow_up
    assert "tool_request_fingerprints" in follow_up
    assert "projectSpatialValue" in follow_up
    assert "briefCard" in follow_up
    assert "compactSpatialResult" in follow_up
    assert "projectNamedSpatialRecords" in follow_up
    assert "named_spatial_records" in follow_up
    assert "named_record_refs" in follow_up
    assert "candidate = { tool_name: entry.tool_name, call_id: entry.call_id, is_error: entry.is_error, batch_index: entry.batch_index, result: { status:" in follow_up
    assert "if (entry.tool_name === 'analyze_spatial_evidence')" in follow_up
    assert "pending_expansions" not in follow_up
    assert "latest_tool_results" in follow_up
    assert "function_call_output" not in follow_up
    assert "nextMandatoryWebTool" not in follow_up
    assert "const forceFinal = turn >= 6" not in follow_up
    assert "context_budget_tokens: 24000" in chapter_code
    assert "no_new_evidence_limit: 2" in chapter_code
    assert "public_knowledge_retrieval" not in chapter_code
    assert "工具不可用时不得假装成功" not in chapter_code
    assert _targets(workflow, "解析证据路由响应") == ["校验证据路由决策"]
    assert _targets(workflow, "校验证据路由决策") == ["证据路由需要修正？"]
    assert _targets(workflow, "证据路由需要修正？", 0) == ["构建证据路由请求体"]
    assert _targets(workflow, "证据路由需要修正？", 1) == ["路由 Agent 请求工具？"]
    assert _targets(workflow, "路由 Agent 请求工具？", 0) == ["准备证据路由工具调用"]
    assert _targets(workflow, "路由 Agent 请求工具？", 1) == ["构建章节研究分析请求"]
    assert _targets(workflow, "构建章节研究分析请求") == ["构建章节研究模型请求体"]
    assert _targets(workflow, "解析章节研究模型响应") == ["校验决策备忘录"]
    assert "构建独立章节成稿请求" not in nodes
    assert "请求独立章节成稿模型" not in nodes
    assert "深化章节判断" not in nodes
    assert "请求深化分析模型" not in nodes
    assert _targets(workflow, "更新证据简报") == ["恢复章节工具上下文"]
    assert _targets(workflow, "恢复章节工具上下文") == ["刷新分析任务租约"]
    assert _targets(workflow, "刷新分析任务租约") == ["恢复路由请求上下文"]
    assert _targets(workflow, "恢复路由请求上下文") == ["工具获取达到运行边界？"]
    assert _targets(workflow, "工具获取达到运行边界？", 0) == ["记录任务失败"]
    assert _targets(workflow, "工具获取达到运行边界？", 1) == ["构建证据路由请求体"]
    assert "按现有证据继续分析" not in nodes["恢复路由请求上下文"]["parameters"]["jsCode"]
    assert "按现有证据继续分析" not in route_validation_code

    research_code = nodes["构建章节研究分析请求"]["parameters"]["jsCode"]
    assert "working_research_brief: brief" in research_code
    assert "tools: []" in research_code
    assert "name: 'decision_memo'" in research_code
    assert "reasoning: { effort: 'medium' }" in research_code
    assert CORE_AGENT_PROMPT in research_code
    assert "明确判断、关键依据和行动建议" in research_code
    assert "Harness" not in research_code
    assert "状态码" not in research_code
    assert "evidence_boundary" not in research_code

    for name in ("构建整体研究框架", "请求研究框架模型", "确认整体研究框架", "校验当前分析方向", "构建证据路由请求", "请求证据路由模型", "构建章节研究分析请求", "请求章节研究模型", "校验决策备忘录", "保存决策备忘录与分析状态", "构建跨单元综合请求", "请求跨单元综合模型", "校验报告蓝图", "生成最终报告"):
        assert nodes[name]["onError"] == "continueErrorOutput"
        assert "记录任务失败" in _targets(workflow, name, 1)
    assert workflow["settings"]["executionTimeout"] == 14400
    assert "citations = COALESCE" in nodes["保存决策备忘录与分析状态"]["parameters"]["query"]
    assert "jsonb_set" in nodes["保存决策备忘录与分析状态"]["parameters"]["query"]
    assert "run.decision_state->'steps'" in nodes["保存决策备忘录与分析状态"]["parameters"]["query"]
    assert "heartbeat_at = NOW()" in nodes["标记当前方向执行中"]["parameters"]["query"]
    assert "completed_steps" in nodes["读取最新分析状态"]["parameters"]["query"]
    assert "analysis_step_outputs" in nodes["读取最新分析状态"]["parameters"]["query"]
    assert "steps: { ...completedSteps" in nodes["合并当前分析方向状态"]["parameters"]["jsCode"]
    assert "jsonb_object_agg(step.step, step.output)" in nodes["读取完整分析状态"]["parameters"]["query"]
    follow_up_code = nodes["更新证据简报"]["parameters"]["jsCode"]
    restore_tool_context_code = nodes["恢复章节工具上下文"]["parameters"]["jsCode"]
    tool_prepare_code = nodes["准备证据路由工具调用"]["parameters"]["jsCode"]
    tool_http_code = json.dumps(nodes["执行证据工具"]["parameters"], ensure_ascii=False)
    assert "mcp_request_body" in tool_prepare_code
    assert "stop_reason: current.stop_reason ?? baseState.stop_reason" in restore_tool_context_code
    assert "SET heartbeat_at = NOW()" in nodes["刷新分析任务租约"]["parameters"]["query"]
    assert "SET decision_state" not in nodes["刷新分析任务租约"]["parameters"]["query"]
    assert "stop_reason: state.stop_reason ?? null" in nodes["构建证据路由请求"]["parameters"]["jsCode"]
    assert "evidence_boundary" not in nodes["构建章节研究分析请求"]["parameters"]["jsCode"]
    assert "const state = routed.state" in nodes["构建章节研究分析请求"]["parameters"]["jsCode"]
    assert "JSON.stringify" in tool_prepare_code
    assert "return calls.map" in tool_prepare_code
    assert "parallel_agent_tool_calls_not_supported" not in tool_prepare_code
    assert nodes["执行证据工具"]["type"] == "n8n-nodes-base.httpRequest"
    assert "JSON.parse($json.mcp_request_body)" in tool_http_code
    assert "Promise.allSettled" not in tool_http_code
    assert nodes["执行证据工具"]["parameters"]["options"]["timeout"] == 180000
    assert nodes["执行证据工具"]["onError"] == "continueErrorOutput"
    assert "completed_chapters" not in tool_prepare_code
    assert "read_previous_chapter" not in tool_prepare_code
    assert "$('构建证据路由请求').first().json" in tool_prepare_code
    assert "$('准备证据路由工具调用').first().json" in follow_up_code
    assert "const items = $input.all()" in follow_up_code
    assert "normalizedResults = items.map" in follow_up_code
    assert ".item.json" not in tool_prepare_code
    assert ".item.json" not in follow_up_code
    validation_code = nodes["校验决策备忘录"]["parameters"]["jsCode"]
    blueprint_validation_code = nodes["校验报告蓝图"]["parameters"]["jsCode"]
    assert "entry.tool_name === 'read_project_document'" in follow_up_code
    assert "entry.tool_name === 'analyze_spatial_evidence'" in follow_up_code
    assert "compactSpatialAttributes" in follow_up_code
    assert "attributes: compactSpatialAttributes(item.attributes)" in follow_up_code
    assert "entry.tool_name === 'fetch_public_web_page'" in follow_up_code
    assert "entry.tool_name === 'search_literature_evidence'" in follow_up_code
    assert "public_knowledge_graphrag" in follow_up_code
    assert "source_type: 'public_web_fulltext'" in follow_up_code
    assert "nextMandatoryWebTool" not in follow_up_code
    assert "public_web_no_candidates" not in follow_up_code
    assert "tool_evidence: toolEvidence" in follow_up_code
    assert "latest_tool_results: latestToolResults" in follow_up_code
    assert "working_research_brief: current.working_research_brief" in restore_tool_context_code
    assert "tool_evidence: current.tool_evidence" in restore_tool_context_code
    assert "response.tool_evidence" in validation_code
    assert "decisionMemo" in validation_code
    assert "decision_memo_required_content_missing" in validation_code
    assert "namedEntities" in validation_code
    assert "decision_brief" not in validation_code
    assert "reader_chapter" not in validation_code
    assert "live_web_fulltext_count" in validation_code
    assert "literature_evidence_count" in validation_code
    assert "dual_source_status" not in validation_code
    assert "public_context_count" not in validation_code
    assert "reader_chapter_missing_evidence_context" not in validation_code
    assert "reader_chapter_missing_conditions" not in validation_code
    assert "canonicalFact" not in blueprint_validation_code
    assert "must_include_facts" not in blueprint_validation_code
    assert "canonicalName" not in blueprint_validation_code
    assert "must_include_named_entities" not in blueprint_validation_code
    assert "const logicByUnitId = new Map()" in blueprint_validation_code
    assert "memo?.decision" in blueprint_validation_code
    assert "report_blueprint_decision_logic_incomplete" in blueprint_validation_code
    assert "blueprint.decision_logic = decisionLogic" in blueprint_validation_code
    assert "report_blueprint_fact_not_in_memos" not in blueprint_validation_code
    blueprint_request_code = nodes["构建跨单元综合请求"]["parameters"]["jsCode"]
    assert "const memoByUnitId = new Map" in blueprint_request_code
    assert "decisionMemos.length !== units.length" in blueprint_request_code
    assert "刷新分析任务租约" in nodes
    assert "刷新报告阶段租约" in nodes
    assert _targets(workflow, "生成 Word 报告并发送飞书") == ["恢复已发送报告上下文"]
    assert _targets(workflow, "恢复已发送报告上下文") == ["清理成功执行过程数据"]
    assert _targets(workflow, "需要发送飞书？", 1) == ["清理成功执行过程数据"]
    assert _targets(workflow, "清理成功执行过程数据") == ["完成分析任务"]
    cleanup_code = nodes["清理成功执行过程数据"]["parameters"]["jsCode"]
    for transient_key in (
        "research_result_store",
        "working_research_brief",
        "latest_tool_results",
        "tool_evidence",
        "tool_diagnostics",
        "route_diagnostics",
        "tool_request_fingerprints",
        "tool_result_fingerprints",
        "conversation_items",
    ):
        assert transient_key in cleanup_code
    assert "['content', 'text', 'raw', 'body']" in cleanup_code
    assert "decision_state: retainedState" in cleanup_code
    assert "report_blueprint:" in cleanup_code
    assert "report_sections:" in cleanup_code
    assert "decision_memo: item.decision_memo" in cleanup_code
    assert _targets(workflow, "更新证据简报") == ["恢复章节工具上下文"]
    assert _targets(workflow, "恢复章节工具上下文") == ["刷新分析任务租约"]
    assert _targets(workflow, "刷新分析任务租约") == ["恢复路由请求上下文"]
    assert _targets(workflow, "恢复路由请求上下文") == ["工具获取达到运行边界？"]
    assert _targets(workflow, "刷新报告阶段租约") == ["恢复报告图件上下文"]
    assert _targets(workflow, "恢复报告图件上下文") == ["构建报告叙事请求"]


def test_agent_prompts_use_one_domain_contract_without_internal_process_requirements():
    workflow = _generated("urban-renewal-agent.workflow.mjs")
    nodes = _nodes(workflow)
    prompt_nodes = (
        "构建整体研究框架",
        "构建证据路由请求",
        "构建章节研究分析请求",
        "构建跨单元综合请求",
        "构建报告章节写作请求",
        "构建报告叙事请求",
    )
    prompt_code = {name: nodes[name]["parameters"]["jsCode"] for name in prompt_nodes}
    for code in prompt_code.values():
        assert CORE_AGENT_PROMPT in code
        assert "事实—代理—未知" not in code
        assert "完整披露" not in code
        assert "输出前自检" not in code
        assert "Harness" not in code

    for name in ("构建报告章节写作请求", "构建报告叙事请求"):
        code = prompt_code[name]
        assert "逐字" not in code
        assert "忠实保留" not in code
        assert "工具过程" not in code
        assert "状态码" not in code
        assert "决策单元编号" not in code
        assert "工作流状态" not in code


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
    assert _targets(workflow, "生成最终报告") == ["规范化最终报告响应"]
    assert _targets(workflow, "规范化最终报告响应") == ["需要发送飞书？"]
    normalize_report_code = nodes["规范化最终报告响应"]["parameters"]["jsCode"]
    assert "final_report_markdown_missing" in normalize_report_code
    assert "current.body" in normalize_report_code and "current.data" in normalize_report_code
    section_writer_code = nodes["构建报告章节写作请求"]["parameters"]["jsCode"]
    assert CORE_AGENT_PROMPT in section_writer_code
    assert "source_analyses: sourceAnalyses" in section_writer_code
    assert "judgment:" in section_writer_code
    assert "basis:" in section_writer_code
    assert "actions:" in section_writer_code
    assert "internalPatterns" not in nodes["校验报告章节正文"]["parameters"]["jsCode"]
    assert "reference_only_conclusions" not in section_writer_code
    assert "owns_claims" not in section_writer_code
    assert "must_include_facts" not in section_writer_code
    assert "must_include_named_entities" not in section_writer_code
    assert "completed_sections" not in section_writer_code
    assert "report_blueprint: state.report_blueprint" not in section_writer_code
    assert "/analysis/spatial-strategy/visuals" in nodes["生成项目数据图件"]["parameters"]["url"]
    assert "/analysis/spatial-strategy/reports/deliver" in nodes["生成 Word 报告并发送飞书"]["parameters"]["url"]
    editorial_code = nodes["构建报告叙事请求"]["parameters"]["jsCode"]
    assert CORE_AGENT_PROMPT in editorial_code
    assert "narrative" in editorial_code
    assert "判断、依据和行动建议" in editorial_code
    assert "section_edits" not in editorial_code
    assert "remove_exact" not in editorial_code
    assert "term_replacements" not in editorial_code
    assert "reasoning: { effort: 'high' }" in editorial_code
    editorial_validation_code = nodes["校验报告叙事"]["parameters"]["jsCode"]
    assert "editorial_narrative: narrative" in editorial_validation_code
    assert "section_edits" not in editorial_validation_code
    assert "remove_exact" not in editorial_validation_code
    assert "term_replacements" not in editorial_validation_code
    visual_code = nodes["构建图件设计请求"]["parameters"]["jsCode"]
    assert "decision_memos" in visual_code
    assert "evidence_status" not in visual_code
    assert "evidence_count" not in visual_code
    visual_validation_code = nodes["校验图件设计"]["parameters"]["jsCode"]
    assert "suppliedVisuals.filter" in visual_validation_code
    assert "visual_plan_items_dropped" in visual_validation_code
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
