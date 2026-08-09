from __future__ import annotations

import asyncio
import inspect
import json
import re
from contextlib import suppress
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List

from core.config import settings
from modules.documents import build_project_evidence_dossier

from .auditor import audit_execution
from .context_builder import build_context_bundle, build_context_summary
from .gate import latest_user_message, run_gate
from .finalizer_evidence import build_finalizer_evidence_pack
from .latency import LatencyRecorder
from .memory import create_working_memory
from .providers.client import LLMRuntimeConfig
from .providers.langgraph_react import run_langgraph_react_loop
from .providers.llm_provider import (
    generate_answer_output_with_llm,
    is_llm_enabled,
    run_gate_with_llm,
    run_tool_allocator_with_llm,
)
from .providers.tool_loop import tool_allocation_candidates
from .schemas import (
    AgentMessage,
    AgentPlanEnvelope,
    AgentTranslationPack,
    AgentThinkingItem,
    AgentTurnDiagnostics,
    AgentTurnOutput,
    AgentTurnRequest,
    AgentTurnResponse,
    AgentTurnStreamEvent,
    AuditResult,
    EffectiveExecutionProfile,
    FinalProductRecheckDecision,
    FirstProductRecheckDecision,
    ProductDraftInventory,
    ToolAllocationDecision,
    ToolLoopResult,
    SpatialEvidencePacket,
)
from .selected_sources import selected_sources_artifact_from_items
from .skill_dependencies import (
    cultural_tourism_child_request,
    formal_specialist_request,
    market_audience_child_request,
    resolve_skill_dependencies,
    spatial_evidence_child_request,
    skill_instruction,
)
from .synthesizer import (
    build_answer_evidence_payload,
    build_answer_fallback,
    build_citations,
    enrich_answer_output,
)
from .tools import get_tool_registry

StreamEmit = Callable[[str, dict[str, Any]], Awaitable[None] | None]

_VISUAL_SNAPSHOT_LIMIT = 12
_VISUAL_SNAPSHOT_MAX_DATA_URL_CHARS = 2_500_000
REQUIRED_MARKET_WEB_CATEGORIES = (
    "统计",
    "政策规划",
    "文保档案",
    "片区供给",
    "直接及区域竞品",
    "文化机构或机构采购",
    "公开价格与活动",
)


def _visual_snapshot_inputs(payload: AgentTurnRequest) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    images: List[Dict[str, Any]] = []
    metadata: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for raw in list(payload.visual_snapshots or [])[:_VISUAL_SNAPSHOT_LIMIT]:
        kind = str(raw.kind or "").strip()
        title = str(raw.title or kind or "地图快照").strip()
        data_url = str(raw.data_url or "").strip()
        item_warnings = [str(item).strip() for item in (raw.warnings or []) if str(item).strip()]
        if not data_url.startswith("data:image/"):
            warnings.extend(item_warnings)
            if kind or title:
                warnings.append(f"{title} 未传入有效图片，已跳过。")
            continue
        if len(data_url) > _VISUAL_SNAPSHOT_MAX_DATA_URL_CHARS:
            warnings.extend(item_warnings)
            warnings.append(f"{title} 图片过大，已跳过直传。")
            continue
        meta = {
            "snapshot_id": str(raw.snapshot_id or "").strip(),
            "kind": kind,
            "title": title,
            "source": str(raw.source or "frontend_map").strip(),
            "captured_at": str(raw.captured_at or "").strip(),
            "bounds": dict(raw.bounds or {}),
            "warnings": item_warnings,
        }
        metadata.append(meta)
        images.append({**meta, "data_url": data_url})
    if len(payload.visual_snapshots or []) > _VISUAL_SNAPSHOT_LIMIT:
        warnings.append(f"地图视觉快照超过 {_VISUAL_SNAPSHOT_LIMIT} 张，已只使用前 {_VISUAL_SNAPSHOT_LIMIT} 张。")
    return images, metadata, warnings


_STAGE_LABELS = {
    "gating": "门卫判断",
    "clarifying": "生成追问",
    "executing": "执行工具",
    "synthesizing": "综合分析",
    "answered": "已完成",
    "failed": "失败",
    "requires_clarification": "需要补充信息",
    "requires_risk_confirmation": "等待风险确认",
}

async def _maybe_emit(emit: StreamEmit | None, event_type: str, payload: dict[str, Any]) -> None:
    if emit is None:
        return
    outcome = emit(event_type, payload)
    if inspect.isawaitable(outcome):
        await outcome


async def _emit_status(emit: StreamEmit | None, stage: str) -> None:
    await _maybe_emit(emit, "status", {"stage": stage, "label": _STAGE_LABELS.get(stage, stage)})


def _timeline_item(seed: dict[str, Any], fallback_id: str) -> AgentThinkingItem:
    payload = dict(seed or {})
    payload.setdefault("id", fallback_id)
    payload.setdefault("phase", "")
    payload.setdefault("title", "处理中")
    payload.setdefault("detail", "")
    payload.setdefault("display_text", "")
    payload.setdefault("state", "pending")
    return AgentThinkingItem(**payload)


