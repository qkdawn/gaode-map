from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Callable

from .stage1_contracts import AutomatedVerificationCheck, VerificationTask


@dataclass(frozen=True)
class VerificationToolSpec:
    """A deterministic verifier selected by claim type rather than by model guesswork."""

    tool_id: str
    verifies: tuple[str, ...]
    required_inputs: tuple[str, ...]
    produces: tuple[str, ...]


@dataclass(frozen=True)
class VerificationRun:
    ledger: list[dict[str, Any]]
    checks: list[AutomatedVerificationCheck]
    tasks: list[VerificationTask]
    notes: list[str]


Verifier = Callable[
    [dict[str, Any], Any, set[str]],
    tuple[dict[str, Any], AutomatedVerificationCheck, VerificationTask | None],
]

_ROAD_TERMS = (
    "路网",
    "道路",
    "整合度",
    "连接度",
    "可理解度",
    "空间句法",
    "integration",
    "connectivity",
    "intelligibility",
)
_RELATIVE_TERMS = (
    "较高",
    "较低",
    "偏高",
    "偏低",
    "高于",
    "低于",
    "极高",
    "极低",
    "优势",
    "短板",
    "活跃",
    "稀疏",
)
_TRAFFIC_OVERREACH_TERMS = (
    "外部可达",
    "交通可达",
    "交通通达",
    "主干道连接",
    "真实步行",
    "实际客流",
)
_FRONTAGE_TERMS = ("商业界面", "沿街界面", "店铺连续", "商业连续")
_BEFORE_AFTER_TERMS = ("改造前后", "改善", "提升", "回应短板", "一路")
_POI_TERMS = ("poi", "兴趣点", "业态数量", "设施数量", "店铺数量", "poi密度")
_POPULATION_TERMS = ("人口", "年龄结构", "常住人口", "居住人口", "人口密度")
_NIGHTLIGHT_TERMS = ("夜光", "灯光", "nightlight", "viirs")
_H3_TERMS = ("h3", "gap_score", "缺口分", "网格缺口", "供需缺口")
_POI_OVERREACH_TERMS = (
    "真实需求",
    "消费需求",
    "实际客流",
    "支付能力",
    "支付意愿",
    "营业额",
    "坪效",
    "收入",
    "购买力",
    "开店成功",
)
_POPULATION_OVERREACH_TERMS = (
    "项目客流",
    "实际客流",
    "消费偏好",
    "支付意愿",
    "支付能力",
    "购买力",
)
_NIGHTLIGHT_OVERREACH_TERMS = (
    "客流",
    "消费",
    "支付",
    "营业额",
    "收入",
    "购买力",
    "消费力",
)
_H3_OVERREACH_TERMS = (
    "开店成功",
    "成功概率",
    "必然成功",
    "营业额",
    "收益",
    "最佳业态",
    "最适合开",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _road_parts(snapshot: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    road = _mapping(getattr(snapshot, "road", None))
    summary = _mapping(road.get("summary")) or road
    diagnostics = _mapping(road.get("diagnostics"))
    regression = _mapping(diagnostics.get("regression"))
    return road, summary, regression


def _claim_types(node: dict[str, Any]) -> set[str]:
    claim = _text(node.get("claim"))
    metric = _text(node.get("metric")).lower()
    method = _text(node.get("method")).lower()
    text = " ".join((claim, metric, method, _text(node.get("source_ref")))).lower()
    types: set[str] = set()
    if any(term.lower() in text for term in _ROAD_TERMS):
        if (
            "可理解度" in text
            or "intelligibility" in text
            or metric in {"r", "r2", "r_squared"}
        ):
            types.add("network_intelligibility")
        if "整合度" in text or "integration" in text:
            types.add("network_integration")
        if "连接度" in text or "connectivity" in text:
            types.add("network_connectivity")
        if any(term in claim for term in _BEFORE_AFTER_TERMS):
            types.add("before_after_network_change")
    if any(term in text for term in _POI_TERMS):
        types.add("poi_proxy")
    if any(term in text for term in _POPULATION_TERMS):
        types.add("population_proxy")
    if any(term in text for term in _NIGHTLIGHT_TERMS):
        types.add("nightlight_proxy")
    if any(term in text for term in _H3_TERMS):
        types.add("h3_gap_proxy")
    if (
        len(
            types.intersection(
                {"poi_proxy", "population_proxy", "nightlight_proxy", "h3_gap_proxy"}
            )
        )
        >= 2
    ):
        types.add("multi_proxy_conclusion")
    return types


def _road_metric(
    summary: dict[str, Any], regression: dict[str, Any], *keys: str
) -> float | None:
    for container in (regression, summary):
        for key in keys:
            value = _number(container.get(key))
            if value is not None:
                return value
    return None


def _check_status(current: str, proposed: str) -> str:
    rank = {
        "verified": 5,
        "cross_checked": 4,
        "inferred": 3,
        "hypothesis": 2,
        "blocked": 1,
        "fieldwork_required": 1,
    }
    if current not in rank:
        return proposed
    return proposed if rank[proposed] < rank[current] else current


def _append_limitation(node: dict[str, Any], message: str) -> None:
    existing = _text(node.get("limitation"))
    if message and message not in existing:
        node["limitation"] = "；".join(item for item in (existing, message) if item)


def _verify_road_claim(
    raw: dict[str, Any], snapshot: Any, claim_types: set[str]
) -> tuple[dict[str, Any], AutomatedVerificationCheck, VerificationTask | None]:
    node = deepcopy(raw)
    evidence_id = _text(node.get("id")) or "unknown-evidence"
    road, summary, regression = _road_parts(snapshot)
    diagnostics: list[str] = []
    derived: dict[str, Any] = {}
    task: VerificationTask | None = None

    if not road:
        node["status"] = "blocked"
        node["confidence"] = "low"
        missing = "包含算法、分析半径、样本量和路网指标的 road analysis snapshot"
        reason = "当前 Stage 1 输入没有可供自动复核的路网分析产物"
        action = "先运行路网句法分析，再由 Agent 自动复算和解释指标"
        _append_limitation(node, reason)
        task = VerificationTask(
            evidence_id=evidence_id,
            status="blocked",
            missing_input=missing,
            blocking_reason=reason,
            executor="agent",
            next_action=action,
        )
        node.update(
            missing_input=task.missing_input,
            blocking_reason=task.blocking_reason,
            executor=task.executor,
            next_action=task.next_action,
        )
        return (
            node,
            AutomatedVerificationCheck(
                evidence_id=evidence_id,
                claim_types=sorted(claim_types),
                tool_id="verify_road_analysis_claim",
                outcome="blocked",
                status="blocked",
                summary=reason,
                diagnostics=[action],
                derived_values={},
            ),
            task,
        )

    proposed_status = _text(node.get("status")) or "inferred"
    claim = _text(node.get("claim"))

    if "network_intelligibility" in claim_types:
        r_value = _road_metric(
            summary, regression, "r", "avg_intelligibility", "intelligibility"
        )
        r2_value = _road_metric(
            summary, regression, "r2", "avg_intelligibility_r2", "intelligibility_r2"
        )
        sample_size = _road_metric(summary, regression, "n", "node_count", "edge_count")
        if r_value is None:
            proposed_status = _check_status(proposed_status, "blocked")
            diagnostics.append("缺少连接度与整合度相关系数 r，无法复算 R²。")
        else:
            derived_r2 = r_value * r_value
            derived["intelligibility_r"] = round(r_value, 8)
            derived["intelligibility_r2_recomputed"] = round(derived_r2, 8)
            if r2_value is None:
                derived["intelligibility_r2_reported"] = None
                proposed_status = _check_status(proposed_status, "cross_checked")
                diagnostics.append(
                    f"已由 r={r_value:.4g} 自动复算 R²={derived_r2:.4g}。"
                )
            else:
                difference = abs(derived_r2 - r2_value)
                derived["intelligibility_r2_reported"] = round(r2_value, 8)
                derived["r2_absolute_error"] = round(difference, 8)
                if difference <= 0.01:
                    proposed_status = _check_status(proposed_status, "cross_checked")
                    diagnostics.append(
                        f"相关系数 r={r_value:.4g} 与决定系数 R²={r2_value:.4g} 数学一致（r²={derived_r2:.4g}）。"
                    )
                else:
                    proposed_status = _check_status(proposed_status, "blocked")
                    diagnostics.append(
                        f"指标不一致：r={r_value:.4g} 的平方为 {derived_r2:.4g}，但产物记录 R²={r2_value:.4g}。"
                    )
        if sample_size is not None:
            derived["sample_size"] = int(sample_size)
        if any(term in claim for term in _RELATIVE_TERMS) and not _text(
            node.get("comparison_baseline")
        ):
            proposed_status = _check_status(proposed_status, "inferred")
            diagnostics.append(
                "没有同算法、同半径基准，不能把 r 或 R²直接定性为高、低或极低。"
            )

    if "network_integration" in claim_types:
        integration = _road_metric(
            summary,
            regression,
            "avg_integration_global",
            "avg_accessibility_global",
            "avg_integration",
            "mean_integration",
        )
        if integration is not None:
            derived["avg_integration"] = round(integration, 8)
        else:
            diagnostics.append("路网产物未提供可定位的平均整合度。")
            proposed_status = _check_status(proposed_status, "blocked")
        if any(term in claim for term in _RELATIVE_TERMS) and not _text(
            node.get("comparison_baseline")
        ):
            proposed_status = _check_status(proposed_status, "inferred")
            diagnostics.append("整合度缺少同算法、同半径的比较基准，只能陈述数值。")
        if any(term in claim for term in _TRAFFIC_OVERREACH_TERMS):
            proposed_status = _check_status(proposed_status, "inferred")
            diagnostics.append(
                "空间句法整合度反映拓扑潜力，不等同于现实交通时间、流量或主干道连接质量。"
            )

    if "network_connectivity" in claim_types:
        connectivity = _road_metric(
            summary, regression, "avg_connectivity", "mean_connectivity"
        )
        if connectivity is not None:
            derived["avg_connectivity"] = round(connectivity, 8)
        if any(term in claim for term in _FRONTAGE_TERMS):
            proposed_status = _check_status(proposed_status, "hypothesis")
            diagnostics.append(
                "连接度不能单独证明商业界面连续性；仍需沿街开口、围墙、入口和POI贴边证据。"
            )

    if "before_after_network_change" in claim_types:
        proposed_geometry = (
            road.get("proposed_network")
            or road.get("after_network")
            or road.get("scenario_network")
        )
        if not proposed_geometry:
            proposed_status = _check_status(proposed_status, "blocked")
            diagnostics.append("缺少改造后可计算路径中心线，不能验证方案改善幅度。")
            task = VerificationTask(
                evidence_id=evidence_id,
                status="blocked",
                missing_input="改造后路网或内部路径中心线数据",
                blocking_reason="只有现状路网指标，没有可用于前后模拟的方案网络几何",
                executor="agent",
                next_action="方案中心线进入系统后自动运行前后路网对比",
            )

    if proposed_status == "blocked" and task is None:
        task = VerificationTask(
            evidence_id=evidence_id,
            status="blocked",
            missing_input="原始路网指标、诊断元数据或同口径比较基准",
            blocking_reason="现有路网分析产物不足以完成该主张的自动复核",
            executor="agent",
            next_action="补齐路网分析输入后重新执行确定性核验",
        )
    if task is not None:
        node.update(
            missing_input=task.missing_input,
            blocking_reason=task.blocking_reason,
            executor=task.executor,
            next_action=task.next_action,
        )
    if proposed_status in {"blocked", "hypothesis"}:
        node["confidence"] = "low"
    elif (
        proposed_status in {"cross_checked", "inferred"}
        and _text(node.get("confidence")) == "high"
    ):
        node["confidence"] = "medium"
    node["status"] = proposed_status
    if derived:
        node["derived_values"] = {**_mapping(node.get("derived_values")), **derived}
    for message in diagnostics:
        _append_limitation(node, message)
    tool_ids = [
        str(item) for item in list(node.get("verification_tool_ids") or []) if str(item)
    ]
    if "verify_road_analysis_claim" not in tool_ids:
        tool_ids.append("verify_road_analysis_claim")
    node["verification_tool_ids"] = tool_ids

    outcome = "passed"
    if proposed_status == "blocked":
        outcome = "blocked"
    elif proposed_status in {"inferred", "hypothesis"} or diagnostics:
        outcome = "passed_with_gaps"
    summary_text = diagnostics[0] if diagnostics else "路网指标自动核验完成。"
    return (
        node,
        AutomatedVerificationCheck(
            evidence_id=evidence_id,
            claim_types=sorted(claim_types),
            tool_id="verify_road_analysis_claim",
            outcome=outcome,
            status=proposed_status,
            summary=summary_text,
            diagnostics=diagnostics,
            derived_values=derived,
        ),
        task,
    )


def _nested_number(value: Any, keys: tuple[str, ...], depth: int = 0) -> float | None:
    if depth > 3:
        return None
    if isinstance(value, dict):
        for key in keys:
            number = _number(value.get(key))
            if number is not None:
                return number
        for child in value.values():
            number = _nested_number(child, keys, depth + 1)
            if number is not None:
                return number
    return None


def _proxy_source(snapshot: Any, claim_type: str) -> tuple[bool, dict[str, Any]]:
    if claim_type == "poi_proxy":
        pois = list(getattr(snapshot, "pois", None) or [])
        summary = _mapping(getattr(snapshot, "poi_summary", None))
        count = _nested_number(summary, ("total_count", "poi_count", "count", "total"))
        if count is None and pois:
            count = float(len(pois))
        derived = {"poi_record_count": int(count)} if count is not None else {}
        return bool(pois or summary), derived
    if claim_type == "population_proxy":
        population = _mapping(getattr(snapshot, "population", None))
        total = _nested_number(
            population, ("total_population", "population_total", "total", "population")
        )
        return bool(population), {
            "population_total": total
        } if total is not None else {}
    if claim_type == "nightlight_proxy":
        nightlight = _mapping(getattr(snapshot, "nightlight", None))
        average = _nested_number(
            nightlight,
            ("mean_radiance", "avg_light", "mean_light", "avg_dn", "mean", "average"),
        )
        count = _nested_number(
            nightlight, ("sample_count", "cell_count", "grid_count", "count")
        )
        derived: dict[str, Any] = {}
        if average is not None:
            derived["nightlight_average"] = round(average, 8)
        if count is not None:
            derived["nightlight_sample_count"] = int(count)
        return bool(nightlight), derived
    h3 = _mapping(getattr(snapshot, "h3", None))
    score = _nested_number(h3, ("average_gap_score", "mean_gap_score", "gap_score"))
    count = _nested_number(h3, ("cell_count", "grid_count", "count"))
    derived = {}
    if score is not None:
        derived["h3_gap_score"] = round(score, 8)
    if count is not None:
        derived["h3_cell_count"] = int(count)
    return bool(h3), derived


def _verify_proxy_claim(
    raw: dict[str, Any], snapshot: Any, claim_types: set[str]
) -> tuple[dict[str, Any], AutomatedVerificationCheck, VerificationTask | None]:
    node = deepcopy(raw)
    evidence_id = _text(node.get("id")) or "unknown-evidence"
    claim = _text(node.get("claim"))
    proposed_status = _text(node.get("status")) or "inferred"
    diagnostics: list[str] = []
    derived: dict[str, Any] = {}
    task: VerificationTask | None = None
    source_types = sorted(
        claim_types.intersection(
            {"poi_proxy", "population_proxy", "nightlight_proxy", "h3_gap_proxy"}
        )
    )
    missing_sources: list[str] = []
    source_labels = {
        "poi_proxy": "POI",
        "population_proxy": "人口",
        "nightlight_proxy": "夜光",
        "h3_gap_proxy": "H3 网格",
    }
    for claim_type in source_types:
        available, values = _proxy_source(snapshot, claim_type)
        if not available:
            missing_sources.append(source_labels[claim_type])
        derived.update(values)

    if missing_sources:
        proposed_status = _check_status(proposed_status, "blocked")
        reason = f"当前 Stage 1 输入缺少可复核的{'、'.join(missing_sources)}分析产物"
        diagnostics.append(reason)
        task = VerificationTask(
            evidence_id=evidence_id,
            status="blocked",
            missing_input=f"{'、'.join(missing_sources)}分析快照及其口径、范围和年份",
            blocking_reason=reason,
            executor="agent",
            next_action=f"先运行{'、'.join(missing_sources)}分析，再自动复核该主张",
        )

    if "poi_proxy" in source_types and any(
        term in claim for term in _POI_OVERREACH_TERMS
    ):
        proposed_status = _check_status(proposed_status, "hypothesis")
        diagnostics.append(
            "POI 数量或密度反映设施供给代理，不能直接证明真实需求、客流、支付或经营绩效。"
        )
    if "population_proxy" in source_types and any(
        term in claim for term in _POPULATION_OVERREACH_TERMS
    ):
        proposed_status = _check_status(proposed_status, "hypothesis")
        diagnostics.append(
            "人口规模或年龄结构不能直接证明项目客流、消费偏好或支付意愿。"
        )
    if "nightlight_proxy" in source_types:
        if _text(node.get("evidence_type")) != "P":
            node["evidence_type"] = "P"
            diagnostics.append("夜光属于代理指标，证据类型已归一化为 P。")
        if any(term in claim for term in _NIGHTLIGHT_OVERREACH_TERMS):
            proposed_status = _check_status(proposed_status, "hypothesis")
            diagnostics.append(
                "夜光强度只能辅助描述活动或建成环境信号，不能等同于客流、消费金额或支付能力。"
            )
    if "h3_gap_proxy" in source_types:
        if _text(node.get("evidence_type")) != "P":
            node["evidence_type"] = "P"
            diagnostics.append("H3 gap_score 属于模型代理指标，证据类型已归一化为 P。")
        if any(term in claim for term in _H3_OVERREACH_TERMS):
            proposed_status = _check_status(proposed_status, "hypothesis")
            diagnostics.append(
                "H3 gap_score 只能表达当前模型口径下的空间缺口，不能解释为开店成功概率、收益或确定业态。"
            )

    if any(term in claim for term in _RELATIVE_TERMS) and not _text(
        node.get("comparison_baseline")
    ):
        proposed_status = _check_status(proposed_status, "inferred")
        diagnostics.append(
            "相对判断缺少同年份、同范围、同口径比较基准，只能陈述当前数值或分布。"
        )
    if "multi_proxy_conclusion" in claim_types:
        proposed_status = _check_status(proposed_status, "inferred")
        diagnostics.append(
            "多个代理指标相互印证只能提高线索一致性，不能自动升级为高置信度事实或因果结论。"
        )

    if task is not None:
        node.update(
            missing_input=task.missing_input,
            blocking_reason=task.blocking_reason,
            executor=task.executor,
            next_action=task.next_action,
        )
    if proposed_status in {"blocked", "hypothesis"}:
        node["confidence"] = "low"
    elif proposed_status == "inferred" and _text(node.get("confidence")) == "high":
        node["confidence"] = "medium"
    node["status"] = proposed_status
    if derived:
        node["derived_values"] = {**_mapping(node.get("derived_values")), **derived}
    for message in diagnostics:
        _append_limitation(node, message)
    tool_ids = [
        str(item) for item in list(node.get("verification_tool_ids") or []) if str(item)
    ]
    if "verify_proxy_indicator_claim" not in tool_ids:
        tool_ids.append("verify_proxy_indicator_claim")
    node["verification_tool_ids"] = tool_ids

    outcome = "passed"
    if proposed_status == "blocked":
        outcome = "blocked"
    elif proposed_status in {"inferred", "hypothesis"} or diagnostics:
        outcome = "passed_with_gaps"
    summary = (
        diagnostics[0] if diagnostics else "代理指标的来源与推论边界自动核验完成。"
    )
    return (
        node,
        AutomatedVerificationCheck(
            evidence_id=evidence_id,
            claim_types=sorted(claim_types),
            tool_id="verify_proxy_indicator_claim",
            outcome=outcome,
            status=proposed_status,
            summary=summary,
            diagnostics=diagnostics,
            derived_values=derived,
        ),
        task,
    )


_VERIFICATION_TOOLS: tuple[tuple[VerificationToolSpec, Verifier], ...] = (
    (
        VerificationToolSpec(
            tool_id="verify_road_analysis_claim",
            verifies=(
                "network_integration",
                "network_connectivity",
                "network_intelligibility",
                "before_after_network_change",
            ),
            required_inputs=("road_analysis_snapshot",),
            produces=("derived_metrics", "semantic_diagnostics", "verification_status"),
        ),
        _verify_road_claim,
    ),
    (
        VerificationToolSpec(
            tool_id="verify_proxy_indicator_claim",
            verifies=(
                "poi_proxy",
                "population_proxy",
                "nightlight_proxy",
                "h3_gap_proxy",
                "multi_proxy_conclusion",
            ),
            required_inputs=("matching_analysis_snapshot",),
            produces=("proxy_boundaries", "derived_metrics", "verification_status"),
        ),
        _verify_proxy_claim,
    ),
)


def list_verification_tools() -> list[VerificationToolSpec]:
    return [spec for spec, _runner in _VERIFICATION_TOOLS]


def run_automated_verification(
    ledger: list[dict[str, Any]], *, snapshot: Any
) -> VerificationRun:
    """Plan and execute deterministic checks for claims covered by registered verifiers."""

    normalized: list[dict[str, Any]] = []
    checks: list[AutomatedVerificationCheck] = []
    tasks: list[VerificationTask] = []
    notes: list[str] = []
    for raw in ledger:
        node = deepcopy(raw)
        claim_types = _claim_types(node)
        applicable = [
            (spec, runner)
            for spec, runner in _VERIFICATION_TOOLS
            if claim_types.intersection(spec.verifies)
        ]
        for spec, runner in applicable:
            covered = claim_types.intersection(spec.verifies)
            node, check, task = runner(node, snapshot, covered)
            checks.append(check)
            if task is not None and not any(
                existing.evidence_id == task.evidence_id
                and existing.missing_input == task.missing_input
                for existing in tasks
            ):
                tasks.append(task)
            notes.append(
                f"{node.get('id')} 已由 {spec.tool_id} 自动核验：{check.summary}"
            )
        normalized.append(node)
    return VerificationRun(ledger=normalized, checks=checks, tasks=tasks, notes=notes)
