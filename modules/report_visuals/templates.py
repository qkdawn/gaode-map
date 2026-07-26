"""The two approved Vega-Lite templates and their input validation."""
from __future__ import annotations

import math
import re
from typing import Any

from .schemas import (
    AGE_BANDS,
    DIRECTION_LABELS,
    DIRECTION_ORDER,
    DISTANCE_BANDS,
    DISTANCE_BAND_LABELS,
    EditorialAction,
)

AGE_TITLE = "15 分钟范围居住背景的年龄结构（2026）"
AGE_CAPTION = "统计口径：15 分钟范围内的居住背景年龄结构。"
POPULATION_SUPPLY_CONTEXT_TITLE = "居民使用背景与周边供给结构"
POPULATION_SUPPLY_CONTEXT_CAPTION = "人口用于描述居住背景，POI 用于描述设施供给；二者均不证明项目客群、需求、客流、消费、经营质量或合作关系。"
DIRECTION_TITLE = "方向 × 距离圈层的首轮行动优先级"
DIRECTION_CAPTION = "规则：仅在报告已成立的方向性证据同时满足时标出行动类别；未列为首轮动作的单元保持中性。用于安排首轮现场验证与试验。"

_FONT = "Microsoft YaHei, Noto Sans CJK SC, PingFang SC, sans-serif"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canonical_age_band(value: object) -> str | None:
    text = str(value).strip().replace(" ", "").replace("岁", "").replace("至", "-").replace("—", "-").replace("–", "-")
    aliases = {"0-14": "0–14", "00-14": "0–14", "15-24": "15–24", "25-44": "25–44", "45-59": "45–59", "60+": "60+", "60以上": "60+", "60及以上": "60+", "60岁以上": "60+"}
    return aliases.get(text)


def normalize_age_structure(raw: dict[str, Any] | None) -> tuple[int, list[dict[str, Any]]] | str:
    if not isinstance(raw, dict):
        return "缺少 population.age_structure 结构化指标"
    time_scope = raw.get("time_scope") if isinstance(raw.get("time_scope"), dict) else {}
    year = raw.get("year") or raw.get("dataset_year") or time_scope.get("year")
    if year is None:
        year = next(
            (
                item.get("year")
                for item in time_scope.get("datasets", [])
                if isinstance(item, dict)
                and item.get("source_id") == "current:dataset:population"
            ),
            None,
        )
    try:
        year = int(year)
    except (TypeError, ValueError):
        return "年龄结构缺少可用年份"
    distribution = raw.get("age_distribution") or raw.get("rows") or raw.get("data")
    if not isinstance(distribution, list):
        distribution = next(
            (
                value.get("age_distribution")
                for value in raw.values()
                if isinstance(value, dict)
                and isinstance(value.get("age_distribution"), list)
            ),
            None,
        )
    if not isinstance(distribution, list):
        return "年龄结构缺少五段分布"
    shares: dict[str, float] = {}
    for item in distribution:
        if not isinstance(item, dict):
            continue
        band = _canonical_age_band(item.get("age_band_label") or item.get("age_band") or item.get("label") or item.get("band"))
        value = _number(item.get("percentage") if "percentage" in item else item.get("share", item.get("ratio")))
        if band is None or value is None:
            continue
        if value < 0:
            return "年龄结构包含负值"
        shares[band] = value * 100 if value <= 1 else value
    if set(shares) != set(AGE_BANDS):
        counts = {band: 0.0 for band in AGE_BANDS}
        for item in distribution:
            if not isinstance(item, dict):
                continue
            try:
                start_age = int(str(item.get("age_band") or "").strip())
            except (TypeError, ValueError):
                continue
            count = _number(item.get("total"))
            if count is None:
                female = _number(item.get("female"))
                male = _number(item.get("male"))
                count = female + male if female is not None and male is not None else None
            if count is None or count < 0:
                continue
            band = (
                "0–14" if start_age < 15 else
                "15–24" if start_age < 25 else
                "25–44" if start_age < 45 else
                "45–59" if start_age < 60 else
                "60+"
            )
            counts[band] += count
        total = sum(counts.values())
        if total <= 0 or any(value <= 0 for value in counts.values()):
            return "年龄结构必须完整包含 0–14、15–24、25–44、45–59、60+ 五段"
        shares = {band: value / total * 100 for band, value in counts.items()}
    if abs(sum(shares.values()) - 100) > 0.25:
        return "年龄结构占比合计未接近 100%"
    return year, [{"age_band": band, "share": round(shares[band], 2), "label": f"{shares[band]:.2f}%"} for band in AGE_BANDS]


def population_age_structure_spec(year: int, values: list[dict[str, Any]]) -> dict[str, Any]:
    title = AGE_TITLE.replace("2026", str(year))
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": "15 分钟范围内的居住背景年龄结构。",
        "width": 640,
        "height": 238,
        "title": {"text": title, "anchor": "start", "font": _FONT, "fontSize": 20, "fontWeight": 700, "color": "#172033", "offset": 18},
        "data": {"values": values},
        "layer": [
            {
                "mark": {"type": "bar", "cornerRadiusEnd": 5, "color": "#2F6B8A", "height": 28},
                "encoding": {
                    "y": {"field": "age_band", "type": "ordinal", "sort": list(AGE_BANDS), "axis": {"title": None, "labelFont": _FONT, "labelFontSize": 14, "labelColor": "#334155", "domain": False, "ticks": False}},
                    "x": {"field": "share", "type": "quantitative", "scale": {"domain": [0, max(40, math.ceil(max(item["share"] for item in values) / 5) * 5 + 5)]}, "axis": {"title": "人口占比（%）", "titleFont": _FONT, "labelFont": _FONT, "titleColor": "#475569", "labelColor": "#64748B", "gridColor": "#E2E8F0", "tickCount": 5, "domain": False}},
                    "tooltip": [{"field": "age_band", "type": "ordinal", "title": "年龄段"}, {"field": "share", "type": "quantitative", "title": "占比（%）", "format": ".2f"}],
                },
            },
            {
                "mark": {"type": "text", "align": "left", "baseline": "middle", "dx": 7, "font": _FONT, "fontSize": 13, "fontWeight": 700, "color": "#1E293B"},
                "encoding": {"y": {"field": "age_band", "type": "ordinal", "sort": list(AGE_BANDS)}, "x": {"field": "share", "type": "quantitative"}, "text": {"field": "label"}},
            },
        ],
        "config": {"view": {"stroke": None}, "background": "#FFFFFF"},
    }


