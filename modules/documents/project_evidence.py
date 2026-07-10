from __future__ import annotations

import re
from collections import defaultdict
from enum import Enum
from typing import Any, Dict, Iterable, List, Literal, Sequence

from pydantic import BaseModel, Field

from store.ai_database import SessionLocal
from store.ai_models import Document, DocumentIndexNode

from .schemas import DocumentRole


class EvidenceStatus(str, Enum):
    CONFIRMED = "confirmed"
    PENDING_VERIFICATION = "pending_verification"
    DESIGN_INTENT = "design_intent"
    CONFLICTING = "conflicting"


class EvidenceItem(BaseModel):
    id: str
    source_id: str
    document_id: str
    document_title: str
    document_role: DocumentRole
    status: EvidenceStatus
    category: str
    title: str
    content: str
    summary: str = ""
    node_id: str
    page_start: int = 1
    page_end: int = 1
    locator: str
    citation: str


class EvidenceConflict(BaseModel):
    metric_key: str
    label: str
    values: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    preferred_value: str = ""
    preferred_evidence_id: str = ""
    unresolved: bool = False
    explanation: str = ""


class ProjectEvidenceDossier(BaseModel):
    status: Literal["empty", "ready", "partial", "failed"] = "empty"
    question: str = ""
    document_ids: List[str] = Field(default_factory=list)
    document_roles: Dict[str, DocumentRole] = Field(default_factory=dict)
    readable_document_ids: List[str] = Field(default_factory=list)
    unreadable_document_ids: List[str] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    conflicts: List[EvidenceConflict] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    precedence: List[str] = Field(
        default_factory=lambda: [
            "project_brief anchors project facts and constraints",
            "design_vision records intended direction rather than existing conditions",
            "reference_document is supplementary and cannot override project_brief",
            "GIS evidence contextualizes the project and cannot overwrite internal project facts",
        ]
    )

    @property
    def has_project_anchor(self) -> bool:
        return any(role == DocumentRole.PROJECT_BRIEF for role in self.document_roles.values())

    @property
    def has_readable_project_anchor(self) -> bool:
        readable = set(self.readable_document_ids)
        return any(
            role == DocumentRole.PROJECT_BRIEF and document_id in readable
            for document_id, role in self.document_roles.items()
        )


_CORE_ROLES = {DocumentRole.PROJECT_BRIEF, DocumentRole.DESIGN_VISION}
_PENDING_MARKERS = ("待确认", "待核实", "暂定", "初步", "拟", "建议", "约", "左右", "预计", "可能")
_CATEGORY_RULES: Sequence[tuple[str, Sequence[str]]] = (
    ("resident_stakeholders", ("居民", "住户", "住宅", "产权", "共建", "共管", "自治", "安置")),
    ("heritage_protection", ("历史建筑", "文物", "保护", "古建筑", "修缮", "活化")),
    ("building_scale", ("建筑", "栋", "面积", "平方米", "㎡", "礼堂")),
    ("existing_problems", ("问题", "破损", "渗漏", "开裂", "老化", "消防", "排水", "无障碍", "停车", "电梯")),
    ("spatial_vision", ("一路", "一院", "一园", "空间", "院落", "动线", "入口", "轴线", "花园")),
    ("project_positioning", ("定位", "愿景", "目标", "功能", "业态", "运营", "更新")),
    ("surrounding_context", ("周边", "地铁", "医院", "博物馆", "公园", "商场", "交通", "公里", "米")),
)
_CATEGORY_ORDER = [rule[0] for rule in _CATEGORY_RULES] + ["other"]
_ROLE_PRIORITY = {
    DocumentRole.PROJECT_BRIEF: 3,
    DocumentRole.DESIGN_VISION: 2,
    DocumentRole.REFERENCE_DOCUMENT: 1,
}
_QUANTITY_RE = re.compile(r"(?P<approx>约|近|超过|不足|大约|约有)?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>万平方米|平方米|㎡|户|栋)")
_TOKEN_SPLIT_RE = re.compile(r"[\s,，。；;：:\-_/|()（）\[\]【】]+")
_GENERIC_PROJECT_QUESTIONS = ("分析这个项目", "这个项目", "适合做什么", "项目定位", "改造建议", "更新建议", "运营建议")


