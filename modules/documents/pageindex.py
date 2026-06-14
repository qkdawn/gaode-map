from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List

from core.config import settings
from store.ai_database import SessionLocal
from store.ai_models import Document, DocumentBlock, DocumentIndexNode

from .schemas import DocumentIndexNodeRecord
from .service import DocumentNotFound


_ROOT_NODE_ID = "root"
_MAX_NODE_TEXT_CHARS = 2400
_MAX_NODE_SUMMARY_CHARS = 360
_CHINESE_HEADING_RE = re.compile(r"^([一二三四五六七八九十]+)[、.．]")
_NUMBERED_HEADING_RE = re.compile(r"^([0-9]+)[、.．]")


@dataclass
class _IndexSeed:
    node_id: str
    parent_node_id: str
    title: str
    level: int
    ordinal: int
    start_block_index: int
    end_block_index: int
    page_start: int
    page_end: int
    text_parts: List[str]


class PageIndexDocumentNotReady(RuntimeError):
    pass


def rebuild_document_index(document_id: str) -> List[DocumentIndexNodeRecord]:
    normalized_id = _normalize_document_id(document_id)
    session = SessionLocal()
    try:
        _replace_document_index(session, normalized_id)
        session.commit()
        return [_node_payload(row) for row in _ordered_nodes(session, normalized_id)]
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def rebuild_document_index_in_session(session, document_id: str) -> None:
    _replace_document_index(session, _normalize_document_id(document_id))


def list_document_index_nodes(document_id: str) -> List[DocumentIndexNodeRecord]:
    normalized_id = _normalize_document_id(document_id)
    session = SessionLocal()
    try:
        document = session.get(Document, normalized_id)
        if document is None:
            raise DocumentNotFound("document_not_found")
        nodes = _ordered_nodes(session, normalized_id)
    finally:
        session.close()
    if not nodes and document.status == "parsed":
        return rebuild_document_index(normalized_id)
    return [_node_payload(row) for row in nodes]


def _replace_document_index(session, document_id: str) -> None:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNotFound("document_not_found")
    blocks = (
        session.query(DocumentBlock)
        .filter_by(document_id=document_id)
        .order_by(DocumentBlock.page_index.asc(), DocumentBlock.block_index.asc(), DocumentBlock.id.asc())
        .all()
    )
    markdown_path = _write_pageindex_markdown(document, blocks)
    pageindex_payload = _build_pageindex_payload(markdown_path)
    seeds = _pageindex_tree_to_seeds(pageindex_payload, document, blocks)
    session.query(DocumentIndexNode).filter_by(document_id=document_id).delete()
    for seed in seeds:
        text = _join_text(seed.text_parts)
        session.add(
            DocumentIndexNode(
                document_id=document_id,
                node_id=seed.node_id,
                parent_node_id=seed.parent_node_id,
                title=seed.title[:255],
                level=seed.level,
                ordinal=seed.ordinal,
                start_block_index=seed.start_block_index,
                end_block_index=seed.end_block_index,
                page_start=seed.page_start,
                page_end=max(seed.page_start, seed.page_end),
                summary=_summarize_node(seed.title, text),
                text=text[:_MAX_NODE_TEXT_CHARS],
                meta={
                    "index_kind": "pageindex",
                    "source": "pageindex_markdown",
                    "line_num": seed.start_block_index,
                    "markdown_path": str(markdown_path),
                    "content_chars": len(text),
                },
                created_at=datetime.utcnow(),
            )
        )


def _normalize_document_id(document_id: str) -> str:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        raise DocumentNotFound("document_not_found")
    return normalized_id


def _ordered_nodes(session, document_id: str) -> List[DocumentIndexNode]:
    return (
        session.query(DocumentIndexNode)
        .filter_by(document_id=document_id)
        .order_by(DocumentIndexNode.ordinal.asc(), DocumentIndexNode.id.asc())
        .all()
    )


