from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .schemas import SpatialStrategyRunAccepted, SpatialStrategyRunDetail


RUN_STATUS = {
    "queued": "准备中",
    "running": "分析中",
    "completed": "已完成",
    "failed": "需要处理",
    "cancelled": "已停止",
}

CHAPTER_STATUS = {
    "pending": "等待分析",
    "queued": "等待分析",
    "running": "正在分析",
    "completed": "已完成",
    "failed": "需要处理",
    "revision_required": "需要处理",
    "cancelled": "已停止",
    "skipped": "已停止",
}

EVIDENCE_LABELS = {
    "project_document": "项目材料",
    "project_data": "项目数据",
    "project_data_record": "项目数据",
    "project_computed_result": "空间数据",
    "knowledge_base": "公开资料",
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _chapter_number(step_key: str, chapter_order: Mapping[str, int] | None = None) -> int | None:
    return chapter_order.get(step_key) if chapter_order else None


def _chapter_title(step_key: str, chapter_titles: Mapping[str, str] | None = None) -> str:
    return chapter_titles.get(step_key, "") if chapter_titles else ""


def _reader_message(raw_status: str, current_step: str, completed: int, total: int, chapter_order: Mapping[str, int] | None = None, chapter_titles: Mapping[str, str] | None = None) -> str:
    current_number = _chapter_number(current_step, chapter_order)
    current_title = _chapter_title(current_step, chapter_titles)
    if raw_status == "queued":
        return "分析任务已接收，正在准备项目资料。"
    if raw_status == "running" and current_number:
        return f"正在分析第 {current_number} 个决策单元“{current_title}”，已完成 {completed} / {total} 个分析单元。"
    if raw_status == "failed" and current_number:
        if completed >= total:
            return "决策单元已经完成，但报告整理暂时未通过检查，可从这里继续。"
        return f"第 {current_number} 个决策单元“{current_title}”暂时未完成，前面的结果已保留，可从这里继续。"
    if raw_status == "completed":
        return "分析单元已完成，报告可以阅读。"
    if raw_status == "cancelled":
        return "分析已停止，已完成的决策单元仍然保留。"
    return "分析状态正在更新。"


def _report_summary(markdown: str) -> str:
    match = re.search(r"^## 总判断\s*$\n+(.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _reader_report(value: Any) -> dict[str, Any] | None:
    report = _mapping(value)
    markdown = _text(report.get("markdown"))
    if not report or not markdown:
        return None
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    labels: list[str] = []
    for citation in report.get("citations") if isinstance(report.get("citations"), list) else []:
        source_type = _text(_mapping(citation).get("source_type"))
        label = EVIDENCE_LABELS.get(source_type, "待现场核验")
        if label not in labels:
            labels.append(label)
    manifest = _mapping(report.get("asset_manifest"))
    visual_assets = manifest.get("visual_assets") if isinstance(manifest.get("visual_assets"), list) else []
    return {
        "title": title_match.group(1).strip() if title_match else "空间策略与行动方案",
        "summary": _report_summary(markdown),
        "markdown": markdown,
        "evidence_labels": labels,
        "visual_assets": visual_assets,
        "updated_at": report.get("updated_at"),
    }


def project_run_accepted(payload: Mapping[str, Any]) -> SpatialStrategyRunAccepted:
    return SpatialStrategyRunAccepted(
        accepted=True,
        run_id=_text(payload.get("run_id")),
        status="准备中",
        message="分析任务已接收，正在准备项目资料。",
        status_url=_text(payload.get("status_url")),
    )


def project_run_detail(payload: Mapping[str, Any]) -> SpatialStrategyRunDetail:
    raw_status = _text(payload.get("status"))
    current_step = _text(payload.get("current_step"))
    progress = _mapping(payload.get("progress"))
    raw_steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    actual_steps = {
        _text(item.get("step")): _mapping(item)
        for item in raw_steps
        if isinstance(item, Mapping)
    }
    state = _mapping(payload.get("decision_state"))
    plan = state.get("decision_units") if isinstance(state.get("decision_units"), list) else []
    planned_keys = [_text(item.get("unit_id")) for item in plan if isinstance(item, Mapping) and _text(item.get("unit_id"))]
    ordered_keys = planned_keys or list(actual_steps)
    chapter_order = {key: index for index, key in enumerate(ordered_keys, 1)}
    chapter_titles = {
        _text(item.get("unit_id")): _text(item.get("title"))
        for item in plan
        if isinstance(item, Mapping) and _text(item.get("unit_id")) and _text(item.get("title"))
    }
    total = max(1, min(32, int(progress.get("total_steps") or len(ordered_keys) or 1)))
    completed = max(0, min(total, int(progress.get("completed_steps") or 0)))
    chapters = []
    display_keys = ordered_keys
    for number, step_key in enumerate(display_keys, 1):
        title = chapter_titles.get(step_key) or _chapter_title(step_key, chapter_titles) or _text(actual_steps.get(step_key, {}).get("output", {}).get("title")) or step_key
        actual = actual_steps.get(step_key, {})
        actual_status = _text(actual.get("status")) or "pending"
        if step_key == current_step:
            if raw_status == "failed":
                actual_status = "failed"
            elif raw_status == "running" and actual_status == "pending":
                actual_status = "running"
        output = _mapping(actual.get("output"))
        content = _text(output.get("content"))
        chapters.append(
            {
                "number": number,
                "title": title,
                "status": CHAPTER_STATUS.get(actual_status, "等待分析"),
                "content": content,
                "updated_at": actual.get("updated_at"),
            }
        )
    current_number = _chapter_number(current_step, chapter_order)
    current_chapter = (
        {"number": current_number, "title": _chapter_title(current_step, chapter_titles) or current_step}
        if current_number
        else None
    )
    return SpatialStrategyRunDetail(
        run_id=_text(payload.get("run_id")),
        status=RUN_STATUS.get(raw_status, "准备中"),
        message=_reader_message(raw_status, current_step, completed, total, chapter_order, chapter_titles),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
        progress={"completed_chapters": completed, "total_chapters": total},
        current_chapter=current_chapter,
        chapters=chapters,
        report=_reader_report(payload.get("report")),
    )
