from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config import settings
from store.agent_model_profile_repo import agent_model_profile_repo

from .providers.client import LLMRuntimeConfig, get_llm_provider_client

ProviderName = Literal["deepseek", "openai_compatible"]
SYSTEM_PROFILE_ID = "system-default"
SYSTEM_GLM_PROFILE_ID = "system-glm"
_SYSTEM_PROFILE_IDS = frozenset({SYSTEM_PROFILE_ID, SYSTEM_GLM_PROFILE_ID})


class AgentModelProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    source: Literal["system", "personal"]
    provider: ProviderName
    base_url: str
    model: str
    enabled: bool = True
    is_default: bool = False
    has_api_key: bool = False
    created_at: str = ""
    updated_at: str = ""


class AgentModelProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    provider: ProviderName
    base_url: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=160)
    api_key: str = Field(min_length=1, max_length=4096)
    enabled: bool = True
    is_default: bool = False


class AgentModelProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    provider: Optional[ProviderName] = None
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=512)
    model: Optional[str] = Field(default=None, min_length=1, max_length=160)
    api_key: Optional[str] = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None

    @model_validator(mode="after")
    def validate_secret_update(self):
        if self.clear_api_key and self.api_key:
            raise ValueError("clear_api_key 与 api_key 不能同时设置")
        return self


class AgentModelProfileTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = ""
    provider: Optional[ProviderName] = None
    base_url: str = ""
    model: str = ""
    api_key: str = ""


class AgentModelProfileTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    message: str


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _cipher() -> Fernet:
    secret = str(settings.ai_model_config_secret or "").strip().encode("utf-8")
    if not secret:
        raise HTTPException(status_code=503, detail="未配置 AI_MODEL_CONFIG_SECRET，不能保存个人模型 API Key")
    try:
        return Fernet(secret)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="AI_MODEL_CONFIG_SECRET 不是有效的 Fernet 密钥") from exc


def _encrypt_api_key(api_key: str) -> str:
    return _cipher().encrypt(str(api_key).encode("utf-8")).decode("utf-8")


def _decrypt_api_key(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _cipher().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(status_code=503, detail="个人模型 API Key 无法解密，请重新配置该模型") from exc


def _normalize_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if not re.match(r"^https?://", url, flags=re.I):
        raise HTTPException(status_code=422, detail="Base URL 必须以 http:// 或 https:// 开头")
    return url


def _system_view(*, is_default: bool = False) -> AgentModelProfileView:
    enabled = bool(
        settings.ai_enabled
        and str(settings.ai_base_url or "").strip()
        and str(settings.ai_api_key or "").strip()
        and str(settings.ai_model or "").strip()
        and str(settings.ai_provider or "") in {"deepseek", "openai_compatible"}
    )
    display = str(settings.ai_model or "系统默认模型").strip() or "系统默认模型"
    return AgentModelProfileView(
        id=SYSTEM_PROFILE_ID,
        display_name=display,
        source="system",
        provider=str(settings.ai_provider or "openai_compatible"),
        base_url=str(settings.ai_base_url or "").strip().rstrip("/"),
        model=str(settings.ai_model or "").strip(),
        enabled=enabled,
        is_default=is_default,
        has_api_key=bool(str(settings.ai_api_key or "").strip()),
    )


def _system_glm_view(*, is_default: bool = False) -> AgentModelProfileView:
    enabled = bool(
        settings.ai_glm_enabled
        and str(settings.ai_glm_base_url or "").strip()
        and str(settings.ai_glm_api_key or "").strip()
        and str(settings.ai_glm_model or "").strip()
    )
    return AgentModelProfileView(
        id=SYSTEM_GLM_PROFILE_ID,
        display_name="GLM-5.2",
        source="system",
        provider="openai_compatible",
        base_url=str(settings.ai_glm_base_url or "").strip().rstrip("/"),
        model=str(settings.ai_glm_model or "").strip(),
        enabled=enabled,
        is_default=is_default,
        has_api_key=bool(str(settings.ai_glm_api_key or "").strip()),
    )


def _system_views(*, has_personal_default: bool = False) -> list[AgentModelProfileView]:
    glm = _system_glm_view()
    glm_is_default = not has_personal_default and glm.enabled
    views = [_system_view(is_default=not has_personal_default and not glm.enabled)]
    if settings.ai_glm_enabled:
        views.append(glm.model_copy(update={"is_default": glm_is_default}))
    return views


def _personal_view(row: dict[str, Any]) -> AgentModelProfileView:
    return AgentModelProfileView(
        id=str(row.get("id") or ""),
        display_name=str(row.get("display_name") or ""),
        source="personal",
        provider=str(row.get("provider") or "openai_compatible"),
        base_url=str(row.get("base_url") or ""),
        model=str(row.get("model_name") or ""),
        enabled=bool(row.get("enabled")),
        is_default=bool(row.get("is_default")),
        has_api_key=bool(str(row.get("api_key_ciphertext") or "")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def list_model_profiles() -> list[AgentModelProfileView]:
    personal = [_personal_view(row) for row in agent_model_profile_repo.list_records()]
    has_personal_default = any(item.enabled and item.is_default for item in personal)
    return [*_system_views(has_personal_default=has_personal_default), *personal]


def create_model_profile(payload: AgentModelProfileCreate) -> AgentModelProfileView:
    profile_id = f"personal-{uuid4().hex[:16]}"
    row = agent_model_profile_repo.upsert_record(profile_id, {
        "display_name": payload.display_name.strip(),
        "provider": payload.provider,
        "base_url": _normalize_url(payload.base_url),
        "model_name": payload.model.strip(),
        "api_key_ciphertext": _encrypt_api_key(payload.api_key.strip()),
        "enabled": payload.enabled,
        "is_default": payload.is_default,
    })
    return _personal_view(row)


def update_model_profile(profile_id: str, payload: AgentModelProfilePatch) -> AgentModelProfileView:
    if profile_id in _SYSTEM_PROFILE_IDS:
        raise HTTPException(status_code=403, detail="系统模型不可修改")
    existing = agent_model_profile_repo.get_record(profile_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    values: dict[str, Any] = {}
    for source, target in (("display_name", "display_name"), ("provider", "provider"), ("model", "model_name"), ("enabled", "enabled"), ("is_default", "is_default")):
        value = getattr(payload, source)
        if value is not None:
            values[target] = value.strip() if isinstance(value, str) else value
    if payload.base_url is not None:
        values["base_url"] = _normalize_url(payload.base_url)
    if payload.clear_api_key:
        values["api_key_ciphertext"] = ""
    elif payload.api_key is not None and payload.api_key.strip():
        values["api_key_ciphertext"] = _encrypt_api_key(payload.api_key.strip())
    row = agent_model_profile_repo.upsert_record(profile_id, values)
    return _personal_view(row)


def delete_model_profile(profile_id: str) -> None:
    if profile_id in _SYSTEM_PROFILE_IDS:
        raise HTTPException(status_code=403, detail="系统模型不可删除")
    if not agent_model_profile_repo.delete_record(profile_id):
        raise HTTPException(status_code=404, detail="模型配置不存在")


def resolve_model_runtime(profile_id: str = "") -> tuple[AgentModelProfileView, LLMRuntimeConfig]:
    requested = str(profile_id or "").strip()
    if requested == SYSTEM_GLM_PROFILE_ID:
        view = _system_glm_view()
        if not view.enabled:
            raise HTTPException(status_code=503, detail="GLM 系统模型不可用，请检查 GLM_ENABLED、GLM_BASE_URL、GLM_API_KEY 和 GLM_MODEL")
        return view, LLMRuntimeConfig(
            provider=view.provider,
            base_url=view.base_url,
            api_key=str(settings.ai_glm_api_key or "").strip(),
            model=view.model,
            thinking_enabled=bool(settings.ai_glm_thinking_enabled),
            timeout_s=int(settings.ai_timeout_s or 60),
        )
    if requested and requested != SYSTEM_PROFILE_ID:
        row = agent_model_profile_repo.get_record(requested)
        if row is None:
            raise HTTPException(status_code=422, detail="所选模型配置不存在，请重新选择")
        view = _personal_view(row)
        if not view.enabled:
            raise HTTPException(status_code=422, detail="所选模型配置已禁用，请重新选择")
        api_key = _decrypt_api_key(str(row.get("api_key_ciphertext") or ""))
        if not api_key:
            raise HTTPException(status_code=422, detail="所选模型未配置 API Key")
        return view, LLMRuntimeConfig(
            provider=view.provider,
            base_url=view.base_url,
            api_key=api_key,
            model=view.model,
            thinking_enabled=bool(settings.ai_thinking_enabled),
            timeout_s=int(settings.ai_timeout_s or 60),
        )
    if not requested:
        personal_default = next((row for row in agent_model_profile_repo.list_records() if row.get("enabled") and row.get("is_default")), None)
        if personal_default is not None:
            return resolve_model_runtime(str(personal_default.get("id") or ""))
        glm = _system_glm_view()
        if glm.enabled:
            return resolve_model_runtime(SYSTEM_GLM_PROFILE_ID)
    view = _system_view()
    if not view.enabled:
        raise HTTPException(status_code=503, detail="系统默认模型不可用，请先配置模型")
    return view, LLMRuntimeConfig.from_settings()


def _safe_connection_error(exc: Exception, *, secrets: tuple[str, ...] = ()) -> str:
    message = str(exc)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"(?i)(authorization|api[-_ ]?key)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", message)
    message = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+\-/=]+", "Bearer [REDACTED]", message)
    message = re.sub(r"(https?://)[^/@\s]+@", r"\1[REDACTED]@", message)
    return message[:300]


async def test_model_profile(payload: AgentModelProfileTestRequest) -> AgentModelProfileTestResponse:
    if payload.profile_id:
        _, runtime = resolve_model_runtime(payload.profile_id)
    else:
        if not (payload.provider and payload.base_url.strip() and payload.model.strip() and payload.api_key.strip()):
            raise HTTPException(status_code=422, detail="测试未保存模型时必须填写 Provider、Base URL、模型 ID 和 API Key")
        runtime = LLMRuntimeConfig(
            provider=payload.provider,
            base_url=_normalize_url(payload.base_url),
            api_key=payload.api_key.strip(),
            model=payload.model.strip(),
            thinking_enabled=False,
            timeout_s=min(int(settings.ai_timeout_s or 60), 30),
        )
    client = get_llm_provider_client(runtime=runtime)
    if client is None:
        return AgentModelProfileTestResponse(success=False, message="不支持的模型 Provider")
    try:
        text = await client.chat_text(messages=[{"role": "user", "content": "只回复 OK"}], temperature=0)
        return AgentModelProfileTestResponse(success=bool(text.strip()), message="连接成功" if text.strip() else "模型未返回内容")
    except Exception as exc:  # noqa: BLE001
        return AgentModelProfileTestResponse(
            success=False,
            message=f"连接失败：{_safe_connection_error(exc, secrets=(runtime.api_key,))}",
        )