def _trace_to_thinking_payload(seed: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    payload = dict(seed or {})
    tool_name = str(payload.get("tool_name") or "unknown_tool").strip()
    status = str(payload.get("status") or "").strip()
    state = "completed" if status == "success" else ("failed" if status in {"failed", "blocked", "skipped"} else "active")
    title_status = {
        "start": "开始调用",
        "success": "执行成功",
        "failed": "执行失败",
        "blocked": "等待确认",
        "skipped": "已跳过",
    }.get(status, status or "执行中")
    items: List[str] = []
    arguments_summary = str(payload.get("arguments_summary") or "").strip()
    result_summary = str(payload.get("result_summary") or "").strip()
    produced_artifacts = [str(item) for item in (payload.get("produced_artifacts") or []) if str(item).strip()]
    if arguments_summary:
        items.append(f"参数：{arguments_summary}")
    if result_summary:
        items.append(f"结果：{result_summary}")
    if payload.get("evidence_count") not in (None, ""):
        items.append(f"证据：{payload.get('evidence_count')} 条")
    if payload.get("warning_count") not in (None, "", 0):
        items.append(f"警告：{payload.get('warning_count')} 条")
    if produced_artifacts:
        items.append(f"产物：{'、'.join(produced_artifacts[:6])}")
    phase = str(payload.get("phase") or "executing")
    return {
        "id": str(payload.get("id") or payload.get("call_id") or fallback_id),
        "phase": phase,
        "title": f"{title_status} {tool_name}",
        "detail": str(payload.get("message") or payload.get("reason") or ""),
        "display_text": str(payload.get("display_text") or ""),
        "items": items,
        "meta": {
            "tool_name": tool_name,
            "status": status,
            "call_id": str(payload.get("call_id") or ""),
        },
        "state": state,
    }


def _build_diagnostics(
    *,
    memory,
    used_tools: List[str] | None = None,
    citations: List[str] | None = None,
    error: str = "",
    thinking_timeline: List[AgentThinkingItem] | None = None,
    research_notes: List[str] | None = None,
    planning_summary: str = "",
    audit_summary: str = "",
    translation_pack: AgentTranslationPack | None = None,
    latency_ms: Dict[str, int] | None = None,
) -> AgentTurnDiagnostics:
    return AgentTurnDiagnostics(
        execution_trace=list(memory.execution_trace or []),
        used_tools=list(used_tools or []),
        citations=list(citations or []),
        research_notes=list(research_notes if research_notes is not None else (memory.research_notes or [])),
        audit_issues=list(memory.audit_issues or []),
        thinking_timeline=list(thinking_timeline or []),
        planning_summary=str(planning_summary or ""),
        audit_summary=str(audit_summary or ""),
        translation_pack=translation_pack or AgentTranslationPack(),
        latency_ms=dict(latency_ms or {}),
        error=str(error or ""),
    )


def _tool_loop_limits() -> tuple[int | None, int | None]:
    configured_steps = int(settings.ai_max_tool_steps or 0)
    max_steps = max(1, configured_steps) if configured_steps > 0 else None
    max_errors = max(1, int(settings.ai_max_tool_errors or 2))
    return max_steps, max_errors


def _build_loop_plan_summary(*, used_tools: List[str], assistant_summary: str = "") -> str:
    if used_tools:
        tool_text = " -> ".join(list(dict.fromkeys([str(item).strip() for item in used_tools if str(item).strip()]))[:5])
        return f"本轮按需调用工具补证据：{tool_text}。"
    if str(assistant_summary or "").strip():
        return "现有证据已基本够用，本轮未继续调用工具。"
    return "根据当前问题复用已有证据并按需补充必要工具。"


def _build_rule_audit_summary(audit: AuditResult) -> str:
    if list(audit.missing_evidence or []):
        missing = "、".join([str(item).strip() for item in list(audit.missing_evidence or [])[:3] if str(item).strip()])
        return f"当前回答仍有证据缺口：{missing}。"
    if list(audit.issues or []):
        issue = next((str(item).strip() for item in audit.issues if str(item).strip()), "")
        if issue:
            return f"当前回答需要标注边界：{issue}"
    return "当前证据足以支持直接回答，并已保留必要解释边界。"


def _merge_notes(existing: List[str], incoming: List[Any]) -> List[str]:
    seen = {str(item).strip() for item in existing if str(item).strip()}
    merged = list(existing or [])
    for item in incoming or []:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


_FORMAL_SPECIALIST_ROLES = (
    "spatial_structure",
    "positioning_product",
    "spatial_function_programming",
    "operations_phasing",
)
_TERMINAL_RECHECK_FORBIDDEN_TEXT = (
    "revision_required",
    "third rewrite",
    "third_rewrite",
    "第三次返写",
    "第三轮返写",
    "继续返写",
    "再次返写",
)


def _market_public_web_coverage_error(artifacts: dict[str, Any]) -> str:
    public_sources = artifacts.get("public_web_sources")
    if not isinstance(public_sources, dict):
        return "市场发现未返回 public_web_sources，不能登记完成"
    if str(public_sources.get("coverage_status") or "").strip() not in {
        "usable_sources_found",
        "searched_no_usable_source",
    }:
        return "市场发现的 public_web_sources.coverage_status 未正常闭合"
    category_coverage = public_sources.get("category_coverage")
    if not isinstance(category_coverage, list):
        return "市场发现缺少 public_web_sources.category_coverage，不能登记完成"
    allowed_statuses = {"usable_sources_found", "searched_no_usable_source"}
    statuses = {
        str(item.get("category") or "").strip(): str(item.get("coverage_status") or "").strip()
        for item in category_coverage
        if isinstance(item, dict) and str(item.get("category") or "").strip()
    }
    missing = [category for category in REQUIRED_MARKET_WEB_CATEGORIES if category not in statuses]
    invalid = [category for category in REQUIRED_MARKET_WEB_CATEGORIES if statuses.get(category) not in allowed_statuses]
    if missing:
        return f"市场公开检索类别覆盖不完整，缺少：{'、'.join(missing)}"
    if invalid:
        return f"市场公开检索类别未正常闭合：{'、'.join(invalid)}"
    return ""


def _market_discovery_contract_error(discovery: Any) -> str:
    if not isinstance(discovery, dict):
        return "市场发现工件不存在"
    if discovery.get("stage") != "market_discovery":
        return "市场发现工件阶段无效"
    if discovery.get("status") != "completed":
        return "市场发现工件尚未完成"
    artifacts = discovery.get("artifacts")
    if not isinstance(artifacts, dict):
        return "市场发现工件缺少结构化 artifacts"
    return _market_public_web_coverage_error(artifacts)


def _product_recheck_payload(result, artifact_key: str) -> Any:
    artifacts = dict(result.artifacts or {})
    existing = artifacts.get(artifact_key)
    if existing is not None:
        return existing
    text = str(result.assistant_summary or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed.get(artifact_key, parsed)


def _new_loop_artifacts(result, initial_artifacts: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(result.artifacts or {}).items()
        if key not in initial_artifacts or initial_artifacts[key] != value
    }


def _specialist_artifacts(memory) -> dict[str, Any]:
    return {
        role: memory.artifacts[role]
        for role in _FORMAL_SPECIALIST_ROLES
        if isinstance(memory.artifacts.get(role), dict)
    }


def _product_inventory_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    artifacts = value.get("artifacts") if isinstance(value.get("artifacts"), dict) else value
    return artifacts.get("product_inventory") if isinstance(artifacts, dict) else None


def _record_specialist_result(memory, *, role: str, result, revision: bool) -> None:
    current = memory.artifacts.get(role)
    versions = list(current.get("versions") or []) if isinstance(current, dict) else []
    version = len(versions) + 1
    versions.append({
        "version": version,
        "summary": str(result.assistant_summary or "").strip(),
        "artifacts": dict(result.artifacts or {}),
        "research_notes": list(result.research_notes or []),
        "used_tools": list(result.used_tools or []),
        "revision": bool(revision),
    })
    memory.artifacts[role] = {
        "role": role,
        "status": "completed",
        "current_version": version,
        "summary": str(result.assistant_summary or "").strip(),
        "artifacts": dict(result.artifacts or {}),
        "versions": versions,
    }
    memory.execution_trace.extend(list(result.execution_trace or []))
    memory.tool_results.extend(list(result.tool_results or []))
    memory.research_notes = _merge_notes(memory.research_notes, list(result.research_notes or []))


async def _run_formal_specialist_roles(
    *,
    payload: AgentTurnRequest,
    context,
    memory,
    llm_runtime: LLMRuntimeConfig | None,
    emit_thinking,
    roles: tuple[str, ...] = _FORMAL_SPECIALIST_ROLES,
    revision_context: dict[str, Any] | None = None,
) -> str:
    """Run each formal specialist in its own allocated tool loop."""

    discovery = memory.artifacts.get("market_audience_research")
    if discovery is None:
        return ""
    discovery_error = _market_discovery_contract_error(discovery)
    if discovery_error:
        return discovery_error
    max_steps_override, max_errors_override = _tool_loop_limits()
    for role in roles:
        is_revision = revision_context is not None
        upstream = {
            "cultural_tourism_research": memory.artifacts.get("cultural_tourism_research"),
            "market_audience_research": discovery,
            **_specialist_artifacts(memory),
        }
        prompt = formal_specialist_request(
            payload,
            role=role,
            upstream_artifacts=upstream,
            revision_context=revision_context,
        )
        await emit_thinking(
            {
                "phase": "executing",
                "title": f"启动专项角色：{role}",
                "detail": "该角色在独立工具授权和独立工具循环中形成自己的本轮工件。",
                "state": "active",
            },
            f"formal-specialist:{role}:{'revision' if is_revision else 'draft'}",
        )
        role_payload = payload.model_copy(
            update={
                "messages": [
                    *[item.model_copy(deep=True) for item in payload.messages if item.role != "system"],
                    AgentMessage(role="user", content=prompt),
                ]
            }
        )
        try:
            allowed_tools = await _allocate_tools_for_role(
                payload=role_payload,
                context=context,
                memory=memory,
                llm_runtime=llm_runtime,
                agent_role=role,
                task=prompt,
                emit_thinking=emit_thinking,
            )
        except Exception as exc:
            return f"专项角色 {role} 的工具授权失败：{exc}"
        initial_artifacts = {
            **dict(memory.artifacts or {}),
            "formal_specialist_role": role,
            "formal_specialist_upstream": upstream,
            "product_recheck_revision": revision_context or {},
        }
        try:
            result = await run_langgraph_react_loop(
                messages=role_payload.messages,
                snapshot=payload.analysis_snapshot,
                context=context,
                registry=get_tool_registry(),
                governance_mode=payload.governance_mode,
                confirmed_tools=list(payload.risk_confirmations or []),
                include_secondary_tools=True,
                max_steps_override=max_steps_override,
                max_errors_override=max_errors_override,
                initial_artifacts=initial_artifacts,
                llm_runtime=llm_runtime,
                system_instruction=skill_instruction("spatial-business-analyst"),
                allowed_tool_names=allowed_tools,
            )
        except Exception as exc:
            return f"专项角色 {role} 调用失败：{exc}"
        if result.status != "completed":
            return result.error or result.stop_reason or f"专项角色 {role} 未完成"
        result.artifacts = _new_loop_artifacts(result, initial_artifacts)
        if role == "positioning_product":
            try:
                inventory = ProductDraftInventory.model_validate(_product_inventory_payload(result.artifacts))
            except Exception as exc:
                return f"定位产品草案缺少合法的完整 product_inventory：{exc}"
            current_inventory_payload = _product_inventory_payload(memory.artifacts.get(role))
            if revision_context is not None and current_inventory_payload is not None:
                current_inventory = ProductDraftInventory.model_validate(current_inventory_payload)
                current_ids = {item.product_id.strip() for item in current_inventory.products}
                revised_ids = {item.product_id.strip() for item in inventory.products}
                if revised_ids != current_ids:
                    return "定位产品定向返写必须保留同一组 product_id，不得新增或静默删除产品"
            result.artifacts["product_inventory"] = inventory.model_dump(mode="json")
        _record_specialist_result(memory, role=role, result=result, revision=is_revision)
        await emit_thinking(
            {
                "phase": "executing",
                "title": f"专项角色完成：{role}",
                "detail": "已持久化该角色的本轮完整工件，供下一专业角色和再校核消费。",
                "state": "completed",
            },
            f"formal-specialist:{role}:{'revision' if is_revision else 'draft'}",
        )
    return ""


async def _allocate_tools_for_role(
    *,
    payload: AgentTurnRequest,
    context,
    memory,
    llm_runtime: LLMRuntimeConfig | None,
    agent_role: str,
    task: str,
    emit_thinking,
) -> List[str]:
    registry = get_tool_registry()
    candidates = tool_allocation_candidates(registry, agent_role=agent_role)
    candidate_payload = [
        {
            "name": name,
            "description": item.spec.description,
            "evidence_contract": list(item.spec.evidence_contract or []),
            "cautions": list(item.spec.cautions or []),
        }
        for name, item in candidates.items()
    ]
    try:
        proposed = await run_tool_allocator_with_llm(
            messages=payload.messages,
            snapshot=payload.analysis_snapshot,
            context=context,
            agent_role=agent_role,
            task=task,
            candidate_tools=candidate_payload,
            emit=None,
            runtime=llm_runtime,
        )
        allowed = [name for name in proposed.allowed_tools if name in candidates]
        if not allowed:
            allowed = sorted(candidates)
            rationale = str(proposed.rationale or "").strip()
            proposed = proposed.model_copy(update={
                "rationale": f"{rationale}；未选中具体工具，使用该角色的受限候选集。".lstrip("；"),
            })
        decision = proposed.model_copy(update={"agent_role": agent_role, "allowed_tools": allowed})
    except Exception:
        decision = ToolAllocationDecision(
            agent_role=agent_role,
            allowed_tools=sorted(candidates),
            rationale="工具分派不可用，使用该角色的受限候选集。",
        )
    allocations = memory.artifacts.setdefault("tool_allocations", {})
    role_allocations = allocations.setdefault(agent_role, [])
    role_allocations.append(decision.model_dump(mode="json"))
    await emit_thinking(
        {
            "phase": "tool_allocation",
            "title": f"工具授权：{agent_role}",
            "detail": decision.rationale or "已按任务与证据目标生成工具授权。",
            "items": list(decision.allowed_tools),
            "state": "completed",
        },
        f"tool-allocation:{agent_role}",
    )
    return list(decision.allowed_tools)


async def _run_required_skill_dependencies(
    *,
    payload: AgentTurnRequest,
    effective_profile: EffectiveExecutionProfile | None,
    context,
    memory,
    llm_runtime: LLMRuntimeConfig | None,
    emit_thinking,
) -> str:
    """Execute declared pre-parent research stages and publish their artifacts."""

    dependencies = resolve_skill_dependencies(payload, effective_profile)
    for dependency in dependencies:
        stage = dependency.stage
        await emit_thinking(
            {
                "phase": "preflight",
                "title": f"启动研究阶段：{dependency.skill_id}/{stage}",
                "detail": "前置研究将在父级分析前完成，并把可复核工件交给后续阶段。",
                "state": "active",
            },
            f"dependency-start:{dependency.skill_id}:{stage}",
        )
        if dependency.skill_id == "cultural-tourism-theme-research" and stage == "preflight":
            child_instruction = cultural_tourism_child_request(payload)
            artifact_key = "cultural_tourism_research"
            agent_role = "cultural_tourism_research"
            task = "完成八类资源、周边关系、主题判断与公开网页核验；仅使用能支撑当前研究的工具。"
        elif dependency.skill_id == "spatial-market-audience-research" and stage == "market_discovery":
            child_instruction = market_audience_child_request(payload, stage=stage)
            artifact_key = "market_audience_research"
            agent_role = "market_audience_research"
            task = "完成项目条件、候选客群、市场母体、竞争/替代供给与需求或公共服务履约的发现研究。"
        elif dependency.skill_id == "spatial-evidence-research" and stage == "decision_evidence":
            child_instruction = spatial_evidence_child_request(payload, research_requests=dependency.research_requests)
            artifact_key = "spatial_evidence_research"
            agent_role = "spatial_evidence_research"
            task = "围绕已确认的决策问题按需查询项目材料、空间数据、指标或公开来源，并只输出可被报告消费的证据备忘录。"
        else:
            return f"未注册前置 Skill 执行器：{dependency.skill_id}"
        child_snapshot = payload.analysis_snapshot.model_copy(
            deep=True,
            update={
                "context": {
                    **dict(payload.analysis_snapshot.context or {}),
                    "history_id": str(payload.history_id or "").strip(),
                }
            },
        )
        child_messages = [
            *[item.model_copy(deep=True) for item in payload.messages if item.role != "system"],
            AgentMessage(role="user", content=child_instruction),
        ]
        try:
            child_allowed_tools = await _allocate_tools_for_role(
                payload=payload.model_copy(update={"messages": child_messages}),
                context=context,
                memory=memory,
                llm_runtime=llm_runtime,
                agent_role=agent_role,
                task=task,
                emit_thinking=emit_thinking,
            )
        except Exception as exc:
            return f"前置 Skill {dependency.skill_id} 的工具授权失败：{exc}"
        max_steps_override, max_errors_override = _tool_loop_limits()
        child_initial_artifacts = dict(memory.artifacts or {})
        try:
            child = await run_langgraph_react_loop(
                messages=child_messages,
                snapshot=child_snapshot,
                context=context,
                registry=get_tool_registry(),
                governance_mode=payload.governance_mode,
                confirmed_tools=list(payload.risk_confirmations or []),
                include_secondary_tools=True,
                max_steps_override=max_steps_override,
                max_errors_override=max_errors_override,
                initial_artifacts=child_initial_artifacts,
                llm_runtime=llm_runtime,
                system_instruction=skill_instruction(dependency.skill_id),
                allowed_tool_names=child_allowed_tools,
            )
        except Exception as exc:
            return f"前置 Skill {dependency.skill_id} 调用失败：{exc}"
        if child.status != "completed":
            return child.error or child.stop_reason or f"前置 Skill {dependency.skill_id} 未完成"
        child.artifacts = _new_loop_artifacts(child, child_initial_artifacts)
        if artifact_key == "market_audience_research":
            coverage_error = _market_public_web_coverage_error(dict(child.artifacts or {}))
            if coverage_error:
                return coverage_error
        if artifact_key == "spatial_evidence_research":
            try:
                packet = SpatialEvidencePacket.model_validate(child.artifacts.get("spatial_evidence_packet"))
            except Exception as exc:
                return f"空间证据研究未返回合法 spatial_evidence_packet：{exc}"
            child.artifacts["spatial_evidence_packet"] = packet.model_dump(mode="json")
        artifact = {
            "skill_id": dependency.skill_id,
            "status": "completed",
            "summary": str(child.assistant_summary or "").strip(),
            "artifacts": dict(child.artifacts or {}),
            "research_notes": list(child.research_notes or []),
            "used_tools": list(child.used_tools or []),
        }
        if artifact_key == "market_audience_research":
            artifact["stage"] = stage
            artifact["revision_budget"] = 1
            artifact["recheck_status"] = "pending_parent_drafts"
        memory.artifacts[artifact_key] = artifact
        memory.execution_trace.extend(list(child.execution_trace or []))
        memory.tool_results.extend(list(child.tool_results or []))
        memory.research_notes = _merge_notes(memory.research_notes, child.research_notes)
        await emit_thinking(
            {
                "phase": "preflight",
                "title": f"研究阶段完成：{dependency.skill_id}/{stage}",
                "detail": "已将本轮研究工件交给后续分析；后续阶段复用结论与来源，不重复伪造证据。",
                "state": "completed",
            },
            f"dependency-complete:{dependency.skill_id}:{stage}",
        )
    return ""


async def _run_market_product_recheck(
    *,
    payload: AgentTurnRequest,
    context,
    memory,
    parent_drafts: dict[str, Any],
    llm_runtime: LLMRuntimeConfig | None,
    emit_thinking,
) -> str:
    """Run first recheck, one bounded parent rewrite, then the final recheck."""

    discovery = memory.artifacts.get("market_audience_research")
    if discovery is None:
        return ""
    discovery_error = _market_discovery_contract_error(discovery)
    if discovery_error:
        return discovery_error
    draft_artifacts = parent_drafts.get("artifacts") if isinstance(parent_drafts, dict) else None
    missing_drafts = [
        role for role in _FORMAL_SPECIALIST_ROLES
        if not isinstance(draft_artifacts, dict) or not isinstance(draft_artifacts.get(role), dict)
    ]
    if missing_drafts:
        return f"产品市场再校核缺少本轮专项草案：{'、'.join(missing_drafts)}"
    try:
        draft_inventory = ProductDraftInventory.model_validate(
            _product_inventory_payload(draft_artifacts["positioning_product"])
        )
    except Exception as exc:
        return f"产品市场再校核缺少定位草案的完整 product_inventory：{exc}"
    draft_product_ids = {item.product_id.strip() for item in draft_inventory.products}
    await emit_thinking(
        {
            "phase": "executing",
            "title": "启动研究阶段：spatial-market-audience-research/product_recheck",
            "detail": "父级定位、空间和运营草案已形成，开始逐产品市场再校核。",
            "state": "active",
        },
        "market-product-recheck-start",
    )
    max_steps_override, max_errors_override = _tool_loop_limits()

    async def run_recheck(check_number: int, drafts: dict[str, Any]):
        messages = [
            *[item.model_copy(deep=True) for item in payload.messages if item.role != "system"],
            AgentMessage(
                role="user",
                content=market_audience_child_request(
                    payload,
                    stage="product_recheck",
                    parent_drafts=drafts,
                    check_number=check_number,
                ),
            ),
        ]
        allowed_tools = await _allocate_tools_for_role(
            payload=payload.model_copy(update={"messages": messages}),
            context=context,
            memory=memory,
            llm_runtime=llm_runtime,
            agent_role="market_audience_research",
            task=f"执行第 {check_number} 次产品市场再校核；第二次必须形成逐产品终局裁决。",
            emit_thinking=emit_thinking,
        )
        initial_artifacts = {
            **dict(memory.artifacts or {}),
            "parent_drafts": drafts,
            "product_recheck_number": check_number,
        }
        result = await run_langgraph_react_loop(
            messages=messages,
            snapshot=payload.analysis_snapshot,
            context=context,
            registry=get_tool_registry(),
            governance_mode=payload.governance_mode,
            confirmed_tools=list(payload.risk_confirmations or []),
            include_secondary_tools=True,
            max_steps_override=max_steps_override,
            max_errors_override=max_errors_override,
            initial_artifacts=initial_artifacts,
            llm_runtime=llm_runtime,
            system_instruction=skill_instruction("spatial-market-audience-research"),
            allowed_tool_names=allowed_tools,
        )
        result.artifacts = _new_loop_artifacts(result, initial_artifacts)
        return result

    try:
        first_check = await run_recheck(1, parent_drafts)
    except Exception as exc:
        return f"第一次产品市场再校核调用失败：{exc}"
    if first_check.status != "completed":
        return first_check.error or first_check.stop_reason or "第一次产品市场再校核未完成"

    first_payload = _product_recheck_payload(first_check, "first_product_recheck")
    try:
        first_decision = FirstProductRecheckDecision.model_validate(first_payload)
    except Exception as exc:
        return f"第一次产品市场再校核缺少合法的逐产品返写裁决：{exc}"
    first_product_ids = {item.product_id.strip() for item in first_decision.products}
    if first_product_ids != draft_product_ids:
        missing = sorted(draft_product_ids - first_product_ids)
        added = sorted(first_product_ids - draft_product_ids)
        return f"第一次产品市场再校核必须覆盖定位草案的完整产品清单；缺少={missing}，新增={added}"
    first_check.artifacts["first_product_recheck"] = first_decision.model_dump(mode="json")
    revision_roles = tuple(
        role
        for role in _FORMAL_SPECIALIST_ROLES
        if any(item.revision_required and role in item.owner_roles for item in first_decision.products)
    )

    revision_context = {
        "summary": str(first_check.assistant_summary or "").strip(),
        "artifacts": dict(first_check.artifacts or {}),
        "decision": first_decision.model_dump(mode="json"),
    }
    if revision_roles:
        revision_error = await _run_formal_specialist_roles(
            payload=payload,
            context=context,
            memory=memory,
            llm_runtime=llm_runtime,
            emit_thinking=emit_thinking,
            roles=revision_roles,
            revision_context=revision_context,
        )
        if revision_error:
            return revision_error
    revised_drafts = {
        "status": "revised_for_final_product_recheck",
        "artifacts": _specialist_artifacts(memory),
        "first_product_recheck": revision_context,
    }
    try:
        second_check = await run_recheck(2, revised_drafts)
    except Exception as exc:
        return f"第二次产品市场再校核调用失败：{exc}"
    if second_check.status != "completed":
        return second_check.error or second_check.stop_reason or "第二次产品市场再校核未完成"
    final_payload = _product_recheck_payload(second_check, "final_product_recheck")
    try:
        final_decision = FinalProductRecheckDecision.model_validate(final_payload)
    except Exception as exc:
        return f"第二次产品市场再校核缺少合法的逐产品终局裁决：{exc}"
    final_product_ids = {item.product_id.strip() for item in final_decision.products}
    if final_product_ids != first_product_ids:
        missing = sorted(first_product_ids - final_product_ids)
        added = sorted(final_product_ids - first_product_ids)
        return f"第二次产品市场再校核必须覆盖首轮同一组产品；缺少={missing}，新增={added}"
    terminal_text = f"{second_check.assistant_summary} {final_decision.model_dump(mode='json')}".lower()
    forbidden = next((item for item in _TERMINAL_RECHECK_FORBIDDEN_TEXT if item in terminal_text), "")
    if forbidden:
        return f"第二次产品市场再校核不是终局裁决，出现禁止的返写信号：{forbidden}"
    second_check.artifacts["final_product_recheck"] = final_decision.model_dump(mode="json")
    discovery["revision_budget"] = 0
    revision_used_tools: list[str] = []
    revision_notes: list[str] = []
    for role in revision_roles:
        artifact = memory.artifacts.get(role)
        versions = artifact.get("versions") if isinstance(artifact, dict) else []
        latest = versions[-1] if isinstance(versions, list) and versions else {}
        if isinstance(latest, dict):
            revision_used_tools.extend(str(item).strip() for item in latest.get("used_tools") or [] if str(item).strip())
            revision_notes.extend(str(item).strip() for item in latest.get("research_notes") or [] if str(item).strip())

    discovery["product_recheck"] = {
        "status": "completed",
        "stage": "product_recheck",
        "revision_budget": 0,
        "recheck_status": "second_check_completed",
        "checks": [
            {"number": 1, "summary": str(first_check.assistant_summary or "").strip(), "artifacts": dict(first_check.artifacts or {})},
            {"number": 2, "summary": str(second_check.assistant_summary or "").strip(), "artifacts": dict(second_check.artifacts or {})},
        ],
        "first_decision": first_decision.model_dump(mode="json"),
        "revision_roles": list(revision_roles),
        "revision": revised_drafts,
        "final_decision": final_decision.model_dump(mode="json"),
        "summary": str(second_check.assistant_summary or "").strip(),
        "artifacts": dict(second_check.artifacts or {}),
        "research_notes": _merge_notes(list(first_check.research_notes or []), [*revision_notes, *list(second_check.research_notes or [])]),
        "used_tools": list(dict.fromkeys([*list(first_check.used_tools or []), *revision_used_tools, *list(second_check.used_tools or [])])),
    }
    memory.execution_trace.extend([*list(first_check.execution_trace or []), *list(second_check.execution_trace or [])])
    memory.tool_results.extend([*list(first_check.tool_results or []), *list(second_check.tool_results or [])])
    memory.research_notes = _merge_notes(memory.research_notes, discovery["product_recheck"]["research_notes"])
    await emit_thinking(
        {
            "phase": "executing",
            "title": "产品市场再校核完成",
            "detail": "已完成第一次校核、唯一一次定向返写和第二次最终校核；主分析据此写入最终决策。",
            "state": "completed",
        },
        "market-product-recheck-complete",
    )
    return ""


async def _run_main_agent_loop(
    payload: AgentTurnRequest, *, emit: StreamEmit | None = None,
    llm_runtime: LLMRuntimeConfig | None = None,
    effective_profile: EffectiveExecutionProfile | None = None,
) -> AgentTurnResponse:
    latency = LatencyRecorder()
    snapshot = payload.analysis_snapshot
    question = latest_user_message(payload.messages)
    thinking_timeline: List[AgentThinkingItem] = []

    async def emit_event(event_type: str, event_payload: dict[str, Any]) -> None:
        if event_type == "trace":
            await _maybe_emit(emit, event_type, event_payload)
            event_payload = _trace_to_thinking_payload(
                event_payload,
                f"trace-{len(thinking_timeline) + 1}",
            )
        elif event_type != "thinking":
            await _maybe_emit(emit, event_type, event_payload)
            return
        item = _timeline_item(event_payload, str(event_payload.get("id") or f"thinking-{len(thinking_timeline) + 1}"))
        existing_index = next((index for index, current in enumerate(thinking_timeline) if current.id == item.id), -1)
        if existing_index >= 0:
            thinking_timeline[existing_index] = item
        else:
            thinking_timeline.append(item)
        await _maybe_emit(emit, "thinking", item.model_dump(mode="json"))

    async def emit_thinking(seed: dict[str, Any], fallback_id: str) -> None:
        payload = dict(seed or {})
        payload.setdefault("id", fallback_id)
        await emit_event("thinking", payload)

    context = build_context_bundle(snapshot)
    memory = create_working_memory()
    map_search_context = payload.map_search_context.as_artifact()
    if map_search_context:
        memory.artifacts["frontend_map_search_context"] = map_search_context
        context.available_artifacts.append("frontend_map_search_context")
        context.context_summary.available_context_sources.append("analysis:frontend_map_search_context")
        context.limits.append(
            "frontend_map_search_context 是本轮可检索地图空间对象源；最终回答只能引用 search_analysis_context/read_analysis_evidence_node 已读取到的 EvidenceNode 中的具体地名、格子、线段或 cell。"
        )
    selected_sources = payload.selected_sources_context.source_items()
    if selected_sources:
        memory.artifacts["selected_sources_context"] = selected_sources_artifact_from_items(selected_sources)
        context.available_artifacts.append("selected_sources_context")
        context.context_summary.available_context_sources.append("analysis:selected_sources_context")
        context.limits.append(
            "selected_sources_context 是本轮已选分析来源；主 Agent 分析来源时只能通过 list_selected_sources/search_selected_source_evidence/read_selected_source_evidence_node 使用这些来源，不得引用未选来源。"
        )
        project_dossier = build_project_evidence_dossier(selected_sources, question=question)
        if project_dossier.document_ids:
            memory.artifacts["project_evidence_dossier"] = project_dossier.model_dump(mode="json")
            context.available_artifacts.append("project_evidence_dossier")
            context.context_summary.available_context_sources.append("document:project_evidence_dossier")
            context.limits.append(
                "项目摘要 project_brief 是项目事实与约束锚点；design_vision 是设计意图；reference_document 只能补充。GIS 只能解释周边与验证机会，不能覆盖项目文档事实。"
            )
            memory.research_notes = _merge_notes(memory.research_notes, project_dossier.warnings)
            if project_dossier.status == "failed" and project_dossier.has_project_anchor:
                memory.research_notes = _merge_notes(
                    memory.research_notes,
                    ["核心项目文档未成功读取；最终回答必须明确失败，不能退化为自信的 GIS-only 项目结论。"],
                )
    visual_image_inputs, visual_snapshot_meta, visual_snapshot_warnings = _visual_snapshot_inputs(payload)
    if visual_snapshot_meta:
        memory.artifacts["visual_snapshots"] = visual_snapshot_meta
        context.available_artifacts.append("frontend_visual_snapshots")
        context.context_summary.available_context_sources.append("visual:frontend_map_snapshots")
        context.limits.append("地图视觉快照只能作为可见图层证据，不能伪装成后端指标计算结果。")
    memory.research_notes = _merge_notes(memory.research_notes, visual_snapshot_warnings)
    used_tools: List[str] = []
    planning_summary = ""
    audit_summary = ""
    latest_rule_audit = AuditResult()
    current_plan_envelope = AgentPlanEnvelope()
    translation_pack = AgentTranslationPack(status="skipped")

    await _maybe_emit(emit, "meta", {"conversation_id": str(payload.conversation_id or "")})
    await _emit_status(emit, "gating")
    if visual_snapshot_meta:
        snapshot_titles = [
            str(item.get("title") or item.get("kind") or "").strip()
            for item in visual_snapshot_meta
            if str(item.get("title") or item.get("kind") or "").strip()
        ]
        await emit_thinking(
            {
                "phase": "preflight",
                "title": "地图视觉快照已接收",
                "detail": f"本轮已收到 {len(visual_snapshot_meta)} 张前端地图快照：{'、'.join(snapshot_titles[:6])}。",
                "display_text": f"本轮已收到 {len(visual_snapshot_meta)} 张前端地图快照。",
                "items": snapshot_titles[:6],
                "state": "completed",
            },
            "visual-snapshots",
        )
    elif visual_snapshot_warnings:
        await emit_thinking(
            {
                "phase": "preflight",
                "title": "地图视觉快照未传入",
                "detail": "本轮未收到可直传模型的地图快照，已继续使用结构化指标分析。",
                "display_text": "本轮未收到可直传模型的地图快照。",
                "items": list(visual_snapshot_warnings or [])[:6],
                "state": "completed",
            },
            "visual-snapshots",
        )
    await emit_thinking(
        {
            "phase": "gating",
            "title": "门卫判断",
            "detail": "正在判断问题是否清晰、范围是否可执行。",
            "state": "active",
        },
        "gating-check",
    )

    if not (llm_runtime.configured() if llm_runtime else is_llm_enabled()):
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=AgentTurnDiagnostics(
                error="LLM provider 未启用或配置不完整，当前版本要求统一主链路工具循环与自然回答。",
                thinking_timeline=list(thinking_timeline or []),
                latency_ms=latency.finish(),
            ),
            context_summary=context.context_summary,
            plan=AgentPlanEnvelope(),
        )

    with latency.track("rule_gate"):
        gate = run_gate(payload.messages, snapshot)
    gate_fast_passed = gate.status == "pass"
    if gate_fast_passed:
        latency.set("gate", 0)
        await emit_thinking(
            {
                "phase": "gating",
                "title": "门卫快速通过",
                "detail": gate.summary or "问题和范围已满足执行条件，已跳过 LLM 门卫。",
                "display_text": gate.summary or "已跳过 LLM 门卫。",
                "state": "completed",
            },
            "gating-check",
        )
    else:
        try:
            with latency.track("gate"):
                gate_kwargs = dict(
                    messages=payload.messages,
                    snapshot=snapshot,
                    context=context,
                    emit=emit_event,
                )
                if llm_runtime is not None:
                    gate_kwargs["runtime"] = llm_runtime
                gate = await run_gate_with_llm(**gate_kwargs)
        except Exception as exc:
            await _emit_status(emit, "failed")
            return AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=AgentTurnDiagnostics(
                    error=f"Gatekeeper 调用失败：{exc}",
                    thinking_timeline=list(thinking_timeline or []),
                    latency_ms=latency.finish(),
                ),
                context_summary=context.context_summary,
                plan=AgentPlanEnvelope(),
            )

    if gate.status == "clarify":
        await _emit_status(emit, "clarifying")
        await emit_thinking(
            {
                "phase": "clarifying",
                "title": "需要先补充信息",
                "detail": gate.summary or gate.clarification_question,
                "display_text": gate.summary or "",
                "items": list(gate.clarification_questions or []),
                "state": "failed",
            },
            "clarify-question",
        )
        await _emit_status(emit, "requires_clarification")
        return AgentTurnResponse(
            status="requires_clarification",
            stage="requires_clarification",
            output=AgentTurnOutput(
                clarification_question=gate.clarification_question,
                clarification_options=list(gate.clarification_options or []),
            ),
            diagnostics=AgentTurnDiagnostics(
                research_notes=list(gate.research_notes or []) + list(gate.missing_information or []),
                thinking_timeline=list(thinking_timeline or []),
                latency_ms=latency.finish(),
            ),
            context_summary=context.context_summary,
            plan=AgentPlanEnvelope(summary=gate.summary or ""),
        )
    if gate.status == "block":
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=AgentTurnDiagnostics(
                error=gate.blocked_reason or gate.summary or "当前请求被门卫节点阻断",
                thinking_timeline=list(thinking_timeline or []),
                latency_ms=latency.finish(),
            ),
            context_summary=context.context_summary,
            plan=AgentPlanEnvelope(summary=gate.summary or ""),
        )

    if not gate_fast_passed:
        await emit_thinking(
            {
                "phase": "gating",
                "title": "门卫通过",
                "detail": gate.summary or "问题已明确，可以继续收集证据并回答。",
                "display_text": gate.summary or "",
                "state": "completed",
            },
            "gating-check",
        )

    dependency_error = await _run_required_skill_dependencies(
        payload=payload,
        effective_profile=effective_profile,
        context=context,
        memory=memory,
        llm_runtime=llm_runtime,
        emit_thinking=emit_thinking,
    )
    if dependency_error:
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=_build_diagnostics(memory=memory, error=dependency_error, thinking_timeline=thinking_timeline, latency_ms=latency.finish()),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=AgentPlanEnvelope(),
        )
    specialist_error = await _run_formal_specialist_roles(
        payload=payload,
        context=context,
        memory=memory,
        llm_runtime=llm_runtime,
        emit_thinking=emit_thinking,
    )
    if specialist_error:
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=_build_diagnostics(memory=memory, error=specialist_error, thinking_timeline=thinking_timeline, latency_ms=latency.finish()),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=AgentPlanEnvelope(),
        )
    parent_drafts = {
        "status": "ready_for_product_recheck",
        "artifacts": _specialist_artifacts(memory),
    }
    recheck_error = await _run_market_product_recheck(
        payload=payload,
        context=context,
        memory=memory,
        parent_drafts=parent_drafts,
        llm_runtime=llm_runtime,
        emit_thinking=emit_thinking,
    )
    if recheck_error:
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=_build_diagnostics(memory=memory, error=recheck_error, thinking_timeline=thinking_timeline, latency_ms=latency.finish()),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=AgentPlanEnvelope(),
        )

    await _emit_status(emit, "executing")
    await emit_thinking(
        {
            "phase": "executing",
            "title": "执行工具循环",
            "detail": "正在按需调用工具补证据，证据足够后会直接收敛到回答。",
            "state": "active",
        },
        "tool-loop",
    )
    try:
        main_allowed_tools = await _allocate_tools_for_role(
            payload=payload,
            context=context,
            memory=memory,
            llm_runtime=llm_runtime,
            agent_role="main_analysis",
            task="围绕用户当前问题整合项目材料和已委派研究备忘录，形成可追溯结论。",
            emit_thinking=emit_thinking,
        )
        max_steps_override, max_errors_override = _tool_loop_limits()
        main_initial_artifacts = dict(memory.artifacts or {})
        with latency.track("tool_loop"):
            loop_kwargs = dict(
                messages=payload.messages,
                snapshot=snapshot,
                context=context,
                registry=get_tool_registry(),
                governance_mode=payload.governance_mode,
                confirmed_tools=list(payload.risk_confirmations or []),
                emit=emit_event,
                include_secondary_tools=True,
                max_steps_override=max_steps_override,
                max_errors_override=max_errors_override,
                initial_artifacts=main_initial_artifacts,
                allowed_tool_names=main_allowed_tools,
            )
            if llm_runtime is not None:
                loop_kwargs["llm_runtime"] = llm_runtime
            if effective_profile is not None and str(effective_profile.skill_id or "").strip():
                loop_kwargs["system_instruction"] = skill_instruction(effective_profile.skill_id)
            loop_result = await run_langgraph_react_loop(**loop_kwargs)
            loop_result.artifacts = _new_loop_artifacts(loop_result, main_initial_artifacts)
    except Exception as exc:
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=_build_diagnostics(
                memory=memory,
                used_tools=used_tools,
                error=f"工具循环调用失败：{exc}",
                thinking_timeline=thinking_timeline,
                latency_ms=latency.finish(),
            ),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=AgentPlanEnvelope(),
        )

    dependency_used_tools = [
        str(item).strip()
        for artifact_name in ("cultural_tourism_research", "market_audience_research")
        for item in (memory.artifacts.get(artifact_name, {}).get("used_tools", []) if isinstance(memory.artifacts.get(artifact_name), dict) else [])
        if str(item).strip()
    ]
    for role in _FORMAL_SPECIALIST_ROLES:
        artifact = memory.artifacts.get(role)
        if not isinstance(artifact, dict):
            continue
        for version in artifact.get("versions") or []:
            if isinstance(version, dict):
                dependency_used_tools.extend(
                    str(item).strip() for item in version.get("used_tools") or [] if str(item).strip()
                )
    market_artifact = memory.artifacts.get("market_audience_research")
    if isinstance(market_artifact, dict) and isinstance(market_artifact.get("product_recheck"), dict):
        dependency_used_tools.extend(
            str(item).strip()
            for item in market_artifact["product_recheck"].get("used_tools") or []
            if str(item).strip()
        )
    used_tools = list(dict.fromkeys([*dependency_used_tools, *list(loop_result.used_tools or [])]))
    dependency_traces = list(memory.execution_trace or [])
    dependency_results = list(memory.tool_results or [])
    memory.execution_trace = [*dependency_traces, *list(loop_result.execution_trace or [])]
    memory.tool_results = [*dependency_results, *list(loop_result.tool_results or [])]
    protected_specialist_keys = {"market_audience_research", *_FORMAL_SPECIALIST_ROLES}
    memory.artifacts.update({
        key: value
        for key, value in dict(loop_result.artifacts or {}).items()
        if key not in protected_specialist_keys
    })
    memory.research_notes = _merge_notes(memory.research_notes, list(loop_result.research_notes or []))
    planning_summary = _build_loop_plan_summary(
        used_tools=used_tools,
        assistant_summary=str(loop_result.assistant_summary or ""),
    )
    current_plan_envelope = AgentPlanEnvelope(
        steps=list(loop_result.steps or []),
        summary=planning_summary,
    )
    await _maybe_emit(emit, "plan", current_plan_envelope.model_dump(mode="json"))

    if loop_result.status == "requires_risk_confirmation":
        await emit_thinking(
            {
                "phase": "executing",
                "title": "等待风险确认",
                "detail": loop_result.risk_prompt or "存在需要确认的高成本工具调用。",
                "state": "failed",
            },
            "tool-loop",
        )
        await _emit_status(emit, "requires_risk_confirmation")
        return AgentTurnResponse(
            status="requires_risk_confirmation",
            stage="requires_risk_confirmation",
            output=AgentTurnOutput(risk_prompt=loop_result.risk_prompt),
            diagnostics=_build_diagnostics(
                memory=memory,
                used_tools=used_tools,
                thinking_timeline=thinking_timeline,
                planning_summary=planning_summary,
                latency_ms=latency.finish(),
            ),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=current_plan_envelope,
        )

    if loop_result.status == "failed":
        await emit_thinking(
            {
                "phase": "executing",
                "title": "工具循环失败",
                "detail": loop_result.error or loop_result.stop_reason or "工具循环未能稳定完成。",
                "state": "failed",
            },
            "tool-loop",
        )
        await _emit_status(emit, "failed")
        return AgentTurnResponse(
            status="failed",
            stage="failed",
            output=AgentTurnOutput(),
            diagnostics=_build_diagnostics(
                memory=memory,
                used_tools=used_tools,
                error=loop_result.error or loop_result.stop_reason or "tool_loop_failed",
                thinking_timeline=thinking_timeline,
                planning_summary=planning_summary,
                latency_ms=latency.finish(),
            ),
            context_summary=build_context_summary(snapshot, memory.artifacts),
            plan=current_plan_envelope,
        )

    latest_rule_audit = audit_execution(question=question, snapshot=snapshot, context=context, memory=memory)
    memory.audit_issues = list(latest_rule_audit.issues or [])
    audit_summary = _build_rule_audit_summary(latest_rule_audit)
    await emit_thinking(
        {
            "phase": "assess",
            "title": "证据检查完成",
            "detail": audit_summary,
            "display_text": audit_summary,
            "items": list(latest_rule_audit.missing_evidence or [])[:3],
            "state": "completed",
        },
        "audit-check",
    )

    answer_evidence_payload = build_answer_evidence_payload(
        question=question,
        snapshot=snapshot,
        artifacts=memory.artifacts,
        tool_results=memory.tool_results,
        research_notes=list(memory.research_notes or []),
        audit=latest_rule_audit,
    )
    translation_pack = AgentTranslationPack(
        status="skipped",
        summary="指标转译已合并到最终回答阶段，减少一次独立 LLM 往返。",
    )
    latency.set("translation", 0)
    memory.research_notes.append("指标转译已合并到最终回答阶段，减少一次独立 LLM 往返。")
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "指标转译合并",
            "detail": translation_pack.summary,
            "display_text": translation_pack.summary,
            "state": "completed",
        },
        "translation-layer",
    )
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "最终证据检索",
            "detail": "正在按需读取可检索地图证据，供最终回答引用具体空间对象。",
            "state": "active",
        },
        "finalizer-evidence",
    )
    try:
        with latency.track("finalizer_evidence"):
            finalizer_evidence_pack = build_finalizer_evidence_pack(
                question=question,
                snapshot=snapshot,
                artifacts=memory.artifacts,
                answer_evidence_payload=answer_evidence_payload,
            )
            answer_evidence_payload["finalizer_evidence_pack"] = finalizer_evidence_pack
            finalizer_nodes = list(finalizer_evidence_pack.get("evidence_nodes") or [])
            finalizer_document_nodes = list(finalizer_evidence_pack.get("document_evidence_nodes") or [])
            finalizer_read_count = len(finalizer_nodes)
            finalizer_search_count = len(finalizer_evidence_pack.get("search_queries") or [])
        if finalizer_read_count:
            for tool_name in ("search_analysis_context", "read_analysis_evidence_node"):
                if tool_name not in used_tools:
                    used_tools.append(tool_name)
        await emit_thinking(
            {
                "phase": "synthesizing",
                "title": "最终证据检索完成",
                "detail": f"已整理 {len(finalizer_document_nodes)} 个项目文档证据，并执行 {finalizer_search_count} 次 GIS 检索、读取 {finalizer_read_count} 个空间 EvidenceNode。",
                "display_text": f"已读取 {len(finalizer_document_nodes)} 个文档证据和 {finalizer_read_count} 个地图证据节点。",
                "items": [
                    str(item.get("title") or item.get("id") or "").strip()
                    for item in (finalizer_document_nodes + finalizer_nodes)[:4]
                    if str(item.get("title") or item.get("id") or "").strip()
                ],
                "meta": {
                    "status": finalizer_evidence_pack.get("status"),
                    "search_count": finalizer_search_count,
                    "read_count": finalizer_read_count,
                    "document_read_count": len(finalizer_document_nodes),
                    "warnings": list(finalizer_evidence_pack.get("warnings") or [])[:4],
                },
                "state": "completed",
            },
            "finalizer-evidence",
        )
    except Exception as exc:
        note = f"最终证据检索失败，已继续使用现有证据回答：{exc}"
        memory.research_notes.append(note)
        dossier = answer_evidence_payload.get("project_evidence_dossier")
        dossier = dossier if isinstance(dossier, dict) else {}
        answer_evidence_payload["finalizer_evidence_pack"] = {
            "status": "failed",
            "warnings": [note, *list(dossier.get("warnings") or [])][:8],
            "document_evidence_nodes": list(dossier.get("evidence") or []),
            "document_conflicts": list(dossier.get("conflicts") or []),
            "document_status": dossier.get("status") or "empty",
            "evidence_nodes": [],
            "search_queries": [],
        }
        await emit_thinking(
            {
                "phase": "synthesizing",
                "title": "最终证据检索失败",
                "detail": note,
                "state": "failed",
            },
            "finalizer-evidence",
        )
    citations = build_citations(snapshot, memory.artifacts)
    await _emit_status(emit, "synthesizing")
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "综合分析",
            "detail": "正在基于现有证据组织自然回答。",
            "state": "active",
        },
        "synthesizing-final",
    )
    synthesis_error = ""
    try:
        with latency.track("answer"):
            synthesizer_kwargs = dict(
                messages=payload.messages,
                snapshot=snapshot,
                context=context,
                answer_evidence_payload=answer_evidence_payload,
                translation_pack=translation_pack,
                image_inputs=visual_image_inputs,
                emit=emit_event,
            )
            if llm_runtime is not None:
                synthesizer_kwargs["runtime"] = llm_runtime
            answer_output = await generate_answer_output_with_llm(**synthesizer_kwargs)
    except Exception as exc:
        synthesis_error = f"综合回答 LLM 调用失败，已切换到服务端兜底：{exc}"
        memory.research_notes.append(synthesis_error)
        answer_output = AgentTurnOutput(
            answer=build_answer_fallback(
                question=question,
                snapshot=snapshot,
                artifacts=memory.artifacts,
                tool_results=memory.tool_results,
                research_notes=list(memory.research_notes or []),
                audit=latest_rule_audit,
            )
        )
    if not str(answer_output.answer or "").strip():
        answer_output.answer = build_answer_fallback(
            question=question,
            snapshot=snapshot,
            artifacts=memory.artifacts,
            tool_results=memory.tool_results,
            research_notes=list(memory.research_notes or []),
            audit=latest_rule_audit,
        )
    await _emit_status(emit, "answered")
    await emit_thinking(
        {
            "phase": "synthesizing",
            "title": "回答生成完成",
            "detail": "已生成最终自然回答。",
            "state": "completed",
        },
        "synthesizing-final",
    )
    answer_output = enrich_answer_output(
        output=answer_output,
        question=question,
        snapshot=snapshot,
        artifacts=memory.artifacts,
        tool_results=memory.tool_results,
        research_notes=list(memory.research_notes or []),
        audit=latest_rule_audit,
    )
    return AgentTurnResponse(
        status="answered",
        stage="answered",
        output=answer_output,
        diagnostics=_build_diagnostics(
            memory=memory,
            used_tools=used_tools,
            citations=citations,
            thinking_timeline=thinking_timeline,
            planning_summary=planning_summary,
            audit_summary=audit_summary,
            translation_pack=translation_pack,
            latency_ms=latency.finish(),
            error=synthesis_error,
        ),
        context_summary=build_context_summary(snapshot, memory.artifacts),
        plan=current_plan_envelope,
    )


