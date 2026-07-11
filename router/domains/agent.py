import json
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from modules.agent.capability_run_service import (
    get_capability_run,
    list_capability_runs,
)
from modules.agent.capability_runs import CapabilityRun, CapabilityRunDetail
from modules.agent.capability_catalog import (
    AnalysisCapability,
    CapabilityReadiness,
    evaluate_capability_readiness,
    list_analysis_capabilities,
)
from modules.agent.runtime import stream_main_agent_loop
from modules.agent.execution_service import agent_capabilities, prepare_agent_turn
from modules.agent.model_profiles import (
    AgentModelProfileCreate,
    AgentModelProfilePatch,
    AgentModelProfileTestRequest,
    AgentModelProfileTestResponse,
    AgentModelProfileView,
    create_model_profile,
    delete_model_profile,
    test_model_profile,
    update_model_profile,
)
from modules.agent.schemas import (
    AgentContextAskRequest,
    AgentContextAskResponse,
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
    AgentTurnStreamEvent,
    AgentSessionDetail,
    AgentSessionMetadataPatchRequest,
    AgentSessionSnapshotRequest,
    AgentSessionSummary,
    AgentTurnRequest,
    AgentTurnResponse,
)
from modules.agent.context_ask_service import answer_context_ask, stream_context_ask
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
from modules.agent.session_service import (
    delete_agent_session,
    get_agent_session_detail,
    list_agent_sessions,
    persist_streamed_main_agent_loop_response,
    update_agent_session_metadata,
    upsert_agent_session,
)
from modules.agent.tool_service import list_agent_tools
from store.agent_session_repo import agent_session_repo
from store.history_repo import history_repo

router = APIRouter()
logger = logging.getLogger(__name__)


