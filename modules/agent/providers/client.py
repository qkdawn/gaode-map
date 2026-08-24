from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

import httpx

from core.config import settings

from .chat_parser import (
    extract_chat_completion_text,
    extract_json_object,
    finalize_tool_calls,
    merge_tool_call_delta,
)


LoopEmit = Callable[[str, Dict[str, Any]], Awaitable[None] | None]


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    thinking_enabled: bool = True
    timeout_s: float = 60.0

    @classmethod
    def from_settings(cls) -> "LLMRuntimeConfig":
        return cls(
            provider=str(settings.ai_provider or "").strip(),
            base_url=str(settings.ai_base_url or "").strip().rstrip("/"),
            api_key=str(settings.ai_api_key or ""),
            model=str(settings.ai_model or "").strip(),
            thinking_enabled=bool(settings.ai_thinking_enabled),
            timeout_s=float(settings.ai_timeout_s),
        )

    def configured(self) -> bool:
        return bool(self.provider and self.base_url and self.api_key and self.model)


@dataclass(frozen=True)
class LLMProviderSpec:
    name: str
    supports_json_mode: bool = True
    supports_text_mode: bool = True


class LLMProviderClient(Protocol):
    @property
    def supports_json_mode(self) -> bool: ...

    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_payload: Dict[str, Any],
        emit=None,
        phase: str = "",
        title: str = "",
        reasoning_id: str = "",
    ) -> Dict[str, Any]: ...

    async def chat_text(
        self,
        *,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
    ) -> str: ...

    async def stream_text(
        self,
        *,
        messages: List[Dict[str, str]],
        emit_delta: Callable[[str], Any],
        temperature: float = 0.1,
        max_tokens: int = 900,
    ) -> str: ...

    async def chat_completion(
        self,
        *,
        request_body: Dict[str, Any],
        emit=None,
        phase: str = "",
        title: str = "",
        reasoning_id: str = "",
        enable_thinking: bool = True,
    ) -> Dict[str, Any]: ...

    async def health(self) -> bool: ...


LLM_PROVIDER_REGISTRY: Dict[str, LLMProviderSpec] = {
    "deepseek": LLMProviderSpec(name="deepseek", supports_json_mode=True, supports_text_mode=True),
    "openai_compatible": LLMProviderSpec(name="openai_compatible", supports_json_mode=True, supports_text_mode=True),
}


def normalize_provider_name(value: Any) -> str:
    return str(value or "").strip().lower()


def get_llm_provider_spec(provider: Optional[str] = None) -> Optional[LLMProviderSpec]:
    name = normalize_provider_name(provider if provider is not None else settings.ai_provider)
    if not name:
        return None
    return LLM_PROVIDER_REGISTRY.get(name)


def has_llm_base_config() -> bool:
    return bool(
        str(settings.ai_base_url or "").strip()
        and str(settings.ai_api_key or "").strip()
        and str(settings.ai_model or "").strip()
    )


def is_llm_enabled() -> bool:
    return bool(settings.ai_enabled and get_llm_provider_spec() and has_llm_base_config())


