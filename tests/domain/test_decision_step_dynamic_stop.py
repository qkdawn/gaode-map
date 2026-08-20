from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "n8n" / "workflow-generators" / "urban-renewal-agent.workflow.mjs"


def _workflow() -> dict:
    script = f"import workflow from {json.dumps(GENERATOR.as_uri())}; process.stdout.write(JSON.stringify(workflow));"
    result = subprocess.run(
        ["node", "--input-type=module", "-"], cwd=ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8", input=script,
    )
    return json.loads(result.stdout)


def _nodes() -> dict[str, dict]:
    return {node["name"]: node for node in _workflow()["nodes"]}


def _targets(workflow: dict, node_name: str, output: int = 0) -> list[str]:
    outputs = workflow["connections"].get(node_name, {}).get("main", [])
    return [item["node"] for item in (outputs[output] if len(outputs) > output else [])]


def test_formal_workflow_delegates_agent_runtime_to_codex_harness():
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    removed_runtime_nodes = {
        "构建证据路由请求", "请求证据路由模型", "校验证据路由决策", "路由 Agent 请求工具？",
        "准备证据路由工具调用", "执行证据工具", "更新证据简报", "证据路由需要修正？",
        "工具获取达到运行边界？", "构建章节研究模型请求体", "解析章节研究模型响应",
        "构建报告章节模型请求体", "解析报告章节写作响应", "构建图件模型请求体", "解析图件模型响应",
    }
    assert removed_runtime_nodes.isdisjoint(nodes)
    harness_nodes = {
        "调用 Codex Harness 分析单元": "harness/analyze-unit",
        "调用 Codex Harness 综合方案": "harness/synthesize",
        "调用 Codex Harness 撰写章节": "harness/write-section",
        "调用 Codex Harness 设计图件": "harness/design-visuals",
    }
    for name, path in harness_nodes.items():
        node = nodes[name]
        assert node["type"] == "n8n-nodes-base.httpRequest"
        assert path in node["parameters"]["url"]
        assert node["parameters"]["options"]["timeout"] == 3_600_000
        assert node.get("retryOnFail") is not True


def test_completed_units_resume_without_recomputation():
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}
    condition = nodes["当前方向已完成？"]["parameters"]["conditions"]["conditions"][0]["leftValue"]
    assert "decision_state.steps[$json.step_key] !== undefined" in condition
    assert _targets(workflow, "当前方向已完成？", 0) == ["复用已完成章节"]
    assert _targets(workflow, "当前方向已完成？", 1) == ["标记当前方向执行中"]
    assert _targets(workflow, "复用已完成章节") == ["逐项执行分析方向"]
    assert "DELETE FROM analysis_step_outputs" not in nodes["创建或恢复分析任务"]["parameters"]["query"]


def test_completed_report_stages_resume_without_recomputation():
    workflow = _workflow()
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert _targets(workflow, "读取完整分析状态") == ["检查综合方案恢复状态"]
    assert _targets(workflow, "综合方案已完成？", 0) == ["检查报告章节恢复状态"]
    assert _targets(workflow, "综合方案已完成？", 1) == ["构建跨单元综合请求"]
    assert _targets(workflow, "报告章节已完成？", 0) == ["构建图件设计请求"]
    assert _targets(workflow, "报告章节已完成？", 1) == ["展开报告章节队列"]
    assert "completedIds" in nodes["展开报告章节队列"]["parameters"]["jsCode"]
    assert "!completedIds.has" in nodes["展开报告章节队列"]["parameters"]["jsCode"]


def test_harness_requests_keep_only_domain_inputs():
    nodes = _nodes()
    synthesis = nodes["调用 Codex Harness 综合方案"]["parameters"]["jsonBody"]
    unit = nodes["调用 Codex Harness 分析单元"]["parameters"]["jsonBody"]
    section = nodes["调用 Codex Harness 撰写章节"]["parameters"]["jsonBody"]
    assert "run_id" in synthesis and "project_question" in synthesis
    assert all(term not in synthesis for term in ("decision_state", "decision_inputs", "decision_memos", "conversation_items"))
    assert "decision_unit" in unit and "history_id" in unit
    assert all(term not in unit for term in ("tool_calls", "response_id", "conversation_items", "retry"))
    assert "solution" in section and "section" in section
    assert all(term not in section for term in ("source_unit_ids", "decision_state", "tool_name", "node_id"))


def test_research_chain_is_fixed_domain_work_not_model_governance():
    nodes = _nodes()
    builder = nodes["构建整体研究框架"]["parameters"]["jsCode"]
    workflow_json = json.dumps(_workflow(), ensure_ascii=False)
    for unit_id in (
        "current_structure", "future_role", "users_and_scenarios", "spatial_mechanisms",
        "product_and_operation", "first_phase_actions", "phasing",
    ):
        assert unit_id in builder
    assert "证据充分性" not in builder
    assert "投资前提审查" not in builder
    assert "max_output_tokens" not in workflow_json
    assert "function_call_output" not in workflow_json


def test_report_state_does_not_persist_unit_numbers_or_harness_messages():
    nodes = _nodes()
    section_validator = nodes["校验报告章节正文"]["parameters"]["jsCode"]
    cleanup = nodes["清理成功执行过程数据"]["parameters"]["jsCode"]
    assert "source_unit_ids" not in section_validator
    assert "decision_state: retainedState" in cleanup
    assert "decision_memo: item.decision_memo" in cleanup
    decision_output = nodes["校验决策备忘录"]["parameters"]["jsCode"]
    assert "named_entities: Array.isArray(memo.named_entities)" in decision_output
    for runtime_field in ("response_id", "conversation_items", "tool_calls", "route_decision"):
        assert runtime_field not in cleanup


def test_named_spatial_entities_reach_report_and_visual_consumers():
    nodes = _nodes()
    section_request = nodes["构建报告章节写作请求"]["parameters"]["jsCode"]
    visual_request = nodes["构建图件设计请求"]["parameters"]["jsCode"]

    assert "named_entities: Array.isArray(blueprint.named_entities)" in section_request
    assert "named_entities: Array.isArray(blueprint.named_entities)" in visual_request
