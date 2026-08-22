from __future__ import annotations

from typing import Any, Dict

from modules.providers.amap.utils.get_type_info import infer_type_info_from_text, resolve_type_info

from ..analysis_extractors import (
    analyze_target_supply_gap,
    build_h3_structure_analysis,
)
from ..schemas import AnalysisSnapshot, ToolResult


async def analyze_target_supply_gap_from_scope(
    *,
    arguments: Dict[str, Any],
    snapshot: AnalysisSnapshot,
    artifacts: Dict[str, Any],
    question: str,
) -> ToolResult:
    place_type = str(arguments.get("place_type") or "").strip()
    target = resolve_type_info(place_type) if place_type else infer_type_info_from_text(question)
    resolved_place_type = str((target or {}).get("label") or place_type).strip()
    h3_structure = (
        dict(artifacts.get("current_h3_structure_analysis"))
        if isinstance(artifacts.get("current_h3_structure_analysis"), dict)
        else build_h3_structure_analysis(snapshot, artifacts)
    )
    payload = analyze_target_supply_gap(
        snapshot,
        artifacts,
        place_type=resolved_place_type,
        h3_structure=h3_structure,
    )
    return ToolResult(
        tool_name="analyze_target_supply_gap",
        status="success",
        result=payload,
        evidence=[
            {"field": "target_supply_gap.place_type", "value": payload.get("place_type")},
            {"field": "target_supply_gap.candidate_count", "value": payload.get("candidate_count")},
            {"field": "target_supply_gap.max_gap_value", "value": payload.get("max_gap_value")},
        ],
        artifacts={
            "current_h3_structure_analysis": h3_structure,
            "current_target_supply_gap": payload,
        },
    )