POI_SUPPLY_STRUCTURE_TITLE = "15 分钟等时圈内的 POI 供给结构"
POI_SUPPLY_STRUCTURE_CAPTION = (
    "统计对象为逐点经保存的 15 分钟步行等时圈几何核验后的 POI；深色表示等时圈内数量。"
    "浅色仅在保存路网的连续道路可达性可用时表示≤5分钟可达数量，未出现不代表 0。"
)
_SUPPLY_ROLE_TITLES = {
    "complementary_anchor": "项目所需配套",
    "comparison_supply": "同类对标供给",
}
_SUPPLY_METRIC_ORDER = ("15 分钟等时圈内 POI", "≤5 分钟可达 POI")
_SUPPLY_METRIC_COLORS = ("#2F6B8A", "#8CB9D3")

def _nonnegative_integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0 or not float(number).is_integer():
        return None
    return int(number)


def _supply_label(value: Any) -> str:
    label = re.sub(r"\s+", " ", str(value or "").strip())
    if not label:
        return ""
    return label if len(label) <= 17 else label[:16] + "…"


def normalize_poi_supply_structure(raw: dict[str, Any] | None) -> dict[str, Any] | str:
    """Validate only verified real-taxonomy rows for the supply graphic."""

    if not isinstance(raw, dict):
        return "缺少 poi.supply_structure 结构化指标"
    payload = raw.get("poi_supply_structure") if isinstance(raw.get("poi_supply_structure"), dict) else raw.get("result") if isinstance(raw.get("result"), dict) else raw
    status = str(payload.get("status") or raw.get("status") or "available").strip().lower()
    if status not in {"available", "partial", "generated", "success", "succeeded", "complete"}:
        return str(payload.get("error_reason") or payload.get("summary") or "POI 供给结构指标不可用")
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else raw.get("scope")
    if not isinstance(scope, dict) or scope.get("kind") != "verified_walking_isochrone" or scope.get("time_min") != 15 or scope.get("mode") != "walking":
        return "POI 供给结构缺少已核验的 15 分钟 walking 等时圈几何口径"
    rows = payload.get("classified_rows")
    if not isinstance(rows, list) or not rows:
        return "POI 供给结构缺少经过真实 POI 分类映射的明细行"

    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {role: {} for role in _SUPPLY_ROLE_TITLES}
    for row in rows:
        if not isinstance(row, dict):
            return "POI 供给结构包含无效分类行"
        role = str(row.get("role") or "").strip()
        main_category = str(row.get("main_category") or "").strip()
        subcategory = str(row.get("subcategory") or "").strip()
        count = _nonnegative_integer(row.get("isochrone_poi_count"))
        nearby_raw = row.get("nearby_5_min_poi_count")
        nearby = _nonnegative_integer(nearby_raw) if nearby_raw is not None else None
        if role not in _SUPPLY_ROLE_TITLES or not main_category or not subcategory or count is None:
            return "POI 供给结构分类行缺少真实主类、附属类或等时圈数量"
        if nearby_raw is not None and nearby is None:
            return "POI 供给结构分类行的五分钟可达数量无效"
        selected = row.get("selected_type_codes")
        references = row.get("statement_refs")
        if not isinstance(selected, list) or not selected or not isinstance(references, list) or not references:
            return "POI 供给结构分类行缺少类型选择或报告判断回指"
        grouped[role].setdefault(main_category, []).append({
            "subcategory": subcategory,
            "isochrone_poi_count": count,
            "nearby_5_min_poi_count": nearby,
            "selected_type_codes": [str(value) for value in selected],
            "source_group_ids": [str(value) for value in row.get("source_group_ids") or []],
            "statement_refs": [str(value) for value in references],
        })
    if not any(grouped[role] for role in grouped):
        return "没有可用于供给结构图的真实分类行"
    try:
        year = int(payload.get("year")) if payload.get("year") is not None else None
    except (TypeError, ValueError):
        year = None
    return {
        "year": year,
        "roles": _supply_display_blocks(grouped),
        "classified_rows": grouped,
        "scope": scope,
        "taxonomy_audit": payload.get("taxonomy_audit") if isinstance(payload.get("taxonomy_audit"), dict) else {},
        "isochrone_audit": payload.get("isochrone_audit") if isinstance(payload.get("isochrone_audit"), dict) else {},
        "five_minute_accessibility_status": str(payload.get("five_minute_accessibility_status") or "unavailable"),
        "omitted_groups": [
            {"group_id": str(item.get("group_id") or ""), "reason": str(item.get("omission_reason") or item.get("status") or "")}
            for item in payload.get("groups") or []
            if isinstance(item, dict) and str(item.get("status") or "available") not in {"available", "partial"}
        ],
    }


def _supply_display_blocks(grouped: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, list[dict[str, Any]]]:
    """Keep every true main category, collapsing only extra subcategories."""

    result: dict[str, list[dict[str, Any]]] = {role: [] for role in _SUPPLY_ROLE_TITLES}
    for role, main_categories in grouped.items():
        for main_category, rows in sorted(main_categories.items(), key=lambda item: (-sum(row["isochrone_poi_count"] for row in item[1]), item[0])):
            ordered = sorted(rows, key=lambda row: (-row["isochrone_poi_count"], row["subcategory"]))
            visible = ordered[:3]
            if len(ordered) > 3:
                remainder = ordered[3:]
                nearby_values = [row["nearby_5_min_poi_count"] for row in remainder]
                visible.append({
                    "subcategory": "其他已选附属类",
                    "isochrone_poi_count": sum(row["isochrone_poi_count"] for row in remainder),
                    "nearby_5_min_poi_count": sum(nearby_values) if all(value is not None for value in nearby_values) else None,
                    "selected_type_codes": [code for row in remainder for code in row["selected_type_codes"]],
                    "source_group_ids": [group_id for row in remainder for group_id in row["source_group_ids"]],
                    "statement_refs": [ref for row in remainder for ref in row["statement_refs"]],
                    "other_subcategories": [row["subcategory"] for row in remainder],
                })
            result[role].append({"main_category": main_category, "subcategories": visible})
    return result


