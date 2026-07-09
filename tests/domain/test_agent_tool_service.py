import asyncio
import logging

from modules.agent.schemas import AnalysisSnapshot, PlanStep, ToolResult, ToolSpec
from modules.agent.tool_service import run_registered_tool
from modules.agent.tools import RegisteredTool


def test_run_registered_tool_executes_via_executor_and_returns_trace():
    seen = {}

    async def runner(*, arguments, snapshot, artifacts, question):
        seen["arguments"] = dict(arguments)
        seen["scope_polygon"] = artifacts.get("scope_polygon")
        seen["question"] = question
        return ToolResult(
            tool_name="shared_tool",
            status="success",
            result={"ok": True},
            artifacts={"shared_artifact": {"ready": True}},
        )

    registered = RegisteredTool(
        spec=ToolSpec(
            name="shared_tool",
            description="Shared execution test tool",
            category="action",
            layer="L1",
            requires=["scope_polygon"],
            input_schema={
                "type": "object",
                "properties": {"mode": {"type": "string"}},
                "additionalProperties": False,
            },
            produces=["shared_artifact"],
        ),
        runner=runner,
    )

    execution = asyncio.run(
        run_registered_tool(
            step=PlanStep(tool_name="shared_tool", arguments={"mode": "test"}),
            snapshot=AnalysisSnapshot(
                scope={
                    "polygon": [
                        [112.98, 28.19],
                        [112.99, 28.19],
                        [112.99, 28.20],
                        [112.98, 28.20],
                        [112.98, 28.19],
                    ]
                }
            ),
            artifacts={},
            question="run shared tool",
            registry={"shared_tool": registered},
        )
    )

    assert execution.registered_tool is registered
    assert execution.result.status == "success"
    assert execution.result.result == {"ok": True}
    assert execution.trace.tool_name == "shared_tool"
    assert execution.trace.status == "success"
    assert seen["arguments"] == {"mode": "test"}
    assert seen["question"] == "run shared tool"
    assert seen["scope_polygon"][0] == [112.98, 28.19]


def test_run_registered_tool_logs_audit_record(caplog):
    async def runner(*, arguments, snapshot, artifacts, question):
        del arguments, snapshot, artifacts, question
        return ToolResult(tool_name="logged_tool", status="success", result={"ok": True})

    registered = RegisteredTool(
        spec=ToolSpec(
            name="logged_tool",
            description="Logged execution test tool",
            category="information",
            layer="L1",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            readonly=True,
            cost_level="safe",
            risk_level="safe",
        ),
        runner=runner,
    )

    with caplog.at_level(logging.INFO, logger="modules.agent.tool_service"):
        execution = asyncio.run(
            run_registered_tool(
                step=PlanStep(tool_name="logged_tool"),
                snapshot=AnalysisSnapshot(),
                artifacts={},
                question="",
                registry={"logged_tool": registered},
                caller="internal",
            )
        )

    assert execution.result.status == "success"
    assert any(
        "agent_tool_call caller=internal tool=logged_tool status=success" in record.message
        for record in caplog.records
    )


def test_run_registered_tool_logs_unknown_tool(caplog):
    with caplog.at_level(logging.WARNING, logger="modules.agent.tool_service"):
        try:
            asyncio.run(
                run_registered_tool(
                    step=PlanStep(tool_name="missing_tool"),
                    snapshot=AnalysisSnapshot(),
                    artifacts={},
                    question="",
                    registry={},
                )
            )
        except KeyError:
            pass

    assert any(
        "agent_tool_call caller=internal tool=missing_tool status=unknown" in record.message
        for record in caplog.records
    )
