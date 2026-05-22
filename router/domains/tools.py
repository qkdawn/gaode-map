from __future__ import annotations

from typing import List

from fastapi import APIRouter, Security

from modules.agent.schemas import AgentToolSummary, ToolResult
from modules.agent.tool_service import ExternalToolRunRequest, list_external_tools, run_external_tool
from router.utils.deps import verify_api_key

router = APIRouter(prefix="/api/v1/tools", tags=["external-tools"])


@router.get("", response_model=List[AgentToolSummary])
async def get_external_tools(_api_key_valid: bool = Security(verify_api_key)):
    return list_external_tools()


@router.post("/{tool_name}/run", response_model=ToolResult)
async def run_external_tool_api(
    tool_name: str,
    payload: ExternalToolRunRequest,
    _api_key_valid: bool = Security(verify_api_key),
):
    return await run_external_tool(tool_name, payload)
