from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from modules.agent_harness import CodexHarnessError, run_codex


CHAPTER_SCHEMA_PATH = Path(__file__).with_name("strategy_chapter.schema.json")
VISUAL_DESIGN_SCHEMA_PATH = Path(__file__).with_name("visual_design.schema.json")
CORE_PROMPT = "基于已有项目材料和空间数据完成用户任务，给出明确判断及行动建议。不要虚构信息；无法完成时直接说明原因。"
STRATEGY_UNIT_IDS = (
    "project_basis",
    "regional_role",
    "supply_gap",
    "audience_use",
    "theme_resources",
    "positioning",
    "product_mix",
    "spatial_layout",
    "operating_model",
    "investment_operation",
    "phasing",
)
_FAILED_TOOL_STATUSES = {
    "data_source_unavailable",
    "failed",
    "invalid_request",
    "not_found",
    "partial",
    "unavailable",
}
_FAILED_CHAPTER_PREFIXES = (
    "无法生成本章节",
    "无法完成本章节",
)
_DEMOGRAPHIC_SUMMARY_REF = "computed:population:summary"


class SpatialStrategyHarnessError(RuntimeError):
    pass


def _tool_name(value: Any) -> str:
    name = str(value or "").rsplit(".", 1)[-1]
    return name.rsplit("__", 1)[-1] or "unknown_tool"


def _run_codex(
    *,
    prompt: str,
    schema_path: Path,
    enabled_tools: list[str],
    tool_call_validator: Callable[[list[dict[str, Any]]], None] | None = None,
    output_validator: Callable[[dict[str, Any], list[dict[str, Any]]], None] | None = None,
) -> dict:
    try:
        return run_codex(
            prompt=prompt,
            schema_path=schema_path,
            enabled_tools=enabled_tools,
            tool_call_validator=tool_call_validator,
            output_validator=output_validator,
        )
    except CodexHarnessError as exc:
        raise SpatialStrategyHarnessError(str(exc)) from exc


def _failed_tool_result(value: Any) -> tuple[str, str] | None:
    if isinstance(value, dict):
        status = str(value.get("status") or "").strip().casefold()
        error = str(value.get("error") or "").strip().casefold()
        if status in _FAILED_TOOL_STATUSES:
            return status, "$.status"
        if error in _FAILED_TOOL_STATUSES:
            return error, "$.error"
    return None


def _validate_strategy_tool_results(calls: list[dict[str, Any]]) -> None:
    for index, call in enumerate(calls):
        name = _tool_name(call.get("name"))
        if call.get("_recoverable_validation_failure"):
            if any(
                _tool_name(later.get("name")) == name
                and str(later.get("status") or "") not in {"failed", "declined"}
                and not _failed_tool_result(later.get("result"))
                for later in calls[index + 1 :]
            ):
                continue
            raise SpatialStrategyHarnessError(
                f"strategy_tool_failed:{name}:invalid_request"
            )
        failure = _failed_tool_result(call.get("result"))
        if failure:
            status, path = failure
            raise SpatialStrategyHarnessError(
                f"strategy_tool_failed:{name}:{status}:{path}"
            )


