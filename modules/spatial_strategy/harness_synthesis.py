from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HARNESS_RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "codex-harness"
BLUEPRINT_SCHEMA_PATH = Path(__file__).with_name("report_blueprint.schema.json")
CORE_PROMPT = "基于已有项目材料和空间数据完成用户任务，给出明确判断及行动建议。不要虚构信息；无法完成时直接说明原因。"
DECISION_MEMO_SCHEMA_PATH = Path(__file__).with_name("decision_memo.schema.json")
REPORT_SECTION_SCHEMA_PATH = Path(__file__).with_name("report_section.schema.json")
VISUAL_DESIGN_SCHEMA_PATH = Path(__file__).with_name("visual_design.schema.json")


class SpatialStrategyHarnessError(RuntimeError):
    pass


def _prompt(*, run_id: str, project_question: str) -> str:
    return "\n".join(
        [
            CORE_PROMPT,
            "这是城市空间策略的综合阶段，不写正式报告正文。",
            f"项目任务：{project_question}",
            f"运行编号：{run_id}",
            "先调用 spatial-project MCP 的 read_strategy_decisions，只传入上述运行编号，读取已经完成的领域决策。",
            "在这些决策之间完成取舍和整合：比较至少三个候选定位，选择一个推荐定位；明确未来空间与使用状态、优先使用者、使用场景、产品与运营组合、空间改变机制、首期行动和后续分期。",
            "保留会改变方案选择的具名 POI、道路、路径、建筑和地点，并在相关判断中使用其名称、空间关系、距离或指标，不用笼统方位替代已有的具体对象。",
            "刚性条件应转化为分区、分时、独立流线或可逆改造等具体响应；未来客群和使用场景是策略选择，不要求现状数据证明其必然发生。",
            "以项目准备创造的未来状态和可实施空间项目包为主体。产权、保护、结构和消防核定只写入直接受其影响的行动，不得代替角色、客群、场景、空间配置或首期项目包。",
            "五个章节依次为：项目未来角色与总体判断；优先使用者及未来使用场景；产品和运营组合；入口、路径、建筑、院落与住宅界面的空间策略；首期项目包、实施顺序与预期改变。",
            "最终只返回符合指定 JSON Schema 的综合蓝图。",
        ]
    )


def _run_codex(*, prompt: str, schema_path: Path, enabled_tools: list[str]) -> dict:
    codex = shutil.which("codex")
    if not codex:
        raise SpatialStrategyHarnessError("codex_harness_unavailable")

    HARNESS_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=HARNESS_RUNTIME_ROOT) as directory:
        output_path = Path(directory) / "result.json"
        enabled_tools_config = "mcp_servers.spatial-project.enabled_tools=" + json.dumps(enabled_tools)
        completed = subprocess.run(
            [
                codex,
                "-a",
                "never",
                "exec",
                "--ephemeral",
                "--color",
                "never",
                "--sandbox",
                "danger-full-access",
                "--cd",
                str(PROJECT_ROOT),
                "--disable",
                "tool_suggest",
                "-c",
                enabled_tools_config,
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ],
            cwd=PROJECT_ROOT,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "codex_exec_failed").strip()[-1200:]
            raise SpatialStrategyHarnessError(f"codex_harness_failed: {detail}")
        try:
            result = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SpatialStrategyHarnessError("codex_harness_invalid_output") from exc
        if not isinstance(result, dict):
            raise SpatialStrategyHarnessError("codex_harness_invalid_output")
        return result


def synthesize_strategy_blueprint(*, run_id: str, project_question: str) -> dict:
    return _run_codex(
        prompt=_prompt(run_id=run_id, project_question=project_question),
        schema_path=BLUEPRINT_SCHEMA_PATH,
        enabled_tools=["read_strategy_decisions"],
    )


def analyze_strategy_unit(
    *,
    run_id: str,
    history_id: str,
    project_question: str,
    decision_unit: dict,
) -> dict:
    unit = json.dumps(decision_unit, ensure_ascii=False)
    prompt = "\n".join(
        [
            CORE_PROMPT,
            f"项目任务：{project_question}",
            f"运行编号：{run_id}",
            f"项目材料编号：{history_id}",
            f"当前城市空间决策任务：{unit}",
            "读取已有决策和完成当前判断所需的项目材料与空间数据。把现状转化为明确的未来选择；每项行动说明做什么、服务谁、落在哪里、优先级和预期改变。",
            "需要空间证据时，把完整空间问题交给 analyze_spatial_question；空间工具 Agent 负责拆分子问题、选择事实域、空间操作和必要语义维度，并执行多次互补计算。当前决策单元不要选择底层指标或计算模式。",
            "工具选择：项目材料用于场地条件，空间工具用于名称、坐标、距离、道路与 POI 关系及指标，文献检索用于方法和案例机制。只有具名对象的公开属性会改变当前判断时才联网，查询使用“所在城市或区县 + 准确名称 + 待确认属性”，并读取选中的原网页；不逐个搜索无关对象。",
            "空间数据包含具名 POI、道路、路径、建筑或地点时，在 named_entities 中保留真实名称、对象类型、空间关系、具体事实和已有记录引用；没有具名数据时返回空数组。",
            "最终只返回符合指定 JSON Schema 的当前决策结果。",
        ]
    )
    return _run_codex(
        prompt=prompt,
        schema_path=DECISION_MEMO_SCHEMA_PATH,
        enabled_tools=[
            "read_strategy_decisions",
            "analyze_spatial_question",
            "read_project_document",
            "search_literature_evidence",
            "search_public_web",
            "fetch_public_web_page",
        ],
    )


def write_strategy_section(*, project_question: str, solution: dict, section: dict) -> dict:
    prompt = "\n".join(
        [
            CORE_PROMPT,
            "只撰写一个正式报告章节。输出判断、依据和行动建议，不描述 Agent、工具、工作流或执行过程。",
            f"项目任务：{project_question}",
            "已选方案：" + json.dumps(solution, ensure_ascii=False),
            "本章任务：" + json.dumps(section, ensure_ascii=False),
            "正文直接说明服务谁、形成什么使用方式、做什么、放在哪里、何时实施以及预期改变什么；不重复其他章节。",
            "相关依据已有具名 POI、道路、路径、建筑或地点时，正文使用其真实名称和具体距离或指标，不退化为只有方向和汇总数量的描述。",
            "最终只返回符合指定 JSON Schema 的章节。",
        ]
    )
    return _run_codex(prompt=prompt, schema_path=REPORT_SECTION_SCHEMA_PATH, enabled_tools=[])


def design_strategy_visuals(*, project_question: str, solution: dict, available_datasets: list[dict]) -> dict:
    prompt = "\n".join(
        [
            CORE_PROMPT,
            "为已选城市空间方案设计3到5张数据图或表，只呈现能够解释定位选择、空间配置或行动顺序的现有项目数据。",
            f"项目任务：{project_question}",
            "已选方案：" + json.dumps(solution, ensure_ascii=False),
            "可用数据：" + json.dumps(available_datasets, ensure_ascii=False),
            "只使用可用数据列表中的 dataset_id。每张图的 caption 直接说明数据支持哪项方案选择或行动；不写待验证说明，不生成现有数据无法支持的建筑级图件。",
            "同时存在 poi 和 road_edges 时，至少设计一张 poi_access 或 context_full 地图，用具名 POI 和道路名称说明连接关系。",
            "最终只返回符合指定 JSON Schema 的图件方案。",
        ]
    )
    return _run_codex(prompt=prompt, schema_path=VISUAL_DESIGN_SCHEMA_PATH, enabled_tools=[])
