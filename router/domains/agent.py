import json
from typing import List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from modules.agent.runtime import process_agent_turn, stream_agent_turn
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
from modules.agent.context_ask_service import answer_context_ask
from modules.agent.iteration_change_service import generate_nightlight_iteration_analysis, generate_poi_iteration_analysis
from modules.agent.poi_iteration_build_service import build_agent_poi_iteration_payload
from modules.agent.prompt_registry import (
    PromptConfig,
    PromptUpdateRequest,
    get_prompt_config,
    list_prompt_configs,
    update_prompt_config,
)
from modules.agent.summary_service import evaluate_summary_readiness, stream_generate_summary_pack
from modules.agent.site_selection_service import generate_site_selection_pack
from modules.agent.session_service import (
    delete_agent_session,
    get_agent_session_detail,
    list_agent_sessions,
    persist_agent_turn,
    update_agent_session_metadata,
    upsert_agent_session,
)
from modules.agent.tool_service import list_agent_tools
from store.agent_session_repo import agent_session_repo
from store.history_repo import history_repo

router = APIRouter()


def _encode_sse(event: AgentTurnStreamEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"


def _encode_summary_sse(event: AgentSummaryStreamEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"


@router.post("/api/v1/analysis/agent/turn", response_model=AgentTurnResponse)
async def run_agent_turn(payload: AgentTurnRequest):
    response = await process_agent_turn(payload)
    return await persist_agent_turn(payload, response, agent_session_repo)


@router.post("/api/v1/analysis/agent/turn/stream")
async def run_agent_turn_stream(request: Request, payload: AgentTurnRequest):
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
        generator = stream_agent_turn(payload)
        try:
            async for event in generator:
                if await request.is_disconnected():
                    break
                outgoing = event
                if event.type == "final":
                    response = AgentTurnResponse(**(event.payload or {}).get("response", {}))
                    persisted = await persist_agent_turn(payload, response, agent_session_repo)
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


@router.post("/api/v1/analysis/agent/site-selection", response_model=AgentSiteSelectionResponse)
async def run_agent_site_selection(payload: AgentSiteSelectionRequest):
    response = await generate_site_selection_pack(payload)
    if response.status == "failed" and response.error == "missing_place_type":
        raise HTTPException(status_code=400, detail="missing_place_type")
    return response


@router.post("/api/v1/analysis/agent/context-ask", response_model=AgentContextAskResponse)
async def run_agent_context_ask(payload: AgentContextAskRequest):
    return await answer_context_ask(payload)


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


@router.post("/api/v1/analysis/agent/summary/readiness", response_model=AgentSummaryReadinessResponse)
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
async def post_agent_iteration_nightlight_interpret(payload: AgentIterationNightlightRequest):
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


@router.get("/api/v1/analysis/agent/sessions/{session_id}", response_model=AgentSessionDetail)
async def get_agent_session(session_id: str):
    return await run_in_threadpool(get_agent_session_detail, session_id, agent_session_repo)


@router.put("/api/v1/analysis/agent/sessions/{session_id}", response_model=AgentSessionDetail)
async def put_agent_session(session_id: str, payload: AgentSessionSnapshotRequest):
    return await run_in_threadpool(upsert_agent_session, session_id, payload, agent_session_repo)


@router.patch("/api/v1/analysis/agent/sessions/{session_id}", response_model=AgentSessionDetail)
async def patch_agent_session(session_id: str, payload: AgentSessionMetadataPatchRequest):
    return await run_in_threadpool(update_agent_session_metadata, session_id, payload, agent_session_repo)


@router.delete("/api/v1/analysis/agent/sessions/{session_id}")
async def remove_agent_session(session_id: str):
    return await run_in_threadpool(delete_agent_session, session_id, agent_session_repo)
