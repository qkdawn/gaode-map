from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Tuple

from .context_ask_compaction import as_text, merge_unique
from .executor import execute_plan_step
from .providers.chat_parser import extract_json_object, parse_chat_completion_response
from .providers.client import get_llm_provider_client
from .providers.tool_loop import chat_completion_tools, tool_output_payload
from .schemas import AgentContextAskRequest, AnalysisSnapshot, PlanStep, ToolResult
from .selected_sources import (
    is_analysis_sources_type,
    source_items_from_target,
    source_summary_payloads_from_items,
)
from .source_qa_prompts import SOURCE_QA_SYSTEM_PROMPT, source_qa_final_synthesis_instructions
from .source_qa_tools import (
    failed_source_qa_tool_result,
    selected_dataset_source_ids,
    selected_source_records,
    source_qa_registry,
    validate_source_qa_arguments,
)
from .tool_definitions.source_evidence import (
    selected_source_tool_context,
)


MAX_TOOL_ROUNDS = 4
MAX_TOOL_CALLS = 8


@dataclass
class SourceQaResult:
    status: str = "success"
    answer: str = ""
    evidence: List[Any] = field(default_factory=list)
    citations: List[Any] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    used_tools: List[str] = field(default_factory=list)
    error: str = ""


def _target_sources_summary(payload: AgentContextAskRequest) -> List[Dict[str, Any]]:
    return source_summary_payloads_from_items(source_items_from_target(payload.target))


def _initial_user_payload(payload: AgentContextAskRequest, allowed_source_ids: List[str]) -> Dict[str, Any]:
    return {
        "question": payload.question,
        "conversation_id": payload.conversation_id,
        "history_id": payload.history_id,
        "target": {
            "type": payload.target.type,
            "id": payload.target.id,
            "title": payload.target.title,
            "summary": payload.target.summary,
            "artifact_refs": list(payload.target.artifact_refs or []),
            "sources": _target_sources_summary(payload),
        },
        "allowed_source_ids": allowed_source_ids,
        "instructions": [
            "只能围绕 allowed_source_ids 和已选 sources 回答。",
            "具体对象、局部原因、TopN、分布差异必须先查 scoped dataset 工具。",
            "如果工具结果只有当前范围内部证据，要明确不能证明相对外部区域的优劣。",
            "最终 answer 要有见地且结构清晰；复杂问题可以使用 Markdown 小标题，但标题必须由内容自然生成。",
        ],
    }


def _json_content(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def _chat_completion(request_body: Dict[str, Any]) -> Dict[str, Any]:
    client = get_llm_provider_client()
    if client is None:
        raise ValueError("llm_provider_not_configured")
    return await client.chat_completion(
        request_body=request_body,
        phase="source_qa",
        title="来源问答检索",
        reasoning_id="source-qa",
        enable_thinking=False,
    )


def _assistant_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, dict) else {}


def _normalize_tool_call(raw: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any], str]:
    call_id = as_text(raw.get("call_id") or raw.get("id"))
    name = as_text(raw.get("tool_name") or raw.get("name"))
    args = raw.get("arguments") or raw.get("args")
    argument_error = as_text(raw.get("argument_error"))
    return call_id or name, name, args if isinstance(args, dict) else {}, argument_error


def _collect_tool_evidence(results: List[ToolResult]) -> Tuple[List[Any], List[Any], List[str]]:
    evidence: List[Any] = []
    citations: List[Any] = []
    warnings: List[str] = []
    for result in results:
        warnings.extend([as_text(item) for item in list(result.warnings or []) if as_text(item)])
        nodes = []
        nodes.extend([node for node in list(result.evidence or []) if _is_evidence_node_payload(node)])
        if isinstance(result.artifacts, dict):
            nodes.extend([node for node in list(result.artifacts.get("scope_dataset_evidence_nodes") or []) if _is_evidence_node_payload(node)])
            selected_nodes = result.artifacts.get("selected_source_evidence_nodes")
            if isinstance(selected_nodes, list):
                nodes.extend([node for node in selected_nodes if _is_evidence_node_payload(node)])
        payload_nodes = result.result.get("evidence_nodes") if isinstance(result.result, dict) else []
        nodes.extend([node for node in list(payload_nodes or []) if _is_evidence_node_payload(node)])
        payload_node = result.result.get("evidence_node") if isinstance(result.result, dict) else None
        if _is_evidence_node_payload(payload_node):
            nodes.append(payload_node)
        for node in nodes:
            evidence.append(node)
            citation = node.get("citation")
            if citation not in (None, "", [], {}) and citation not in citations:
                citations.append(citation)
    return evidence, citations, warnings


def _is_evidence_node_payload(value: Any) -> bool:
    return isinstance(value, dict) and bool(as_text(value.get("id"))) and bool(as_text(value.get("source_id") or value.get("sourceId")))


