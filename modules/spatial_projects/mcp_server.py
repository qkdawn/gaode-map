"""MCP entry point for history-backed spatial projects.

Run with ``python -m modules.spatial_projects.mcp_server``.  The default
stdio transport is suitable for Codex; use ``--transport streamable-http``
when deploying the same server for a remote MCP client.
"""

import argparse
import base64
import inspect
import json
import os
import re
import sys
import types
from typing import Annotated, Any, Literal, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy.exc import SQLAlchemyError

from modules.documents.service import read_document_source
from modules.report_visuals.agent_tools import (
    get_report_vega_visual_asset as _get_report_vega_visual_asset,
    read_report_vega_rendered_report as _read_report_vega_rendered_report,
    read_report_vega_visual_asset as _read_report_vega_visual_asset,
    read_report_vega_visual_manifest as _read_report_vega_visual_manifest,
    read_report_vega_visual_plan as _read_report_vega_visual_plan,
    render_report_vega_visuals as _render_report_vega_visuals,
    report_visual_template_catalog as _report_visual_template_catalog,
)
from modules.spatial_projects.service import SpatialProjectService
from modules.spatial_projects.data_contract import ProjectDataContractService
from modules.spatial_action.spatial_evidence import (
    EvidenceDimension,
    FactDomain,
    SpatialEvidenceSelector,
    SpatialEvidenceService,
)
from modules.spatial_projects.public_web import (
    PublicWebUnavailable,
    fetch_public_web_page as _fetch_public_web_page,
    search_public_web as _search_public_web,
)
from modules.spatial_projects.skill_tools import (
    check_arcgis_report_status as _check_arcgis_report_status,
    create_spatial_report_visual as _create_spatial_report_visual,
    get_spatial_report_visual_asset as _get_spatial_report_visual_asset,
    read_spatial_report_visual_asset as _read_spatial_report_visual_asset,
    read_spatial_report_visual_manifest as _read_spatial_report_visual_manifest,
    execute_metric as _execute_metric,
    metric_catalog as _metric_catalog,
    metric_detail as _metric_detail,
    list_metric_results as _list_metric_results,
    read_metric_result as _read_metric_result,
)
from modules.spatial_strategy.literature_evidence import LiteratureEvidenceService
from modules.spatial_strategy.strategy_decisions import (
    read_strategy_decisions as _read_strategy_decisions,
)

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ResourceLink
except ImportError:  # pragma: no cover - exercised in dependency-light local environments
    FastMCP = None
    ResourceLink = None