def poi_supply_structure_spec(roles: dict[str, list[dict[str, Any]]], *, year: int | None = None) -> dict[str, Any]:
    """Build the two-panel chart from real main-category / subcategory rows."""

    all_counts = [
        count for blocks in roles.values() for block in blocks for row in block["subcategories"]
        for count in (row["isochrone_poi_count"], row.get("nearby_5_min_poi_count")) if count is not None
    ]
    x_domain = [0, max(2, math.ceil(max(all_counts, default=1) * 1.22))]
    max_rows = max((sum(len(block["subcategories"]) for block in blocks) for blocks in roles.values()), default=1)
    panel_height = max(180, max_rows * 55 + 58)

    def panel(role: str, show_legend: bool) -> dict[str, Any]:
        blocks = roles.get(role, [])
        values: list[dict[str, Any]] = []
        order: list[str] = []
        for block in blocks:
            main = block["main_category"]
            for row in block["subcategories"]:
                label = f"{main}｜{row['subcategory']}"
                order.append(label)
                values.append({"category": label, "main_category": main, "subcategory": row["subcategory"], "metric": _SUPPLY_METRIC_ORDER[0], "count": row["isochrone_poi_count"], "label": str(row["isochrone_poi_count"])})
                if row.get("nearby_5_min_poi_count") is not None:
                    values.append({"category": label, "main_category": main, "subcategory": row["subcategory"], "metric": _SUPPLY_METRIC_ORDER[1], "count": row["nearby_5_min_poi_count"], "label": str(row["nearby_5_min_poi_count"])})
        x = {"field": "count", "type": "quantitative", "scale": {"domain": x_domain}, "axis": {"title": "POI 数量", "titleFont": _FONT, "titleFontSize": 12, "labelFont": _FONT, "labelFontSize": 11, "titleColor": "#475569", "labelColor": "#64748B", "gridColor": "#E2E8F0", "tickCount": 4, "domain": False}}
        y = {"field": "category", "type": "ordinal", "sort": order, "axis": {"title": None, "labelFont": _FONT, "labelFontSize": 11, "labelColor": "#334155", "labelLimit": 185, "domain": False, "ticks": False}}
        color = {"field": "metric", "type": "nominal", "scale": {"domain": list(_SUPPLY_METRIC_ORDER), "range": list(_SUPPLY_METRIC_COLORS)}, "legend": {"title": None, "orient": "bottom", "direction": "horizontal", "labelFont": _FONT, "labelFontSize": 11, "labelColor": "#475569", "symbolType": "square"} if show_legend else None}
        return {"width": 360, "height": panel_height, "title": {"text": _SUPPLY_ROLE_TITLES[role], "anchor": "start", "font": _FONT, "fontSize": 15, "fontWeight": 700, "color": "#172033", "offset": 12}, "data": {"values": values}, "layer": [
            {"mark": {"type": "bar", "cornerRadiusEnd": 4, "height": 16}, "encoding": {"x": x, "y": y, "yOffset": {"field": "metric"}, "color": color, "tooltip": [{"field": "main_category", "title": "真实主类"}, {"field": "subcategory", "title": "真实附属类"}, {"field": "metric", "title": "口径"}, {"field": "count", "title": "POI 数量"}]}},
            {"mark": {"type": "text", "align": "left", "baseline": "middle", "dx": 5, "font": _FONT, "fontSize": 11, "fontWeight": 700, "color": "#172033"}, "encoding": {"x": {"field": "count", "type": "quantitative", "scale": {"domain": x_domain}}, "y": y, "yOffset": {"field": "metric"}, "text": {"field": "label"}}},
        ]}

    title = f"{POI_SUPPLY_STRUCTURE_TITLE}（{year}）" if year is not None else POI_SUPPLY_STRUCTURE_TITLE
    return {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "description": "真实主类和附属类的 15 分钟等时圈 POI 供给盘点；不生成综合评分或业务结果推断。", "title": {"text": title, "anchor": "start", "font": _FONT, "fontSize": 20, "fontWeight": 700, "color": "#172033", "offset": 18}, "hconcat": [panel("complementary_anchor", True), panel("comparison_supply", False)], "spacing": 28, "resolve": {"scale": {"y": "independent"}}, "config": {"view": {"stroke": None}, "background": "#FFFFFF"}}


def _matrix_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    aliases = {label: key for key, label in DIRECTION_LABELS.items()}
    value = aliases.get(text, text)
    return value if value in DIRECTION_ORDER else None


def _matrix_distance_band(value: Any) -> str | None:
    text = str(value or "").strip().replace("–", "-").replace("—", "-").replace(" ", "")
    return text if text in DISTANCE_BANDS else None


def _matrix_evidence_present(row: dict[str, Any], requirement: str) -> bool:
    """Check that an editorially declared evidence type is actually present.

    This deliberately validates evidence availability only.  It does not turn
    population, POI, nightlight, or road fields into a synthetic score and does
    not second-guess the report's reviewed action rule.
    """

    signals = row.get("signals") if isinstance(row.get("signals"), dict) else {}
    if requirement == "population":
        return any(
            _number(row.get(key)) is not None
            for key in (
                "population_density",
                "population_density_mean",
                "population",
                "population_count",
            )
        )
    if requirement == "poi":
        return any(_number(row.get(key)) is not None for key in ("poi_density", "poi_count", "poi_total"))
    if requirement == "nightlight":
        return any(_number(row.get(key)) is not None for key in ("nightlight_mean", "nightlight", "nightlight_value"))
    if requirement == "road":
        if signals.get("road_coverage_available") is False or signals.get("road_available") is False:
            return False
        return any(
            _number(row.get(key)) is not None
            for key in (
                "road_integration",
                "road_integration_covered_mean",
                "road_coverage_ratio",
                "road_density",
                "road_density_covered_mean",
            )
        )
    if requirement == "low_road_coverage":
        return signals.get("road_coverage_available") is not False and _number(row.get("road_coverage_ratio")) is not None
    if requirement == "low_road_integration":
        return any(
            _number(row.get(key)) is not None
            for key in ("road_integration", "road_integration_covered_mean")
        )
    return False


def normalize_directional_matrix(
    raw: dict[str, Any] | None,
    actions: list[EditorialAction],
) -> list[dict[str, Any]] | str:
    """Validate the complete directional evidence matrix and apply reviewed actions.

    The visual layer receives a complete 8-by-3 evidence matrix plus explicit,
    reviewed action declarations.  It never calculates a composite priority
    score; a cell is coloured only when the action's required evidence fields
    are available in the corresponding matrix record.
    """

    if not isinstance(raw, dict):
        return "缺少 regional.directional_evidence_matrix 结构化指标"
    nested = raw.get("directional_evidence_matrix")
    if isinstance(nested, dict):
        raw = nested
    rows = raw.get("sectors") or raw.get("rows") or raw.get("data")
    if not isinstance(rows, list):
        return "方向性证据矩阵缺少扇区明细"

    matrix: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        direction = _matrix_direction(row.get("direction") or row.get("sector") or row.get("bearing"))
        distance_band = _matrix_distance_band(row.get("distance_band") or row.get("band") or row.get("distance"))
        if direction is None or distance_band is None:
            continue
        key = direction, distance_band
        if key in matrix:
            return f"方向性证据矩阵包含重复单元：{direction}/{distance_band}"
        matrix[key] = row

    expected = {(direction, band) for direction in DIRECTION_ORDER for band in DISTANCE_BANDS}
    missing = expected.difference(matrix)
    if missing:
        return "方向性证据矩阵必须完整包含 8 个方向 × 3 个距离圈层"

    declared: dict[tuple[str, str], EditorialAction] = {}
    for action in actions:
        key = action.direction, action.distance_band
        if key in declared:
            return f"视觉计划包含重复行动单元：{action.direction}/{action.distance_band}"
        declared[key] = action

    normalized: list[dict[str, Any]] = []
    for distance_band in DISTANCE_BANDS:
        for direction in DIRECTION_ORDER:
            row = matrix[(direction, distance_band)]
            action = declared.get((direction, distance_band))
            if action is None:
                action_name = "未列为首轮动作"
                evidence_label = ""
                cell_label = ""
            else:
                unavailable = [
                    requirement
                    for requirement in action.required_evidence
                    if not _matrix_evidence_present(row, requirement)
                ]
                if unavailable:
                    return (
                        f"方向 {direction}/{distance_band} 缺少行动所需证据："
                        + "、".join(unavailable)
                    )
                action_name = action.action
                evidence_label = action.evidence_label
                cell_label = {
                    "导向验证": "导向",
                    "通达诊断": "通达",
                    "夜间联动测试": "夜间",
                }[action_name]
            normalized.append({
                "direction": DIRECTION_LABELS[direction],
                "distance_band": DISTANCE_BAND_LABELS[distance_band],
                "action": action_name,
                "evidence_label": evidence_label,
                "cell_label": cell_label,
            })
    return normalized

def directional_action_priority_matrix_spec(
    values: list[dict[str, Any]],
    *,
    source_years: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_domain = ["导向验证", "通达诊断", "夜间联动测试", "未列为首轮动作"]
    action_range = ["#2F6B8A", "#C66A27", "#7657B8", "#E2E8F0"]
    years = source_years or {}
    subtitle_parts = [
        f"POI {years['poi']}" if years.get("poi") is not None else "",
        f"夜光 {years['nightlight']}" if years.get("nightlight") is not None else "",
        f"人口 {years['population']}" if years.get("population") is not None else "",
        "路网当前快照",
    ]
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": "分类行动优先级矩阵；原始空间代理保持分项验证，图中不含数值预测。",
        "width": 640,
        "height": 260,
        "title": {"text": DIRECTION_TITLE, "subtitle": " · ".join(part for part in subtitle_parts if part), "anchor": "start", "font": _FONT, "subtitleFont": _FONT, "fontSize": 20, "subtitleFontSize": 11, "fontWeight": 700, "color": "#172033", "subtitleColor": "#64748B", "offset": 18},
        "data": {"values": values},
        "layer": [
            {
                "mark": {"type": "rect", "cornerRadius": 4, "stroke": "#FFFFFF", "strokeWidth": 3},
                "encoding": {
                    "x": {"field": "direction", "type": "ordinal", "sort": [DIRECTION_LABELS[item] for item in DIRECTION_ORDER], "axis": {"title": "方向", "titleFont": _FONT, "labelFont": _FONT, "labelFontSize": 13, "labelColor": "#334155", "domain": False, "ticks": False}},
                    "y": {"field": "distance_band", "type": "ordinal", "sort": [DISTANCE_BAND_LABELS[item] for item in DISTANCE_BANDS], "axis": {"title": "距离圈层", "titleFont": _FONT, "labelFont": _FONT, "labelFontSize": 13, "labelColor": "#334155", "domain": False, "ticks": False}},
                    "color": {"field": "action", "type": "nominal", "scale": {"domain": action_domain, "range": action_range}, "legend": {"title": "行动类别", "titleFont": _FONT, "labelFont": _FONT, "orient": "bottom", "columns": 2, "symbolType": "square", "labelColor": "#475569"}},
                    "tooltip": [{"field": "direction", "title": "方向"}, {"field": "distance_band", "title": "距离圈层"}, {"field": "action", "title": "行动类别"}, {"field": "evidence_label", "title": "已核验的证据标签"}],
                },
            },
            {
                "transform": [{"filter": "datum.cell_label !== ''"}],
                "mark": {"type": "text", "font": _FONT, "fontSize": 11, "fontWeight": 700, "lineBreak": "\n", "lineHeight": 13, "color": "#FFFFFF", "align": "center", "baseline": "middle"},
                "encoding": {"x": {"field": "direction", "type": "ordinal", "sort": [DIRECTION_LABELS[item] for item in DIRECTION_ORDER]}, "y": {"field": "distance_band", "type": "ordinal", "sort": [DISTANCE_BAND_LABELS[item] for item in DISTANCE_BANDS]}, "text": {"field": "cell_label"}},
            },
        ],
        "config": {"view": {"stroke": None}, "background": "#FFFFFF"},
    }

def _route_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _compact_text(value: Any, *, limit: int = 28) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


_FOCUSED_ROLE_LABELS = {
    "complementary_anchor": "互补锚点",
    "comparison_supply": "同类对标",
}
_FOCUSED_ROLE_COLORS = {
    "complementary_anchor": "#2F6B8A",
    "comparison_supply": "#7657B8",
}
# Route colors distinguish POI type groups on the map; role badges remain a
# separate semantic channel so color never implies an operating score.
_FOCUSED_GROUP_COLORS = ("#2F6B8A", "#318C74", "#A56B17", "#7657B8")


def _display_name_lines(value: Any, *, limit: int = 24, line_length: int = 12) -> tuple[str, str]:
    """Return fixed two-line display text while retaining full values upstream."""
    text = _compact_text(value, limit=limit)
    return text[:line_length], text[line_length:]


def _normalize_route_map_poi_rows(
    raw: dict[str, Any] | None,
) -> tuple[int | None, list[dict[str, Any]], list[dict[str, str]]] | str:
    """Validate route-verified grouped POIs for the route-map sidebar.

    The function only accepts the spatial metric's route-backed rows.  Group
    omissions are preserved for the manifest but do not discard other valid
    groups, which lets a mixed complementary/comparison visual remain honest.
    """
    if not isinstance(raw, dict):
        return "缺少 poi.focused_accessibility 结构化结果"
    payload = raw.get("focused_poi_accessibility") if isinstance(raw.get("focused_poi_accessibility"), dict) else raw
    status = str(payload.get("status") or raw.get("status") or "").strip().lower()
    if status not in {"available", "generated", "success", "succeeded", "complete", "partial"}:
        return str(payload.get("omission_reason") or raw.get("summary") or "真实步行路由不可用")
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        return "重点 POI 类型组为空"
    if len(groups) > 4:
        return "重点 POI 图最多展示四个类型组"
    year_value = payload.get("year") or raw.get("year")
    try:
        year = int(year_value) if year_value is not None else None
    except (TypeError, ValueError):
        year = None

    cards: list[dict[str, Any]] = []
    omitted_groups: list[dict[str, str]] = []
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            return "重点 POI 类型组结构无效"
        title = str(group.get("title") or group.get("label") or "").strip()
        role = str(group.get("role") or "").strip()
        statement_ref = str(group.get("statement_ref") or "").strip()
        if not title or role not in _FOCUSED_ROLE_LABELS or not statement_ref:
            return "重点 POI 类型组缺少名称、角色或已审校判断回指"
        group_status = str(group.get("status") or "available").strip().lower()
        if group_status != "available":
            omitted_groups.append({"title": title, "role": role, "reason": str(group.get("omission_reason") or "group_route_unavailable")})
            continue
        pois = group.get("pois") or group.get("items")
        if not isinstance(pois, list) or not pois:
            omitted_groups.append({"title": title, "role": role, "reason": str(group.get("omission_reason") or "no_route_verified_pois")})
            continue
        if len(pois) > 3:
            return f"重点 POI 类型组“{title}”超过三项展示上限"
        for poi_index, poi in enumerate(pois):
            if not isinstance(poi, dict):
                return f"重点 POI 类型组“{title}”存在无效 POI"
            name = str(poi.get("name") or "").strip()
            category = str(poi.get("category") or poi.get("type") or "").strip()
            distance_m = _route_number(poi.get("walking_distance_m", poi.get("distance_m")))
            duration_s = _route_number(poi.get("walking_duration_s", poi.get("duration_s")))
            route_status = str(poi.get("route_status") or "available").lower()
            if not name or not category or distance_m is None or duration_s is None:
                return f"重点 POI 类型组“{title}”缺少真实名称、类别或步行路线结果"
            if poi.get("estimated") is True or route_status in {"estimated", "unavailable", "failed"}:
                return f"重点 POI 类型组“{title}”包含非真实步行路线"
            if duration_s > 15 * 60:
                return f"重点 POI 类型组“{title}”包含超过 15 分钟的路线"
            line_1, line_2 = _display_name_lines(name)
            cards.append({
                "group_index": group_index,
                "poi_index": poi_index,
                "group_title": _compact_text(title, limit=16),
                "group_title_full": title,
                "statement_ref": statement_ref,
                "role": role,
                "role_label": _FOCUSED_ROLE_LABELS[role],
                "role_color": _FOCUSED_ROLE_COLORS[role],
                "name": name,
                "name_line_1": line_1,
                "name_line_2": line_2,
                "category": _compact_text(category, limit=18),
                "distance_label": f"{round(distance_m):,} m",
                "duration_label": f"{max(1, math.ceil(duration_s / 60))} 分钟",
            })
    if not cards:
        return "所有重点 POI 类型组均未获得真实步行路线"
    return year, cards, omitted_groups


FOCUSED_POI_ROUTE_MAP_TITLE = "重点 POI 步行路线与当前路网"
FOCUSED_POI_ROUTE_MAP_CAPTION = (
    "图中路线由当前 road_edges 快照上、从指标结果记录的统一分析起点至 POI 的本地最短路径计算得到；"
    "分钟按统一 4.5 km/h 参考步行速度换算；分析中心仅作为统一计算起点。"
)


