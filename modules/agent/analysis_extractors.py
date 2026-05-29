from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, List, Tuple

from .schemas import AnalysisSnapshot


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int | None = None) -> int | None:
    number = _to_float(value, None)
    if number is None:
        return default
    return int(round(number))


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def _current_frontend_analysis(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    from_artifacts = artifacts.get("current_frontend_analysis")
    if isinstance(from_artifacts, dict):
        return dict(from_artifacts)
    return _safe_dict(snapshot.frontend_analysis)


def _current_frontend_panel(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], key: str) -> Dict[str, Any]:
    frontend_analysis = _current_frontend_analysis(snapshot, artifacts)
    return _safe_dict(frontend_analysis.get(key))


def _current_summary(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], key: str) -> Dict[str, Any]:
    artifact_key = f"current_{key}_summary"
    artifact = artifacts.get(artifact_key)
    if isinstance(artifact, dict):
        return dict(artifact)
    source = getattr(snapshot, key, {})
    return _safe_dict(_safe_dict(source).get("summary"))


def _current_payload(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], key: str) -> Dict[str, Any]:
    artifact_key = f"current_{key}"
    artifact = artifacts.get(artifact_key)
    if isinstance(artifact, dict):
        return dict(artifact)
    return _safe_dict(getattr(snapshot, key, {}))


def _with_analysis_status(payload: Dict[str, Any], *, ready: bool) -> Dict[str, Any]:
    result = dict(payload or {})
    result["data_status"] = "ready" if ready else "empty"
    result["evidence_ready"] = bool(ready)
    return result


def is_poi_structure_ready(payload: Dict[str, Any] | None) -> bool:
    item = _safe_dict(payload)
    if "evidence_ready" in item:
        return bool(item.get("evidence_ready"))
    return bool(_safe_list(item.get("top_categories")) or _safe_list(item.get("dominant_categories")))


def is_h3_structure_ready(payload: Dict[str, Any] | None) -> bool:
    item = _safe_dict(payload)
    if "evidence_ready" in item:
        return bool(item.get("evidence_ready"))
    pattern = str(item.get("distribution_pattern") or "").strip().lower()
    return (
        pattern not in {"", "weak_signal"}
        or
        (_to_int(item.get("structure_signal_count"), 0) or 0) > 0
        or (_to_int(item.get("opportunity_count"), 0) or 0) > 0
        or bool(_safe_list(item.get("structure_rows")))
        or bool(_safe_list(item.get("gap_rows")))
    )


def is_road_pattern_ready(payload: Dict[str, Any] | None) -> bool:
    item = _safe_dict(payload)
    if "evidence_ready" in item:
        return bool(item.get("evidence_ready"))
    return (
        (_to_int(item.get("node_count"), 0) or 0) > 0
        or (_to_int(item.get("edge_count"), 0) or 0) > 0
        or item.get("regression_r2") is not None
    )


def is_population_profile_ready(payload: Dict[str, Any] | None) -> bool:
    item = _safe_dict(payload)
    if "evidence_ready" in item:
        return bool(item.get("evidence_ready"))
    return item.get("total_population") is not None or bool(str(item.get("top_age_band") or "").strip())


def is_nightlight_pattern_ready(payload: Dict[str, Any] | None) -> bool:
    item = _safe_dict(payload)
    if "evidence_ready" in item:
        return bool(item.get("evidence_ready"))
    return (
        item.get("total_radiance") is not None
        or item.get("peak_radiance") is not None
        or (_to_int(item.get("core_hotspot_count"), 0) or 0) > 0
    )


def is_business_profile_ready(payload: Dict[str, Any] | None) -> bool:
    item = _safe_dict(payload)
    return bool(str(item.get("business_profile") or "").strip() or str(item.get("portrait") or "").strip())


def is_commercial_hotspots_ready(payload: Dict[str, Any] | None) -> bool:
    item = _safe_dict(payload)
    return (
        (_to_int(item.get("core_zone_count"), 0) or 0) > 0
        or (_to_int(item.get("opportunity_zone_count"), 0) or 0) > 0
        or bool(_safe_list(item.get("zone_rows")))
    )


def is_target_supply_gap_ready(payload: Dict[str, Any] | None) -> bool:
    item = _safe_dict(payload)
    if "evidence_ready" in item:
        return bool(item.get("evidence_ready"))
    gap_mode = str(item.get("gap_mode") or "").strip().lower()
    return bool(_safe_list(item.get("candidate_zones")) or _safe_list(item.get("gap_zones"))) or gap_mode in {"overall_shortage", "spatial_mismatch"}


def _current_poi_h3_grid(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    artifact_grid = artifacts.get("current_poi_h3_grid")
    if isinstance(artifact_grid, dict):
        return dict(artifact_grid)
    poi_h3_payload = artifacts.get("current_poi_h3")
    if isinstance(poi_h3_payload, dict) and isinstance(poi_h3_payload.get("grid"), dict):
        return dict(poi_h3_payload.get("grid") or {})
    h3_payload = getattr(snapshot, "h3", {})
    if isinstance(h3_payload, dict) and isinstance(h3_payload.get("grid"), dict):
        return dict(h3_payload.get("grid") or {})
    return {}


def _feature_center_point(feature: Dict[str, Any]) -> Dict[str, float] | None:
    geometry = _safe_dict(feature.get("geometry"))
    if str(geometry.get("type") or "").strip() != "Polygon":
        return None
    coordinates = _safe_list(geometry.get("coordinates"))
    if not coordinates:
        return None
    ring = _safe_list(coordinates[0])
    points: List[Tuple[float, float]] = []
    for item in ring:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        lng = _to_float(item[0], None)
        lat = _to_float(item[1], None)
        if lng is None or lat is None:
            continue
        points.append((lng, lat))
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]
    if not points:
        return None
    avg_lng = sum(item[0] for item in points) / len(points)
    avg_lat = sum(item[1] for item in points) / len(points)
    return {"lng": round(avg_lng, 6), "lat": round(avg_lat, 6)}


