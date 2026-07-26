"""Render only Wave-5-approved report visuals and assemble Markdown assets."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from core.svg_safety import validate_safe_svg

from .planning import APPROVED_TEMPLATE_REGISTRY, validate_visual_plan
from .schemas import EditorialAction, ReportVisualRequest, VisualManifest, VisualManifestItem, VisualPlanItem
from .templates import (
    AGE_CAPTION,
    AGE_TITLE,
    POPULATION_SUPPLY_CONTEXT_CAPTION,
    POPULATION_SUPPLY_CONTEXT_TITLE,
    DIRECTION_CAPTION,
    DIRECTION_TITLE,
    FOCUSED_POI_ROUTE_MAP_CAPTION,
    FOCUSED_POI_ROUTE_MAP_TITLE,
    POI_SUPPLY_STRUCTURE_CAPTION,
    POI_SUPPLY_STRUCTURE_TITLE,
    directional_action_priority_matrix_spec,
    focused_poi_walking_route_map_spec,
    normalize_age_structure,
    normalize_directional_matrix,
    normalize_focused_poi_route_map,
    normalize_poi_supply_structure,
    poi_supply_structure_spec,
    population_age_structure_spec,
    population_supply_context_spec,
)

_ASSET_DIR = "assets"
_BLOCK_PATTERN = re.compile(r"\n?<!-- report-visual:(?P<name>[a-z_]+):start -->.*?<!-- report-visual:(?P=name):end -->\n?", re.DOTALL)


def _report_root(report_path: Path) -> Path:
    return report_path.parent.resolve()


def _render_asset(*, report_dir: Path, filename: str, spec: dict[str, Any]) -> tuple[str, str]:
    # Keep template discovery and all non-rendering MCP capabilities available
    # when an external MCP host has not installed the optional SVG converter.
    # Rendering itself still fails explicitly rather than emitting a placeholder.
    try:
        from vl_convert import vegalite_to_svg
    except ModuleNotFoundError as exc:
        raise RuntimeError("Vega SVG renderer is unavailable; install vl-convert-python to render report visuals") from exc

    assets_dir = report_dir / _ASSET_DIR
    assets_dir.mkdir(parents=True, exist_ok=True)
    svg = vegalite_to_svg(spec)
    validate_safe_svg(svg)
    svg_path = assets_dir / f"{filename}.svg"
    spec_path = assets_dir / f"{filename}.vl.json"
    svg_path.write_text(svg, encoding="utf-8", newline="\n")
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return f"{_ASSET_DIR}/{svg_path.name}", f"{_ASSET_DIR}/{spec_path.name}"


def _visual_markdown(plan: VisualPlanItem, title: str, asset_path: str, caption: str) -> str:
    result_refs = "、".join(f"`{result_id}`" for result_id in plan.metric_result_ids)
    evidence_line = f"\n证据结果：{result_refs}\n" if result_refs else ""
    return (
        f"<!-- report-visual:{plan.template_id}:start -->\n"
        f"![{title}]({asset_path})\n\n"
        f"*图注：{caption}*\n"
        f"{evidence_line}"
        f"<!-- report-visual:{plan.template_id}:end -->\n\n"
    )


def _insert_before_anchor(markdown: str, template_id: str, anchor: str, block: str) -> str:
    if anchor not in markdown:
        raise ValueError(f"报告中未找到图表插入锚点：{anchor}")
    return markdown.replace(anchor, block + anchor, 1)


def _omitted(plan: VisualPlanItem, *, title: str, caption: str, reason: str, data_scope: dict[str, Any] | None = None) -> VisualManifestItem:
    return VisualManifestItem(
        template_id=plan.template_id,
        template_version="v1",
        status="omitted",
        chapter_anchor=plan.chapter_anchor,
        metric_ids=plan.metric_ids,
        title=title,
        caption=caption,
        supports_judgment=plan.supports_judgment,
        does_not_prove=plan.does_not_prove,
        omission_reason=reason,
        data_scope=data_scope or {"selection_reason": plan.selection_reason, "template_input": plan.template_input},
    )


def _generated(
    plan: VisualPlanItem,
    *,
    title: str,
    caption: str,
    asset_path: str,
    spec_path: str,
    data_scope: dict[str, Any],
) -> VisualManifestItem:
    return VisualManifestItem(
        template_id=plan.template_id,
        template_version="v1",
        status="generated",
        chapter_anchor=plan.chapter_anchor,
        metric_ids=plan.metric_ids,
        title=title,
        caption=caption,
        supports_judgment=plan.supports_judgment,
        does_not_prove=plan.does_not_prove,
        asset_path=asset_path,
        spec_path=spec_path,
        data_scope={"selection_reason": plan.selection_reason, **data_scope},
    )


def _anchor_ready(plan: VisualPlanItem, markdown: str, *, title: str, caption: str) -> VisualManifestItem | None:
    if plan.chapter_anchor not in markdown:
        return _omitted(plan, title=title, caption=caption, reason="报告中未找到该模板的指定锚点")
    return None


def _render_population(plan: VisualPlanItem, request: ReportVisualRequest, report_dir: Path, markdown: str) -> tuple[VisualManifestItem, str]:
    title = AGE_TITLE
    missing_anchor = _anchor_ready(plan, markdown, title=title, caption=AGE_CAPTION)
    if missing_anchor:
        return missing_anchor, markdown
    normalized = normalize_age_structure(request.age_structure)
    if isinstance(normalized, str):
        return _omitted(plan, title=title, caption=AGE_CAPTION, reason=normalized), markdown
    year, values = normalized
    title = AGE_TITLE.replace("2026", str(year))
    asset_path, spec_path = _render_asset(report_dir=report_dir, filename="population-age-structure", spec=population_age_structure_spec(year, values))
    return _generated(plan, title=title, caption=AGE_CAPTION, asset_path=asset_path, spec_path=spec_path, data_scope={"year": year, "age_bands": values}), _insert_before_anchor(markdown, plan.template_id, plan.chapter_anchor, _visual_markdown(plan, title, asset_path, AGE_CAPTION))


def _render_population_supply_context(plan: VisualPlanItem, request: ReportVisualRequest, report_dir: Path, markdown: str) -> tuple[VisualManifestItem, str]:
    missing_anchor = _anchor_ready(
        plan,
        markdown,
        title=POPULATION_SUPPLY_CONTEXT_TITLE,
        caption=POPULATION_SUPPLY_CONTEXT_CAPTION,
    )
    if missing_anchor:
        return missing_anchor, markdown
    age = normalize_age_structure(request.age_structure)
    if isinstance(age, str):
        return _omitted(plan, title=POPULATION_SUPPLY_CONTEXT_TITLE, caption=POPULATION_SUPPLY_CONTEXT_CAPTION, reason=age), markdown
    supply = normalize_poi_supply_structure(request.poi_supply_structure)
    if isinstance(supply, str):
        return _omitted(plan, title=POPULATION_SUPPLY_CONTEXT_TITLE, caption=POPULATION_SUPPLY_CONTEXT_CAPTION, reason=supply), markdown
    population_year, age_values = age
    asset_path, spec_path = _render_asset(
        report_dir=report_dir,
        filename="population-supply-context",
        spec=population_supply_context_spec(
            population_year=population_year,
            age_values=age_values,
            poi_year=supply["year"],
            supply_roles=supply["roles"],
        ),
    )
    scope = {
        "population_year": population_year,
        "poi_year": supply["year"],
        "population_scope": "saved_15_minute_walking_background",
        "poi_scope": supply["scope"],
        "age_bands": age_values,
        "display_roles": supply["roles"],
        "taxonomy_audit": supply["taxonomy_audit"],
    }
    return _generated(
        plan,
        title=POPULATION_SUPPLY_CONTEXT_TITLE,
        caption=POPULATION_SUPPLY_CONTEXT_CAPTION,
        asset_path=asset_path,
        spec_path=spec_path,
        data_scope=scope,
    ), _insert_before_anchor(
        markdown,
        plan.template_id,
        plan.chapter_anchor,
        _visual_markdown(plan, POPULATION_SUPPLY_CONTEXT_TITLE, asset_path, POPULATION_SUPPLY_CONTEXT_CAPTION),
    )


def _plan_actions(plan: VisualPlanItem) -> list[EditorialAction] | str:
    raw_actions = plan.template_input.get("editorial_actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        return "视觉计划缺少已审校的 editorial_actions；不使用渲染器默认行动规则"
    try:
        return [EditorialAction.model_validate(item) for item in raw_actions]
    except Exception as exc:
        return f"视觉计划中的 directional actions 无效：{exc}"


def _render_directional(plan: VisualPlanItem, request: ReportVisualRequest, report_dir: Path, markdown: str) -> tuple[VisualManifestItem, str]:
    missing_anchor = _anchor_ready(plan, markdown, title=DIRECTION_TITLE, caption=DIRECTION_CAPTION)
    if missing_anchor:
        return missing_anchor, markdown
    actions = _plan_actions(plan)
    if isinstance(actions, str):
        return _omitted(plan, title=DIRECTION_TITLE, caption=DIRECTION_CAPTION, reason=actions), markdown
    normalized = normalize_directional_matrix(request.directional_evidence_matrix, actions)
    if isinstance(normalized, str):
        return _omitted(plan, title=DIRECTION_TITLE, caption=DIRECTION_CAPTION, reason=normalized), markdown
    matrix = request.directional_evidence_matrix.get("directional_evidence_matrix", {})
    source_versions = matrix.get("source_versions", {}) if isinstance(matrix, dict) else {}
    source_years = {
        source: details.get("year")
        for source, details in source_versions.items()
        if source in {"poi", "population", "nightlight"}
        and isinstance(details, dict)
        and details.get("year") is not None
    }
    asset_path, spec_path = _render_asset(
        report_dir=report_dir,
        filename="directional-action-priority",
        spec=directional_action_priority_matrix_spec(normalized, source_years=source_years),
    )
    return _generated(plan, title=DIRECTION_TITLE, caption=DIRECTION_CAPTION, asset_path=asset_path, spec_path=spec_path, data_scope={"actions": [item.model_dump() for item in actions], "source_years": source_years}), _insert_before_anchor(markdown, plan.template_id, plan.chapter_anchor, _visual_markdown(plan, DIRECTION_TITLE, asset_path, DIRECTION_CAPTION))


def _render_poi_supply_structure(plan: VisualPlanItem, request: ReportVisualRequest, report_dir: Path, markdown: str) -> tuple[VisualManifestItem, str]:
    missing_anchor = _anchor_ready(plan, markdown, title=POI_SUPPLY_STRUCTURE_TITLE, caption=POI_SUPPLY_STRUCTURE_CAPTION)
    if missing_anchor:
        return missing_anchor, markdown
    normalized = normalize_poi_supply_structure(request.poi_supply_structure)
    if isinstance(normalized, str):
        return _omitted(plan, title=POI_SUPPLY_STRUCTURE_TITLE, caption=POI_SUPPLY_STRUCTURE_CAPTION, reason=normalized), markdown
    year = normalized["year"]
    title = f"{POI_SUPPLY_STRUCTURE_TITLE}（{year}）" if year is not None else POI_SUPPLY_STRUCTURE_TITLE
    definition = APPROVED_TEMPLATE_REGISTRY[plan.template_id]
    asset_path, spec_path = _render_asset(
        report_dir=report_dir,
        filename=definition.filename,
        spec=poi_supply_structure_spec(normalized["roles"], year=year),
    )
    scope = {
        "poi_year": year,
        "source_id": "current:dataset:poi",
        "scope": normalized["scope"],
        "taxonomy_audit": normalized["taxonomy_audit"],
        "isochrone_audit": normalized["isochrone_audit"],
        "five_minute_accessibility_status": normalized["five_minute_accessibility_status"],
        "classified_rows": normalized["classified_rows"],
        "display_roles": normalized["roles"],
        "omitted_groups": normalized["omitted_groups"],
    }
    return _generated(plan, title=title, caption=POI_SUPPLY_STRUCTURE_CAPTION, asset_path=asset_path, spec_path=spec_path, data_scope=scope), _insert_before_anchor(
        markdown,
        plan.template_id,
        plan.chapter_anchor,
        _visual_markdown(plan, title, asset_path, POI_SUPPLY_STRUCTURE_CAPTION),
    )

def _render_focused_poi_route_map(plan: VisualPlanItem, request: ReportVisualRequest, report_dir: Path, markdown: str) -> tuple[VisualManifestItem, str]:
    missing_anchor = _anchor_ready(plan, markdown, title=FOCUSED_POI_ROUTE_MAP_TITLE, caption=FOCUSED_POI_ROUTE_MAP_CAPTION)
    if missing_anchor:
        return missing_anchor, markdown
    normalized = normalize_focused_poi_route_map(request.focused_poi_accessibility)
    if isinstance(normalized, str):
        return _omitted(plan, title=FOCUSED_POI_ROUTE_MAP_TITLE, caption=FOCUSED_POI_ROUTE_MAP_CAPTION, reason=normalized), markdown
    year, route_map = normalized
    snap_offset = route_map.get("origin_snap_offset_m")
    caption = FOCUSED_POI_ROUTE_MAP_CAPTION
    if snap_offset is not None:
        caption += f" 本次分析中心吸附至最近路网约 {snap_offset:.0f} 米；该连接仅为路网计算起点，不表示正式入口或门到门路线。"
    definition = APPROVED_TEMPLATE_REGISTRY[plan.template_id]
    asset_path, spec_path = _render_asset(report_dir=report_dir, filename=definition.filename, spec=focused_poi_walking_route_map_spec(route_map))
    scope = {
        "poi_year": year,
        "road_source_id": "current:dataset:road_edges",
        "routing_algorithm": "local_road_network_shortest_path",
        "route_poi_count": len(route_map["pois"]),
        "road_edges_clipped_count": route_map["road_edges_clipped_count"],
        "road_edges_rendered_count": route_map["road_edges_rendered_count"],
        "omitted_groups": route_map["omitted_groups"],
    }
    scope["origin_snap_offset_m"] = snap_offset
    return _generated(plan, title=FOCUSED_POI_ROUTE_MAP_TITLE, caption=caption, asset_path=asset_path, spec_path=spec_path, data_scope=scope), _insert_before_anchor(markdown, plan.template_id, plan.chapter_anchor, _visual_markdown(plan, FOCUSED_POI_ROUTE_MAP_TITLE, asset_path, caption))


_RENDERERS: dict[str, Callable[[VisualPlanItem, ReportVisualRequest, Path, str], tuple[VisualManifestItem, str]]] = {
    "population_age_structure": _render_population,
    "population_supply_context": _render_population_supply_context,
    "directional_action_priority_matrix": _render_directional,
    "poi_supply_structure": _render_poi_supply_structure,
    "focused_poi_walking_route_map": _render_focused_poi_route_map,
}


def render_report_visuals(raw_request: ReportVisualRequest | dict[str, Any]) -> VisualManifest:
    """Persist the editor's visual plan, then render only its planned templates.

    This module deliberately does not infer visual needs from Markdown or invent a
    chart from metrics.  Any selected template still validates its data and its
    report anchor; failures become explicit manifest omissions rather than a
    placeholder figure.
    """
    request = raw_request if isinstance(raw_request, ReportVisualRequest) else ReportVisualRequest.model_validate(raw_request)
    validate_visual_plan(request.visual_plan)
    report_path = request.report_path.resolve()
    if not report_path.is_file():
        raise FileNotFoundError(f"报告 Markdown 不存在：{report_path}")
    report_dir = _report_root(report_path)
    (report_dir / "visual-plan.json").write_text(request.visual_plan.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    markdown = _BLOCK_PATTERN.sub("\n", report_path.read_text(encoding="utf-8"))
    manifest_items: list[VisualManifestItem] = []
    for plan in request.visual_plan.items:
        definition = APPROVED_TEMPLATE_REGISTRY[plan.template_id]
        if plan.status == "omitted":
            manifest_items.append(_omitted(plan, title=definition.title, caption=definition.caption, reason=str(plan.omission_reason)))
            continue
        renderer = _RENDERERS[plan.template_id]
        item, markdown = renderer(plan, request, report_dir, markdown)
        manifest_items.append(item)
    report_path.write_text(markdown.rstrip() + "\n", encoding="utf-8", newline="\n")
    manifest = VisualManifest(run_id=request.run_id, items=manifest_items)
    (report_dir / "visual-manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest
