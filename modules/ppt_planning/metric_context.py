from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any, Dict, Iterable, List, Optional

from modules.charting import save_svg

from .schemas import PptSource


RENDERABLE_FIGURE_TYPES = {"bar", "grouped_bar", "line", "radar", "histogram", "heatmap_grid"}
VISUAL_TYPES = {"figure", "diagram", "matrix", "existing_asset", "table", "metric_card"}
VISUAL_STATUSES = {"renderable", "needs_existing_asset", "needs_design_render", "missing_data"}

METRIC_ALIAS_RULES = {
    "poi:poi_count": ["poi数量", "poi总数", "兴趣点数量", "点位数量", "poi_count", "poi count"],
    "h3:grid_count": ["h3共享网格数量", "h3网格数量", "网格数量", "共享网格", "grid_count", "grid count"],
    "h3:poi_count": ["h3poi数量", "h3 poi数量", "h3兴趣点数量", "poi_count"],
    "h3:avg_density_poi_per_km2": ["平均poi密度", "poi密度", "密度", "avg_density_poi_per_km2", "density"],
    "h3:avg_local_entropy": ["平均局部熵", "局部熵", "熵", "local_entropy", "entropy"],
    "h3:functional_mix_score": ["功能混合度", "混合度", "functional_mix", "mix score"],
    "h3:neighbor_interpolation": ["邻域均值", "邻域插值", "neighbor_interpolation", "neighbor density"],
    "h3:lq": ["区位商", "lq"],
    "h3:lq_opportunity_count": ["lq优势格", "优势格数量", "lq_opportunity_count"],
    "population:total_population": ["研究范围总人口", "总人口", "人口总量", "人口规模", "消费基本盘", "total_population", "total population"],
    "population:population_density": ["人口密度", "居住密度", "活动密集度", "空间居住性", "population_density", "density"],
    "population:age_structure": ["主导年龄段占比", "主导年龄段", "年龄结构", "核心消费群体画像", "年龄段占比", "age_structure", "age structure"],
    "population:male_ratio": ["男性占比", "male_ratio"],
    "population:female_ratio": ["女性占比", "female_ratio"],
    "nightlight:total_radiance": ["夜光总辐亮", "夜光总量", "total_radiance"],
    "nightlight:mean_radiance": ["夜光均值", "平均夜光", "mean_radiance"],
    "nightlight:max_radiance": ["夜光峰值", "最高夜光", "max_radiance"],
    "nightlight:lit_pixel_ratio": ["亮光像元占比", "亮光占比", "lit_pixel_ratio"],
    "nightlight:core_hotspot_count": ["核心热点数", "夜光热点", "hotspot_count"],
    "nightlight:hotspot_cell_ratio": ["热点格占比", "hotspot_cell_ratio"],
    "nightlight:gradient_decay": ["梯度", "衰减", "峰边比", "gradient_decay"],
    "road:node_count": ["路网节点数量", "路网节点数", "节点数量", "node_count", "node count"],
    "road:edge_count": ["路网边数量", "路网边数", "边数量", "edge_count", "edge count"],
    "road:avg_connectivity": ["平均连接度", "连接度", "connectivity"],
    "road:avg_control": ["平均控制度", "控制度", "control"],
    "road:avg_depth": ["平均深度值", "深度值", "depth"],
    "road:avg_choice": ["平均选择度", "选择度", "choice"],
    "road:avg_integration": ["平均整合度", "整合度", "integration"],
    "road:avg_intelligibility": ["平均可理解度", "可理解度", "intelligibility"],
}

