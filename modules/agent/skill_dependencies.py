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
    stage: str = "preflight"


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
    if condition == "formal_problem_map_confirmed":
        problem_map = payload.analysis_snapshot.context.get("problem_map")
        return isinstance(problem_map, dict) and str(problem_map.get("status") or "").strip().lower() == "confirmed"
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
        PlannedSkillDependency(skill_id=dependency.skill_id, when=dependency.when, stage=dependency.stage)
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


def market_audience_child_request(
    payload: AgentTurnRequest,
    *,
    stage: str,
    parent_drafts: dict[str, Any] | None = None,
    check_number: int | None = None,
) -> str:
    if stage == "market_discovery":
        stage_instructions = (
            "执行 market_discovery：问题地图已经确认。先建立项目条件、候选客群、市场母体/客源圈、"
            "竞争或替代供给、需求与支付或公共服务履约的证据，再形成唯一的目标与排除客群判断。"
            "把结果保存为稳定的第一阶段研究工件；本阶段不得把候选客群写成已验证目标。"
        )
    elif stage == "product_recheck":
        if check_number not in {1, 2}:
            raise ValueError("product_recheck_requires_check_number")
        check_instruction = (
            "这是第一次校核；必须逐产品固定 product_id，并在 ToolLoopResult.artifacts.first_product_recheck 返回"
            " {status: first, products: [{product_id, verdict, rationale, revision_required, owner_roles}]}；"
            "owner_roles 只能取 spatial_structure、positioning_product、spatial_function_programming、operations_phasing，"
            "不需返写时 revision_required=false 且 owner_roles=[]；需要返写时只列真正负责返写的角色。"
            if check_number == 1
            else (
                "这是返写后的第二次且最终校核；仍不成立的内容必须直接裁决为条件性、延后或退出，"
                "不得要求第三次返写。必须在 ToolLoopResult.artifacts.final_product_recheck 返回"
                " {status: final, products: [{product_id, verdict, rationale, conditions}]}；"
                "verdict 只能是成立、缩减、条件性、延后、退出。若执行器不能直接写 artifacts，"
                "最终响应必须只返回同一 final_product_recheck JSON 对象，不附加说明文字，运行时会将其结构化持久化。"
            )
        )
        stage_instructions = (
            "执行 product_recheck：父级定位、空间和运营草案已经提供。逐产品校核客群覆盖、空间容量、"
            f"价格或价值交换、收入成本、运营主体和分期。{check_instruction}"
            "若直接记录不足，输出条件性建议、停止条件和校准记录，不补造客流、收入或许可。"
        )
    else:
        raise ValueError(f"unsupported_market_research_stage:{stage}")
    return (
        f"执行 spatial-market-audience-research 的 {stage} 阶段。{stage_instructions}"
        f"当前项目 history_id：{str(payload.history_id or '').strip() or '未提供'}。"
        "必须先让现有工具分配子代理按市场研究角色授予工具。候选工具必须覆盖公开检索、项目材料、"
        "当前 POI 与范围数据集/指标；只使用被授予且与证据目标相关的工具。"
        "使用本轮材料与工件，不能把旧运行时底稿当作已完成的市场证据。"
        + (f"父级草案工件：{parent_drafts}" if parent_drafts else "")
    )


def formal_specialist_request(
    payload: AgentTurnRequest,
    *,
    role: str,
    upstream_artifacts: dict[str, Any],
    revision_context: dict[str, Any] | None = None,
) -> str:
    role_instructions = {
        "spatial_structure": (
            "作为空间结构分析师，研究项目内部入口、连接、停留、流线、承载与现场断点；"
            "不得替代市场角色判断外部客源圈、到访频率或支付。"
        ),
        "positioning_product": (
            "作为定位与产品策略师，消费本轮资源主题、市场发现和空间结构工件，比较真实候选路径，"
            "形成工作定位、候选取舍、首批产品、使用情境与增长边界；不得重新发明目标客群。"
            "必须在 ToolLoopResult.artifacts.product_inventory 返回完整稳定清单："
            " {status: draft, products: [{product_id, name}]}。定向返写保留同一组 product_id，"
            "需要缩减、延后或退出的产品仍保留其身份供最终再校核裁决。"
        ),
        "spatial_function_programming": (
            "作为空间功能策划师，将本轮工作定位落实到真实空间对象、服务对象、时段、协同冲突、"
            "支持功能和分期顺序，形成可供产品市场再校核的空间功能草案。"
        ),
        "operations_phasing": (
            "作为运营与分期策略师，基于本轮定位与空间功能草案形成运营主体、活动节律、"
            "价值交换、能力要求和分期动作，不把未知成本、客流、许可或支付补造为事实。"
        ),
    }
    if role not in role_instructions:
        raise ValueError(f"unsupported_formal_specialist_role:{role}")
    revision_instruction = ""
    if revision_context:
        revision_instruction = (
            "这是第一次产品市场再校核后的唯一一次定向返写。只修改校核意见明确影响本角色所有权的内容，"
            "其余已成立判断保持不变；返回本角色完整的新版本，不得提出或预留第二次返写。"
            f"第一次校核：{revision_context}。"
        )
    return (
        f"执行 spatial-business-analyst 正式链路中的独立角色 {role}。"
        f"{role_instructions[role]}{revision_instruction}"
        f"当前项目 history_id：{str(payload.history_id or '').strip() or '未提供'}。"
        "必须只消费本轮已确认问题地图与下列本轮上游工件，历史报告只能作为线索，不能冒充本轮产出。"
        f"本轮上游工件：{upstream_artifacts}。"
        "输出核心判断、数据依据、候选与反例、规划含义、具体动作及证据边界。"
    )
