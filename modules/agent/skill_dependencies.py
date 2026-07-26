"""Conditional Skill dependency planning for one Agent turn.

The planner deliberately owns only dependency selection and hand-off metadata.
Each child Skill owns its own research method and completion criteria.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schemas import AgentTurnRequest, EffectiveExecutionProfile
from .skill_catalog import AgentSkillView, SkillDependencyView, get_agent_skill


_CULTURAL_TOURISM_TOKENS = (
    "文旅", "文化旅游", "旅游", "遗产", "历史建筑", "历史文化", "地方文化",
    "非遗", "文物", "古镇", "古村", "古街", "活化", "再利用", "目的地",
    "红色文化", "博物馆", "传统村落", "文化景观",
)


@dataclass(frozen=True)
class PlannedSkillDependency:
    skill_id: str
    when: str


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_text_values(item))
        return values
    if isinstance(value, (list, tuple)):
        values = []
        for item in value:
            values.extend(_text_values(item))
        return values
    return []


def _project_text(payload: AgentTurnRequest) -> str:
    values: list[str] = []
    values.extend(message.content for message in payload.messages if message.role == "user")
    values.extend(_text_values(payload.analysis_snapshot.context))
    values.extend(_text_values(payload.selected_sources_context.source_items()))
    history_id = str(payload.history_id or "").strip()
    if history_id:
        try:
            from modules.spatial_projects.service import SpatialProjectService

            values.extend(_text_values(SpatialProjectService().read_history_project(history_id)))
        except Exception:
            # A missing history snapshot is a project-data gap, not a reason to
            # silently disable a declared dependency.
            pass
    return "\n".join(values).lower()


def _matches(condition: str, payload: AgentTurnRequest) -> bool:
    if condition == "always":
        return True
    if condition == "cultural_heritage_or_destination_activation":
        source = _project_text(payload)
        return any(token.lower() in source for token in _CULTURAL_TOURISM_TOKENS)
    return False


def resolve_skill_dependencies(
    payload: AgentTurnRequest,
    effective_profile: EffectiveExecutionProfile | None,
) -> list[PlannedSkillDependency]:
    """Return the ordered child Skills required before the selected Skill runs."""

    skill_id = str(effective_profile.skill_id if effective_profile else "").strip()
    if not skill_id:
        return []
    parent: AgentSkillView = get_agent_skill(skill_id)
    return [
        PlannedSkillDependency(skill_id=dependency.skill_id, when=dependency.when)
        for dependency in parent.dependencies
        if _matches(dependency.when, payload)
    ]


def skill_instruction(skill_id: str) -> str:
    """Load the child Skill contract once for the prompt-driven executor."""

    path = Path(__file__).resolve().parents[2] / "skills" / skill_id / "SKILL.md"
    return path.read_text(encoding="utf-8")


def cultural_tourism_child_request(payload: AgentTurnRequest) -> str:
    return (
        "执行 cultural-tourism-theme-research 作为 spatial-business-analyst 的前置子阶段。"
        "必须以本轮项目材料、项目范围和已保存的项目数据为边界，完整执行 Skill 中的八类资源调研、分类 POI/空间查询和公开网页检索。"
        "输出可交给父 Skill 的调研结论，明确事实、空间观察、推断、策划假设和待验证事项。"
        f"当前项目 history_id：{str(payload.history_id or '').strip() or '未提供'}。"
        "本 Agent 的已注册适配器中，list_scope_datasets/query_scope_dataset/aggregate_scope_dataset/read_scope_record 对应已保存项目数据查询，search_public_web 对应公开网页检索；优先使用这些工具并保留查询参数。"
        "不能把旧的运行时底稿当作本轮完成结果。"
    )
