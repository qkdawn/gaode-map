from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.agent_harness import CodexHarnessError, run_codex
from modules.spatial_action.spatial_evidence import (
    FACT_DOMAIN_CAPABILITIES,
    supported_poi_category_labels,
)


SPATIAL_ANALYSIS_SCHEMA_PATH = Path(__file__).with_name("spatial_tool_analysis.schema.json")
SPATIAL_PLAN_SCHEMA_PATH = Path(__file__).with_name("spatial_tool_plan.schema.json")
SPATIAL_EVIDENCE_KNOWLEDGE = (
    "POI与设施供给描述设施数量、类别、集中和相对供给，不直接证明需求或运营质量；"
    "人口规模与结构描述潜在服务背景，不等于真实使用者；"
    "夜光只描述保存等时圈内的亮度构成及空间差异，不替代客流、消费、营业或具体业态；"
    "路网结构描述连接、到达潜力和穿行潜力，不等于实际交通量；"
    "accessibility使用真实路网时间圈回答不同时间范围内能够覆盖什么；"
    "neighborhood和relationship表达局部邻接与跨域共位，共位不表示因果；"
    "inspect把聚合格局落实到真实地点和道路，返回的具名对象不等于已确认的重要节点。"
)


def _fact_domain_catalog() -> str:
    return "；".join(
        f"{binding.domain}（{binding.description}；维度：{','.join(binding.dimensions)}）"
        for binding in FACT_DOMAIN_CAPABILITIES.values()
    )


def _poi_selector_guidance() -> str:
    labels = "、".join(supported_poi_category_labels())
    return (
        f"POI 的 poi.category 只能使用这些已注册类别：{labels}。"
        "‘公共服务’、‘生活服务’、‘区域节点’等宽泛概念不是可用类别；"
        "若问题使用宽泛概念，请不要传 poi.category 筛选，改用 poi.supply 或 poi.mix，"
        "并在判断中明确它只代表总体设施供给。"
    )


class SpatialToolAgentError(RuntimeError):
    pass


_PLAN_PARAMETER_FIELDS = (
    "selectors",
    "travel_time_bands_min",
    "neighbor_steps",
    "rank_order",
    "top_k",
    "record_refs",
    "named_poi_roles",
)

_PLAN_PARAMETER_DEFAULTS = {
    "selectors": [],
    "travel_time_bands_min": None,
    "neighbor_steps": 1,
    "rank_order": "highest",
    "top_k": 10,
    "record_refs": [],
    "named_poi_roles": [],
}

# A spatial question is a bounded evidence request, not an open-ended
# research loop. Keep this aligned with the plan schema; the MCP tool timeout
# provides the outer execution boundary for a complete evidence plan.
MAX_SPATIAL_SUBQUESTIONS = 8


