from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def read_previous_chapter(
    *,
    decision_state: Mapping[str, Any],
    current_step_order: int,
    step_key: str = "",
    step_order: int | None = None,
) -> dict[str, Any]:
    """Read one completed chapter while enforcing the current-step boundary."""
    steps = decision_state.get("steps") if isinstance(decision_state, Mapping) else None
    if not isinstance(steps, Mapping):
        raise ValueError("previous_chapter_state_unavailable")

    target_key = str(step_key or "").strip()
    if target_key:
        entry = steps.get(target_key)
    else:
        target_order = int(step_order or 0)
        entry = next(
            (
                value
                for value in steps.values()
                if isinstance(value, Mapping) and int(value.get("step_order") or 0) == target_order
            ),
            None,
        )
    if not isinstance(entry, Mapping):
        raise ValueError("previous_chapter_not_found")

    resolved_order = int(entry.get("step_order") or 0)
    if resolved_order >= int(current_step_order):
        raise ValueError("previous_chapter_must_be_completed_before_current_step")
    chapter = str(entry.get("reader_chapter") or "").strip()
    if not chapter:
        raise ValueError("previous_chapter_content_unavailable")
    return {
        "step_key": target_key or str(entry.get("step_key") or ""),
        "step_order": resolved_order,
        "title": str(entry.get("title") or ""),
        "research_brief": str(entry.get("research_brief") or ""),
        "decision_brief": str(entry.get("decision_brief") or ""),
        "reader_chapter": chapter,
    }


def read_previous_chapter_from_list(
    *,
    completed_chapters: list[Mapping[str, Any]],
    current_step_order: int,
    step_key: str = "",
    step_order: int | None = None,
) -> dict[str, Any]:
    """Adapt the MCP list-shaped input to the canonical chapter reader."""
    steps = {
        str(chapter.get("step_key") or "").strip(): chapter
        for chapter in completed_chapters
        if isinstance(chapter, Mapping) and str(chapter.get("step_key") or "").strip()
    }
    return read_previous_chapter(
        decision_state={"steps": steps},
        current_step_order=current_step_order,
        step_key=step_key,
        step_order=step_order,
    )
