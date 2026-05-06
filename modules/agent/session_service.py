from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .providers.llm_provider import (
    generate_title_with_llm,
    is_llm_enabled,
)
from .schemas import (
    AgentContextSummary,
    AgentMessage,
    AgentPlanEnvelope,
    AgentSessionDetail,
    AgentSessionMetadataPatchRequest,
    AgentSessionSnapshotRequest,
    AgentSessionSummary,
    AgentTurnDiagnostics,
    AgentTurnOutput,
    AgentTurnRequest,
    AgentTurnResponse,
)

TITLE_SOURCE_USER = "user"
TITLE_SOURCE_AI = "ai"
TITLE_SOURCE_FALLBACK = "fallback"
PANEL_KIND_FOLLOWUP = "followup"


def serialize_datetime(value: Any) -> str:
    if not isinstance(value, datetime):
        return str(value or "")
    dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any, *, max_length: int = 0) -> str:
    text = str(value or "").strip()
    if max_length > 0:
        return text[:max_length]
    return text


def normalize_agent_session_title(value: Any) -> str:
    title = _normalize_text(value, max_length=60)
    if not title:
        raise HTTPException(status_code=422, detail="会话标题不能为空")
    return title


def normalize_agent_session_title_source(value: Any) -> str:
    source = _normalize_text(value, max_length=16).lower()
    if source in {TITLE_SOURCE_USER, TITLE_SOURCE_AI, TITLE_SOURCE_FALLBACK}:
        return source
    return TITLE_SOURCE_FALLBACK


def normalize_agent_panel_kind(value: Any) -> str:
    return _normalize_text(value, max_length=64).lower()


def _require_agent_panel_identity(history_id: str, panel_kind: str) -> tuple[str, str]:
    normalized_history_id = _normalize_text(history_id, max_length=128)
    normalized_panel_kind = normalize_agent_panel_kind(panel_kind)
    if not normalized_history_id:
        raise HTTPException(status_code=422, detail="AI 面板历史必须提供 history_id")
    if not normalized_panel_kind:
        raise HTTPException(status_code=422, detail="AI 面板历史必须提供 panel_kind")
    return normalized_history_id, normalized_panel_kind


def derive_agent_session_title(messages: List[Dict[str, Any]] | List[AgentMessage] | None) -> str:
    rows = messages or []
    for item in rows:
        role = str(getattr(item, "role", "") if not isinstance(item, dict) else item.get("role", "")).strip()
        content = _normalize_text(
            getattr(item, "content", "") if not isinstance(item, dict) else item.get("content", ""),
            max_length=24,
        )
        if role == "user" and content:
            return content
    return "新聊天"


def _summary_card_content_from_output(output: Dict[str, Any]) -> str:
    cards = output.get("cards") or []
    for item in cards:
        if isinstance(item, dict) and str(item.get("type") or "") == "summary":
            return _normalize_text(item.get("content"), max_length=120)
    return ""


def derive_agent_session_preview(payload: Dict[str, Any]) -> str:
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    for key in ("error",):
        text = _normalize_text(diagnostics.get(key), max_length=120)
        if text:
            return text
    for key in ("risk_prompt", "clarification_question"):
        text = _normalize_text(output.get(key), max_length=120)
        if text:
            return text
    summary = _summary_card_content_from_output(output)
    if summary:
        return summary
    messages = payload.get("messages") or []
    for item in reversed(messages):
        if isinstance(item, dict):
            content = _normalize_text(item.get("content"), max_length=120)
        else:
            content = _normalize_text(getattr(item, "content", ""), max_length=120)
        if content:
            return content
    return "开始一段新的分析对话"


def _get_record_title_source(record: Optional[Dict[str, Any]]) -> str:
    if not isinstance(record, dict):
        return TITLE_SOURCE_FALLBACK
    direct = normalize_agent_session_title_source(record.get("title_source"))
    if direct != TITLE_SOURCE_FALLBACK or record.get("title_source"):
        return direct
    snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
    meta = snapshot.get("_meta") if isinstance(snapshot, dict) else {}
    if isinstance(meta, dict):
        return normalize_agent_session_title_source(meta.get("title_source"))
    return TITLE_SOURCE_FALLBACK


def _get_record_history_id(record: Optional[Dict[str, Any]]) -> str:
    if not isinstance(record, dict):
        return ""
    return _normalize_text(record.get("history_id"), max_length=128)


def _get_record_panel_kind(record: Optional[Dict[str, Any]]) -> str:
    if not isinstance(record, dict):
        return ""
    return normalize_agent_panel_kind(record.get("panel_kind"))


def _resolve_upsert_title(
    request: AgentSessionSnapshotRequest,
    existing_record: Optional[Dict[str, Any]],
) -> tuple[str, str]:
    fallback_title = derive_agent_session_title(request.messages)
    requested_title = _normalize_text(request.title, max_length=60)
    existing_title = _normalize_text(existing_record.get("title"), max_length=60) if existing_record else ""
    existing_source = _get_record_title_source(existing_record)
    if requested_title and requested_title != fallback_title:
        return requested_title, TITLE_SOURCE_USER
    if existing_title and existing_source in {TITLE_SOURCE_USER, TITLE_SOURCE_AI}:
        return existing_title, existing_source
    return requested_title or fallback_title, TITLE_SOURCE_FALLBACK