def build_project_evidence_dossier(
    selected_sources: List[Dict[str, Any]],
    *,
    question: str = "",
    max_evidence: int = 28,
) -> ProjectEvidenceDossier:
    document_ids = _selected_document_ids(selected_sources)
    selected_role_hints = _selected_document_roles(selected_sources)
    dossier = ProjectEvidenceDossier(question=str(question or "").strip(), document_ids=document_ids)
    if not document_ids:
        return dossier

    session = SessionLocal()
    try:
        documents = [session.get(Document, document_id) for document_id in document_ids]
        documents = [document for document in documents if document is not None]
        found_ids = {str(document.id) for document in documents}
        for missing_id in [document_id for document_id in document_ids if document_id not in found_ids]:
            hinted_role = selected_role_hints.get(missing_id)
            if hinted_role is not None:
                dossier.document_roles[missing_id] = hinted_role
            dossier.unreadable_document_ids.append(missing_id)
            label = "核心文档" if hinted_role in _CORE_ROLES else "文档"
            dossier.warnings.append(f"{label}未找到：{missing_id}")

        candidates: List[EvidenceItem] = []
        core_failures = 0
        for document in documents:
            try:
                role = DocumentRole(str(document.document_role or ""))
            except ValueError:
                dossier.warnings.append(f"文档角色无效：{document.title or document.id}")
                continue
            dossier.document_roles[str(document.id)] = role
            if str(document.status or "") != "parsed":
                dossier.warnings.append(f"文档尚未完成解析：{document.title or document.id}")
                dossier.unreadable_document_ids.append(str(document.id))
                if role in _CORE_ROLES:
                    core_failures += 1
                continue
            rows = (
                session.query(DocumentIndexNode)
                .filter_by(document_id=document.id)
                .order_by(DocumentIndexNode.ordinal.asc(), DocumentIndexNode.id.asc())
                .all()
            )
            rows = [row for row in rows if str(row.node_id or "") != "root" and str(row.text or row.summary or "").strip()]
            if not rows:
                dossier.warnings.append(f"文档没有可读取的 PageIndex 节点：{document.title or document.id}")
                dossier.unreadable_document_ids.append(str(document.id))
                if role in _CORE_ROLES:
                    core_failures += 1
                continue
            dossier.readable_document_ids.append(str(document.id))
            candidates.extend(_document_evidence_items(document, role, rows))
    except Exception as exc:
        dossier.status = "failed"
        dossier.warnings.append(f"项目证据档案构建失败：{exc}")
        return dossier
    finally:
        session.close()

    dossier.conflicts = _detect_conflicts(candidates)
    _mark_conflicting_items(candidates, dossier.conflicts)
    dossier.evidence = _select_evidence(candidates, question=dossier.question, limit=max_evidence)
    dossier.evidence = _ensure_conflict_evidence(
        dossier.evidence,
        candidates,
        dossier.conflicts,
        limit=max_evidence,
    )

    has_core = any(role in _CORE_ROLES for role in dossier.document_roles.values())
    if dossier.has_project_anchor and not dossier.has_readable_project_anchor:
        dossier.status = "failed"
        dossier.warnings.append("已选择项目摘要，但未能读取任何项目摘要证据；不得退化为参考资料或 GIS-only 的项目结论。")
    elif dossier.evidence:
        dossier.status = "partial" if dossier.warnings or core_failures else "ready"
    elif has_core:
        dossier.status = "failed"
        dossier.warnings.append("已选择项目摘要或设计愿景，但未能读取任何核心文档证据；不得退化为自信的 GIS-only 项目结论。")
    else:
        dossier.status = "partial" if dossier.warnings else "empty"
    return dossier


def dossier_evidence_payloads(
    dossier: ProjectEvidenceDossier | Dict[str, Any] | None,
    *,
    source_ids: Iterable[str] | None = None,
    question: str = "",
    limit: int = 12,
) -> List[Dict[str, Any]]:
    if dossier is None:
        return []
    model = dossier if isinstance(dossier, ProjectEvidenceDossier) else ProjectEvidenceDossier.model_validate(dossier)
    allowed = {str(source_id).strip() for source_id in list(source_ids or []) if str(source_id).strip()}
    items = [item for item in model.evidence if not allowed or item.source_id in allowed]
    selected = _rank_items(items, question=question, limit=limit)
    return [
        {
            "id": item.id,
            "source_id": item.source_id,
            "source_type": "document",
            "title": item.title,
            "content": item.content,
            "summary": item.summary or item.content[:320],
            "metadata": {
                "document_id": item.document_id,
                "document_role": item.document_role.value,
                "evidence_status": item.status.value,
                "category": item.category,
                "node_id": item.node_id,
                "page_start": item.page_start,
                "page_end": item.page_end,
            },
            "locator": item.locator,
            "score": 1.0,
            "evidence_level": "project_document_evidence",
            "warnings": [],
            "citation": item.citation,
        }
        for item in selected
    ]


def _selected_document_roles(items: Iterable[Dict[str, Any]]) -> Dict[str, DocumentRole]:
    roles: Dict[str, DocumentRole] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or item.get("id") or "").strip()
        if not source_id.startswith("document:"):
            continue
        document_id = source_id.split(":", 1)[1].strip()
        raw_role = str(item.get("document_role") or "").strip()
        if not document_id or not raw_role:
            continue
        try:
            roles[document_id] = DocumentRole(raw_role)
        except ValueError:
            continue
    return roles


def _selected_document_ids(items: Iterable[Dict[str, Any]]) -> List[str]:
    results: List[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or item.get("id") or "").strip()
        if not source_id.startswith("document:"):
            continue
        document_id = source_id.split(":", 1)[1].strip()
        if document_id and document_id not in results:
            results.append(document_id)
    return results


def _document_evidence_items(document: Document, role: DocumentRole, rows: Iterable[DocumentIndexNode]) -> List[EvidenceItem]:
    results: List[EvidenceItem] = []
    title = str(document.title or document.file_name or document.id).strip()
    source_id = f"document:{document.id}"
    for row in rows:
        content = str(row.text or row.summary or "").strip()[:2400]
        node_title = str(row.title or "PageIndex 节点").strip()
        page_start = max(1, int(row.page_start or 1))
        page_end = max(page_start, int(row.page_end or page_start))
        page_label = f"p.{page_start}" if page_start == page_end else f"p.{page_start}-{page_end}"
        segments = _evidence_segments(content, role=role)
        for segment_index, segment in enumerate(segments):
            combined = f"{node_title}\n{segment}"
            segment_suffix = "" if len(segments) == 1 else f":claim:{segment_index + 1}"
            results.append(
                EvidenceItem(
                    id=f"{source_id}:project-evidence:{row.node_id}{segment_suffix}",
                    source_id=source_id,
                    document_id=str(document.id),
                    document_title=title,
                    document_role=role,
                    status=_status_for(role, segment),
                    category=_category_for(combined),
                    title=node_title,
                    content=segment,
                    summary=segment[:420],
                    node_id=str(row.node_id),
                    page_start=page_start,
                    page_end=page_end,
                    locator=f"pageindex:{row.node_id}:{page_label}",
                    citation=f"{title} {page_label} / {node_title}",
                )
            )
    return results


def _evidence_segments(content: str, *, role: DocumentRole) -> List[str]:
    text = str(content or "").strip()
    if not text or role == DocumentRole.DESIGN_VISION:
        return [text] if text else []
    clauses = _split_top_level_clauses(text)
    statuses = [_status_for(role, clause) for clause in clauses]
    if len(clauses) <= 1 or len(set(statuses)) <= 1:
        return [text]

    results: List[str] = []
    for clause in clauses:
        quantity_parts = [part.strip() for part in re.split(r"[,，]", clause) if part.strip()]
        quantity_parts_with_values = [part for part in quantity_parts if _QUANTITY_RE.search(part)]
        quantity_statuses = {_status_for(role, part) for part in quantity_parts_with_values}
        if len(quantity_parts_with_values) > 1 and len(quantity_statuses) > 1:
            results.extend(quantity_parts)
        else:
            results.append(clause)
    return results