def _haversine_m(point_a: Tuple[float, float] | None, point_b: Tuple[float, float] | None) -> float:
    if not point_a or not point_b:
        return float("inf")
    lng1, lat1 = point_a
    lng2, lat2 = point_b
    lng1, lat1, lng2, lat2 = map(radians, (lng1, lat1, lng2, lat2))
    dlng = lng2 - lng1
    dlat = lat2 - lat1
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6371000.0 * asin(sqrt(value))


def _current_points(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
    source = artifacts.get("current_pois")
    if isinstance(source, list):
        return [item for item in source if isinstance(item, dict)]
    return [item for item in (snapshot.pois or []) if isinstance(item, dict)]


def _nearby_landmarks(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], center_point: Dict[str, float] | None) -> List[Dict[str, Any]]:
    if not center_point:
        return []
    center = (_to_float(center_point.get("lng"), None), _to_float(center_point.get("lat"), None))
    if center[0] is None or center[1] is None:
        return []
    nearby: List[Dict[str, Any]] = []
    for point in _current_points(snapshot, artifacts):
        lng = _to_float(point.get("lng"), None)
        lat = _to_float(point.get("lat"), None)
        if lng is None or lat is None:
            continue
        distance = _haversine_m((lng, lat), center)
        if distance == float("inf"):
            continue
        nearby.append(
            {
                "name": str(point.get("name") or "").strip(),
                "distance": distance,
                "lines": _safe_list(point.get("lines")),
                "type": str(point.get("type") or "").strip(),
            }
        )
    nearby.sort(key=lambda item: item["distance"])
    filtered = [item for item in nearby if item.get("name")]
    if filtered:
        return filtered[:3]
    try:
        from modules.providers.amap.get_around_place import get_around_place

        around = get_around_place(
            center={"lng": center[0], "lat": center[1]},
            radius=350,
            types="",
            keywords="",
            point_type="poi",
        )
    except Exception:
        return []
    fallback_points: List[Dict[str, Any]] = []
    for item in around[:3]:
        lng = _to_float(item.get("lng"), None)
        lat = _to_float(item.get("lat"), None)
        if lng is None or lat is None:
            continue
        fallback_points.append(
            {
                "name": str(item.get("name") or "").strip(),
                "distance": _haversine_m((lng, lat), center),
                "lines": _safe_list(item.get("lines")),
                "type": str(item.get("type") or "").strip(),
            }
        )
    return [item for item in fallback_points if item.get("name")][:3]


def _band_metric(
    value: float | None,
    *,
    strong_at: float,
    moderate_at: float,
    reverse: bool = False,
) -> str:
    if value is None:
        return "unknown"
    if reverse:
        if value <= strong_at:
            return "strong"
        if value <= moderate_at:
            return "moderate"
        return "weak"
    if value >= strong_at:
        return "strong"
    if value >= moderate_at:
        return "moderate"
    return "weak"


def _combine_signal(signals: List[str]) -> str:
    filtered = [item for item in signals if item in {"strong", "moderate", "weak"}]
    if not filtered:
        return "unknown"
    score = 0
    for item in filtered:
        if item == "strong":
            score += 1
        elif item == "weak":
            score -= 1
    if score >= 1:
        return "strong"
    if score <= -1:
        return "weak"
    return "moderate"


def _format_approx_address(*, label: str, h3_id: str, center_point: Dict[str, float] | None, nearby: List[Dict[str, Any]]) -> str:
    if nearby:
        primary = nearby[0]
        road_hint = ""
        lines = [str(item).strip() for item in _safe_list(primary.get("lines")) if str(item).strip()]
        if lines:
            road_hint = f"{lines[0]}附近"
        elif primary.get("distance") is not None:
            road_hint = f"{int(round(float(primary['distance'])))}米内"
        name = str(primary.get("name") or "").strip()
        if name and road_hint:
            return f"{name}{road_hint}"
        if name:
            return f"{name}周边"
    if center_point:
        lng = _to_float(center_point.get("lng"), None)
        lat = _to_float(center_point.get("lat"), None)
        if lng is not None and lat is not None:
            return f"{label or '候选格'}（{h3_id[:5]}...，{lng:.5f},{lat:.5f}）"
    return f"{label or '候选格'}（H3格 {h3_id[:5]}...）" if h3_id else (label or "候选格")


def _build_candidate_reason(*, gap_score: float | None, demand_pct: float | None, supply_pct: float | None) -> str:
    parts: List[str] = []
    if gap_score is not None:
        parts.append(f"缺口分 {gap_score:.2f}")
    if demand_pct is not None:
        parts.append(f"需求分位 {_format_ratio(demand_pct)}")
    if supply_pct is not None:
        parts.append(f"供给分位 {_format_ratio(supply_pct)}")
    return "，".join(parts) if parts else "当前以 H3 gap 结构为主做方向性判断"


