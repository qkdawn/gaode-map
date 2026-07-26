"""Render only Wave-5-approved report visuals and assemble Markdown assets."""
from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from core.svg_safety import validate_safe_svg

from .planning import APPROVED_TEMPLATE_REGISTRY, validate_visual_plan
from .schemas import EditorialAction, ReportVisualRequest, VisualManifest, VisualManifestItem, VisualPlan, VisualPlanItem
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
    POI_DISTANCE_BAND_SUPPLY_CAPTION,
    POI_DISTANCE_BAND_SUPPLY_TITLE,
    directional_action_priority_matrix_spec,
    focused_poi_walking_route_map_spec,
    normalize_age_structure,
    normalize_directional_matrix,
    normalize_focused_poi_route_map,
    normalize_poi_supply_structure,
    normalize_poi_distance_band_supply_structure,
    poi_distance_band_supply_structure_spec,
    poi_supply_structure_spec,
    population_age_structure_spec,
    population_supply_context_spec,
)

_ASSET_DIR = "assets"
_BLOCK_PATTERN = re.compile(r"\n?<!-- report-visual:(?P<name>[a-z_]+):start -->.*?<!-- report-visual:(?P=name):end -->\n?", re.DOTALL)
_VISUAL_BLOCK_PATTERN = re.compile(r"<!-- report-visual:(?P<name>[a-z_]+):start -->(?P<body>.*?)<!-- report-visual:(?P=name):end -->", re.DOTALL)


def _report_root(report_path: Path) -> Path:
    return report_path.parent.resolve()