def _split_top_level_clauses(text: str) -> List[str]:
    opening = {"（": "）", "(": ")", "【": "】", "[": "]"}
    closing = set(opening.values())
    stack: List[str] = []
    clauses: List[str] = []
    start = 0
    for index, char in enumerate(text):
        if char in opening:
            stack.append(opening[char])
        elif char in closing and stack and stack[-1] == char:
            stack.pop()
        elif char in "，,；;。！？!?" and not stack:
            clause = text[start:index].strip()
            if clause:
                clauses.append(clause)
            start = index + 1
    tail = text[start:].strip()
    if tail:
        clauses.append(tail)
    return clauses or [text]


def _category_for(text: str) -> str:
    normalized = str(text or "")
    best_category = "other"
    best_score = 0
    for category, keywords in _CATEGORY_RULES:
        score = sum(2 if keyword in normalized else 0 for keyword in keywords)
        if score > best_score:
            best_category = category
            best_score = score
    return best_category


def _status_for(role: DocumentRole, text: str) -> EvidenceStatus:
    if role == DocumentRole.DESIGN_VISION:
        return EvidenceStatus.DESIGN_INTENT
    if any(marker in text for marker in _PENDING_MARKERS):
        return EvidenceStatus.PENDING_VERIFICATION
    return EvidenceStatus.CONFIRMED


def _select_evidence(items: List[EvidenceItem], *, question: str, limit: int) -> List[EvidenceItem]:
    core = [item for item in items if item.document_role in _CORE_ROLES]
    references = [item for item in items if item.document_role == DocumentRole.REFERENCE_DOCUMENT]
    selected: List[EvidenceItem] = []
    # Guarantee category coverage for project briefs and design visions before relevance ranking.
    for category in _CATEGORY_ORDER:
        category_items = [item for item in core if item.category == category]
        selected.extend(_rank_items(category_items, question=question, limit=2))
    selected = _dedupe_items(selected)
    for item in _rank_items(core, question=question, limit=max(0, limit - len(selected))):
        if item.id not in {current.id for current in selected}:
            selected.append(item)
    if len(selected) < limit:
        for item in _rank_items(references, question=question, limit=limit - len(selected)):
            if item.id not in {current.id for current in selected}:
                selected.append(item)
    return selected[:limit]


def _rank_items(items: List[EvidenceItem], *, question: str, limit: int) -> List[EvidenceItem]:
    if limit <= 0:
        return []
    generic = not str(question or "").strip() or any(token in str(question or "") for token in _GENERIC_PROJECT_QUESTIONS)
    tokens = _query_tokens(question)

    def score(item: EvidenceItem) -> tuple[float, int, int]:
        haystack = f"{item.title} {item.summary} {item.content}".lower()
        relevance = sum(1.0 for token in tokens if token and token in haystack)
        if generic and item.category != "other":
            relevance += 1.0
        relevance += _ROLE_PRIORITY[item.document_role] * 0.25
        return relevance, -item.page_start, -len(item.content)

    return sorted(items, key=score, reverse=True)[:limit]


def _query_tokens(question: str) -> List[str]:
    text = str(question or "").strip().lower()
    tokens = [token for token in _TOKEN_SPLIT_RE.split(text) if len(token) >= 2]
    chinese = "".join(char for char in text if "\u4e00" <= char <= "\u9fff")
    for size in (2, 3, 4):
        tokens.extend(chinese[index:index + size] for index in range(max(0, len(chinese) - size + 1)))
    return list(dict.fromkeys(token for token in tokens if token))[:80]


def _dedupe_items(items: List[EvidenceItem]) -> List[EvidenceItem]:
    seen: set[str] = set()
    results: List[EvidenceItem] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        results.append(item)
    return results


def _ensure_conflict_evidence(
    selected: List[EvidenceItem],
    candidates: List[EvidenceItem],
    conflicts: List[EvidenceConflict],
    *,
    limit: int,
) -> List[EvidenceItem]:
    required_ids = {evidence_id for conflict in conflicts for evidence_id in conflict.evidence_ids}
    if not required_ids:
        return selected[:limit]
    by_id = {item.id: item for item in candidates}
    required = [by_id[evidence_id] for evidence_id in required_ids if evidence_id in by_id]
    others = [item for item in selected if item.id not in required_ids]
    return _dedupe_items([*required, *others])[: max(limit, len(required))]


