"""Deterministic, Skill-first semantic tools for history-backed spatial projects.

This module is deliberately a narrow domain facade.  It prepares the internal
history/project/source context required by the existing metric engine, then
returns only reader-facing metric semantics.  It does not author reports,
coordinate agents, or expose GIS/runtime infrastructure.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from modules.spatial_action.metric_tools import (
    MetricCatalogItem,
    MetricDetail,
    MetricResult,
    MetricToolService,
)
from modules.spatial_action.source_index import (
    SourceIndex,
    SourceIndexItem,
    build_source_index,
)
from modules.spatial_action.visual_contracts import VisualPlanItem
from store.analysis_run_repo import analysis_run_repo
from modules.spatial_action.arcgis_spatial_tools import ArcGISSpatialToolModule
from modules.spatial_projects.service import SpatialProjectService
from modules.spatial_projects.visual_asset_store import SpatialReportVisualAssetStore

_STATUS = Literal["available", "unavailable", "failed"]
_PRIVATE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bridge",
        "bridge_url",
        "connection",
        "connection_string",
        "database",
        "db",
        "engine",
        "file_path",
        "host",
        "password",
        "path",
        "renderer",
        "secret",
        "token",
        "url",
    }
)
_GEOMETRY_KEYS = frozenset({"coordinates", "features", "geometry", "polygon", "polygon_wgs84"})


class SkillMetricEnvelope(BaseModel):
    """Fixed public shape shared by catalog, detail, and execution calls."""

    model_config = ConfigDict(extra="forbid")

    status: _STATUS
    result: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    spatial_scope: dict[str, Any] = Field(default_factory=dict)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    method: dict[str, Any] = Field(default_factory=dict)
    comparison_basis: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class _ExecutionContext:
    history_id: str
    history_detail: dict[str, Any]
    project_documents: dict[str, Any]
    source_versions: list[dict[str, Any]]
    source_index: SourceIndex
    warnings: list[str]
    time_scope: dict[str, Any]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field}_must_be_object")
    return deepcopy(dict(value))


def _unique_text(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(_text(value) for value in values if _text(value)))


def _safe_semantic_value(value: Any, *, drop_geometry: bool = True) -> Any:
    """Copy semantic facts while removing infrastructure and raw geometry payloads."""

    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for raw_key in sorted(value, key=lambda item: str(item)):
            key = str(raw_key)
            normalized = key.lower()
            if normalized in _PRIVATE_KEYS or (drop_geometry and normalized in _GEOMETRY_KEYS):
                continue
            cleaned[key] = _safe_semantic_value(value[raw_key], drop_geometry=drop_geometry)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_safe_semantic_value(item, drop_geometry=drop_geometry) for item in value]
    return deepcopy(value)


def _analysis_polygon_geometry(scope: Any) -> dict[str, Any] | None:
    """Normalize the persisted analysis scope into Polygon or MultiPolygon GeoJSON.

    The metric domain needs the full declared geometry to derive its centroid.
    Older callers still receive a representative ring through ``_polygon_ring``;
    that compatibility shape stays at this facade instead of leaking into metric
    implementations.
    """

    value = scope
    if isinstance(value, Mapping):
        value = value.get("polygon") or value.get("geometry") or value
    if isinstance(value, Mapping) and value.get("type") in {"Polygon", "MultiPolygon"}:
        coordinates = value.get("coordinates")
        if isinstance(coordinates, list) and coordinates:
            return {"type": str(value["type"]), "coordinates": deepcopy(coordinates)}
    if not isinstance(value, list) or not value:
        return None
    if all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in value):
        return {"type": "Polygon", "coordinates": [deepcopy(value)]}
    if (
        isinstance(value[0], list)
        and value[0]
        and all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in value[0])
    ):
        return {"type": "Polygon", "coordinates": deepcopy(value)}
    return None


def _polygon_ring(scope: Any) -> list[list[float]]:
    """Return one outer ring for legacy metrics while retaining full geometry elsewhere."""

    geometry = _analysis_polygon_geometry(scope)
    if not geometry:
        return []
    coordinates = geometry.get("coordinates")
    if geometry["type"] == "Polygon":
        ring = coordinates[0] if isinstance(coordinates, list) and coordinates else []
    else:
        ring = coordinates[0][0] if isinstance(coordinates, list) and coordinates and coordinates[0] else []
    normalized: list[list[float]] = []
    for point in ring if isinstance(ring, list) else []:
        try:
            normalized.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError, IndexError):
            return []
    return normalized if len(normalized) >= 4 else []


def _dataset_versions(datasets: list[Any], *, history_id: str) -> list[dict[str, Any]]:
    versions: list[dict[str, Any]] = []
    for dataset in datasets:
        if not isinstance(dataset, Mapping):
            continue
        source_id = _text(dataset.get("source_id"))
        if not source_id:
            continue
        selected_year = dataset.get("selected_year")
        source_id_lower = source_id.lower()
        versions.append(
            {
                "source_id": source_id,
                "year": selected_year if isinstance(selected_year, int) else None,
                "version": f"history:{history_id}:{source_id}:{selected_year or 'undated'}:{int(dataset.get('record_count') or 0)}",
                "record_count": int(dataset.get("record_count") or 0),
                "data_kind": "raster" if any(name in source_id_lower for name in ("population", "nightlight")) else "record",
                "health_hint": _text(dataset.get("status")),
            }
        )
    return sorted(versions, key=lambda item: item["source_id"])


class SpatialBusinessSkillTools:
    """Deep facade that hides history-context assembly behind three metric tools."""

    def __init__(
        self,
        *,
        project_service: SpatialProjectService | None = None,
        metric_service: MetricToolService | None = None,
        visual_tools: ArcGISSpatialToolModule | None = None,
        visual_asset_store: SpatialReportVisualAssetStore | None = None,
        run_repo: Any = None,
    ) -> None:
        self._projects = project_service or SpatialProjectService()
        self._metrics = metric_service or MetricToolService()
        self._visuals = visual_tools or ArcGISSpatialToolModule()
        self._visual_assets = visual_asset_store or SpatialReportVisualAssetStore()
        self._runs = run_repo or analysis_run_repo
        # A live MCP session may execute several complementary metrics before it
        # asks ArcGIS for a map.  Retain only the immutable project's bounded
        # execution context and generated result/asset metadata; this is not a
        # report run and does not coordinate or author Agents.
        self._contexts: dict[str, _ExecutionContext] = {}

    def metric_catalog(self) -> dict[str, Any]:
        """Return lightweight discovery data without loading private execution context."""

        metrics = [self._catalog_item(item) for item in self._metrics.catalog()]
        return self._envelope(
            status="available",
            result={"metrics": metrics},
            method={"kind": "metric_catalog", "selection_rule": "Read metric_detail before execution."},
        )

    def metric_detail(self, tool_id: str) -> dict[str, Any]:
        """Return one metric's analyst knowledge card in the common semantic envelope."""

        normalized_tool_id = self._required_identifier(tool_id, "tool_id")
        catalog_item = next((item for item in self._metrics.catalog() if item.tool_id == normalized_tool_id), None)
        if catalog_item is None:
            return self._envelope(
                status="unavailable",
                limitations=["指定的指标工具未注册。"],
                method={"tool_id": normalized_tool_id},
            )
        detail = self._metrics.detail(normalized_tool_id)
        return self._detail_envelope(detail, catalog_item)

    def list_metric_results(
        self,
        history_id: str,
        run_id: str | None = None,
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        """Read persisted analysis results from immutable run source indexes."""
        normalized_history_id = self._required_identifier(history_id, "history_id")
        normalized_run_id = _text(run_id)
        normalized_tool_id = _text(tool_id)
        manifests = self._runs.list(normalized_history_id, capability_id="spatial-business-analyst")
        results: list[dict[str, Any]] = []
        for manifest in manifests:
            current_run_id = _text(manifest.get("run_id"))
            if normalized_run_id and current_run_id != normalized_run_id:
                continue
            detail = self._runs.get(current_run_id)
            results.extend(self._persisted_results(detail, current_run_id, normalized_tool_id))
        return self._envelope(
            status="available",
            result={"history_id": normalized_history_id, "results": results, "result_count": len(results)},
            method={"kind": "persisted_metric_results", "execution": "read_only"},
        )

    def arcgis_report_status(self) -> dict[str, Any]:
        """Check live ArcGIS Bridge authentication and report-template readiness."""

        status = self._visuals.report_status()
        return self._envelope(
            status="available" if status["ready"] else "unavailable",
            result=status,
            limitations=list(status["limitations"]),
            method={"kind": "arcgis_report_status", "live_check": True},
        )

    def read_metric_result(
        self,
        history_id: str,
        result_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Read one persisted metric result by its source-index resource id."""
        normalized_history_id = self._required_identifier(history_id, "history_id")
        normalized_result_id = self._required_identifier(result_id, "result_id")
        matches = self.list_metric_results(normalized_history_id, run_id=run_id).get("result", {}).get("results", [])
        result = next((item for item in matches if item.get("result_id") == normalized_result_id), None)
        if result is None:
            raise LookupError("metric_result_not_found")
        return self._envelope(
            status="available",
            result=result,
            method={"kind": "persisted_metric_result", "execution": "read_only"},
        )

    @staticmethod
    def _persisted_results(detail: Mapping[str, Any] | None, run_id: str, tool_id: str = "") -> list[dict[str, Any]]:
        if not isinstance(detail, Mapping):
            return []
        source_index = next(
            (
                item.get("payload")
                for item in detail.get("artifacts", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("artifact"), Mapping)
                and item["artifact"].get("artifact_type") == "source_index"
                and isinstance(item.get("payload"), Mapping)
            ),
            {},
        )
        results = []
        for item in source_index.get("items", []) if isinstance(source_index, Mapping) else []:
            if not isinstance(item, Mapping) or item.get("resource_type") != "analysis_result":
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            current_tool_id = _text(item.get("title") or payload.get("tool_id"))
            if tool_id and current_tool_id != tool_id:
                continue
            results.append({
                "result_id": _text(item.get("resource_id")),
                "run_id": run_id,
                "tool_id": current_tool_id,
                "status": _text(item.get("status")) or _text(payload.get("status")) or "unavailable",
                "summary": _text(item.get("summary") or payload.get("summary")),
                "spatial_scope": _safe_semantic_value(item.get("spatial_scope") or payload.get("spatial_scope") or {}),
                "time_scope": _safe_semantic_value(item.get("time_scope") or payload.get("time_scope") or {}),
                "limitations": _unique_text(list(item.get("limitations") or payload.get("limitations") or [])),
                "data": _safe_semantic_value(payload.get("data") if "data" in payload else payload),
            })
        return results

    def execute_metric(
        self,
        history_id: str,
        tool_id: str,
        parameters: Mapping[str, Any] | None = None,
        comparison_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one registered metric against one history project.

        Parameters and comparison context are copied at this boundary.  The
        metric service receives a fully assembled private context; callers only
        receive stable result, evidence, scope, method, and comparison facts.
        """

        normalized_history_id = self._required_identifier(history_id, "history_id")
        normalized_tool_id = self._required_identifier(tool_id, "tool_id")
        normalized_parameters = _mapping(parameters, field="parameters")
        normalized_comparison = _mapping(comparison_context, field="comparison_context")
        catalog_item = next((item for item in self._metrics.catalog() if item.tool_id == normalized_tool_id), None)
        if catalog_item is None:
            return self._envelope(
                status="unavailable",
                limitations=["指定的指标工具未注册。"],
                method={"tool_id": normalized_tool_id},
            )
        try:
            context = self._execution_context(normalized_history_id)
        except LookupError:
            return self._envelope(
                status="unavailable",
                limitations=["指定的分析历史不存在或当前不可读取。"],
                method=self._method(catalog_item, self._metrics.detail(normalized_tool_id)),
            )

        detail = self._metrics.detail(normalized_tool_id)
        result = self._metrics.execute(
            tool_id=normalized_tool_id,
            history_id=normalized_history_id,
            history_detail=context.history_detail,
            project_documents=context.project_documents,
            source_index=context.source_index,
            parameters=normalized_parameters,
            project_anchors=normalized_comparison,
        )
        self._retain_metric_result(context.source_index, result)
        return self._execution_envelope(result, catalog_item, detail, context)

    def create_spatial_report_visual(
        self,
        history_id: str,
        visual_request: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Render one approved, real-data thematic map from prior authorized results.

        Callers supply decision semantics, prior result identifiers, and
        immutable geometry-query snapshot identifiers. Template selection,
        layer fields, SVG safety, credentials, and Bridge behavior stay behind
        the ArcGIS domain module.
        """

        normalized_history_id = self._required_identifier(history_id, "history_id")
        request = _mapping(visual_request, field="visual_request")
        try:
            context = self._execution_context(normalized_history_id)
        except LookupError:
            return self._envelope(
                status="unavailable",
                limitations=["指定的分析历史不存在或当前不可读取。"],
                method={"kind": "spatial_report_visual"},
            )
        try:
            visual = self._approved_visual_plan(request, context.source_index)
        except ValueError as exc:
            return self._envelope(
                status="unavailable",
                limitations=[str(exc)],
                method={"kind": "spatial_report_visual"},
            )
        asset = self._visuals.create_approved_visual_asset(
            visual_plan=visual,
            source_index=context.source_index,
            history_detail=context.history_detail,
        )
        context.source_index.upsert(asset)
        if asset.status == "available":
            visual.status = "generated"
            visual.asset_id = asset.resource_id
            payload = asset.payload if isinstance(asset.payload, Mapping) else {}
            self._visual_assets.save(
                history_id=normalized_history_id,
                asset_id=asset.resource_id,
                filename=_text(payload.get("filename")),
                svg=payload.get("svg"),
                visual_manifest=_mapping(payload.get("visual_manifest"), field="visual_manifest"),
            )
        else:
            visual.status = "unavailable"
        return self._visual_envelope(asset, visual, history_id=normalized_history_id)

    def get_spatial_report_visual_asset(self, history_id: str, asset_id: str) -> dict[str, Any]:
        """Return safe metadata for one generated report visual resource."""

        normalized_history_id = self._required_identifier(history_id, "history_id")
        normalized_asset_id = self._required_identifier(asset_id, "asset_id")
        metadata = self._visual_assets.metadata(
            history_id=normalized_history_id,
            asset_id=normalized_asset_id,
        )
        return self._envelope(
            status="available",
            result=metadata,
            artifacts=[{**metadata, "status": "available"}],
            method={"kind": "spatial_report_visual_asset_read"},
        )

    def read_spatial_report_visual_asset(self, history_id: str, asset_id: str) -> str:
        """Read the validated SVG body behind an MCP resource URI."""

        return self._visual_assets.read(
            history_id=self._required_identifier(history_id, "history_id"),
            asset_id=self._required_identifier(asset_id, "asset_id"),
        )

    def read_spatial_report_visual_manifest(self, history_id: str, asset_id: str) -> dict[str, Any]:
        """Read the persisted public render-quality manifest for one map."""
        normalized_history_id = self._required_identifier(history_id, "history_id")
        normalized_asset_id = self._required_identifier(asset_id, "asset_id")
        manifest = self._visual_assets.read_manifest(
            history_id=normalized_history_id,
            asset_id=normalized_asset_id,
        )
        return self._envelope(
            status="available" if manifest.get("quality_status") == "passed" else "unavailable",
            result={"asset_id": normalized_asset_id, "visual_manifest": manifest},
            warnings=list(manifest.get("warnings") or []),
            limitations=[] if manifest.get("quality_status") == "passed" else ["该地图没有可验证的 1.0 质量 manifest。"],
            method={"kind": "spatial_report_visual_manifest_read"},
        )

    @staticmethod
    def _retain_metric_result(source_index: SourceIndex, result: MetricResult) -> None:
        """Make one completed metric addressable by a later map request.

        Production ``MetricToolService`` already writes this entry.  Repeating
        the deterministic upsert here keeps the Skill facade correct for any
        conforming metric implementation and never creates a second result.
        """

        source_index.upsert(
            SourceIndexItem(
                resource_id=result.result_id,
                resource_type="analysis_result",
                title=result.tool_id,
                status=result.status,
                summary=result.summary,
                source_ids=list(result.input_sources),
                spatial_scope=dict(result.spatial_scope),
                time_scope=dict(result.time_scope),
                limitations=list(result.limitations),
                payload=result.model_dump(mode="json", exclude={"result_id"}),
            )
        )

    @staticmethod
    def _approved_visual_plan(request: dict[str, Any], source_index: SourceIndex) -> VisualPlanItem:
        # VisualPlanItem rejects renderer/template/Bridge vocabulary.  These
        # enforced values additionally prevent a caller from self-approving an
        # arbitrary non-map request or impersonating a report editor.
        candidate = {
            **request,
            "owner": "chief_analyst",
            "status": "approved",
            "visual_semantics": "thematic_map",
        }
        visual = VisualPlanItem.model_validate(candidate)
        if not visual.required_result_ids:
            raise ValueError("visual_request_requires_executed_result_ids")
        if not visual.input_snapshot_ids:
            raise ValueError("visual_request_requires_geometry_snapshot_ids")
        available_results = {
            item.resource_id
            for item in source_index.items
            if item.resource_type == "analysis_result" and item.status == "available"
        }
        missing_results = sorted(set(visual.required_result_ids) - available_results)
        if missing_results:
            raise ValueError(f"visual_request_results_not_available:{','.join(missing_results)}")
        authorized_sources = source_index.resource_ids()
        unknown_sources = sorted(set(visual.required_source_ids) - authorized_sources)
        if unknown_sources:
            raise ValueError(f"visual_request_sources_not_authorized:{','.join(unknown_sources)}")
        return visual

    def _execution_context(self, history_id: str) -> _ExecutionContext:
        existing = self._contexts.get(history_id)
        if existing is not None:
            return existing
        project = _mapping(self._projects.read_history_project(history_id), field="history_project")
        # History-backed projects may expose the polygon directly as a coordinate
        # ring, while spatial-project snapshots carry it inside a scope object.
        # Keep that storage detail at this boundary and present one context shape
        # to the metric and visual domains.
        raw_scope = project.get("scope")
        scope = _mapping(raw_scope, field="history_project.scope") if isinstance(raw_scope, Mapping) else {}
        params = _mapping(project.get("params"), field="history_project.params") if isinstance(project.get("params"), Mapping) else {}
        datasets = project.get("datasets") if isinstance(project.get("datasets"), list) else []
        documents = project.get("documents") if isinstance(project.get("documents"), list) else []
        analysis_geometry = _analysis_polygon_geometry(raw_scope)
        polygon = _polygon_ring(analysis_geometry)
        coordinate_system = _text(
            scope.get("coordinate_system")
            or scope.get("coord_type")
            or project.get("coordinate_system")
            or params.get("coordinate_system")
            or params.get("coord_type")
        )
        history_detail: dict[str, Any] = {
            "history_id": history_id,
            "project_name": _text(project.get("project_name")) or history_id,
            "description": _text(project.get("description")),
        }
        if params:
            history_detail["params"] = dict(params)
        if polygon:
            history_detail["polygon"] = polygon
        if analysis_geometry:
            history_detail["analysis_geometry"] = analysis_geometry
        if coordinate_system:
            history_detail["coordinate_system"] = coordinate_system.lower()
        reference_point = scope.get("center") or project.get("center") or params.get("center")
        if isinstance(reference_point, (list, tuple)) and len(reference_point) >= 2:
            try:
                longitude, latitude = float(reference_point[0]), float(reference_point[1])
                if coordinate_system.lower() == "gcj02":
                    from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84
                    longitude, latitude = gcj02_to_wgs84(longitude, latitude)
                history_detail["analysis_reference_point"] = [longitude, latitude]
            except (TypeError, ValueError):
                pass

        normalized_documents: list[dict[str, Any]] = []
        for index, document in enumerate(documents):
            if not isinstance(document, Mapping):
                continue
            document_id = _text(document.get("document_id") or document.get("id")) or str(index + 1)
            normalized_documents.append(
                {
                    "source_id": f"document:{document_id}",
                    "id": document_id,
                    "title": _text(document.get("title")) or f"项目材料 {index + 1}",
                    "document_role": _text(document.get("document_role")),
                    "status": _text(document.get("status")),
                    "extracts": [],
                }
            )
        project_documents = {
            "project_name": history_detail["project_name"],
            "description": history_detail["description"],
            "documents": normalized_documents,
        }
        source_versions = _dataset_versions(datasets, history_id=history_id)
        time_scope = {
            "datasets": [
                {"source_id": item["source_id"], "year": item["year"]}
                for item in source_versions
                if item["year"] is not None
            ]
        }
        warnings = _unique_text(
            list(project.get("warnings") or [])
            + [warning for dataset in datasets if isinstance(dataset, Mapping) for warning in list(dataset.get("warnings") or [])]
        )
        source_index = build_source_index(
            run_id=f"skill-metric:{history_id}",
            project_documents=project_documents,
            source_versions=source_versions,
            data_preview={"scope": {"scope_type": "history_project"}},
        )
        context = _ExecutionContext(
            history_id=history_id,
            history_detail=history_detail,
            project_documents=project_documents,
            source_versions=source_versions,
            source_index=source_index,
            warnings=warnings,
            time_scope=time_scope,
        )
        self._contexts[history_id] = context
        return context

    def _detail_envelope(self, detail: MetricDetail, catalog_item: MetricCatalogItem) -> dict[str, Any]:
        return self._envelope(
            status="available",
            result={
                "tool_id": detail.tool_id,
                "name": detail.name,
                "use_for": detail.use_for.model_dump(mode="json"),
                "interpret_with": detail.interpret_with.model_dump(mode="json"),
                "watch_out": detail.watch_out.model_dump(mode="json"),
                "unavailable_semantics": detail.unavailable_semantics,
                "execution_status": catalog_item.implementation_status,
                "artifact_types": list(detail.asset_types),
            },
            artifacts=[{"artifact_type": item, "status": "available"} for item in detail.asset_types],
            limitations=[] if catalog_item.implementation_status == "implemented" else [detail.unavailable_semantics],
            spatial_scope={"primary_spatial_unit": catalog_item.primary_spatial_unit},
            method=self._method(catalog_item, detail),
            comparison_basis=detail.compare_by.model_dump(mode="json"),
        )

    def _execution_envelope(
        self,
        result: MetricResult,
        catalog_item: MetricCatalogItem,
        detail: MetricDetail,
        context: _ExecutionContext,
    ) -> dict[str, Any]:
        structured = _safe_semantic_value(result.structured_result)
        comparison = structured.pop("project_internal_comparison", None)
        health = structured.pop("data_health", [])
        evidence = self._evidence(context.source_index, result, health)
        artifacts = self._artifacts(context.source_index, result)
        warnings = _unique_text([*context.warnings, *self._health_warnings(health)])
        spatial_scope = _safe_semantic_value(result.spatial_scope)
        if not spatial_scope:
            spatial_scope = {"primary_spatial_unit": catalog_item.primary_spatial_unit}
        time_scope = _safe_semantic_value(result.time_scope)
        if not time_scope:
            time_scope = context.time_scope
        return self._envelope(
            status=result.status,
            result={"result_id": result.result_id, "tool_id": result.tool_id, "summary": result.summary, "data": structured},
            evidence=evidence,
            artifacts=artifacts,
            warnings=warnings,
            limitations=_unique_text(list(result.limitations)),
            spatial_scope=spatial_scope,
            time_scope=time_scope,
            method=self._method(catalog_item, detail),
            comparison_basis=_safe_semantic_value(comparison) if isinstance(comparison, Mapping) else detail.compare_by.model_dump(mode="json"),
        )

    @classmethod
    def _visual_envelope(
        cls, asset: SourceIndexItem, visual: VisualPlanItem, *, history_id: str,
    ) -> dict[str, Any]:
        payload = asset.payload if isinstance(asset.payload, Mapping) else {}
        resource_uri = SpatialReportVisualAssetStore.resource_uri(history_id, asset.resource_id) if asset.status == "available" else ""
        return cls._envelope(
            status=asset.status,
            result={
                "asset_id": asset.resource_id if asset.status == "available" else "",
                "filename": _text(payload.get("filename")),
                "resource_uri": resource_uri,
                "summary": asset.summary,
                "visual_id": visual.visual_id,
                "visual_semantics": visual.visual_semantics,
                "visual_manifest": _safe_semantic_value(payload.get("visual_manifest") or {}),
                "reader_guidance": {
                    "what_it_shows": visual.what_it_shows,
                    "how_to_read": visual.how_to_read,
                    "supports_judgment": visual.supports_judgment,
                    "does_not_prove": visual.does_not_prove,
                    "next_validation": visual.next_validation,
                },
            },
            artifacts=([ {"artifact_id": asset.resource_id, "status": asset.status, "filename": _text(payload.get("filename")), "resource_uri": resource_uri, "summary": asset.summary} ] if asset.status == "available" else []),
            limitations=list(asset.limitations),
            spatial_scope=asset.spatial_scope,
            time_scope=asset.time_scope,
            method={"kind": "spatial_report_visual", "visual_semantics": visual.visual_semantics},
            comparison_basis={"required_result_ids": list(visual.required_result_ids)},
        )

    @staticmethod
    def _catalog_item(item: MetricCatalogItem) -> dict[str, Any]:
        return {
            "tool_id": item.tool_id,
            "name": item.name,
            "purpose": item.purpose,
            "question_tags": list(item.question_tags),
            "primary_spatial_unit": item.primary_spatial_unit,
            "action_targets": list(item.action_targets),
            "execution_status": item.implementation_status,
        }

    @staticmethod
    def _method(item: MetricCatalogItem, detail: MetricDetail) -> dict[str, Any]:
        return {
            "tool_id": item.tool_id,
            "name": item.name,
            "definition": detail.measures.definition,
            "unit": detail.measures.unit,
            "calculation": detail.measures.calculation,
            "spatial_units": list(detail.measures.spatial_units),
            "time_semantics": detail.measures.time_semantics,
            "method_version": detail.measures.method_version,
        }

    @staticmethod
    def _evidence(source_index: SourceIndex, result: MetricResult, health: Any) -> list[dict[str, Any]]:
        source_ids = set(result.input_sources)
        evidence: list[dict[str, Any]] = []
        for item in sorted(source_index.items, key=lambda value: value.resource_id):
            # A metric result is a reusable output, not evidence for itself.
            # Returning it here would let a later chapter cite the conclusion
            # instead of the underlying materials and datasets.
            if item.resource_type == "analysis_result" or not source_ids.intersection(item.source_ids):
                continue
            evidence.append(
                {
                    "evidence_id": item.resource_id,
                    "kind": item.resource_type,
                    "status": item.status,
                    "summary": item.summary,
                    "spatial_scope": _safe_semantic_value(item.spatial_scope),
                    "time_scope": _safe_semantic_value(item.time_scope),
                    "limitations": _unique_text(list(item.limitations)),
                }
            )
        for value in health if isinstance(health, list) else []:
            if not isinstance(value, Mapping):
                continue
            source_id = _text(value.get("source_id"))
            if not source_id:
                continue
            evidence.append(
                {
                    "evidence_id": f"health:{source_id}",
                    "kind": "data_health",
                    "status": _text(value.get("status")) or "unavailable",
                    "summary": "数据健康状态。",
                    "spatial_scope": {},
                    "time_scope": {},
                    "limitations": _unique_text(list(value.get("limitations") or [])),
                }
            )
        return sorted(evidence, key=lambda item: item["evidence_id"])

    @staticmethod
    def _artifacts(source_index: SourceIndex, result: MetricResult) -> list[dict[str, Any]]:
        asset_ids = set(result.asset_ids)
        artifacts: list[dict[str, Any]] = []
        for item in sorted(source_index.items, key=lambda value: value.resource_id):
            if item.resource_type == "asset" and item.resource_id in asset_ids:
                artifacts.append({"artifact_id": item.resource_id, "status": item.status, "summary": item.summary})
        for asset_id in sorted(asset_ids - {item["artifact_id"] for item in artifacts}):
            artifacts.append({"artifact_id": asset_id, "status": "available", "summary": "已生成的指标工件。"})
        return artifacts

    @staticmethod
    def _health_warnings(health: Any) -> list[str]:
        if not isinstance(health, list):
            return []
        return [
            f"{_text(value.get('source_id'))}：数据健康状态为 {_text(value.get('status'))}。"
            for value in health
            if isinstance(value, Mapping) and _text(value.get("status")) in {"limited", "unavailable"}
        ]

    @staticmethod
    def _required_identifier(value: Any, field: str) -> str:
        normalized = _text(value)
        if not normalized:
            raise ValueError(f"{field}_required")
        return normalized

    @staticmethod
    def _envelope(
        *,
        status: _STATUS,
        result: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        limitations: list[str] | None = None,
        spatial_scope: dict[str, Any] | None = None,
        time_scope: dict[str, Any] | None = None,
        method: dict[str, Any] | None = None,
        comparison_basis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return SkillMetricEnvelope(
            status=status,
            result=_safe_semantic_value(result or {}),
            evidence=_safe_semantic_value(evidence or []),
            artifacts=_safe_semantic_value(artifacts or []),
            warnings=_unique_text(warnings or []),
            limitations=_unique_text(limitations or []),
            spatial_scope=_safe_semantic_value(spatial_scope or {}),
            time_scope=_safe_semantic_value(time_scope or {}),
            method=_safe_semantic_value(method or {}),
            comparison_basis=_safe_semantic_value(comparison_basis or {}),
        ).model_dump(mode="json")


_default_tools: SpatialBusinessSkillTools | None = None


def _default() -> SpatialBusinessSkillTools:
    global _default_tools
    if _default_tools is None:
        _default_tools = SpatialBusinessSkillTools()
    return _default_tools


def metric_catalog() -> dict[str, Any]:
    """Discover registered spatial metrics through the default application facade."""

    return _default().metric_catalog()


def metric_detail(tool_id: str) -> dict[str, Any]:
    """Read one registered metric's semantic knowledge card."""

    return _default().metric_detail(tool_id)


def list_metric_results(history_id: str, run_id: str | None = None, tool_id: str | None = None) -> dict[str, Any]:
    """List persisted metric results without executing metrics."""
    return _default().list_metric_results(history_id, run_id=run_id, tool_id=tool_id)


def read_metric_result(history_id: str, result_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Read one persisted metric result without executing it again."""
    return _default().read_metric_result(history_id, result_id, run_id=run_id)


def execute_metric(
    history_id: str,
    tool_id: str,
    parameters: Mapping[str, Any] | None = None,
    comparison_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one history-backed metric through the default application facade."""

    return _default().execute_metric(history_id, tool_id, parameters, comparison_context)


def create_spatial_report_visual(history_id: str, visual_request: Mapping[str, Any]) -> dict[str, Any]:
    """Render a real-data report map from prior authorized metric results."""

    return _default().create_spatial_report_visual(history_id, visual_request)


def check_arcgis_report_status() -> dict[str, Any]:
    """Check ArcGIS report-visual readiness before requesting a render."""

    return _default().arcgis_report_status()


def get_spatial_report_visual_asset(history_id: str, asset_id: str) -> dict[str, Any]:
    """Get metadata and an MCP resource URI for one generated visual."""

    return _default().get_spatial_report_visual_asset(history_id, asset_id)


def read_spatial_report_visual_asset(history_id: str, asset_id: str) -> str:
    """Read a validated generated SVG for the MCP resource handler."""

    return _default().read_spatial_report_visual_asset(history_id, asset_id)


def read_spatial_report_visual_manifest(history_id: str, asset_id: str) -> dict[str, Any]:
    """Read one persisted map quality manifest."""
    return _default().read_spatial_report_visual_manifest(history_id, asset_id)


__all__ = [
    "SpatialBusinessSkillTools",
    "check_arcgis_report_status",
    "create_spatial_report_visual",
    "get_spatial_report_visual_asset",
    "read_spatial_report_visual_asset",
    "read_spatial_report_visual_manifest",
    "execute_metric",
    "list_metric_results",
    "metric_catalog",
    "metric_detail",
    "read_metric_result",
]
