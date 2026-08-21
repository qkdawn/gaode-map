from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CodexHarnessError(RuntimeError):
    pass


def _contains_unavailable_source(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("error") == "data_source_unavailable":
            return True
        return any(_contains_unavailable_source(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_unavailable_source(item) for item in value)
    return value == "data_source_unavailable"


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=False, exclude_none=True)
    return value if isinstance(value, dict) else {}


def _mcp_failure(items: list[Any]) -> str:
    for item in items:
        payload = _model_payload(item)
        if payload.get("type") != "mcpToolCall":
            continue
        error = payload.get("error")
        status = str(payload.get("status") or "")
        if not error and status not in {"failed", "declined"}:
            continue
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "")
        else:
            detail = str(error or "")
        return detail.strip() or "mcp_tool_failed"
    return ""


def _sdk_config(enabled_tools: list[str]) -> CodexConfig:
    tool_allowlist = json.dumps(enabled_tools, ensure_ascii=True, separators=(",", ":"))
    return CodexConfig(
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        config_overrides=(
            "features.tool_suggest=false",
            f"mcp_servers.spatial-project.enabled_tools={tool_allowlist}",
            "mcp_servers.spatial-project.required=true",
        ),
    )


def run_codex(*, prompt: str, schema_path: Path, enabled_tools: list[str]) -> dict:
    """Run one domain task through Codex Harness with a constrained MCP surface."""

    try:
        output_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexHarnessError("codex_harness_invalid_schema") from exc
    if not isinstance(output_schema, dict):
        raise CodexHarnessError("codex_harness_invalid_schema")

    try:
        with Codex(_sdk_config(enabled_tools)) as codex:
            thread = codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                cwd=str(PROJECT_ROOT),
                ephemeral=True,
                sandbox=Sandbox.full_access,
                service_name="gaode-map-spatial-strategy",
            )
            turn = thread.run(prompt, output_schema=output_schema)
    except Exception as exc:
        detail = str(exc).strip()[-1200:] or exc.__class__.__name__
        if "data_source_unavailable" in detail:
            raise CodexHarnessError("data_source_unavailable") from exc
        raise CodexHarnessError(f"codex_harness_failed: {detail}") from exc

    tool_failure = _mcp_failure(turn.items)
    if tool_failure:
        if "data_source_unavailable" in tool_failure:
            raise CodexHarnessError("data_source_unavailable")
        raise CodexHarnessError(f"codex_harness_failed: {tool_failure[-1200:]}")

    try:
        result = json.loads(turn.final_response or "")
    except json.JSONDecodeError as exc:
        raise CodexHarnessError("codex_harness_invalid_output") from exc
    if not isinstance(result, dict):
        raise CodexHarnessError("codex_harness_invalid_output")
    if _contains_unavailable_source(result):
        raise CodexHarnessError("data_source_unavailable")
    return result
