"""Constrained MCP-facing tools for Wave-5 Vega report visuals.

The visual-evidence editor may select from approved templates and reference
persisted metric-result IDs.  It never receives a Vega specification, raw
metric payload, filesystem path, or SVG body.  This module resolves the
referenced immutable metric results inside the same history project and passes
them to the existing constrained renderer.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from modules.spatial_projects.service import SpatialProjectService
from modules.spatial_action.metric_result_registry import (
    MetricResultRegistry,
    metric_result_registry,
)

from .asset_store import ReportVegaVisualAssetStore
from .planning import APPROVED_TEMPLATE_REGISTRY
from .schemas import VisualPlan
from .service import render_report_visuals

_DIRECTIONAL_TEMPLATE = "directional_action_priority_matrix"
_ALLOWED_TEMPLATE_INPUTS: dict[str, frozenset[str]] = {
    _DIRECTIONAL_TEMPLATE: frozenset({"editorial_actions"}),
}
_FORBIDDEN_TEMPLATE_INPUT_KEYS = frozenset(
    {
        "asset_path",
        "filename",
        "file_path",
        "path",
        "report_path",
        "spec",
        "svg",
        "vega",
        "vega_lite",
        "vegalite",
    }
)
_METRIC_REQUEST_FIELDS = {
    "population.age_structure": "age_structure",
    "regional.directional_evidence_matrix": "directional_evidence_matrix",
    "poi.supply_structure": "poi_supply_structure",
    "poi.focused_accessibility": "focused_poi_accessibility",
}


@dataclass(frozen=True)
class _PersistedMetricResult:
    result_id: str
    tool_id: str
    status: str
    structured_result: dict[str, Any]
    time_scope: dict[str, Any]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field}_must_be_object")
    return deepcopy(dict(value))


class ReportVegaVisualTools:
    """Own the trusted boundary between a visual editor and the Vega renderer."""

    def __init__(
        self,
        *,
        project_service: SpatialProjectService | None = None,
        result_registry: MetricResultRegistry | None = None,
        asset_store: ReportVegaVisualAssetStore | None = None,
    ) -> None:
        self._projects = project_service or SpatialProjectService()
        self._result_registry = result_registry or metric_result_registry
        self._assets = asset_store or ReportVegaVisualAssetStore()

    def template_catalog(self) -> dict[str, Any]:
        """Return the only report-visual templates an editor may select."""

        templates = []
        for template in APPROVED_TEMPLATE_REGISTRY.values():
            templates.append(
                {
                    "template_id": template.template_id,
                    "title": template.title,
                    "caption": template.caption,
                    "required_metric_ids": list(template.required_metric_ids),
                    "chapter_anchor": template.required_anchor,
                    "allowed_template_input_keys": sorted(_ALLOWED_TEMPLATE_INPUTS.get(template.template_id, frozenset())),
                    "selection_rule": "仅当删除该图会削弱相邻已审校判断时选择；不得制作装饰图或改写策略。",
                }
            )
        return {
            "status": "available",
            "result": {"templates": templates},
            "limitations": [
                "此目录不接受自由 Vega-Lite JSON、SVG、文件路径或原始指标数据。",
                "图表数据必须由同一 history_id 下已持久化的空间指标结果 ID 提供。",
            ],
            "method": {"kind": "report_vega_visual_template_catalog", "renderer": "constrained_vega_lite"},
        }

    def render(
        self,
        *,
        history_id: str,
        report_id: str,
        report_markdown: str,
        visual_plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Render a reviewed plan using only same-history persisted metric results."""

        normalized_history_id = self._required_id(history_id, "history_id")
        normalized_report_id = self._required_id(report_id, "report_id")
        if not isinstance(report_markdown, str) or not report_markdown.strip():
            raise ValueError("report_markdown_required")
        # Validate the history before any local report bundle is written.
        self._projects.read_history_project(normalized_history_id)

        plan = VisualPlan.model_validate(_mapping(visual_plan, field="visual_plan"))
        self._validate_editor_plan(plan)
        current_results = self._runtime_metric_results(normalized_history_id)
        renderer_payload = self._resolve_renderer_payload(plan, current_results)
        report_path = self._assets.prepare_report(
            history_id=normalized_history_id,
            report_id=normalized_report_id,
            report_markdown=report_markdown,
        )
        manifest = render_report_visuals(
            {
                "run_id": plan.run_id,
                "report_path": report_path,
                "visual_plan": plan.model_dump(mode="json"),
                **renderer_payload,
            }
        )
        enriched = self._enriched_manifest(
            history_id=normalized_history_id,
            report_id=normalized_report_id,
            plan=plan,
            manifest=manifest.model_dump(mode="json"),
        )
        self._assets.write_manifest(
            history_id=normalized_history_id,
            report_id=normalized_report_id,
            manifest=enriched,
        )
        assets = [
            {
                "asset_id": item["asset_id"],
                "template_id": item["template_id"],
                "title": item["title"],
                "resource_uri": item["resource_uri"],
            }
            for item in enriched["items"]
            if item["status"] == "generated"
        ]
        omitted = [
            {
                "template_id": item["template_id"],
                "reason": item.get("omission_reason") or "not_generated",
            }
            for item in enriched["items"]
            if item["status"] == "omitted"
        ]
        return {
            "status": "available",
            "result": {
                "history_id": normalized_history_id,
                "report_id": normalized_report_id,
                "report_resource_uri": self._assets.report_resource_uri(normalized_history_id, normalized_report_id),
                "visual_plan_resource_uri": self._assets.plan_resource_uri(normalized_history_id, normalized_report_id),
                "visual_manifest_resource_uri": self._assets.manifest_resource_uri(normalized_history_id, normalized_report_id),
                "assets": assets,
                "omitted": omitted,
            },
            "limitations": [
                "生成的视觉仅支持 visual-plan 中已审校判断；不会推断客流、营收、合作关系或自由图表结论。",
            ],
            "method": {"kind": "report_vega_visual_render", "renderer": "constrained_vega_lite"},
        }

    def get_asset(self, *, history_id: str, report_id: str, asset_id: str) -> dict[str, Any]:
        normalized_history_id = self._required_id(history_id, "history_id")
        normalized_report_id = self._required_id(report_id, "report_id")
        self._projects.read_history_project(normalized_history_id)
        metadata = self._assets.asset_metadata(
            history_id=normalized_history_id,
            report_id=normalized_report_id,
            asset_id=self._required_id(asset_id, "asset_id"),
        )
        return {
            "status": "available",
            "result": metadata,
            "method": {"kind": "report_vega_visual_asset_read"},
        }

    def read_asset(self, *, history_id: str, report_id: str, asset_id: str) -> str:
        return self._assets.read_asset(
            history_id=self._required_id(history_id, "history_id"),
            report_id=self._required_id(report_id, "report_id"),
            asset_id=self._required_id(asset_id, "asset_id"),
        )

    def read_report(self, *, history_id: str, report_id: str) -> str:
        return self._assets.read_report(
            history_id=self._required_id(history_id, "history_id"),
            report_id=self._required_id(report_id, "report_id"),
        )

    def read_plan(self, *, history_id: str, report_id: str) -> str:
        return self._assets.read_plan(
            history_id=self._required_id(history_id, "history_id"),
            report_id=self._required_id(report_id, "report_id"),
        )

    def read_manifest(self, *, history_id: str, report_id: str) -> dict[str, Any]:
        normalized_history_id = self._required_id(history_id, "history_id")
        normalized_report_id = self._required_id(report_id, "report_id")
        self._projects.read_history_project(normalized_history_id)
        return {
            "status": "available",
            "result": {"visual_manifest": self._assets.read_manifest(history_id=normalized_history_id, report_id=normalized_report_id)},
            "method": {"kind": "report_vega_visual_manifest_read"},
        }

    @staticmethod
    def _required_id(value: Any, field: str) -> str:
        text = _text(value)
        ReportVegaVisualAssetStore._validate_id(text, field)
        return text

    def _runtime_metric_results(self, history_id: str) -> dict[str, _PersistedMetricResult]:
        return {
            result.result_id: _PersistedMetricResult(
                result_id=result.result_id,
                tool_id=result.tool_id,
                status=result.status,
                structured_result=result.structured_result,
                time_scope=result.time_scope,
            )
            for result in self._result_registry.list(history_id)
        }

    def _validate_editor_plan(self, plan: VisualPlan) -> None:
        for item in plan.items:
            definition = APPROVED_TEMPLATE_REGISTRY[item.template_id]
            if item.chapter_anchor != definition.required_anchor:
                raise ValueError(f"{item.template_id}_must_use_approved_report_anchor")
            if not _text(item.statement_ref):
                raise ValueError(f"{item.template_id}_requires_statement_ref")
            if item.status == "planned" and not item.metric_result_ids:
                raise ValueError(f"{item.template_id}_requires_metric_result_ids")
            missing_metric_ids = set(definition.required_metric_ids).difference(item.metric_ids)
            if missing_metric_ids:
                raise ValueError(f"{item.template_id}_missing_required_metric_ids:{','.join(sorted(missing_metric_ids))}")
            self._validate_template_input(item.template_id, item.template_input)

    @staticmethod
    def _validate_template_input(template_id: str, template_input: Mapping[str, Any]) -> None:
        keys = {str(key) for key in template_input}
        forbidden = keys & _FORBIDDEN_TEMPLATE_INPUT_KEYS
        if forbidden:
            raise ValueError(f"{template_id}_template_input_forbidden:{','.join(sorted(forbidden))}")
        allowed = _ALLOWED_TEMPLATE_INPUTS.get(template_id, frozenset())
        unexpected = keys - allowed
        if unexpected:
            raise ValueError(f"{template_id}_template_input_not_allowed:{','.join(sorted(unexpected))}")

    @staticmethod
    def _resolve_renderer_payload(plan: VisualPlan, persisted: Mapping[str, _PersistedMetricResult]) -> dict[str, dict[str, Any]]:
        selected_by_tool: dict[str, _PersistedMetricResult] = {}
        for item in plan.items:
            if item.status != "planned":
                continue
            for result_id in item.metric_result_ids:
                result = persisted.get(result_id)
                if result is None:
                    raise ValueError(f"visual_metric_result_not_found:{result_id}")
                if result.status != "available":
                    raise ValueError(f"visual_metric_result_not_available:{result_id}")
                if result.tool_id not in item.metric_ids:
                    raise ValueError(f"visual_metric_result_tool_mismatch:{result_id}")
                prior = selected_by_tool.get(result.tool_id)
                if prior is not None and prior.result_id != result.result_id:
                    raise ValueError(f"visual_metric_result_ambiguous_for_tool:{result.tool_id}")
                selected_by_tool[result.tool_id] = result
            required = set(APPROVED_TEMPLATE_REGISTRY[item.template_id].required_metric_ids)
            selected_metric_ids = {
                persisted[result_id].tool_id
                for result_id in item.metric_result_ids
                if result_id in persisted
            }
            missing = required.difference(selected_metric_ids)
            if missing:
                raise ValueError(f"visual_metric_results_missing_required:{item.template_id}:{','.join(sorted(missing))}")

        request_values: dict[str, dict[str, Any]] = {}
        for tool_id, field in _METRIC_REQUEST_FIELDS.items():
            result = selected_by_tool.get(tool_id)
            if result is not None:
                value = deepcopy(result.structured_result)
                if result.time_scope:
                    value.setdefault("time_scope", deepcopy(result.time_scope))
                request_values[field] = value
        return request_values

    def _enriched_manifest(
        self,
        *,
        history_id: str,
        report_id: str,
        plan: VisualPlan,
        manifest: Mapping[str, Any],
    ) -> dict[str, Any]:
        plans = {item.template_id: item for item in plan.items}
        items: list[dict[str, Any]] = []
        for raw_item in manifest.get("items") or []:
            item = deepcopy(dict(raw_item)) if isinstance(raw_item, Mapping) else {}
            template_id = _text(item.get("template_id"))
            plan_item = plans.get(template_id)
            if plan_item is None:
                raise ValueError("rendered_visual_not_in_plan")
            item["statement_ref"] = plan_item.statement_ref
            item["metric_result_ids"] = list(plan_item.metric_result_ids)
            item["asset_id"] = template_id
            if item.get("status") == "generated":
                asset_path = _text(item.get("asset_path"))
                self._assets.validate_asset_path(asset_path)
                item["resource_uri"] = self._assets.asset_resource_uri(history_id, report_id, template_id)
            items.append(item)
        return {
            "schema_version": "report-vega-visuals.v1",
            "history_id": history_id,
            "report_id": report_id,
            "run_id": plan.run_id,
            "report_resource_uri": self._assets.report_resource_uri(history_id, report_id),
            "visual_plan_resource_uri": self._assets.plan_resource_uri(history_id, report_id),
            "items": items,
        }