class OpenAICompatibleProviderClient:
    def __init__(self, spec: LLMProviderSpec, runtime: Optional[LLMRuntimeConfig] = None):
        self.spec = spec
        self.runtime = runtime or LLMRuntimeConfig.from_settings()

    @property
    def supports_json_mode(self) -> bool:
        return bool(self.spec.supports_json_mode)

    async def chat_json(
        self,
        *,
        system_prompt: str,
        user_payload: Dict[str, Any],
        emit=None,
        phase: str = "",
        title: str = "",
        reasoning_id: str = "",
    ) -> Dict[str, Any]:
        return await invoke_json_role(
            system_prompt=system_prompt,
            user_payload=user_payload,
            emit=emit,
            phase=phase,
            title=title,
            reasoning_id=reasoning_id,
            runtime=self.runtime,
        )

    async def chat_text(self, *, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        body: Dict[str, Any] = {
            "model": self.runtime.model,
            "messages": messages,
            "temperature": float(temperature),
            "stream": False,
        }
        payload = await self.chat_completion(request_body=body)
        return extract_chat_completion_text(payload)

    async def _chat_completion(
        self,
        *,
        request_body: Dict[str, Any],
        emit=None,
        content_emit=None,
        phase: str = "",
        title: str = "",
        reasoning_id: str = "",
        enable_thinking: bool = True,
    ) -> Dict[str, Any]:
        base_url = self.runtime.base_url
        api_key = self.runtime.api_key
        model = str((request_body or {}).get("model") or self.runtime.model or "").strip()
        if not (base_url and api_key and model):
            raise ValueError("llm_provider_not_configured")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {**dict(request_body or {}), "model": model}
        async with httpx.AsyncClient(timeout=None) as client:
            return await _stream_chat_completion(
                client=client,
                base_url=base_url,
                headers=headers,
                request_body=body,
                emit=emit,
                content_emit=content_emit,
                phase=phase,
                title=title,
                reasoning_id=reasoning_id,
                enable_thinking=bool(enable_thinking and self.runtime.thinking_enabled),
            )

    async def chat_completion(
        self,
        *,
        request_body: Dict[str, Any],
        emit=None,
        phase: str = "",
        title: str = "",
        reasoning_id: str = "",
        enable_thinking: bool = True,
    ) -> Dict[str, Any]:
        return await self._chat_completion(
            request_body=request_body,
            emit=emit,
            phase=phase,
            title=title,
            reasoning_id=reasoning_id,
            enable_thinking=enable_thinking,
        )

    async def stream_text(
        self,
        *,
        messages: List[Dict[str, str]],
        emit_delta: Callable[[str], Any],
        temperature: float = 0.1,
        max_tokens: int = 900,
    ) -> str:
        async def forward_delta(_event_type: str, payload: Dict[str, Any]) -> None:
            delta = str(payload.get("delta") or "")
            if not delta:
                return
            outcome = emit_delta(delta)
            if inspect.isawaitable(outcome):
                await outcome

        payload = await self._chat_completion(
            request_body={
                "model": self.runtime.model,
                "messages": messages,
                "temperature": float(temperature),
                "max_tokens": max(128, int(max_tokens)),
            },
            content_emit=forward_delta,
            enable_thinking=False,
        )
        return extract_chat_completion_text(payload)

    async def health(self) -> bool:
        base_url = self.runtime.base_url
        api_key = self.runtime.api_key
        if not (base_url and api_key):
            return False
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                response = await client.get(f"{base_url}/models", headers=headers)
            return 200 <= response.status_code < 300
        except Exception:
            return False


def get_llm_provider_client(
    provider: Optional[str] = None,
    *,
    runtime: Optional[LLMRuntimeConfig] = None,
) -> Optional[LLMProviderClient]:
    spec = get_llm_provider_spec(provider if provider is not None else (runtime.provider if runtime else None))
    if not spec:
        return None
    if spec.name in {"deepseek", "openai_compatible"}:
        return OpenAICompatibleProviderClient(spec, runtime=runtime)
    return None


async def invoke_json_role(
    *,
    system_prompt: str,
    user_payload: Dict[str, Any],
    emit=None,
    phase: str = "",
    title: str = "",
    reasoning_id: str = "",
    image_inputs: List[Dict[str, Any]] | None = None,
    enable_thinking: bool = True,
    stream: bool = True,
    runtime: Optional[LLMRuntimeConfig] = None,
) -> Dict[str, Any]:
    effective = runtime or LLMRuntimeConfig.from_settings()
    if not effective.configured() or get_llm_provider_spec(effective.provider) is None:
        raise ValueError("llm_provider_not_configured")

    user_content: Any = json.dumps(user_payload, ensure_ascii=False)
    cleaned_images = [
        item
        for item in (image_inputs or [])
        if isinstance(item, dict)
        and str(item.get("data_url") or "").startswith("data:image/")
    ]
    if cleaned_images:
        user_content = [{"type": "text", "text": user_content}]
        user_content.extend(
            {
                "type": "image_url",
                "image_url": {"url": str(item["data_url"])},
            }
            for item in cleaned_images
        )

    request_body = {
        "model": effective.model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {
        "Authorization": f"Bearer {effective.api_key}",
        "Content-Type": "application/json",
    }
    timeout_s = max(float(effective.timeout_s), 0.1)
    thinking_enabled = bool(enable_thinking and effective.thinking_enabled)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
        if stream:
            response_payload = await _stream_chat_completion(
                client=client,
                base_url=effective.base_url,
                headers=headers,
                request_body=request_body,
                emit=emit,
                phase=phase,
                title=title,
                reasoning_id=reasoning_id,
                enable_thinking=thinking_enabled,
            )
        else:
            response = await client.post(
                f"{effective.base_url}/chat/completions",
                headers=headers,
                json=_with_provider_thinking(
                    request_body,
                    enabled=thinking_enabled,
                ),
            )
            if response.status_code >= 400:
                detail = response.text[:800] or str(
                    getattr(response, "reason_phrase", "LLM provider error")
                )
                raise httpx.HTTPStatusError(
                    f"LLM provider returned HTTP {response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )
            response_payload = response.json()
    return extract_json_object(extract_chat_completion_text(response_payload))


def _with_provider_thinking(
    request_body: Dict[str, Any], *, enabled: bool
) -> Dict[str, Any]:
    body = dict(request_body or {})
    model = str(body.get("model") or settings.ai_model or "").strip()
    if enabled and model != "deepseek-reasoner":
        body["thinking"] = {"type": "enabled"}
    return body


async def _iter_sse_data(response: httpx.Response):
    data_lines: List[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines)


async def _maybe_emit(
    emit: LoopEmit | None, event_type: str, payload: Dict[str, Any]
) -> None:
    if emit is None:
        return
    outcome = emit(event_type, payload)
    if inspect.isawaitable(outcome):
        await outcome


async def _stream_chat_completion(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    request_body: Dict[str, Any],
    emit: LoopEmit | None = None,
    content_emit: LoopEmit | None = None,
    reasoning_id: str = "llm-reasoning",
    phase: str = "executing",
    title: str = "模型思考",
    enable_thinking: bool = True,
) -> Dict[str, Any]:
    body = _with_provider_thinking(
        {**request_body, "stream": True}, enabled=enable_thinking
    )
    response_id = ""
    finish_reason = ""
    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_call_accumulator: List[Dict[str, Any]] = []

    async with client.stream(
        "POST", f"{base_url}/chat/completions", headers=headers, json=body
    ) as response:
        if response.status_code >= 400:
            error_body = (
                await response.aread()
            ).decode("utf-8", errors="replace").strip()
            detail = error_body[:800] or str(
                getattr(response, "reason_phrase", "LLM provider error")
            )
            raise httpx.HTTPStatusError(
                f"LLM provider returned HTTP {response.status_code}: {detail}",
                request=response.request,
                response=response,
            )
        async for raw_data in _iter_sse_data(response):
            if raw_data.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(raw_data)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid_chat_completion_stream_chunk:{exc}"
                ) from exc
            if chunk.get("id"):
                response_id = str(chunk.get("id") or response_id)
            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0] if isinstance(choices[0], dict) else {}
            if choice.get("finish_reason"):
                finish_reason = str(choice.get("finish_reason") or "")
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            reasoning_delta = delta.get("reasoning_content")
            if isinstance(reasoning_delta, str) and reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                await _maybe_emit(
                    emit,
                    "reasoning_delta",
                    {
                        "id": reasoning_id,
                        "phase": phase,
                        "title": title,
                        "delta": reasoning_delta,
                        "state": "active",
                    },
                )
            content_delta = delta.get("content")
            if isinstance(content_delta, str) and content_delta:
                content_parts.append(content_delta)
                await _maybe_emit(
                    content_emit, "content_delta", {"delta": content_delta}
                )
            for raw_call in delta.get("tool_calls") or []:
                merge_tool_call_delta(tool_call_accumulator, raw_call)

    if reasoning_parts:
        await _maybe_emit(
            emit,
            "reasoning_delta",
            {
                "id": reasoning_id,
                "phase": phase,
                "title": title,
                "delta": "",
                "state": "completed",
            },
        )
    return {
        "id": response_id,
        "choices": [
            {
                "finish_reason": finish_reason or "stop",
                "message": {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "reasoning_content": "".join(reasoning_parts),
                    "tool_calls": finalize_tool_calls(tool_call_accumulator),
                },
            }
        ],
    }