def get_pageindex_document(document_id: str) -> str:
    normalized_id = _normalize_document_id(document_id)
    session = SessionLocal()
    try:
        document = session.get(Document, normalized_id)
        if document is None:
            raise DocumentNotFound("document_not_found")
        nodes = _ordered_nodes(session, normalized_id)
        if not nodes and document.status == "parsed":
            session.close()
            rebuild_document_index(normalized_id)
            session = SessionLocal()
            document = session.get(Document, normalized_id)
            nodes = _ordered_nodes(session, normalized_id)
        payload = {
            "doc_id": normalized_id,
            "doc_name": str(document.title or document.file_name or ""),
            "type": "md",
            "status": "completed" if nodes else "pending",
            "line_count": _pageindex_line_count(nodes),
        }
        return json.dumps(payload, ensure_ascii=False)
    finally:
        session.close()


def get_pageindex_document_structure(document_id: str) -> str:
    normalized_id = _normalize_document_id(document_id)
    nodes = list_document_index_nodes(normalized_id)
    structure = _nodes_to_pageindex_structure(nodes, include_text=False)
    return json.dumps(structure, ensure_ascii=False)


def get_pageindex_page_content(document_id: str, pages: str) -> str:
    normalized_id = _normalize_document_id(document_id)
    line_nums = _parse_pageindex_pages(pages)
    nodes = list_document_index_nodes(normalized_id)
    if not nodes:
        raise PageIndexDocumentNotReady("pageindex_document_not_ready")
    min_line = min(line_nums)
    max_line = max(line_nums)
    result = []
    seen = set()
    for node in nodes:
        line_num = int((node.meta or {}).get("line_num") or node.start_block_index or node.ordinal or 0)
        if min_line <= line_num <= max_line and line_num not in seen:
            seen.add(line_num)
            result.append({"page": line_num, "content": node.text, "title": node.title, "node_id": node.node_id})
    return json.dumps(result, ensure_ascii=False)


def _build_index_seeds(document: Document, blocks: Iterable[DocumentBlock]) -> List[_IndexSeed]:
    ordered_blocks = [block for block in blocks if str(block.text or "").strip()]
    title = str(document.title or document.file_name or "文档").strip() or "文档"
    root = _IndexSeed(
        node_id=_ROOT_NODE_ID,
        parent_node_id="",
        title=title,
        level=0,
        ordinal=0,
        start_block_index=0,
        end_block_index=0,
        page_start=1,
        page_end=1,
        text_parts=[],
    )
    seeds: List[_IndexSeed] = [root]
    stack: List[_IndexSeed] = [root]

    for block in ordered_blocks:
        text = str(block.text or "").strip()
        page = max(1, int(block.page_index or 0) + 1)
        block_index = int(block.block_index or 0)
        heading_level = _heading_level(block, text)
        if heading_level is not None:
            parent = _parent_for_level(stack, heading_level)
            node = _IndexSeed(
                node_id=f"n{len(seeds)}",
                parent_node_id=parent.node_id,
                title=text[:255],
                level=heading_level,
                ordinal=len(seeds),
                start_block_index=block_index,
                end_block_index=block_index,
                page_start=page,
                page_end=page,
                text_parts=[],
            )
            seeds.append(node)
            stack = [item for item in stack if item.level < heading_level]
            stack.append(node)
            _touch_ancestors(stack, block_index, page)
            continue

        target = stack[-1] if stack else root
        target.text_parts.append(text)
        target.end_block_index = max(target.end_block_index, block_index)
        target.page_end = max(target.page_end, page)
        _touch_ancestors(stack, block_index, page)

    if not root.text_parts:
        root.text_parts = [part for seed in seeds[1:] for part in seed.text_parts[:1]][:3]
    root.end_block_index = max((seed.end_block_index for seed in seeds), default=0)
    root.page_end = max((seed.page_end for seed in seeds), default=1)
    return seeds


def _write_pageindex_markdown(document: Document, blocks: Iterable[DocumentBlock]) -> Path:
    root = Path(settings.document_upload_dir).resolve() / str(document.id) / "pageindex"
    root.mkdir(parents=True, exist_ok=True)
    markdown_path = root / "document.md"
    lines = [f"# {str(document.title or document.file_name or '文档').strip() or '文档'}", ""]
    current_heading = ""
    for block in blocks:
        text = str(block.text or "").strip()
        if not text or text.lower() == "list":
            continue
        heading_level = _heading_level(block, text)
        if heading_level is not None:
            level = min(6, max(2, heading_level + 1))
            lines.extend([f"{'#' * level} {text}", ""])
            current_heading = text
            continue
        if not current_heading and str(block.block_type or "").strip().lower() != "title":
            lines.extend(["## 正文", ""])
            current_heading = "正文"
        lines.extend([text, ""])
    markdown_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return markdown_path


