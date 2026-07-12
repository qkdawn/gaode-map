from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .capability_catalog import AnalysisCapability, list_analysis_capabilities


CapabilityIntentAction = Literal["none", "open_configuration", "explain_unavailable"]


class CapabilityIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


class CapabilityIntentResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: bool = False
    capability_id: str = ""
    action: CapabilityIntentAction = "none"
    matched_phrase: str = ""
    reason: str = ""


_SEPARATORS = re.compile(r"[\s，。！？、,.!?;；:：'\"“”‘’()（）【】\[\]{}]+")


def _normalize(value: str) -> str:
    return _SEPARATORS.sub("", str(value or "")).lower()


def _candidate_phrases(capability: AnalysisCapability) -> list[tuple[str, str]]:
    return sorted(
        (
            (_normalize(phrase), phrase)
            for phrase in capability.intent_phrases
            if _normalize(phrase)
        ),
        key=lambda item: (-len(item[0]), item[0]),
    )


def resolve_capability_intent(message: str) -> CapabilityIntentResolution:
    """Resolve only explicit capability invocation phrases; ordinary questions stay in chat."""

    normalized = _normalize(message)
    if not normalized:
        return CapabilityIntentResolution()

    matches: list[tuple[int, str, AnalysisCapability, str]] = []
    for capability in list_analysis_capabilities():
        for phrase, source_phrase in _candidate_phrases(capability):
            if phrase in normalized:
                matches.append((len(phrase), capability.id, capability, source_phrase))
                break
    if not matches:
        return CapabilityIntentResolution()

    _, _, capability, matched_phrase = max(matches, key=lambda item: (item[0], item[1]))
    if capability.status != "available":
        return CapabilityIntentResolution(
            matched=True,
            capability_id=capability.id,
            action="explain_unavailable",
            matched_phrase=matched_phrase,
            reason=capability.availability_note,
        )
    return CapabilityIntentResolution(
        matched=True,
        capability_id=capability.id,
        action="open_configuration",
        matched_phrase=matched_phrase,
        reason="已识别明确的能力执行意图；先打开统一配置页检查输入并锁定运行版本。",
    )
