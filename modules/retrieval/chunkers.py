from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from modules.agent.analysis_extractors import (
    analyze_poi_mix,
    build_h3_structure_analysis,
    build_nightlight_pattern_analysis,
    build_poi_structure_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
)
from modules.agent.schemas import AnalysisSnapshot

from .schemas import KnowledgeChunk


NIGHTLIGHT_WARNING = "夜光仅作为活力 proxy，不能直接等同客流。"
POI_WARNING = "POI 供给不能直接等同市场需求。"
POPULATION_WARNING = "人口指标不能直接推断消费能力。"
ROAD_WARNING = "路网句法不能单独替代选址判断。"
_POI_RECORD_BATCH_SIZE = 50
_POI_RECORD_MAX_BATCHES = 12


def _safe_dict(value: Any) -> Dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return list(value or []) if isinstance(value, list) else []


def _text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, default=str)


def _compact_metrics(payload: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    return {key: payload.get(key) for key in keys if payload.get(key) not in (None, "", [], {})}


def _source_present(artifacts: Dict[str, Any], snapshot: AnalysisSnapshot, artifact_key: str, snapshot_key: str = "") -> List[str]:
    refs: List[str] = []
    if artifacts.get(artifact_key):
        refs.append(artifact_key)
    if snapshot_key:
        payload = getattr(snapshot, snapshot_key, {})
        if isinstance(payload, dict) and payload:
            refs.append(f"snapshot.{snapshot_key}")
    return refs


def _chunk(
    *,
    chunk_id: str,
    kind: str,
    domain: str,
    title: str,
    content: str,
    metrics: Dict[str, Any] | None = None,
    source_artifacts: List[str] | None = None,
    warnings: List[str] | None = None,
    evidence_level: str = "derived_metric",
) -> KnowledgeChunk | None:
    clean_content = " ".join(str(content or "").split())
    if not clean_content and not metrics:
        return None
    return KnowledgeChunk(
        chunk_id=chunk_id,
        kind=kind,  # type: ignore[arg-type]
        domain=domain,
        title=title,
        content=clean_content or title,
        metrics=dict(metrics or {}),
        source_artifacts=list(source_artifacts or []),
        warnings=list(warnings or []),
        evidence_level=evidence_level,
    )


def _map_search_context_chunks(artifacts: Dict[str, Any]) -> List[KnowledgeChunk]:
    context = _safe_dict(artifacts.get("frontend_map_search_context"))
    if not context:
        return []
    chunks: List[KnowledgeChunk] = []
    place_anchors = _safe_dict(context.get("place_anchors"))
    spatial_anchors = _safe_dict(context.get("spatial_anchors"))

    groups = []
    names: List[str] = []
    for group in _safe_list(place_anchors.get("groups")):
        item = _safe_dict(group)
        rows = [_safe_dict(row) for row in _safe_list(item.get("items"))]
        clean_rows = [
            {
                "name": str(row.get("name") or "").strip(),
                "type": str(row.get("type") or "").strip(),
                "address": str(row.get("address") or "").strip(),
                "lng": row.get("lng"),
                "lat": row.get("lat"),
            }
            for row in rows
            if str(row.get("name") or "").strip()
        ]
        if clean_rows:
            groups.append({"key": item.get("key"), "label": item.get("label"), "items": clean_rows[:12]})
            names.extend([row["name"] for row in clean_rows if row["name"] not in names])
    if not names:
        names = [str(name).strip() for name in _safe_list(place_anchors.get("names")) if str(name).strip()][:48]
    chunk = _chunk(
        chunk_id="session:current:analysis:poi.place_anchors",
        kind="analysis",
        domain="poi",
        title="POI 地名锚点",
        content="；".join(
            [
                f"{group.get('label') or group.get('key')}："
                + "、".join(
                    " ".join(part for part in [str(row.get("name") or ""), str(row.get("type") or ""), str(row.get("address") or "")] if part).strip()
                    for row in _safe_list(group.get("items"))[:12]
                )
                for group in groups
            ]
        )
        or "、".join(names),
        metrics={"groups": groups[:8], "names": names[:48]},
        source_artifacts=["frontend_map_search_context"],
        warnings=[POI_WARNING, "地名锚点来自前端当前 POI 结果的代表性归类；如需核对具体名称，应优先检索 current_pois 生成的 POI 记录 EvidenceNode。"],
        evidence_level="frontend_map_anchor",
    )
    if chunk:
        chunks.append(chunk)

    selected_point = _safe_dict(spatial_anchors.get("selected_point"))
    h3 = _safe_dict(spatial_anchors.get("h3"))
    h3_cells = _safe_list(h3.get("top_cells"))
    chunk = _chunk(
        chunk_id="session:current:analysis:h3.spatial_anchors",
        kind="analysis",
        domain="h3",
        title="H3 代表格空间锚点",
        content=" ".join([_text(selected_point), _text(h3_cells[:12])]),
        metrics={
            "selected_point": selected_point,
            "feature_count": h3.get("feature_count"),
            "top_cells": h3_cells[:12],
        },
        source_artifacts=["frontend_map_search_context"],
        warnings=[POI_WARNING, "H3 代表格是前端当前图层抽样，不是完整网格结果。"],
        evidence_level="frontend_map_anchor",
    )
    if chunk:
        chunks.append(chunk)

    road = _safe_dict(spatial_anchors.get("road"))
    road_segments = _safe_list(road.get("sample_segments"))
    chunk = _chunk(
        chunk_id="session:current:analysis:road.metric_anchors",
        kind="analysis",
        domain="road",
        title="路网指标与代表线段锚点",
        content=" ".join([_text(road.get("metric_tabs")), _text(road.get("metric_keys")), _text(road_segments[:12])]),
        metrics={
            "feature_count": road.get("feature_count"),
            "metric_tabs": _safe_list(road.get("metric_tabs"))[:12],
            "metric_keys": _safe_list(road.get("metric_keys"))[:24],
            "sample_segments": road_segments[:12],
        },
        source_artifacts=["frontend_map_search_context"],
        warnings=[ROAD_WARNING, "代表线段来自前端当前路网图层抽样；只能辅助定位局部路网现象。"],
        evidence_level="frontend_map_anchor",
    )
    if chunk:
        chunks.append(chunk)

    population = _safe_dict(spatial_anchors.get("population"))
    population_cells = _safe_list(population.get("top_cells"))
    chunk = _chunk(
        chunk_id="session:current:analysis:population.cell_anchors",
        kind="analysis",
        domain="population",
        title="人口代表 cell 锚点",
        content=" ".join([_text(population.get("layer_summary")), _text(population_cells[:12])]),
        metrics={
            "cell_count": population.get("cell_count"),
            "layer_summary": _safe_dict(population.get("layer_summary")),
            "top_cells": population_cells[:12],
        },
        source_artifacts=["frontend_map_search_context"],
        warnings=[POPULATION_WARNING, "人口 cell 是前端当前图层代表样本，不能直接推断消费能力。"],
        evidence_level="frontend_map_anchor",
    )
    if chunk:
        chunks.append(chunk)

    nightlight = _safe_dict(spatial_anchors.get("nightlight"))
    nightlight_cells = _safe_list(nightlight.get("top_cells"))
    chunk = _chunk(
        chunk_id="session:current:analysis:nightlight.cell_anchors",
        kind="analysis",
        domain="nightlight",
        title="夜光代表 cell 锚点",
        content=" ".join([_text(nightlight.get("layer_summary")), _text(nightlight.get("analysis")), _text(nightlight_cells[:12])]),
        metrics={
            "cell_count": nightlight.get("cell_count"),
            "layer_summary": _safe_dict(nightlight.get("layer_summary")),
            "analysis": _safe_dict(nightlight.get("analysis")),
            "top_cells": nightlight_cells[:12],
        },
        source_artifacts=["frontend_map_search_context"],
        warnings=[NIGHTLIGHT_WARNING, "夜光 cell 是前端当前图层代表样本，只能作为活力 proxy。"],
        evidence_level="frontend_map_anchor",
    )
    if chunk:
        chunks.append(chunk)
    return chunks


def _poi_record_chunks(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> List[KnowledgeChunk]:
    pois = _safe_list(artifacts.get("current_pois") or snapshot.pois)
    if not pois:
        return []
    source_refs = _source_present(artifacts, snapshot, "current_pois")
    if snapshot.pois and "snapshot.pois" not in source_refs:
        source_refs.append("snapshot.pois")
    chunks: List[KnowledgeChunk] = []
    max_records = _POI_RECORD_BATCH_SIZE * _POI_RECORD_MAX_BATCHES
    records = [_safe_dict(item) for item in pois[:max_records] if isinstance(item, dict)]
    for batch_index in range(0, len(records), _POI_RECORD_BATCH_SIZE):
        batch = records[batch_index : batch_index + _POI_RECORD_BATCH_SIZE]
        rows: List[Dict[str, Any]] = []
        content_parts: List[str] = []
        for offset, poi in enumerate(batch):
            name = str(poi.get("name") or poi.get("title") or "").strip()
            poi_type = str(poi.get("type") or poi.get("type_label") or poi.get("category") or poi.get("category_label") or "").strip()
            address = str(poi.get("address") or poi.get("adname") or poi.get("district") or "").strip()
            lng = poi.get("lng") if poi.get("lng") is not None else (_safe_list(poi.get("location"))[0] if _safe_list(poi.get("location")) else None)
            lat = poi.get("lat") if poi.get("lat") is not None else (_safe_list(poi.get("location"))[1] if len(_safe_list(poi.get("location"))) > 1 else None)
            row = {
                "index": batch_index + offset,
                "name": name,
                "type": poi_type,
                "address": address,
                "lng": lng,
                "lat": lat,
            }
            rows.append(row)
            content_parts.append(" ".join(part for part in (name, poi_type, address) if part).strip())
        chunk = _chunk(
            chunk_id=f"session:current:analysis:poi.records.{(batch_index // _POI_RECORD_BATCH_SIZE) + 1}",
            kind="analysis",
            domain="poi",
            title=f"当前 POI 记录 {batch_index + 1}-{batch_index + len(batch)}",
            content="；".join(part for part in content_parts if part),
            metrics={"rows": rows, "record_count": len(rows), "total_available": len(pois)},
            source_artifacts=source_refs,
            warnings=[POI_WARNING, "该 EvidenceNode 来自当前分析范围内已加载的 POI 结果；可引用其中实际出现的名称，但不能扩展成完整城市地名数据库。"],
            evidence_level="current_poi_record",
        )
        if chunk:
            chunks.append(chunk)
    if len(pois) > max_records:
        overflow = _chunk(
            chunk_id="session:current:analysis:poi.records.limit",
            kind="analysis",
            domain="poi",
            title="当前 POI 记录索引截断说明",
            content=f"当前 POI 共 {len(pois)} 条，已为检索索引保留前 {max_records} 条。统计分析仍应使用摘要与结构化指标。",
            metrics={"total_available": len(pois), "indexed_count": max_records},
            source_artifacts=source_refs,
            warnings=[POI_WARNING],
            evidence_level="index_limit_note",
        )
        if overflow:
            chunks.append(overflow)
    return chunks


def build_analysis_chunks(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> List[KnowledgeChunk]:
    chunks: List[KnowledgeChunk] = []
    poi_summary = _safe_dict(artifacts.get("current_poi_summary") or snapshot.poi_summary)
    h3_summary = _safe_dict(artifacts.get("current_poi_h3_summary") or _safe_dict(snapshot.h3).get("summary"))
    population_summary = _safe_dict(artifacts.get("current_population_summary") or _safe_dict(snapshot.population).get("summary"))
    nightlight_summary = _safe_dict(artifacts.get("current_nightlight_summary") or _safe_dict(snapshot.nightlight).get("summary"))
    road_summary = _safe_dict(artifacts.get("current_road_summary") or _safe_dict(snapshot.road).get("summary"))

    poi_structure = _safe_dict(artifacts.get("current_poi_structure_analysis")) or build_poi_structure_analysis(snapshot, artifacts)
    h3_structure = _safe_dict(artifacts.get("current_h3_structure_analysis")) or build_h3_structure_analysis(snapshot, artifacts)
    population_profile = _safe_dict(artifacts.get("current_population_profile_analysis")) or build_population_profile_analysis(snapshot, artifacts)
    nightlight_pattern = _safe_dict(artifacts.get("current_nightlight_pattern_analysis")) or build_nightlight_pattern_analysis(snapshot, artifacts)
    road_pattern = _safe_dict(artifacts.get("current_road_pattern_analysis")) or build_road_pattern_analysis(snapshot, artifacts)
    business_profile = _safe_dict(artifacts.get("current_business_profile")) or analyze_poi_mix(snapshot, artifacts, poi_structure=poi_structure)

    raw_chunks = [
        _chunk(
            chunk_id="session:current:analysis:poi.summary",
            kind="analysis",
            domain="poi",
            title="POI 结构摘要",
            content=" ".join(
                item
                for item in [
                    _text(poi_structure.get("summary_text")),
                    _text(business_profile.get("summary_text")),
                    f"主导类别：{'、'.join(poi_structure.get('dominant_categories') or [])}" if poi_structure.get("dominant_categories") else "",
                ]
                if item
            ),
            metrics={**_compact_metrics(poi_summary, ["total"]), **_compact_metrics(poi_structure, ["dining_ratio", "shopping_ratio", "lodging_ratio", "office_ratio", "culture_ratio"])},
            source_artifacts=_source_present(artifacts, snapshot, "current_poi_summary") + ["current_poi_structure_analysis"],
            warnings=[POI_WARNING],
        ),
        _chunk(
            chunk_id="session:current:analysis:h3.summary",
            kind="analysis",
            domain="h3",
            title="H3 网格结构摘要",
            content=_text(h3_structure.get("summary_text")) or _text(h3_summary),
            metrics={**_compact_metrics(h3_summary, ["grid_count", "avg_density_poi_per_km2"]), **_compact_metrics(h3_structure, ["distribution_pattern", "structure_signal_count", "hotspot_count", "opportunity_count"])},
            source_artifacts=_source_present(artifacts, snapshot, "current_poi_h3_summary", "h3") + ["current_h3_structure_analysis"],
        ),
        _chunk(
            chunk_id="session:current:analysis:h3.hotspot.top",
            kind="analysis",
            domain="h3",
            title="H3 热点网格",
            content=" ".join([_text(h3_structure.get("typing_recommendation")), _text(h3_structure.get("structure_rows"))]),
            metrics={"rows": _safe_list(h3_structure.get("structure_rows"))[:5]},
            source_artifacts=["current_h3_structure_analysis"],
        ),
        _chunk(
            chunk_id="session:current:analysis:h3.opportunity.top",
            kind="analysis",
            domain="h3",
            title="H3 机会网格与供给缺口",
            content=" ".join([_text(h3_structure.get("gap_recommendation")), _text(h3_structure.get("gap_rows"))]),
            metrics={"rows": _safe_list(h3_structure.get("gap_rows"))[:5], "target_category": h3_structure.get("target_category_label") or h3_structure.get("target_category")},
            source_artifacts=["current_h3_structure_analysis"],
            warnings=[POI_WARNING],
        ),
        _chunk(
            chunk_id="session:current:analysis:population.summary",
            kind="analysis",
            domain="population",
            title="人口画像摘要",
            content=_text(population_profile.get("summary_text")) or _text(population_summary),
            metrics={**_compact_metrics(population_summary, ["total_population", "male_ratio", "female_ratio", "average_density_per_km2"]), **_compact_metrics(population_profile, ["top_age_band", "density_level", "dominant_cell_ratio"])},
            source_artifacts=_source_present(artifacts, snapshot, "current_population_summary", "population") + ["current_population_profile_analysis"],
            warnings=[POPULATION_WARNING],
        ),
        _chunk(
            chunk_id="session:current:analysis:nightlight.summary",
            kind="analysis",
            domain="nightlight",
            title="夜光活力摘要",
            content=_text(nightlight_pattern.get("summary_text")) or _text(nightlight_summary),
            metrics={**_compact_metrics(nightlight_summary, ["total_radiance", "mean_radiance", "max_radiance", "lit_pixel_ratio"]), **_compact_metrics(nightlight_pattern, ["core_hotspot_count", "hotspot_cell_ratio", "economic_activity_intensity_level", "peak_to_edge_ratio"])},
            source_artifacts=_source_present(artifacts, snapshot, "current_nightlight_summary", "nightlight") + ["current_nightlight_pattern_analysis"],
            warnings=[NIGHTLIGHT_WARNING],
        ),
        _chunk(
            chunk_id="session:current:analysis:road.summary",
            kind="analysis",
            domain="road",
            title="路网句法摘要",
            content=_text(road_pattern.get("summary_text")) or _text(road_summary),
            metrics={**_compact_metrics(road_summary, ["node_count", "edge_count", "avg_choice", "avg_connectivity"]), **_compact_metrics(road_pattern, ["regression_r2", "connectivity_signal", "access_signal", "readability_signal"])},
            source_artifacts=_source_present(artifacts, snapshot, "current_road_summary", "road") + ["current_road_pattern_analysis"],
            warnings=[ROAD_WARNING],
        ),
    ]

    site_selection = _safe_dict(artifacts.get("site_selection_pack"))
    candidates = _safe_list(site_selection.get("candidates") or site_selection.get("candidate_sites") or site_selection.get("candidate_zones"))
    if not candidates:
        candidates = _safe_list(_safe_dict(artifacts.get("current_target_supply_gap")).get("candidate_zones"))
    raw_chunks.append(
        _chunk(
            chunk_id="session:current:analysis:site_selection.candidates",
            kind="analysis",
            domain="site_selection",
            title="选址候选点摘要",
            content=" ".join([_text(site_selection.get("summary_text")), _text(candidates[:5])]),
            metrics={"candidate_count": len(candidates), "candidates": candidates[:5]},
            source_artifacts=[key for key in ("site_selection_pack", "current_target_supply_gap", "current_site_candidate_scores") if artifacts.get(key)],
            warnings=[POI_WARNING, NIGHTLIGHT_WARNING, POPULATION_WARNING, ROAD_WARNING],
        )
    )

    for item in raw_chunks:
        if item is not None:
            chunks.append(item)
    chunks.extend(_poi_record_chunks(snapshot, artifacts))
    chunks.extend(_map_search_context_chunks(artifacts))
    return chunks


def build_report_chunks(snapshot: AnalysisSnapshot, artifacts: Dict[str, Any]) -> List[KnowledgeChunk]:
    del snapshot
    chunks: List[KnowledgeChunk] = []
    summary_pack = _safe_dict(artifacts.get("summary_pack"))
    if not summary_pack:
        summary_pack = _safe_dict(artifacts.get("current_summary_pack"))
    report_payloads = [
        _safe_dict(artifacts.get("area_character_pack")),
        _safe_dict(artifacts.get("site_selection_pack")),
        summary_pack,
    ]

    for source_index, payload in enumerate(report_payloads):
        if not payload:
            continue
        prefix = "report" if source_index == 2 else ("area_character" if source_index == 0 else "site_selection")
        title = str(payload.get("report_title") or payload.get("title") or payload.get("headline") or "分析报告").strip()
        summary_text = str(
            payload.get("report_content")
            or payload.get("summary_text")
            or _safe_dict(payload.get("headline_judgment")).get("summary")
            or ""
        ).strip()
        summary_chunk = _chunk(
            chunk_id=f"session:current:report:{prefix}.summary",
            kind="report",
            domain="report",
            title=title,
            content=summary_text,
            metrics={},
            source_artifacts=[key for key in ("summary_pack", "area_character_pack", "site_selection_pack") if artifacts.get(key)],
            evidence_level="report_text",
        )
        if summary_chunk:
            chunks.append(summary_chunk)

        sections = _safe_list(payload.get("report_sections"))
        if not sections and summary_pack:
            sections = [
                {"key": key, "heading": _safe_dict(value).get("title") or key, "paragraphs": [_safe_dict(value).get("reasoning") or _safe_dict(value).get("summary") or ""]}
                for key, value in summary_pack.items()
                if isinstance(value, dict) and key not in {"prompt_snapshots", "validation_results"}
            ]
        for index, section in enumerate(sections[:12]):
            item = _safe_dict(section)
            section_key = str(item.get("key") or item.get("id") or item.get("heading") or f"section-{index + 1}").strip()
            section_key = ".".join(part for part in section_key.lower().replace(" ", "_").split(".") if part)[:80]
            paragraphs = item.get("paragraphs")
            content = "\n".join(str(part) for part in paragraphs if str(part).strip()) if isinstance(paragraphs, list) else str(item.get("content") or item.get("reasoning") or "")
            chunk = _chunk(
                chunk_id=f"session:current:report:section.{section_key}",
                kind="report",
                domain="report",
                title=str(item.get("heading") or item.get("title") or section_key).strip(),
                content=content,
                metrics={key: item.get(key) for key in ("evidence_refs", "score", "status") if item.get(key) not in (None, "", [], {})},
                source_artifacts=[key for key in ("summary_pack", "area_character_pack", "site_selection_pack") if artifacts.get(key)],
                evidence_level="report_text",
            )
            if chunk:
                chunks.append(chunk)

    evidence_refs = _safe_list(summary_pack.get("evidence_refs"))
    if evidence_refs:
        evidence_chunk = _chunk(
            chunk_id="session:current:report:evidence_chain",
            kind="report",
            domain="report",
            title="报告证据链",
            content=_text(evidence_refs),
            metrics={"evidence_refs": evidence_refs[:20]},
            source_artifacts=["summary_pack"],
            evidence_level="report_evidence",
        )
        if evidence_chunk:
            chunks.append(evidence_chunk)

    audit_notes = _safe_list(summary_pack.get("validation_results")) or _safe_list(summary_pack.get("audit_notes"))
    if audit_notes:
        audit_chunk = _chunk(
            chunk_id="session:current:report:audit_notes",
            kind="report",
            domain="report",
            title="报告审计说明",
            content=_text(audit_notes),
            metrics={"audit_notes": audit_notes[:20]},
            source_artifacts=["summary_pack"],
            evidence_level="audit_note",
        )
        if audit_chunk:
            chunks.append(audit_chunk)
    return chunks