def _build_pageindex_payload(markdown_path: Path) -> dict[str, Any]:
    markdown_content = markdown_path.read_text(encoding="utf-8")
    nodes, lines = _extract_nodes_from_markdown(markdown_content)
    nodes_with_content = _extract_node_text_content(nodes, lines)
    tree = _build_tree_from_nodes(nodes_with_content)
    _write_node_id(tree)
    return {
        "doc_name": markdown_path.stem,
        "line_count": markdown_content.count("\n") + 1,
        "structure": tree,
    }


def _extract_nodes_from_markdown(markdown_content: str) -> tuple[list[dict[str, Any]], list[str]]:
    header_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
    lines = markdown_content.split("\n")
    node_list: list[dict[str, Any]] = []
    in_code_block = False
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not stripped or in_code_block:
            continue
        match = header_pattern.match(stripped)
        if match:
            node_list.append({"node_title": match.group(2).strip(), "line_num": line_num, "level": len(match.group(1))})
    return node_list, lines


def _extract_node_text_content(node_list: list[dict[str, Any]], markdown_lines: list[str]) -> list[dict[str, Any]]:
    all_nodes = [{"title": item["node_title"], "line_num": int(item["line_num"]), "level": int(item["level"])} for item in node_list]
    for index, node in enumerate(all_nodes):
        start_line = node["line_num"] - 1
        end_line = all_nodes[index + 1]["line_num"] - 1 if index + 1 < len(all_nodes) else len(markdown_lines)
        node["text"] = "\n".join(markdown_lines[start_line:end_line]).strip()
    return all_nodes


