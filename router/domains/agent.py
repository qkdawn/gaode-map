import json
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from modules.agent.analysis_run_service import (
    get_analysis_run,
    list_analysis_runs,
)
from modules.agent.analysis_runs import (
    AnalysisRun,
    AnalysisRunDetail,
)
from modules.agent.capability_guidance import (
    CapabilityWorkbenchOverview,
    build_capability_workbench_overview,
)
from modules.agent.capability_catalog import (
    AnalysisCapability,
    CapabilityReadiness,
    evaluate_capability_readiness,
    list_analysis_capabilities,
)
from modules.agent.capability_intent import (
    CapabilityIntentRequest,
    CapabilityIntentResolution,
    resolve_capability_intent,
)
from modules.agent.schemas import (
    AgentIterationNightlightRequest,
    AgentIterationNightlightResponse,
    AgentIterationPoiBuildRequest,
    AgentIterationPoiBuildResponse,
    AgentIterationPoiRequest,
    AgentIterationPoiResponse,
    AgentSiteSelectionRequest,
    AgentSiteSelectionResponse,
    AgentSummaryStreamEvent,
    AgentToolSummary,
    AgentSummaryReadinessResponse,
    AgentSummaryRequest,
    AgentTurnRequest,
)
from modules.agent.iteration_change_service import (
    generate_nightlight_iteration_analysis,
    generate_poi_iteration_analysis,
)
from modules.agent.poi_iteration_build_service import build_agent_poi_iteration_payload
from modules.agent.prompt_registry import (
    PromptConfig,
    PromptUpdateRequest,
    get_prompt_config,
    list_prompt_configs,
    update_prompt_config,
)
from modules.agent.summary_service import (
    evaluate_summary_readiness,
    stream_generate_summary_pack,
)
from modules.agent.site_selection_service import generate_site_selection_pack
from modules.agent.tool_service import list_agent_tools
from modules.agent_conversation import (
    ConversationSessionDetail,
    ConversationSessionMetadataPatch,
    ConversationSessionSummary,
    ConversationTurnRequest,
    codex_conversation_service,
)
from store.analysis_run_storage import AnalysisRunStorageError
from store.history_repo import history_repo

router = APIRouter()
logger = logging.getLogger(__name__)


def _encode_sse(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _encode_summary_sse(event: AgentSummaryStreamEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"


@router.get(
    "/api/v1/analysis/agent/analysis-capabilities",
    response_model=List[AnalysisCapability],
)
async def get_analysis_capabilities():
    return await run_in_threadpool(list_analysis_capabilities)


@router.post(
    "/api/v1/analysis/agent/analysis-capabilities/resolve-intent",
    response_model=CapabilityIntentResolution,
)
async def post_analysis_capability_intent(payload: CapabilityIntentRequest):
    return await run_in_threadpool(resolve_capability_intent, payload.message)


@router.post(
    "/api/v1/analysis/agent/analysis-capabilities/workbench",
    response_model=CapabilityWorkbenchOverview,
)
async def post_analysis_capability_workbench(payload: AgentTurnRequest):
    return await run_in_threadpool(build_capability_workbench_overview, payload)


@router.get(
    "/api/v1/analysis/agent/analysis/runs",
    response_model=List[AnalysisRun],
)
async def get_analysis_runs(history_id: str, capability_id: str = ""):
    try:
        return await run_in_threadpool(
            list_analysis_runs,
            history_id,
            capability_id=capability_id,
        )
    except AnalysisRunStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/api/v1/analysis/agent/analysis/runs/{run_id}",
    response_model=AnalysisRunDetail,
)
async def get_analysis_run_detail(run_id: str):
    try:
        detail = await run_in_threadpool(get_analysis_run, run_id)
    except AnalysisRunStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="analysis_run_not_found")
    return detail


@router.post(
    "/api/v1/analysis/agent/analysis-capabilities/{capability_id}/readiness",
    response_model=CapabilityReadiness,
)
async def post_analysis_capability_readiness(
    capability_id: str, payload: AgentTurnRequest
):
    try:
        return await run_in_threadpool(
            evaluate_capability_readiness, capability_id, payload
        )
    except AnalysisRunStorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="analysis_capability_not_found"
        ) from exc


