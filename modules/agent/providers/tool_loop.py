from __future__ import annotations

from typing import Any, Dict, List

from ..tools import RegisteredTool

_CORE_TOOL_NAMES = {
    "read_current_scope",
    "read_current_results",
    "search_analysis_context",
    "read_analysis_evidence_node",
}

_PROJECT_TOOL_NAMES = {
    "read_project_context",
}

_PROJECT_TOKENS = (
    "项目",
    "任务书",
    "现状资料",
    "项目定位",
    "改造建议",
    "更新建议",
    "空间策划",
)

_CURRENT_POI_TOOL_NAMES = {
    "query_current_pois",
}

_SOURCE_TOOL_NAMES = {
    "list_selected_sources",
    "search_selected_source_evidence",
    "read_selected_source_evidence_node",
}

_REPORT_TOOL_NAMES = {
    "search_report_context",
    "read_report_evidence_node",
}

_SCOPE_DATASET_TOOL_NAMES = {
    "list_scope_datasets",
    "query_scope_dataset",
    "aggregate_scope_dataset",
    "read_scope_record",
}

_BUSINESS_ANALYST_TOOL_NAMES = {
    "plan_business_analyst_analysis",
}

_BUSINESS_ANALYST_TOKENS = (
    "商业",
    "业态",
    "选址",
    "补位",
    "机会",
    "诊断",
    "竞品",
    "客群",
    "适合",
    "值不值得",
    "可不可以",
    "咖啡",
    "餐饮",
    "零售",
    "购物",
    "scorecard",
    "BA",
)

_SCOPE_DATASET_TOKENS = (
    "哪些",
    "多少",
    "几个",
    "明细",
    "列表",
    "具体",
    "全部",
    "所有",
    "每个",
    "排名",
    "最高",
    "最低",
    "top",
    "Top",
    "统计",
    "分组",
    "类别",
    "记录",
    "POI",
    "poi",
    "cell",
    "格子",
    "路段",
)

_CURRENT_POI_TOKENS = (
    "POI",
    "poi",
    "兴趣点",
    "学校",
    "小学",
    "中学",
    "大学",
    "学院",
    "幼儿园",
    "医院",
    "诊所",
    "药店",
    "餐饮",
    "咖啡",
    "商场",
    "酒店",
    "公园",
    "地铁",
)

_REPORT_TOKENS = (
    "报告",
    "章节",
    "PPT",
    "ppt",
    "文稿",
    "页面",
    "图表",
)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _has_artifact(artifacts: Dict[str, Any], key: str) -> bool:
    return bool(isinstance(artifacts, dict) and artifacts.get(key))


def _business_analyst_requires_scope_dataset(artifacts: Dict[str, Any]) -> bool:
    skeleton = artifacts.get("business_analyst_skeleton") if isinstance(artifacts, dict) else {}
    if not isinstance(skeleton, dict):
        return False
    model_tool_map = skeleton.get("model_tool_map") if isinstance(skeleton.get("model_tool_map"), dict) else {}
    encoded = str(model_tool_map)
    return any(name in encoded for name in _SCOPE_DATASET_TOOL_NAMES)


def select_react_tool_registry(
    registry: Dict[str, RegisteredTool],
    *,
    question: str,
    artifacts: Dict[str, Any] | None = None,
    include_secondary: bool = False,
) -> Dict[str, RegisteredTool]:
    visible = llm_visible_registry(registry, include_secondary=include_secondary)
    artifact_payload = dict(artifacts or {})
    question_text = str(question or "")
    allowed = set(_CORE_TOOL_NAMES)
    if _contains_any(question_text, _PROJECT_TOKENS) or _has_artifact(artifact_payload, "project_evidence_dossier"):
        allowed.update(_PROJECT_TOOL_NAMES)
    if _has_artifact(artifact_payload, "selected_sources_context"):
        allowed.update(_SOURCE_TOOL_NAMES)
    if _contains_any(question_text, _REPORT_TOKENS):
        allowed.update(_REPORT_TOOL_NAMES)
    if _contains_any(question_text, _BUSINESS_ANALYST_TOKENS) or _has_artifact(artifact_payload, "business_analyst_skeleton"):
        allowed.update(_BUSINESS_ANALYST_TOOL_NAMES)
    if _contains_any(question_text, _SCOPE_DATASET_TOKENS) or _business_analyst_requires_scope_dataset(artifact_payload):
        allowed.update(_SCOPE_DATASET_TOOL_NAMES)
    if _contains_any(question_text, _CURRENT_POI_TOKENS) and _contains_any(question_text, _SCOPE_DATASET_TOKENS):
        allowed.update(_CURRENT_POI_TOOL_NAMES)
    selected = {name: tool for name, tool in visible.items() if name in allowed}
    if not selected:
        return visible
    return selected


def llm_visible_registry(registry: Dict[str, RegisteredTool], *, include_secondary: bool = False) -> Dict[str, RegisteredTool]:
    visible: Dict[str, RegisteredTool] = {}
    for name, registered in registry.items():
        exposure = str(registered.spec.llm_exposure or "secondary")
        if exposure == "primary" or (include_secondary and exposure == "secondary"):
            visible[name] = registered
    return visible


def chat_completion_tools(registry: Dict[str, RegisteredTool]) -> List[Dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": registered.spec.description,
                "parameters": registered.spec.input_schema or {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
        for name, registered in registry.items()
    ]
