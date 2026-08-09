from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List

from modules.providers.amap.utils.transform_posi import wgs84_to_gcj02
from store.analysis_artifact_repo import analysis_artifact_repo

from .schemas import PptDataSourceSummary


SYSTEM_SOURCE_DEFINITIONS = (
    ("current:scope", "data", "当前等时圈范围", "scope"),
    ("current:dataset:poi", "data", "POI 基础数据", "poi_fetch"),
    ("current:dataset:h3", "sheet", "H3 / 共享网格", "poi_h3_grid"),
    ("current:analysis:poi_h3", "sheet", "POI / H3 空间结构分析", "poi_h3_grid"),
    ("current:analysis:population", "data", "人口结构分析", "population"),
    ("current:analysis:nightlight", "data", "夜光强度分析", "nightlight"),
    ("current:analysis:road", "data", "路网与可达性分析", "road_syntax"),
)

_ARTIFACT_TYPES = {
    "h3": "poi_h3_grid",
    "population": "population",
    "nightlight": "nightlight",
    "road": "road_syntax",
}

_POLICY = "该来源已构建为 AI 输入块；生成时只发送 scope/metrics/evidence/chart specs，不发送 current 原始数据。"


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | int | None:
    if value in (None, "", [], {}):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return int(result) if result.is_integer() else result


def _first_number(*values: Any) -> float | int | None:
    for value in values:
        result = _number(value)
        if result is not None:
            return result
    return None


def _latest_artifact_payload(history_id: str, artifact_type: str) -> Dict[str, Any]:
    artifacts = analysis_artifact_repo.list(history_id, artifact_type=artifact_type)
    return _dict(_dict(artifacts[0]).get("payload")) if artifacts else {}


def _scope_payload(history: Dict[str, Any]) -> Dict[str, Any]:
    params = _dict(history.get("params"))
    polygon = _list(history.get("polygon"))
    center = _list(params.get("center"))
    if len(center) >= 2:
        try:
            lng, lat = wgs84_to_gcj02(float(center[0]), float(center[1]))
            center = [lng, lat]
        except (TypeError, ValueError):
            center = center[:2]
    mode = _text(params.get("mode")) or "walking"
    time_min = _number(params.get("time_min"))
    speed_kmh = {"walking": 5, "bicycling": 15, "driving": 30}.get(mode, 5)
    radius_m = round(speed_kmh * 1000 * float(time_min) / 60) if time_min else None
    return {
        "center": center[:2],
        "center_coord_type": "gcj02" if len(center) >= 2 else "",
        "radius_m": radius_m,
        "time_min": time_min,
        "mode": mode,
        "has_polygon": bool(polygon),
        "polygon_point_count": len(polygon),
        "has_drawn_polygon": False,
        "drawn_polygon_point_count": 0,
        "has_isochrone_feature": bool(polygon),
    }


def _scope_text(scope: Dict[str, Any]) -> str:
    parts = []
    if scope.get("time_min") is not None:
        parts.append(f"{scope['time_min']}分钟")
    if scope.get("radius_m") is not None:
        parts.append(f"{round(float(scope['radius_m']))}米")
    return " / ".join(parts) or "当前分析范围"