def _strategy_tool_validator(
    *,
    run_id: str,
    history_id: str | None = None,
    required_chapter_ids: list[str],
):
    def validate(calls: list[dict[str, Any]]) -> None:
        if history_id:
            for call in calls:
                arguments = call.get("arguments")
                if not isinstance(arguments, dict) or "history_id" not in arguments:
                    continue
                if str(arguments.get("history_id") or "").strip() != history_id:
                    raise SpatialStrategyHarnessError(
                        f"strategy_tool_history_scope_mismatch:{_tool_name(call.get('name'))}"
                    )
        _validate_strategy_tool_results(calls)
        chapter_calls = [
            call
            for call in calls
            if _tool_name(call.get("name")) == "read_strategy_chapters"
            and not call.get("_recoverable_validation_failure")
        ]
        if not required_chapter_ids:
            if chapter_calls:
                raise SpatialStrategyHarnessError("strategy_chapter_read_not_allowed")
            return
        if len(chapter_calls) != 1:
            raise SpatialStrategyHarnessError("strategy_chapter_read_count_invalid")
        arguments = chapter_calls[0].get("arguments")
        if not isinstance(arguments, dict):
            raise SpatialStrategyHarnessError("strategy_chapter_read_arguments_invalid")
        actual_ids = arguments.get("unit_ids")
        if (
            str(arguments.get("run_id") or "").strip() != run_id
            or actual_ids != required_chapter_ids
        ):
            raise SpatialStrategyHarnessError("strategy_chapter_read_scope_mismatch")

    return validate


def _chapter_output_validator(unit_id: str, title: str):
    def validate(output: dict[str, Any], _calls: list[dict[str, Any]]) -> None:
        if str(output.get("unit_id") or "").strip() != unit_id:
            raise SpatialStrategyHarnessError("strategy_chapter_unit_id_mismatch")
        if str(output.get("title") or "").strip() != title:
            raise SpatialStrategyHarnessError("strategy_chapter_title_mismatch")
        content = str(output.get("content") or "").strip()
        if not content:
            raise SpatialStrategyHarnessError("strategy_chapter_content_missing")
        if content.startswith(_FAILED_CHAPTER_PREFIXES):
            raise SpatialStrategyHarnessError("strategy_chapter_generation_failed")
        citations = output.get("citations")
        if not isinstance(citations, list):
            raise SpatialStrategyHarnessError("strategy_chapter_citations_invalid")
        if unit_id != "audience_use" and any(
            str(citation.get("record_ref") or citation.get("source_locator") or "").strip()
            == _DEMOGRAPHIC_SUMMARY_REF
            for citation in citations
            if isinstance(citation, dict)
        ):
            raise SpatialStrategyHarnessError(
                "strategy_chapter_demographic_evidence_not_owned"
            )

    return validate


