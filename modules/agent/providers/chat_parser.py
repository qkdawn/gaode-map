from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def _strip_json_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _load_json_object(text: str) -> Dict[str, Any]:
    candidates = [text, _strip_json_trailing_commas(text)]
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("llm_json_output_not_object")
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise ValueError("invalid_llm_json_output")


def extract_text_content(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("invalid_chat_completion_payload")
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("invalid_chat_completion_payload")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks)
    raise ValueError("invalid_chat_completion_payload")


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("empty_llm_output")
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        return _load_json_object(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return _load_json_object(text[start:end + 1])
        raise


def merge_tool_call_delta(accumulator: List[Dict[str, Any]], raw_call: Dict[str, Any]) -> None:
    if not isinstance(raw_call, dict):
        return
    raw_index = raw_call.get("index")
    index = int(raw_index) if isinstance(raw_index, int) or str(raw_index).isdigit() else len(accumulator)
    while len(accumulator) <= index:
        accumulator.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    current = accumulator[index]
    if raw_call.get("id"):
        current["id"] = str(raw_call.get("id") or "")
    if raw_call.get("type"):
        current["type"] = str(raw_call.get("type") or "function")
    function_delta = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
    current_function = current.setdefault("function", {"name": "", "arguments": ""})
    if function_delta.get("name"):
        current_function["name"] = str(current_function.get("name") or "") + str(function_delta.get("name") or "")
    if function_delta.get("arguments") is not None:
        current_function["arguments"] = str(current_function.get("arguments") or "") + str(function_delta.get("arguments") or "")


def finalize_tool_calls(accumulator: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    finalized: List[Dict[str, Any]] = []
    for item in accumulator:
        function_payload = item.get("function") if isinstance(item.get("function"), dict) else {}
        if not (str(item.get("id") or "").strip() or str(function_payload.get("name") or "").strip()):
            continue
        finalized.append(
            {
                "id": str(item.get("id") or function_payload.get("name") or "").strip(),
                "type": str(item.get("type") or "function"),
                "function": {
                    "name": str(function_payload.get("name") or "").strip(),
                    "arguments": str(function_payload.get("arguments") or ""),
                },
            }
        )
    return finalized


def parse_chat_completion_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    function_calls: List[Dict[str, Any]] = []
    texts: List[str] = []
    warnings: List[str] = []
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return {"function_calls": function_calls, "texts": texts, "warnings": warnings}
    choice = choices[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        texts.append(content.strip())
    raw_tool_calls = message.get("tool_calls") or []
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            continue
        function_payload = item.get("function") if isinstance(item.get("function"), dict) else {}
        tool_name = str(function_payload.get("name") or "").strip()
        arguments_raw = str(function_payload.get("arguments") or "")
        if not tool_name:
            continue
        try:
            arguments = json.loads(arguments_raw) if arguments_raw else {}
            if not isinstance(arguments, dict):
                raise ValueError("tool_call_arguments_not_object")
            argument_error = ""
        except Exception as exc:
            arguments = {}
            argument_error = f"invalid_tool_call_arguments:{exc}"
            warnings.append(argument_error)
        function_calls.append(
            {
                "call_id": str(item.get("id") or tool_name),
                "tool_name": tool_name,
                "arguments": arguments,
                "argument_error": argument_error,
            }
        )
    return {"function_calls": function_calls, "texts": texts, "warnings": warnings}


def extract_chat_completion_text(payload: Dict[str, Any]) -> str:
    parsed = parse_chat_completion_response(payload)
    texts = [str(item).strip() for item in parsed.get("texts") or [] if str(item).strip()]
    if texts:
        return "\n".join(texts)
    raise ValueError("invalid_chat_completion_output_text")