async def run_source_qa_loop(payload: AgentContextAskRequest) -> SourceQaResult:
    if not is_analysis_sources_type(payload.target.type):
        return SourceQaResult(status="skipped", error="target_not_selected_sources")
    allowed_source_ids = selected_dataset_source_ids(payload)
    history_id = as_text(payload.history_id)
    if allowed_source_ids and not history_id:
        return SourceQaResult(status="failed", error="history_id_required", warnings=["已选来源包含当前范围数据源，但缺少 history_id，无法执行来源工具检索。"])

    registry = source_qa_registry(payload)
    snapshot_payload = payload.analysis_snapshot.model_dump(mode="python")
    context = snapshot_payload.get("context") if isinstance(snapshot_payload.get("context"), dict) else {}
    snapshot_payload["context"] = {**context, "history_id": history_id}
    snapshot = AnalysisSnapshot(**snapshot_payload)
    tool_schemas = chat_completion_tools(registry)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SOURCE_QA_SYSTEM_PROMPT},
        {"role": "user", "content": _json_content(_initial_user_payload(payload, allowed_source_ids))},
    ]
    tool_results: List[ToolResult] = []
    used_tools: List[str] = []
    warnings: List[str] = []
    qa_artifacts: Dict[str, Any] = {
        "selected_source_tool_context": selected_source_tool_context(
            selected_source_records(payload),
            include_mapped_dataset_ids=True,
        )
    }

    for _round in range(MAX_TOOL_ROUNDS):
        body: Dict[str, Any] = {
            "messages": messages,
            "tools": tool_schemas,
            "tool_choice": "auto",
            "temperature": 0.1,
        }
        response = await _chat_completion(body)
        parsed = parse_chat_completion_response(response)
        tool_calls = list(parsed.get("function_calls") or [])
        message = _assistant_message(response)
        if not tool_calls:
            text = "\n".join([as_text(item) for item in list(parsed.get("texts") or []) if as_text(item)])
            data = extract_json_object(text)
            evidence, citations, tool_warnings = _collect_tool_evidence(tool_results)
            return SourceQaResult(
                status="success",
                answer=as_text(data.get("answer")),
                evidence=merge_unique(list(data.get("evidence") or []) + evidence),
                citations=merge_unique(list(data.get("citations") or []) + citations),
                warnings=merge_unique([as_text(item) for item in list(data.get("warnings") or []) if as_text(item)] + warnings + tool_warnings),
                tool_results=tool_results,
                used_tools=merge_unique(used_tools),
            )

        messages.append(message or {"role": "assistant", "content": "", "tool_calls": []})
        for raw_call in tool_calls:
            if len(tool_results) >= MAX_TOOL_CALLS:
                warnings.append(f"来源问答工具调用超过上限 {MAX_TOOL_CALLS}，已停止继续检索。")
                break
            call_id, tool_name, arguments, argument_error = _normalize_tool_call(raw_call)
            if argument_error:
                result = failed_source_qa_tool_result(tool_name, argument_error)
            elif tool_name not in registry:
                result = failed_source_qa_tool_result(tool_name, f"tool_not_allowed:{tool_name}")
            else:
                clean_args, validation_error = validate_source_qa_arguments(
                    tool_name=tool_name,
                    arguments=arguments,
                    history_id=history_id,
                    allowed_source_ids=allowed_source_ids,
                )
                if validation_error:
                    result = failed_source_qa_tool_result(tool_name, validation_error)
                else:
                    result, _trace = await execute_plan_step(
                        registered_tool=registry[tool_name],
                        step=PlanStep(
                            tool_name=tool_name,
                            arguments=clean_args,
                            reason="source_qa_tool_call",
                            expected_artifacts=list(registry[tool_name].spec.produces or []),
                        ),
                        snapshot=snapshot,
                        artifacts=qa_artifacts,
                        question=as_text(payload.question),
                        run_preflight=False,
                    )
            tool_results.append(result)
            if result.status == "success":
                used_tools.append(result.tool_name)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id or tool_name,
                    "name": tool_name,
                    "content": tool_output_payload(result),
                }
            )
        if len(tool_results) >= MAX_TOOL_CALLS:
            break

    evidence, citations, tool_warnings = _collect_tool_evidence(tool_results)
    final_payload = {
        "question": payload.question,
        "allowed_source_ids": allowed_source_ids,
        "tool_results": [json.loads(tool_output_payload(result)) for result in tool_results],
        "instructions": source_qa_final_synthesis_instructions(),
    }
    final_body = {
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SOURCE_QA_SYSTEM_PROMPT},
            {"role": "user", "content": _json_content(final_payload)},
        ],
        "temperature": 0.1,
    }
    response = await _chat_completion(final_body)
    text = "\n".join([as_text(item) for item in list(parse_chat_completion_response(response).get("texts") or []) if as_text(item)])
    data = extract_json_object(text)
    return SourceQaResult(
        status="success",
        answer=as_text(data.get("answer")),
        evidence=merge_unique(list(data.get("evidence") or []) + evidence),
        citations=merge_unique(list(data.get("citations") or []) + citations),
        warnings=merge_unique([as_text(item) for item in list(data.get("warnings") or []) if as_text(item)] + warnings + tool_warnings),
        tool_results=tool_results,
        used_tools=merge_unique(used_tools),
    )