def analyze_strategy_unit(
    *,
    run_id: str,
    history_id: str,
    project_question: str,
    decision_unit: dict,
) -> dict:
    unit_id = str(decision_unit.get("unit_id") or "").strip()
    title = str(decision_unit.get("title") or "").strip()
    if unit_id not in STRATEGY_UNIT_IDS or not title:
        raise SpatialStrategyHarnessError("strategy_unit_invalid")
    depends_on = [
        str(item).strip()
        for item in decision_unit.get("depends_on", [])
        if str(item).strip()
    ]
    if any(item not in STRATEGY_UNIT_IDS for item in depends_on):
        raise SpatialStrategyHarnessError("strategy_unit_dependency_invalid")
    task = {
        key: decision_unit[key]
        for key in (
            "unit_id",
            "title",
            "question",
            "depends_on",
            "decision_output",
            "evidence_focus",
            "spatial_questions",
        )
        if key in decision_unit
    }
    prior_instruction = (
        "本章没有前序章节，不要调用 read_strategy_chapters。"
        if not depends_on
        else "调用一次 read_strategy_chapters，只读取这些前序章节："
        + json.dumps(depends_on, ensure_ascii=False)
        + "。"
    )
    prompt = "\n".join(
        [
            CORE_PROMPT,
            f"项目任务：{project_question}",
            f"运行编号：{run_id}",
            f"项目材料编号：{history_id}",
            f"所有项目工具的 history_id 必须严格使用 {history_id}，不得缩写、改写或使用 run_id。",
            "当前章节任务：" + json.dumps(task, ensure_ascii=False),
            prior_instruction,
            (
                "使用 project_context 读取项目、材料和数据目录。按当前章节的 spatial_questions 把完整问题交给 analyze_spatial_question；该工具会自动复用相同的稳定计算。只对当前任务需要的 spatial: 引用调用 read_spatial_evidence_result。"
                if task.get("spatial_questions")
                else "使用 project_context 读取项目、材料和数据目录。本章没有新增空间问题，只消费前序章节和项目材料，不调用空间计算或空间结果读取工具。"
            ),
            "前序章节只用于继承已完成判断。本章只写当前任务新增的判断、取舍和行动，不复述前序章节的数据、比例、假设表或验证表。",
            (
                "人口总量、年龄结构及其引用只由客群与使用章节持有。本章可继承客群结论，但不重复人口数字，也不在 citations 中复制 computed:population:summary。"
                if unit_id != "audience_use"
                else "本章负责人口总量、年龄结构及其客群含义；统一使用项目目录中的确定性人口汇总。"
            ),
            "直接撰写可交付的 Markdown 章节正文。章节内容按当前任务自由组织，先给明确判断，再写依据、取舍和行动建议；不要描述 Agent、Harness、工具调用、工作流或执行过程。",
            "工具或数据读取失败时不要生成章节；不要把失败改写成证据不足、降级定位或待核验结论。citations 只填写工具真实返回的来源定位，不虚构来源。",
            f"最终只返回 unit_id={unit_id}、title={title}、content、citations 四个字段。",
        ]
    )
    enabled_tools = ["project_context"]
    if task.get("spatial_questions"):
        enabled_tools.extend([
            "analyze_spatial_question",
            "read_spatial_evidence_result",
        ])
    if depends_on:
        enabled_tools.insert(0, "read_strategy_chapters")
    if unit_id in {
        "project_basis",
        "theme_resources",
        "positioning",
        "product_mix",
        "spatial_layout",
        "operating_model",
        "investment_operation",
        "phasing",
    }:
        enabled_tools.append("read_project_document")
    if unit_id in {"theme_resources", "positioning", "product_mix"}:
        enabled_tools.append("search_literature_evidence")
    return _run_codex(
        prompt=prompt,
        schema_path=CHAPTER_SCHEMA_PATH,
        enabled_tools=enabled_tools,
        tool_call_validator=_strategy_tool_validator(
            run_id=run_id,
            history_id=history_id,
            required_chapter_ids=depends_on,
        ),
        output_validator=_chapter_output_validator(unit_id, title),
    )


def design_strategy_visuals(*, run_id: str, project_question: str, visual_task: str) -> dict:
    prompt = "\n".join(
        [
            CORE_PROMPT,
            "为城市空间策略报告设计3到5张数据图或表。每张图只回答一个决策问题，并紧邻对应章节。",
            f"运行编号：{run_id}",
            f"项目任务：{project_question}",
            f"图件任务：{visual_task}",
            "调用一次 read_strategy_chapters，读取这11个已完成章节："
            + json.dumps(STRATEGY_UNIT_IDS, ensure_ascii=False)
            + "。再按需读取项目目录和空间结果。图件解释已有章节判断，不重新提出总体方案。",
            "只使用项目目录中存在的 dataset_id。需要标注具名 POI 时，只使用章节 citations 中已有的 record_ref。不要根据名称、距离或关键词重新判断节点重要性。",
            "地图若包含 poi 图层，必须同时包含 road_edges 图层并设置 map_variant；没有道路上下文时不要设计 POI 地图，改用不含 poi 的地图、图表或表格。",
            "工具或数据读取失败时不要生成图件方案。最终只返回符合指定 JSON Schema 的图件方案。",
        ]
    )
    return _run_codex(
        prompt=prompt,
        schema_path=VISUAL_DESIGN_SCHEMA_PATH,
        enabled_tools=[
            "read_strategy_chapters",
            "project_context",
            "analyze_spatial_question",
            "read_spatial_evidence_result",
        ],
        tool_call_validator=_strategy_tool_validator(
            run_id=run_id,
            required_chapter_ids=list(STRATEGY_UNIT_IDS),
        ),
    )
