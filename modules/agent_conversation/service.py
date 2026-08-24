from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from openai_codex import ApprovalMode, AsyncCodex, Sandbox

from store.agent_session_repo import AgentSessionRepo, agent_session_repo

from .schemas import (
    ConversationMessage,
    ConversationSessionDetail,
    ConversationSessionMetadataPatch,
    ConversationSessionSummary,
    ConversationTurnRequest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_INSTRUCTIONS = (
    "基于已有项目材料和空间数据完成用户任务，给出明确判断及行动建议。"
    "优先通过 spatial-project MCP 按需读取项目事实；不要虚构信息。无法完成时直接说明原因。"
)


def _iso_datetime(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=False, exclude_none=True)
    return {}


def _summary(record: dict[str, Any]) -> ConversationSessionSummary:
    status = str(record.get("status") or "idle")
    if status not in {"idle", "running", "answered", "failed"}:
        status = "failed"
    return ConversationSessionSummary(
        id=str(record.get("id") or ""),
        title=str(record.get("title") or ""),
        preview=str(record.get("preview") or ""),
        status=status,
        history_id=str(record.get("history_id") or ""),
        panel_kind=str(record.get("panel_kind") or "analysis"),
        is_pinned=bool(record.get("is_pinned")),
        created_at=_iso_datetime(record.get("created_at")),
        updated_at=_iso_datetime(record.get("updated_at")),
        pinned_at=_iso_datetime(record.get("pinned_at")) or None,
    )


def _developer_instructions(payload: ConversationTurnRequest) -> str:
    context = json.dumps(payload.map_context, ensure_ascii=False, separators=(",", ":"))
    if len(context) > 8_000:
        context = context[:8_000]
    return (
        f"当前产品会话绑定的 analysis history_id 是 {payload.history_id}。"
        "需要项目数据时把该标识传给 spatial-project MCP。"
        f"当前地图界面上下文：{context or '{}'}"
    )


def _project_item(item: Any) -> dict[str, Any]:
    raw = _model_payload(item)
    item_type = str(raw.get("type") or "unknown")
    projected: dict[str, Any] = {
        "id": str(raw.get("id") or ""),
        "type": item_type,
    }
    if item_type == "agentMessage":
        projected["text"] = str(raw.get("text") or "")
        projected["phase"] = str(raw.get("phase") or "")
    elif item_type == "reasoning":
        projected["summary"] = [str(value) for value in raw.get("summary") or []]
    elif item_type == "plan":
        projected["text"] = str(raw.get("text") or "")
    elif item_type == "mcpToolCall":
        error = raw.get("error") if isinstance(raw.get("error"), dict) else {}
        projected.update(
            server=str(raw.get("server") or ""),
            tool=str(raw.get("tool") or ""),
            status=_enum_value(raw.get("status")),
            duration_ms=raw.get("duration_ms"),
            error=str(error.get("message") or ""),
        )
    return projected


def _thread_messages(thread: Any) -> list[ConversationMessage]:
    messages: list[ConversationMessage] = []
    for turn in getattr(thread, "turns", []) or []:
        for item in getattr(turn, "items", []) or []:
            raw = _model_payload(item)
            item_type = str(raw.get("type") or "")
            if item_type == "agentMessage":
                if str(raw.get("phase") or "") != "final_answer":
                    continue
                text = str(raw.get("text") or "").strip()
                if text:
                    messages.append(
                        ConversationMessage(
                            id=str(raw.get("id") or ""),
                            role="assistant",
                            content=text,
                        )
                    )
                continue
            if item_type != "userMessage":
                continue
            parts: list[str] = []
            for content in raw.get("content") or []:
                if isinstance(content, dict) and content.get("type") == "text":
                    parts.append(str(content.get("text") or ""))
            text = "\n".join(part for part in parts if part).strip()
            if text:
                messages.append(
                    ConversationMessage(
                        id=str(raw.get("id") or ""), role="user", content=text
                    )
                )
    return messages


class CodexConversationService:
    def __init__(
        self,
        repo: AgentSessionRepo = agent_session_repo,
        codex_factory: Callable[[], AsyncCodex] = AsyncCodex,
    ) -> None:
        self._repo = repo
        self._codex_factory = codex_factory

    def list_sessions(self) -> list[ConversationSessionSummary]:
        return [_summary(record) for record in self._repo.list_records()]

    async def get_session(self, session_id: str) -> ConversationSessionDetail:
        record = self._require_record(session_id)
        async with self._codex_factory() as codex:
            thread = await codex.thread_resume(
                record["codex_thread_id"],
                approval_mode=ApprovalMode.auto_review,
                cwd=str(PROJECT_ROOT),
                sandbox=Sandbox.read_only,
            )
            response = await thread.read(include_turns=True)
        return ConversationSessionDetail(
            **_summary(record).model_dump(),
            messages=_thread_messages(response.thread),
        )

    async def update_session(
        self, session_id: str, payload: ConversationSessionMetadataPatch
    ) -> ConversationSessionDetail:
        if payload.title is None and payload.is_pinned is None:
            raise HTTPException(status_code=422, detail="至少提供一个可更新字段")
        record = self._require_record(session_id)
        if payload.title is not None:
            async with self._codex_factory() as codex:
                thread = await codex.thread_resume(record["codex_thread_id"])
                await thread.set_name(payload.title)
        updated = self._repo.update_metadata(
            session_id, title=payload.title, is_pinned=payload.is_pinned
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return await self.get_session(session_id)

    async def delete_session(self, session_id: str) -> dict[str, str]:
        record = self._require_record(session_id)
        async with self._codex_factory() as codex:
            await codex.thread_archive(record["codex_thread_id"])
        if not self._repo.delete_record(session_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"status": "success", "id": session_id}

    async def stream_turn(
        self, request: Request, payload: ConversationTurnRequest
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        record = self._repo.get_record(payload.conversation_id)
        codex = self._codex_factory()
        turn = None
        final_text = ""
        agent_message_phases: dict[str, str] = {}
        try:
            await codex.__aenter__()
            if record is None:
                thread = await codex.thread_start(
                    approval_mode=ApprovalMode.auto_review,
                    base_instructions=BASE_INSTRUCTIONS,
                    cwd=str(PROJECT_ROOT),
                    developer_instructions=_developer_instructions(payload),
                    sandbox=Sandbox.read_only,
                    service_name="gaode-map-analysis",
                )
                title = payload.message[:60]
                await thread.set_name(title)
                record = self._repo.upsert_record(
                    payload.conversation_id,
                    codex_thread_id=thread.id,
                    title=title,
                    preview=payload.message[:120],
                    status="running",
                    history_id=payload.history_id,
                    panel_kind=payload.panel_kind,
                )
            else:
                if record["history_id"] != payload.history_id:
                    raise HTTPException(status_code=409, detail="会话不属于当前分析记录")
                if record["panel_kind"] != payload.panel_kind:
                    raise HTTPException(status_code=409, detail="会话类型与当前面板不一致")
                thread = await codex.thread_resume(
                    record["codex_thread_id"],
                    approval_mode=ApprovalMode.auto_review,
                    cwd=str(PROJECT_ROOT),
                    developer_instructions=_developer_instructions(payload),
                    sandbox=Sandbox.read_only,
                )
                self._repo.update_metadata(payload.conversation_id, status="running")

            yield "thread", {"conversation_id": payload.conversation_id}
            turn = await thread.turn(payload.message)
            async for notification in turn.stream():
                if await request.is_disconnected():
                    await turn.interrupt()
                    self._repo.update_metadata(payload.conversation_id, status="idle")
                    return
                method = notification.method
                event_payload = notification.payload
                if method == "turn/started":
                    yield "turn_started", {"turn_id": turn.id}
                elif method == "item/started":
                    item = _project_item(event_payload.item)
                    if item.get("type") == "agentMessage":
                        agent_message_phases[str(item.get("id") or "")] = str(
                            item.get("phase") or ""
                        )
                    yield "item_started", item
                elif method == "item/agentMessage/delta":
                    item_id = str(event_payload.item_id)
                    if agent_message_phases.get(item_id) == "commentary":
                        continue
                    delta = str(event_payload.delta or "")
                    final_text += delta
                    yield "message_delta", {
                        "item_id": item_id,
                        "delta": delta,
                    }
                elif method == "item/completed":
                    item = _project_item(event_payload.item)
                    if item.get("type") == "agentMessage":
                        if item.get("phase") != "final_answer":
                            continue
                        if item.get("text"):
                            final_text = str(item["text"])
                    yield "item_completed", item
                elif method == "turn/completed":
                    status = _enum_value(event_payload.turn.status)
                    error = getattr(event_payload.turn.error, "message", "") or ""
                    persisted_status = "answered" if status == "completed" else "failed"
                    self._repo.update_metadata(
                        payload.conversation_id,
                        preview=(final_text or payload.message)[:120],
                        status=persisted_status,
                    )
                    yield "turn_completed", {
                        "turn_id": turn.id,
                        "status": status,
                        "error": str(error),
                    }
        except asyncio.CancelledError:
            if turn is not None:
                await turn.interrupt()
            if record is not None:
                self._repo.update_metadata(payload.conversation_id, status="idle")
            raise
        except HTTPException as exc:
            yield "error", {"message": str(exc.detail)}
        except Exception as exc:
            if record is not None:
                self._repo.update_metadata(payload.conversation_id, status="failed")
            yield "error", {"message": f"Codex App Server 执行失败: {exc}"}
        finally:
            await codex.close()

    def _require_record(self, session_id: str) -> dict[str, Any]:
        record = self._repo.get_record(session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return record


codex_conversation_service = CodexConversationService()