def normalize_focused_poi_route_map(raw: dict[str, Any] | None) -> tuple[int | None, dict[str, Any]] | str:
    """Validate only local-road route evidence for the constrained map template."""
    cards_result = _normalize_route_map_poi_rows(raw)
    if isinstance(cards_result, str):
        return cards_result
    year, cards, omitted_groups = cards_result
    payload = raw.get("focused_poi_accessibility") if isinstance(raw, dict) and isinstance(raw.get("focused_poi_accessibility"), dict) else raw
    if not isinstance(payload, dict):
        return "缺少 poi.focused_accessibility 结构化结果"
    if str(payload.get("routing_algorithm") or "local_road_network_shortest_path") != "local_road_network_shortest_path":
        return "路线地图只接受当前路网快照上的本地最短路径"
    context = payload.get("map_context")
    if not isinstance(context, dict) or context.get("status") == "unavailable":
        return str((context or {}).get("omission_reason") or "缺少可用于路线地图的当前路网快照")
    if str(context.get("road_source_id") or "") != "current:dataset:road_edges":
        return "路线地图缺少 current:dataset:road_edges 路网来源声明"
    origin = _valid_map_coordinate(context.get("origin") or payload.get("origin"))
    if origin is None:
        return "路线地图缺少统一分析起点"
    road_values = _geojson_line_values(context.get("road_edges"), feature_key="road")
    if not road_values:
        return "路线地图缺少可绘制的真实路网线"

    card_lookup = {(card["group_index"], card["poi_index"]): card for card in cards}
    groups = payload.get("groups")
    if not isinstance(groups, list):
        return "重点 POI 类型组为空"
    route_values: list[dict[str, Any]] = []
    poi_values: list[dict[str, Any]] = []
    sidebar: list[dict[str, Any]] = []
    group_headers: list[dict[str, Any]] = []
    number = 0
    origin_snap_offsets: list[float] = []
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict) or str(group.get("status") or "available").lower() != "available":
            continue
        role = str(group.get("role") or "")
        role_color = _FOCUSED_ROLE_COLORS.get(role)
        if role_color is None:
            return "路线地图的 POI 角色无效"
        route_color = _FOCUSED_GROUP_COLORS[group_index % len(_FOCUSED_GROUP_COLORS)]
        title = str(group.get("title") or "").strip()
        pois = group.get("pois")
        group_has_route = False
        if not isinstance(pois, list):
            continue
        for poi_index, poi in enumerate(pois):
            card = card_lookup.get((group_index, poi_index))
            if card is None or not isinstance(poi, dict):
                continue
            geometry = poi.get("route_geometry")
            route_status = str(poi.get("route_geometry_status") or "").lower()
            if route_status != "available" or not isinstance(geometry, dict) or geometry.get("type") != "LineString":
                continue
            coordinates = _line_coordinates(geometry.get("coordinates"))
            if len(coordinates) < 2:
                continue
            snap_offset = _route_number(poi.get("origin_snap_distance_m"))
            if snap_offset is not None:
                origin_snap_offsets.append(snap_offset)
            number += 1
            route_id = f"route-{number}"
            for order, (x, y) in enumerate(coordinates):
                route_values.append({"route_id": route_id, "order": order, "x": x, "y": y, "route_color": route_color})
            location = _valid_map_coordinate(poi.get("location"))
            if location is None:
                location = coordinates[-1]
            poi_values.append({"number": str(number), "x": location[0], "y": location[1], "route_color": route_color})
            sidebar.append({
                **card,
                "number": str(number),
                "role_color": role_color,
                "route_color": route_color,
                "group_title": _compact_text(title, limit=16),
            })
            group_has_route = True
        if group_has_route:
            group_headers.append({"group_index": group_index, "group_title": _compact_text(title, limit=16), "role_label": _FOCUSED_ROLE_LABELS[role], "role_color": role_color, "route_color": route_color})
    if not route_values or not poi_values:
        return "没有带完整本地路网路径几何的重点 POI"
    extent = _map_extent([*road_values, *route_values, *poi_values, {"x": origin[0], "y": origin[1]}])
    if extent is None:
        return "路线地图范围无效"
    return year, {
        "origin": {"x": origin[0], "y": origin[1]},
        "roads": road_values,
        "routes": route_values,
        "pois": poi_values,
        "sidebar": sidebar,
        "group_headers": group_headers,
        "omitted_groups": omitted_groups,
        "extent": extent,
        "road_edges_clipped_count": int(context.get("road_edges_clipped_count") or len(road_values)),
        "road_edges_rendered_count": int(context.get("road_edges_rendered_count") or len(road_values)),
        "origin_snap_offset_m": round(max(origin_snap_offsets), 1) if origin_snap_offsets else None,
    }