class _StdioMcpFallback:
    """Small MCP stdio implementation used only when the official SDK is unavailable.

    It covers the MCP surface needed by local Codex: initialize, tools/list,
    tools/call, and ping. Streamable HTTP always requires the official SDK.
    """

    def __init__(self, name: str):
        self.name = name
        self._tools: dict[str, Any] = {}
        self._resources: list[tuple[str, Any, str]] = []

    def tool(self):
        def register(callback):
            self._tools[callback.__name__] = callback
            return callback

        return register

    def resource(self, uri: str, *, mime_type: str = "application/octet-stream", **_kwargs: Any):
        def register(callback):
            self._resources.append((uri, callback, mime_type))
            return callback
        return register

    @staticmethod
    def _schema(callback: Any) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required = []
        try:
            resolved_annotations = get_type_hints(callback)
        except (NameError, TypeError):
            resolved_annotations = {}
        for parameter in inspect.signature(callback).parameters.values():
            annotation = resolved_annotations.get(parameter.name, parameter.annotation)
            properties[parameter.name] = _StdioMcpFallback._annotation_schema(annotation)
            if parameter.default is inspect.Parameter.empty:
                required.append(parameter.name)
        return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}

    @staticmethod
    def _annotation_schema(annotation: Any) -> dict[str, Any]:
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is Annotated:
            return _StdioMcpFallback._inline_schema_refs(TypeAdapter(annotation).json_schema())
        if origin in {Union, types.UnionType}:
            non_null = [item for item in args if item is not type(None)]
            if len(non_null) == 1:
                return _StdioMcpFallback._annotation_schema(non_null[0])
            return {"anyOf": [_StdioMcpFallback._annotation_schema(item) for item in non_null]}
        if annotation is int:
            return {"type": "integer"}
        if annotation is float:
            return {"type": "number"}
        if annotation is bool:
            return {"type": "boolean"}
        if annotation is str:
            return {"type": "string"}
        if origin in {list, set, tuple}:
            item_schema = _StdioMcpFallback._annotation_schema(args[0]) if args else {}
            return {"type": "array", "items": item_schema}
        if origin in {dict} or annotation in {dict, Any}:
            return {"type": "object", "additionalProperties": True}
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return _StdioMcpFallback._inline_schema_refs(annotation.model_json_schema())
        return {"type": "string"}

    @staticmethod
    def _inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
        definitions = schema.get("$defs") if isinstance(schema.get("$defs"), dict) else {}

        def expand(value: Any) -> Any:
            if isinstance(value, dict):
                reference = value.get("$ref")
                if isinstance(reference, str) and reference.startswith("#/$defs/"):
                    target = definitions.get(reference.rsplit("/", 1)[-1])
                    if isinstance(target, dict):
                        overrides = {key: item for key, item in value.items() if key != "$ref"}
                        return expand({**target, **overrides})
                return {key: expand(item) for key, item in value.items() if key != "$defs"}
            if isinstance(value, list):
                return [expand(item) for item in value]
            return value

        expanded = expand(schema)
        return expanded if isinstance(expanded, dict) else {}

    def _tool_list(self) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": name,
                    "description": inspect.getdoc(callback) or "",
                    "inputSchema": self._schema(callback),
                }
                for name, callback in self._tools.items()
            ]
        }

    @staticmethod
    def _write(message: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(message, ensure_ascii=True, default=str) + "\n")
        sys.stdout.flush()

    def _handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        if method == "notifications/initialized" or request_id is None:
            return None
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": self.name, "version": "0.1.0"}}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": self._tool_list()}
        if method == "resources/read":
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            uri = str(params.get("uri") or "")
            for template, callback, mime_type in self._resources:
                pattern = re.sub(
                    r"\\\{([A-Za-z_][A-Za-z0-9_]*)\\\}",
                    r"(?P<\1>[^/]+)",
                    re.escape(template),
                )
                match = re.fullmatch(pattern, uri)
                if match:
                    payload = callback(**match.groupdict())
                    if isinstance(payload, bytes):
                        contents = {"uri": uri, "mimeType": mime_type, "blob": base64.b64encode(payload).decode("ascii")}
                    else:
                        contents = {"uri": uri, "mimeType": mime_type, "text": str(payload)}
                    return {"jsonrpc": "2.0", "id": request_id, "result": {"contents": [contents]}}
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "unknown_resource"}}
        if method == "tools/call":
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            name = str(params.get("name") or "")
            callback = self._tools.get(name)
            if callback is None:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "unknown_tool"}}
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            try:
                result = callback(**arguments)
                content = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]}
                return {"jsonrpc": "2.0", "id": request_id, "result": content}
            except Exception as exc:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method_not_found"}}

    def run(self, *, transport: str) -> None:
        if transport != "stdio":
            raise RuntimeError("Streamable HTTP requires the official 'mcp' package. Install project dependencies before using this transport.")
        for raw_line in sys.stdin:
            try:
                request = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(request, dict):
                continue
            response = self._handle(request)
            if response is not None:
                self._write(response)


service = SpatialProjectService()
mcp = (
    FastMCP(
        "Spatial Project",
        host=os.getenv("FASTMCP_HOST", "127.0.0.1"),
        port=int(os.getenv("FASTMCP_PORT", "8000")),
    )
    if FastMCP is not None
    else _StdioMcpFallback("spatial-project")
)
data_contract = ProjectDataContractService(projects=service, metric_results=_list_metric_results)
spatial_evidence = SpatialEvidenceService(projects=service)
literature_evidence = LiteratureEvidenceService()


