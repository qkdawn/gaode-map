"""Approved template registry for the Wave 5 visual-evidence editor.

The registry keeps editorial selection separate from rendering.  The editor can
choose *whether* a chart belongs next to an already-reviewed decision, while the
renderer retains ownership of metric validation and SVG generation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .schemas import ReportVisualTemplateId, VisualPlan

AGE_ANCHOR = "由此形成四类优先使用情境："
DIRECTION_ANCHOR = "现状大门应设置"
POI_ROUTE_MAP_ANCHOR = "<!-- report-anchor:poi-route-map -->"
POI_SUPPLY_STRUCTURE_ANCHOR = "<!-- report-anchor:poi-supply-structure -->"


@dataclass(frozen=True)
class ApprovedVisualTemplate:
    template_id: ReportVisualTemplateId
    title: str
    caption: str
    filename: str
    required_metric_ids: tuple[str, ...]
    required_anchor: str


APPROVED_TEMPLATE_REGISTRY: dict[ReportVisualTemplateId, ApprovedVisualTemplate] = {
    "population_age_structure": ApprovedVisualTemplate(
        "population_age_structure", "15 分钟范围居住背景的年龄结构", "人口反映居住背景，不等同于客流、到访概率或支付能力。",
        "population-age-structure", ("population.age_structure",), AGE_ANCHOR,
    ),
    "directional_action_priority_matrix": ApprovedVisualTemplate(
        "directional_action_priority_matrix", "方向 × 距离圈层的首轮行动优先级", "规则结果只表达行动优先级，不表示真实进场量、客流预测或消费。",
        "directional-action-priority", ("regional.directional_evidence_matrix",), DIRECTION_ANCHOR,
    ),
    "focused_poi_walking_route_map": ApprovedVisualTemplate(
        "focused_poi_walking_route_map", "重点 POI 步行路线与当前路网", "图中路线由当前 road_edges 快照上、从指标结果记录的统一分析起点至 POI 的本地最短路径计算得到；分钟按统一 4.5 km/h 参考步行速度换算。它不表示合作关系、客流导入、消费转化、经营质量或市场规模。",
        "focused-poi-walking-route-map", ("poi.focused_accessibility",), POI_ROUTE_MAP_ANCHOR,
    ),
    "poi_supply_structure": ApprovedVisualTemplate(
        "poi_supply_structure", "15 分钟等时圈内的 POI 供给结构", "统计对象为逐点经保存的 15 分钟步行等时圈几何核验后的 POI；“≤5 分钟道路可达”仅在保存 road_edges 能形成连续道路路径时显示，未出现不代表 0。它不表示项目定位、客流、消费、经营质量、市场规模或合作关系。",
        "poi-supply-structure", ("poi.supply_structure",), POI_SUPPLY_STRUCTURE_ANCHOR,
    ),
}


def validate_visual_plan(plan: VisualPlan) -> VisualPlan:
    """Reject plans that drift outside the narrow approved template contract."""
    for item in plan.items:
        definition = APPROVED_TEMPLATE_REGISTRY[item.template_id]
        if item.chapter_anchor != definition.required_anchor:
            raise ValueError(f"{item.template_id} must use its approved report anchor")
        missing = set(definition.required_metric_ids).difference(item.metric_ids)
        if missing:
            raise ValueError(f"{item.template_id} is missing required metric ids: {', '.join(sorted(missing))}")
    return plan