def _metric(
    *,
    domain: str,
    key: str,
    label: str,
    value: Any,
    unit: str,
    scope: str,
    source_id: str,
    source_ids: Iterable[str],
    source_path: str,
    calculation_method: str,
    description: str,
    ready: bool,
    details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    normalized_value = _number(value)
    result: Dict[str, Any] = {
        "metric_id": f"analysis:{domain}:{key}",
        "domain": domain,
        "label": label,
        "value": normalized_value if normalized_value is not None else None,
        "unit": unit,
        "scope": scope,
        "source_id": source_id,
        "source_ids": list(source_ids),
        "source_path": source_path,
        "calculation_method": calculation_method,
        "status": "ready" if normalized_value is not None else ("missing" if ready else "not_ready"),
        "description": description,
    }
    if details:
        result["details"] = details
        result["evidence_payload"] = details
    return result


def _quantile(values: Iterable[float], q: float) -> float:
    sorted_values = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = max(0.0, min(1.0, q)) * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = min(len(sorted_values) - 1, lower + 1)
    ratio = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * ratio


def _average(values: Iterable[Any]) -> float | None:
    finite = [float(value) for value in values if _number(value) is not None]
    return sum(finite) / len(finite) if finite else None


def _h3_derived(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    properties = [_dict(feature.get("properties")) for feature in features]
    category_keys = sorted({key for props in properties for key in _dict(props.get("category_counts"))})
    category_count = max(2, len(category_keys))
    rows = []
    for props in properties:
        poi_count = float(_number(props.get("poi_count")) or 0)
        density = float(_number(props.get("density_poi_per_km2")) or 0)
        neighbor_density = float(_number(props.get("neighbor_mean_density")) or 0)
        entropy = None
        if poi_count >= 3:
            entropy = max(0.0, min(1.0, float(_number(props.get("local_entropy")) or 0) / math.log(category_count)))
        rows.append({
            "poi_count": poi_count,
            "density": density,
            "neighbor_density": neighbor_density,
            "entropy": entropy,
            "category_counts": _dict(props.get("category_counts")),
        })
    density_p70 = _quantile((row["density"] for row in rows), 0.7)
    entropy_p70 = _quantile((row["entropy"] for row in rows if row["entropy"] is not None), 0.7)
    typing_opportunity_count = sum(
        1
        for row in rows
        if row["entropy"] is not None
        and row["density"] >= density_p70
        and row["entropy"] >= entropy_p70
        and row["density"] - row["neighbor_density"] > 0
    )
    global_counts = {
        key: sum(float(_number(row["category_counts"].get(key)) or 0) for row in rows)
        for key in category_keys
    }
    global_total = sum(global_counts.values())
    target_key = "group-7" if "group-7" in category_keys else (category_keys[0] if category_keys else "")
    lq_values = []
    alpha = 0.5
    for row in rows:
        if row["poi_count"] < 3 or not target_key:
            continue
        global_share = (global_counts[target_key] + alpha) / (global_total + alpha * category_count)
        cell_share = (float(_number(row["category_counts"].get(target_key)) or 0) + alpha) / (row["poi_count"] + alpha * category_count)
        if global_share > 0:
            lq_values.append(cell_share / global_share)
    return {
        "typing_opportunity_count": typing_opportunity_count,
        "max_lq": max(lq_values) if lq_values else None,
        "lq_opportunity_count": sum(value >= 1.2 for value in lq_values),
        "avg_neighbor_density": _average(props.get("neighbor_mean_density") for props in properties),
        "avg_neighbor_entropy": _average(props.get("neighbor_mean_entropy") for props in properties),
    }


def _age_structure(overview: Dict[str, Any]) -> Dict[str, Any] | None:
    summary = _dict(overview.get("summary"))
    total_population = _number(summary.get("total_population"))
    rows = []
    for item in _list(overview.get("age_distribution")):
        row = _dict(item)
        total = _number(row.get("total"))
        if total is None or total <= 0:
            continue
        ratio = float(f"{float(total) / float(total_population):.6f}") if total_population and total_population > 0 else None
        rows.append({
            "age_band": _text(row.get("age_band")),
            "age_band_label": _text(row.get("age_band_label")),
            "total": total,
            "ratio": ratio,
        })
    rows.sort(key=lambda item: float(item["total"]), reverse=True)
    if not rows:
        return None
    top = rows[0]
    return {
        "dominant_age_band": top["age_band"],
        "dominant_age_band_label": top["age_band_label"],
        "dominant_age_band_population": top["total"],
        "dominant_age_band_ratio": top["ratio"],
        "age_distribution_ratios": rows,
    }


def _build_metrics(
    *,
    poi_count: int,
    scope_text: str,
    h3_payload: Dict[str, Any],
    population_payload: Dict[str, Any],
    nightlight_payload: Dict[str, Any],
    road_payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    metrics.append(_metric(
        domain="poi", key="poi_count", label="POI 数量", value=poi_count, unit="个", scope=scope_text,
        source_id="current:dataset:poi", source_ids=["current:dataset:poi"], source_path="allPoisDetails.length",
        calculation_method="当前范围内已抓取 POI 明细去重计数。", description="POI 明细为空，无法形成数量指标。", ready=poi_count > 0,
    ))

    h3_summary = _dict(h3_payload.get("summary"))
    h3_features = _list(_dict(h3_payload.get("grid")).get("features"))
    h3_ready = bool(h3_payload)
    derived = _h3_derived(h3_features)
    base_h3 = (
        ("grid_count", "网格数量", "个", h3_summary.get("grid_count"), "h3AnalysisSummary.grid_count"),
        ("poi_count", "H3 POI 数量", "个", h3_summary.get("poi_count"), "h3AnalysisSummary.poi_count"),
        ("avg_density_poi_per_km2", "平均 POI 密度", "个/km²", h3_summary.get("avg_density_poi_per_km2"), "h3AnalysisSummary.avg_density_poi_per_km2"),
        ("avg_local_entropy", "平均局部熵", "", h3_summary.get("avg_local_entropy"), "h3AnalysisSummary.avg_local_entropy"),
        ("global_moran_i_density", "密度 Moran I", "", h3_summary.get("global_moran_i_density"), "h3AnalysisSummary.global_moran_i_density"),
        ("functional_mix_score", "功能混合度", "", derived["typing_opportunity_count"], "h3DerivedStats.typingSummary"),
    )
    for key, label, unit, value, source_path in base_h3:
        metrics.append(_metric(
            domain="h3", key=key, label=label, value=value, unit=unit, scope=scope_text,
            source_id="current:analysis:poi_h3", source_ids=["current:dataset:h3", "current:analysis:poi_h3"],
            source_path=source_path, calculation_method=f"{label}来自 POI H3 空间分析汇总。",
            description=(f"{label}当前结果未返回。" if h3_ready else "请先完成 POI H3 网格分析。"), ready=h3_ready,
        ))
    h3_extra = (
        ("typing_opportunity_count", "高密高混合机会格数量", "个", derived["typing_opportunity_count"], "h3DerivedStats.typingSummary.opportunityCount", "来自 H3 功能混合类型诊断，统计高密-高混合且邻域差值为正的机会格。", "当前 H3 派生结果未提供功能混合机会格。"),
        ("gi_z_stats_mean", "Gi* Z 均值", "", _dict(h3_summary.get("gi_z_stats")).get("mean"), "h3AnalysisSummary.gi_z_stats.mean", "Gi* Z 均值来自 H3 空间自相关统计。", "Gi* Z 均值当前结果未返回。"),
        ("gi_z_stats_max", "Gi* Z 峰值", "", _dict(h3_summary.get("gi_z_stats")).get("max"), "h3AnalysisSummary.gi_z_stats.max", "Gi* Z 峰值来自 H3 空间自相关统计。", "Gi* Z 峰值当前结果未返回。"),
        ("lisa_i_stats_mean", "LISA I 均值", "", _dict(h3_summary.get("lisa_i_stats")).get("mean"), "h3AnalysisSummary.lisa_i_stats.mean", "LISA I 均值来自 H3 空间自相关统计。", "LISA I 均值当前结果未返回。"),
        ("lisa_i_stats_max", "LISA I 峰值", "", _dict(h3_summary.get("lisa_i_stats")).get("max"), "h3AnalysisSummary.lisa_i_stats.max", "LISA I 峰值来自 H3 空间自相关统计。", "LISA I 峰值当前结果未返回。"),
        ("neighbor_interpolation", "邻域均值/邻域插值", "个/km²", derived["avg_neighbor_density"], "h3AnalysisGridFeatures.properties.neighbor_mean_density", "对 H3 网格属性 neighbor_mean_density 做均值汇总。", "当前 H3 汇总未提供邻域插值结果。"),
        ("neighbor_mean_entropy", "邻域平均熵", "", derived["avg_neighbor_entropy"], "h3AnalysisGridFeatures.properties.neighbor_mean_entropy", "对 H3 网格属性 neighbor_mean_entropy 做均值汇总。", "当前 H3 汇总未提供邻域熵结果。"),
        ("lq", "区位商 LQ", "", derived["max_lq"], "h3DerivedStats.lqSummary.maxLq", "来自 H3 区位商诊断，取目标业态 LQ 最大值。", "当前 H3 汇总未提供 LQ 结果。"),
        ("lq_opportunity_count", "LQ 优势格数量", "个", derived["lq_opportunity_count"], "h3DerivedStats.lqSummary.opportunityCount", "来自 H3 区位商诊断，统计目标业态 LQ >= 1.2 的优势格。", "当前 H3 派生结果未提供 LQ 优势格数量。"),
    )
    for key, label, unit, value, source_path, method, missing_description in h3_extra:
        metrics.append(_metric(
            domain="h3", key=key, label=label, value=value, unit=unit, scope=scope_text,
            source_id="current:analysis:poi_h3", source_ids=["current:analysis:poi_h3"], source_path=source_path,
            calculation_method=method, description=(missing_description if h3_ready else "请先完成 POI H3 网格分析。"), ready=h3_ready,
        ))

    population_overview = _dict(population_payload.get("overview"))
    population_summary = _dict(population_overview.get("summary") or population_payload.get("summary"))
    population_layer_summary = _dict(_dict(population_payload.get("layer")).get("summary"))
    population_ready = bool(population_payload)
    population_rows = (
        ("total_population", "总人口", "人", _first_number(population_summary.get("total_population"), population_summary.get("population_total"), population_summary.get("total")), "populationOverview.summary.total_population"),
        ("population_density", "人口密度", "人/km²", _first_number(population_layer_summary.get("average_density_per_km2"), population_layer_summary.get("population_density"), population_layer_summary.get("density"), population_summary.get("population_density"), population_summary.get("density")), "populationLayer.summary.average_density_per_km2"),
        ("male_ratio", "男性占比", "%", population_summary.get("male_ratio"), "populationOverview.summary.male_ratio"),
        ("female_ratio", "女性占比", "%", population_summary.get("female_ratio"), "populationOverview.summary.female_ratio"),
    )
    for key, label, unit, value, source_path in population_rows:
        metrics.append(_metric(
            domain="population", key=key, label=label, value=value, unit=unit, scope=scope_text,
            source_id="current:analysis:population", source_ids=["current:analysis:population"], source_path=source_path,
            calculation_method=f"{label}来自当前范围人口分析汇总。",
            description=(f"{label}当前结果未返回。" if population_ready else "请先完成人口计算。"), ready=population_ready,
        ))
    age = _age_structure(population_overview)
    age_value = float(f"{float(age['dominant_age_band_ratio']) * 100:.2f}") if age and age.get("dominant_age_band_ratio") is not None else None
    age_label = _text(age.get("dominant_age_band_label") or age.get("dominant_age_band")) if age else ""
    age_description = (
        f"已计算各年龄段占比；当前占比最高年龄段为{age_label}，占总人口 {float(age_value):.1f}%。"
        if age_value is not None else ("当前人口分析未提供年龄结构。" if population_ready else "请先完成人口计算。")
    )
    metrics.append(_metric(
        domain="population", key="age_structure", label="年龄结构", value=age_value, unit="%", scope=scope_text,
        source_id="current:analysis:population", source_ids=["current:analysis:population"], source_path="populationOverview.age_distribution",
        calculation_method="基于 populationOverview.age_distribution 计算各年龄段占总人口比例，并以占比最高年龄段作为卡片主值。",
        description=age_description, ready=population_ready, details=age,
    ))

    night_summary = {**_dict(nightlight_payload.get("summary")), **_dict(_dict(nightlight_payload.get("layer")).get("analysis"))}
    night_ready = bool(nightlight_payload)
    night_rows = (
        ("total_radiance", "夜光总辐亮", "", night_summary.get("total_radiance"), "nightlight.summary.total_radiance"),
        ("mean_radiance", "夜光均值", "", _first_number(night_summary.get("mean_radiance"), night_summary.get("mean")), "nightlight.summary.mean_radiance"),
        ("max_radiance", "夜光峰值", "", _first_number(night_summary.get("max_radiance"), night_summary.get("max")), "nightlight.summary.max_radiance"),
        ("lit_pixel_ratio", "亮光像元占比", "%", night_summary.get("lit_pixel_ratio"), "nightlight.summary.lit_pixel_ratio"),
        ("core_hotspot_count", "核心热点数", "个", night_summary.get("core_hotspot_count"), "nightlightLayer.analysis.core_hotspot_count"),
        ("hotspot_cell_ratio", "热点格占比", "%", night_summary.get("hotspot_cell_ratio"), "nightlightLayer.analysis.hotspot_cell_ratio"),
        ("peak_to_edge_ratio", "峰边比", "", night_summary.get("peak_to_edge_ratio"), "nightlightLayer.analysis.peak_to_edge_ratio"),
        ("gradient_decay", "梯度/衰减类指标", "", night_summary.get("peak_to_edge_ratio"), "nightlightLayer.analysis.peak_to_edge_ratio"),
    )
    for key, label, unit, value, source_path in night_rows:
        metrics.append(_metric(
            domain="nightlight", key=key, label=label, value=value, unit=unit, scope=scope_text,
            source_id="current:analysis:nightlight", source_ids=["current:analysis:nightlight"], source_path=source_path,
            calculation_method=("以峰值格亮度与边缘/外圈平均亮度的比值表达夜光空间衰减强弱。" if key == "gradient_decay" else f"{label}来自当前范围夜光分析汇总。"),
            description=(("梯度/衰减类指标已从峰边比读取。" if key == "gradient_decay" else f"{label}已从当前夜光分析结果读取。") if _number(value) is not None else (f"{label}当前结果未返回。" if night_ready else "请先完成夜光计算。")), ready=night_ready,
        ))

    road_summary = _dict(road_payload.get("summary"))
    road_ready = bool(road_payload)
    road_rows = (
        ("node_count", "路网节点数", "个", road_summary.get("node_count"), "roadSyntaxSummary.node_count"),
        ("edge_count", "路网边数", "条", road_summary.get("edge_count"), "roadSyntaxSummary.edge_count"),
        ("avg_connectivity", "平均连接度", "", _first_number(road_summary.get("avg_connectivity"), road_summary.get("connectivity")), "roadSyntaxSummary.avg_connectivity"),
        ("avg_control", "平均控制度", "", _first_number(road_summary.get("avg_control"), road_summary.get("control")), "roadSyntaxSummary.avg_control"),
        ("avg_depth", "平均深度值", "", _first_number(road_summary.get("avg_depth"), road_summary.get("depth")), "roadSyntaxSummary.avg_depth"),
        ("avg_choice", "平均选择度", "", _first_number(road_summary.get("avg_choice"), road_summary.get("avg_choice_local"), road_summary.get("avg_choice_global"), road_summary.get("choice")), "roadSyntaxSummary.avg_choice|avg_choice_local|avg_choice_global"),
        ("avg_integration", "平均整合度", "", _first_number(road_summary.get("avg_integration"), road_summary.get("avg_integration_local"), road_summary.get("avg_integration_global"), road_summary.get("integration"), road_summary.get("avg_closeness"), road_summary.get("avg_accessibility_global")), "roadSyntaxSummary.avg_integration|avg_integration_local|avg_integration_global"),
        ("avg_intelligibility", "平均可理解度", "", _first_number(road_summary.get("avg_intelligibility"), road_summary.get("intelligibility")), "roadSyntaxSummary.avg_intelligibility"),
    )
    for key, label, unit, value, source_path in road_rows:
        metrics.append(_metric(
            domain="road", key=key, label=label, value=value, unit=unit, scope=scope_text,
            source_id="current:analysis:road", source_ids=["current:analysis:road"], source_path=source_path,
            calculation_method=f"{label}来自当前范围路网句法分析汇总。",
            description=(f"{label}当前结果未返回。" if road_ready else "请先完成路网计算。"), ready=road_ready,
        ))
    return metrics


def _display_value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _evidence_node(
    *, source_id: str, level: str, title: str, content: str, payload: Dict[str, Any], kind: str
) -> Dict[str, Any]:
    stable_key = _text(_list(payload.get("metric_ids"))[0] if _list(payload.get("metric_ids")) else "")
    stable_key = stable_key or _text(payload.get("summary_key")) or (f"count:{payload['count']}" if payload.get("count") else "") or title
    node_id = f"{source_id}:evidence:{level}:{stable_key}".replace(" ", "-")
    locator = _text(payload.get("locator"))
    data = {
        **payload,
        "evidence_node_id": node_id,
        "source_ids": [source_id],
        "kind": kind,
        "locator": locator,
    }
    return {
        "id": node_id,
        "kind": kind,
        "run_id": "",
        "source_ids": [source_id],
        "metric_ids": list(payload.get("metric_ids") or []),
        "title": title,
        "content": content,
        "summary": content[:260],
        "data": data,
        "time_scope": {},
        "spatial_scope": {},
        "method": level,
        "quality_flags": [],
        "locator": locator,
        "citation": "",
    }


def _analysis_summary(source_id: str, payloads: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if source_id == "current:analysis:poi_h3":
        return _dict(payloads["h3"].get("summary"))
    if source_id == "current:analysis:population":
        overview = _dict(payloads["population"].get("overview"))
        return _dict(overview.get("summary") or overview)
    if source_id == "current:analysis:nightlight":
        return _dict(payloads["nightlight"].get("summary"))
    if source_id == "current:analysis:road":
        return _dict(payloads["road"].get("summary"))
    return {}


def _ai_payload(
    *, source_id: str, title: str, scope: Dict[str, Any] | None, metrics: List[Dict[str, Any]],
    evidence_nodes: List[Dict[str, Any]], excluded: List[Dict[str, Any]], metric_gaps: List[Dict[str, Any]],
) -> Dict[str, Any]:
    included = []
    if scope:
        included.append("scope")
    if metrics:
        included.append("metrics")
    if metric_gaps:
        included.append("metric_gaps")
    if evidence_nodes:
        included.append("evidence")
    return {
        "version": "ppt_ai_input_block_v1",
        "source_id": source_id,
        "sourceId": source_id,
        "title": title,
        "source_kind": "system",
        "sourceKind": "system",
        "included": included,
        "scope": scope,
        "metrics": metrics,
        "metric_gaps": metric_gaps,
        "metricGaps": metric_gaps,
        "visual_specs": [],
        "visualSpecs": [],
        "excluded": excluded,
        "counts": {"scope": 1 if scope else 0, "metrics": len(metrics), "metric_gaps": len(metric_gaps), "evidence": len(evidence_nodes), "visual_specs": 0},
        "policy": _POLICY,
        "evidence_nodes": evidence_nodes,
    }


def build_ppt_transport(payload: Dict[str, Any]) -> Dict[str, Any]:
    counts = _dict(payload.get("counts"))
    included = list(payload.get("included") or [])
    source_id = _text(payload.get("source_id"))
    source_kind = _text(payload.get("source_kind"))
    return {
        "source_id": source_id, "sourceId": source_id, "title": _text(payload.get("title")),
        "source_kind": source_kind, "sourceKind": source_kind,
        "transport_status": "ready_to_send" if included else "selected_no_payload",
        "transportStatus": "ready_to_send" if included else "selected_no_payload",
        "included": included,
        "metric_count": int(counts.get("metrics") or 0), "metricCount": int(counts.get("metrics") or 0),
        "metric_gap_count": int(counts.get("metric_gaps") or 0), "metricGapCount": int(counts.get("metric_gaps") or 0),
        "evidence_count": len(_list(payload.get("evidence_nodes"))), "evidenceCount": len(_list(payload.get("evidence_nodes"))),
        "scope_count": int(counts.get("scope") or 0), "scopeCount": int(counts.get("scope") or 0),
        "visual_spec_count": int(counts.get("visual_specs") or 0), "visualSpecCount": int(counts.get("visual_specs") or 0),
        "excluded": list(payload.get("excluded") or []), "policy": _text(payload.get("policy")), "preview": True,
    }


def build_system_ppt_sources(history_id: str, history: Dict[str, Any], poi_payload: Dict[str, Any]) -> List[PptDataSourceSummary]:
    payloads = {key: _latest_artifact_payload(history_id, artifact_type) for key, artifact_type in _ARTIFACT_TYPES.items()}
    scope = _scope_payload(history)
    poi_count = int(poi_payload.get("count") or len(_list(poi_payload.get("pois"))))
    h3_features = _list(_dict(payloads["h3"].get("grid")).get("features"))
    metrics = _build_metrics(
        poi_count=poi_count,
        scope_text=_scope_text(scope),
        h3_payload=payloads["h3"],
        population_payload=payloads["population"],
        nightlight_payload=payloads["nightlight"],
        road_payload=payloads["road"],
    )
    sources = []
    for source_id, source_type, title, task_key in SYSTEM_SOURCE_DEFINITIONS:
        ready = bool(scope.get("has_polygon")) if source_id == "current:scope" else (
            poi_count > 0 if source_id == "current:dataset:poi" else bool(payloads["h3"] if source_id in {"current:dataset:h3", "current:analysis:poi_h3"} else payloads[source_id.rsplit(":", 1)[-1]])
        )
        bound = [metric for metric in metrics if source_id in _list(metric.get("source_ids"))]
        ready_metrics = [metric for metric in bound if metric.get("status") == "ready"]
        gap_metrics = [metric for metric in bound if metric.get("status") != "ready"]
        gaps = [{
            "gap_id": f"gap-{index}", "metric_id": metric["metric_id"], "source_id": source_id,
            "needed_metric": metric["label"], "text": metric.get("description") or f"{metric['label']} 暂无可用数据。", "status": metric["status"],
        } for index, metric in enumerate(gap_metrics, start=1)]
        evidence_nodes: List[Dict[str, Any]] = []
        if ready_metrics:
            summary_metrics = ready_metrics[:8]
            content = "；".join(f"{metric['label']}={_display_value(metric['value'])}{metric.get('unit') or ''}" for metric in summary_metrics)
            evidence_nodes.append(_evidence_node(
                source_id=source_id, level="metric_summary", title="标准指标摘要", content=content,
                payload={"metric_ids": [metric["metric_id"] for metric in ready_metrics[:12]]}, kind="spatial_metric",
            ))
        if source_id == "current:dataset:poi":
            evidence_nodes.append(_evidence_node(
                source_id=source_id, level="dataset_summary", title=title,
                content=f"当前来源包含 POI {poi_count} 条。完整 POI 明细不传给 AI。",
                payload={"count": poi_count}, kind="dataset_record",
            ))
        elif source_id == "current:dataset:h3":
            evidence_nodes.append(_evidence_node(
                source_id=source_id, level="dataset_summary", title=title,
                content=f"当前来源包含 H3 网格 {len(h3_features)} 个。完整 geometry/features 不传给 AI。",
                payload={"count": len(h3_features)}, kind="dataset_record",
            ))
        elif source_id == "current:analysis:population":
            age_metric = next((metric for metric in ready_metrics if metric["metric_id"] == "analysis:population:age_structure"), None)
            if age_metric and age_metric.get("details"):
                details = _dict(age_metric.get("details"))
                evidence_nodes.append(_evidence_node(
                    source_id=source_id, level="derived_metric", title="年龄结构", content=_text(age_metric.get("description")),
                    payload={
                        "metric_id": age_metric["metric_id"], "source_path": age_metric["source_path"],
                        "calculation_method": age_metric["calculation_method"], **details,
                        "locator": "populationOverview.age_distribution", "evidence_level": "derived_metric",
                    }, kind="spatial_metric",
                ))
        analysis_summary = _analysis_summary(source_id, payloads)
        if analysis_summary:
            content = json.dumps(analysis_summary, ensure_ascii=False, separators=(",", ":"))[:700]
            evidence_nodes.append(_evidence_node(
                source_id=source_id, level="analysis_summary", title=title, content=content,
                payload={"summary_keys": list(analysis_summary)[:20]}, kind="dataset_record",
            ))
        if source_id == "current:scope":
            excluded = [{"type": "current.scope.raw_geometry", "reason": "不传完整等时圈 GeoJSON，只传范围摘要和点位数量。"}]
        elif source_id == "current:dataset:poi":
            excluded = [{"type": "current.datasets.poi.items", "reason": "不传原始 POI 列表，只传 POI 数量和轻量摘要。", "count": poi_count}]
        elif source_id == "current:dataset:h3":
            excluded = [{"type": "current.datasets.h3.features", "reason": "不传 H3 geometry/features，只传网格数量和轻量摘要。", "count": len(h3_features)}]
        else:
            feature_count = len(h3_features) if source_id == "current:analysis:poi_h3" else (
                len(_list(_dict(payloads["nightlight"].get("layer")).get("cells"))) if source_id == "current:analysis:nightlight" else 0
            )
            excluded = [{"type": f"current.analysis.{source_id.rsplit(':', 1)[-1]}", "reason": "不传完整分析明细/features，只传标准 metrics、缺口和轻量摘要。", "count": feature_count}]
        ai_payload = _ai_payload(
            source_id=source_id, title=title, scope=scope if ready and source_id == "current:scope" else None,
            metrics=ready_metrics, evidence_nodes=evidence_nodes if ready else [], excluded=excluded, metric_gaps=gaps,
        )
        if source_id == "current:scope":
            label = f"{scope['time_min']} 分钟范围" if scope.get("time_min") is not None else "已生成"
            count = 1 if ready else 0
        elif source_id == "current:dataset:poi":
            label, count = (f"POI {poi_count} 条" if poi_count else "待生成"), poi_count
        elif source_id == "current:dataset:h3":
            label, count = (f"H3 {len(h3_features)} 个网格" if h3_features else "待生成"), 1 if ready else 0
        else:
            label, count = (f"ready {len(ready_metrics)} 项 / 缺口 {len(gap_metrics)} 项" if bound else ("已生成" if ready else "待生成")), 1 if ready else 0
        meta = {
            "label": label, "sourceKind": "system", "areaId": history_id, "packageVersion": "", "package": {}, "count": count,
            "aiPayload": ai_payload, "ai_payload": ai_payload, "transport": build_ppt_transport(ai_payload),
            "taskKey": task_key, "readyMetricCount": len(ready_metrics), "gapMetricCount": len(gap_metrics), "metrics": bound[:80],
        }
        sources.append(PptDataSourceSummary(
            id=source_id, type=source_type, title=title, status="ready" if ready else "pending", summary=label,
            count=count, source_kind="system",
            evidence_count=poi_count if source_id == "current:dataset:poi" else (len(evidence_nodes) if ready else 0),
            locator_summary="当前分析范围" if source_id == "current:scope" else "",
            availability="available" if ready else "pending:analysis_not_ready", meta=meta,
        ))
    return sources