def _analyze_spatial_question(*, history_id: str, question: str) -> dict[str, Any]:
    from modules.spatial_action.spatial_tool_agent import analyze_spatial_question

    return analyze_spatial_question(history_id=history_id, question=question)


def _call(callback, **kwargs: Any) -> Any:
    try:
        return callback(**kwargs)
    except LookupError as exc:
        return {"status": "not_found", "error": str(exc)}
    except ValueError as exc:
        code = str(getattr(exc, "code", "") or str(exc))
        response = {"status": "invalid_request", "error": code}
        if code != str(exc):
            response["message"] = str(exc)
        return response
    except SQLAlchemyError:
        return {
            "status": "unavailable",
            "error": "data_source_unavailable",
            "retryable": True,
            "limitations": ["项目数据源当前不可用，未执行或读取本次请求。"],
        }


class GeoJSONGeometryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"]
    coordinates: list[Any]


class SpatialRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    record_id: str
    year: int | None = None


class SpatialQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation: Literal["nearest", "within_distance", "intersects", "at_point"]
    point: list[float] | None = Field(default=None, min_length=2, max_length=2)
    geometry: GeoJSONGeometryInput | None = None
    coord_type: Literal["wgs84", "gcj02"]
    max_distance_m: float | None = Field(default=None, ge=0)
    min_overlap_ratio: float | None = Field(default=None, ge=0, le=1)
    record: SpatialRecordInput | None = None
    exclude_target: bool = True

    @model_validator(mode="after")
    def validate_target(self):
        targets = [self.point is not None, self.geometry is not None, self.record is not None]
        if sum(targets) != 1:
            raise ValueError("spatial 必须且只能提供 point、geometry 或 record 之一")
        if self.relation == "within_distance" and self.max_distance_m is None:
            raise ValueError("within_distance 必须提供 max_distance_m")
        if self.relation == "at_point" and self.point is None and self.record is None:
            raise ValueError("at_point 只能使用 point 或 record")
        return self


class SortInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    direction: Literal["asc", "desc"] = "asc"


class AggregateMetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["count", "sum", "avg", "min", "max", "area_weighted_sum", "area_weighted_avg", "intersection_length_sum"] = "count"
    field: str = "*"
    as_: str | None = Field(default=None, alias="as")

    def to_payload(self) -> dict[str, Any]:
        payload = self.model_dump(by_alias=True, exclude_none=True)
        return payload


@mcp.tool()
def compute_spatial_evidence(
    history_id: str,
    analysis: Literal["scope", "accessibility", "direction", "neighborhood", "rank", "relationship", "inspect"],
    fact_domains: Annotated[list[FactDomain] | None, Field(max_length=4)] = None,
    evidence_dimensions: Annotated[list[EvidenceDimension] | None, Field(max_length=8)] = None,
    selectors: Annotated[list[SpatialEvidenceSelector] | None, Field(max_length=8)] = None,
    travel_time_bands_min: Annotated[list[tuple[float, float]] | None, Field(max_length=6)] = None,
    neighbor_steps: Annotated[int, Field(ge=1, le=3)] = 1,
    rank_order: Literal["highest", "lowest"] = "highest",
    top_k: Annotated[int, Field(ge=1, le=20)] = 10,
    record_refs: Annotated[list[str] | None, Field(max_length=20)] = None,
) -> dict[str, Any]:
    """Deterministically compute one spatial operation over selected fact domains.

    This low-level tool does not interpret a user question or produce a conclusion.
    POI, population, nightlight, and road are fact domains. Scope, accessibility,
    direction, neighborhood, rank, relationship, and inspect are operations.
    Semantic dimensions choose meaning while each domain owns concrete indicators.
    Rank and relationship require one dimension per fact domain. For persisted
    continuous road corridors, use road.object=corridor with rank and a movement
    dimension.
    """
    return _call(
        spatial_evidence.compute_domains,
        history_id=history_id,
        request={
            "analysis": analysis,
            "fact_domains": list(fact_domains or []),
            "evidence_dimensions": list(evidence_dimensions or []),
            "selectors": [
                item.model_dump(mode="json") if isinstance(item, BaseModel) else dict(item)
                for item in selectors or []
            ],
            "travel_time_bands_min": travel_time_bands_min,
            "neighbor_steps": neighbor_steps,
            "rank_order": rank_order,
            "top_k": top_k,
            "record_refs": list(record_refs or []),
        },
    )


