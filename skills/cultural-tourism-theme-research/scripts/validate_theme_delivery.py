#!/usr/bin/env python3
"""Check the mandatory structural detail of a cultural-tourism theme report."""

from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SECTIONS = {
    "第七部分": "叙事体系",
    "第八部分": "叙事空间结构",
    "第九部分": "核心叙事空间场景",
    "第十部分": "场景与运营转化表",
}

STORY_FIELDS = (
    "叙事层级", "名称", "起点", "发展", "转折", "高潮", "延续", "当代回应",
    "时间范围", "人物/群体", "核心空间", "核心事件", "主要冲突", "情感基调",
    "游客理解价值", "证据/边界",
)
NODE_FIELDS = (
    "节点", "对应主题/故事线", "资源依据", "叙事任务", "游客行为", "空间类型",
    "展示/体验方式", "日间", "夜间", "活动", "运营主体", "证据/边界",
)
PATH_FIELDS = ("路径", "适用条件", "起点—节点—终点", "交叉/分流方式", "开放与安全边界", "不适用时的替代安排", "验证动作")
OPERATIONS_FIELDS = ("上位主题", "子主题", "故事线", "空间节点", "游客行为", "活动内容", "对应业态", "运营主体", "收益方式", "更新周期", "保护风险", "实施优先级")
DECISION_FIELDS = ("场景", "主要功能", "常设/周期/节庆", "付费可能", "专业团队需求", "可参与主体", "更新周期", "淡季/夜间适用性", "维护成本与安全", "真实性风险", "过度商业化风险", "前置验证")


def section(text: str, name: str) -> str:
    match = re.search(rf"(?ms)^## {re.escape(name)}.*?(?=^## |\Z)", text)
    return match.group(0) if match else ""


def require_fields(errors: list[str], body: str, label: str, fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in body]
    if missing:
        errors.append(f"{label} missing fields: {', '.join(missing)}")


def subsection(body: str, heading: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(heading)}.*?(?=^### |\Z)", body)
    return match.group(0) if match else ""


def table_data_rows(body: str) -> int:
    rows = [line for line in body.splitlines() if line.startswith("|")]
    return max(0, len(rows) - 2)  # Header and Markdown separator.


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_theme_delivery.py <report.md>")
        return 2

    report = Path(sys.argv[1])
    try:
        text = report.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"FAIL cannot read {report}: {exc}")
        return 2

    errors: list[str] = []
    if "[[TODO]]" in text:
        errors.append("report still contains [[TODO]] placeholders")
    document_unavailable = any(marker in text for marker in (
        "未取得任何文档正文",
        "项目原始材料正文不可读",
        "项目原始文档正文未取得",
    ))
    if document_unavailable:
        if "项目本体身份待验证" not in text:
            errors.append("unreadable project documents require: 项目本体身份待验证")
        if "范围背景" not in text:
            errors.append("unreadable project documents require: 范围背景")
    bodies = {name: section(text, name) for name in SECTIONS}
    for name, title in SECTIONS.items():
        if not bodies[name]:
            errors.append(f"missing section: {name}：{title}")

    story = bodies["第七部分"]
    if "### 故事线卡" not in story:
        errors.append("第七部分 missing heading: ### 故事线卡")
    require_fields(errors, story, "story cards", STORY_FIELDS)

    spatial = bodies["第八部分"]
    if "### 节点与路径清单" not in spatial:
        errors.append("第八部分 missing heading: ### 节点与路径清单")
    require_fields(errors, spatial, "node list", NODE_FIELDS)
    require_fields(errors, spatial, "path list", PATH_FIELDS)
    path_types = {
        "主游线": ("主游线",),
        "次游线": ("次游线",),
        "居民日常": ("居民日常",),
        "夜游": ("夜游",),
        "节庆": ("节庆",),
        "雨天/淡季": ("雨天/淡季", "雨天淡季", "雨天或淡季"),
    }
    for path_type, accepted_labels in path_types.items():
        if not any(label in spatial for label in accepted_labels):
            errors.append(f"第八部分 missing path type: {path_type}")

    scenes = bodies["第九部分"]
    starts = list(re.finditer(r"(?m)^### .+$", scenes))
    cards = [
        scenes[start.end(): starts[position + 1].start() if position + 1 < len(starts) else len(scenes)]
        for position, start in enumerate(starts)
    ]
    if not 8 <= len(cards) <= 12:
        errors.append(f"第九部分 requires 8-12 scene cards, found {len(cards)}")
    for number, card in enumerate(cards, start=1):
        for index in range(1, 21):
            if not re.search(rf"(?m)(?<!\d){index}\.\s*", card):
                errors.append(f"scene card {number} missing field number: {index}")
        missing_senses = [sense for sense in ("视觉", "听觉", "触觉", "嗅觉", "味觉") if sense not in card]
        if missing_senses:
            errors.append(f"scene card {number} missing separated senses: {', '.join(missing_senses)}")

    operations = bodies["第十部分"]
    if "### 场景与运营关系表" not in operations:
        errors.append("第十部分 missing heading: ### 场景与运营关系表")
    if "### 逐场景运营判断" not in operations:
        errors.append("第十部分 missing heading: ### 逐场景运营判断")
    require_fields(errors, operations, "operations table", OPERATIONS_FIELDS)
    require_fields(errors, operations, "operations decision", DECISION_FIELDS)
    relationship_rows = table_data_rows(subsection(operations, "### 场景与运营关系表"))
    decision_rows = table_data_rows(subsection(operations, "### 逐场景运营判断"))
    if relationship_rows < len(cards):
        errors.append(f"operations relationship table has {relationship_rows} rows for {len(cards)} scene cards")
    if decision_rows < len(cards):
        errors.append(f"operations decision table has {decision_rows} rows for {len(cards)} scene cards")

    if errors:
        print("FAIL theme delivery validation")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS theme delivery validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