def _encode_sse(event: AgentTurnStreamEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"


def _encode_summary_sse(event: AgentSummaryStreamEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"


def _encode_context_ask_sse(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/api/v1/analysis/agent/capabilities")
async def get_agent_capabilities():
    return await run_in_threadpool(agent_capabilities)


@router.get(
    "/api/v1/analysis/agent/analysis-capabilities",
    response_model=List[AnalysisCapability],
)
async def get_analysis_capabilities():
    return await run_in_threadpool(list_analysis_capabilities)


@router.get(
    "/api/v1/analysis/agent/analysis-capability-runs",
    response_model=List[CapabilityRun],
)
async def get_analysis_capability_runs(history_id: str, capability_id: str = ""):
    try:
        return await run_in_threadpool(
            list_capability_runs,
            history_id,
            capability_id=capability_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/api/v1/analysis/agent/analysis-capability-runs/{run_id}",
    response_model=CapabilityRunDetail,
)
async def get_analysis_capability_run(run_id: str):
    detail = await run_in_threadpool(get_capability_run, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="capability_run_not_found")
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
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail="analysis_capability_not_found"
        ) from exc


@router.post(
    "/api/v1/analysis/agent/model-profiles", response_model=AgentModelProfileView
)
async def post_agent_model_profile(payload: AgentModelProfileCreate):
    return await run_in_threadpool(create_model_profile, payload)


@router.patch(
    "/api/v1/analysis/agent/model-profiles/{profile_id}",
    response_model=AgentModelProfileView,
)
async def patch_agent_model_profile(profile_id: str, payload: AgentModelProfilePatch):
    return await run_in_threadpool(update_model_profile, profile_id, payload)


@router.delete("/api/v1/analysis/agent/model-profiles/{profile_id}", status_code=204)
async def remove_agent_model_profile(profile_id: str):
    await run_in_threadpool(delete_model_profile, profile_id)


@router.post(
    "/api/v1/analysis/agent/model-profiles/test",
    response_model=AgentModelProfileTestResponse,
)
async def test_agent_model_profile(payload: AgentModelProfileTestRequest):
    return await test_model_profile(payload)


@router.post("/api/v1/analysis/agent/main-loop/stream")
async def run_agent_main_loop_stream(request: Request, payload: AgentTurnRequest):
    try:
        prepared = await run_in_threadpool(
            prepare_agent_turn, payload, agent_session_repo
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = prepared.payload

    async def event_stream():
        bootstrap_events = [
            AgentTurnStreamEvent(
                type="status",
                payload={"stage": "gating", "label": "门卫判断"},
            ),
            AgentTurnStreamEvent(
                type="thinking",
                payload={
                    "id": "router-bootstrap-gating",
                    "phase": "gating",
                    "title": "门卫判断",
                    "detail": "后端已收到请求，正在进入门卫判断。",
                    "state": "active",
                },
            ),
        ]
        for bootstrap in bootstrap_events:
            if await request.is_disconnected():
                return
            yield _encode_sse(bootstrap)
        generator = stream_main_agent_loop(
            payload,
            llm_runtime=prepared.runtime,
            effective_profile=prepared.effective_profile,
            skill_id=prepared.effective_profile.skill_id,
        )
        try:
            async for event in generator:
                if await request.is_disconnected():
                    break
                outgoing = event
                if event.type == "final":
                    response = AgentTurnResponse(
                        **(event.payload or {}).get("response", {})
                    )
                    persisted = await persist_streamed_main_agent_loop_response(
                        payload,
                        response,
                        agent_session_repo,
                        logger=logger,
                        conversation_profile=prepared.conversation_profile,
                    )
                    outgoing = AgentTurnStreamEvent(
                        type="final",
                        payload={"response": persisted.model_dump(mode="json")},
                    )
                yield _encode_sse(outgoing)
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


@router.get("/api/v1/analysis/agent/sessions", response_model=List[AgentSessionSummary])
async def get_agent_sessions():
    return await run_in_threadpool(list_agent_sessions, agent_session_repo)


@router.post(
    "/api/v1/analysis/agent/site-selection", response_model=AgentSiteSelectionResponse
)
async def run_agent_site_selection(payload: AgentSiteSelectionRequest):
    response = await generate_site_selection_pack(payload)
    if response.status == "failed" and response.error == "missing_place_type":
        raise HTTPException(status_code=400, detail="missing_place_type")
    return response


@router.post(
    "/api/v1/analysis/agent/context-ask", response_model=AgentContextAskResponse
)
async def run_agent_context_ask(payload: AgentContextAskRequest):
    return await answer_context_ask(payload)


@router.post("/api/v1/analysis/agent/context-ask/stream")
async def run_agent_context_ask_stream(
    request: Request, payload: AgentContextAskRequest
):
    async def event_stream():
        generator = stream_context_ask(payload)
        try:
            async for event_type, event_payload in generator:
                if await request.is_disconnected():
                    break
                yield _encode_context_ask_sse(event_type, event_payload)
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
    "/api/v1/analysis/agent/sessions/{session_id}", response_model=AgentSessionDetail
)
async def get_agent_session(session_id: str):
    return await run_in_threadpool(
        get_agent_session_detail, session_id, agent_session_repo
    )


@router.put(
    "/api/v1/analysis/agent/sessions/{session_id}", response_model=AgentSessionDetail
)
async def put_agent_session(session_id: str, payload: AgentSessionSnapshotRequest):
    return await run_in_threadpool(
        upsert_agent_session, session_id, payload, agent_session_repo
    )


@router.patch(
    "/api/v1/analysis/agent/sessions/{session_id}", response_model=AgentSessionDetail
)
async def patch_agent_session(
    session_id: str, payload: AgentSessionMetadataPatchRequest
):
    return await run_in_threadpool(
        update_agent_session_metadata, session_id, payload, agent_session_repo
    )


@router.delete("/api/v1/analysis/agent/sessions/{session_id}")
async def remove_agent_session(session_id: str):
    return await run_in_threadpool(delete_agent_session, session_id, agent_session_repo)
