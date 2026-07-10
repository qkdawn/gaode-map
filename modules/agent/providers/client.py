from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable, Dict, List, Optional, Protocol

import httpx

from core.config import settings


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    thinking_enabled: bool = True
    timeout_s: int = 60

    @classmethod
    def from_settings(cls) -> "LLMRuntimeConfig":
        return cls(
            provider=str(settings.ai_provider or "").strip(),
            base_url=str(settings.ai_base_url or "").strip().rstrip("/"),
            api_key=str(settings.ai_api_key or ""),
            model=str(settings.ai_model or "").strip(),
            thinking_enabled=bool(settings.ai_thinking_enabled),
            timeout_s=int(settings.ai_timeout_s or 60),
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
        from .llm_provider import _invoke_json_role

        return await _invoke_json_role(
            system_prompt=system_prompt,
            user_payload=user_payload,
            emit=emit,
            phase=phase,
            title=title,
            reasoning_id=reasoning_id,
            runtime=self.runtime,
        )

    async def chat_text(self, *, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        from .chat_parser import extract_chat_completion_text

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
        from .llm_provider import _resolve_httpx_timeout, _stream_chat_completion

        base_url = self.runtime.base_url
        api_key = self.runtime.api_key
        model = str((request_body or {}).get("model") or self.runtime.model or "").strip()
        if not (base_url and api_key and model):
            raise ValueError("llm_provider_not_configured")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {**dict(request_body or {}), "model": model}
        async with httpx.AsyncClient(timeout=_resolve_httpx_timeout(self.runtime.timeout_s)) as client:
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
        from .chat_parser import extract_chat_completion_text

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
            async with httpx.AsyncClient(timeout=float(self.runtime.timeout_s or 15)) as client:
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
    runtime: Optional[LLMRuntimeConfig] = None,
) -> Dict[str, Any]:
    client = get_llm_provider_client(runtime=runtime)
    if client is None:
        raise ValueError("llm_provider_not_configured")
    return await client.chat_json(
        system_prompt=system_prompt,
        user_payload=user_payload,
        emit=emit,
        phase=phase,
        title=title,
        reasoning_id=reasoning_id,
    )