def focused_poi_walking_route_map_spec(data: dict[str, Any]) -> dict[str, Any]:
    """Build a map-like road/path panel plus a compact, numbered POI list."""
    x_domain = [data["extent"][0], data["extent"][2]]
    y_domain = [data["extent"][1], data["extent"][3]]
    x = {"type": "quantitative", "scale": {"domain": x_domain, "nice": False}, "axis": None}
    y = {"type": "quantitative", "scale": {"domain": y_domain, "nice": False}, "axis": None}
    map_height = max(500, 28 + len(data["sidebar"]) * 52 + len(data["group_headers"]) * 24 + max(0, len(data["group_headers"]) - 1) * 12)
    sidebar, headers = _route_map_sidebar_layout(data["sidebar"], height=map_height)
    legend_y = map_height - 20
    # Legend uses pixel values in dedicated layers.  It must not introduce an
    # incompatible coordinate scale into the geographic road/path layers.
    legend_layers = [
        {"data": {"values": [{}]}, "mark": {"type": "rule", "stroke": "#CBD5E1", "strokeWidth": 2}, "encoding": {"x": {"value": 16}, "x2": {"value": 30}, "y": {"value": legend_y}}},
        {"data": {"values": [{}]}, "mark": {"type": "text", "align": "left", "baseline": "middle", "font": _FONT, "fontSize": 10, "color": "#475467"}, "encoding": {"x": {"value": 34}, "y": {"value": legend_y}, "text": {"value": "当前路网快照"}}},
        {"data": {"values": [{}]}, "mark": {"type": "rule", "stroke": "#2F6B8A", "strokeWidth": 3, "strokeCap": "round"}, "encoding": {"x": {"value": 126}, "x2": {"value": 142}, "y": {"value": legend_y}}},
        {"data": {"values": [{}]}, "mark": {"type": "text", "align": "left", "baseline": "middle", "font": _FONT, "fontSize": 10, "color": "#475467"}, "encoding": {"x": {"value": 146}, "y": {"value": legend_y}, "text": {"value": "本地最短路径（按 POI 类型组着色）"}}},
    ]
    origin_legend_x = 342
    legend_layers.extend([
        {"data": {"values": [{}]}, "mark": {"type": "point", "shape": "diamond", "filled": True, "size": 72, "fill": "#FFFFFF", "stroke": "#172033", "strokeWidth": 1.5}, "encoding": {"x": {"value": origin_legend_x}, "y": {"value": legend_y}}},
        {"data": {"values": [{}]}, "mark": {"type": "text", "align": "left", "baseline": "middle", "font": _FONT, "fontSize": 10, "color": "#475467"}, "encoding": {"x": {"value": origin_legend_x + 10}, "y": {"value": legend_y}, "text": {"value": "分析中心（路线起点）"}}},
    ])
    if data.get("origin_snap_offset_m") is not None:
        legend_layers.append(
            {"data": {"values": [{}]}, "mark": {"type": "text", "align": "left", "baseline": "middle", "font": _FONT, "fontSize": 10, "color": "#8B5E34"}, "encoding": {"x": {"value": 470}, "y": {"value": legend_y}, "text": {"value": f"起点吸附至路网约 {data['origin_snap_offset_m']:.0f} m"}}}
        )
    map_panel = {
        "width": 620,
        "height": map_height,
        "layer": [
            {"data": {"values": data["roads"]}, "mark": {"type": "line", "stroke": "#CBD5E1", "strokeWidth": 1.0, "strokeCap": "round", "strokeJoin": "round"}, "encoding": {"x": {"field": "x", **x}, "y": {"field": "y", **y}, "detail": {"field": "road_id", "type": "nominal"}, "order": {"field": "order", "type": "quantitative"}}},
            {"data": {"values": data["routes"]}, "mark": {"type": "line", "strokeWidth": 3.2, "strokeCap": "round", "strokeJoin": "round"}, "encoding": {"x": {"field": "x", **x}, "y": {"field": "y", **y}, "detail": {"field": "route_id", "type": "nominal"}, "order": {"field": "order", "type": "quantitative"}, "color": {"field": "route_color", "type": "nominal", "scale": None, "legend": None}}},
            {"data": {"values": data["pois"]}, "mark": {"type": "circle", "size": 430, "stroke": "#FFFFFF", "strokeWidth": 2}, "encoding": {"x": {"field": "x", **x}, "y": {"field": "y", **y}, "color": {"field": "route_color", "type": "nominal", "scale": None, "legend": None}}},
            {"data": {"values": data["pois"]}, "mark": {"type": "text", "font": _FONT, "fontSize": 11, "fontWeight": 700, "color": "#FFFFFF", "baseline": "middle"}, "encoding": {"x": {"field": "x", **x}, "y": {"field": "y", **y}, "text": {"field": "number"}}},
            {"data": {"values": [data["origin"]]}, "mark": {"type": "point", "shape": "diamond", "filled": True, "size": 220, "fill": "#FFFFFF", "stroke": "#172033", "strokeWidth": 2}, "encoding": {"x": {"field": "x", **x}, "y": {"field": "y", **y}}},
            *legend_layers,
        ],
    }
    side_x = {"type": "quantitative", "scale": {"domain": [0, 400]}, "axis": None}
    side_y = {"type": "quantitative", "scale": {"domain": [0, map_height]}, "axis": None}
    sidebar_panel = {
        "width": 400,
        "height": map_height,
        "layer": [
            {"data": {"values": sidebar}, "mark": {"type": "rect", "cornerRadius": 6, "fill": "#F8FAFC", "stroke": "#E2E8F0"}, "encoding": {"x": {"datum": 0, **side_x}, "x2": {"datum": 394}, "y": {"field": "y_top", **side_y}, "y2": {"field": "y_bottom"}}},
            {"data": {"values": headers}, "mark": {"type": "text", "align": "left", "baseline": "middle", "font": _FONT, "fontSize": 13, "fontWeight": 700, "color": "#172033"}, "encoding": {"x": {"datum": 2, **side_x}, "y": {"field": "header_y", **side_y}, "text": {"field": "group_title"}}},
            {"data": {"values": headers}, "mark": {"type": "text", "align": "right", "baseline": "middle", "font": _FONT, "fontSize": 11, "fontWeight": 700}, "encoding": {"x": {"datum": 386, **side_x}, "y": {"field": "header_y", **side_y}, "text": {"field": "role_label"}, "color": {"field": "role_color", "type": "nominal", "scale": None, "legend": None}}},
            {"data": {"values": sidebar}, "mark": {"type": "circle", "size": 270, "stroke": "#FFFFFF", "strokeWidth": 1.5}, "encoding": {"x": {"datum": 16, **side_x}, "y": {"field": "number_y", **side_y}, "color": {"field": "route_color", "type": "nominal", "scale": None, "legend": None}}},
            {"data": {"values": sidebar}, "mark": {"type": "text", "font": _FONT, "fontSize": 10, "fontWeight": 700, "color": "#FFFFFF", "baseline": "middle"}, "encoding": {"x": {"datum": 16, **side_x}, "y": {"field": "number_y", **side_y}, "text": {"field": "number"}}},
            {"data": {"values": sidebar}, "mark": {"type": "text", "align": "left", "baseline": "middle", "font": _FONT, "fontSize": 12, "fontWeight": 700, "color": "#172033"}, "encoding": {"x": {"datum": 32, **side_x}, "y": {"field": "name_y", **side_y}, "text": {"field": "name_line_1"}}},
            {"data": {"values": sidebar}, "transform": [{"filter": "datum.name_line_2 !== ''"}], "mark": {"type": "text", "align": "left", "baseline": "middle", "font": _FONT, "fontSize": 11, "color": "#475467"}, "encoding": {"x": {"datum": 32, **side_x}, "y": {"field": "name_line_2_y", **side_y}, "text": {"field": "name_line_2"}}},
            {"data": {"values": sidebar}, "mark": {"type": "text", "align": "left", "baseline": "middle", "font": _FONT, "fontSize": 10, "color": "#64748B"}, "encoding": {"x": {"datum": 32, **side_x}, "y": {"field": "meta_y", **side_y}, "text": {"field": "category"}}},
            {"data": {"values": sidebar}, "mark": {"type": "text", "align": "right", "baseline": "middle", "font": _FONT, "fontSize": 11, "fontWeight": 700}, "encoding": {"x": {"datum": 386, **side_x}, "y": {"field": "meta_y", **side_y}, "text": {"field": "route_label"}, "color": {"field": "route_color", "type": "nominal", "scale": None, "legend": None}}},
        ],
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": "当前 road_edges 快照上的重点 POI 本地最短路径与编号清单。",
        "title": {"text": FOCUSED_POI_ROUTE_MAP_TITLE, "anchor": "start", "font": _FONT, "fontSize": 20, "fontWeight": 700, "color": "#172033", "offset": 18},
        "hconcat": [map_panel, sidebar_panel],
        "spacing": 18,
        "padding": {"left": 6, "right": 6, "top": 6, "bottom": 36},
        "config": {"view": {"stroke": "#E2E8F0", "cornerRadius": 8}, "background": "#FFFFFF"},
    }