def _canonical_sha256(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _assert_scope_year_compatible(plan: VisualPlanItem, provenance: dict[str, dict[str, Any]]) -> None:
    """Reject an editor plan that names a different scope/year than its result."""
    if not plan.scope_year:
        return

    def values_for_key(value: Any, keys: set[str]) -> list[Any]:
        values: list[Any] = []
        if isinstance(value, dict):
            values.extend(item for key, item in value.items() if key in keys)
            for item in value.values():
                values.extend(values_for_key(item, keys))
        elif isinstance(value, list):
            for item in value:
                values.extend(values_for_key(item, keys))
        return values

    result_scopes = [
        (
            str(provenance.get(result_id, {}).get("tool_id") or ""),
            provenance.get(result_id, {}).get("time_scope", {}),
        )
        for result_id in plan.metric_result_ids
    ]
    for key, expected in plan.scope_year.items():
        metric_prefix = key[:-5] if key.endswith("_year") else ""
        keys = {key, "year"} if metric_prefix else {key}
        matching_scopes = [
            scope for tool_id, scope in result_scopes
            if not metric_prefix or tool_id == metric_prefix or tool_id.startswith(f"{metric_prefix}.")
        ]
        if not matching_scopes:
            raise ValueError(f"visual_scope_year_conflict:{plan.template_id}:{key}")
        matches = [
            any(str(value) == str(expected) for value in values_for_key(scope, keys))
            for scope in matching_scopes
        ]
        # A generic expectation applies to every result; a metric-prefixed one
        # applies only to that result family. Results may never satisfy each
        # other's year or scope fields.
        if expected is not None and not all(matches):
            raise ValueError(f"visual_scope_year_conflict:{plan.template_id}:{key}")


def _remove_stale_template_assets(report_dir: Path) -> None:
    """A new run may never inherit a prior run's template asset or spec."""
    assets_dir = report_dir / _ASSET_DIR
    for definition in APPROVED_TEMPLATE_REGISTRY.values():
        for suffix in (".svg", ".vl.json"):
            candidate = assets_dir / f"{definition.filename}{suffix}"
            if candidate.is_file():
                candidate.unlink()


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
        metric_result_ids=plan.metric_result_ids,
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
        metric_result_ids=plan.metric_result_ids,
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


def _render_poi_distance_band_supply_structure(plan: VisualPlanItem, request: ReportVisualRequest, report_dir: Path, markdown: str) -> tuple[VisualManifestItem, str]:
    missing_anchor = _anchor_ready(plan, markdown, title=POI_DISTANCE_BAND_SUPPLY_TITLE, caption=POI_DISTANCE_BAND_SUPPLY_CAPTION)
    if missing_anchor:
        return missing_anchor, markdown
    normalized = normalize_poi_distance_band_supply_structure(request.poi_distance_band_supply_structure)
    if isinstance(normalized, str):
        return _omitted(plan, title=POI_DISTANCE_BAND_SUPPLY_TITLE, caption=POI_DISTANCE_BAND_SUPPLY_CAPTION, reason=normalized), markdown
    definition = APPROVED_TEMPLATE_REGISTRY[plan.template_id]
    asset_path, spec_path = _render_asset(
        report_dir=report_dir,
        filename=definition.filename,
        spec=poi_distance_band_supply_structure_spec(normalized["categories"], year=normalized["year"]),
    )
    title = f"{POI_DISTANCE_BAND_SUPPLY_TITLE}（{normalized['year']}）"
    scope = {"poi_year": normalized["year"], "scope": normalized["scope"], "total_count": normalized["total_count"], "categories": normalized["categories"]}
    return _generated(plan, title=title, caption=POI_DISTANCE_BAND_SUPPLY_CAPTION, asset_path=asset_path, spec_path=spec_path, data_scope=scope), _insert_before_anchor(
        markdown, plan.template_id, plan.chapter_anchor, _visual_markdown(plan, title, asset_path, POI_DISTANCE_BAND_SUPPLY_CAPTION)
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
    "poi_distance_band_supply_structure": _render_poi_distance_band_supply_structure,
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
    report_id = request.report_id
    for plan in request.visual_plan.items:
        _assert_scope_year_compatible(plan, request.metric_result_provenance)
    _remove_stale_template_assets(report_dir)
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
    for plan, item in zip(request.visual_plan.items, manifest_items):
        item.history_id = request.history_id
        item.report_id = request.report_id
        item.run_id = request.run_id
        item.scope_year_fingerprint = _canonical_sha256(
            {
                "expected": plan.scope_year,
                "result_provenance": {result_id: request.metric_result_provenance.get(result_id, {}) for result_id in plan.metric_result_ids},
                "data_scope": item.data_scope,
            }
        )
        if item.status == "generated":
            item.asset_sha256 = _file_sha256(report_dir / str(item.asset_path))
            item.spec_sha256 = _file_sha256(report_dir / str(item.spec_path))
    manifest = VisualManifest(
        history_id=request.history_id,
        report_id=report_id,
        run_id=request.run_id,
        metric_result_ids=sorted({result_id for plan in request.visual_plan.items for result_id in plan.metric_result_ids}),
        visual_plan_sha256=_file_sha256(report_dir / "visual-plan.json"),
        report_markdown_sha256=_file_sha256(report_path),
        items=manifest_items,
    )
    (report_dir / "visual-manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def validate_report_visual_bundle(report_dir: str | Path) -> list[str]:
    """Validate plan, manifest, Markdown blocks and generated files as one contract."""
    root = Path(report_dir).resolve()
    plan_path, manifest_path, report_path = root / "visual-plan.json", root / "visual-manifest.json", root / "project-report.md"
    if not plan_path.exists() and not manifest_path.exists():
        return []
    errors: list[str] = []
    if not plan_path.is_file() or not manifest_path.is_file() or not report_path.is_file():
        return ["visual_bundle_missing_required_file"]
    try:
        plan = VisualPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        manifest = VisualManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"visual_bundle_invalid:{exc}"]
    if manifest.visual_plan_sha256 != _file_sha256(plan_path):
        errors.append("visual_plan_checksum_mismatch")
    if manifest.report_markdown_sha256 != _file_sha256(report_path):
        errors.append("visual_report_checksum_mismatch")
    if manifest.run_id != plan.run_id:
        errors.append("visual_run_id_mismatch")
    plan_by_id = {item.template_id: item for item in plan.items}
    manifest_by_id = {item.template_id: item for item in manifest.items}
    if set(plan_by_id) != set(manifest_by_id):
        errors.append("visual_plan_manifest_item_mismatch")
    markdown = report_path.read_text(encoding="utf-8")
    blocks = {match.group("name"): match.group("body") for match in _VISUAL_BLOCK_PATTERN.finditer(markdown)}
    if len(blocks) != len(list(_VISUAL_BLOCK_PATTERN.finditer(markdown))):
        errors.append("visual_markdown_block_duplicate")
    for template_id, plan_item in plan_by_id.items():
        item = manifest_by_id.get(template_id)
        if item is None:
            continue
        if item.status == "omitted":
            if not item.omission_reason:
                errors.append(f"visual_omission_reason_missing:{template_id}")
            if template_id in blocks or item.asset_path or item.spec_path:
                errors.append(f"visual_omitted_item_has_asset_or_block:{template_id}")
            continue
        if plan_item.status != "planned" or template_id not in blocks:
            errors.append(f"visual_generated_block_missing:{template_id}")
        if item.metric_ids != plan_item.metric_ids:
            errors.append(f"visual_metric_ids_mismatch:{template_id}")
        if item.metric_result_ids != plan_item.metric_result_ids:
            errors.append(f"visual_metric_result_ids_mismatch:{template_id}")
        if not item.asset_path or not item.spec_path:
            errors.append(f"visual_generated_paths_missing:{template_id}")
            continue
        asset, spec = root / item.asset_path, root / item.spec_path
        if not asset.is_file() or not spec.is_file():
            errors.append(f"visual_generated_file_missing:{template_id}")
        else:
            if item.asset_sha256 != _file_sha256(asset):
                errors.append(f"visual_asset_checksum_mismatch:{template_id}")
            if item.spec_sha256 != _file_sha256(spec):
                errors.append(f"visual_spec_checksum_mismatch:{template_id}")
        # The renderer may include trusted result provenance; require at least a
        # full SHA-256 rather than accepting a free-form fingerprint.
        if not re.fullmatch(r"[0-9a-f]{64}", item.scope_year_fingerprint):
            errors.append(f"visual_scope_year_fingerprint_invalid:{template_id}")
    if set(blocks) != {item.template_id for item in manifest.items if item.status == "generated"}:
        errors.append("visual_markdown_manifest_block_mismatch")
    return errors