_FOLLOW_UP_OPERATIONS = {"inspect", "neighborhood"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _planned_parameter(value: dict[str, Any], field: str) -> Any:
    raw = value.get(field, _PLAN_PARAMETER_DEFAULTS[field])
    if field in {"selectors", "record_refs"} and raw is None:
        return []
    return raw


def _call_matches_subquestion(arguments: dict[str, Any], item: dict[str, Any]) -> bool:
    if not all(arguments.get(field) == item.get(field) for field in (
        "analysis", "fact_domains", "evidence_dimensions",
    )):
        return False
    return all(
        _canonical_json(_planned_parameter(arguments, field))
        == _canonical_json(_planned_parameter(item, field))
        for field in _PLAN_PARAMETER_FIELDS
    )


def _plan_tool_call_validator(plan: dict, *, history_id: str):
    """Build a post-turn validator for the actual MCP calls emitted by Codex."""

    planned = plan.get("subquestions") if isinstance(plan, dict) else None
    if not isinstance(planned, list) or not planned:
        raise SpatialToolAgentError("spatial_plan_invalid")

    def validate(calls: list[dict[str, Any]]) -> None:
        if not calls:
            raise SpatialToolAgentError("spatial_plan_without_tool_call")
        # The model may correct a rejected argument set within the same turn.
        # Input validation errors are recoverable when a later call obtains a
        # real result; transport and data-source failures remain visible.
        calls = [
            call
            for call in calls
            if str((call.get("result") or {}).get("status") or "")
            not in {"invalid_request"}
            and not call.get("_recoverable_validation_failure")
        ]
        if not calls:
            raise SpatialToolAgentError("spatial_plan_without_tool_call")
        matched: set[int] = set()
        deferred_parameter_mismatch: str | None = None
        for call in calls:
            name = str(call.get("name") or "").rsplit(".", 1)[-1]
            if name not in {"compute_spatial_evidence", "compute_spatial_evidence_batch"}:
                raise SpatialToolAgentError("spatial_plan_tool_not_allowed")
            arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            if str(arguments.get("history_id") or "").strip() != history_id:
                raise SpatialToolAgentError("spatial_plan_history_mismatch")
            if name == "compute_spatial_evidence_batch":
                requests = arguments.get("requests")
                if not isinstance(requests, list) or not requests:
                    raise SpatialToolAgentError("spatial_plan_batch_invalid")
                batch_matches: set[int] = set()
                for request in requests:
                    if not isinstance(request, dict):
                        raise SpatialToolAgentError("spatial_plan_batch_invalid")
                    matches = [
                        index for index, item in enumerate(planned)
                        if isinstance(item, dict) and _call_matches_subquestion(request, item)
                    ]
                    if len(matches) != 1:
                        semantic_matches = [
                            index for index, item in enumerate(planned)
                            if isinstance(item, dict)
                            and all(request.get(field) == item.get(field) for field in (
                                "analysis", "fact_domains", "evidence_dimensions",
                            ))
                        ]
                        if semantic_matches:
                            deferred_parameter_mismatch = deferred_parameter_mismatch or "spatial_plan_batch_mismatch"
                            continue
                        raise SpatialToolAgentError("spatial_plan_batch_mismatch")
                    if matches[0] in matched or matches[0] in batch_matches:
                        deferred_parameter_mismatch = deferred_parameter_mismatch or "spatial_plan_batch_mismatch"
                        continue
                    batch_matches.add(matches[0])
                matched.update(batch_matches)
                continue
            semantic_candidates = [
                (index, item)
                for index, item in enumerate(planned)
                if isinstance(item, dict)
                and all(arguments.get(field) == item.get(field) for field in (
                    "analysis", "fact_domains", "evidence_dimensions",
                ))
            ]
            if not semantic_candidates:
                # The execution Agent may use inspect/neighborhood as a
                # bounded follow-up to a planned computation.  These calls
                # are supplemental, but must stay within a planned fact-domain
                # and evidence-dimension contract.
                supplemental_candidates = [
                    item
                    for item in planned
                    if isinstance(item, dict)
                    and arguments.get("fact_domains") == item.get("fact_domains")
                    and arguments.get("evidence_dimensions") == item.get("evidence_dimensions")
                ]
                if supplemental_candidates:
                    continue
                raise SpatialToolAgentError("spatial_plan_semantics_mismatch")
            full_matches = [
                (index, item)
                for index, item in semantic_candidates
                if _call_matches_subquestion(arguments, item)
            ]
            if not full_matches:
                for field in _PLAN_PARAMETER_FIELDS:
                    if any(
                        _canonical_json(_planned_parameter(arguments, field))
                        != _canonical_json(_planned_parameter(item, field))
                        for _, item in semantic_candidates
                    ):
                        deferred_parameter_mismatch = deferred_parameter_mismatch or f"spatial_plan_parameter_mismatch:{field}"
                        break
                else:
                    deferred_parameter_mismatch = deferred_parameter_mismatch or "spatial_plan_parameter_mismatch"
                # A same-turn supplemental computation may intentionally use a
                # narrower band or different top_k.  Keep it for provenance,
                # but only fail if the planned computation is still missing.
                continue
            index, _expected = next(
                ((index, item) for index, item in full_matches if index not in matched),
                full_matches[0],
            )
            matched.add(index)
        if matched != set(range(len(planned))):
            # Let the output/ref validator report the missing planned result
            # when at least one planned computation was completed.  This
            # allows the model to issue bounded supplemental calls without
            # masking the stronger computation_refs contract.
            if not matched and deferred_parameter_mismatch:
                raise SpatialToolAgentError(deferred_parameter_mismatch)
            if not matched:
                raise SpatialToolAgentError("spatial_plan_subquestion_not_executed")

    return validate


def _plan_output_validator(plan: dict):
    def validate(output: dict[str, Any], calls: list[dict[str, Any]]) -> None:
        _validate_plan_execution(plan, output)
        _validate_computation_refs(plan, output, calls)

    return validate


def _bound_spatial_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Keep model-generated plans within the deterministic tool budget."""

    subquestions = plan.get("subquestions") if isinstance(plan, dict) else None
    if not isinstance(subquestions, list) or not subquestions:
        raise SpatialToolAgentError("spatial_plan_invalid")
    bounded: list[dict[str, Any]] = []
    for item in subquestions:
        if not isinstance(item, dict):
            continue
        # A record reference is valid only when it points to a persisted
        # result. Placeholder labels cannot be resolved by the deterministic
        # executor and turn into an avoidable hanging call.
        refs = item.get("record_refs")
        if isinstance(refs, list):
            item = {**item, "record_refs": [ref for ref in refs if str(ref).strip() and not str(ref).endswith("_candidates") and not str(ref).endswith("_roads")]}
        bounded.append(item)
        if len(bounded) >= MAX_SPATIAL_SUBQUESTIONS:
            break
    if not bounded:
        raise SpatialToolAgentError("spatial_plan_invalid")
    return {**plan, "subquestions": bounded}


def _validate_plan_execution(plan: dict, result: dict) -> None:
    planned = plan.get("subquestions") if isinstance(plan, dict) else None
    executed = result.get("subquestions") if isinstance(result, dict) else None
    if not isinstance(planned, list) or not isinstance(executed, list) or len(planned) != len(executed):
        raise SpatialToolAgentError("spatial_plan_execution_mismatch")
    for expected, actual in zip(planned, executed):
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            raise SpatialToolAgentError("spatial_plan_execution_mismatch")
        if not str(actual.get("question") or "").strip():
            raise SpatialToolAgentError("spatial_plan_execution_mismatch")
        for field in ("analysis", "fact_domains", "evidence_dimensions"):
            if actual.get(field) != expected.get(field):
                raise SpatialToolAgentError("spatial_plan_execution_mismatch")


def _validate_computation_refs(
    plan: dict,
    result: dict,
    calls: list[dict[str, Any]],
) -> None:
    planned = plan.get("subquestions") if isinstance(plan, dict) else None
    executed = result.get("subquestions") if isinstance(result, dict) else None
    if not isinstance(planned, list) or not isinstance(executed, list):
        raise SpatialToolAgentError("spatial_plan_execution_mismatch")
    for index, (expected, actual) in enumerate(zip(planned, executed)):
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            raise SpatialToolAgentError("spatial_plan_execution_mismatch")
        real_ids: set[str] = set()
        for call in calls:
            arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            name = str(call.get("name") or "").rsplit(".", 1)[-1]
            if name == "compute_spatial_evidence" and _call_matches_subquestion(arguments, expected):
                result_id = str((call.get("result") or {}).get("result_id") or "").strip()
                if result_id:
                    real_ids.add(result_id)
            elif name == "compute_spatial_evidence_batch":
                requests = arguments.get("requests")
                batch_results = (call.get("result") or {}).get("results")
                if isinstance(requests, list) and isinstance(batch_results, list):
                    for request, batch_result in zip(requests, batch_results):
                        if _call_matches_subquestion(request, expected) and isinstance(batch_result, dict):
                            result_id = str(batch_result.get("result_id") or "").strip()
                            if result_id:
                                real_ids.add(result_id)
        real_ids.discard("")
        references = {
            str(item).strip()
            for item in actual.get("computation_refs") or []
            if str(item).strip()
        }
        if not real_ids:
            raise SpatialToolAgentError(f"spatial_tool_result_id_missing:{index}")
        if not references or not references <= real_ids:
            raise SpatialToolAgentError(f"spatial_computation_ref_mismatch:{index}")


def analyze_spatial_question(
    *,
    history_id: str,
    question: str,
    evidence_executor: Callable[[str, list[dict[str, Any]]], Mapping[str, Any]] | None = None,
) -> dict:
    """Decompose a question, then execute deterministic spatial computations.

    Planning and computation are separate Harness turns so the domain tool cannot
    be called before the Agent has produced a bounded set of semantic subquestions.
    """

    normalized_history_id = str(history_id or "").strip()
    normalized_question = str(question or "").strip()
    if not normalized_history_id:
        raise ValueError("history_id_required")
    if not normalized_question:
        raise ValueError("question_required")

    if evidence_executor is not None:
        plan = _deterministic_plan(normalized_question)
        batch = evidence_executor(normalized_history_id, plan)
        raw_results = batch.get("results") if isinstance(batch, Mapping) else None
        results = raw_results if isinstance(raw_results, list) else []
        subquestions: list[dict[str, Any]] = []
        unresolved: list[str] = []
        for item, result in zip(plan, results):
            result_mapping = result if isinstance(result, Mapping) else {}
            result_id = str(result_mapping.get("result_id") or "").strip()
            if not result_id:
                unresolved.append(f"{item['question']}：未返回可复核的 result_id")
                continue
            if str(result_mapping.get("status") or "") not in {"available", "partial"}:
                unresolved.append(f"{item['question']}：{_result_finding(result_mapping)}")
            subquestions.append({
                **item,
                "finding": _result_finding(result_mapping),
                "computation_refs": [result_id],
            })
        if len(subquestions) != len(plan):
            raise SpatialToolAgentError("spatial_plan_without_tool_call")
        return {
            "question": normalized_question,
            "subquestions": subquestions,
            "synthesis": f"已完成 {len(subquestions)} 项确定性空间计算；详细证据通过 computation_refs 复核。",
            "spatial_implications": ["依据各空间结果的时间圈、方向或局部关系组织后续判断。"],
            "unresolved": unresolved,
        }

    planning_prompt = "\n".join(
        [
            "你是城市空间工具 Agent 的问题拆解阶段。只理解用户问题并拆成必要的空间子问题，不调用任何工具，不写分析结论。",
            f"项目材料编号：{normalized_history_id}",
            f"空间问题：{normalized_question}",
            "事实域知识：" + SPATIAL_EVIDENCE_KNOWLEDGE,
            "可选事实域：" + _fact_domain_catalog(),
            "可选空间操作：scope用于范围事实和事实域发现；accessibility用于真实路网时间圈；direction用于八方向比较；neighborhood用于指定单元邻域；rank用于单域极值；relationship用于2至4个事实域的共位，也用于一个POI事实域内两个明确业态的点关系；inspect用于展开已有记录引用。",
            "夜光操作语义：scope看圈内亮度构成；accessibility看等时带亮度增量；direction看圈内八方向差异；neighborhood看目标格与相邻格反差；rank找明暗候选格；relationship看夜光与其他事实的共同格网错位；inspect解释指定夜光格的圈内位置与局部上下文。",
            "选择能够改变问题判断的最小证据组合。总体存量用scope；空间流向用direction；服务覆盖用accessibility；寻找极值后可继续inspect或neighborhood；只有问题要求跨域共同出现或错位时才用relationship。不要用scope总量回答方向、可达性或局部关系问题。",
            "为每个子问题选择一个七操作中的操作、相关事实域和能改变判断的最小语义维度。不要选择或枚举底层指标，具体字段和聚合策略由领域工具内部决定。",
            "rank和跨域relationship必须为每个事实域明确一个语义维度。一个POI事实域内的业态关系使用poi.supply，并在poi.category中给出两个业态，由POI执行器决定具体方法。POI与人口共同做accessibility时只给出一个poi.category；执行器按设施等权计算各人口格网的相对供需可达水平。road.to_movement表示到达潜力，road.through_movement表示穿行潜力，不能互相替代。",
            _poi_selector_guidance(),
            "需要具名候选时可使用 named_poi_roles：regional_anchor 表示区域交通、文化和公共服务锚点，daily_service 表示居民日常服务节点；两者会优先覆盖不同 POI 类别。候选只是现场核验和接洽清单，不是已确认客群来源、合作方或到访关系；comparable_supply 只有在同时给出明确 poi.category selector 时才可使用。",
            "最终只返回符合问题拆解 JSON Schema 的计划。",
        ]
    )
    try:
        plan = run_codex(
            prompt=planning_prompt,
            schema_path=SPATIAL_PLAN_SCHEMA_PATH,
            enabled_tools=[],
        )
        plan = _bound_spatial_plan(plan)
        execution_prompt = "\n".join(
            [
                "你是城市空间工具 Agent 的执行与综合阶段。按照给定问题拆解计划，调用确定性空间计算工具获取事实，再为每个子问题形成判断并综合整体含义。",
                f"项目材料编号：{normalized_history_id}",
                f"原始空间问题：{normalized_question}",
                "问题拆解计划：" + json.dumps(plan, ensure_ascii=False, separators=(",", ":")),
                "按计划中的 selectors、travel_time_bands_min、neighbor_steps、rank_order、top_k 和 record_refs 传递用户已明确的筛选、时间、邻域、排序和记录参数；没有给出的参数由领域工具默认处理。优先对彼此独立且不依赖 record_refs 的子问题一次调用 compute_spatial_evidence_batch 并行获取空间事实，批量请求必须按计划原顺序传递完整参数。只有需要先取得前一步 record_ref 的 inspect 或 neighborhood 才使用单个 compute_spatial_evidence 串行等待。可以为一个子问题进行多次互补计算；每次调用都必须服务于计划中的子问题。不要选择或枚举底层指标，具体字段和聚合策略由领域工具内部决定。",
                "需要具名地点或道路时先用rank取得record_ref，或直接用已有record_ref调用inspect；需要核查候选周边关系时调用neighborhood。",
                _poi_selector_guidance(),
                "按计划原样传递 named_poi_roles；它只返回候选具名对象，不把候选自动解释为已验证锚点、合作方或客群来源。",
                "只依据工具返回结果形成判断，并在每个子问题的 computation_refs 中保留所用 result_id。工具执行失败或证据不足时直接说明，不虚构结果。",
                "最终只返回符合指定空间分析 JSON Schema 的结果。",
            ]
        )
        result = run_codex(
            prompt=execution_prompt,
            schema_path=SPATIAL_ANALYSIS_SCHEMA_PATH,
            enabled_tools=["compute_spatial_evidence", "compute_spatial_evidence_batch"],
            tool_call_validator=_plan_tool_call_validator(plan, history_id=normalized_history_id),
            output_validator=_plan_output_validator(plan),
        )
        return result
    except CodexHarnessError as exc:
        raise SpatialToolAgentError(str(exc)) from exc