def _detect_conflicts(items: List[EvidenceItem]) -> List[EvidenceConflict]:
    claims: Dict[str, List[tuple[EvidenceItem, str, float]]] = defaultdict(list)
    for item in items:
        text = f"{item.title} {item.content}"
        for match in _QUANTITY_RE.finditer(text):
            metric_key, label = _quantity_metric(text, match.start(), match.group("unit"))
            if not metric_key:
                continue
            display = f"{match.group('approx') or ''}{match.group('value')}{match.group('unit')}"
            claims[metric_key].append((item, display, float(match.group("value"))))

    conflicts: List[EvidenceConflict] = []
    for metric_key, metric_claims in claims.items():
        distinct_values = {value for _, _, value in metric_claims}
        source_ids = {item.source_id for item, _, _ in metric_claims}
        if len(distinct_values) <= 1 or len(source_ids) <= 1:
            continue
        max_priority = max(_ROLE_PRIORITY[item.document_role] for item, _, _ in metric_claims)
        highest = [claim for claim in metric_claims if _ROLE_PRIORITY[claim[0].document_role] == max_priority]
        highest_values = {claim[2] for claim in highest}
        unresolved = len(highest_values) > 1
        preferred = highest[0] if len(highest_values) == 1 else None
        unique_display = list(dict.fromkeys(display for _, display, _ in metric_claims))
        evidence_ids = list(dict.fromkeys(item.id for item, _, _ in metric_claims))
        label = _metric_label(metric_key)
        explanation = (
            f"多个同级权威文档对{label}给出不同数值，当前不静默选边，需人工核实。"
            if unresolved
            else f"{label}存在跨文档差异；当前采用更高优先级的项目摘要口径，同时保留其他来源作为待核实冲突。"
        )
        conflicts.append(
            EvidenceConflict(
                metric_key=metric_key,
                label=label,
                values=unique_display,
                evidence_ids=evidence_ids,
                preferred_value=preferred[1] if preferred else "",
                preferred_evidence_id=preferred[0].id if preferred else "",
                unresolved=unresolved,
                explanation=explanation,
            )
        )
    return conflicts


def _quantity_metric(text: str, position: int, unit: str) -> tuple[str, str]:
    context = text[max(0, position - 28):position + 28]
    if unit == "户":
        return "households", "居民户数"
    if unit == "栋":
        if any(token in context for token in ("历史", "保护", "文物", "古建筑")):
            return "protected_buildings", "历史/保护建筑数量"
        if any(token in context for token in ("住宅", "居民楼", "宿舍")):
            return "residential_buildings", "住宅建筑数量"
        if any(token in context for token in ("地上建筑", "现有建筑", "总计", "共")):
            return "total_buildings", "建筑总数"
        return "", ""
    if unit in {"平方米", "㎡", "万平方米"}:
        if any(token in context for token in ("历史", "保护", "文物", "古建筑")):
            return "protected_building_area", "历史/保护建筑面积"
        if any(token in context for token in ("总建筑面积", "总面积", "建筑面积")):
            return "total_building_area", "项目建筑面积"
    return "", ""


def _metric_label(metric_key: str) -> str:
    return {
        "households": "居民户数",
        "protected_buildings": "历史/保护建筑数量",
        "residential_buildings": "住宅建筑数量",
        "total_buildings": "建筑总数",
        "protected_building_area": "历史/保护建筑面积",
        "total_building_area": "项目建筑面积",
    }.get(metric_key, metric_key)


def _mark_conflicting_items(items: List[EvidenceItem], conflicts: List[EvidenceConflict]) -> None:
    conflicting_ids = {evidence_id for conflict in conflicts for evidence_id in conflict.evidence_ids}
    for item in items:
        if item.id in conflicting_ids and item.status == EvidenceStatus.CONFIRMED:
            item.status = EvidenceStatus.CONFLICTING
