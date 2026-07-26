#!/usr/bin/env python3
"""Render a formal decision logic map from the persisted report state."""
from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from textwrap import wrap
from typing import Any


STATE_PATH = Path("state/decision-logic-map.json")
OUTPUT_PATH = Path("decision-logic-map.svg")
WIDTH = 1840
MARGIN = 40
COLUMN_GAP = 18
COLUMN_WIDTHS = (330, 290, 330, 390, 330)
HEADER_HEIGHT = 126
ROW_GAP = 24
CARD_PADDING = 18
TITLE_LINE_HEIGHT = 28
TEXT_LINE_HEIGHT = 22
BODY_LINE_WIDTH = 20

COLORS = {
    "supported": ("#E9F7EE", "#20734A"),
    "conditional": ("#FFF7E6", "#A95A00"),
    "excluded": ("#F9ECEC", "#B1413D"),
}


def _text_lines(value: Any, width: int = BODY_LINE_WIDTH) -> list[str]:
    if isinstance(value, list):
        source = [str(item).strip() for item in value if str(item).strip()]
    else:
        source = [str(value).strip()] if str(value).strip() else []
    lines: list[str] = []
    for item in source:
        lines.extend(wrap(item, width=width, break_long_words=True, break_on_hyphens=False) or [item])
    return lines or ["未提供"]


def _metric_lines(rule: dict[str, Any]) -> list[str]:
    metrics = rule.get("metric_refs") or []
    if not metrics:
        return ["未使用空间指标"]
    lines: list[str] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        tool_id = str(metric.get("tool_id", "未命名指标"))
        observation = str(metric.get("observation", ""))
        effect = str(metric.get("decision_effect", ""))
        # Metric identifiers are stable evidence handles and must remain searchable in the SVG.
        lines.append(tool_id)
        lines.extend(_text_lines(observation, 20))
        lines.extend(_text_lines(f"影响: {effect}", 20))
    return lines or ["未使用空间指标"]


def _card_height(title: str, lines: list[str]) -> int:
    return CARD_PADDING * 2 + TITLE_LINE_HEIGHT + len(_text_lines(title, 17)) * TEXT_LINE_HEIGHT + len(lines) * TEXT_LINE_HEIGHT


def _draw_card(x: int, y: int, width: int, height: int, title: str, lines: list[str], fill: str, stroke: str) -> str:
    parts = [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
    ]
    cursor = y + CARD_PADDING + TITLE_LINE_HEIGHT
    for line in _text_lines(title, 17):
        parts.append(f'<text x="{x + CARD_PADDING}" y="{cursor}" class="card-title">{escape(line)}</text>')
        cursor += TEXT_LINE_HEIGHT
    cursor += 4
    for line in lines:
        parts.append(f'<text x="{x + CARD_PADDING}" y="{cursor}" class="card-text">{escape(line)}</text>')
        cursor += TEXT_LINE_HEIGHT
    return "".join(parts)


def _rule_cards(rule: dict[str, Any]) -> list[tuple[str, list[str]]]:
    return [
        ("条件与事实", _text_lines(rule.get("when"))),
        (f"{rule.get('id', '规则')} | {rule.get('decision_question', '决策问题')}", _metric_lines(rule)),
        ("候选与反例", _text_lines(rule.get("alternatives")) + _text_lines(f"反例: {rule.get('counterexample', '')}")),
        ("当前结论与动作", _text_lines(f"结论: {rule.get('judgment', '')}") + _text_lines(f"动作: {rule.get('action', '')}")),
        ("验证与边界", _text_lines(rule.get("limitations")) + _text_lines(f"验证: {rule.get('validation', '')}")),
    ]


def render(report_dir: Path, output_path: Path | None = None) -> Path:
    report_dir = report_dir.resolve()
    state_path = report_dir / STATE_PATH
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    logic_map = payload.get("payload") if isinstance(payload, dict) else None
    if not isinstance(logic_map, dict) or logic_map.get("status") != "ready":
        raise ValueError("decision_logic_map_ready_required")
    rules = logic_map.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("decision_logic_map_rules_required")

    output_path = (output_path or report_dir / OUTPUT_PATH).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_specs: list[tuple[dict[str, Any], list[tuple[str, list[str]]], int]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        cards = _rule_cards(rule)
        height = max(_card_height(title, lines) for title, lines in cards)
        row_specs.append((rule, cards, height))
    if not row_specs:
        raise ValueError("decision_logic_map_rules_required")

    height = HEADER_HEIGHT + MARGIN + sum(row_height + ROW_GAP for _, _, row_height in row_specs)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}">',
        "<style>"
        ".title{font:700 30px 'Microsoft YaHei',Arial,sans-serif;fill:#12352A}"
        ".subtitle{font:400 16px 'Microsoft YaHei',Arial,sans-serif;fill:#547168}"
        ".column{font:700 17px 'Microsoft YaHei',Arial,sans-serif;fill:#164D3C}"
        ".card-title{font:700 17px 'Microsoft YaHei',Arial,sans-serif;fill:#173F33}"
        ".card-text{font:400 15px 'Microsoft YaHei',Arial,sans-serif;fill:#24483D}"
        ".arrow{stroke:#729B8A;stroke-width:2;marker-end:url(#arrow)}"
        "</style>",
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#729B8A"/></marker></defs>',
        f'<rect width="{WIDTH}" height="{height}" fill="#F7FAF8"/>',
        f'<text x="{MARGIN}" y="48" class="title">空间商业决策逻辑图</text>',
        f'<text x="{MARGIN}" y="76" class="subtitle">事实与条件如何推导当前选择；每个节点保留反例、指标边界和验证路径。</text>',
    ]
    columns = ("条件与事实", "判断规则与指标", "候选与反例", "当前结论与动作", "验证与边界")
    x = MARGIN
    for index, label in enumerate(columns):
        parts.append(f'<text x="{x}" y="{HEADER_HEIGHT - 20}" class="column">{label}</text>')
        x += COLUMN_WIDTHS[index] + COLUMN_GAP

    y = HEADER_HEIGHT
    for rule, cards, row_height in row_specs:
        fill, stroke = COLORS.get(str(rule.get("status")), COLORS["conditional"])
        x = MARGIN
        for index, (title, lines) in enumerate(cards):
            parts.append(_draw_card(x, y, COLUMN_WIDTHS[index], row_height, title, lines, fill, stroke))
            if index < len(cards) - 1:
                arrow_x = x + COLUMN_WIDTHS[index]
                parts.append(f'<line x1="{arrow_x + 4}" y1="{y + row_height // 2}" x2="{arrow_x + COLUMN_GAP - 5}" y2="{y + row_height // 2}" class="arrow"/>')
            x += COLUMN_WIDTHS[index] + COLUMN_GAP
        y += row_height + ROW_GAP
    parts.append("</svg>")
    output_path.write_text("".join(parts), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a spatial business decision logic map as SVG.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    print(render(Path(args.report_dir), Path(args.output) if args.output else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