def _build_tree_from_nodes(node_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stack: list[tuple[dict[str, Any], int]] = []
    root_nodes: list[dict[str, Any]] = []
    for node in node_list:
        tree_node = {
            "title": node["title"],
            "node_id": "",
            "text": node.get("text", ""),
            "line_num": node["line_num"],
            "nodes": [],
        }
        level = int(node["level"])
        while stack and stack[-1][1] >= level:
            stack.pop()
        if not stack:
            root_nodes.append(tree_node)
        else:
            stack[-1][0]["nodes"].append(tree_node)
        stack.append((tree_node, level))
    return root_nodes


def _write_node_id(data: list[dict[str, Any]], counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    for node in data:
        node["node_id"] = str(counter[0]).zfill(4)
        counter[0] += 1
        _write_node_id(node.get("nodes") or [], counter)


def _pageindex_tree_to_seeds(payload: dict[str, Any], document: Document, blocks: Iterable[DocumentBlock]) -> list[_IndexSeed]:
    seeds: list[_IndexSeed] = []
    root_title = str(document.title or document.file_name or "文档").strip() or "文档"
    root = _IndexSeed(
        node_id=_ROOT_NODE_ID,
        parent_node_id="",
        title=root_title,
        level=0,
        ordinal=0,
        start_block_index=1,
        end_block_index=int(payload.get("line_count") or 1),
        page_start=1,
        page_end=max(1, max((int(block.page_index or 0) + 1 for block in blocks), default=1)),
        text_parts=[],
    )
    seeds.append(root)

    def visit(nodes: list[dict[str, Any]], parent_id: str, level: int) -> None:
        for node in nodes:
            text = _strip_markdown_heading(str(node.get("text") or ""))
            seed = _IndexSeed(
                node_id=str(node.get("node_id") or f"n{len(seeds)}"),
                parent_node_id=parent_id,
                title=str(node.get("title") or "")[:255],
                level=level,
                ordinal=len(seeds),
                start_block_index=int(node.get("line_num") or len(seeds)),
                end_block_index=_max_line_num(node),
                page_start=1,
                page_end=1,
                text_parts=[text] if text else [],
            )
            seeds.append(seed)
            visit(list(node.get("nodes") or []), seed.node_id, level + 1)

    visit(list(payload.get("structure") or []), _ROOT_NODE_ID, 1)
    return seeds


def _strip_markdown_heading(text: str) -> str:
    lines = str(text or "").splitlines()
    if lines and re.match(r"^#{1,6}\s+", lines[0].strip()):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _max_line_num(node: dict[str, Any]) -> int:
    values = [int(node.get("line_num") or 0)]
    for child in list(node.get("nodes") or []):
        values.append(_max_line_num(child))
    return max(values)


def _nodes_to_pageindex_structure(nodes: list[DocumentIndexNodeRecord], *, include_text: bool) -> list[dict[str, Any]]:
    children: dict[str, list[DocumentIndexNodeRecord]] = {}
    for node in nodes:
        children.setdefault(node.parent_node_id or "", []).append(node)

    def build(parent_id: str) -> list[dict[str, Any]]:
        result = []
        for node in sorted(children.get(parent_id, []), key=lambda item: item.ordinal):
            if node.node_id == _ROOT_NODE_ID:
                result.extend(build(node.node_id))
                continue
            item = {
                "title": node.title,
                "node_id": node.node_id,
                "line_num": int((node.meta or {}).get("line_num") or node.start_block_index or node.ordinal),
            }
            if node.summary:
                item["summary"] = node.summary
            if include_text:
                item["text"] = node.text
            nested = build(node.node_id)
            if nested:
                item["nodes"] = nested
            result.append(item)
        return result

    return build("")


def _pageindex_line_count(nodes: list[DocumentIndexNode]) -> int:
    return max((int((node.meta or {}).get("line_num") or node.start_block_index or node.ordinal or 0) for node in nodes), default=0)


def _parse_pageindex_pages(pages: str) -> list[int]:
    result: list[int] = []
    for part in str(pages or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            start = int(start_raw.strip())
            end = int(end_raw.strip())
            if start > end:
                raise ValueError("invalid_page_range")
            result.extend(range(start, end + 1))
        else:
            result.append(int(part))
    if not result:
        raise ValueError("empty_pages")
    return sorted(set(result))


def _heading_level(block: DocumentBlock, text: str) -> int | None:
    block_type = str(block.block_type or "").strip().lower()
    if block_type == "title":
        return 1
    value = str(text or "").strip()
    if not value or len(value) > 48:
        return None
    if _CHINESE_HEADING_RE.match(value):
        return 1
    if _NUMBERED_HEADING_RE.match(value):
        return 2
    if value.endswith(("：", ":")):
        return 2
    return None


def _parent_for_level(stack: List[_IndexSeed], level: int) -> _IndexSeed:
    for seed in reversed(stack):
        if seed.level < level:
            return seed
    return stack[0]


def _touch_ancestors(stack: List[_IndexSeed], block_index: int, page: int) -> None:
    for seed in stack:
        seed.end_block_index = max(seed.end_block_index, block_index)
        seed.page_end = max(seed.page_end, page)


def _join_text(parts: List[str]) -> str:
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _summarize_node(title: str, text: str) -> str:
    collapsed = " ".join(str(text or "").split())
    if not collapsed:
        return str(title or "").strip()[:_MAX_NODE_SUMMARY_CHARS]
    return collapsed[:_MAX_NODE_SUMMARY_CHARS]


def _node_payload(record: DocumentIndexNode) -> DocumentIndexNodeRecord:
    return DocumentIndexNodeRecord(
        id=int(record.id),
        document_id=str(record.document_id),
        node_id=str(record.node_id),
        parent_node_id=str(record.parent_node_id or ""),
        title=str(record.title or ""),
        level=int(record.level or 0),
        ordinal=int(record.ordinal or 0),
        start_block_index=int(record.start_block_index or 0),
        end_block_index=int(record.end_block_index or 0),
        page_start=int(record.page_start or 1),
        page_end=int(record.page_end or record.page_start or 1),
        summary=str(record.summary or ""),
        text=str(record.text or ""),
        meta=dict(record.meta or {}),
        created_at=record.created_at,
    )