@router.post("/api/v1/analysis/agent/conversations/turns/stream")
async def stream_conversation_turn(request: Request, payload: ConversationTurnRequest):
    async def event_stream():
        async for event_type, event_payload in codex_conversation_service.stream_turn(
            request, payload
        ):
            yield _encode_sse(event_type, event_payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/api/v1/analysis/agent/sessions",
    response_model=List[ConversationSessionSummary],
)
async def get_agent_sessions():
    return await run_in_threadpool(codex_conversation_service.list_sessions)


@router.post(
    "/api/v1/analysis/agent/site-selection", response_model=AgentSiteSelectionResponse
)
async def run_agent_site_selection(payload: AgentSiteSelectionRequest):
    response = await generate_site_selection_pack(payload)
    if response.status == "failed" and response.error == "missing_place_type":
        raise HTTPException(status_code=400, detail="missing_place_type")
    return response


@router.get("/api/v1/analysis/agent/tools", response_model=List[AgentToolSummary])
async def get_agent_tools():
    return list_agent_tools()


@router.get("/api/v1/analysis/agent/prompts", response_model=List[PromptConfig])
async def get_agent_prompts():
    return list_prompt_configs()


@router.get("/api/v1/analysis/agent/prompts/{prompt_key}", response_model=PromptConfig)
async def get_agent_prompt(prompt_key: str):
    try:
        return get_prompt_config(prompt_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="prompt_not_found")


@router.put("/api/v1/analysis/agent/prompts/{prompt_key}", response_model=PromptConfig)
async def put_agent_prompt(prompt_key: str, payload: PromptUpdateRequest):
    try:
        return update_prompt_config(prompt_key, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="prompt_not_found")


@router.post(
    "/api/v1/analysis/agent/summary/readiness",
    response_model=AgentSummaryReadinessResponse,
)
async def get_agent_summary_readiness(payload: AgentSummaryRequest):
    return await evaluate_summary_readiness(payload)


@router.post("/api/v1/analysis/agent/summary/generate")
async def post_agent_summary_generate(request: Request, payload: AgentSummaryRequest):
    async def event_stream():
        generator = stream_generate_summary_pack(payload)
        try:
            async for event in generator:
                if await request.is_disconnected():
                    break
                yield _encode_summary_sse(event)
        finally:
            await generator.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/api/v1/analysis/agent/iteration/nightlight/interpret",
    response_model=AgentIterationNightlightResponse,
)
async def post_agent_iteration_nightlight_interpret(
    payload: AgentIterationNightlightRequest,
):
    return await generate_nightlight_iteration_analysis(payload.evidence)


@router.post(
    "/api/v1/analysis/agent/iteration/poi/interpret",
    response_model=AgentIterationPoiResponse,
)
async def post_agent_iteration_poi_interpret(payload: AgentIterationPoiRequest):
    return await generate_poi_iteration_analysis(payload.evidence)


@router.post(
    "/api/v1/analysis/agent/iteration/poi/build",
    response_model=AgentIterationPoiBuildResponse,
)
async def post_agent_iteration_poi_build(payload: AgentIterationPoiBuildRequest):
    return await build_agent_poi_iteration_payload(payload, history_repo)


@router.get(
    "/api/v1/analysis/agent/sessions/{session_id}",
    response_model=ConversationSessionDetail,
)
async def get_agent_session(session_id: str):
    return await codex_conversation_service.get_session(session_id)


@router.patch(
    "/api/v1/analysis/agent/sessions/{session_id}",
    response_model=ConversationSessionDetail,
)
async def patch_agent_session(
    session_id: str, payload: ConversationSessionMetadataPatch
):
    return await codex_conversation_service.update_session(session_id, payload)


@router.delete("/api/v1/analysis/agent/sessions/{session_id}")
async def remove_agent_session(session_id: str):
    return await codex_conversation_service.delete_session(session_id)
