from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "n8n" / "workflow-generators" / "urban-renewal-agent.workflow.mjs"


def _workflow() -> dict:
    script = f"import workflow from {json.dumps(GENERATOR.as_uri())}; process.stdout.write(JSON.stringify(workflow));"
    result = subprocess.run(["node", "--input-type=module", "-"], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", input=script)
    return json.loads(result.stdout)


def _nodes() -> dict[str, dict]:
    return {node["name"]: node for node in _workflow()["nodes"]}


def _targets(workflow: dict, node_name: str, output: int = 0) -> list[str]:
    outputs = workflow["connections"].get(node_name, {}).get("main", [])
    return [item["node"] for item in (outputs[output] if len(outputs) > output else [])]


def test_workflow_has_only_unit_and_visual_harness_calls():
    workflow = _workflow()
    nodes = _nodes()

    assert "harness/analyze-unit" in nodes["调用 Codex Harness 分析单元"]["parameters"]["url"]
    assert "harness/design-visuals" in nodes["调用 Codex Harness 设计图件"]["parameters"]["url"]
    assert not any("harness/synthesize" in json.dumps(node) for node in workflow["nodes"])
    assert not any("harness/write-section" in json.dumps(node) for node in workflow["nodes"])
    assert "综合方案已完成？" not in nodes
    assert "逐节生成统一报告" not in nodes


def test_completed_chapter_resumes_from_its_persisted_output():
    workflow = _workflow()
    nodes = _nodes()
    validation = nodes["校验当前分析方向"]["parameters"]["jsCode"]
    condition = nodes["当前方向已完成？"]["parameters"]["conditions"]["conditions"][0]["leftValue"]

    assert "Object.keys(candidate).sort()" in validation
    assert "candidate.unit_id" in validation and "candidate.title" in validation
    assert "无法生成本章节" in validation and "无法完成本章节" in validation
    assert "Array.isArray(candidate.citations)" in validation
    assert "existing_output !== null" in condition
    assert _targets(workflow, "当前方向已完成？", 0) == ["复用已完成章节"]
    assert _targets(workflow, "当前方向已完成？", 1) == ["标记当前方向执行中"]
    assert "step.step = $1::jsonb->>'step_key'" in nodes["读取最新分析状态"]["parameters"]["query"]
    assert "DELETE FROM analysis_step_outputs" not in nodes["创建或恢复分析任务"]["parameters"]["query"]


def test_unit_output_persists_only_four_chapter_fields():
    nodes = _nodes()
    validator = nodes["校验策略章节"]["parameters"]["jsCode"]
    persist = nodes["保存策略章节"]["parameters"]["query"]
    cleanup = nodes["清理成功执行过程数据"]["parameters"]["jsCode"]

    assert "['citations', 'content', 'title', 'unit_id']" in validator
    assert "const output = { unit_id: unitId, title, content, citations: result.citations }" in validator
    assert "payload.value->'output'->'citations'" in persist
    for removed in ("decision_result", "decision_memo", "report_blueprint", "report_sections"):
        assert removed not in validator
        assert removed not in cleanup


def test_research_chain_contains_audience_but_no_market_flow_or_skill_dispatch():
    builder = _nodes()["构建整体研究框架"]["parameters"]["jsCode"]
    expected = (
        "project_basis", "regional_role", "supply_gap", "audience_use", "theme_resources",
        "positioning", "product_mix", "spatial_layout", "operating_model", "investment_operation", "phasing",
    )
    for unit_id in expected:
        assert unit_id in builder
    assert "客群与使用" in builder
    assert "market_flow" not in builder
    assert "市场流向" not in builder
    assert "client-decision-" not in builder
    assert "skill_id" not in builder


def test_final_report_reads_ordered_chapters_once_from_step_outputs():
    workflow = _workflow()
    nodes = _nodes()
    query = nodes["读取完整分析状态"]["parameters"]["query"]
    visual_request = nodes["构建图件设计请求"]["parameters"]["jsCode"]
    compose_body = nodes["生成最终报告"]["parameters"]["jsonBody"]

    assert "jsonb_agg(step.output ORDER BY step.step_order" in query
    assert _targets(workflow, "读取完整分析状态") == ["构建图件设计请求"]
    assert "strategy_report_requires_all_chapters" in visual_request
    assert "chapters" in compose_body
    assert "decision_state" not in compose_body
    assert "editorial_narrative" not in compose_body
