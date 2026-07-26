from __future__ import annotations

from typing import Any, Dict

from modules.ppt_planning.schemas import PptWebSourceSearchRequest
from modules.ppt_web_source.service import preview_ppt_web_source

from ..schemas import AnalysisSnapshot, ToolResult


def _history_id(arguments: Dict[str, Any], snapshot: AnalysisSnapshot) -> str:
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    return str(arguments.get("area_id") or arguments.get("history_id") or context.get("history_id") or "").strip()


async def search_public_web(*, arguments: Dict[str, Any], snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], question: str) -> ToolResult:
    del artifacts, question
    area_id = _history_id(arguments, snapshot)
    if not area_id:
        return ToolResult(tool_name="search_public_web", status="failed", error="history_id_required", warnings=["公开网页检索需要 history_id 作为项目区域标识"])
    context = snapshot.context if isinstance(snapshot.context, dict) else {}
    request = PptWebSourceSearchRequest(
        area_id=area_id,
        region_name=str(arguments.get("region_name") or context.get("project_name") or context.get("region_name") or "当前项目区域"),
        administrative_area=str(arguments.get("administrative_area") or context.get("administrative_area") or ""),
        topic=str(arguments.get("topic") or "文旅主题资源"),
        intent=str(arguments.get("intent") or "文旅八类资源、历史文化、非遗、产业与目的地活化"),
        categories=list(arguments.get("categories") or ["区域概况", "文旅案例", "产业商业", "政策背景"]),
        source_modes=list(arguments.get("source_modes") or ["trusted", "market"]),
        urls=list(arguments.get("urls") or []),
        limit=int(arguments.get("limit") or 8),
    )
    try:
        response = await preview_ppt_web_source(request)
    except Exception as exc:
        return ToolResult(tool_name="search_public_web", status="failed", error=str(exc), warnings=["公开网页检索不可用，本轮必须保留网页证据缺口"])
    items = list(response.items or [])
    return ToolResult(
        tool_name="search_public_web",
        status="success" if items else "failed",
        result={"summary": response.summary, "items": items, "evidence_refs": list(response.evidence_refs or [])},
        evidence=[{"field": "public_web.item_count", "value": len(items)}],
        warnings=list(response.warnings or []),
        artifacts={"cultural_tourism_web_sources": items} if items else {},
        error=None if items else "web_evidence_empty",
    )
