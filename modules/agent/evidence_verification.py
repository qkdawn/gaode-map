from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from .stage1_contracts import (
    VerificationSummary,
    VerificationTask,
    historical_plan_date,
    verification_status_counts,
)
from .verification_tools import run_automated_verification

_ALLOWED_STATUSES = {
    "verified",
    "cross_checked",
    "inferred",
    "hypothesis",
    "blocked",
    "fieldwork_required",
}
_FIELDWORK_TERMS = (
    "现场",
    "入户",
    "访谈",
    "测绘",
    "结构",
    "消防",
    "产权",
    "审批",
    "鉴定",
)
_RELATIVE_TERMS = (
    "较高",
    "较低",
    "偏高",
    "偏低",
    "高于",
    "低于",
    "优势",
    "短板",
    "领先",
    "落后",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _source_search_text(source: dict[str, Any]) -> str:
    fields = (
        "source_id",
        "id",
        "title",
        "name",
        "label",
        "file_name",
        "source_type",
        "provider",
    )
    return " ".join(
        _text(source.get(field)).lower() for field in fields if source.get(field)
    )


def _known_source_ref(source_ref: str, sources: list[dict[str, Any]]) -> bool:
    needle = source_ref.lower().strip()
    if not needle:
        return False
    for source in sources:
        candidates = [
            _text(source.get(field)).lower()
            for field in ("source_id", "id", "title", "name", "label", "file_name")
            if _text(source.get(field))
        ]
        if any(candidate in needle or needle in candidate for candidate in candidates):
            return True
    return False


def _snapshot_refs(snapshot: Any) -> set[str]:
    refs: set[str] = set()
    for field in (
        "frontend_analysis",
        "poi_summary",
        "population",
        "nightlight",
        "h3",
        "road",
    ):
        if getattr(snapshot, field, None):
            refs.update({field, f"analysis_snapshot.{field}"})
    return refs


def _references_snapshot(source_ref: str, refs: set[str]) -> bool:
    normalized = source_ref.lower().replace(" ", "")
    aliases = {
        "poi": "poi_summary",
        "人口": "population",
        "夜光": "nightlight",
        "h3": "h3",
        "路网": "road",
        "前端分析": "frontend_analysis",
    }
    return any(ref in normalized for ref in refs) or any(
        token in normalized and canonical in refs
        for token, canonical in aliases.items()
    )


def _task_for(node: dict[str, Any], *, as_of: date) -> VerificationTask | None:
    status = _text(node.get("status"))
    if status not in {"blocked", "fieldwork_required"}:
        return None
    evidence_id = _text(node.get("id")) or "unknown-evidence"
    claim = _text(node.get("claim")) or "该证据结论"
    missing_input = _text(node.get("missing_input"))
    blocking_reason = _text(node.get("blocking_reason"))
    next_action = _text(node.get("next_action"))
    executor = _text(node.get("executor"))
    if status == "fieldwork_required":
        executor = "fieldwork"
        missing_input = (
            missing_input or f"{claim}对应的现场观察、测绘、访谈或权属核验记录"
        )
        blocking_reason = blocking_reason or "现有数字资料不能替代现场或法定核验"
        next_action = next_action or "形成带日期、对象和记录人的现场核验表"
    else:
        if executor not in {"agent", "manual_authority"}:
            executor = "manual_authority"
        missing_input = (
            missing_input
            or f"截至 {as_of.isoformat()} 可确认{claim}的原始文件或主管部门记录"
        )
        blocking_reason = blocking_reason or "当前输入中没有足以完成复核的原始依据"
        next_action = next_action or "补充原始文件后由 Agent 重新交叉核对"
    return VerificationTask(
        evidence_id=evidence_id,
        status=status,
        missing_input=missing_input,
        blocking_reason=blocking_reason,
        executor=executor,
        next_action=next_action,
    )


def verify_evidence_ledger(
    ledger: list[dict[str, Any]],
    *,
    selected_sources: list[dict[str, Any]],
    snapshot: Any,
    as_of: date | None = None,
) -> tuple[list[dict[str, Any]], VerificationSummary]:
    """Conservatively normalize model-proposed evidence states against available inputs.

    This phase deliberately does not pretend that an LLM assertion is a verification. Direct
    source references may remain verified; computed evidence without raw recomputation is at
    most cross-checked, and unsupported verification claims are downgraded.
    """

    current_date = as_of or date.today()
    normalized: list[dict[str, Any]] = []
    notes: list[str] = []
    snapshot_refs = _snapshot_refs(snapshot)

    for index, raw in enumerate(ledger):
        node = deepcopy(raw) if isinstance(raw, dict) else {}
        node["id"] = _text(node.get("id")) or f"evidence-{index + 1}"
        node["claim"] = _text(node.get("claim"))
        source_ref = node.get("source_ref")
        if isinstance(source_ref, list):
            source_ref = "；".join(_text(item) for item in source_ref if _text(item))
        node["source_ref"] = _text(source_ref) or "未提供来源"
        status = _text(node.get("status"))
        if status not in _ALLOWED_STATUSES:
            status = "hypothesis"

        binding_status = _text(node.get("provenance_binding_status"))
        has_binding_result = binding_status in {
            "verified",
            "corrected",
            "unverifiable",
            "conflicting",
        }
        source_known = binding_status in {"verified", "corrected"} or (
            not has_binding_result
            and _known_source_ref(node["source_ref"], selected_sources)
        )
        snapshot_known = _references_snapshot(node["source_ref"], snapshot_refs)
        evidence_type = _text(node.get("evidence_type"))
        if binding_status == "conflicting":
            status = "blocked"
            node["blocking_reason"] = "真实数据资产之间存在未解决的来源元数据冲突"
            node["missing_input"] = "唯一可定位的权威 artifact 及统一后的元数据"
            node["executor"] = "manual_authority"
            node["next_action"] = "裁决冲突来源后重新执行证据绑定"
            notes.append(f"{node['id']} 因真实数据资产元数据冲突而阻塞。")
        elif binding_status == "unverifiable" and status in {
            "verified",
            "cross_checked",
        }:
            status = "inferred" if node["claim"] else "blocked"
            notes.append(f"{node['id']} 的来源无法绑定到真实数据资产，验证状态已降级。")
        elif status in {"verified", "cross_checked"} and not (
            source_known or snapshot_known
        ):
            status = "inferred" if node["claim"] else "blocked"
            notes.append(f"{node['id']} 的验证状态因来源无法在本轮输入中定位而降级。")
        elif status == "verified" and evidence_type == "G" and snapshot_known:
            status = "cross_checked"
            notes.append(
                f"{node['id']} 为计算/代理证据，未取得原始计算链，因此降级为交叉核对。"
            )

        temporal_status = _text(node.get("temporal_status")) or "not_applicable"
        if historical_plan_date(node["claim"], as_of=current_date):
            temporal_status = "current_status_unknown"
            if status not in {"fieldwork_required", "blocked"}:
                status = "blocked"
            node["missing_input"] = _text(node.get("missing_input")) or (
                f"截至 {current_date.isoformat()} 的实施进展、完成证明或计划调整文件"
            )
            node["blocking_reason"] = _text(node.get("blocking_reason")) or (
                "原文中的计划日期早于当前分析日期，不能继续作为未来动作引用"
            )
            node["executor"] = "manual_authority"
            node["next_action"] = _text(node.get("next_action")) or (
                "向项目实施主体或主管部门核对当前状态，并更新为已完成、逾期、取消或替代计划"
            )
        baseline = _text(node.get("comparison_baseline"))
        if any(term in node["claim"] for term in _RELATIVE_TERMS) and not baseline:
            if status in {"verified", "cross_checked"}:
                status = "inferred"
            notes.append(f"{node['id']} 使用相对判断但没有比较基准，已限制为推断。")

        confidence = _text(node.get("confidence"))
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        if status in {"inferred", "hypothesis"} and confidence == "high":
            confidence = "medium"
            notes.append(f"{node['id']} 的高置信度与推断状态不一致，已降为中等。")
        elif status in {"blocked", "fieldwork_required"} and confidence != "low":
            confidence = "low"
            notes.append(f"{node['id']} 尚未完成核验，置信度已降为低。")

        node["status"] = status
        node["confidence"] = confidence
        node["temporal_status"] = temporal_status

        if status == "fieldwork_required" and not any(
            term in node["claim"] for term in _FIELDWORK_TERMS
        ):
            notes.append(f"{node['id']} 被标记为现场核验，需在任务中说明具体现场对象。")
        normalized.append(node)

    automated = run_automated_verification(normalized, snapshot=snapshot)
    normalized = automated.ledger
    notes.extend(automated.notes)
    tasks = list(automated.tasks)
    for node in normalized:
        task = _task_for(node, as_of=current_date)
        if task is not None and not any(
            existing.evidence_id == task.evidence_id
            and existing.missing_input == task.missing_input
            for existing in tasks
        ):
            tasks.append(task)
    blocking_reasons: list[str] = []
    if not normalized:
        blocking_reasons.append("模型未生成可审计的证据节点。")
    invalid_claim_ids = [node["id"] for node in normalized if not node["claim"]]
    if invalid_claim_ids:
        blocking_reasons.append(
            f"证据节点缺少明确主张：{'、'.join(invalid_claim_ids)}。"
        )

    counts = verification_status_counts(normalized)
    if blocking_reasons:
        gate_status = "failed"
    elif tasks or counts.get("inferred") or counts.get("hypothesis") or notes:
        gate_status = "passed_with_gaps"
    else:
        gate_status = "passed"
    summary = VerificationSummary(
        status=gate_status,
        report_allowed=not blocking_reasons,
        as_of_date=current_date.isoformat(),
        status_counts=counts,
        automated_checks=automated.checks,
        tasks=tasks,
        notes=notes,
        blocking_reasons=blocking_reasons,
    )
    return normalized, summary