_default_tools = ReportVegaVisualTools()


def report_visual_template_catalog() -> dict[str, Any]:
    return _default_tools.template_catalog()


def render_report_vega_visuals(
    history_id: str,
    report_id: str,
    report_markdown: str,
    visual_plan: Mapping[str, Any],
) -> dict[str, Any]:
    return _default_tools.render(
        history_id=history_id,
        report_id=report_id,
        report_markdown=report_markdown,
        visual_plan=visual_plan,
    )


def get_report_vega_visual_asset(history_id: str, report_id: str, asset_id: str) -> dict[str, Any]:
    return _default_tools.get_asset(history_id=history_id, report_id=report_id, asset_id=asset_id)


def read_report_vega_visual_asset(history_id: str, report_id: str, asset_id: str) -> str:
    return _default_tools.read_asset(history_id=history_id, report_id=report_id, asset_id=asset_id)


def read_report_vega_rendered_report(history_id: str, report_id: str) -> str:
    return _default_tools.read_report(history_id=history_id, report_id=report_id)


def read_report_vega_visual_plan(history_id: str, report_id: str) -> str:
    return _default_tools.read_plan(history_id=history_id, report_id=report_id)


def read_report_vega_visual_manifest(history_id: str, report_id: str) -> dict[str, Any]:
    return _default_tools.read_manifest(history_id=history_id, report_id=report_id)


__all__ = [
    "ReportVegaVisualTools",
    "get_report_vega_visual_asset",
    "read_report_vega_rendered_report",
    "read_report_vega_visual_asset",
    "read_report_vega_visual_manifest",
    "read_report_vega_visual_plan",
    "render_report_vega_visuals",
    "report_visual_template_catalog",
]
