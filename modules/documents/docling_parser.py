from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List


@dataclass(frozen=True)
class ParsedDocumentBlock:
    page_index: int
    block_index: int
    block_type: str
    text: str
    section_title: str = ""


def parse_document_with_docling(file_path: str) -> List[ParsedDocumentBlock]:
    try:
        from docling.document_converter import DocumentConverter
    except Exception as exc:
        raise RuntimeError("docling_unavailable") from exc

    result = DocumentConverter().convert(Path(file_path))
    document = getattr(result, "document", result)
    raw_blocks = list(_iter_docling_blocks(document))
    return _normalize_blocks(raw_blocks)


def _iter_docling_blocks(document: Any) -> Iterable[dict[str, Any]]:
    exported = _export_document(document)
    if isinstance(exported, dict):
        for key in ("texts", "pictures", "tables", "groups", "body"):
            for item in _safe_list(exported.get(key)):
                yield from _iter_exported_item(item)
        if not any(key in exported for key in ("texts", "tables", "groups", "body")):
            yield from _iter_exported_item(exported)
        return

    for attr_name in ("texts", "tables"):
        for item in _safe_list(getattr(document, attr_name, [])):
            yield _item_payload(item)


def _export_document(document: Any) -> Any:
    for method_name in ("export_to_dict", "export_to_document_tokens"):
        method = getattr(document, method_name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                continue
    return None


def _iter_exported_item(item: Any) -> Iterable[dict[str, Any]]:
    if isinstance(item, dict):
        if "children" in item:
            for child in _safe_list(item.get("children")):
                yield from _iter_exported_item(child)
        if any(key in item for key in ("text", "label", "type", "data", "table_cells", "rows")):
            yield item
        return
    yield _item_payload(item)


def _item_payload(item: Any) -> dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    if payload:
        return payload
    return {
        "text": getattr(item, "text", ""),
        "label": getattr(item, "label", ""),
        "type": getattr(item, "type", ""),
        "page_no": getattr(item, "page_no", None),
        "prov": getattr(item, "prov", None),
        "data": getattr(item, "data", None),
    }


def _normalize_blocks(raw_blocks: List[dict[str, Any]]) -> List[ParsedDocumentBlock]:
    blocks: List[ParsedDocumentBlock] = []
    section_title = ""
    for raw in raw_blocks:
        block_type = _block_type(raw)
        text = _block_text(raw, block_type)
        if not text:
            continue
        page_index = _page_index(raw)
        block_index = len(blocks)
        inherited_section = "" if block_type == "title" else section_title
        blocks.append(
            ParsedDocumentBlock(
                page_index=page_index,
                block_index=block_index,
                block_type=block_type,
                text=text,
                section_title=inherited_section,
            )
        )
        if block_type == "title":
            section_title = text[:255]
    return blocks


def _block_type(raw: dict[str, Any]) -> str:
    label = str(raw.get("label") or raw.get("type") or raw.get("self_ref") or "").lower()
    if "table" in label or raw.get("data") or raw.get("table_cells") or raw.get("rows"):
        return "table"
    if "title" in label or "heading" in label or label in {"section_header", "header"}:
        return "title"
    return "paragraph"


def _block_text(raw: dict[str, Any], block_type: str) -> str:
    if block_type == "table":
        table = _table_payload(raw)
        if table:
            return _table_to_markdown(table)
    return str(raw.get("text") or raw.get("content") or raw.get("name") or "").strip()


def _table_payload(raw: dict[str, Any]) -> List[List[str]]:
    if isinstance(raw.get("rows"), list):
        return [[str(cell or "").strip() for cell in row] for row in raw.get("rows") if isinstance(row, list)]
    data = raw.get("data")
    if isinstance(data, dict):
        rows = data.get("table_cells") or data.get("rows") or []
    elif hasattr(data, "table_cells"):
        rows = getattr(data, "table_cells", [])
    else:
        rows = raw.get("table_cells") or []
    if not rows:
        return []
    if rows and all(isinstance(row, list) for row in rows):
        return [[str(cell or "").strip() for cell in row] for row in rows]
    grid: dict[int, dict[int, str]] = {}
    for cell in rows:
        payload = cell if isinstance(cell, dict) else {}
        row_index = int(payload.get("row_index") or payload.get("start_row_offset_idx") or 0)
        col_index = int(payload.get("col_index") or payload.get("start_col_offset_idx") or 0)
        text = str(payload.get("text") or "").strip()
        grid.setdefault(row_index, {})[col_index] = text
    if not grid:
        return []
    width = max(max(cols.keys()) for cols in grid.values()) + 1
    return [[cols.get(col, "") for col in range(width)] for _, cols in sorted(grid.items())]


def _table_to_markdown(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:] or [[""] * width]
    rendered = [header, separator, *body]
    return "\n".join("| " + " | ".join(cell.replace("\n", " ").strip() for cell in row) + " |" for row in rendered)


def _page_index(raw: dict[str, Any]) -> int:
    value = raw.get("pageIndex")
    if value is None:
        value = raw.get("page_index")
    if value is None:
        value = raw.get("page_no")
    if value is None:
        prov = raw.get("prov")
        if isinstance(prov, list) and prov:
            value = _item_payload(prov[0]).get("page_no")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed - 1 if parsed > 0 else parsed)


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []
