from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "n8n" / "workflow-components" / "decision-step.json"


def _code(name: str) -> str:
    workflow = json.loads(COMPONENT.read_text(encoding="utf-8"))
    return next(node for node in workflow["nodes"] if node["name"] == name)["parameters"]["jsCode"]


def _workflow() -> dict:
    return json.loads(COMPONENT.read_text(encoding="utf-8"))


def _run_follow_up(prior: dict, tool_result: dict) -> dict:
    script = f"""
const code = {json.dumps(_code('Build MCP Agent Follow-up'), ensure_ascii=False)};
const prior = {json.dumps(prior, ensure_ascii=False)};
const toolResult = {json.dumps(tool_result, ensure_ascii=False)};
const run = new Function('$input', '$', code);
const output = run({{ all: () => [{{ json: toolResult }}], first: () => ({{ json: toolResult }}) }}, () => ({{ all: () => [{{ json: prior }}], first: () => ({{ json: prior }}) }}));
process.stdout.write(JSON.stringify(output[0].json));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def _prior(**overrides: object) -> dict:
    return {
        "conversation_items": [{"role": "user", "content": [{"type": "input_text", "text": "question"}]}],
        "output": [{"type": "function_call", "call_id": "call-1", "name": "project_context"}],
        "mcp_call_id": "call-1",
        "mcp_tool_name": "project_context",
        "agent_turn": 1,
        "usage": {"total_tokens": 1000},
        "instructions": "write chapter",
        "tools": [{"type": "function", "name": "project_context"}],
        "text": {"format": {"type": "json_schema"}},
        "tool_result_fingerprints": [],
        "stale_tool_turns": 0,
        "tool_error_count": 0,
        **overrides,
    }


def test_decision_agent_uses_dynamic_stop_conditions_instead_of_six_turn_limit():
    request = _code("Build Structured Decision Request")
    follow_up = _code("Build MCP Agent Follow-up")

    assert "parallel_tool_calls: false" in request
    assert "context_budget_tokens: 24000" in request
    assert "context_reserve_tokens: 6000" in request
    assert "no_new_evidence_limit: 2" in request
    assert "tool_error_limit: 2" in request

    assert "const forceFinal = turn >= 6" not in follow_up
    assert "context_budget" in follow_up
    assert "no_new_evidence" in follow_up
    assert "tool_errors" in follow_up
    assert "emergency_cap" not in follow_up
    assert "tool_choice: resolvedStopReason ? 'none' : undefined" in follow_up
    assert "tools: resolvedStopReason ? [] : prior.tools" in follow_up


def test_dynamic_stop_code_nodes_compile_and_task_completion_exits_tool_loop():
    codes = [
        _code("Build Structured Decision Request"),
        _code("Prepare MCP Agent Tool Call"),
        _code("Build MCP Agent Follow-up"),
    ]
    script = "\n".join(
        f"new Function('$input', '$', 'return (async () => {{\\n' + {json.dumps(code)} + '\\n}})();');"
        for code in codes
    )
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)

    connections = _workflow()["connections"]["Agent Has Tool Calls"]["main"]
    assert connections[1][0]["node"] == "Validate Decision Output"


def test_parallel_tool_contract_preserves_multiple_calls():
    prepare = _code("Prepare MCP Agent Tool Call")

    assert "return calls.map" in prepare
    assert "parallel_agent_tool_calls_not_supported" not in prepare
    assert "tool_call_count: Number(response.tool_call_count ?? 0) + calls.length" in prepare


def test_evidence_fingerprint_is_recursive_and_context_estimate_covers_request_state():
    follow_up = _code("Build MCP Agent Follow-up")

    assert "Array.isArray(value)" in follow_up
    assert "Object.keys(value).sort()" in follow_up
    assert "usage.total_tokens" in follow_up
    assert "instructions: prior.instructions" in follow_up
    assert "tools: prior.tools" in follow_up
    assert "text: prior.text" in follow_up


def test_new_evidence_keeps_tools_available():
    output = _run_follow_up(_prior(), {"tool_name": "project_context", "structured_content": {"datasets": ["poi"]}})

    assert output["stop_reason"] is None
    assert output["tools"] == [{"type": "function", "name": "project_context"}]
    assert output["stale_tool_turns"] == 0


def test_context_budget_stops_tool_loop():
    output = _run_follow_up(
        _prior(usage={"total_tokens": 18_000}),
        {"tool_name": "project_context", "structured_content": {"datasets": ["poi"]}},
    )

    assert output["stop_reason"] == "context_budget"
    assert output["tool_choice"] == "none"
    assert output["tools"] == []


def test_repeated_evidence_stops_after_configured_stale_limit():
    tool_result = {"tool_name": "project_context", "structured_content": {"datasets": ["poi"]}}
    first = _run_follow_up(_prior(), tool_result)
    second = _run_follow_up(
        _prior(tool_result_fingerprints=first["tool_result_fingerprints"], stale_tool_turns=1),
        tool_result,
    )

    assert second["stop_reason"] == "no_new_evidence"
    assert second["tools"] == []


def test_repeated_tool_errors_stop_the_loop():
    output = _run_follow_up(
        _prior(tool_error_count=1),
        {"tool_name": "project_context", "is_error": True, "content": "unavailable"},
    )

    assert output["stop_reason"] == "tool_errors"
    assert output["tools"] == []