@mcp.tool()
def analyze_spatial_question(
    history_id: str,
    question: Annotated[str, Field(min_length=1, max_length=1000)],
) -> dict[str, Any]:
    """Ask the reusable spatial tool agent to decompose and answer a spatial question.

    The agent chooses fact domains, semantic dimensions, and spatial operations;
    it may call the deterministic tool multiple times and synthesize the facts.
    Callers do not select metrics or analysis modes.
    """
    return _call(_analyze_spatial_question, history_id=history_id, question=question)


@mcp.tool()
def read_strategy_decisions(run_id: str) -> dict[str, Any]:
    """Read the completed domain decisions for one spatial-strategy run."""
    return _read_strategy_decisions(run_id)


@mcp.tool()
def read_project_document(
    history_id: str,
    document_id: str,
    start_block: int = 0,
    max_blocks: int = 20,
    page_start: int | None = None,
    page_end: int | None = None,
) -> dict[str, Any]:
    """Read project-specific site, policy, history, ownership, or design facts from a parsed document.

    Read only the blocks or pages needed for the current decision and continue
    from next_start_block when the returned window is incomplete.
    """
    return _call(
        data_contract.read_project_document,
        history_id=history_id,
        document_id=document_id,
        start_block=start_block,
        max_blocks=max_blocks,
        page_start=page_start,
        page_end=page_end,
    )


def list_history_projects(limit: int = 100) -> list[dict[str, Any]]:
    """List history-backed spatial projects by identity only; read one for documents and datasets."""
    return _call(service.list_history_projects, limit=limit)


def read_history_project(history_id: str) -> dict[str, Any]:
    """Read one history-backed spatial project, its documents, datasets, scope, and version status."""
    return _call(service.read_history_project, history_id=history_id)


def _require_history_project(history_id: str) -> dict[str, Any] | None:
    project = _call(service.read_history_project, history_id=history_id)
    if isinstance(project, dict) and project.get("status") in {"not_found", "invalid_request", "unavailable"}:
        return project
    return None


@mcp.tool()
def search_literature_evidence(
    history_id: str,
    question: str,
    mode: Literal["focused", "synthesis"] = "focused",
    top_k: int = 6,
) -> dict[str, Any]:
    """Search the indexed PDF literature corpus.

    Use this for transferable methods, precedents, and mechanisms rather than
    project spatial facts. Use focused for fast original-text evidence and
    synthesis only for cross-document comparison or mechanism synthesis. Do
    not include private project details in the question.
    """
    blocked = _require_history_project(history_id)
    if blocked:
        return blocked
    return literature_evidence.search(
        question=question,
        mode=mode,
        top_k=top_k,
    )


@mcp.tool()
async def search_public_web(
    history_id: str,
    query: str,
    provider: Literal["anysearch", "exa"] = "anysearch",
    limit: int = 5,
) -> dict[str, Any]:
    """Discover public-web sources for one saved project through AnySearch or Exa.

    Use this only when a named place's public attribute can change the current
    decision, such as an official plan, function, opening status, operator, or
    public activity. Build a focused query from location, exact object name,
    and the attribute to confirm. Results are research leads only; call
    fetch_public_web_page on selected sources before using them.
    """
    blocked = _require_history_project(history_id)
    if blocked:
        return blocked
    normalized_query = query.strip()
    if not normalized_query:
        return {"status": "invalid_request", "error": "query_required"}
    try:
        result = await _search_public_web(normalized_query, provider, max(1, min(limit, 10)))
    except PublicWebUnavailable as exc:
        return {"status": "unavailable", "error": str(exc), "retryable": True}
    result["history_id"] = history_id
    return result