def _target_candidate_zones(
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    gap_zones: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    features = _safe_list(_current_poi_h3_grid(snapshot, artifacts).get("features"))
    feature_lookup = {}
    for feature in features:
        props = _safe_dict(_safe_dict(feature).get("properties"))
        h3_id = str(props.get("h3_id") or "").strip()
        if h3_id:
            feature_lookup[h3_id] = feature
    candidate_zones: List[Dict[str, Any]] = []
    for index, zone in enumerate(gap_zones[:5]):
        h3_id = str(zone.get("h3_id") or "").strip()
        label = str(zone.get("label") or "").strip() or "候选格"
        center_point = _feature_center_point(feature_lookup.get(h3_id) or {}) if h3_id else None
        nearby = _nearby_landmarks(snapshot, artifacts, center_point)
        gap_score = _to_float(zone.get("gap_score"), None)
        demand_pct = _to_float(zone.get("demand_pct"), None)
        supply_pct = _to_float(zone.get("supply_pct"), None)
        approx_address = _format_approx_address(label=label, h3_id=h3_id, center_point=center_point, nearby=nearby)
        candidate_zones.append(
            {
                "rank": index + 1,
                "h3_id": h3_id,
                "label": label,
                "gap_score": gap_score,
                "demand_pct": demand_pct,
                "supply_pct": supply_pct,
                "center_point": center_point or {},
                "approx_address": approx_address,
                "display_title": f"候选{index + 1}：{approx_address}",
                "reason_summary": _build_candidate_reason(
                    gap_score=gap_score,
                    demand_pct=demand_pct,
                    supply_pct=supply_pct,
                ),
            }
        )
    return candidate_zones


def _top_category_pairs(category_stats: Dict[str, Any], *, fallback_total: int = 0) -> List[Dict[str, Any]]:
    labels = [str(item).strip() for item in (_safe_list(category_stats.get("labels")) or [])]
    raw_values = _safe_list(category_stats.get("values"))
    pairs: List[Dict[str, Any]] = []
    values: List[float] = []
    for item in raw_values:
        values.append(_to_float(item, 0.0) or 0.0)
    total = sum(value for value in values if value > 0)
    if total <= 0 and fallback_total > 0:
        total = float(fallback_total)
    for index, label in enumerate(labels):
        if not label:
            continue
        count = values[index] if index < len(values) else 0.0
        if count <= 0:
            continue
        ratio = (count / total) if total > 0 else 0.0
        pairs.append({"label": label, "count": int(round(count)), "ratio": round(ratio, 4)})
    pairs.sort(key=lambda item: item["count"], reverse=True)
    return pairs


def build_poi_structure_analysis(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    panel = _current_frontend_panel(snapshot, artifacts, "poi")
    poi_summary = artifacts.get("current_poi_summary") if isinstance(artifacts.get("current_poi_summary"), dict) else snapshot.poi_summary
    poi_summary = _safe_dict(poi_summary)
    pairs = _top_category_pairs(_safe_dict(panel.get("category_stats")), fallback_total=_to_int(poi_summary.get("total"), 0) or 0)
    ratio_by_label = {str(item["label"]): float(item["ratio"]) for item in pairs}
    dining_ratio = ratio_by_label.get("餐饮", 0.0)
    shopping_ratio = ratio_by_label.get("购物", 0.0)
    lodging_ratio = ratio_by_label.get("住宿", 0.0)
    office_ratio = ratio_by_label.get("公司", 0.0) + ratio_by_label.get("商务住宅", 0.0)
    culture_ratio = ratio_by_label.get("科教文化", 0.0)
    structure_tags: List[str] = []
    if dining_ratio >= 0.28:
        structure_tags.append("餐饮主导")
    if shopping_ratio >= 0.15:
        structure_tags.append("购物配套较强")
    if lodging_ratio >= 0.08:
        structure_tags.append("住宿承接明显")
    if office_ratio >= 0.1:
        structure_tags.append("商务功能参与")
    if culture_ratio >= 0.08:
        structure_tags.append("科教文化配套明显")
    if dining_ratio + shopping_ratio >= 0.45:
        structure_tags.append("生活消费主导")
    dominant_categories = [str(item["label"]) for item in pairs[:3]]
    top_category_text = "、".join(
        f"{item['label']} {_format_ratio(float(item['ratio']))}"
        for item in pairs[:3]
    ) or "暂无稳定类别分布"
    summary_text = (
        f"当前 POI 结构以 {top_category_text} 为主。"
        if pairs
        else "当前缺少可直接利用的 POI 类别结构结果。"
    )
    payload = {
        "top_categories": pairs[:8],
        "dominant_categories": dominant_categories,
        "dining_ratio": round(dining_ratio, 4),
        "shopping_ratio": round(shopping_ratio, 4),
        "lodging_ratio": round(lodging_ratio, 4),
        "office_ratio": round(office_ratio, 4),
        "culture_ratio": round(culture_ratio, 4),
        "structure_tags": structure_tags,
        "summary_text": summary_text,
    }
    return _with_analysis_status(payload, ready=bool(pairs or dominant_categories))


def build_h3_structure_analysis(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    h3_panel = _current_frontend_panel(snapshot, artifacts, "h3")
    derived = _safe_dict(h3_panel.get("derived_stats"))
    structure_summary = _safe_dict(derived.get("structureSummary"))
    typing_summary = _safe_dict(derived.get("typingSummary"))
    gap_summary = _safe_dict(derived.get("gapSummary"))
    top_cells = _safe_dict(derived.get("topCells"))
    structure_rows = _safe_list(structure_summary.get("rows"))
    signal_count = sum(1 for row in structure_rows if _safe_dict(row).get("is_structure_signal"))
    if signal_count <= 0:
        signal_count = len(structure_rows)
    hotspot_count = sum(
        1
        for row in _safe_list(typing_summary.get("rows"))
        if _safe_dict(row).get("is_opportunity")
    )
    if hotspot_count <= 0:
        hotspot_count = _to_int(typing_summary.get("opportunityCount"), 0) or 0
    opportunity_count = _to_int(gap_summary.get("opportunityCount"), None)
    if opportunity_count is None:
        opportunity_count = _to_int(typing_summary.get("opportunityCount"), 0) or 0
    typing_recommendation = str(typing_summary.get("recommendation") or "").strip()
    gap_recommendation = str(gap_summary.get("recommendation") or "").strip()
    recommendation_text = f"{typing_recommendation} {gap_recommendation}".strip()

    if signal_count <= 0 and opportunity_count <= 0:
        distribution_pattern = "weak_signal"
    elif signal_count >= 5 or opportunity_count >= 3:
        distribution_pattern = "multi_core"
    elif signal_count >= 1:
        distribution_pattern = "single_core"
    else:
        distribution_pattern = "dispersed"

    summary_text = (
        f"H3 结构表现为 {distribution_pattern}，结构信号 {signal_count} 个，机会区 {opportunity_count} 个。"
        if structure_summary or typing_summary or gap_summary
        else "当前缺少可直接利用的 H3 结构化诊断结果。"
    )
    payload = {
        "distribution_pattern": distribution_pattern,
        "structure_signal_count": signal_count,
        "hotspot_count": hotspot_count,
        "opportunity_count": opportunity_count,
        "gi_stats": _safe_dict(structure_summary.get("giZStats")),
        "lisa_stats": _safe_dict(structure_summary.get("lisaIStats")),
        "typing_recommendation": typing_recommendation,
        "gap_recommendation": gap_recommendation,
        "summary_text": summary_text,
        "top_cells": top_cells,
        "structure_rows": structure_rows[:10],
        "gap_rows": _safe_list(gap_summary.get("rows"))[:10],
        "target_category": str(h3_panel.get("target_category") or "").strip(),
        "target_category_label": str(h3_panel.get("target_category_label") or "").strip(),
    }
    return _with_analysis_status(payload, ready=is_h3_structure_ready(payload))


def build_road_pattern_analysis(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    road_panel = _current_frontend_panel(snapshot, artifacts, "road")
    road_summary = _current_summary(snapshot, artifacts, "road")
    node_count = _to_int(road_summary.get("node_count"), 0) or 0
    edge_count = _to_int(road_summary.get("edge_count"), 0) or 0
    regression = _safe_dict(road_panel.get("regression"))
    regression_r2 = _to_float(regression.get("r2"), None)
    metric = str(road_panel.get("metric") or "").strip()
    main_tab = str(road_panel.get("main_tab") or "").strip()
    avg_connectivity = _to_float(road_summary.get("avg_connectivity"), None)
    avg_control = _to_float(road_summary.get("avg_control"), None)
    avg_depth = _to_float(road_summary.get("avg_depth"), None)
    avg_choice_global = _to_float(road_summary.get("avg_choice_global"), None)
    avg_choice_local = _to_float(road_summary.get("avg_choice_local"), None)
    avg_integration_global = _to_float(road_summary.get("avg_integration_global"), None)
    avg_integration_local = _to_float(road_summary.get("avg_integration_local"), None)
    avg_intelligibility = _to_float(road_summary.get("avg_intelligibility"), None)
    avg_intelligibility_r2 = _to_float(
        road_summary.get("avg_intelligibility_r2"),
        regression_r2,
    )
    road_orientation_analysis = _safe_dict(road_summary.get("road_orientation_analysis"))
    default_radius_label = str(road_summary.get("default_radius_label") or "").strip()
    radius_labels = [str(item).strip() for item in _safe_list(road_summary.get("radius_labels")) if str(item).strip()]
    connectivity_signal = _combine_signal(
        [
            _band_metric(avg_connectivity, strong_at=3.5, moderate_at=2.5),
            _band_metric(avg_control, strong_at=1.2, moderate_at=0.8),
        ]
    )
    access_signal = _combine_signal(
        [
            _band_metric(avg_depth, strong_at=4.0, moderate_at=6.0, reverse=True),
            _band_metric(avg_choice_local, strong_at=0.015, moderate_at=0.005),
            _band_metric(avg_choice_global, strong_at=0.015, moderate_at=0.005),
            _band_metric(avg_integration_local, strong_at=1.2, moderate_at=0.8),
            _band_metric(avg_integration_global, strong_at=1.2, moderate_at=0.8),
        ]
    )
    readability_signal = _combine_signal(
        [
            _band_metric(avg_intelligibility, strong_at=0.5, moderate_at=0.25),
            _band_metric(avg_intelligibility_r2, strong_at=0.45, moderate_at=0.2),
        ]
    )
    pattern_tags: List[str] = []
    if node_count >= 1000 and edge_count >= 1000:
        pattern_tags.append("路网规模较大")
    if edge_count > node_count and node_count > 0:
        pattern_tags.append("连接较充分")
    if regression_r2 is not None and regression_r2 >= 0.5:
        pattern_tags.append("结构可读性较强")
    if connectivity_signal == "strong":
        pattern_tags.append("内部连通顺畅")
    elif connectivity_signal == "weak":
        pattern_tags.append("内部连通偏弱")
    if access_signal == "strong":
        pattern_tags.append("主路径承接较强")
    elif access_signal == "weak":
        pattern_tags.append("通达效率一般")
    if readability_signal == "strong":
        pattern_tags.append("动线识别清晰")
    elif readability_signal == "weak":
        pattern_tags.append("动线可读性有限")
    if metric:
        pattern_tags.append(f"当前关注指标:{metric}")
    summary_text = (
        f"路网节点 {node_count}、边段 {edge_count}。"
        + (f" 回归 R²={regression_r2:.3f}。" if regression_r2 is not None else "")
        if road_summary or road_panel
        else "当前缺少可直接利用的路网结构结果。"
    )
    payload = {
        "metric": metric,
        "main_tab": main_tab,
        "node_count": node_count,
        "edge_count": edge_count,
        "regression_r2": regression_r2,
        "avg_connectivity": avg_connectivity,
        "avg_control": avg_control,
        "avg_depth": avg_depth,
        "avg_choice_global": avg_choice_global,
        "avg_choice_local": avg_choice_local,
        "avg_integration_global": avg_integration_global,
        "avg_integration_local": avg_integration_local,
        "avg_intelligibility": avg_intelligibility,
        "avg_intelligibility_r2": avg_intelligibility_r2,
        "road_orientation_analysis": road_orientation_analysis,
        "default_radius_label": default_radius_label,
        "radius_labels": radius_labels,
        "connectivity_signal": connectivity_signal,
        "access_signal": access_signal,
        "readability_signal": readability_signal,
        "pattern_tags": pattern_tags,
        "summary_text": summary_text,
    }
    return _with_analysis_status(payload, ready=is_road_pattern_ready(payload))


def _pick_top_age_band(age_distribution: List[Dict[str, Any]], layer_summary: Dict[str, Any]) -> str:
    label = str(layer_summary.get("top_dominant_age_band_label") or "").strip()
    if label:
        return label
    best_label = ""
    best_total = -1.0
    for row in age_distribution:
        item = _safe_dict(row)
        total = _to_float(item.get("total"), 0.0) or 0.0
        if total > best_total:
            best_total = total
            best_label = str(item.get("age_band_label") or item.get("age_band") or "").strip()
    return best_label


def _density_level(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 10000:
        return "high"
    if value >= 3000:
        return "medium"
    return "low"


def build_population_profile_analysis(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    panel = _current_frontend_panel(snapshot, artifacts, "population")
    summary = _current_summary(snapshot, artifacts, "population")
    layer_summary = _safe_dict(panel.get("layer_summary"))
    age_distribution = [_safe_dict(item) for item in _safe_list(panel.get("age_distribution"))]
    average_density = _to_float(
        layer_summary.get("average_density_per_km2"),
        _to_float(summary.get("average_density_per_km2"), None),
    )
    dominant_cell_ratio = _to_float(layer_summary.get("dominant_cell_ratio"), None)
    top_age_band = _pick_top_age_band(age_distribution, layer_summary)
    total_population = _to_float(summary.get("total_population"), None)
    male_ratio = _to_float(summary.get("male_ratio"), None)
    female_ratio = _to_float(summary.get("female_ratio"), None)
    profile_tags: List[str] = []
    if total_population is not None:
        profile_tags.append("人口基础存在")
    if male_ratio is not None and female_ratio is not None and abs(male_ratio - female_ratio) <= 0.08:
        profile_tags.append("性别结构均衡")
    if top_age_band:
        profile_tags.append(f"年龄主段:{top_age_band}")
    density_level = _density_level(average_density)
    if density_level != "unknown":
        profile_tags.append(f"密度水平:{density_level}")
    summary_text = (
        f"人口总量约 {total_population:.0f}，年龄主段为 {top_age_band or '未明确'}。"
        if total_population is not None or top_age_band
        else "当前缺少可直接利用的人口结构结果。"
    )
    payload = {
        "view": str(panel.get("analysis_view") or snapshot.current_filters.get("population_view") or "").strip(),
        "total_population": total_population,
        "male_ratio": male_ratio,
        "female_ratio": female_ratio,
        "top_age_band": top_age_band,
        "dominant_cell_ratio": dominant_cell_ratio,
        "density_level": density_level,
        "profile_tags": profile_tags,
        "summary_text": summary_text,
    }
    return _with_analysis_status(payload, ready=is_population_profile_ready(payload))


def build_nightlight_pattern_analysis(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    panel = _current_frontend_panel(snapshot, artifacts, "nightlight")
    summary = _current_summary(snapshot, artifacts, "nightlight")
    analysis = _safe_dict(panel.get("analysis"))
    total_radiance = _to_float(summary.get("total_radiance"), None)
    mean_radiance = _to_float(summary.get("mean_radiance"), None)
    peak_radiance = _to_float(summary.get("max_radiance"), _to_float(analysis.get("peak_radiance"), None))
    lit_pixel_ratio = _to_float(summary.get("lit_pixel_ratio"), None)
    core_hotspot_count = _to_int(analysis.get("core_hotspot_count"), 0) or 0
    hotspot_cell_ratio = _to_float(analysis.get("hotspot_cell_ratio"), None)
    max_distance_km = _to_float(analysis.get("max_distance_km"), None)
    peak_to_edge_ratio = _to_float(analysis.get("peak_to_edge_ratio"), None)
    p90_radiance = _to_float(summary.get("p90_radiance"), None)
    economic_activity_intensity_level = str(analysis.get("economic_activity_intensity_level") or "").strip()
    economic_activity_summary_text = str(analysis.get("economic_activity_summary_text") or "").strip()
    sector_direction_analysis = _safe_dict(analysis.get("sector_direction_analysis"))
    pattern_tags: List[str] = []
    if lit_pixel_ratio is not None and lit_pixel_ratio >= 0.8:
        pattern_tags.append("亮灯覆盖高")
    if core_hotspot_count > 0:
        pattern_tags.append("存在夜间热点核心")
    if peak_to_edge_ratio is not None and peak_to_edge_ratio >= 2:
        pattern_tags.append("中心亮度突出")
    if total_radiance is not None or core_hotspot_count > 0:
        total_text = f"{total_radiance:.1f}" if total_radiance is not None else "-"
        mean_text = f"{mean_radiance:.2f}" if mean_radiance is not None else "-"
        summary_text = economic_activity_summary_text or f"基于夜间灯光亮度，等时圈内经济活动强度总辐亮 {total_text}，均值 {mean_text}，热点核心 {core_hotspot_count} 个。"
    else:
        summary_text = "当前缺少可直接利用的夜光结构结果。"
    payload = {
        "view": str(panel.get("analysis_view") or snapshot.current_filters.get("nightlight_view") or "").strip(),
        "total_radiance": total_radiance,
        "mean_radiance": mean_radiance,
        "p90_radiance": p90_radiance,
        "peak_radiance": peak_radiance,
        "lit_pixel_ratio": lit_pixel_ratio,
        "core_hotspot_count": core_hotspot_count,
        "hotspot_cell_ratio": hotspot_cell_ratio,
        "max_distance_km": max_distance_km,
        "peak_to_edge_ratio": peak_to_edge_ratio,
        "economic_activity_intensity_level": economic_activity_intensity_level,
        "economic_activity_summary_text": economic_activity_summary_text,
        "sector_direction_analysis": sector_direction_analysis,
        "pattern_tags": pattern_tags,
        "summary_text": summary_text,
        "legend_note": str(panel.get("legend_note") or "").strip(),
    }
    return _with_analysis_status(payload, ready=is_nightlight_pattern_ready(payload))


def analyze_poi_mix(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any], poi_structure: Dict[str, Any] | None = None) -> Dict[str, Any]:
    poi_structure = poi_structure or build_poi_structure_analysis(snapshot, artifacts)
    top_categories = [item for item in _safe_list(poi_structure.get("top_categories")) if isinstance(item, dict)]
    dominant_functions = [str(item.get("label") or "") for item in top_categories[:2] if str(item.get("label") or "").strip()]
    supporting_functions = [str(item.get("label") or "") for item in top_categories[2:5] if str(item.get("label") or "").strip()]
    dining_ratio = _to_float(poi_structure.get("dining_ratio"), 0.0) or 0.0
    shopping_ratio = _to_float(poi_structure.get("shopping_ratio"), 0.0) or 0.0
    lodging_ratio = _to_float(poi_structure.get("lodging_ratio"), 0.0) or 0.0
    office_ratio = _to_float(poi_structure.get("office_ratio"), 0.0) or 0.0
    culture_ratio = _to_float(poi_structure.get("culture_ratio"), 0.0) or 0.0
    top_share = sum(_to_float(item.get("ratio"), 0.0) or 0.0 for item in top_categories[:3])
    richness = sum(1 for item in top_categories if (_to_float(item.get("ratio"), 0.0) or 0.0) >= 0.05)
    functional_mix_score = round(max(0.0, min(100.0, 45 + richness * 8 + (1 - min(top_share, 1.0)) * 35)), 1)

    if dining_ratio + shopping_ratio >= 0.48:
        business_profile = "生活消费主导"
        portrait = "该区域更像一个以日常消费和社区级配套为主的综合商业区。"
    elif office_ratio >= 0.16:
        business_profile = "商务消费复合"
        portrait = "该区域兼具商务活动与日常消费功能，不是单一生活配套区。"
    elif lodging_ratio >= 0.1:
        business_profile = "住宿接待复合"
        portrait = "该区域对流动人口和短停留需求有较强承接能力，商业结构带有接待属性。"
    else:
        business_profile = "综合服务混合"
        portrait = "该区域呈现多业态混合供给，更像综合服务片区而不是单一功能板块。"

    if culture_ratio >= 0.1:
        portrait += " 科教文化占比不低，说明公共服务或教育相关配套参与度较高。"

    return {
        "business_profile": business_profile,
        "dominant_functions": dominant_functions,
        "supporting_functions": supporting_functions,
        "functional_mix_score": functional_mix_score,
        "portrait": portrait,
        "summary_text": f"{business_profile}，主导功能为 {'、'.join(dominant_functions) or '未明确'}。",
    }


def detect_commercial_hotspots(
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    *,
    target_category: str = "",
    h3_structure: Dict[str, Any] | None = None,
    poi_structure: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    del poi_structure
    h3_structure = h3_structure or build_h3_structure_analysis(snapshot, artifacts)
    structure_rows = [_safe_dict(item) for item in _safe_list(h3_structure.get("structure_rows"))]
    gap_rows = [_safe_dict(item) for item in _safe_list(h3_structure.get("gap_rows"))]
    signal_count = _to_int(h3_structure.get("structure_signal_count"), 0) or 0
    opportunity_count = _to_int(h3_structure.get("opportunity_count"), 0) or 0
    text = " ".join(
        [
            str(h3_structure.get("typing_recommendation") or ""),
            str(h3_structure.get("gap_recommendation") or ""),
        ]
    )
    if signal_count <= 0 and opportunity_count <= 0:
        hotspot_mode = "dispersed"
    elif "走廊" in text or "带" in text:
        hotspot_mode = "corridor"
    elif signal_count >= 5 or opportunity_count >= 3:
        hotspot_mode = "multi_core"
    else:
        hotspot_mode = "single_core"

    core_zone_count = sum(1 for row in structure_rows if _to_float(row.get("structure_signal"), 0.0) or row.get("is_structure_signal"))
    if core_zone_count <= 0:
        core_zone_count = min(signal_count, 1 if signal_count > 0 else 0)
    secondary_zone_count = max(0, signal_count - core_zone_count)
    zone_rows: List[Dict[str, Any]] = []
    for row in gap_rows[:5] or structure_rows[:5]:
        zone_rows.append(
            {
                "h3_id": str(row.get("h3_id") or ""),
                "label": str(row.get("gap_zone_label") or row.get("type_key") or "").strip(),
                "structure_signal": _to_float(row.get("structure_signal"), None),
                "density": _to_float(row.get("density"), None),
                "poi_count": _to_int(row.get("poi_count"), None),
                "gap_score": _to_float(row.get("gap_score"), None),
            }
        )
    target_suffix = f"（目标类别：{target_category}）" if str(target_category).strip() else ""
    return {
        "hotspot_mode": hotspot_mode,
        "core_zone_count": core_zone_count,
        "secondary_zone_count": secondary_zone_count,
        "opportunity_zone_count": opportunity_count,
        "zone_rows": zone_rows,
        "summary_text": f"商业热点结构为 {hotspot_mode}{target_suffix}，核心区 {core_zone_count} 个，机会区 {opportunity_count} 个。",
    }


def analyze_target_supply_gap(
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    *,
    place_type: str,
    h3_structure: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    h3_structure = h3_structure or build_h3_structure_analysis(snapshot, artifacts)
    gap_rows = [_safe_dict(item) for item in _safe_list(h3_structure.get("gap_rows"))]
    opportunity_count = _to_int(h3_structure.get("opportunity_count"), 0) or 0
    max_gap = 0.0
    if gap_rows:
        max_gap = max(_to_float(row.get("gap_score"), 0.0) or 0.0 for row in gap_rows)
    gap_zones = [
        {
            "h3_id": str(row.get("h3_id") or ""),
            "label": str(row.get("gap_zone_label") or "").strip(),
            "gap_score": _to_float(row.get("gap_score"), None),
            "demand_pct": _to_float(row.get("demand_pct"), None),
            "supply_pct": _to_float(row.get("supply_pct"), None),
        }
        for row in gap_rows[:5]
    ]
    candidate_zones = _target_candidate_zones(snapshot, artifacts, gap_zones)
    poi_summary = artifacts.get("current_poi_summary") if isinstance(artifacts.get("current_poi_summary"), dict) else snapshot.poi_summary
    poi_summary = _safe_dict(poi_summary)
    targeted_summary = bool(str(poi_summary.get("types") or "").strip() or str(poi_summary.get("keywords") or "").strip())
    targeted_count = _to_int(poi_summary.get("total"), None)

    if opportunity_count >= 3 or max_gap >= 0.45:
        supply_gap_level = "high"
    elif opportunity_count >= 1 or max_gap >= 0.25:
        supply_gap_level = "medium"
    else:
        supply_gap_level = "low"

    if targeted_summary and targeted_count is not None and targeted_count <= 5:
        gap_mode = "overall_shortage"
    elif opportunity_count > 0:
        gap_mode = "spatial_mismatch"
    else:
        gap_mode = "unclear"

    target_label = str(place_type or h3_structure.get("target_category_label") or h3_structure.get("target_category") or "").strip()
    evidence_summary = (
        f"目标业态 `{target_label or '未指定'}` 当前缺口判断基于 H3 gap 结果，机会区 {opportunity_count} 个，最大 gap {max_gap:.2f}。"
        if gap_rows
        else "当前缺少可直接利用的 H3 gap 结果，只能给出弱判断。"
    )
    payload = {
        "place_type": target_label,
        "supply_gap_level": supply_gap_level,
        "gap_mode": gap_mode,
        "gap_zones": gap_zones,
        "candidate_zones": candidate_zones,
        "evidence_summary": evidence_summary,
        "summary_text": (
            f"{target_label or '目标业态'}供给缺口等级为 {supply_gap_level}，模式为 {gap_mode}。"
            + (f" 当前可优先查看 {candidate_zones[0]['approx_address']} 等 {len(candidate_zones)} 个候选格。" if candidate_zones else "")
        ),
    }
    return _with_analysis_status(payload, ready=bool(gap_rows or candidate_zones or gap_mode in {"overall_shortage", "spatial_mismatch"}))


def _append_rule_hit(
    hits: List[Dict[str, Any]],
    *,
    rule_id: str,
    label: str,
    evidence_metrics: List[str],
    threshold_hit: str,
    confidence: str,
) -> None:
    hits.append(
        {
            "rule_id": rule_id,
            "label": label,
            "evidence_metrics": evidence_metrics,
            "threshold_hit": threshold_hit,
            "confidence": confidence,
        }
    )


def infer_area_character_labels(
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    *,
    poi_structure: Dict[str, Any] | None = None,
    business_profile: Dict[str, Any] | None = None,
    population_profile: Dict[str, Any] | None = None,
    nightlight_pattern: Dict[str, Any] | None = None,
    road_pattern: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    poi_structure = poi_structure or build_poi_structure_analysis(snapshot, artifacts)
    business_profile = business_profile or analyze_poi_mix(snapshot, artifacts, poi_structure=poi_structure)
    population_profile = population_profile or build_population_profile_analysis(snapshot, artifacts)
    nightlight_pattern = nightlight_pattern or build_nightlight_pattern_analysis(snapshot, artifacts)
    road_pattern = road_pattern or build_road_pattern_analysis(snapshot, artifacts)

    dining_ratio = _to_float(poi_structure.get("dining_ratio"), 0.0) or 0.0
    culture_ratio = _to_float(poi_structure.get("culture_ratio"), 0.0) or 0.0
    office_ratio = _to_float(poi_structure.get("office_ratio"), 0.0) or 0.0
    total_population = _to_float(population_profile.get("total_population"), None)
    top_age_band = str(population_profile.get("top_age_band") or "").strip()
    density_level = str(population_profile.get("density_level") or "").strip()
    core_hotspot_count = _to_int(nightlight_pattern.get("core_hotspot_count"), 0) or 0
    total_radiance = _to_float(nightlight_pattern.get("total_radiance"), None)
    peak_to_edge_ratio = _to_float(nightlight_pattern.get("peak_to_edge_ratio"), None)
    node_count = _to_int(road_pattern.get("node_count"), 0) or 0
    edge_count = _to_int(road_pattern.get("edge_count"), 0) or 0
    business_label = str(business_profile.get("business_profile") or "").strip()

    rule_hits: List[Dict[str, Any]] = []
    character_tags: List[str] = []

    if dining_ratio >= 0.28 and core_hotspot_count >= 1 and ((peak_to_edge_ratio or 0.0) >= 2.0 or (total_radiance or 0.0) >= 1000):
        _append_rule_hit(
            rule_hits,
            rule_id="night_economic_activity_cluster",
            label="夜间经济活动活跃片区",
            evidence_metrics=["poi.dining_ratio", "nightlight.core_hotspot_count", "nightlight.peak_to_edge_ratio"],
            threshold_hit=f"餐饮占比 {dining_ratio:.2f}，夜间热点 {core_hotspot_count} 个，中心亮度比 {peak_to_edge_ratio or 0.0:.2f}",
            confidence="strong",
        )
        character_tags.append("夜间经济活动活跃片区")

    if culture_ratio >= 0.08 and (total_population or 0.0) >= 20000 and node_count >= 1500 and edge_count >= node_count:
        _append_rule_hit(
            rule_hits,
            rule_id="community_service_cluster",
            label="生活服务型社区",
            evidence_metrics=["poi.culture_ratio", "population.total_population", "road.node_count", "road.edge_count"],
            threshold_hit=f"科教文化占比 {culture_ratio:.2f}，人口 {total_population or 0.0:.0f}，路网节点 {node_count}",
            confidence="moderate",
        )
        character_tags.append("生活服务型社区")

    if office_ratio >= 0.12 and node_count >= 1500 and top_age_band in {"25-34岁", "35-44岁"} and ((total_radiance or 0.0) >= 800 or density_level in {"high", "medium"}):
        _append_rule_hit(
            rule_hits,
            rule_id="business_oriented_cluster",
            label="商务导向片区",
            evidence_metrics=["poi.office_ratio", "road.node_count", "population.top_age_band", "nightlight.total_radiance"],
            threshold_hit=f"商务占比 {office_ratio:.2f}，主年龄段 {top_age_band or '-'}，夜光总辐亮 {total_radiance or 0.0:.1f}",
            confidence="moderate",
        )
        character_tags.append("商务导向片区")

    if not character_tags and business_label:
        character_tags.append(business_label)

    dominant_functions = [str(item) for item in (business_profile.get("dominant_functions") or []) if str(item).strip()][:3]
    crowd_traits: List[str] = []
    if top_age_band:
        crowd_traits.append(f"年龄主段 {top_age_band}")
    if total_population is not None:
        crowd_traits.append(f"人口基盘约 {total_population:.0f}")
    if density_level in {"high", "medium"}:
        crowd_traits.append(f"居住密度 {density_level}")

    if core_hotspot_count >= 1 or (total_radiance or 0.0) >= 800:
        activity_period = "夜间经济活动信号较强"
    elif (total_radiance or 0.0) > 0 or (peak_to_edge_ratio or 0.0) > 0:
        activity_period = "夜间经济活动信号中等"
    else:
        activity_period = "夜间经济活动信号较弱"

    if node_count >= 2000 and edge_count >= node_count:
        spatial_temperament = "路网细密、可达性较强"
    elif node_count >= 500:
        spatial_temperament = "骨架清晰、通达性中等"
    else:
        spatial_temperament = "结构较松散、仍需结合实地判断"

    confidence = "strong" if any(item.get("confidence") == "strong" for item in rule_hits) else ("moderate" if rule_hits else "weak")
    return {
        "character_tags": character_tags,
        "dominant_functions": dominant_functions,
        "activity_period": activity_period,
        "crowd_traits": crowd_traits,
        "spatial_temperament": spatial_temperament,
        "rule_hits": rule_hits,
        "confidence": confidence,
        "summary_text": (
            f"区域标签为 {'、'.join(character_tags) or '综合服务混合'}，主导功能为 {'、'.join(dominant_functions) or '未明确'}。"
        ),
    }


def score_site_candidates(
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    *,
    target_supply_gap: Dict[str, Any] | None = None,
    population_profile: Dict[str, Any] | None = None,
    nightlight_pattern: Dict[str, Any] | None = None,
    road_pattern: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    target_supply_gap = target_supply_gap or analyze_target_supply_gap(snapshot, artifacts, place_type="")
    population_profile = population_profile or build_population_profile_analysis(snapshot, artifacts)
    nightlight_pattern = nightlight_pattern or build_nightlight_pattern_analysis(snapshot, artifacts)
    road_pattern = road_pattern or build_road_pattern_analysis(snapshot, artifacts)

    candidates = [_safe_dict(item) for item in _safe_list(target_supply_gap.get("candidate_zones"))]
    total_population = _to_float(population_profile.get("total_population"), 0.0) or 0.0
    density_level = str(population_profile.get("density_level") or "").strip()
    core_hotspot_count = _to_int(nightlight_pattern.get("core_hotspot_count"), 0) or 0
    peak_to_edge_ratio = _to_float(nightlight_pattern.get("peak_to_edge_ratio"), 0.0) or 0.0
    node_count = _to_int(road_pattern.get("node_count"), 0) or 0
    edge_count = _to_int(road_pattern.get("edge_count"), 0) or 0

    ranked: List[Dict[str, Any]] = []
    for index, zone in enumerate(candidates[:5]):
        gap_score = _to_float(zone.get("gap_score"), 0.0) or 0.0
        demand_pct = _to_float(zone.get("demand_pct"), 0.0) or 0.0
        supply_pct = _to_float(zone.get("supply_pct"), 0.0) or 0.0
        supply_gap_score = max(0.0, min(100.0, 35 + gap_score * 90 + max(demand_pct - supply_pct, 0.0) * 50))

        population_score = 45.0
        if total_population >= 30000:
            population_score += 25.0
        elif total_population >= 10000:
            population_score += 15.0
        if density_level == "high":
            population_score += 10.0
        elif density_level == "medium":
            population_score += 5.0

        vitality_score = min(100.0, 35 + core_hotspot_count * 12 + peak_to_edge_ratio * 10)
        access_score = min(100.0, 30 + min(node_count / 80.0, 45.0) + (10.0 if edge_count >= node_count and node_count > 0 else 0.0))
        total_score = round(
            supply_gap_score * 0.4
            + population_score * 0.2
            + vitality_score * 0.2
            + access_score * 0.2,
            1,
        )

        strengths: List[str] = []
        risks: List[str] = []
        if supply_gap_score >= 70:
            strengths.append("目标业态供给缺口较明显")
        if vitality_score >= 60:
            strengths.append("夜间曝光和活力支撑较好")
        if access_score >= 60:
            strengths.append("路网通达性较强")
        if population_score >= 60:
            strengths.append("周边人口基盘可支撑")

        if supply_pct >= 0.6:
            risks.append("现状供给分位不低，需复核竞品强度")
        if core_hotspot_count <= 0:
            risks.append("夜间活力信号偏弱")
        if node_count < 500:
            risks.append("路网骨架证据偏弱")
        if total_population < 8000:
            risks.append("人口基盘偏小")

        ranked.append(
            {
                "rank": index + 1,
                "h3_id": str(zone.get("h3_id") or ""),
                "approx_address": str(zone.get("approx_address") or zone.get("display_title") or "").strip(),
                "display_title": str(zone.get("display_title") or zone.get("approx_address") or "").strip(),
                "total_score": total_score,
                "scores": {
                    "supply_gap": round(supply_gap_score, 1),
                    "population_support": round(population_score, 1),
                    "vitality": round(vitality_score, 1),
                    "accessibility": round(access_score, 1),
                },
                "strengths": strengths,
                "risks": risks,
                "reason_summary": str(zone.get("reason_summary") or "").strip(),
            }
        )
    ranked.sort(key=lambda item: (-float(item.get("total_score") or 0.0), int(item.get("rank") or 999)))
    for index, item in enumerate(ranked):
        item["rank"] = index + 1

    return {
        "candidate_sites": ranked,
        "ranking": [
            {
                "rank": int(item.get("rank") or 0),
                "title": str(item.get("display_title") or item.get("approx_address") or "").strip(),
                "total_score": float(item.get("total_score") or 0.0),
            }
            for item in ranked
        ],
        "strengths": ranked[0].get("strengths") if ranked else [],
        "risks": ranked[0].get("risks") if ranked else ["当前缺少足够候选区证据"],
        "not_recommended_reason": (
            "候选区供给缺口、人口或活力证据不足，当前结果更适合作为预筛而非最终定点。"
            if not ranked
            else "低排名点位在供给缺口、可达性或活力上至少一项明显偏弱。"
        ),
        "confidence": "moderate" if ranked else "weak",
        "summary_text": (
            f"已完成 {len(ranked)} 个候选区打分排序，首选 {ranked[0]['display_title']}。"
            if ranked
            else "当前缺少足够候选区，暂不能形成稳定排序。"
        ),
    }