def population_supply_context_spec(
    *,
    population_year: int,
    age_values: list[dict[str, Any]],
    poi_year: int | None,
    supply_roles: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Combine resident background and verified POI supply without scoring them."""

    age = population_age_structure_spec(population_year, age_values)
    supply = poi_supply_structure_spec(supply_roles, year=poi_year)
    age.pop("$schema", None)
    supply.pop("$schema", None)
    age["title"] = {
        "text": f"人口使用背景（{population_year}）",
        "anchor": "start",
        "font": _FONT,
        "fontSize": 17,
        "fontWeight": 700,
        "color": "#172033",
        "offset": 14,
    }
    supply["title"] = {
        "text": f"周边 POI 供给（{poi_year}）" if poi_year is not None else "周边 POI 供给",
        "anchor": "start",
        "font": _FONT,
        "fontSize": 17,
        "fontWeight": 700,
        "color": "#172033",
        "offset": 14,
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": "人口居住背景与真实分类 POI 供给的并列证据，不生成综合评分。",
        "title": {
            "text": POPULATION_SUPPLY_CONTEXT_TITLE,
            "subtitle": "人口校准服务测试覆盖；POI 识别成熟供给与补充任务",
            "anchor": "start",
            "font": _FONT,
            "subtitleFont": _FONT,
            "fontSize": 22,
            "subtitleFontSize": 13,
            "fontWeight": 700,
            "color": "#172033",
            "subtitleColor": "#64748B",
            "offset": 22,
        },
        "vconcat": [age, supply],
        "spacing": 34,
        "config": {"view": {"stroke": None}, "background": "#FFFFFF"},
    }

def _route_map_sidebar_layout(rows: list[dict[str, Any]], *, height: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    values: list[dict[str, Any]] = []
    headers: list[dict[str, Any]] = []
    y = height - 14
    current_group: int | None = None
    for row in rows:
        group_index = int(row["group_index"])
        if group_index != current_group:
            if current_group is not None:
                y -= 12
            headers.append({**row, "header_y": y})
            y -= 24
            current_group = group_index
        values.append({
            **row,
            "route_label": f"{row['distance_label']} · {row['duration_label']}",
            "y_top": y,
            "y_bottom": y - 46,
            "number_y": y - 15,
            "name_y": y - 12,
            "name_line_2_y": y - 27,
            "meta_y": y - 39,
        })
        y -= 52
    return values, headers


def _valid_map_coordinate(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if -180 <= x <= 180 and -90 <= y <= 90 else None


def _line_coordinates(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [coordinate for item in value if (coordinate := _valid_map_coordinate(item)) is not None]


def _geojson_line_values(features: Any, *, feature_key: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    if not isinstance(features, list):
        return values
    for index, feature in enumerate(features):
        geometry = feature.get("geometry") if isinstance(feature, dict) and feature.get("type") == "Feature" else feature
        if not isinstance(geometry, dict):
            continue
        line_sets = [geometry.get("coordinates")] if geometry.get("type") == "LineString" else geometry.get("coordinates") if geometry.get("type") == "MultiLineString" else []
        if not isinstance(line_sets, list):
            continue
        for line_index, line in enumerate(line_sets):
            coordinates = _line_coordinates(line)
            for order, (x, y) in enumerate(coordinates):
                values.append({f"{feature_key}_id": f"{index}-{line_index}", "order": order, "x": x, "y": y})
    return values


def _geojson_boundary_lines(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    polygons = [geometry.get("coordinates")] if geometry.get("type") == "Polygon" else geometry.get("coordinates") if geometry.get("type") == "MultiPolygon" else []
    values: list[dict[str, Any]] = []
    if not isinstance(polygons, list):
        return values
    for polygon_index, polygon in enumerate(polygons):
        rings = polygon if geometry.get("type") == "Polygon" else polygon
        if not isinstance(rings, list):
            continue
        for ring_index, ring in enumerate(rings):
            coordinates = _line_coordinates(ring)
            for order, (x, y) in enumerate(coordinates):
                values.append({"boundary_id": f"{polygon_index}-{ring_index}", "order": order, "x": x, "y": y})
    return values


def _map_extent(values: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    coordinates = [(float(item["x"]), float(item["y"])) for item in values if _valid_map_coordinate((item.get("x"), item.get("y"))) is not None]
    if not coordinates:
        return None
    xs, ys = zip(*coordinates)
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    pad = max(max_x - min_x, max_y - min_y, 0.001) * 0.08
    return min_x - pad, min_y - pad, max_x + pad, max_y + pad
