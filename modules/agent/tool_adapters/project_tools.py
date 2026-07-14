from __future__ import annotations

from typing import Any, Dict, List

from ..schemas import AnalysisSnapshot, ToolResult
from ..selected_sources import (
    document_role_from_item,
    source_id_from_item,
    source_title_from_item,
)


def _selected_sources(artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
    context = artifacts.get("selected_sources_context") if isinstance(artifacts, dict) else {}
    if not isinstance(context, dict):
        return []
    return [item for item in list(context.get("sources") or []) if isinstance(item, dict)]


def _project_documents(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    documents = []
    for source in sources:
        source_id = source_id_from_item(source)
        if not source_id.startswith("document:"):
            continue
        documents.append(
            {
                "source_id": source_id,
                "title": source_title_from_item(source),
                "document_role": document_role_from_item(source),
                "evidence_count": len(list(source.get("evidence_nodes") or [])),
                "status": str(source.get("status") or "ready"),
            }
        )
    return documents


async def read_project_context(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    del arguments, question
    sources = _selected_sources(artifacts)
    documents = _project_documents(sources)
    dossier = artifacts.get("project_evidence_dossier") if isinstance(artifacts, dict) else {}
    dossier = dossier if isinstance(dossier, dict) else {}
    history_id = str((snapshot.context or {}).get("history_id") or "").strip()
    project_evidence = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "content": item.get("content"),
            "status": item.get("status"),
            "category": item.get("category"),
            "citation": item.get("citation"),
            "locator": item.get("locator"),
        }
        for item in list(dossier.get("evidence") or [])[:28]
        if isinstance(item, dict)
    ]
    warnings = list(dossier.get("warnings") or [])
    if not documents:
        warnings.append("当前没有选中的项目文档；GIS 分析数据不能替代项目任务书、现状资料或设计约束。")
    if not history_id:
        warnings.append("当前没有绑定历史记录；无法确认空间分析数据对应的范围和版本。")

    status = str(dossier.get("status") or "empty")
    if documents and history_id and status in {"ready", "partial"}:
        result_status = "success"
    else:
        result_status = "failed"
    result = {
        "history_id": history_id,
        "documents": documents,
        "document_evidence_status": status,
        "project_evidence": project_evidence,
        "evidence_conflicts": list(dossier.get("conflicts") or []),
        "scope": snapshot.scope if isinstance(snapshot.scope, dict) else {},
        "analysis_results": {
            "poi_summary": snapshot.poi_summary if isinstance(snapshot.poi_summary, dict) else {},
            "h3_summary": (snapshot.h3 or {}).get("summary", {}) if isinstance(snapshot.h3, dict) else {},
            "population_summary": (snapshot.population or {}).get("summary", {}) if isinstance(snapshot.population, dict) else {},
            "nightlight_summary": (snapshot.nightlight or {}).get("summary", {}) if isinstance(snapshot.nightlight, dict) else {},
            "road_summary": (snapshot.road or {}).get("summary", {}) if isinstance(snapshot.road, dict) else {},
        },
        "warnings": sorted(set(str(item).strip() for item in warnings if str(item).strip())),
    }
    evidence = [
        {"field": "project.history_id", "value": history_id},
        {"field": "project.document_count", "value": len(documents)},
        {"field": "project.evidence_count", "value": len(project_evidence)},
        {"field": "project.document_evidence_status", "value": status},
    ]
    return ToolResult(
        tool_name="read_project_context",
        status="success" if result_status == "success" else "failed",
        result=result,
        evidence=evidence,
        warnings=result["warnings"],
        artifacts={"project_context": result},
        error=None if result_status == "success" else "project_context_incomplete",
    )