async def process_main_agent_loop(payload: AgentTurnRequest) -> AgentTurnResponse:
    return await _run_main_agent_loop(payload)


async def stream_main_agent_loop(
    payload: AgentTurnRequest, *, llm_runtime: LLMRuntimeConfig | None = None,
    effective_profile: EffectiveExecutionProfile | None = None, skill_id: str = "",
) -> AsyncIterator[AgentTurnStreamEvent]:
    queue: asyncio.Queue[AgentTurnStreamEvent | None] = asyncio.Queue()

    async def emit(event_type: str, event_payload: dict[str, Any]) -> None:
        await queue.put(AgentTurnStreamEvent(type=event_type, payload=event_payload))

    async def runner() -> None:
        try:
            if effective_profile is not None:
                await emit("meta", {"effective_execution_profile": effective_profile.model_dump(mode="json")})
            response = await _run_main_agent_loop(
                payload,
                emit=emit,
                llm_runtime=llm_runtime,
                effective_profile=effective_profile,
            )
            if effective_profile is not None:
                response = response.model_copy(update={"effective_execution_profile": effective_profile})
            if response.status == "failed" and response.diagnostics.error:
                await emit("error", {"message": response.diagnostics.error})
            await queue.put(
                AgentTurnStreamEvent(
                    type="final",
                    payload={"response": response.model_dump(mode="json")},
                )
            )
        except Exception as exc:
            failed = AgentTurnResponse(
                status="failed",
                stage="failed",
                output=AgentTurnOutput(),
                diagnostics=AgentTurnDiagnostics(error=f"Agent 流式执行失败：{exc}"),
                context_summary=build_context_summary(payload.analysis_snapshot),
                plan=AgentPlanEnvelope(),
            )
            await emit("error", {"message": failed.diagnostics.error})
            await queue.put(
                AgentTurnStreamEvent(
                    type="final",
                    payload={"response": failed.model_dump(mode="json")},
                )
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
