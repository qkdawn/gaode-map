from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any, Dict, Iterable, List, Optional

from modules.charting import save_svg

from .schemas import PptSource


SUPPORTED_CHART_TYPES = {"bar", "grouped_bar", "line", "radar", "metric_table", "histogram", "heatmap_grid"}


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
    source_ids = [_clean_text(item) for item in _safe_list(item.get("source_ids") or item.get("sourceIds")) if _clean_text(item)]
    source_id = _clean_text(item.get("source_id") or item.get("sourceId")) or (source_ids[0] if source_ids else f"current:analysis:{domain}")
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
        for raw_gap in _safe_list(ai_payload.get("metric_gaps") or ai_payload.get("metricGaps")):
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
        "source_id": _clean_text(item.get("source_id") or item.get("sourceId")) or _clean_text(metric.get("source_id")),
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
                "source_id": _clean_text(item.get("source_id") or item.get("sourceId")),
            })
    return gaps


def _normalize_chart(raw: Any, metric_by_id: Dict[str, Dict[str, Any]], index: int) -> Optional[Dict[str, Any]]:
    item = _safe_dict(raw)
    chart_type = _clean_text(item.get("chart_type") or item.get("chartType")) or "bar"
    if chart_type not in SUPPORTED_CHART_TYPES:
        chart_type = "bar"
    columns = _safe_list(item.get("columns"))
    rows = _safe_list(item.get("rows"))
    source_metric_ids = [
        _clean_text(metric_id)
        for metric_id in _safe_list(item.get("source_metric_ids") or item.get("sourceMetricIds"))
        if metric_by_id.get(_clean_text(metric_id)) and _clean_text(metric_by_id[_clean_text(metric_id)].get("status")) == "ready"
    ]
    source_ids = list(dict.fromkeys(
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
    if not rows or not columns:
        return None
    return {
        "chart_id": _clean_text(item.get("chart_id") or item.get("chartId")) or f"chart-{index}",
        "title": _clean_text(item.get("title")) or f"图表 {index}",
        "chart_type": chart_type,
        "columns": columns,
        "rows": rows,
        "source_metric_ids": source_metric_ids,
        "source_ids": source_ids,
        "unit": _clean_text(item.get("unit")),
        "render_hint": _clean_text(item.get("render_hint") or item.get("renderHint")),
    }


def validate_metric_assets(slide_payload: Dict[str, Any], metric_context: Dict[str, Any]) -> Dict[str, Any]:
    metric_by_id = {
        _clean_text(metric.get("metric_id")): metric
        for metric in _safe_list(metric_context.get("metrics"))
        if _clean_text(metric.get("status")) == "ready"
    }
    claims = [
        claim
        for index, raw in enumerate(_safe_list(slide_payload.get("metric_claims") or slide_payload.get("metricClaims")), start=1)
        if (claim := _normalize_claim(raw, metric_by_id, index))
    ]
    charts = [
        chart
        for index, raw in enumerate(_safe_list(slide_payload.get("chart_specs") or slide_payload.get("chartSpecs")), start=1)
        if (chart := _normalize_chart(raw, metric_by_id, index))
    ]
    gaps = _normalize_gaps(slide_payload.get("metric_gaps") or slide_payload.get("metricGaps"))
    requested_claims = bool(_safe_list(slide_payload.get("metric_claims") or slide_payload.get("metricClaims")))
    requested_charts = bool(_safe_list(slide_payload.get("chart_specs") or slide_payload.get("chartSpecs")))
    if (requested_claims and not claims) or (requested_charts and not charts):
        known_gap_ids = {_clean_text(gap.get("metric_id")) for gap in gaps}
        for gap in _safe_list(metric_context.get("metric_gaps"))[:6]:
            metric_id = _clean_text(gap.get("metric_id"))
            if metric_id and metric_id in known_gap_ids:
                continue
            gaps.append(gap)
    return {
        "metric_claims": claims,
        "metric_gaps": gaps,
        "chart_specs": charts,
    }


def _column_key(column: Any) -> str:
    if isinstance(column, dict):
        return _clean_text(column.get("key") or column.get("field") or column.get("label"))
    return _clean_text(column)


def _column_label(column: Any) -> str:
    if isinstance(column, dict):
        return _clean_text(column.get("label") or column.get("key") or column.get("field"))
    return _clean_text(column)


def _chart_svg(spec: Dict[str, Any]) -> str:
    title = html.escape(_clean_text(spec.get("title")) or "图表")
    chart_type = _clean_text(spec.get("chart_type"))
    columns = _safe_list(spec.get("columns"))
    rows = [_safe_dict(row) for row in _safe_list(spec.get("rows"))[:40]]
    width = 980
    height = 560
    if chart_type == "metric_table":
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
    if chart_type in {"line", "radar"}:
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


def render_chart_artifacts(chart_specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    for spec in chart_specs:
        svg = _chart_svg(spec)
        chart_id, filename = save_svg(svg)
        artifacts.append({
            "chart_id": spec.get("chart_id") or chart_id,
            "format": "svg",
            "filename": filename,
            "url": f"/download/{filename}",
            "source_chart_id": chart_id,
        })
    return artifacts
