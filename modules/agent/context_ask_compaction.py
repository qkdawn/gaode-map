from __future__ import annotations

import json
from typing import Any, Dict, List


def as_text(value: Any) -> str:
    return str(value or "").strip()


def compact_items(items: List[Any], limit: int = 8) -> List[Any]:
    compacted: List[Any] = []
    for item in list(items or [])[:limit]:
        if isinstance(item, dict):
            compacted.append({str(k): v for k, v in list(item.items())[:8]})
        else:
            text = as_text(item)
            if text:
                compacted.append(text[:500])
    return compacted


def compact_value(value: Any, *, depth: int = 2, list_limit: int = 8, string_limit: int = 500) -> Any:
    if depth <= 0:
        if isinstance(value, (dict, list, tuple)):
            return f"{type(value).__name__}({len(value)})"
        if isinstance(value, str):
            return value[:string_limit]
        return value
    if isinstance(value, dict):
        compacted: Dict[str, Any] = {}
        for key, item in list(value.items())[:16]:
            compacted[str(key)] = compact_value(item, depth=depth - 1, list_limit=list_limit, string_limit=string_limit)
        return compacted
    if isinstance(value, (list, tuple)):
        return [
            compact_value(item, depth=depth - 1, list_limit=list_limit, string_limit=string_limit)
            for item in list(value)[:list_limit]
        ]
    if isinstance(value, str):
        return value[:string_limit]
    return value


def compact_evidence_nodes(nodes: List[Any], *, limit: int = 3) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    for node in list(nodes or [])[:limit]:
        if not isinstance(node, dict):
            text = as_text(node)
            if text:
                compacted.append({"content": text[:220]})
            continue
        summary = as_text(node.get("summary"))
        content = as_text(node.get("content") or node.get("text"))
        compacted_node: Dict[str, Any] = {
            "id": as_text(node.get("id") or node.get("node_id")),
            "kind": as_text(node.get("kind")),
            "run_id": as_text(node.get("run_id")),
            "source_ids": compact_items(node.get("source_ids") or [], limit=4),
            "metric_ids": compact_items(node.get("metric_ids") or [], limit=4),
            "title": as_text(node.get("title"))[:160],
        }
        if summary:
            compacted_node["summary"] = summary[:220]
        elif content:
            compacted_node["content"] = content[:220]
        locator = node.get("locator")
        if isinstance(locator, dict):
            compacted_node["locator"] = compact_value(locator, depth=1, list_limit=4, string_limit=120)
        citation = node.get("citation")
        if isinstance(citation, dict):
            compacted_node["citation"] = compact_value(citation, depth=1, list_limit=4, string_limit=120)
        elif as_text(citation):
            compacted_node["citation"] = as_text(citation)[:160]
        compacted.append({key: value for key, value in compacted_node.items() if value not in ("", None, [], {})})
    return compacted


def merge_unique(values: List[Any]) -> List[Any]:
    merged: List[Any] = []
    seen = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) if isinstance(value, (dict, list)) else str(value)
        if key in seen:
            continue
        seen.add(key)
        merged.append(value)
    return merged