@mcp.tool()
async def fetch_public_web_page(
    history_id: str,
    urls: list[str],
    provider: Literal["anysearch", "exa"] = "anysearch",
    max_characters: int = 5000,
) -> dict[str, Any]:
    """Read selected public-web pages for one saved project through AnySearch or Exa.

    Prefer official or first-party pages whose date and geographic scope match
    the decision. Use the page only for the public attribute it supports; it
    does not replace project documents or saved spatial records.
    """
    blocked = _require_history_project(history_id)
    if blocked:
        return blocked
    normalized_urls = [url.strip() for url in urls if url.strip().startswith(("https://", "http://"))][:5]
    if not normalized_urls:
        return {"status": "invalid_request", "error": "urls_required"}
    try:
        result = await _fetch_public_web_page(normalized_urls, provider, max(500, min(max_characters, 20000)))
    except PublicWebUnavailable as exc:
        return {"status": "unavailable", "error": str(exc), "retryable": True}
    result["history_id"] = history_id
    return result


def list_history_project_documents(history_id: str) -> dict[str, Any]:
    """List project documents linked to one analysis history, including their roles and parse status."""
    result = _call(service.list_history_project_documents, history_id=history_id)
    if isinstance(result, dict) and result.get("status") in {"not_found", "invalid_request", "unavailable"}:
        return result
    return {"documents": result}


def get_history_project_document_resource(history_id: str, document_id: str) -> Any:
    """Return a link to the original DOCX or PDF so the client can read it on demand."""
    metadata = _call(
        service.get_history_project_document_resource,
        history_id=history_id,
        document_id=document_id,
    )
    if not isinstance(metadata, dict) or metadata.get("status") in {"not_found", "invalid_request", "unavailable"}:
        return metadata
    resource = {
        "type": "resource_link",
        "uri": f"spatial-document://{history_id}/{document_id}/original",
        "name": metadata["file_name"],
        "title": metadata["title"],
        "description": "项目上传的原始文档。读取该资源可获得未经摘要的 DOCX 或 PDF。",
        "mimeType": metadata["mime_type"],
        "size": metadata["size"],
    }
    return ResourceLink.model_validate(resource) if ResourceLink is not None else resource


@mcp.resource(
    "spatial-document://{history_id}/{document_id}/original",
    name="history-project-original-document",
    description="Original DOCX or PDF uploaded for one history project.",
    mime_type="application/octet-stream",
)
def read_history_project_document_resource(history_id: str, document_id: str) -> bytes:
    """Read a project document through its opaque MCP URI without exposing a local path."""
    _, content = read_document_source(document_id, history_id=history_id)
    return content


def list_history_project_datasets(history_id: str) -> dict[str, Any]:
    """List datasets available for one analysis history, including years, counts, and warnings."""
    return _call(service.list_history_project_datasets, history_id=history_id)


def query_history_project_dataset(
    history_id: str,
    source_id: str,
    filters: dict[str, Any] | None = None,
    sort: SortInput | None = None,
    spatial: SpatialQueryInput | None = None,
    limit: int = 20,
    offset: int = 0,
    year: int | None = None,
) -> dict[str, Any]:
    """Read dataset records, optionally around a coordinate or inside a geometry.

    ``spatial`` accepts ``relation`` (nearest, within_distance, intersects, or
    at_point), exactly one of ``point: [lng, lat]`` or GeoJSON ``geometry``,
    ``coord_type`` (wgs84 or gcj02), and ``max_distance_m`` when required.
    """
    return _call(
        service.query_history_project_dataset,
        history_id=history_id,
        source_id=source_id,
        filters=filters,
        sort=sort.model_dump(exclude_none=True) if sort else None,
        spatial=spatial.model_dump(exclude_none=True) if spatial else None,
        limit=limit,
        offset=offset,
        year=year,
    )


