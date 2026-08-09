from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .schemas import SpatialStrategyRunAccepted, SpatialStrategyRunDetail


CHAPTERS = (
    ("step_01_policy_site", "政策与场地"),
    ("step_02_regional_role", "区域角色"),
    ("step_03_market_flow", "市场与流动"),
    ("step_04_supply_gap", "供给与空位"),
    ("step_05_audience_use", "客群与使用"),
    ("step_06_theme_resources", "主题与资源"),
    ("step_07_positioning", "项目定位"),
    ("step_08_product_mix", "产品组合"),
    ("step_09_spatial_layout", "空间布局"),
    ("step_10_operating_model", "运营模式"),
    ("step_11_financial_check", "财务校验"),
    ("step_12_phasing", "分期实施"),
)

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


def _chapter_number(step_key: str) -> int | None:
    for index, (candidate, _) in enumerate(CHAPTERS, 1):
        if candidate == step_key:
            return index
    return None


def _chapter_title(step_key: str) -> str:
    for candidate, title in CHAPTERS:
        if candidate == step_key:
            return title
    return ""


def _reader_message(raw_status: str, current_step: str, completed: int) -> str:
    current_number = _chapter_number(current_step)
    current_title = _chapter_title(current_step)
    if raw_status == "queued":
        return "分析任务已接收，正在准备项目资料。"
    if raw_status == "running" and current_number:
        return f"正在分析第 {current_number} 章“{current_title}”，已完成 {completed} 章。"
    if raw_status == "failed" and current_number:
        if completed >= 12:
            return "十二章已经完成，但报告整理暂时未通过检查，可从这里继续。"
        return f"第 {current_number} 章“{current_title}”暂时未完成，前面的结果已保留，可从这里继续。"
    if raw_status == "completed":
        return "十二章分析已完成，报告可以阅读。"
    if raw_status == "cancelled":
        return "分析已停止，已完成的章节仍然保留。"
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
        "title": title_match.group(1).strip() if title_match else "空间分析报告",
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
    completed = max(0, min(12, int(progress.get("completed_steps") or 0)))
    raw_steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    actual_steps = {
        _text(item.get("step")): _mapping(item)
        for item in raw_steps
        if isinstance(item, Mapping)
    }
    chapters = []
    for number, (step_key, title) in enumerate(CHAPTERS, 1):
        actual = actual_steps.get(step_key, {})
        actual_status = _text(actual.get("status")) or "pending"
        if step_key == current_step:
            if raw_status == "failed":
                actual_status = "failed"
            elif raw_status == "running" and actual_status == "pending":
                actual_status = "running"
        output = _mapping(actual.get("output"))
        chapters.append(
            {
                "number": number,
                "title": title,
                "status": CHAPTER_STATUS.get(actual_status, "等待分析"),
                "content": _text(output.get("reader_chapter")),
                "updated_at": actual.get("updated_at"),
            }
        )
    current_number = _chapter_number(current_step)
    current_chapter = (
        {"number": current_number, "title": _chapter_title(current_step)}
        if current_number
        else None
    )
    return SpatialStrategyRunDetail(
        run_id=_text(payload.get("run_id")),
        status=RUN_STATUS.get(raw_status, "准备中"),
        message=_reader_message(raw_status, current_step, completed),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
        progress={"completed_chapters": completed, "total_chapters": 12},
        current_chapter=current_chapter,
        chapters=chapters,
        report=_reader_report(payload.get("report")),
    )