SUMMARY_VISUAL_HINTS = ["指标卡组", "核心指标", "关键指标", "综合指标", "指标总览", "dashboard", "summary", "overview"]
SPATIAL_ASSET_KIND_BY_SOURCE = {
    "current:scope": ["overview_map"],
    "current:dataset:poi": ["poi_map", "overview_map"],
    "current:dataset:h3": ["h3_map", "overview_map"],
    "current:analysis:poi_h3": ["h3_map", "overview_map"],
    "current:analysis:population": ["population_map", "overview_map"],
    "current:analysis:nightlight": ["nightlight_map", "overview_map"],
    "current:analysis:road": ["road_map", "overview_map"],
}
SPATIAL_COMPOSITION_TITLES = {
    "current:scope": "空间边界与基底概貌",
    "current:analysis:nightlight": "夜间活力分布与热点诊断",
    "current:analysis:population": "人口密度与客群结构诊断",
    "current:analysis:poi_h3": "POI-H3空间结构与混合度诊断",
    "current:dataset:h3": "POI-H3空间结构与混合度诊断",
    "current:analysis:road": "路网可达性与句法结构诊断",
    "current:dataset:poi": "POI分布与业态供给诊断",
}
SPATIAL_COMPOSITION_SOURCES = tuple(SPATIAL_ASSET_KIND_BY_SOURCE.keys())
SPATIAL_OVERLAY_LIMIT = 6
MAP_REQUEST_LAYER_LIMIT = 4
MAP_REQUEST_SOURCE_BY_COMPOSITION = {
    "overview": "current:scope",
    "population": "current:analysis:population",
    "nightlight": "current:analysis:nightlight",
    "h3": "current:analysis:poi_h3",
    "road": "current:analysis:road",
    "composite_nightlife": "current:analysis:nightlight",
}
MAP_REQUEST_COMPOSITION_BY_SOURCE = {
    "current:scope": "overview",
    "current:analysis:population": "population",
    "current:analysis:nightlight": "nightlight",
    "current:analysis:poi_h3": "h3",
    "current:dataset:h3": "h3",
    "current:analysis:road": "road",
}
MAP_REQUEST_LAYER_BY_SOURCE = {
    "current:analysis:population": "population_grid",
    "current:analysis:nightlight": "nightlight_grid",
    "current:analysis:poi_h3": "h3_grid",
    "current:dataset:h3": "h3_grid",
    "current:analysis:road": "road_syntax",
}
MAP_REQUEST_ALLOWED_LAYERS = {
    "scope_boundary",
    "poi_points",
    "h3_grid",
    "population_grid",
    "nightlight_grid",
    "road_syntax",
}
CARRIER_PACKAGE_SOURCE_PREFIX = "package:poi-road-carriers:"
SPATIAL_VISUAL_HINTS = [
    "地图",
    "热力",
    "热力图",
    "分布",
    "空间",
    "密度",
    "图层",
    "格网",
    "网格",
    "路网",
    "夜光",
    "人口密度",
    "h3",
    "map",
    "heatmap",
    "layer",
    "spatial",
]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, "", [], {}):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _stable_id(parts: Iterable[Any]) -> str:
    raw = json.dumps([_clean_text(item) for item in parts], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _normalize_lookup_text(value: Any) -> str:
    text = _clean_text(value).lower()
    text = text.replace("／", "/")
    text = re.sub(r"[\s\-_:/()（）【】\[\]{}，,。·|]+", "", text)
    return text


def _metric_tokens(metric: Dict[str, Any]) -> List[str]:
    tokens = [
        _clean_text(metric.get("metric_id")),
        _clean_text(metric.get("domain")),
        _clean_text(metric.get("label")),
        _clean_text(metric.get("source_path")),
        _clean_text(metric.get("description")),
    ]
    domain = _clean_text(metric.get("domain"))
    key = _clean_text(metric.get("metric_id")).split(":")
    if len(key) >= 3:
        tokens.append(key[-1])
    if domain and len(key) >= 3:
        tokens.append(f"{domain}:{key[-1]}")
    return [_normalize_lookup_text(token) for token in tokens if _normalize_lookup_text(token)]


def _visual_search_tokens(item: Dict[str, Any], data: Dict[str, Any]) -> List[str]:
    tokens = [
        _clean_text(item.get("title")),
        _clean_text(item.get("intent") or item.get("render_intent")),
        _clean_text(item.get("visual_type")),
        _clean_text(data.get("title")),
        _clean_text(data.get("intent")),
    ]
    return [_normalize_lookup_text(token) for token in tokens if _normalize_lookup_text(token)]


def _metric_alias_score(metric: Dict[str, Any], visual_tokens: List[str]) -> float:
    metric_id = _clean_text(metric.get("metric_id"))
    label = _normalize_lookup_text(metric.get("label"))
    source_path = _normalize_lookup_text(metric.get("source_path"))
    description = _normalize_lookup_text(metric.get("description"))
    metric_tokens = set(_metric_tokens(metric))
    aliases = METRIC_ALIAS_RULES.get(":".join(metric_id.split(":")[1:3]), [])
    alias_tokens = [_normalize_lookup_text(alias) for alias in aliases if _normalize_lookup_text(alias)]
    score = 0.0
    for token in visual_tokens:
        if not token:
            continue
        if token == label:
            score += 6.0
        elif token == source_path:
            score += 5.0
        elif token in metric_tokens:
            score += 4.0
        elif token in alias_tokens:
            score += 3.0
        elif any(alias and alias in token for alias in alias_tokens):
            score += 2.0
        elif any(token and token in alias for alias in alias_tokens):
            score += 1.5
        elif token in description:
            score += 1.0
    metric_id_lookup = _normalize_lookup_text(metric_id)
    if metric_id_lookup and any(token == metric_id_lookup for token in visual_tokens):
        score += 8.0
    return score


def _choose_metric_count(visual_type: str, title: str, intent: str) -> int:
    search_text = _normalize_lookup_text(" ".join([title, intent]))
    if any(hint in search_text for hint in SUMMARY_VISUAL_HINTS):
        return 4
    if visual_type == "metric_card":
        return 4 if any(token in search_text for token in ["卡组", "总览", "综合", "核心"]) else 1
    if visual_type == "table":
        return 4
    return 3


def _infer_visual_metric_ids(item: Dict[str, Any], data: Dict[str, Any], metric_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    visual_tokens = _visual_search_tokens(item, data)
    if not visual_tokens:
        return []
    source_ids = {
        _clean_text(source_id)
        for source_id in _safe_list(item.get("source_ids"))
        if _clean_text(source_id)
    }
    source_ids.update({
        _clean_text(source_id)
        for source_id in _safe_list(data.get("source_ids"))
        if _clean_text(source_id)
    })
    if not source_ids:
        return []
    candidates = []
    for metric in metric_by_id.values():
        metric_source_ids = {
            _clean_text(source_id)
            for source_id in _safe_list(metric.get("source_ids"))
            if _clean_text(source_id)
        }
        metric_source_id = _clean_text(metric.get("source_id"))
        if source_ids and not (metric_source_id in source_ids or metric_source_ids.intersection(source_ids)):
            continue
        score = _metric_alias_score(metric, visual_tokens)
        if score > 0:
            candidates.append((score, _clean_text(metric.get("metric_id")), metric))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (-item[0], _clean_text(item[2].get("label")), _clean_text(item[1])))
    limit = _choose_metric_count(_clean_text(item.get("visual_type")), _clean_text(item.get("title")), _clean_text(item.get("intent") or item.get("render_intent")))
    return [metric_id for _, metric_id, _ in candidates[:limit] if metric_id]


def _visual_source_ids(item: Dict[str, Any], data: Dict[str, Any]) -> List[str]:
    return list(dict.fromkeys(
        _clean_text(source_id)
        for source_id in [
            *_safe_list(item.get("source_ids")),
            *_safe_list(data.get("source_ids")),
        ]
        if _clean_text(source_id)
    ))


def _asset_lookup_text(asset: Dict[str, Any]) -> str:
    return _normalize_lookup_text(" ".join([
        _clean_text(asset.get("asset_id") or asset.get("assetId")),
        _clean_text(asset.get("asset_kind") or asset.get("assetKind") or asset.get("kind")),
        _clean_text(asset.get("source")),
        _clean_text(asset.get("title")),
        _clean_text(asset.get("caption")),
    ]))


def _asset_is_ready(asset: Dict[str, Any]) -> bool:
    return bool(_clean_text(asset.get("url")) or _clean_text(asset.get("data_url") or asset.get("dataUrl") or asset.get("image_url") or asset.get("imageUrl")))


def _carrier_package_source_id(source_ids: List[str]) -> str:
    for source_id in source_ids:
        cleaned = _clean_text(source_id)
        if cleaned.startswith(CARRIER_PACKAGE_SOURCE_PREFIX):
            return cleaned
    return ""


def _is_spatial_visual_request(visual_type: str, title: str, intent: str, data: Dict[str, Any]) -> bool:
    if visual_type == "existing_asset":
        return True
    text = _normalize_lookup_text(" ".join([title, intent, _clean_text(data.get("asset_kind") or data.get("assetKind"))]))
    return any(_normalize_lookup_text(hint) in text for hint in SPATIAL_VISUAL_HINTS)


def _find_existing_asset_for_visual(
    item: Dict[str, Any],
    data: Dict[str, Any],
    asset_by_id: Dict[str, Dict[str, Any]],
    *,
    visual_type: str,
    title: str,
    intent: str,
) -> Dict[str, Any]:
    explicit_asset_id = _clean_text(item.get("asset_id") or item.get("assetId") or data.get("asset_id") or data.get("assetId"))
    if explicit_asset_id and _asset_is_ready(asset_by_id.get(explicit_asset_id, {})):
        return asset_by_id[explicit_asset_id]
    source_ids = _visual_source_ids(item, data)
    if not source_ids or not _is_spatial_visual_request(visual_type, title, intent, data):
        return {}
    carrier_package_source_id = _carrier_package_source_id(source_ids)
    wanted_kinds: List[str] = []
    for source_id in source_ids:
        wanted_kinds.extend(SPATIAL_ASSET_KIND_BY_SOURCE.get(source_id, []))
    wanted_kinds = list(dict.fromkeys([_normalize_lookup_text(kind) for kind in wanted_kinds if _normalize_lookup_text(kind)]))
    if not wanted_kinds and not carrier_package_source_id:
        return {}
    visual_text = _normalize_lookup_text(" ".join([title, intent]))
    expected_compositions = {
        MAP_REQUEST_COMPOSITION_BY_SOURCE.get(source_id)
        for source_id in source_ids
        if MAP_REQUEST_COMPOSITION_BY_SOURCE.get(source_id)
    }
    if "current:analysis:nightlight" in source_ids:
        expected_compositions.add("composite_nightlife")
    candidates = []
    for asset in asset_by_id.values():
        if not _asset_is_ready(asset):
            continue
        asset_text = _asset_lookup_text(asset)
        score = 0
        asset_data = _safe_dict(asset.get("data"))
        asset_map_request = _safe_dict(asset_data.get("map_request") or asset_data.get("mapRequest"))
        asset_composition = _clean_text(asset_map_request.get("composition"))
        asset_package_source_id = _clean_text(asset_data.get("package_source_id") or asset_data.get("packageSourceId"))
        if carrier_package_source_id and asset_package_source_id == carrier_package_source_id:
            score += 14
        if carrier_package_source_id and _clean_text(asset_data.get("composition")) == "carrier_snapshot":
            score += 4
        if asset_composition and asset_composition in expected_compositions:
            score += 12
        for kind in wanted_kinds:
            if kind and kind in asset_text:
                score += 5 if kind != "overviewmap" else 1
        if visual_text and asset_text and (visual_text in asset_text or asset_text in visual_text):
            score += 2
        title_text = _normalize_lookup_text(title)
        if title_text and title_text in asset_text:
            score += 2
        if score > 0:
            candidates.append((score, _clean_text(asset.get("asset_id") or asset.get("assetId")), asset))
    if not candidates:
        return {}
    candidates.sort(key=lambda row: (-row[0], row[1]))
    return candidates[0][2]


def _display_number(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:,.1f}".rstrip("0").rstrip(".")
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _metric(
    metrics: List[Dict[str, Any]],
    *,
    source_id: str,
    domain: str,
    key: str,
    label: str,
    value: Any,
    unit: str = "",
    method: str = "",
    spatial_scope: str = "",
    time_scope: str = "",
    source_path: str = "",
    confidence: str = "high",
) -> None:
    number = _safe_float(value)
    if number is None:
        return
    metric_id = f"{domain}:{key}:{_stable_id([source_id, source_path, label])}"
    display = f"{label} {_display_number(number)}{unit}"
    metrics.append({
        "metric_id": metric_id,
        "source_id": source_id,
        "domain": domain,
        "label": label,
        "value": number,
        "unit": unit,
        "method": method,
        "calculation_method": method,
        "spatial_scope": spatial_scope,
        "scope": spatial_scope,
        "time_scope": time_scope,
        "source_path": source_path,
        "confidence": confidence,
        "status": "ready",
        "description": display,
        "display_text": display,
    })


def _normalize_analysis_metric(raw: Any) -> Optional[Dict[str, Any]]:
    item = _safe_dict(raw)
    metric_id = _clean_text(item.get("metric_id") or item.get("metricId"))
    domain = _clean_text(item.get("domain"))
    label = _clean_text(item.get("label"))
    status = _clean_text(item.get("status")) or "missing"
    if not metric_id or not domain or not label:
        return None
    value = _safe_float(item.get("value"))
    unit = _clean_text(item.get("unit"))
    method = _clean_text(item.get("calculation_method") or item.get("calculationMethod") or item.get("method"))
    scope = _clean_text(item.get("scope") or item.get("spatial_scope") or item.get("spatialScope"))
    display = f"{label} {_display_number(value)}{unit}" if status == "ready" and value is not None else label
    source_ids = [_clean_text(item) for item in _safe_list(item.get("source_ids")) if _clean_text(item)]
    source_id = _clean_text(item.get("source_id")) or (source_ids[0] if source_ids else f"current:analysis:{domain}")
    if not source_ids:
        source_ids = [source_id]
    return {
        "metric_id": metric_id,
        "source_id": source_id,
        "source_ids": source_ids,
        "domain": domain,
        "label": label,
        "value": value,
        "unit": unit,
        "method": method,
        "calculation_method": method,
        "spatial_scope": scope,
        "scope": scope,
        "time_scope": _clean_text(item.get("time_scope") or item.get("timeScope")),
        "source_path": _clean_text(item.get("source_path") or item.get("sourcePath")),
        "confidence": _clean_text(item.get("confidence")) or ("high" if status == "ready" else "low"),
        "status": status,
        "description": _clean_text(item.get("description")),
        "display_text": display,
    }


def _analysis_metric_gap(metric: Dict[str, Any], index: int) -> Dict[str, Any]:
    label = _clean_text(metric.get("label")) or _clean_text(metric.get("metric_id")) or f"指标 {index}"
    status = _clean_text(metric.get("status")) or "missing"
    description = _clean_text(metric.get("description"))
    return {
        "gap_id": f"analysis-metric-gap-{index}",
        "text": description or f"{label} 暂无可用数据。",
        "needed_metric": label,
        "source_id": _clean_text(metric.get("source_id")),
        "metric_id": _clean_text(metric.get("metric_id")),
        "status": status,
    }


def _carrier_scope(carrier: Dict[str, Any]) -> str:
    carrier_id = _clean_text(carrier.get("carrier_id") or carrier.get("carrierId"))
    label = _clean_text(carrier.get("carrier_label") or carrier.get("carrierLabel"))
    carrier_type = _clean_text(carrier.get("carrier_type") or carrier.get("carrierType"))
    if label and carrier_id:
        return f"{label} / {carrier_id}"
    if label:
        return label
    if carrier_id:
        return carrier_id
    return carrier_type or "空间载体"


def _append_carrier_package_metrics(metrics: List[Dict[str, Any]], *, source: PptSource, package: Dict[str, Any]) -> None:
    for index, raw_carrier in enumerate(_safe_list(package.get("carriers")), start=1):
        carrier = _safe_dict(raw_carrier)
        carrier_id = _clean_text(carrier.get("carrier_id") or carrier.get("carrierId")) or f"carrier_{index:02d}"
        scope = _carrier_scope(carrier)
        poi_metrics = _safe_dict(carrier.get("poi_metrics") or carrier.get("poiMetrics"))
        nightlight_metrics = _safe_dict(carrier.get("nightlight_metrics") or carrier.get("nightlightMetrics"))
        road_metrics = _safe_dict(carrier.get("road_metrics") or carrier.get("roadMetrics"))
        _metric(
            metrics,
            source_id=source.id,
            domain="carrier",
            key=f"{carrier_id}:poi_density_per_km2",
            label=f"{scope} POI 密度",
            value=poi_metrics.get("poi_density_per_km2"),
            unit="个/km²",
            method="来自空间载体资料包 poi_metrics.poi_density_per_km2。",
            spatial_scope=scope,
            source_path=f"package.carriers.{carrier_id}.poi_metrics.poi_density_per_km2",
        )
        _metric(
            metrics,
            source_id=source.id,
            domain="carrier",
            key=f"{carrier_id}:nightlight_mean_radiance",
            label=f"{scope} 夜光均值",
            value=nightlight_metrics.get("mean_radiance"),
            method="来自空间载体资料包 nightlight_metrics.mean_radiance。",
            spatial_scope=scope,
            source_path=f"package.carriers.{carrier_id}.nightlight_metrics.mean_radiance",
        )
        _metric(
            metrics,
            source_id=source.id,
            domain="carrier",
            key=f"{carrier_id}:road_choice_score",
            label=f"{scope} choice",
            value=road_metrics.get("choice_score"),
            method="来自空间载体资料包 road_metrics.choice_score。",
            spatial_scope=scope,
            source_path=f"package.carriers.{carrier_id}.road_metrics.choice_score",
        )
        _metric(
            metrics,
            source_id=source.id,
            domain="carrier",
            key=f"{carrier_id}:road_integration_score",
            label=f"{scope} integration",
            value=road_metrics.get("integration_score"),
            method="来自空间载体资料包 road_metrics.integration_score。",
            spatial_scope=scope,
            source_path=f"package.carriers.{carrier_id}.road_metrics.integration_score",
        )


def build_metric_context(*, sources: List[PptSource], source_ids: List[str], current: Dict[str, Any]) -> Dict[str, Any]:
    selected = set(source_ids or [])
    metrics: List[Dict[str, Any]] = []
    missing_metrics: List[Dict[str, Any]] = []
    normalized_sources: List[PptSource] = []
    for raw_source in sources:
        if isinstance(raw_source, PptSource):
            normalized_sources.append(raw_source)
            continue
        try:
            normalized_sources.append(PptSource.model_validate(raw_source))
        except Exception:
            continue
    for source in normalized_sources:
        if selected and source.id not in selected:
            continue
        meta = _safe_dict(source.meta)
        package = _safe_dict(meta.get("package"))
        if _safe_list(package.get("carriers")):
            _append_carrier_package_metrics(metrics, source=source, package=package)
        ai_payload = _safe_dict(meta.get("aiPayload") or meta.get("ai_payload"))
        for raw_metric in _safe_list(ai_payload.get("metrics")):
            metric = _normalize_analysis_metric(raw_metric)
            if not metric:
                continue
            metric_source_ids = set(_safe_list(metric.get("source_ids")))
            if selected and metric_source_ids and not metric_source_ids.intersection(selected):
                continue
            if _clean_text(metric.get("status")) == "ready" and _safe_float(metric.get("value")) is not None:
                metrics.append(metric)
        for raw_gap in _safe_list(ai_payload.get("metric_gaps")):
            gap_metric = _normalize_analysis_metric(raw_gap)
            if gap_metric:
                missing_metrics.append(gap_metric)
                continue
            item = _safe_dict(raw_gap)
            label = _clean_text(item.get("needed_metric") or item.get("neededMetric") or item.get("label") or item.get("metric_id"))
            if label:
                missing_metrics.append({
                    "metric_id": _clean_text(item.get("metric_id") or item.get("metricId")) or f"gap:{source.id}:{len(missing_metrics) + 1}",
                    "source_id": source.id,
                    "source_ids": [source.id],
                    "domain": _clean_text(item.get("domain")) or "gap",
                    "label": label,
                    "value": None,
                    "unit": "",
                    "status": _clean_text(item.get("status")) or "missing",
                    "description": _clean_text(item.get("text") or item.get("description")),
                })
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for metric in metrics:
        metric_id = _clean_text(metric.get("metric_id"))
        if not metric_id or metric_id in seen:
            continue
        seen.add(metric_id)
        deduped.append(metric)
    domains = sorted({metric.get("domain") for metric in deduped if metric.get("domain")})
    return {
        "version": "ppt_metric_context_v1",
        "metrics": deduped[:240],
        "missing_metrics": missing_metrics[:160],
        "metric_gaps": [_analysis_metric_gap(metric, index) for index, metric in enumerate(missing_metrics[:80], start=1)],
        "metric_count": len(deduped),
        "missing_metric_count": len(missing_metrics),
        "domains": domains,
        "policy": "Only use ready metric_id values from selected source aiPayload.metrics. If a numeric page lacks usable ready metrics, write metric_gaps instead of inventing values.",
    }


def compact_metric_context_for_llm(metric_context: Dict[str, Any], limit: int = 120) -> Dict[str, Any]:
    metrics = _safe_list(metric_context.get("metrics"))[:limit]
    return {
        "version": metric_context.get("version"),
        "metric_count": metric_context.get("metric_count", len(metrics)),
        "domains": metric_context.get("domains", []),
        "metrics": metrics,
        "metric_gaps": _safe_list(metric_context.get("metric_gaps"))[:40],
        "missing_metric_count": metric_context.get("missing_metric_count", 0),
        "policy": metric_context.get("policy"),
    }


def _normalize_claim(raw: Any, metric_by_id: Dict[str, Dict[str, Any]], index: int) -> Optional[Dict[str, Any]]:
    item = _safe_dict(raw)
    metric_id = _clean_text(item.get("metric_id") or item.get("metricId"))
    metric = metric_by_id.get(metric_id)
    if not metric or _clean_text(metric.get("status")) != "ready":
        return None
    value = _safe_float(metric.get("value"))
    if value is None:
        return None
    return {
        "claim_id": _clean_text(item.get("claim_id") or item.get("claimId")) or f"claim-{index}",
        "metric_id": metric_id,
        "text": _clean_text(item.get("text")) or _clean_text(metric.get("display_text")),
        "value": value,
        "unit": _clean_text(item.get("unit")) or _clean_text(metric.get("unit")),
        "source_id": _clean_text(item.get("source_id")) or _clean_text(metric.get("source_id")),
        "method": _clean_text(metric.get("calculation_method") or metric.get("method")),
        "calculation_method": _clean_text(metric.get("calculation_method") or metric.get("method")),
        "spatial_scope": _clean_text(item.get("spatial_scope") or item.get("spatialScope")) or _clean_text(metric.get("spatial_scope")),
        "scope": _clean_text(metric.get("scope") or metric.get("spatial_scope")),
        "source_path": _clean_text(metric.get("source_path")),
        "status": "ready",
        "usage": _clean_text(item.get("usage")) or "support_key_message",
    }


def _normalize_gaps(raw_gaps: Any) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    for index, raw in enumerate(_safe_list(raw_gaps), start=1):
        if isinstance(raw, str):
            text = _clean_text(raw)
            if text:
                gaps.append({"gap_id": f"gap-{index}", "text": text})
            continue
        item = _safe_dict(raw)
        text = _clean_text(item.get("text") or item.get("reason") or item.get("metric"))
        if text:
            gaps.append({
                "gap_id": _clean_text(item.get("gap_id") or item.get("gapId")) or f"gap-{index}",
                "text": text,
                "needed_metric": _clean_text(item.get("needed_metric") or item.get("neededMetric")),
                "source_id": _clean_text(item.get("source_id")),
            })
    return gaps


def _visual_id(item: Dict[str, Any], index: int) -> str:
    return _clean_text(
        item.get("visual_id")
        or item.get("chart_id")
        or item.get("chartId")
        or item.get("asset_id")
        or item.get("assetId")
    ) or f"visual-{index}"


def _visual_missing(base: Dict[str, Any], reason: str, **extra: Any) -> Dict[str, Any]:
    data = _safe_dict(base.get("data"))
    return {
        **base,
        **extra,
        "status": "missing_data",
        "data": {
            **data,
            "reason": reason,
        },
    }


def _normalize_source_metric_ids(item: Dict[str, Any], data: Dict[str, Any], metric_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    requested = _safe_list(item.get("source_metric_ids") or data.get("source_metric_ids"))
    ids = [
        _clean_text(metric_id)
        for metric_id in requested
        if metric_by_id.get(_clean_text(metric_id)) and _clean_text(metric_by_id[_clean_text(metric_id)].get("status")) == "ready"
    ]
    if ids:
        return list(dict.fromkeys(ids))
    row_ids = [
        _clean_text(_safe_dict(row).get("metric_id") or _safe_dict(row).get("metricId"))
        for row in _safe_list(item.get("rows") or data.get("rows"))
    ]
    return list(dict.fromkeys(
        metric_id
        for metric_id in row_ids
        if metric_by_id.get(metric_id) and _clean_text(metric_by_id[metric_id].get("status")) == "ready"
    ))


def _normalize_matrix_cells(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    cells = []
    for index, raw in enumerate(_safe_list(data.get("cells")), start=1):
        item = _safe_dict(raw)
        row = _clean_text(item.get("row") or item.get("y") or item.get("row_id") or item.get("rowId"))
        column = _clean_text(item.get("column") or item.get("x") or item.get("column_id") or item.get("columnId"))
        label = _clean_text(item.get("label") or item.get("text") or item.get("value") or item.get("diagnosis") or item.get("strategy"))
        if row and column and label:
            cells.append({
                "cell_id": _clean_text(item.get("cell_id") or item.get("cellId")) or f"cell-{index}",
                "row": row,
                "column": column,
                "label": label,
                "tone": _clean_text(item.get("tone") or item.get("status") or item.get("priority")),
            })
    return cells


def _normalize_visual(raw: Any, metric_by_id: Dict[str, Dict[str, Any]], asset_by_id: Dict[str, Dict[str, Any]], index: int) -> Optional[Dict[str, Any]]:
    item = _safe_dict(raw)
    visual_type = _clean_text(item.get("visual_type"))
    if visual_type not in VISUAL_TYPES:
        visual_id = _visual_id(item, index)
        return {
            "visual_id": visual_id,
            "visual_type": "metric_card",
            "title": _clean_text(item.get("title")) or f"可视化 {index}",
            "intent": _clean_text(item.get("intent") or item.get("render_intent")),
            "status": "missing_data",
            "source_ids": [_clean_text(source_id) for source_id in _safe_list(item.get("source_ids")) if _clean_text(source_id)],
            "data": {
                **_safe_dict(item.get("data")),
                "reason": f"{visual_type or 'unknown'} 不是支持的 visual_type，未生成数值图 fallback。",
            },
        }
    visual_id = _visual_id(item, index)
    title = _clean_text(item.get("title")) or f"可视化 {index}"
    source_ids = [_clean_text(source_id) for source_id in _safe_list(item.get("source_ids")) if _clean_text(source_id)]
    base = {
        "visual_id": visual_id,
        "visual_type": visual_type,
        "title": title,
        "intent": _clean_text(item.get("intent") or item.get("render_intent")),
        "status": _clean_text(item.get("status")) if _clean_text(item.get("status")) in VISUAL_STATUSES else "",
        "source_ids": source_ids,
        "data": _safe_dict(item.get("data")),
    }
    matched_asset = _find_existing_asset_for_visual(
        item,
        base["data"],
        asset_by_id,
        visual_type=visual_type,
        title=title,
        intent=base["intent"],
    )
    if matched_asset and visual_type == "existing_asset":
        asset_id = _clean_text(matched_asset.get("asset_id") or matched_asset.get("assetId"))
        return {
            **base,
            "visual_type": "existing_asset",
            "status": "renderable",
            "asset_kind": _clean_text(matched_asset.get("asset_kind") or matched_asset.get("assetKind") or matched_asset.get("kind")),
            "source": _clean_text(matched_asset.get("source")),
            "asset_id": asset_id,
            "caption": _clean_text(item.get("caption") or matched_asset.get("caption") or matched_asset.get("title")),
            "overlay_requirements": [_clean_text(value) for value in _safe_list(item.get("overlay_requirements") or item.get("overlayRequirements")) if _clean_text(value)],
            "asset": matched_asset,
            "source_ids": _visual_source_ids(item, base["data"]) or source_ids,
        }

    if visual_type == "diagram":
        data = _safe_dict(item.get("data"))
        steps = [_safe_dict(step) for step in _safe_list(item.get("steps") or data.get("steps"))]
        nodes = [_safe_dict(node) for node in _safe_list(item.get("nodes"))]
        links = [_safe_dict(link) for link in _safe_list(item.get("links"))]
        valid_links = [
            link for link in links
            if _clean_text(link.get("source") or link.get("from")) and _clean_text(link.get("target") or link.get("to"))
        ]
        valid_steps = [
            step for step in steps
            if _clean_text(step.get("label") or step.get("title") or step.get("name"))
        ]
        if len(valid_steps) < 3 and (len(nodes) < 2 or not valid_links):
            return _visual_missing(
                base,
                "策略路径图需要至少 3 个步骤，或至少 2 个节点并包含明确连线；未生成无意义框图。",
                diagram_kind=_clean_text(item.get("diagram_kind") or item.get("diagramKind")),
                nodes=nodes,
                groups=_safe_list(item.get("groups")),
                links=links,
                layout_hint=_clean_text(item.get("layout_hint") or item.get("layoutHint")),
                design_notes=_clean_text(item.get("design_notes") or item.get("designNotes")),
            )
        return {
            **base,
            "status": "renderable",
            "diagram_kind": _clean_text(item.get("diagram_kind") or item.get("diagramKind")),
            "steps": valid_steps,
            "nodes": nodes,
            "groups": _safe_list(item.get("groups")),
            "links": valid_links,
            "layout_hint": _clean_text(item.get("layout_hint") or item.get("layoutHint")),
            "design_notes": _clean_text(item.get("design_notes") or item.get("designNotes")),
        }

    if visual_type == "matrix":
        data = _safe_dict(item.get("data"))
        rows = [_safe_dict(row) for row in _safe_list(data.get("rows") or item.get("rows"))]
        columns = [_safe_dict(column) for column in _safe_list(data.get("columns") or item.get("columns"))]
        cells = _normalize_matrix_cells(data)
        row_labels = [_item_label(row) for row in rows if _item_label(row)]
        column_labels = [_item_label(column) for column in columns if _item_label(column)]
        if len(row_labels) < 2 or len(column_labels) < 2 or not cells:
            return _visual_missing(
                base,
                "诊断矩阵需要至少 2 个行维度、2 个列维度和带文本的单元格；未生成空彩块。",
                diagram_kind=_clean_text(item.get("matrix_kind") or item.get("matrixKind") or item.get("diagram_kind") or item.get("diagramKind")),
                rows=rows,
                columns=columns,
                cells=cells,
            )
        return {
            **base,
            "status": "renderable",
            "diagram_kind": _clean_text(item.get("matrix_kind") or item.get("matrixKind") or item.get("diagram_kind") or item.get("diagramKind")),
            "rows": rows,
            "columns": columns,
            "cells": cells,
        }

    if visual_type == "existing_asset":
        asset_id = _clean_text(item.get("asset_id") or item.get("assetId"))
        asset = asset_by_id.get(asset_id) if asset_id else {}
        asset = asset or {}
        asset_source = _clean_text(item.get("source")) or _clean_text(asset.get("source"))
        resolved_source_ids = _visual_source_ids(item, base["data"]) or source_ids
        raw_overlays = _safe_list(base["data"].get("metric_overlays") or base["data"].get("metricOverlays"))
        overlays = [
            {
                "label": _clean_text(overlay.get("label")) or _clean_text(overlay.get("metric_id") or overlay.get("metricId")),
                "value": overlay.get("value"),
                "unit": _clean_text(overlay.get("unit")),
                "metric_id": _clean_text(overlay.get("metric_id") or overlay.get("metricId")),
            }
            for overlay in [_safe_dict(raw) for raw in raw_overlays]
            if _clean_text(overlay.get("label") or overlay.get("metric_id") or overlay.get("metricId"))
        ]
        composition = _map_request_composition(resolved_source_ids, title, base["intent"])
        map_request = _safe_dict(base["data"].get("map_request") or base["data"].get("mapRequest"))
        if not asset and not map_request and composition in MAP_REQUEST_SOURCE_BY_COMPOSITION:
            map_request = _build_map_request(
                composition=composition,
                source_ids=resolved_source_ids,
                title=title,
                overlays=overlays,
                data=base["data"],
            )
        next_data = base["data"]
        carrier_package_source_id = _carrier_package_source_id(resolved_source_ids)
        if map_request:
            next_data = {
                **base["data"],
                "composition": "map_with_metric_overlays" if asset else "map_snapshot_request",
                "map_request": map_request,
            }
            next_data.pop("capture_error", None)
            next_data.pop("captureError", None)
        elif not asset and carrier_package_source_id:
            next_data = {
                **base["data"],
                "composition": "carrier_snapshot_request",
                "package_source_id": carrier_package_source_id,
                "carrier_snapshot_request": _build_carrier_snapshot_request(
                    package_source_id=carrier_package_source_id,
                    title=title,
                    data=base["data"],
                ),
            }
            next_data.pop("capture_error", None)
            next_data.pop("captureError", None)
        return {
            **base,
            "status": "renderable" if asset else "needs_existing_asset",
            "asset_kind": _clean_text(item.get("asset_kind") or item.get("assetKind") or asset.get("asset_kind") or asset.get("assetKind")),
            "source": asset_source,
            "asset_id": asset_id,
            "caption": _clean_text(item.get("caption") or asset.get("caption")),
            "overlay_requirements": [_clean_text(value) for value in _safe_list(item.get("overlay_requirements") or item.get("overlayRequirements")) if _clean_text(value)],
            "asset": asset,
            "source_ids": resolved_source_ids,
            "data": next_data,
        }

    data = _safe_dict(item.get("data"))
    figure_kind = _clean_text(item.get("figure_kind") or item.get("figureKind") or item.get("chart_type") or item.get("chartType") or data.get("figure_kind") or data.get("chart_type")) or "bar"
    columns = _safe_list(item.get("columns") or data.get("columns"))
    rows = _safe_list(item.get("rows") or data.get("rows"))
    source_metric_ids = _normalize_source_metric_ids(item, data, metric_by_id)
    if not source_metric_ids:
        source_metric_ids = _infer_visual_metric_ids(item, data, metric_by_id)
    metric_source_ids = list(dict.fromkeys(
        _clean_text(metric_by_id[metric_id].get("source_id"))
        for metric_id in source_metric_ids
        if _clean_text(metric_by_id[metric_id].get("source_id"))
    ))
    if source_metric_ids:
        rows = [
            {
                "label": metric_by_id[metric_id].get("label"),
                "value": metric_by_id[metric_id].get("value"),
                "unit": metric_by_id[metric_id].get("unit"),
                "metric_id": metric_id,
            }
            for metric_id in source_metric_ids
        ]
        columns = [{"key": "label", "label": "指标"}, {"key": "value", "label": "数值"}, {"key": "unit", "label": "单位"}]
    if not columns and rows:
        keys = []
        for row in rows:
            for key in _safe_dict(row).keys():
                if key not in keys:
                    keys.append(key)
        columns = [{"key": key, "label": key} for key in keys]

    if not source_metric_ids:
        return _visual_missing(
            base,
            "数值图、表格和指标卡必须绑定 metric_context.metrics 中的 ready metric_id；未生成无证据图。",
            visual_type=visual_type,
            source_metric_ids=[],
            source_ids=source_ids,
        )

    if not rows or not columns:
        return _visual_missing(
            base,
            "缺少可复核的 rows/columns，未生成空图表。",
            visual_type="metric_card" if visual_type == "figure" else visual_type,
            source_metric_ids=source_metric_ids,
            source_ids=list(dict.fromkeys(source_ids + metric_source_ids)),
        )

    if visual_type == "figure" and figure_kind not in RENDERABLE_FIGURE_TYPES:
        return _visual_missing(
            base,
            f"{figure_kind} 不是可渲染数值图类型，未降级成柱状图。",
            visual_type="metric_card",
            source_metric_ids=source_metric_ids,
            source_ids=list(dict.fromkeys(source_ids + metric_source_ids)),
        )

    return {
        **base,
        "status": "renderable",
        "figure_kind": "metric_table" if visual_type == "table" else figure_kind,
        "source_metric_ids": source_metric_ids,
        "source_ids": list(dict.fromkeys(source_ids + metric_source_ids)),
        "unit": _clean_text(item.get("unit")),
        "render_hint": _clean_text(item.get("render_hint") or item.get("renderHint")),
        "data": {
            **data,
            "columns": columns,
            "rows": rows,
        },
    }


def _find_ready_asset_for_source(source_id: str, asset_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    wanted_kinds = [
        _normalize_lookup_text(kind)
        for kind in SPATIAL_ASSET_KIND_BY_SOURCE.get(source_id, [])
        if _normalize_lookup_text(kind)
    ]
    if not wanted_kinds:
        return {}
    candidates = []
    for asset in asset_by_id.values():
        if not _asset_is_ready(asset):
            continue
        asset_text = _asset_lookup_text(asset)
        score = 0
        asset_data = _safe_dict(asset.get("data"))
        asset_map_request = _safe_dict(asset_data.get("map_request") or asset_data.get("mapRequest"))
        asset_composition = _clean_text(asset_map_request.get("composition"))
        expected_composition = MAP_REQUEST_COMPOSITION_BY_SOURCE.get(source_id)
        if asset_composition and (
            asset_composition == expected_composition
            or (source_id == "current:analysis:nightlight" and asset_composition == "composite_nightlife")
        ):
            score += 12
        for kind in wanted_kinds:
            if kind and kind in asset_text:
                score += 10 if kind != "overviewmap" else 1
        if score:
            candidates.append((score, _clean_text(asset.get("asset_id") or asset.get("assetId")), asset))
    if not candidates:
        return {}
    candidates.sort(key=lambda row: (-row[0], row[1]))
    return candidates[0][2]


def _spatial_source_for_visual(visual: Dict[str, Any], metric_by_id: Dict[str, Dict[str, Any]]) -> str:
    candidates = [
        _clean_text(source_id)
        for source_id in _safe_list(visual.get("source_ids"))
        if _clean_text(source_id)
    ]
    for metric_id in _safe_list(visual.get("source_metric_ids")):
        metric = metric_by_id.get(_clean_text(metric_id), {})
        source_id = _clean_text(metric.get("source_id"))
        if source_id:
            candidates.append(source_id)
        candidates.extend([
            _clean_text(item)
            for item in _safe_list(metric.get("source_ids"))
            if _clean_text(item)
        ])
    unique_candidates = list(dict.fromkeys(candidates))
    for source_id in SPATIAL_COMPOSITION_SOURCES:
        if source_id in unique_candidates:
            return source_id
    return ""


def _metric_overlay(metric: Dict[str, Any], metric_id: str) -> Dict[str, Any]:
    return {
        "label": _clean_text(metric.get("label")) or metric_id,
        "value": metric.get("value"),
        "unit": _clean_text(metric.get("unit")),
        "metric_id": metric_id,
    }


def _collect_visual_overlays(visuals: List[Dict[str, Any]], metric_by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    overlays: List[Dict[str, Any]] = []
    seen = set()
    for visual in visuals:
        for metric_id in _safe_list(visual.get("source_metric_ids")):
            metric_id = _clean_text(metric_id)
            metric = metric_by_id.get(metric_id)
            if not metric or metric_id in seen:
                continue
            seen.add(metric_id)
            overlays.append(_metric_overlay(metric, metric_id))
            if len(overlays) >= SPATIAL_OVERLAY_LIMIT:
                return overlays
    return overlays


def _metric_columns() -> List[Dict[str, str]]:
    return [{"key": "label", "label": "指标"}, {"key": "value", "label": "数值"}, {"key": "unit", "label": "单位"}]


def _metric_dashboard_from_group(source_id: str, group: List[Dict[str, Any]], overlays: List[Dict[str, Any]]) -> Dict[str, Any]:
    first = group[0]
    metric_ids = [overlay["metric_id"] for overlay in overlays if _clean_text(overlay.get("metric_id"))]
    source_ids = list(dict.fromkeys(
        source for visual in group for source in _safe_list(visual.get("source_ids")) if _clean_text(source)
    ))
    if source_id and source_id not in source_ids:
        source_ids.append(source_id)
    return {
        **first,
        "visual_id": _clean_text(first.get("visual_id")) or f"visual-spatial-dashboard-{_stable_id([source_id, *metric_ids])}",
        "visual_type": "metric_card",
        "title": SPATIAL_COMPOSITION_TITLES.get(source_id) or first.get("title") or "空间指标诊断",
        "intent": "用同源空间指标形成紧凑诊断，不拆成多张表格。",
        "status": "renderable",
        "source_metric_ids": metric_ids,
        "source_ids": source_ids,
        "figure_kind": "metric_table",
        "data": {
            **_safe_dict(first.get("data")),
            "composition": "metric_dashboard",
            "metric_overlays": overlays,
            "rows": overlays,
            "columns": _metric_columns(),
        },
    }


def _map_request_composition(source_ids: List[str], title: str, intent: str) -> str:
    unique_sources = [source_id for source_id in dict.fromkeys(source_ids) if source_id]
    text = _normalize_lookup_text(" ".join([title, intent, *unique_sources]))
    if "night" in text and ("poi" in text or "夜生活" in text or "夜间消费" in text):
        return "composite_nightlife"
    for source_id in unique_sources:
        composition = MAP_REQUEST_COMPOSITION_BY_SOURCE.get(source_id)
        if composition:
            return composition
    return ""


def _map_request_layer(layer_type: str, source_id: str, *, role: str = "analysis") -> Dict[str, Any]:
    return {
        "layer_type": layer_type,
        "source": source_id,
        "role": role,
        "required": layer_type != "scope_boundary",
    }


def _build_map_request(
    *,
    composition: str,
    source_ids: List[str],
    title: str,
    overlays: List[Dict[str, Any]],
    data: Dict[str, Any],
) -> Dict[str, Any]:
    unique_sources = [source_id for source_id in dict.fromkeys(source_ids) if source_id]
    layers = [_map_request_layer("scope_boundary", "current:scope", role="context")]
    for source_id in unique_sources:
        layer_type = MAP_REQUEST_LAYER_BY_SOURCE.get(source_id)
        if layer_type and layer_type in MAP_REQUEST_ALLOWED_LAYERS:
            layers.append(_map_request_layer(layer_type, source_id))
    if composition == "composite_nightlife" and "poi_points" not in {layer["layer_type"] for layer in layers}:
        layers.append(_map_request_layer("poi_points", "current:dataset:poi"))
    layers = layers[:MAP_REQUEST_LAYER_LIMIT]
    if composition != "overview" and not any(layer["layer_type"] != "scope_boundary" for layer in layers):
        return {}
    return {
        "version": "ppt_map_request_v1",
        "composition": composition,
        "title": title,
        "basemap": {
            "provider": _clean_text(data.get("basemap_provider") or data.get("basemapProvider")) or "amap",
            "style": _clean_text(data.get("basemap_style") or data.get("basemapStyle")) or ("dark" if composition in {"nightlight", "composite_nightlife"} else "light"),
        },
        "focus": {
            "scope_id": _clean_text(data.get("scope_id") or data.get("scopeId")),
            "bounds": _safe_dict(data.get("bounds")),
            "fit": _clean_text(data.get("fit")) or "scope",
            "padding_px": 36,
        },
        "layers": layers,
        "annotations": [
            {
                "type": "metric_overlay",
                "label": _clean_text(overlay.get("label")),
                "value": overlay.get("value"),
                "unit": _clean_text(overlay.get("unit")),
                "metric_id": _clean_text(overlay.get("metric_id") or overlay.get("metricId")),
            }
            for overlay in overlays[:SPATIAL_OVERLAY_LIMIT]
            if _clean_text(overlay.get("label"))
        ],
    }


def _build_carrier_snapshot_request(
    *,
    package_source_id: str,
    title: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "version": "ppt_carrier_snapshot_request_v1",
        "composition": "carrier_snapshot",
        "title": title,
        "package_source_id": package_source_id,
        "focus_carrier_ids": [
            _clean_text(item)
            for item in _safe_list(data.get("focus_carrier_ids") or data.get("focusCarrierIds") or data.get("carrier_ids") or data.get("carrierIds"))
            if _clean_text(item)
        ][:8],
        "extent_mode": _clean_text(data.get("extent_mode") or data.get("extentMode")) or "all",
    }


def _existing_asset_composition_from_group(
    source_id: str,
    group: List[Dict[str, Any]],
    overlays: List[Dict[str, Any]],
    asset_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    first = group[0]
    metric_ids = [overlay["metric_id"] for overlay in overlays if _clean_text(overlay.get("metric_id"))]
    source_ids = list(dict.fromkeys(
        source for visual in group for source in _safe_list(visual.get("source_ids")) if _clean_text(source)
    ))
    if source_id and source_id not in source_ids:
        source_ids.append(source_id)
    composition = _map_request_composition(source_ids, _clean_text(first.get("title")), _clean_text(first.get("intent")))
    if composition not in MAP_REQUEST_SOURCE_BY_COMPOSITION:
        return _metric_dashboard_from_group(source_id, group, overlays)
    asset = _find_ready_asset_for_source(source_id, asset_by_id)
    data = _safe_dict(first.get("data"))
    asset_id = _clean_text(asset.get("asset_id") or asset.get("assetId"))
    map_request = _build_map_request(
        composition=composition,
        source_ids=source_ids,
        title=SPATIAL_COMPOSITION_TITLES.get(source_id) or first.get("title") or "空间指标诊断",
        overlays=overlays,
        data=data,
    )
    if not map_request:
        return _metric_dashboard_from_group(source_id, group, overlays)
    return {
        **first,
        "visual_id": _clean_text(first.get("visual_id")) or f"visual-spatial-map-{_stable_id([source_id, asset_id, composition, *metric_ids])}",
        "visual_type": "existing_asset",
        "title": SPATIAL_COMPOSITION_TITLES.get(source_id) or first.get("title") or "空间指标诊断",
        "intent": "用地图位置关系解释同源指标诊断。",
        "status": "renderable" if asset_id else "needs_existing_asset",
        "asset_kind": _clean_text(asset.get("asset_kind") or asset.get("assetKind") or asset.get("kind")),
        "source": _clean_text(asset.get("source")),
        "asset_id": asset_id,
        "caption": _clean_text(asset.get("caption") or asset.get("title")),
        "overlay_requirements": [_clean_text(overlay.get("label")) for overlay in overlays if _clean_text(overlay.get("label"))],
        "asset": asset,
        "source_metric_ids": metric_ids,
        "source_ids": source_ids,
        "data": {
            **data,
            "composition": "map_with_metric_overlays" if asset_id else "map_snapshot_request",
            "metric_overlays": overlays,
            "map_request": map_request,
        },
    }


def _consolidate_spatial_visuals(
    visuals: List[Dict[str, Any]],
    metric_by_id: Dict[str, Dict[str, Any]],
    asset_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    ordered_sources: List[str] = []
    passthrough: List[Dict[str, Any]] = []
    for visual in visuals:
        visual_type = _clean_text(visual.get("visual_type"))
        if visual_type not in {"figure", "table", "metric_card"} or _clean_text(visual.get("status")) != "renderable":
            passthrough.append(visual)
            continue
        source_id = _spatial_source_for_visual(visual, metric_by_id)
        if not source_id:
            passthrough.append(visual)
            continue
        if source_id not in groups:
            groups[source_id] = []
            ordered_sources.append(source_id)
        groups[source_id].append(visual)

    consolidated = []
    consumed = {id(visual) for group in groups.values() for visual in group}
    for visual in visuals:
        if id(visual) in consumed:
            source_id = _spatial_source_for_visual(visual, metric_by_id)
            if not source_id or groups.get(source_id, [None])[0] is not visual:
                continue
            overlays = _collect_visual_overlays(groups[source_id], metric_by_id)
            if not overlays:
                consolidated.extend(groups[source_id])
                continue
            consolidated.append(_existing_asset_composition_from_group(source_id, groups[source_id], overlays, asset_by_id))
            continue
        consolidated.append(visual)
    return consolidated


def validate_visual_assets(slide_payload: Dict[str, Any], metric_context: Dict[str, Any], existing_assets: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    metric_by_id = {
        _clean_text(metric.get("metric_id")): metric
        for metric in _safe_list(metric_context.get("metrics"))
        if _clean_text(metric.get("status")) == "ready"
    }
    asset_by_id = {
        _clean_text(asset.get("asset_id") or asset.get("assetId")): _safe_dict(asset)
        for asset in _safe_list(existing_assets)
        if _clean_text(_safe_dict(asset).get("asset_id") or _safe_dict(asset).get("assetId"))
    }
    claims = [
        claim
        for index, raw in enumerate(_safe_list(slide_payload.get("metric_claims")), start=1)
        if (claim := _normalize_claim(raw, metric_by_id, index))
    ]
    visuals = [
        visual
        for index, raw in enumerate(_safe_list(slide_payload.get("visual_specs")), start=1)
        if (visual := _normalize_visual(raw, metric_by_id, asset_by_id, index))
    ]
    visuals = _consolidate_spatial_visuals(visuals, metric_by_id, asset_by_id)
    gaps = _normalize_gaps(slide_payload.get("metric_gaps"))
    requested_claims = bool(_safe_list(slide_payload.get("metric_claims")))
    requested_visuals = bool(_safe_list(slide_payload.get("visual_specs")))
    if (requested_claims and not claims) or (requested_visuals and not visuals):
        known_gap_ids = {_clean_text(gap.get("metric_id")) for gap in gaps}
        for gap in _safe_list(metric_context.get("metric_gaps"))[:6]:
            metric_id = _clean_text(gap.get("metric_id"))
            if metric_id and metric_id in known_gap_ids:
                continue
            gaps.append(gap)
    return {
        "metric_claims": claims,
        "metric_gaps": gaps,
        "visual_specs": visuals,
    }


def _column_key(column: Any) -> str:
    if isinstance(column, dict):
        return _clean_text(column.get("key") or column.get("field") or column.get("label"))
    return _clean_text(column)


def _column_label(column: Any) -> str:
    if isinstance(column, dict):
        return _clean_text(column.get("label") or column.get("key") or column.get("field"))
    return _clean_text(column)


def _item_label(item: Any, fallback: str = "") -> str:
    if isinstance(item, dict):
        return _clean_text(item.get("title") or item.get("label") or item.get("name") or item.get("id")) or fallback
    return _clean_text(item) or fallback


def _wrap_label(text: str, *, line_limit: int = 12, max_lines: int = 2) -> List[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    words = cleaned.split()
    if len(words) > 1:
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= line_limit or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
    else:
        lines = [cleaned[index:index + line_limit] for index in range(0, len(cleaned), line_limit)]
    lines = lines[:max_lines]
    if len(cleaned) > sum(len(line) for line in lines):
        lines[-1] = f"{lines[-1][:max(1, line_limit - 1)]}…"
    return lines


def _diagram_link_path(
    source_pos: Dict[str, float],
    target_pos: Dict[str, float],
    *,
    box_w: float,
    box_h: float,
) -> str:
    sx = source_pos["x"]
    sy = source_pos["y"]
    tx = target_pos["x"]
    ty = target_pos["y"]
    source_row = int(source_pos["row"])
    target_row = int(target_pos["row"])
    source_col = int(source_pos["col"])
    target_col = int(target_pos["col"])
    source_forward = bool(source_pos["forward"])
    target_forward = bool(target_pos["forward"])
    start_x = sx + (box_w if source_forward else 0)
    start_y = sy + box_h / 2
    end_x = tx if target_forward else tx + box_w
    end_y = ty + box_h / 2
    if source_row == target_row:
        mid_x = (start_x + end_x) / 2
        return f"M {start_x:.1f} {start_y:.1f} L {mid_x:.1f} {start_y:.1f} L {mid_x:.1f} {end_y:.1f} L {end_x:.1f} {end_y:.1f}"
    if source_col == target_col:
        start_y = sy + box_h
        end_y = ty
        mid_y = (start_y + end_y) / 2
        center_x = sx + box_w / 2
        return f"M {center_x:.1f} {start_y:.1f} L {center_x:.1f} {mid_y:.1f} L {center_x:.1f} {end_y:.1f}"
    gutter_x = max(start_x, end_x) + 28 if source_forward else min(start_x, end_x) - 28
    mid_y = (start_y + end_y) / 2
    return f"M {start_x:.1f} {start_y:.1f} L {gutter_x:.1f} {start_y:.1f} L {gutter_x:.1f} {mid_y:.1f} L {end_x:.1f} {mid_y:.1f} L {end_x:.1f} {end_y:.1f}"


def _diagram_svg(spec: Dict[str, Any]) -> str:
    title = html.escape(_clean_text(spec.get("title")) or "语义图")
    subtitle = html.escape(_clean_text(spec.get("intent") or spec.get("diagram_kind") or spec.get("design_notes")))
    visual_type = _clean_text(spec.get("visual_type"))
    steps = _safe_list(spec.get("steps"))[:6]
    nodes = _safe_list(spec.get("nodes"))[:10]
    links = _safe_list(spec.get("links"))[:12]
    width = 980
    height = 560
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" rx="0" fill="#f8fafc" />',
        '<rect x="24" y="24" width="932" height="512" rx="22" fill="#ffffff" stroke="#dbe3ee" />',
        f'<text x="54" y="64" font-size="24" font-weight="700" fill="#111827" font-family="sans-serif">{title}</text>',
    ]
    if subtitle:
        parts.append(f'<text x="54" y="92" font-size="13" fill="#64748b" font-family="sans-serif">{subtitle}</text>')
    palette = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#dc2626", "#0f766e"]
    if visual_type == "matrix":
        row_items = _safe_list(spec.get("rows"))
        column_items = _safe_list(spec.get("columns"))
        cells = _safe_list(spec.get("cells"))
        row_labels = [_item_label(item, f"行 {index + 1}") for index, item in enumerate(row_items)]
        col_labels = [_item_label(item, f"列 {index + 1}") for index, item in enumerate(column_items)]
        cell_by_key = {
            (_clean_text(_safe_dict(cell).get("row")), _clean_text(_safe_dict(cell).get("column"))): _safe_dict(cell)
            for cell in cells
        }
        cell_w = 720 / max(1, len(col_labels))
        cell_h = 320 / max(1, len(row_labels))
        start_x = 200
        start_y = 130
        for col_index, label in enumerate(col_labels):
            x = start_x + col_index * cell_w
            parts.append(f'<text x="{x + cell_w / 2:.1f}" y="116" text-anchor="middle" font-size="13" font-weight="700" fill="#475569" font-family="sans-serif">{html.escape(label)}</text>')
        for row_index, label in enumerate(row_labels):
            y = start_y + row_index * cell_h
            parts.append(f'<text x="54" y="{y + cell_h / 2 + 5:.1f}" font-size="13" font-weight="700" fill="#475569" font-family="sans-serif">{html.escape(label)}</text>')
            for col_index, _col in enumerate(col_labels):
                x = start_x + col_index * cell_w
                cell = cell_by_key.get((label, _col), {})
                color = palette[(row_index + col_index) % len(palette)]
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w - 8:.1f}" height="{cell_h - 8:.1f}" rx="12" fill="{color}" opacity="0.12" stroke="#e2e8f0" />')
                label_text = html.escape(_clean_text(cell.get("label"))[:22])
                if label_text:
                    parts.append(f'<text x="{x + 14:.1f}" y="{y + 30:.1f}" font-size="13" font-weight="700" fill="#111827" font-family="sans-serif">{label_text}</text>')
        parts.append("</svg>")
        return "\n".join(parts)

    items = (steps or nodes)[:6]
    if len(items) <= 4:
        box_w = 198
        box_h = 100
        gap = 30
        label_limit = 9
    else:
        box_w = 222
        box_h = 92
        gap = 52
        label_limit = 12
    top_y = 188
    row_gap = 132
    columns = min(len(items), 4) if len(items) <= 4 else 3
    total_w = columns * box_w + max(0, columns - 1) * gap
    x0 = (width - total_w) / 2
    positions: Dict[str, Dict[str, float]] = {}
    node_parts: List[str] = []
    for index, item in enumerate(items):
        if len(items) <= 4:
            row = 0
            col = index
            draw_col = col
            forward = True
        else:
            row = index // 3
            col = index % 3
            draw_col = col if row % 2 == 0 else 2 - col
            forward = row % 2 == 0
        x = x0 + draw_col * (box_w + gap)
        y = top_y + row * row_gap
        item_dict = _safe_dict(item)
        item_id = _clean_text(item_dict.get("id")) or f"node-{index + 1}"
        fallback_id = f"node-{index + 1}"
        label_lines = _wrap_label(_item_label(item, f"节点 {index + 1}"), line_limit=label_limit, max_lines=2)
        detail = html.escape(_clean_text(item_dict.get("description") or item_dict.get("role") or item_dict.get("type")))
        color = palette[index % len(palette)]
        position = {"x": x, "y": y, "row": row, "col": draw_col, "forward": 1 if forward else 0}
        positions[item_id] = position
        positions[fallback_id] = position
        node_parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{box_w}" height="{box_h}" rx="18" fill="#ffffff" stroke="#d8e1ee" stroke-width="1.4" />')
        node_parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{box_w}" height="5" rx="2.5" fill="{color}" />')
        node_parts.append(f'<circle cx="{x + 28:.1f}" cy="{y + 34:.1f}" r="11" fill="{color}" opacity="0.13" />')
        node_parts.append(f'<circle cx="{x + 28:.1f}" cy="{y + 34:.1f}" r="5.5" fill="{color}" />')
        for line_index, line in enumerate(label_lines):
            text_y = y + 30 + line_index * 20
            node_parts.append(f'<text x="{x + 48:.1f}" y="{text_y:.1f}" font-size="15" font-weight="700" fill="#111827" font-family="sans-serif">{html.escape(line)}</text>')
        if detail:
            node_parts.append(f'<text x="{x + 48:.1f}" y="{y + 76:.1f}" font-size="12" fill="#64748b" font-family="sans-serif">{detail[:28]}</text>')
    if not links and len(items) > 1:
        links = [{"source": f"node-{index}", "target": f"node-{index + 1}"} for index in range(1, min(len(items), 9))]
    link_parts: List[str] = []
    for link in links:
        link_dict = _safe_dict(link)
        source = _clean_text(link_dict.get("source") or link_dict.get("from"))
        target = _clean_text(link_dict.get("target") or link_dict.get("to"))
        if source not in positions or target not in positions:
            continue
        path = _diagram_link_path(positions[source], positions[target], box_w=box_w, box_h=box_h)
        link_parts.append(f'<path d="{path}" fill="none" stroke="#9aa8ba" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#arrow)" />')
    parts.extend(link_parts)
    parts.extend(node_parts)
    parts.insert(1, '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#9aa8ba" /></marker></defs>')
    parts.append("</svg>")
    return "\n".join(parts)


def _visual_svg(spec: Dict[str, Any]) -> str:
    title = html.escape(_clean_text(spec.get("title")) or "可视化")
    visual_type = _clean_text(spec.get("visual_type"))
    if visual_type in {"diagram", "matrix"}:
        return _diagram_svg(spec)
    figure_kind = _clean_text(spec.get("figure_kind"))
    data = _safe_dict(spec.get("data"))
    columns = _safe_list(data.get("columns"))
    rows = [_safe_dict(row) for row in _safe_list(data.get("rows"))[:40]]
    width = 980
    height = 560
    if visual_type in {"table", "metric_card"} or figure_kind == "metric_table":
        line_height = 34
        table_height = min(420, max(80, len(rows) * line_height))
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">', '<rect width="100%" height="100%" fill="#f8f6f2" />']
        parts.append(f'<text x="44" y="46" font-size="24" font-weight="700" fill="#1f2937" font-family="sans-serif">{title}</text>')
        x = 44
        y = 86
        col_width = max(110, int((width - 88) / max(1, len(columns))))
        for col_index, col in enumerate(columns):
            parts.append(f'<text x="{x + col_index * col_width}" y="{y}" font-size="13" font-weight="700" fill="#475569" font-family="sans-serif">{html.escape(_column_label(col))}</text>')
        for row_index, row in enumerate(rows):
            row_y = y + 26 + row_index * line_height
            if row_y > y + table_height:
                break
            parts.append(f'<line x1="44" y1="{row_y - 18}" x2="{width - 44}" y2="{row_y - 18}" stroke="#e5e7eb" />')
            for col_index, col in enumerate(columns):
                key = _column_key(col)
                parts.append(f'<text x="{x + col_index * col_width}" y="{row_y}" font-size="13" fill="#111827" font-family="sans-serif">{html.escape(_clean_text(row.get(key)))}</text>')
        parts.append("</svg>")
        return "\n".join(parts)

    label_key = _column_key(columns[0]) if columns else "label"
    numeric_keys = [_column_key(col) for col in columns[1:] if _column_key(col)]
    if not numeric_keys:
        numeric_keys = ["value"]
    labels = [_clean_text(row.get(label_key) or row.get("label") or row.get("name") or f"项 {idx + 1}") for idx, row in enumerate(rows)]
    values = [[_safe_float(row.get(key)) or 0.0 for row in rows] for key in numeric_keys[:5]]
    max_value = max([max(series) for series in values if series] or [1.0])
    max_value = max(max_value, 1.0)
    plot_left, plot_top, plot_width, plot_height = 80, 86, 840, 350
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">', '<rect width="100%" height="100%" fill="#f8f6f2" />']
    parts.append(f'<text x="44" y="46" font-size="24" font-weight="700" fill="#1f2937" font-family="sans-serif">{title}</text>')
    parts.append(f'<line x1="{plot_left}" y1="{plot_top + plot_height}" x2="{plot_left + plot_width}" y2="{plot_top + plot_height}" stroke="#334155" />')
    parts.append(f'<line x1="{plot_left}" y1="{plot_top}" x2="{plot_left}" y2="{plot_top + plot_height}" stroke="#334155" />')
    colors = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed"]
    if figure_kind in {"line", "radar"}:
        for series_index, series in enumerate(values):
            points = []
            for idx, value in enumerate(series):
                x = plot_left + (plot_width * idx / max(1, len(series) - 1))
                y = plot_top + plot_height - (value / max_value) * plot_height
                points.append(f"{x:.1f},{y:.1f}")
            parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[series_index % len(colors)]}" stroke-width="3" />')
    else:
        group_width = plot_width / max(1, len(rows))
        bar_width = group_width / max(1, len(values)) * 0.7
        for row_index, _row in enumerate(rows):
            for series_index, series in enumerate(values):
                value = series[row_index] if row_index < len(series) else 0
                bar_height = (value / max_value) * plot_height
                x = plot_left + row_index * group_width + series_index * bar_width + 4
                y = plot_top + plot_height - bar_height
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{colors[series_index % len(colors)]}" />')
    for idx, label in enumerate(labels[:18]):
        x = plot_left + (idx + 0.5) * (plot_width / max(1, len(rows)))
        parts.append(f'<text x="{x:.1f}" y="{plot_top + plot_height + 34}" text-anchor="end" font-size="11" fill="#475569" font-family="sans-serif" transform="rotate(-30 {x:.1f} {plot_top + plot_height + 34})">{html.escape(label)}</text>')
    for idx, key in enumerate(numeric_keys[:5]):
        parts.append(f'<rect x="{plot_left + idx * 150}" y="510" width="12" height="12" fill="{colors[idx % len(colors)]}" />')
        parts.append(f'<text x="{plot_left + idx * 150 + 18}" y="521" font-size="12" fill="#475569" font-family="sans-serif">{html.escape(key)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def render_visual_artifacts(visual_specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    for spec in visual_specs:
        if _clean_text(spec.get("status")) != "renderable":
            continue
        if _clean_text(spec.get("visual_type")) == "existing_asset":
            asset = _safe_dict(spec.get("asset"))
            url = _clean_text(asset.get("url") or spec.get("url"))
            data_url = _clean_text(asset.get("data_url") or asset.get("dataUrl") or asset.get("image_url") or asset.get("imageUrl"))
            if not (url or data_url):
                continue
            asset_id = _clean_text(spec.get("asset_id") or asset.get("asset_id") or asset.get("assetId"))
            artifacts.append({
                "visual_id": spec.get("visual_id") or asset_id,
                "visual_type": "existing_asset",
                "asset_id": asset_id,
                "asset_kind": spec.get("asset_kind") or asset.get("asset_kind") or asset.get("assetKind"),
                "format": "image",
                "filename": _clean_text(asset.get("filename")),
                "url": url or data_url,
                "source_visual_id": asset_id,
                "caption": _clean_text(spec.get("caption") or asset.get("caption") or asset.get("title")),
                "data": {
                    "map_request": _safe_dict(_safe_dict(spec.get("data")).get("map_request") or _safe_dict(asset.get("data")).get("map_request")),
                    "carrier_snapshot_request": _safe_dict(_safe_dict(spec.get("data")).get("carrier_snapshot_request") or _safe_dict(asset.get("data")).get("carrier_snapshot_request")),
                    "package_source_id": _clean_text(_safe_dict(spec.get("data")).get("package_source_id") or _safe_dict(asset.get("data")).get("package_source_id")),
                    "composition": _clean_text(_safe_dict(spec.get("data")).get("composition")),
                },
            })
            continue
        if _clean_text(spec.get("visual_type")) not in {"figure", "table", "metric_card", "diagram", "matrix"}:
            continue
        svg = _visual_svg(spec)
        visual_id, filename = save_svg(svg)
        artifacts.append({
            "visual_id": spec.get("visual_id") or visual_id,
            "visual_type": spec.get("visual_type"),
            "format": "svg",
            "filename": filename,
            "url": f"/download/{filename}",
            "source_visual_id": visual_id,
        })
    return artifacts