def _build_turn_title_seed(payload: AgentTurnRequest, response: AgentTurnResponse) -> tuple[str, str]:
    first_user_message = ""
    for item in payload.messages:
        if str(item.role or "").strip() == "user" and _normalize_text(item.content):
            first_user_message = _normalize_text(item.content)
            break
    assistant_summary = ""
    for item in response.output.cards:
        if str(item.type or "").strip() == "summary" and _normalize_text(item.content):
            assistant_summary = _normalize_text(item.content, max_length=240)
            break
    if not assistant_summary:
        assistant_summary = _normalize_text(response.output.clarification_question or response.output.risk_prompt, max_length=240)
    if not assistant_summary and response.diagnostics.error:
        assistant_summary = _normalize_text(response.diagnostics.error, max_length=240)
    return first_user_message, assistant_summary


async def generate_agent_session_title(payload: AgentTurnRequest, response: AgentTurnResponse) -> Optional[str]:
    if not is_llm_enabled():
        return None
    first_user_message, assistant_summary = _build_turn_title_seed(payload, response)
    if not first_user_message:
        return None
    try:
        title = await generate_title_with_llm(
            first_user_message=first_user_message,
            assistant_summary=assistant_summary,
            status=response.status,
        )
    except Exception:
        return None
    normalized = _normalize_text(title, max_length=60)
    return normalized or None


def build_snapshot_payload(request: AgentSessionSnapshotRequest) -> Dict[str, Any]:
    payload = {
        "input": str(request.input or ""),
        "stage": str(request.stage or "gating"),
        "messages": [item.model_dump() for item in request.messages],
        "output": request.output.model_dump(),
        "diagnostics": request.diagnostics.model_dump(),
        "context_summary": request.context_summary.model_dump(),
        "plan": request.plan.model_dump(),
        "risk_confirmations": [str(item) for item in request.risk_confirmations],
    }
    history_id = _normalize_text(request.history_id, max_length=128)
    panel_kind = normalize_agent_panel_kind(request.panel_kind)
    payload["_meta"] = {
        "history_id": history_id,
        "panel_kind": panel_kind,
    }
    return payload


def build_turn_persist_payload(payload: AgentTurnRequest, response: AgentTurnResponse) -> AgentSessionSnapshotRequest:
    messages = [item.model_dump() for item in payload.messages]
    summary_card = next((item for item in response.output.cards if item.type == "summary" and str(item.content or "").strip()), None)
    if response.status == "answered":
        messages.append(
            {
                "role": "assistant",
                "content": str(summary_card.content if summary_card else "已完成分析"),
            }
        )
    request = AgentSessionSnapshotRequest(
        title=derive_agent_session_title(messages),
        preview="",
        status=response.status,
        stage=response.stage,
        history_id=_normalize_text(payload.history_id, max_length=128),
        panel_kind=PANEL_KIND_FOLLOWUP,
        input="" if response.status == "answered" else str(payload.messages[-1].content if payload.messages else ""),
        messages=[AgentMessage(**item) for item in messages],
        output=response.output,
        diagnostics=response.diagnostics,
        context_summary=response.context_summary,
        plan=response.plan,
        risk_confirmations=[str(item) for item in payload.risk_confirmations],
    )
    request.preview = derive_agent_session_preview(build_snapshot_payload(request))
    return request


def _normalize_output(snapshot: Dict[str, Any]) -> AgentTurnOutput:
    if isinstance(snapshot.get("output"), dict):
        return AgentTurnOutput(**snapshot.get("output"))
    return AgentTurnOutput(
        cards=[item for item in (snapshot.get("cards") or []) if isinstance(item, dict)],
        clarification_question=str(snapshot.get("clarification_question") or ""),
        risk_prompt=str(snapshot.get("risk_prompt") or ""),
        next_suggestions=[str(item) for item in (snapshot.get("next_suggestions") or [])],
    )


def _normalize_diagnostics(snapshot: Dict[str, Any]) -> AgentTurnDiagnostics:
    if isinstance(snapshot.get("diagnostics"), dict):
        return AgentTurnDiagnostics(**snapshot.get("diagnostics"))
    return AgentTurnDiagnostics(
        execution_trace=[item for item in (snapshot.get("execution_trace") or []) if isinstance(item, dict)],
        used_tools=[str(item) for item in (snapshot.get("used_tools") or [])],
        citations=[str(item) for item in (snapshot.get("citations") or [])],
        research_notes=[str(item) for item in (snapshot.get("research_notes") or [])],
        audit_issues=[],
        thinking_timeline=[item for item in (snapshot.get("thinking_timeline") or []) if isinstance(item, dict)],
        error=str(snapshot.get("error") or ""),
    )


