from __future__ import annotations

import math
from numbers import Real
from typing import Any, AsyncIterator, Dict, List

from .analysis_extractors import (
    analyze_poi_mix,
    build_h3_structure_analysis,
    build_nightlight_pattern_analysis,
    build_poi_structure_analysis,
    build_population_profile_analysis,
    build_road_pattern_analysis,
    detect_commercial_hotspots,
    infer_area_character_labels,
    is_h3_structure_ready,
    is_nightlight_pattern_ready,
    is_poi_structure_ready,
    is_population_profile_ready,
    is_road_pattern_ready,
)
from .schemas import (
    AgentSummaryGenerateResponse,
    AgentSummaryProgressStep,
    AgentSummaryReadinessResponse,
    AgentSummaryRequest,
    AgentSummaryStreamEvent,
)
from .providers.llm_provider import _invoke_json_role, is_llm_enabled
from .synthesizer import build_citations, build_summary_panel_payloads
from .tool_adapters.capability_tools import ensure_area_data_readiness
from .tool_adapters.scenario_tools import run_area_character_pack

_DIMENSION_ORDER = ["poi", "h3", "population", "nightlight", "road"]
_DIMENSION_TO_TASK = {
    "poi": "poi_grid",
    "h3": "poi_grid",
    "population": "population",
    "nightlight": "nightlight",
    "road": "road_syntax",
}
_STRUCTURED_TASK_ORDER = ["poi_structure", "spatial_structure", "area_labels"]
_PHASE_ORDER = ["precheck", "fetch_missing", "derive_analysis", "analysis_started"]
_SUMMARY_SECTION_SPECS = [
    ("spatial_structure", "空间结构"),
    ("poi_structure", "POI结构"),
    ("consumption_vitality", "经济活动强度"),
    ("business_support", "业态承接"),
]
_SPATIAL_DIMENSION_SPECS = [
    ("aggregation", "集聚性"),
    ("mixing", "混合性"),
    ("morphology", "形态性"),
]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            return None
        if number.is_integer():
            return int(number)
        return number
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _build_progress_steps(phases: List[str], *, failed: bool = False) -> List[AgentSummaryProgressStep]:
    completed = set(phases or [])
    active = ""
    for phase in reversed(_PHASE_ORDER):
        if phase in completed:
            active = phase
            break
    steps: List[AgentSummaryProgressStep] = []
    for phase in _PHASE_ORDER:
        status = "pending"
        if phase in completed:
            status = "completed"
        elif active and _PHASE_ORDER.index(phase) == _PHASE_ORDER.index(active) + 1:
            status = "running"
        steps.append(AgentSummaryProgressStep(key=phase, label=phase, status=status))
    if failed and steps:
        # mark current running step failed; if none running, fail the last completed phase
        running_index = next((idx for idx, item in enumerate(steps) if item.status == "running"), -1)
        if running_index >= 0:
            steps[running_index].status = "failed"
        else:
            completed_index = max((idx for idx, item in enumerate(steps) if item.status == "completed"), default=-1)
            if completed_index >= 0:
                steps[completed_index].status = "failed"
    return steps


