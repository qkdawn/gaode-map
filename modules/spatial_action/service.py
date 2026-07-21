from __future__ import annotations

from collections import deque
from typing import Any, Iterable

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from .schemas import (
    LocalizedPatternCell,
    LocalizedPatternInputCell,
    LocalizedPatternResult,
    LocalizedPatternZone,
)


def _bh_adjust(raw: list[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted(raw, key=lambda item: item[1])
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 1.0
    for reverse_index in range(count - 1, -1, -1):
        cell_id, p_value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_value * count / rank)
        adjusted[cell_id] = min(1.0, running)
    return adjusted


def _adjacency(cells: list[LocalizedPatternInputCell]) -> dict[str, set[str]]:
    ids = {cell.cell_id for cell in cells}
    adjacency = {cell.cell_id: set(cell.neighbor_ids).intersection(ids) for cell in cells}
    geoms = {cell.cell_id: shape(cell.geometry) for cell in cells}
    for index, left in enumerate(cells):
        for right in cells[index + 1 :]:
            if right.cell_id in adjacency[left.cell_id] or left.cell_id in adjacency[right.cell_id]:
                adjacency[left.cell_id].add(right.cell_id)
                adjacency[right.cell_id].add(left.cell_id)
                continue
            left_geom = geoms[left.cell_id]
            right_geom = geoms[right.cell_id]
            if left_geom.touches(right_geom) or left_geom.intersects(right_geom):
                adjacency[left.cell_id].add(right.cell_id)
                adjacency[right.cell_id].add(left.cell_id)
    return adjacency


def _components(selected: dict[str, str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    remaining = set(selected)
    groups: list[list[str]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        pattern_type = selected[seed]
        queue = deque([seed])
        group = [seed]
        while queue:
            current = queue.popleft()
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in remaining and selected.get(neighbor) == pattern_type:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
                    group.append(neighbor)
        groups.append(sorted(group))
    return groups


class SpatialActionService:
    """Build addressable local spatial patterns from existing metric cells."""

    def analyze_local_patterns(
        self,
        cells: Iterable[LocalizedPatternInputCell | dict[str, Any]],
        *,
        alpha: float = 0.05,
    ) -> LocalizedPatternResult:
        normalized = [
            item
            if isinstance(item, LocalizedPatternInputCell)
            else LocalizedPatternInputCell.model_validate(item)
            for item in cells
        ]
        if not normalized:
            return LocalizedPatternResult(
                evidence_state="proxy",
                pattern_label="无局部模式",
                cells=[],
                zones=[],
                diagnostics=["no_cells"],
            )
        adjacency = _adjacency(normalized)
        raw_p = [
            (cell.cell_id, cell.p_value)
            for cell in normalized
            if cell.p_value is not None
        ]
        has_significance = bool(raw_p)
        adjusted = _bh_adjust([(cell_id, float(value)) for cell_id, value in raw_p])
        selected: dict[str, str] = {}
        diagnostics: list[str] = []
        if has_significance:
            for cell in normalized:
                adjusted_value = (
                    cell.adjusted_p_value
                    if cell.adjusted_p_value is not None
                    else adjusted.get(cell.cell_id)
                )
                if adjusted_value is None or adjusted_value > alpha:
                    continue
                selected[cell.cell_id] = (
                    cell.cluster_type
                    if cell.cluster_type == "hotspot" and adjacency[cell.cell_id]
                    else "local_outlier"
                )
            evidence_state = "measured"
            pattern_label = "显著局部空间模式"
            significance_method = "benjamini_hochberg_fdr"
        else:
            ordered = sorted(normalized, key=lambda item: item.value)
            threshold = ordered[max(0, int(len(ordered) * 0.75) - 1)].value
            selected = {
                cell.cell_id: "high_value_cluster"
                for cell in normalized
                if cell.value >= threshold
            }
            evidence_state = "proxy"
            pattern_label = "高值集中区"
            significance_method = "upper_quartile_proxy"
            diagnostics.append("p_values_missing_not_statistical_hotspot")
        by_id = {cell.cell_id: cell for cell in normalized}
        output_cells: list[LocalizedPatternCell] = []
        zones: list[LocalizedPatternZone] = []
        for zone_index, cell_ids in enumerate(_components(selected, adjacency), start=1):
            pattern_type = selected[cell_ids[0]]
            zone_id = f"zone:{pattern_type}:{zone_index:03d}"
            zone_geometry = unary_union([shape(by_id[cell_id].geometry) for cell_id in cell_ids])
            zones.append(
                LocalizedPatternZone(
                    zone_id=zone_id,
                    pattern_type=pattern_type,
                    cell_ids=cell_ids,
                    geometry=mapping(zone_geometry),
                    source_metric_ids=sorted({by_id[cell_id].metric_id for cell_id in cell_ids}),
                    significance_method=significance_method,
                )
            )
            for cell_id in cell_ids:
                cell = by_id[cell_id]
                output_cells.append(
                    LocalizedPatternCell(
                        cell_id=cell.cell_id,
                        metric_id=cell.metric_id,
                        value=cell.value,
                        statistic=cell.statistic,
                        z_score=cell.z_score,
                        p_value=cell.p_value,
                        adjusted_p_value=(
                            cell.adjusted_p_value
                            if cell.adjusted_p_value is not None
                            else adjusted.get(cell.cell_id)
                        ),
                        cluster_type=selected[cell_id],
                        zone_id=zone_id,
                    )
                )
        return LocalizedPatternResult(
            evidence_state=evidence_state,
            pattern_label=pattern_label,
            cells=sorted(output_cells, key=lambda item: item.cell_id),
            zones=zones,
            diagnostics=diagnostics,
        )