def _normalize_context_summary(snapshot: Dict[str, Any]) -> AgentContextSummary:
    if isinstance(snapshot.get("context_summary"), dict):
        return AgentContextSummary(**snapshot.get("context_summary"))
    return AgentContextSummary()


def _normalize_plan(snapshot: Dict[str, Any]) -> AgentPlanEnvelope:
    if isinstance(snapshot.get("plan"), dict):
        return AgentPlanEnvelope(**snapshot.get("plan"))
    return AgentPlanEnvelope()


def _build_summary_model(record: Dict[str, Any]) -> AgentSessionSummary:
    return AgentSessionSummary(
        id=str(record.get("id") or ""),
        title=str(record.get("title") or ""),
        preview=str(record.get("preview") or ""),
        status=str(record.get("status") or "idle"),
        history_id=_get_record_history_id(record),
        is_pinned=bool(record.get("is_pinned")),
        title_source=_get_record_title_source(record),
        panel_kind=_get_record_panel_kind(record),
        created_at=serialize_datetime(record.get("created_at")),
        updated_at=serialize_datetime(record.get("updated_at")),
        pinned_at=serialize_datetime(record.get("pinned_at")) if record.get("pinned_at") else None,
    )


def _build_detail_model(record: Dict[str, Any]) -> AgentSessionDetail:
    summary = _build_summary_model(record)
    snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
    output = _normalize_output(snapshot)
    diagnostics = _normalize_diagnostics(snapshot)
    return AgentSessionDetail(
        **summary.model_dump(),
        stage=str(snapshot.get("stage") or "gating"),
        input=str(snapshot.get("input") or ""),
        messages=[AgentMessage(**item) for item in (snapshot.get("messages") or []) if isinstance(item, dict)],
        output=output,
        diagnostics=diagnostics,
        context_summary=_normalize_context_summary(snapshot),
        plan=_normalize_plan(snapshot),
        risk_confirmations=[str(item) for item in (snapshot.get("risk_confirmations") or [])],
    )


def list_agent_sessions(repo) -> List[AgentSessionSummary]:
    return [_build_summary_model(record) for record in repo.list_records()]


def get_agent_session_detail(session_id: str, repo) -> AgentSessionDetail:
    record = repo.get_record(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _build_detail_model(record)


def upsert_agent_session(session_id: str, request: AgentSessionSnapshotRequest, repo) -> AgentSessionDetail:
    existing_record = repo.get_record(session_id)
    if not _normalize_text(request.history_id):
        request.history_id = _get_record_history_id(existing_record)
    if not normalize_agent_panel_kind(request.panel_kind):
        request.panel_kind = _get_record_panel_kind(existing_record)
    history_id, panel_kind = _require_agent_panel_identity(request.history_id, request.panel_kind)
    title, title_source = _resolve_upsert_title(request, existing_record)
    preview = _normalize_text(request.preview, max_length=120) or derive_agent_session_preview(build_snapshot_payload(request))
    record = repo.upsert_record(
        session_id,
        title=title,
        preview=preview,
        status=str(request.status or "idle"),
        history_id=history_id,
        panel_kind=panel_kind,
        snapshot=build_snapshot_payload(request),
        is_pinned=request.is_pinned,
        title_source=title_source,
    )
    return _build_detail_model(record)


def update_agent_session_metadata(session_id: str, request: AgentSessionMetadataPatchRequest, repo) -> AgentSessionDetail:
    if request.title is None and request.is_pinned is None:
        raise HTTPException(status_code=422, detail="至少提供一个可更新字段")
    title = normalize_agent_session_title(request.title) if request.title is not None else None
    record = repo.update_metadata(
        session_id,
        title=title,
        is_pinned=request.is_pinned,
        title_source=TITLE_SOURCE_USER if title is not None else None,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _build_detail_model(record)


def delete_agent_session(session_id: str, repo) -> Dict[str, Any]:
    if not repo.delete_record(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "success", "id": session_id}


async def persist_agent_turn(payload: AgentTurnRequest, response: AgentTurnResponse, repo) -> AgentTurnResponse:
    session_id = _normalize_text(payload.conversation_id, max_length=128)
    if not session_id:
        return response
    existing_record = repo.get_record(session_id)
    request = build_turn_persist_payload(payload, response)
    title, title_source = _resolve_upsert_title(request, existing_record)
    request.title = title
    history_id, panel_kind = _require_agent_panel_identity(request.history_id, request.panel_kind)
    preview = _normalize_text(request.preview, max_length=120) or derive_agent_session_preview(build_snapshot_payload(request))
    repo.upsert_record(
        session_id,
        title=title,
        preview=preview,
        status=str(request.status or "idle"),
        history_id=history_id,
        panel_kind=panel_kind,
        snapshot=build_snapshot_payload(request),
        title_source=title_source,
    )
    if existing_record is None and title_source == TITLE_SOURCE_FALLBACK:
        generated_title = await generate_agent_session_title(payload, response)
        if generated_title:
            repo.update_metadata(session_id, title=generated_title, title_source=TITLE_SOURCE_AI)
    return response