def _derive_structured_status(snapshot: Any, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    poi_structure = (
        dict(artifacts.get("current_poi_structure_analysis") or {})
        if isinstance(artifacts.get("current_poi_structure_analysis"), dict)
        else build_poi_structure_analysis(snapshot, artifacts)
    )
    h3_structure = (
        dict(artifacts.get("current_h3_structure_analysis") or {})
        if isinstance(artifacts.get("current_h3_structure_analysis"), dict)
        else build_h3_structure_analysis(snapshot, artifacts)
    )
    population_profile = (
        dict(artifacts.get("current_population_profile_analysis") or {})
        if isinstance(artifacts.get("current_population_profile_analysis"), dict)
        else build_population_profile_analysis(snapshot, artifacts)
    )
    nightlight_pattern = (
        dict(artifacts.get("current_nightlight_pattern_analysis") or {})
        if isinstance(artifacts.get("current_nightlight_pattern_analysis"), dict)
        else build_nightlight_pattern_analysis(snapshot, artifacts)
    )
    road_pattern = (
        dict(artifacts.get("current_road_pattern_analysis") or {})
        if isinstance(artifacts.get("current_road_pattern_analysis"), dict)
        else build_road_pattern_analysis(snapshot, artifacts)
    )
    business_profile = (
        dict(artifacts.get("current_business_profile") or {})
        if isinstance(artifacts.get("current_business_profile"), dict)
        else analyze_poi_mix(snapshot, artifacts, poi_structure=poi_structure)
    )
    area_labels = (
        dict(artifacts.get("current_area_character_labels") or {})
        if isinstance(artifacts.get("current_area_character_labels"), dict)
        else infer_area_character_labels(
            snapshot,
            artifacts,
            poi_structure=poi_structure,
            business_profile=business_profile,
            population_profile=population_profile,
            nightlight_pattern=nightlight_pattern,
            road_pattern=road_pattern,
        )
    )

    missing_tasks: List[str] = []
    if not is_poi_structure_ready(poi_structure):
        missing_tasks.append("poi_structure")
    if not (
        is_h3_structure_ready(h3_structure)
        and is_population_profile_ready(population_profile)
        and is_nightlight_pattern_ready(nightlight_pattern)
        and is_road_pattern_ready(road_pattern)
    ):
        missing_tasks.append("spatial_structure")
    if not bool((area_labels.get("character_tags") or [])):
        missing_tasks.append("area_labels")

    return {
        "missing_tasks": missing_tasks,
        "artifacts": {
            "current_poi_structure_analysis": poi_structure,
            "current_h3_structure_analysis": h3_structure,
            "current_population_profile_analysis": population_profile,
            "current_nightlight_pattern_analysis": nightlight_pattern,
            "current_road_pattern_analysis": road_pattern,
            "current_business_profile": business_profile,
            "current_area_character_labels": area_labels,
        },
    }


def _normalize_data_readiness(
    payload: Dict[str, Any],
    *,
    structured_missing_tasks: List[str] | None = None,
    extra_fetched: List[str] | None = None,
    extra_reused: List[str] | None = None,
) -> Dict[str, Any]:
    data_readiness = dict(payload.get("data_readiness") or {})
    reused = [str(item) for item in (data_readiness.get("reused") or []) if str(item).strip()]
    fetched = [str(item) for item in (data_readiness.get("fetched") or []) if str(item).strip()]
    for item in (extra_reused or []):
        text = str(item).strip()
        if text and text not in reused:
            reused.append(text)
    for item in (extra_fetched or []):
        text = str(item).strip()
        if text and text not in fetched:
            fetched.append(text)
    completed_dimensions = {key for key in reused + fetched if key in _DIMENSION_ORDER}
    missing_dimensions = [key for key in _DIMENSION_ORDER if key not in completed_dimensions]
    missing_tasks: List[str] = []
    for dim in missing_dimensions:
        task_key = _DIMENSION_TO_TASK.get(dim)
        if task_key and task_key not in missing_tasks:
            missing_tasks.append(task_key)
    for task in (structured_missing_tasks or []):
        task_key = str(task).strip()
        if task_key and task_key not in missing_tasks:
            missing_tasks.append(task_key)
    ready = bool(data_readiness.get("ready")) and not missing_tasks
    return {
        "checked": bool(data_readiness.get("checked")),
        "ready": ready,
        "missing_tasks": missing_tasks,
        "reused": reused,
        "fetched": fetched,
    }


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _current_summary(snapshot: Any, artifacts: Dict[str, Any], key: str) -> Dict[str, Any]:
    artifact = artifacts.get(f"current_{key}_summary")
    if isinstance(artifact, dict):
        return dict(artifact)
    payload = getattr(snapshot, key, {})
    if isinstance(payload, dict) and isinstance(payload.get("summary"), dict):
        return dict(payload.get("summary") or {})
    return {}


def _current_commercial_hotspots(snapshot: Any, artifacts: Dict[str, Any], h3_structure: Dict[str, Any]) -> Dict[str, Any]:
    payload = artifacts.get("current_commercial_hotspots")
    if isinstance(payload, dict):
        return dict(payload)
    return detect_commercial_hotspots(snapshot, artifacts, h3_structure=h3_structure)


def _normalize_summary_section_key(value: Any) -> str:
    text = _clean_text(value).lower()
    if text in {key for key, _ in _SUMMARY_SECTION_SPECS}:
        return text
    aliases = {
        "空间结构": "spatial_structure",
        "结构": "spatial_structure",
        "poi_structure": "poi_structure",
        "poi结构": "poi_structure",
        "POI结构": "poi_structure",
        "业态结构": "poi_structure",
        "POI占比": "poi_structure",
        "consumption_vitality": "consumption_vitality",
        "消费活力": "consumption_vitality",
        "商业活力": "consumption_vitality",
        "经济活动强度": "consumption_vitality",
        "夜间经济活动强度": "consumption_vitality",
        "business_support": "business_support",
        "业态承接": "business_support",
        "业态支撑": "business_support",
        "商业承接": "business_support",
    }
    return aliases.get(_clean_text(value), "")


def _section_title_for(key: str) -> str:
    for item_key, label in _SUMMARY_SECTION_SPECS:
        if item_key == key:
            return label
    return ""


def _normalize_spatial_dimension_key(value: Any) -> str:
    text = _clean_text(value).lower()
    if text in {key for key, _ in _SPATIAL_DIMENSION_SPECS}:
        return text
    aliases = {
        "集聚性": "aggregation",
        "混合性": "mixing",
        "形态性": "morphology",
    }
    return aliases.get(_clean_text(value), "")


def _normalize_spatial_dimensions(items: Any) -> List[Dict[str, str]]:
    rows = items if isinstance(items, list) else []
    normalized: List[Dict[str, str]] = []
    for expected_key, expected_label in _SPATIAL_DIMENSION_SPECS:
        matched = next(
            (
                item for item in rows
                if isinstance(item, dict) and _normalize_spatial_dimension_key(item.get("key") or item.get("label")) == expected_key
            ),
            None,
        )
        conclusion = _clean_text((matched or {}).get("conclusion"))
        if conclusion:
            normalized.append({"key": expected_key, "label": expected_label, "conclusion": conclusion})
    return normalized


def _should_rewrite_section_reasoning(key: str, text: str) -> bool:
    content = _clean_text(text)
    if not content:
        return True
    if key == "consumption_vitality" and any(
        token in content
        for token in ("消费能力", "客流", "营业额", "白天活跃", "日间消费", "消费强度", "消费活力", "全天候经济活动")
    ):
        return True
    descriptive_openers = {
        "poi_structure": ("POI构成", "POI结构"),
        "consumption_vitality": ("夜光模式", "夜间灯光", "经济活动强度", "夜间经济活动强度", "消费活力"),
        "business_support": ("路网条件", "路网结构", "空间条件"),
    }
    if any(content.startswith(prefix) for prefix in descriptive_openers.get(key, ())):
        return True
    if any(token in content for token in ("反映了", "揭示了", "提供了", "体现了", "呈现了")):
        judgment_tokens = ("主导", "偏", "较强", "较弱", "明显", "有限", "集中", "分散", "承接", "活跃", "不足", "更像", "适合")
        return not any(token in content for token in judgment_tokens)
    return False


_ECONOMIC_ACTIVITY_LEVEL_LABELS = {
    "high": "高",
    "medium_high": "中等偏上",
    "medium": "中等",
    "low": "偏低",
}

_DIRECTION_TO_ROAD_AXES = {
    "东": {"东西向"},
    "西": {"东西向"},
    "北": {"南北向"},
    "南": {"南北向"},
    "东北": {"东北-西南向"},
    "西南": {"东北-西南向"},
    "西北": {"西北-东南向"},
    "东南": {"西北-东南向"},
}


def _economic_activity_level_label(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return "偏低"
    return _ECONOMIC_ACTIVITY_LEVEL_LABELS.get(text, text)


def _direction_phrase(dominant: str, secondary: str) -> str:
    if dominant and secondary:
        return f"{dominant}及{secondary}"
    return dominant or secondary


def _orientation_phrase(dominant: str, secondary: str) -> str:
    if dominant and secondary:
        return f"区域道路以{dominant}为主，{secondary}为辅。"
    if dominant:
        return f"区域道路以{dominant}为主。"
    if secondary:
        return f"区域道路以{secondary}为辅。"
    return ""


def _direction_matches_orientation(direction: str, orientation: str) -> bool:
    return bool(direction and orientation and orientation in _DIRECTION_TO_ROAD_AXES.get(direction, set()))


def _classify_direction_orientation_consistency(
    dominant_direction: str,
    secondary_direction: str,
    dominant_orientation: str,
    secondary_orientation: str,
) -> tuple[str, str]:
    orientations = [item for item in [dominant_orientation, secondary_orientation] if item]
    if dominant_direction and any(_direction_matches_orientation(dominant_direction, item) for item in orientations):
        return "高度一致", "较明显"
    if secondary_direction and any(_direction_matches_orientation(secondary_direction, item) for item in orientations):
        return "部分一致", "具有一定支撑"
    return "一致性较弱", "相对有限"


def _build_economic_activity_direction_judgment(source_payload: Dict[str, Any]) -> str:
    nightlight = source_payload.get("nightlight_pattern") if isinstance(source_payload.get("nightlight_pattern"), dict) else {}
    road = source_payload.get("road_pattern") if isinstance(source_payload.get("road_pattern"), dict) else {}
    sector = nightlight.get("sector_direction_analysis") if isinstance(nightlight.get("sector_direction_analysis"), dict) else {}
    orientation = road.get("road_orientation_analysis") if isinstance(road.get("road_orientation_analysis"), dict) else {}

    level = _economic_activity_level_label(nightlight.get("economic_activity_intensity_level"))
    dominant_direction = _clean_text(sector.get("dominant_direction"))
    secondary_direction = _clean_text(sector.get("secondary_direction"))
    dominant_orientation = _clean_text(orientation.get("dominant_orientation"))
    secondary_orientation = _clean_text(orientation.get("secondary_orientation"))
    direction_text = _direction_phrase(dominant_direction, secondary_direction)

    if not direction_text:
        return ""
    first = f"从空间分布来看，等时圈内夜间经济活动整体处于{level}水平，高值区域主要集中在{direction_text}方向。"
    road_text = _orientation_phrase(dominant_orientation, secondary_orientation)
    if not road_text:
        return first
    consistency, influence = _classify_direction_orientation_consistency(
        dominant_direction,
        secondary_direction,
        dominant_orientation,
        secondary_orientation,
    )
    return f"{first}{road_text}两者在空间上呈现{consistency}关系，表明交通廊道对夜间经济活动的空间引导作用{influence}。"


def _build_poi_structure_judgment(source_payload: Dict[str, Any]) -> str:
    poi = source_payload.get("poi_structure") if isinstance(source_payload.get("poi_structure"), dict) else {}
    business = source_payload.get("business_profile") if isinstance(source_payload.get("business_profile"), dict) else {}
    tags = [str(item).strip() for item in (poi.get("structure_tags") or []) if str(item).strip()]
    dominant = [str(item).strip() for item in (poi.get("dominant_categories") or []) if str(item).strip()]
    business_label = _clean_text(business.get("label"))
    if "生活消费主导" in tags or business_label == "生活消费主导":
        first = "业态以生活消费为主"
    elif business_label:
        first = f"业态呈现{business_label}特征"
    elif tags:
        first = f"业态以{tags[0]}为主"
    else:
        first = "业态结构已有明确主次"
    if len(dominant) >= 2:
        second = f"{dominant[0]}与{dominant[1]}构成主要供给"
    elif dominant:
        second = f"{dominant[0]}是最核心的供给类型"
    else:
        second = ""
    extras = [item for item in tags if item not in {business_label, "生活消费主导"}]
    third = f"{extras[0]}进一步强化了功能定位" if extras else ""
    return "，".join(part for part in [first, second, third] if part) + "。"


def _build_consumption_vitality_judgment(source_payload: Dict[str, Any]) -> str:
    nightlight = source_payload.get("nightlight_pattern") if isinstance(source_payload.get("nightlight_pattern"), dict) else {}
    direction_judgment = _build_economic_activity_direction_judgment(source_payload)
    if direction_judgment:
        return direction_judgment
    summary_text = _clean_text(nightlight.get("economic_activity_summary_text"))
    if summary_text:
        return summary_text
    pattern_tags = [str(item).strip() for item in (nightlight.get("pattern_tags") or []) if str(item).strip()]
    core_hotspot_count = int(nightlight.get("core_hotspot_count") or 0)
    if core_hotspot_count > 0:
        first = "夜间经济活动存在明确热点"
    elif any("亮灯覆盖高" in item for item in pattern_tags):
        first = "夜间灯光覆盖较广但强核心不足"
    else:
        first = "夜间经济活动强度整体偏弱"
    if any("中心亮度突出" in item for item in pattern_tags):
        second = "经济活动强度更容易集中在少数核心点位"
    elif core_hotspot_count > 0:
        second = "高值区主要体现为夜间活动与照明强度信号"
    else:
        second = "夜光证据不足时不推断白天经济活动表现"
    return "，".join(part for part in [first, second] if part) + "。"


def _build_business_support_judgment(source_payload: Dict[str, Any]) -> str:
    road = source_payload.get("road_pattern") if isinstance(source_payload.get("road_pattern"), dict) else {}
    business = source_payload.get("business_profile") if isinstance(source_payload.get("business_profile"), dict) else {}
    connectivity = _clean_text(((road.get("connectivity") or {}).get("signal")))
    access = _clean_text(((road.get("access") or {}).get("signal")))
    readability = _clean_text(((road.get("readability") or {}).get("signal")))
    business_label = _clean_text(business.get("label")) or "当前业态"

    connectivity_sentence = {
        "strong": "内部路网连通顺畅，节点之间互达性较好",
        "moderate": "内部路网连通性中等，片区内到达基本顺畅",
        "weak": "内部路网连通偏弱，局部转换效率受限",
    }.get(connectivity, "内部路网已有基本支撑")
    access_sentence = {
        "strong": "主路径承接能力较强，更容易形成稳定通行流",
        "moderate": "通达效率中等，更适合片区内日常通行",
        "weak": "被经过与主路径承接能力有限，难以形成高流动性优势",
    }.get(access, "")
    readability_sentence = {
        "strong": "动线识别清晰，有利于组织消费动线",
        "moderate": "动线可读性尚可，商业识别成本可控",
        "weak": "动线可读性有限，不利于快速识别与导流",
    }.get(readability, "")

    strong_count = sum(1 for item in (connectivity, access, readability) if item == "strong")
    weak_count = sum(1 for item in (connectivity, access, readability) if item == "weak")
    if strong_count >= 2:
        closing = f"整体上对{business_label}的空间承接较强。"
    elif weak_count >= 2:
        closing = f"整体更适合片区内日常服务，对{business_label}的扩张承接偏谨慎。"
    else:
        closing = f"整体能承接{business_label}，但更偏向中等强度的片区服务。"
    return "。".join(part for part in [connectivity_sentence, access_sentence, readability_sentence] if part) + f"。{closing}"


def _normalize_area_judgment_reasoning(pack: Dict[str, Any], source_payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(pack or {})
    for key, _ in _SUMMARY_SECTION_SPECS:
        row = dict(normalized.get(key) or {}) if isinstance(normalized.get(key), dict) else {}
        if not row:
            continue
        reasoning = _clean_text(row.get("reasoning"))
        if key == "poi_structure" and _should_rewrite_section_reasoning(key, reasoning):
            row["reasoning"] = _build_poi_structure_judgment(source_payload)
        elif key == "consumption_vitality" and _should_rewrite_section_reasoning(key, reasoning):
            row["reasoning"] = _build_consumption_vitality_judgment(source_payload)
        elif key == "business_support" and _should_rewrite_section_reasoning(key, reasoning):
            row["reasoning"] = _build_business_support_judgment(source_payload)
        normalized[key] = row
    return normalized


def _normalize_secondary_reasoning_with_judgment(pack: Dict[str, Any], source_payload: Dict[str, Any]) -> Dict[str, Any]:
    return _normalize_area_judgment_reasoning(pack, source_payload)


def _build_section_generation_prompt(section_key: str) -> str:
    title = _section_title_for(section_key)
    base = (
        "你是 gaode-map 的商业总结撰写器。"
        "现在只生成一个区域判断卡片，必须输出 JSON，不要输出 markdown。"
    )
    if section_key == "spatial_structure":
        return (
            base
            + "JSON 结构固定为："
            + "{\"section_key\":\"spatial_structure\",\"title\":\"空间结构\",\"reasoning\":\"...\",\"dimensions\":["
            + "{\"key\":\"aggregation\",\"label\":\"集聚性\",\"conclusion\":\"...\"},"
            + "{\"key\":\"mixing\",\"label\":\"混合性\",\"conclusion\":\"...\"},"
            + "{\"key\":\"morphology\",\"label\":\"形态性\",\"conclusion\":\"...\"}"
            + "]}"
            + "规则："
            + "1. 只回答这个圈的空间组织，不要写人口、夜光、客户画像。"
            + "2. reasoning 必须是商业判断句，不要写成指标描述。"
            + "3. dimensions 固定输出 aggregation、mixing、morphology 三条。"
        )
    focus_rules = {
        "poi_structure": "只写主导业态、占比结构和功能特征，要写成判断句，不要写成“反映了/体现了”。",
        "consumption_vitality": (
            "只写夜间经济活动强度，不写消费能力、客流、营业额、白天活跃或日间消费。"
            "优先使用 nightlight_pattern.sector_direction_analysis 与 road_pattern.road_orientation_analysis，"
            "按“夜光高值方位 × 路网走向一致性”写判断："
            "从空间分布来看，等时圈内夜间经济活动整体处于{强度水平}，高值区域主要集中在{夜光主导方位}及{夜光次主导方位}方向。"
            "区域道路以{路网主导走向}为主，{路网次主导走向}为辅。"
            "两者在空间上呈现{一致性等级}关系，表明交通廊道对夜间经济活动的空间引导作用{影响强度}。"
            "缺少路网或夜光方位时只描述可用夜光证据，不要硬凑一致性。"
        ),
        "business_support": "只写路网与空间条件对现有业态的承接。必须先写连通性，再写通达效率，再写认知可读性，最后落到承接判断。",
    }
    return (
        base
        + "JSON 结构固定为："
        + f'{{"section_key":"{section_key}","title":"{title}","reasoning":"..."}}'
        + "规则："
        + focus_rules.get(section_key, "只写当前段落对应的商业判断。")
        + " reasoning 必须直接下判断，推荐使用“以…为主”“偏…”“较强/较弱”“明显/有限”“更适合…”等表达。"
    )


def _build_section_generation_payload(section_key: str, source_payload: Dict[str, Any]) -> Dict[str, Any]:
    common = {
        "section_key": section_key,
        "section_title": _section_title_for(section_key),
        "guardrails": {
            "write_judgment_not_description": True,
            "no_raw_metric_recital": True,
        },
    }
    if section_key == "spatial_structure":
        return {
            **common,
            "spatial_structure": dict(source_payload.get("spatial_structure") or {}),
            "area_labels": list(source_payload.get("area_labels") or []),
        }
    if section_key == "poi_structure":
        return {
            **common,
            "poi_structure": dict(source_payload.get("poi_structure") or {}),
            "business_profile": dict(source_payload.get("business_profile") or {}),
        }
    if section_key == "consumption_vitality":
        return {
            **common,
            "nightlight_pattern": dict(source_payload.get("nightlight_pattern") or {}),
            "road_pattern": dict(source_payload.get("road_pattern") or {}),
            "business_profile": dict(source_payload.get("business_profile") or {}),
        }
    if section_key == "business_support":
        return {
            **common,
            "poi_structure": dict(source_payload.get("poi_structure") or {}),
            "business_profile": dict(source_payload.get("business_profile") or {}),
            "road_pattern": dict(source_payload.get("road_pattern") or {}),
        }
    return common


def _validate_secondary_section_payload(section_key: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    key = _normalize_summary_section_key(raw.get("section_key") or raw.get("title"))
    if key != section_key:
        return {}
    reasoning = _clean_text(raw.get("reasoning"))
    if not reasoning:
        return {}
    payload: Dict[str, Any] = {
        "section_key": section_key,
        "title": _section_title_for(section_key),
        "reasoning": reasoning,
    }
    if section_key == "spatial_structure":
        dimensions = _normalize_spatial_dimensions(raw.get("dimensions"))
        if not dimensions:
            return {}
        payload["dimensions"] = dimensions
    return payload


async def _generate_summary_section_with_llm(
    section_key: str,
    section_title: str,
    source_payload: Dict[str, Any],
) -> Dict[str, Any]:
    raw = await _invoke_json_role(
        system_prompt=_build_section_generation_prompt(section_key),
        user_payload=_build_section_generation_payload(section_key, source_payload),
        emit=None,
        phase=f"summary_section_{section_key}",
        title=f"生成{section_title}判断",
        reasoning_id=f"summary-section-{section_key}",
    )
    return _validate_secondary_section_payload(section_key, raw)


async def _generate_secondary_sections_with_llm(source_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for section_key, section_title in _SUMMARY_SECTION_SPECS:
        validated = await _generate_summary_section_with_llm(section_key, section_title, source_payload)
        if not validated:
            return []
        sections.append(validated)
    return sections


def _normalize_area_judgments(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    rows_by_key: Dict[str, Dict[str, Any]] = {}
    for section_key, _ in _SUMMARY_SECTION_SPECS:
        item = raw.get(section_key)
        if not isinstance(item, dict):
            continue
        payload = _validate_secondary_section_payload(section_key, item)
        if payload:
            rows_by_key[section_key] = payload
    if len(rows_by_key) == len(_SUMMARY_SECTION_SPECS):
        return rows_by_key

    legacy_rows = raw.get("secondary_conclusions") if isinstance(raw.get("secondary_conclusions"), list) else []
    for item in legacy_rows:
        if not isinstance(item, dict):
            continue
        section_key = _normalize_summary_section_key(item.get("section_key") or item.get("title"))
        if not section_key:
            continue
        payload = _validate_secondary_section_payload(section_key, item)
        if payload:
            rows_by_key[section_key] = payload
    return rows_by_key


def _top_poi_mix(snapshot: Any) -> List[Dict[str, Any]]:
    frontend = snapshot.frontend_analysis if isinstance(snapshot.frontend_analysis, dict) else {}
    poi_panel = frontend.get("poi") if isinstance(frontend.get("poi"), dict) else {}
    category_stats = poi_panel.get("category_stats") if isinstance(poi_panel.get("category_stats"), dict) else {}
    labels = [str(item).strip() for item in (category_stats.get("labels") or []) if str(item).strip()]
    values: List[float] = []
    for item in category_stats.get("values") or []:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            values.append(0.0)
    total = sum(value for value in values if value > 0)
    pairs: List[Dict[str, Any]] = []
    for index, label in enumerate(labels):
        value = values[index] if index < len(values) else 0.0
        if value <= 0:
            continue
        ratio = round(value / total, 4) if total > 0 else 0.0
        pairs.append({"label": label, "count": int(round(value)), "ratio": ratio})
    pairs.sort(key=lambda item: item["count"], reverse=True)
    return pairs[:5]


def _derive_icsc_tags(snapshot: Any, artifacts: Dict[str, Any]) -> List[str]:
    business_profile = artifacts.get("current_business_profile") if isinstance(artifacts.get("current_business_profile"), dict) else {}
    poi_structure = artifacts.get("current_poi_structure_analysis") if isinstance(artifacts.get("current_poi_structure_analysis"), dict) else {}
    raw_tags = business_profile.get("business_types")
    if not isinstance(raw_tags, list):
        raw_tags = poi_structure.get("structure_tags")
    tags: List[str] = []
    for item in raw_tags or []:
        text = str(item).strip()
        if text and text not in tags:
            tags.append(text)
    return tags[:6]


def _legacy_summary_pack_system_prompt() -> str:
    return (
        "你是 gaode-map 的商业总结撰写器。"
        "你只负责把已给定的结构化证据整理成商业判断，不得创造新的事实。"
        "必须只输出 JSON，不要输出 markdown。"
        "JSON 结构固定为："
        "{\"headline_judgment\":{\"summary\":\"...\",\"supporting_clause\":\"...\"},"
        "\"secondary_conclusions\":[{\"title\":\"...\",\"reasoning\":\"...\"}],"
        "\"user_profile\":{\"headline\":\"...\",\"traits\":[\"...\"]},"
        "\"behavior_inference\":{\"headline\":\"...\",\"traits\":[\"...\"]}}"
        "规则："
        "1. headline_judgment.summary 必须是一句话商业判断，直接回答这个区域是什么级别或类型的商业。"
        "2. 不要把原始指标、百分比、样本量直接写成主句；不要做数据播报。"
        "3. secondary_conclusions 必须输出 2 到 4 条，每条都要写“判断 + 含义”，不能只列指标。"
        "4. user_profile 必须写消费者是谁，不能写成区域类型或商业区描述。"
        "5. behavior_inference 必须写消费行为、频次、时段或跨区吸引力，不能重复 user_profile 或 headline_judgment。"
        "6. 如果证据不足，也只能基于已给证据做保守判断，不能虚构。"
        "7. 不要输出 ICSC 标签，这部分会由系统注入。"
    )


def _legacy_build_summary_llm_payload(snapshot: Any, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    poi_structure = artifacts.get("current_poi_structure_analysis") if isinstance(artifacts.get("current_poi_structure_analysis"), dict) else {}
    h3_structure = artifacts.get("current_h3_structure_analysis") if isinstance(artifacts.get("current_h3_structure_analysis"), dict) else {}
    population_profile = artifacts.get("current_population_profile_analysis") if isinstance(artifacts.get("current_population_profile_analysis"), dict) else {}
    nightlight_pattern = artifacts.get("current_nightlight_pattern_analysis") if isinstance(artifacts.get("current_nightlight_pattern_analysis"), dict) else {}
    road_pattern = artifacts.get("current_road_pattern_analysis") if isinstance(artifacts.get("current_road_pattern_analysis"), dict) else {}
    business_profile = artifacts.get("current_business_profile") if isinstance(artifacts.get("current_business_profile"), dict) else {}
    area_labels = artifacts.get("current_area_character_labels") if isinstance(artifacts.get("current_area_character_labels"), dict) else {}
    commercial_hotspots = artifacts.get("current_commercial_hotspots") if isinstance(artifacts.get("current_commercial_hotspots"), dict) else {}
    return {
        "task": "summary_pack_generation",
        "business_profile": {
            "label": _clean_text(business_profile.get("business_profile")),
            "portrait": _clean_text(business_profile.get("portrait")),
            "summary_text": _clean_text(business_profile.get("summary_text")),
            "functional_mix_score": business_profile.get("functional_mix_score"),
        },
        "poi_structure": {
            "summary_text": _clean_text(poi_structure.get("summary_text")),
            "dominant_categories": list(poi_structure.get("dominant_categories") or []),
            "structure_tags": list(poi_structure.get("structure_tags") or []),
            "top_category_mix": _top_poi_mix(snapshot),
        },
        "spatial_structure": {
            "distribution_pattern": _clean_text(h3_structure.get("distribution_pattern")),
            "summary_text": _clean_text(h3_structure.get("summary_text")),
            "hotspot_mode": _clean_text(commercial_hotspots.get("hotspot_mode")),
            "hotspot_summary": _clean_text(commercial_hotspots.get("summary_text")),
            "core_zone_count": commercial_hotspots.get("core_zone_count"),
            "opportunity_zone_count": commercial_hotspots.get("opportunity_zone_count"),
        },
        "population_profile": {
            "summary_text": _clean_text(population_profile.get("summary_text")),
            "total_population": population_profile.get("total_population"),
            "top_age_band": _clean_text(population_profile.get("top_age_band")),
        },
        "nightlight_pattern": {
            "summary_text": _clean_text(nightlight_pattern.get("summary_text")),
            "total_radiance": nightlight_pattern.get("total_radiance"),
            "core_hotspot_count": nightlight_pattern.get("core_hotspot_count"),
        },
        "road_pattern": {
            "summary_text": _clean_text(road_pattern.get("summary_text")),
            "node_count": road_pattern.get("node_count"),
            "edge_count": road_pattern.get("edge_count"),
            "regression_r2": road_pattern.get("regression_r2"),
        },
        "area_labels": list(area_labels.get("character_tags") or []),
        "guardrails": {
            "write_business_judgment_not_data_description": True,
            "no_raw_metric_recital_as_headline": True,
            "user_profile_must_describe_people": True,
            "behavior_inference_must_describe_usage": True,
        },
    }


def _normalize_trait_list(items: Any, *, min_items: int = 2, max_items: int = 4) -> List[str]:
    traits: List[str] = []
    for item in items or []:
        text = _clean_text(item)
        if text and text not in traits:
            traits.append(text)
    if len(traits) < min_items:
        return []
    return traits[:max_items]


def _legacy_validate_summary_pack_payload(raw: Dict[str, Any], *, icsc_tags: List[str], evidence_refs: List[str]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    headline = raw.get("headline_judgment") if isinstance(raw.get("headline_judgment"), dict) else {}
    secondary_raw = raw.get("secondary_conclusions") if isinstance(raw.get("secondary_conclusions"), list) else []
    user_profile = raw.get("user_profile") if isinstance(raw.get("user_profile"), dict) else {}
    behavior = raw.get("behavior_inference") if isinstance(raw.get("behavior_inference"), dict) else {}
    secondary: List[Dict[str, str]] = []
    for item in secondary_raw:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        reasoning = _clean_text(item.get("reasoning"))
        if title and reasoning:
            secondary.append({"title": title, "reasoning": reasoning})
    if len(secondary) < 2:
        return {}
    normalized = {
        "headline_judgment": {
            "summary": _clean_text(headline.get("summary")),
            "supporting_clause": _clean_text(headline.get("supporting_clause")),
        },
        "icsc_tags": list(icsc_tags),
        "secondary_conclusions": secondary[:4],
        "user_profile": {
            "headline": _clean_text(user_profile.get("headline")),
            "traits": _normalize_trait_list(user_profile.get("traits")),
        },
        "behavior_inference": {
            "headline": _clean_text(behavior.get("headline")),
            "traits": _normalize_trait_list(behavior.get("traits")),
        },
        "evidence_refs": list(evidence_refs),
        "confidence": "moderate" if len(evidence_refs) >= 2 else "weak",
    }
    if not normalized["headline_judgment"]["summary"]:
        return {}
    if not normalized["user_profile"]["headline"] or not normalized["user_profile"]["traits"]:
        return {}
    if not normalized["behavior_inference"]["headline"] or not normalized["behavior_inference"]["traits"]:
        return {}
    return normalized


def _summary_pack_system_prompt() -> str:
    return (
        "你是 gaode-map 的商业总结撰写器。"
        "你只负责把已给定的结构化证据整理成商业判断，不得创造新的事实。"
        "必须只输出 JSON，不要输出 markdown。"
        "JSON 结构固定为："
        "{\"headline_judgment\":{\"summary\":\"...\",\"supporting_clause\":\"...\"},"
        "\"user_profile\":{\"headline\":\"...\",\"traits\":[\"...\"]},"
        "\"behavior_inference\":{\"headline\":\"...\",\"traits\":[\"...\"]}}"
        "规则："
        "1. headline_judgment.summary 必须是一句话商业判断，直接回答这个区域是什么级别或类型的商业。"
        "2. 不要输出 spatial_structure、poi_structure、consumption_vitality、business_support；这些区域判断由独立任务生成。"
        "3. 不要输出 secondary_conclusions。"
        "4. 不要把原始指标、百分比、样本量直接写成主句；不要做数据播报。"
        "5. user_profile 必须写消费者是谁，不能写成区域类型或商业区描述。"
        "6. behavior_inference 必须写消费行为、频次、时段或跨区吸引力，不能重复 user_profile 或 headline_judgment。"
        "7. 如果证据不足，也只能基于已给证据做保守判断，不能虚构。"
        "8. 不要输出 ICSC 标签，这部分会由系统注入。"
    )


def _build_summary_llm_payload(snapshot: Any, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    poi_structure = artifacts.get("current_poi_structure_analysis") if isinstance(artifacts.get("current_poi_structure_analysis"), dict) else {}
    h3_structure = artifacts.get("current_h3_structure_analysis") if isinstance(artifacts.get("current_h3_structure_analysis"), dict) else {}
    population_profile = artifacts.get("current_population_profile_analysis") if isinstance(artifacts.get("current_population_profile_analysis"), dict) else {}
    nightlight_pattern = artifacts.get("current_nightlight_pattern_analysis") if isinstance(artifacts.get("current_nightlight_pattern_analysis"), dict) else {}
    road_pattern = artifacts.get("current_road_pattern_analysis") if isinstance(artifacts.get("current_road_pattern_analysis"), dict) else {}
    business_profile = artifacts.get("current_business_profile") if isinstance(artifacts.get("current_business_profile"), dict) else {}
    area_labels = artifacts.get("current_area_character_labels") if isinstance(artifacts.get("current_area_character_labels"), dict) else {}
    commercial_hotspots = _current_commercial_hotspots(snapshot, artifacts, h3_structure)
    h3_summary = _current_summary(snapshot, artifacts, "h3")
    return {
        "task": "summary_pack_generation",
        "required_sections": [{"section_key": key, "title": title} for key, title in _SUMMARY_SECTION_SPECS],
        "business_profile": {
            "label": _clean_text(business_profile.get("business_profile")),
            "portrait": _clean_text(business_profile.get("portrait")),
            "summary_text": _clean_text(business_profile.get("summary_text")),
            "functional_mix_score": business_profile.get("functional_mix_score"),
        },
        "poi_structure": {
            "summary_text": _clean_text(poi_structure.get("summary_text")),
            "dominant_categories": list(poi_structure.get("dominant_categories") or []),
            "structure_tags": list(poi_structure.get("structure_tags") or []),
            "top_category_mix": _top_poi_mix(snapshot),
        },
        "spatial_structure": {
            "distribution_pattern": _clean_text(h3_structure.get("distribution_pattern")),
            "summary_text": _clean_text(h3_structure.get("summary_text")),
            "hotspot_mode": _clean_text(commercial_hotspots.get("hotspot_mode")),
            "hotspot_summary": _clean_text(commercial_hotspots.get("summary_text")),
            "core_zone_count": commercial_hotspots.get("core_zone_count"),
            "opportunity_zone_count": commercial_hotspots.get("opportunity_zone_count"),
            "dimensions": {
                "aggregation": {
                    "focus": "判断圈内空间信号是强集聚、弱集聚还是分散。",
                    "evidence": {
                        "avg_density_poi_per_km2": h3_summary.get("avg_density_poi_per_km2"),
                        "global_moran_i_density": h3_summary.get("global_moran_i_density"),
                        "global_moran_z_score": h3_summary.get("global_moran_z_score"),
                        "gi_stats": dict(h3_structure.get("gi_stats") or {}),
                        "lisa_stats": dict(h3_structure.get("lisa_stats") or {}),
                        "core_zone_count": commercial_hotspots.get("core_zone_count"),
                        "opportunity_zone_count": commercial_hotspots.get("opportunity_zone_count"),
                    },
                },
                "mixing": {
                    "focus": "判断圈内功能是单一、复合还是混合。",
                    "evidence": {
                        "avg_local_entropy": h3_summary.get("avg_local_entropy"),
                        "functional_mix_score": business_profile.get("functional_mix_score"),
                        "poi_structure_tags": list(poi_structure.get("structure_tags") or []),
                        "business_profile_label": _clean_text(business_profile.get("business_profile")),
                    },
                },
                "morphology": {
                    "focus": "判断圈内结构形态是单核、多核、廊道还是离散。",
                    "evidence": {
                        "distribution_pattern": _clean_text(h3_structure.get("distribution_pattern")),
                        "hotspot_mode": _clean_text(commercial_hotspots.get("hotspot_mode")),
                        "structure_signal_count": h3_structure.get("structure_signal_count"),
                        "hotspot_count": h3_structure.get("hotspot_count"),
                        "opportunity_count": h3_structure.get("opportunity_count"),
                    },
                },
            },
        },
        "population_profile": {
            "summary_text": _clean_text(population_profile.get("summary_text")),
            "total_population": population_profile.get("total_population"),
            "top_age_band": _clean_text(population_profile.get("top_age_band")),
        },
        "nightlight_pattern": {
            "summary_text": _clean_text(nightlight_pattern.get("summary_text")),
            "total_radiance": nightlight_pattern.get("total_radiance"),
            "mean_radiance": nightlight_pattern.get("mean_radiance"),
            "p90_radiance": nightlight_pattern.get("p90_radiance"),
            "lit_pixel_ratio": nightlight_pattern.get("lit_pixel_ratio"),
            "core_hotspot_count": nightlight_pattern.get("core_hotspot_count"),
            "economic_activity_intensity_level": _clean_text(nightlight_pattern.get("economic_activity_intensity_level")),
            "economic_activity_summary_text": _clean_text(nightlight_pattern.get("economic_activity_summary_text")),
            "sector_direction_analysis": dict(nightlight_pattern.get("sector_direction_analysis") or {}),
            "pattern_tags": list(nightlight_pattern.get("pattern_tags") or []),
        },
        "road_pattern": {
            "summary_text": _clean_text(road_pattern.get("summary_text")),
            "node_count": road_pattern.get("node_count"),
            "edge_count": road_pattern.get("edge_count"),
            "regression_r2": road_pattern.get("regression_r2"),
            "default_radius_label": _clean_text(road_pattern.get("default_radius_label")),
            "radius_labels": list(road_pattern.get("radius_labels") or []),
            "connectivity": {
                "focus": "判断圈内路网是否顺畅、节点之间是否容易互达。",
                "signal": _clean_text(road_pattern.get("connectivity_signal")),
                "avg_connectivity": road_pattern.get("avg_connectivity"),
                "avg_control": road_pattern.get("avg_control"),
            },
            "access": {
                "focus": "判断该范围是否容易被经过、是否具备主路径承接效率。",
                "signal": _clean_text(road_pattern.get("access_signal")),
                "avg_depth": road_pattern.get("avg_depth"),
                "avg_choice_global": road_pattern.get("avg_choice_global"),
                "avg_choice_local": road_pattern.get("avg_choice_local"),
                "avg_integration_global": road_pattern.get("avg_integration_global"),
                "avg_integration_local": road_pattern.get("avg_integration_local"),
            },
            "readability": {
                "focus": "判断路网动线是否清晰、是否利于识别与组织商业活动。",
                "signal": _clean_text(road_pattern.get("readability_signal")),
                "avg_intelligibility": road_pattern.get("avg_intelligibility"),
                "avg_intelligibility_r2": road_pattern.get("avg_intelligibility_r2"),
            },
            "road_orientation_analysis": dict(road_pattern.get("road_orientation_analysis") or {}),
            "pattern_tags": list(road_pattern.get("pattern_tags") or []),
        },
        "area_labels": list(area_labels.get("character_tags") or []),
        "guardrails": {
            "write_business_judgment_not_data_description": True,
            "no_raw_metric_recital_as_headline": True,
            "user_profile_must_describe_people": True,
            "behavior_inference_must_describe_usage": True,
            "area_judgments_are_independent_sections": True,
            "customer_profile_is_not_an_area_judgment": True,
            "business_support_should_cover_road_layers": True,
        },
    }


def _validate_summary_pack_payload(raw: Dict[str, Any], *, icsc_tags: List[str], evidence_refs: List[str]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    headline = raw.get("headline_judgment") if isinstance(raw.get("headline_judgment"), dict) else {}
    user_profile = raw.get("user_profile") if isinstance(raw.get("user_profile"), dict) else {}
    behavior = raw.get("behavior_inference") if isinstance(raw.get("behavior_inference"), dict) else {}
    area_judgments = _normalize_area_judgments(raw)
    for key, _ in _SUMMARY_SECTION_SPECS:
        item = area_judgments.get(key)
        if not item:
            return {}
        if key == "spatial_structure" and not item.get("dimensions"):
            return {}
    normalized = {
        "headline_judgment": {
            "summary": _clean_text(headline.get("summary")),
            "supporting_clause": _clean_text(headline.get("supporting_clause")),
        },
        "icsc_tags": list(icsc_tags),
        "user_profile": {
            "headline": _clean_text(user_profile.get("headline")),
            "traits": _normalize_trait_list(user_profile.get("traits")),
        },
        "behavior_inference": {
            "headline": _clean_text(behavior.get("headline")),
            "traits": _normalize_trait_list(behavior.get("traits")),
        },
        "evidence_refs": list(evidence_refs),
        "confidence": "moderate" if len(evidence_refs) >= 2 else "weak",
    }
    for key, _ in _SUMMARY_SECTION_SPECS:
        normalized[key] = dict(area_judgments[key])
    if not normalized["headline_judgment"]["summary"]:
        return {}
    if not normalized["user_profile"]["headline"] or not normalized["user_profile"]["traits"]:
        return {}
    if not normalized["behavior_inference"]["headline"] or not normalized["behavior_inference"]["traits"]:
        return {}
    return normalized


def _validate_summary_base_payload(raw: Dict[str, Any], *, icsc_tags: List[str], evidence_refs: List[str]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    headline = raw.get("headline_judgment") if isinstance(raw.get("headline_judgment"), dict) else {}
    user_profile = raw.get("user_profile") if isinstance(raw.get("user_profile"), dict) else {}
    behavior = raw.get("behavior_inference") if isinstance(raw.get("behavior_inference"), dict) else {}
    normalized = {
        "headline_judgment": {
            "summary": _clean_text(headline.get("summary")),
            "supporting_clause": _clean_text(headline.get("supporting_clause")),
        },
        "icsc_tags": list(icsc_tags),
        "user_profile": {
            "headline": _clean_text(user_profile.get("headline")),
            "traits": _normalize_trait_list(user_profile.get("traits")),
        },
        "behavior_inference": {
            "headline": _clean_text(behavior.get("headline")),
            "traits": _normalize_trait_list(behavior.get("traits")),
        },
        "evidence_refs": list(evidence_refs),
        "confidence": "moderate" if len(evidence_refs) >= 2 else "weak",
    }
    if not normalized["headline_judgment"]["summary"]:
        return {}
    if not normalized["user_profile"]["headline"] or not normalized["user_profile"]["traits"]:
        return {}
    if not normalized["behavior_inference"]["headline"] or not normalized["behavior_inference"]["traits"]:
        return {}
    return normalized


def _build_summary_status(
    *,
    status: str,
    llm_available: bool,
    generated: bool,
    title: str,
    description: str,
    message: str = "",
    error_code: str = "",
    error_stage: str = "",
    retryable: bool = False,
) -> Dict[str, Any]:
    return {
        "status": status,
        "llm_available": bool(llm_available),
        "generated": bool(generated),
        "title": title,
        "description": description,
        "message": message,
        "error_code": error_code,
        "error_stage": error_stage,
        "retryable": bool(retryable),
    }


async def _generate_summary_pack_with_llm(snapshot: Any, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    if not is_llm_enabled():
        return {}
    source_payload = _build_summary_llm_payload(snapshot, artifacts)
    payload = await _invoke_json_role(
        system_prompt=_summary_pack_system_prompt(),
        user_payload=source_payload,
        emit=None,
        phase="summary_pack",
        title="生成商业判断型总结",
        reasoning_id="summary-pack-reasoning",
    )
    icsc_tags = _derive_icsc_tags(snapshot, artifacts)
    evidence_refs = build_citations(snapshot, artifacts)
    normalized = _validate_summary_base_payload(payload, icsc_tags=icsc_tags, evidence_refs=evidence_refs)
    if not normalized:
        return {}
    for section_key, section_title in _SUMMARY_SECTION_SPECS:
        try:
            section = await _generate_summary_section_with_llm(section_key, section_title, source_payload)
        except Exception:
            section = {}
        if section:
            normalized[section_key] = section
    normalized = _normalize_area_judgment_reasoning(normalized, source_payload)
    return _validate_summary_pack_payload(normalized, icsc_tags=icsc_tags, evidence_refs=evidence_refs)


def _build_stream_event(event_type: str, payload: Dict[str, Any]) -> AgentSummaryStreamEvent:
    return AgentSummaryStreamEvent(type=event_type, payload=_json_safe(payload))


def _chunk_text_for_stream(text: str, *, chunk_size: int = 24) -> List[str]:
    content = _clean_text(text)
    if not content:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(content):
        chunks.append(content[start:start + chunk_size])
        start += chunk_size
    return chunks


def _build_headline_section_prompt() -> str:
    return (
        "你是 gaode-map 的商业总结撰写器。"
        "请基于给定结构化证据，输出 JSON："
        "{\"summary\":\"...\",\"supporting_clause\":\"...\"}"
        "要求："
        "1. summary 必须是一句话商业判断；"
        "2. supporting_clause 必须补一句解释，不要复述 summary；"
        "3. 不能编造新事实，不能罗列原始数值。"
    )


def _build_profile_section_prompt(section_key: str) -> str:
    if section_key == "user_profile":
        task_line = "headline 必须写消费者是谁，traits 写 2 到 4 条稳定画像特征。"
    else:
        task_line = "headline 必须写消费行为或使用方式，traits 写 2 到 4 条行为特征。"
    return (
        "你是 gaode-map 的商业总结撰写器。"
        "请基于给定结构化证据，输出 JSON："
        "{\"headline\":\"...\",\"traits\":[\"...\",\"...\"]}"
        f"{task_line}"
        "不能编造新事实，不能输出 markdown。"
    )


def _build_followup_questions_prompt() -> str:
    return (
        "你是 gaode-map 的商业分析助手。"
        "请基于当前总结证据，输出 JSON："
        "{\"questions\":[\"...\",\"...\",\"...\"]}"
        "要求："
        "1. questions 固定输出 3 条；"
        "2. 每条都要是下一步值得继续追问的问题；"
        "3. 不要输出解释和 markdown。"
    )


def _build_headline_section_payload(source_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task": "summary_headline_generation",
        "business_profile": dict(source_payload.get("business_profile") or {}),
        "poi_structure": dict(source_payload.get("poi_structure") or {}),
        "spatial_structure": dict(source_payload.get("spatial_structure") or {}),
        "population_profile": dict(source_payload.get("population_profile") or {}),
        "nightlight_pattern": dict(source_payload.get("nightlight_pattern") or {}),
        "road_pattern": dict(source_payload.get("road_pattern") or {}),
        "area_labels": list(source_payload.get("area_labels") or []),
    }


def _build_profile_section_payload(section_key: str, source_payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "task": f"summary_{section_key}_generation",
        "business_profile": dict(source_payload.get("business_profile") or {}),
        "poi_structure": dict(source_payload.get("poi_structure") or {}),
        "population_profile": dict(source_payload.get("population_profile") or {}),
        "nightlight_pattern": dict(source_payload.get("nightlight_pattern") or {}),
        "road_pattern": dict(source_payload.get("road_pattern") or {}),
        "area_labels": list(source_payload.get("area_labels") or []),
    }
    if section_key == "behavior_inference":
        payload["spatial_structure"] = dict(source_payload.get("spatial_structure") or {})
    return payload


def _build_followup_questions_payload(source_payload: Dict[str, Any], summary_pack: Dict[str, Any]) -> Dict[str, Any]:
    area_judgments = {
        key: dict(summary_pack.get(key) or {})
        for key, _ in _SUMMARY_SECTION_SPECS
        if isinstance(summary_pack.get(key), dict)
    }
    return {
        "task": "summary_followup_generation",
        "headline_judgment": dict(summary_pack.get("headline_judgment") or {}),
        "area_judgments": area_judgments,
        "user_profile": dict(summary_pack.get("user_profile") or {}),
        "behavior_inference": dict(summary_pack.get("behavior_inference") or {}),
        "icsc_tags": list(summary_pack.get("icsc_tags") or []),
        "business_profile": dict(source_payload.get("business_profile") or {}),
        "area_labels": list(source_payload.get("area_labels") or []),
    }


def _validate_headline_section_payload(raw: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    summary = _clean_text(raw.get("summary"))
    supporting_clause = _clean_text(raw.get("supporting_clause"))
    if not summary:
        return {}
    return {
        "summary": summary,
        "supporting_clause": supporting_clause,
    }


def _validate_profile_section_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    headline = _clean_text(raw.get("headline"))
    traits = _normalize_trait_list(raw.get("traits"))
    if not headline or not traits:
        return {}
    return {
        "headline": headline,
        "traits": traits,
    }


def _validate_followup_questions_payload(raw: Dict[str, Any]) -> List[str]:
    if not isinstance(raw, dict):
        return []
    questions: List[str] = []
    for item in raw.get("questions") or []:
        text = _clean_text(item)
        if text and text not in questions:
            questions.append(text)
    return questions[:3]


async def _generate_headline_section_with_llm(source_payload: Dict[str, Any]) -> Dict[str, str]:
    payload = await _invoke_json_role(
        system_prompt=_build_headline_section_prompt(),
        user_payload=_build_headline_section_payload(source_payload),
        emit=None,
        phase="summary_headline",
        title="生成一句话结论",
        reasoning_id="summary-headline-reasoning",
    )
    return _validate_headline_section_payload(payload)


async def _generate_profile_section_with_llm(section_key: str, source_payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = await _invoke_json_role(
        system_prompt=_build_profile_section_prompt(section_key),
        user_payload=_build_profile_section_payload(section_key, source_payload),
        emit=None,
        phase=f"summary_{section_key}",
        title="生成用户画像" if section_key == "user_profile" else "生成商业行为推断",
        reasoning_id=f"summary-{section_key}-reasoning",
    )
    return _validate_profile_section_payload(payload)


async def _generate_followup_questions_with_llm(source_payload: Dict[str, Any], summary_pack: Dict[str, Any]) -> List[str]:
    payload = await _invoke_json_role(
        system_prompt=_build_followup_questions_prompt(),
        user_payload=_build_followup_questions_payload(source_payload, summary_pack),
        emit=None,
        phase="summary_followups",
        title="生成快捷追问",
        reasoning_id="summary-followups-reasoning",
    )
    return _validate_followup_questions_payload(payload)


async def stream_generate_summary_pack(payload: AgentSummaryRequest) -> AsyncIterator[AgentSummaryStreamEvent]:
    try:
        phases = ["precheck"]
        warnings: List[str] = []
        error = ""
        yield _build_stream_event("status", {"phase": "precheck", "phases": list(phases)})
        readiness_payload = await ensure_area_data_readiness(
            arguments={},
            snapshot=payload.analysis_snapshot,
            artifacts={},
            question="summary_generate_preflight",
        )
        warnings.extend([str(item) for item in (readiness_payload.get("warnings") or []) if str(item).strip()])
        error = str(readiness_payload.get("error") or "")
        artifacts = dict(readiness_payload.get("artifacts") or {})
        normalized = _normalize_data_readiness(readiness_payload)
        summary_pack: Dict[str, Any] = {}
        summary_status = _build_summary_status(
            status="data_incomplete",
            llm_available=is_llm_enabled(),
            generated=False,
            title="总结待生成",
            description="当前区域还缺少基础分析结果，请先补齐 POI、H3、人口、夜光和路网分析。",
            message=error,
            error_code="readiness_failed" if error else "",
            error_stage="precheck" if error else "",
            retryable=bool(error),
        )
        if normalized["ready"]:
            phases.append("fetch_missing")
            yield _build_stream_event("status", {"phase": "fetch_missing", "phases": list(phases)})
            phases.append("derive_analysis")
            yield _build_stream_event("status", {"phase": "derive_analysis", "phases": list(phases)})
            pack_result = await run_area_character_pack(
                arguments={},
                snapshot=payload.analysis_snapshot,
                artifacts=artifacts,
                question="summary_generate_derive_analysis",
            )
            warnings.extend([str(item) for item in (pack_result.warnings or []) if str(item).strip()])
            if pack_result.status == "success":
                artifacts.update(dict(pack_result.artifacts or {}))
            else:
                error = str(pack_result.error or error or "derive_analysis_failed")
                summary_status = _build_summary_status(
                    status="generation_failed",
                    llm_available=is_llm_enabled(),
                    generated=False,
                    title="总结待生成",
                    description="结构化分析阶段失败，本次未生成正式总结。",
                    message=error,
                    error_code="derive_failed",
                    error_stage="derive_analysis",
                    retryable=True,
                )
            structured = _derive_structured_status(payload.analysis_snapshot, artifacts)
            normalized = _normalize_data_readiness(
                readiness_payload,
                structured_missing_tasks=structured["missing_tasks"],
                extra_fetched=_STRUCTURED_TASK_ORDER if pack_result.status == "success" else [],
            )
            if pack_result.status == "success":
                artifacts.update(dict(structured.get("artifacts") or {}))
            if normalized["ready"] and is_llm_enabled():
                phases.append("analysis_started")
                yield _build_stream_event("status", {"phase": "analysis_started", "phases": list(phases)})
                source_payload = _build_summary_llm_payload(payload.analysis_snapshot, artifacts)
                evidence_refs = build_citations(payload.analysis_snapshot, artifacts)
                summary_pack = {
                    "icsc_tags": _derive_icsc_tags(payload.analysis_snapshot, artifacts),
                    "evidence_refs": list(evidence_refs),
                    "confidence": "moderate" if len(evidence_refs) >= 2 else "weak",
                }

                try:
                    headline_payload = await _generate_headline_section_with_llm(source_payload)
                    yield _build_stream_event("section_start", {"key": "headline", "title": "一句话结论"})
                    headline_text = " ".join([headline_payload.get("summary", ""), headline_payload.get("supporting_clause", "")]).strip()
                    for chunk in _chunk_text_for_stream(headline_text):
                        yield _build_stream_event("section_delta", {"key": "headline", "delta": chunk})
                    summary_pack["headline_judgment"] = headline_payload
                    yield _build_stream_event(
                        "section_complete",
                        {"key": "headline", "status": "ready", "payload": dict(headline_payload)},
                    )
                except Exception as exc:
                    warnings.append(f"headline_generation_failed:{exc}")
                    yield _build_stream_event("error", {"key": "headline", "message": str(exc)})
                    yield _build_stream_event("section_complete", {"key": "headline", "status": "failed"})

                yield _build_stream_event("section_start", {"key": "tags", "title": "商业类型标签（ICSC）"})
                yield _build_stream_event(
                    "panel_payload",
                    {"key": "icsc_tags", "payload": {"icsc_tags": list(summary_pack.get("icsc_tags") or [])}},
                )
                yield _build_stream_event(
                    "section_complete",
                    {"key": "tags", "status": "ready", "payload": {"icsc_tags": list(summary_pack.get("icsc_tags") or [])}},
                )

                for section_key, section_title in _SUMMARY_SECTION_SPECS:
                    try:
                        yield _build_stream_event("section_start", {"key": section_key, "title": section_title})
                        section_payload = await _generate_summary_section_with_llm(section_key, section_title, source_payload)
                        section_pack = _normalize_area_judgment_reasoning({section_key: section_payload}, source_payload)
                        section_payload = dict(section_pack.get(section_key) or section_payload)
                        for chunk in _chunk_text_for_stream(_clean_text(section_payload.get("reasoning"))):
                            yield _build_stream_event("section_delta", {"key": section_key, "delta": chunk})
                        summary_pack[section_key] = section_payload
                        yield _build_stream_event(
                            "section_complete",
                            {"key": section_key, "status": "ready", "payload": dict(section_payload)},
                        )
                    except Exception as exc:
                        warnings.append(f"{section_key}_generation_failed:{exc}")
                        yield _build_stream_event("error", {"key": section_key, "message": str(exc)})
                        yield _build_stream_event("section_complete", {"key": section_key, "status": "failed"})

                for section_key, stream_key, title in [
                    ("user_profile", "user_profile", "用户画像"),
                    ("behavior_inference", "behavior", "商业行为推断"),
                ]:
                    try:
                        section_payload = await _generate_profile_section_with_llm(section_key, source_payload)
                        yield _build_stream_event("section_start", {"key": stream_key, "title": title})
                        section_text = "\n".join([section_payload.get("headline", ""), *(section_payload.get("traits") or [])]).strip()
                        for chunk in _chunk_text_for_stream(section_text):
                            yield _build_stream_event("section_delta", {"key": stream_key, "delta": chunk})
                        summary_pack[section_key] = section_payload
                        yield _build_stream_event(
                            "section_complete",
                            {"key": stream_key, "status": "ready", "payload": dict(section_payload)},
                        )
                    except Exception as exc:
                        warnings.append(f"{section_key}_generation_failed:{exc}")
                        yield _build_stream_event("error", {"key": stream_key, "message": str(exc)})
                        yield _build_stream_event("section_complete", {"key": stream_key, "status": "failed"})

                try:
                    followup_questions = await _generate_followup_questions_with_llm(source_payload, summary_pack)
                except Exception as exc:
                    warnings.append(f"followup_generation_failed:{exc}")
                    followup_questions = []
                yield _build_stream_event("section_start", {"key": "followups", "title": "快捷追问"})
                if followup_questions:
                    summary_pack["followup_questions"] = followup_questions
                    yield _build_stream_event(
                        "panel_payload",
                        {"key": "followup_questions", "payload": {"followup_questions": followup_questions}},
                    )
                    yield _build_stream_event(
                        "section_complete",
                        {"key": "followups", "status": "ready", "payload": {"followup_questions": followup_questions}},
                    )
                else:
                    yield _build_stream_event("error", {"key": "followups", "message": "快捷追问生成失败"})
                    yield _build_stream_event("section_complete", {"key": "followups", "status": "failed"})

                validated = _validate_summary_pack_payload(
                    summary_pack,
                    icsc_tags=list(summary_pack.get("icsc_tags") or []),
                    evidence_refs=list(summary_pack.get("evidence_refs") or []),
                )
                normalized_pack = _normalize_area_judgment_reasoning(validated, source_payload) if validated else {}
                if normalized_pack:
                    if summary_pack.get("followup_questions"):
                        normalized_pack["followup_questions"] = list(summary_pack.get("followup_questions") or [])
                    summary_pack = normalized_pack
                    summary_status = _build_summary_status(
                        status="ready",
                        llm_available=True,
                        generated=True,
                        title="总结已生成",
                        description="已基于结构化证据生成商业判断型总结。",
                    )
                else:
                    error = error or "summary_pack_invalid"
                    summary_pack = {}
                    summary_status = _build_summary_status(
                        status="generation_failed",
                        llm_available=True,
                        generated=False,
                        title="总结待生成",
                        description="本次模型输出未通过结构校验，暂未生成正式总结。",
                        message=error,
                        error_code="schema_invalid",
                        error_stage="summary_pack",
                        retryable=True,
                    )
            elif normalized["ready"] and not is_llm_enabled():
                summary_status = _build_summary_status(
                    status="llm_unavailable",
                    llm_available=False,
                    generated=False,
                    title="总结待生成",
                    description="基础分析结果已就绪，但当前环境未启用可用模型。",
                    error_code="llm_unavailable",
                    error_stage="summary_pack",
                    retryable=False,
                )

        panel_payloads = build_summary_panel_payloads(
            "summary_generate",
            payload.analysis_snapshot,
            artifacts,
            summary_pack=summary_pack,
            summary_status=summary_status,
        )
        if summary_pack.get("followup_questions"):
            panel_payloads["summary_followup_questions"] = list(summary_pack.get("followup_questions") or [])
        panel_payloads["data_readiness"] = dict(normalized)
        phases.append("completed")
        yield _build_stream_event(
            "final",
            {
                "data_readiness": dict(normalized),
                "panel_payloads": panel_payloads,
                "summary_pack": summary_pack,
                "error": error,
                "warnings": warnings,
                "phases": phases,
                "progress_steps": [step.model_dump(mode="json") for step in _build_progress_steps(
                    phases,
                    failed=(not normalized["ready"]) or (normalized["ready"] and not bool(summary_pack) and summary_status.get("status") == "generation_failed"),
                )],
            },
        )
    except Exception as exc:
        yield _build_stream_event(
            "error",
            {"key": "global", "message": f"summary_generate_internal_error: {exc.__class__.__name__}"},
        )
        yield _build_stream_event(
            "final",
            {
                "data_readiness": {
                    "checked": True,
                    "ready": False,
                    "missing_tasks": ["poi_grid", "population", "nightlight", "road_syntax", "poi_structure", "spatial_structure", "area_labels"],
                    "reused": [],
                    "fetched": [],
                },
                "panel_payloads": {},
                "summary_pack": {},
                "error": f"summary_generate_internal_error: {exc.__class__.__name__}",
                "warnings": [str(exc)],
                "phases": ["precheck", "fetch_missing"],
                "progress_steps": [step.model_dump(mode="json") for step in _build_progress_steps(["precheck", "fetch_missing"], failed=True)],
            },
        )


async def evaluate_summary_readiness(payload: AgentSummaryRequest) -> AgentSummaryReadinessResponse:
    try:
        phases = ["precheck"]
        readiness_payload = await ensure_area_data_readiness(
            arguments={"auto_fetch": False},
            snapshot=payload.analysis_snapshot,
            artifacts={},
            question="summary_readiness_precheck",
        )
        artifacts = dict(readiness_payload.get("artifacts") or {})
        structured = _derive_structured_status(payload.analysis_snapshot, artifacts)
        normalized = _normalize_data_readiness(
            readiness_payload,
            structured_missing_tasks=structured["missing_tasks"],
        )
        return AgentSummaryReadinessResponse(
            data_readiness=normalized,
            error=str(readiness_payload.get("error") or ""),
            warnings=[str(item) for item in (readiness_payload.get("warnings") or []) if str(item).strip()],
            phases=phases,
            progress_steps=_build_progress_steps(phases, failed=not normalized["ready"] and bool(readiness_payload.get("error"))),
        )
    except Exception as exc:
        phases = ["precheck"]
        return AgentSummaryReadinessResponse(
            data_readiness={
                "checked": False,
                "ready": False,
                "missing_tasks": ["poi_grid", "population", "nightlight", "road_syntax", "poi_structure", "spatial_structure", "area_labels"],
                "reused": [],
                "fetched": [],
            },
            error=f"summary_readiness_internal_error: {exc.__class__.__name__}",
            warnings=[str(exc)],
            phases=phases,
            progress_steps=_build_progress_steps(phases, failed=True),
        )


async def generate_summary_pack(payload: AgentSummaryRequest) -> AgentSummaryGenerateResponse:
    try:
        phases = ["precheck", "fetch_missing"]
        readiness_payload = await ensure_area_data_readiness(
            arguments={},
            snapshot=payload.analysis_snapshot,
            artifacts={},
            question="summary_generate_preflight",
        )
        warnings = [str(item) for item in (readiness_payload.get("warnings") or []) if str(item).strip()]
        error = str(readiness_payload.get("error") or "")
        artifacts = dict(readiness_payload.get("artifacts") or {})
        normalized = _normalize_data_readiness(readiness_payload)
        panel_payloads: Dict[str, Any] = {}
        summary_pack: Dict[str, Any] = {}
        summary_status = _build_summary_status(
            status="data_incomplete",
            llm_available=is_llm_enabled(),
            generated=False,
            title="总结待生成",
            description="当前区域还缺少基础分析结果，请先补齐 POI、H3、人口、夜光和路网分析。",
        )
        summary_status = {
            **summary_status,
            "error_code": "readiness_failed" if error else "",
            "error_stage": "precheck" if error else "",
            "retryable": bool(error),
        }
        if normalized["ready"]:
            phases.append("derive_analysis")
            pack_result = await run_area_character_pack(
                arguments={},
                snapshot=payload.analysis_snapshot,
                artifacts=artifacts,
                question="summary_generate_derive_analysis",
            )
            warnings.extend([str(item) for item in (pack_result.warnings or []) if str(item).strip()])
            if pack_result.status == "success":
                artifacts.update(dict(pack_result.artifacts or {}))
            else:
                error = str(pack_result.error or error or "derive_analysis_failed")
                summary_status = _build_summary_status(
                    status="generation_failed",
                    llm_available=is_llm_enabled(),
                    generated=False,
                    title="总结待生成",
                    description="结构化分析阶段失败，本次未生成正式总结。",
                    message=error,
                    error_code="derive_failed",
                    error_stage="derive_analysis",
                    retryable=True,
                )
            structured = _derive_structured_status(payload.analysis_snapshot, artifacts)
            normalized = _normalize_data_readiness(
                readiness_payload,
                structured_missing_tasks=structured["missing_tasks"],
                extra_fetched=_STRUCTURED_TASK_ORDER if pack_result.status == "success" else [],
            )
            if pack_result.status == "success":
                artifacts.update(dict(structured.get("artifacts") or {}))
            if normalized["ready"]:
                if not is_llm_enabled():
                    summary_status = _build_summary_status(
                        status="llm_unavailable",
                        llm_available=False,
                        generated=False,
                        title="总结待生成",
                        description="基础分析结果已就绪，但当前环境未启用可用模型，暂时无法生成商业判断型总结。",
                    )
                else:
                    try:
                        summary_pack = await _generate_summary_pack_with_llm(payload.analysis_snapshot, artifacts)
                    except Exception as exc:
                        error = f"summary_pack_generation_failed: {exc.__class__.__name__}"
                        warnings.append(str(exc))
                        summary_pack = {}
                    if summary_pack:
                        summary_status = _build_summary_status(
                            status="ready",
                            llm_available=True,
                            generated=True,
                            title="总结已生成",
                            description="已基于结构化证据生成商业判断型总结。",
                        )
                        phases.append("analysis_started")
                    else:
                        if not error:
                            error = "summary_pack_invalid"
                            warnings.append("summary_pack_missing_required_fields")
                        summary_status = _build_summary_status(
                            status="generation_failed",
                            llm_available=True,
                            generated=False,
                            title="总结待生成",
                            description="基础分析结果已就绪，但本次模型输出未通过结构校验，暂未生成正式总结。",
                            message=error,
                        )

        status_key = str(summary_status.get("status") or "")
        if status_key == "data_incomplete":
            if not summary_status.get("error_code"):
                summary_status["error_code"] = "readiness_failed" if error else ""
            if not summary_status.get("error_stage"):
                summary_status["error_stage"] = "precheck" if error else ""
            if "retryable" not in summary_status:
                summary_status["retryable"] = bool(error)
        elif status_key == "llm_unavailable":
            if not summary_status.get("error_code"):
                summary_status["error_code"] = "llm_unavailable"
            if not summary_status.get("error_stage"):
                summary_status["error_stage"] = "summary_pack"
            if "retryable" not in summary_status:
                summary_status["retryable"] = False
        elif status_key == "generation_failed":
            lowered_error = str(error or "").lower()
            if not summary_status.get("error_code"):
                if "derive" in lowered_error:
                    summary_status["error_code"] = "derive_failed"
                elif "invalid_chat_completion" in lowered_error or "empty_llm_output" in lowered_error:
                    summary_status["error_code"] = "llm_invalid_json"
                else:
                    summary_status["error_code"] = "schema_invalid"
            summary_status.setdefault("error_stage", "summary_pack")
            summary_status.setdefault("retryable", True)

        panel_payloads = build_summary_panel_payloads(
            "summary_generate",
            payload.analysis_snapshot,
            artifacts,
            summary_pack=summary_pack,
            summary_status=summary_status,
        )
        panel_payloads["data_readiness"] = dict(normalized)

        return AgentSummaryGenerateResponse(
            data_readiness=normalized,
            panel_payloads=_json_safe(panel_payloads),
            summary_pack=_json_safe(summary_pack),
            error=error,
            warnings=warnings,
            phases=phases,
            progress_steps=_build_progress_steps(
                phases,
                failed=(not normalized["ready"]) or (normalized["ready"] and not bool(summary_pack) and summary_status.get("status") == "generation_failed"),
            ),
        )
    except Exception as exc:
        phases = ["precheck", "fetch_missing"]
        return AgentSummaryGenerateResponse(
            data_readiness={
                "checked": True,
                "ready": False,
                "missing_tasks": ["poi_grid", "population", "nightlight", "road_syntax", "poi_structure", "spatial_structure", "area_labels"],
                "reused": [],
                "fetched": [],
            },
            panel_payloads={},
            summary_pack={},
            error=f"summary_generate_internal_error: {exc.__class__.__name__}",
            warnings=[str(exc)],
            phases=phases,
            progress_steps=_build_progress_steps(phases, failed=True),
        )
