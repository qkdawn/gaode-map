from __future__ import annotations

from pathlib import Path

from modules.agent_harness import CodexHarnessError, run_codex
from modules.spatial_action.spatial_evidence import EVIDENCE_DIMENSION_BINDINGS, FACT_DOMAIN_CAPABILITIES


SPATIAL_ANALYSIS_SCHEMA_PATH = Path(__file__).with_name("spatial_tool_analysis.schema.json")
SPATIAL_EVIDENCE_KNOWLEDGE = (
    "POI与设施供给描述设施数量、类别、集中和相对供给，不直接证明需求或运营质量；"
    "人口规模与结构描述潜在服务背景，不等于真实使用者；"
    "夜光描述夜间活动背景，不替代客流、消费或具体业态；"
    "路网结构描述连接、到达潜力和穿行潜力，不等于实际交通量；"
    "accessibility使用真实路网时间圈回答不同时间范围内能够覆盖什么；"
    "neighborhood和relationship表达局部邻接与跨域共位，共位不表示因果；"
    "inspect把聚合格局落实到真实地点和道路，返回的具名对象不等于已确认的重要节点。"
)


def _fact_domain_catalog() -> str:
    return "；".join(
        f"{binding.domain}（{binding.description}；维度：{','.join(binding.dimensions)}）"
        for binding in FACT_DOMAIN_CAPABILITIES.values()
    )


class SpatialToolAgentError(RuntimeError):
    pass


def analyze_spatial_question(*, history_id: str, question: str) -> dict:
    """Use Codex Harness to plan, execute, and synthesize spatial computations."""

    normalized_history_id = str(history_id or "").strip()
    normalized_question = str(question or "").strip()
    if not normalized_history_id:
        raise ValueError("history_id_required")
    if not normalized_question:
        raise ValueError("question_required")

    prompt = "\n".join(
        [
            "你是城市空间工具 Agent。理解用户问题，将其拆成必要的空间子问题，调用确定性空间计算工具，并综合多次结果。",
            f"项目材料编号：{normalized_history_id}",
            f"空间问题：{normalized_question}",
            "事实域知识：" + SPATIAL_EVIDENCE_KNOWLEDGE,
            "可选事实域：" + _fact_domain_catalog(),
            "可选空间操作：scope用于范围事实和事实域发现；accessibility用于真实路网时间圈；direction用于八方向比较；neighborhood用于指定单元邻域；rank用于单域极值；relationship用于2至4个事实域的共位；inspect用于展开已有记录引用。",
            "选择能够改变问题判断的最小证据组合。总体存量用scope；空间流向用direction；服务覆盖用accessibility；寻找极值后可继续inspect或neighborhood；只有问题要求跨域共同出现或错位时才用relationship。不要用scope总量回答方向、可达性或局部关系问题。",
            "只调用 compute_spatial_evidence 获取空间事实。根据每个子问题选择事实域、空间关系、必要的语义维度和数据筛选；复杂问题应拆分并进行多次互补计算。不要选择或枚举底层指标，具体字段和聚合策略由领域工具内部决定。",
            "rank和relationship必须为每个事实域明确一个语义维度。road.to_movement表示到达潜力，road.through_movement表示穿行潜力，不能互相替代。",
            "道路rank默认返回线段；问题明确要求连续骨架或廊道时，增加road.object=corridor，并选择road.to_movement或road.through_movement。",
            "需要具名地点或道路时先用rank取得record_ref，或直接用已有record_ref调用inspect；需要核查候选周边关系时调用neighborhood。",
            "区分计算事实与空间解释；只依据工具返回结果形成判断，并在每个子问题的 computation_refs 中保留所用 result_id。工具执行失败或证据不足时直接说明，不虚构结果。",
            "最终只返回符合指定 JSON Schema 的空间分析结果。",
        ]
    )
    try:
        return run_codex(
            prompt=prompt,
            schema_path=SPATIAL_ANALYSIS_SCHEMA_PATH,
            enabled_tools=["compute_spatial_evidence"],
        )
    except CodexHarnessError as exc:
        raise SpatialToolAgentError(str(exc)) from exc