def create_history_project_dataset_query_snapshot(
    history_id: str,
    source_id: str,
    filters: dict[str, Any] | None = None,
    spatial: SpatialQueryInput | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """Create an immutable geometry snapshot for a complete spatial dataset query.

    The response contains provenance and counts only. Geometry remains private
    and can be referenced later through ``input_snapshot_ids`` when rendering.
    """
    return _call(
        service.create_history_project_dataset_query_snapshot,
        history_id=history_id,
        source_id=source_id,
        filters=filters,
        spatial=spatial.model_dump(exclude_none=True) if spatial else None,
        year=year,
    )


def aggregate_history_project_dataset(
    history_id: str,
    source_id: str,
    group_by: str = "",
    metrics: list[AggregateMetricInput] | None = None,
    filters: dict[str, Any] | None = None,
    spatial: SpatialQueryInput | None = None,
    top_k: int = 20,
    year: int | None = None,
) -> dict[str, Any]:
    """Aggregate dataset records around a coordinate or inside a geometry.

    ``spatial`` uses the same relation, point/geometry, coordinate type, and
    distance contract as ``query_history_project_dataset``.
    """
    return _call(
        service.aggregate_history_project_dataset,
        history_id=history_id,
        source_id=source_id,
        group_by=group_by,
        metrics=[item.to_payload() for item in metrics] if metrics else None,
        filters=filters,
        spatial=spatial.model_dump(exclude_none=True) if spatial else None,
        top_k=top_k,
        year=year,
    )


def read_history_project_dataset_record(history_id: str, source_id: str, record_id: str, year: int | None = None) -> dict[str, Any]:
    """Read one spatial dataset record from a history-backed project."""
    return _call(service.read_history_project_dataset_record, history_id=history_id, source_id=source_id, record_id=record_id, year=year)


def list_spatial_metric_results(history_id: str, run_id: str | None = None, tool_id: str | None = None) -> dict[str, Any]:
    """List persisted metric results from completed spatial-business analysis runs."""
    return _call(_list_metric_results, history_id=history_id, run_id=run_id, tool_id=tool_id)


def read_spatial_metric_result(history_id: str, result_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Read one persisted metric result without executing the metric again."""
    return _call(_read_metric_result, history_id=history_id, result_id=result_id, run_id=run_id)


def spatial_metric_catalog() -> dict[str, Any]:
    """Discover the business-semantic spatial metrics that both main and specialist Agents may use."""
    return _metric_catalog()


def spatial_metric_detail(tool_id: str) -> dict[str, Any]:
    """Read one metric knowledge card before deciding whether to execute it."""
    return _call(_metric_detail, tool_id=tool_id)


def execute_spatial_metric(
    history_id: str,
    tool_id: str,
    parameters: dict[str, Any] | None = None,
    comparison_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an authorized metric for one saved project without exposing raw geometry or GIS infrastructure."""
    return _call(
        _execute_metric,
        history_id=history_id,
        tool_id=tool_id,
        parameters=parameters,
        comparison_context=comparison_context,
    )


def check_arcgis_report_status() -> dict[str, Any]:
    """Check ArcGIS Bridge connectivity, credentials, and approved report templates."""
    return _call(_check_arcgis_report_status)


def create_spatial_report_visual(history_id: str, visual_request: dict[str, Any]) -> dict[str, Any]:
    """Render an approved real-data thematic SVG map from prior authorized metric results."""
    return _call(
        _create_spatial_report_visual,
        history_id=history_id,
        visual_request=visual_request,
    )


def get_spatial_report_visual_asset(history_id: str, asset_id: str) -> Any:
    """Return a resource link for one generated ArcGIS report visual."""
    metadata = _call(
        _get_spatial_report_visual_asset,
        history_id=history_id,
        asset_id=asset_id,
    )
    if not isinstance(metadata, dict) or metadata.get("status") != "available":
        return metadata
    result = metadata["result"]
    resource = {
        "type": "resource_link",
        "uri": result["resource_uri"],
        "name": result["filename"],
        "title": "ArcGIS 报告视觉",
        "description": "已通过安全校验的 ArcGIS SVG 报告视觉。",
        "mimeType": "image/svg+xml",
    }
    return ResourceLink.model_validate(resource) if ResourceLink is not None else resource


def read_spatial_report_visual_manifest(history_id: str, asset_id: str) -> dict[str, Any]:
    """Re-audit a generated ArcGIS map through its persisted quality manifest."""
    return _call(
        _read_spatial_report_visual_manifest,
        history_id=history_id,
        asset_id=asset_id,
    )


@mcp.resource(
    "spatial-report-visual://{history_id}/{asset_id}",
    name="spatial-report-visual-asset",
    description="Validated ArcGIS SVG report visual generated for one history project.",
    mime_type="image/svg+xml",
)
def read_spatial_report_visual_resource(history_id: str, asset_id: str) -> str:
    """Read one persisted ArcGIS report visual without exposing local paths."""
    return _read_spatial_report_visual_asset(history_id, asset_id)


def report_visual_template_catalog() -> dict[str, Any]:
    """Discover the only approved constrained Vega report-visual templates for the visual-evidence editor."""
    return _report_visual_template_catalog()


def render_report_vega_visuals(
    history_id: str,
    report_id: str,
    report_markdown: str,
    visual_plan: dict[str, Any],
) -> dict[str, Any]:
    """Render a reviewed Vega report-visual plan from same-session metric results only."""
    return _call(
        _render_report_vega_visuals,
        history_id=history_id,
        report_id=report_id,
        report_markdown=report_markdown,
        visual_plan=visual_plan,
    )


def get_report_vega_visual_asset(history_id: str, report_id: str, asset_id: str) -> Any:
    """Return a resource link for one generated constrained Vega SVG report visual."""
    metadata = _call(
        _get_report_vega_visual_asset,
        history_id=history_id,
        report_id=report_id,
        asset_id=asset_id,
    )
    if not isinstance(metadata, dict) or metadata.get("status") != "available":
        return metadata
    result = metadata["result"]
    resource = {
        "type": "resource_link",
        "uri": result["resource_uri"],
        "name": result["filename"],
        "title": "Vega 报告视觉",
        "description": "已通过安全校验、由批准模板生成的 SVG 报告视觉。",
        "mimeType": "image/svg+xml",
    }
    return ResourceLink.model_validate(resource) if ResourceLink is not None else resource


def read_report_vega_visual_manifest(history_id: str, report_id: str) -> dict[str, Any]:
    """Read the traceability manifest for a constrained Vega report-visual bundle."""
    return _call(
        _read_report_vega_visual_manifest,
        history_id=history_id,
        report_id=report_id,
    )


@mcp.resource(
    "report-vega-visual://{history_id}/{report_id}/{asset_id}",
    name="report-vega-visual-asset",
    description="Validated SVG generated from an approved constrained Vega report visual template.",
    mime_type="image/svg+xml",
)
def read_report_vega_visual_resource(history_id: str, report_id: str, asset_id: str) -> str:
    """Read one persisted constrained Vega SVG without exposing local paths."""
    return _read_report_vega_visual_asset(history_id, report_id, asset_id)


@mcp.resource(
    "report-vega-report://{history_id}/{report_id}",
    name="report-vega-rendered-report",
    description="Markdown report after constrained Vega visual blocks are assembled.",
    mime_type="text/markdown",
)
def read_report_vega_report_resource(history_id: str, report_id: str) -> str:
    """Read the assembled Markdown report for one constrained Vega bundle."""
    return _read_report_vega_rendered_report(history_id, report_id)


@mcp.resource(
    "report-vega-visual-plan://{history_id}/{report_id}",
    name="report-vega-visual-plan",
    description="Auditable template-selection plan submitted by the visual-evidence editor.",
    mime_type="application/json",
)
def read_report_vega_visual_plan_resource(history_id: str, report_id: str) -> str:
    """Read the persisted visual plan without exposing any filesystem path."""
    return _read_report_vega_visual_plan(history_id, report_id)


@mcp.resource(
    "report-vega-visual-manifest://{history_id}/{report_id}",
    name="report-vega-visual-manifest",
    description="Traceability manifest for constrained Vega report visual assets.",
    mime_type="application/json",
)
def read_report_vega_visual_manifest_resource(history_id: str, report_id: str) -> str:
    """Read the persisted traceability manifest without exposing any filesystem path."""
    return json.dumps(
        _read_report_vega_visual_manifest(history_id, report_id)["result"]["visual_manifest"],
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
