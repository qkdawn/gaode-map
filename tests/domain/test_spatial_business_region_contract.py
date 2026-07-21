from pathlib import Path


ROOT = Path(__file__).parents[2]
SKILL_ROOT = ROOT / "skills" / "spatial-business-analyst"
REFERENCES = SKILL_ROOT / "references"


def read(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def test_skill_drives_an_adaptive_decision_report():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    for phrase in (
        "工作定位",
        "project_semantic_model",
        "problem_map",
        "decision_inventory",
        "list_spatial_metric_results",
        "query_history_project_dataset",
        "Codex 原生 Subagent DAG",
        "请确认或修订上述问题地图",
    ):
        assert phrase in skill

    for legacy in (
        "ChapterDeliveryPackage",
        "ChapterAssignment",
        "EditorialReview",
        "publish_spatial_business_run",
        "revision_required",
        "analysis-plan.json",
    ):
        assert legacy not in skill


def test_report_contract_is_decision_complete_without_fixed_sections():
    report = read("report-contract.md")

    for concept in (
        "最小逻辑主线",
        "当前判断与推荐方向",
        "项目事实与关键关系",
        "备选方案与取舍",
        "空间、产品与运营方案",
        "实施与验证",
        "证据审计",
        "decision_inventory",
    ):
        assert concept in report
    assert "未涉及的逻辑不强行创建空章节" in report
    assert "报告不设固定页数、图数和章节数量" in report
    assert "章节责任只能在证据收敛后形成" in report
    assert "报告开头继续结论先行" in report
    for depth_concept in (
        "项目特有机制",
        "相对优势",
        "反例与失败条件",
        "承接能力",
        "路径依赖",
        "不来自章节展开、字段数量或篇幅",
    ):
        assert depth_concept in report


def test_problem_map_precedes_research_decisions_and_outline():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    model = read("adaptive-report-model.md")

    assert skill.index("→ 展示 problem_map 并等待用户确认") < skill.index("→ read_spatial_metric_result")
    assert skill.index("### 人工确认门槛") < skill.index("### 波次 1：多视角证据研究")
    for blocked_action in (
        "不读取专项结果明细",
        "不执行新指标",
        "不启动 Subagent",
        "不生成正式大纲",
    ):
        assert blocked_action in skill
    for concrete_question in (
        "为什么选择文化生活",
        "替代路径为什么不优先",
        "居民共存会阻断哪些产品",
        "礼堂与庭院及各栋建筑怎样形成系统",
        "运营主体必须具备什么能力",
        "什么证据会推翻当前选择",
    ):
        assert concrete_question in skill

    assert model.index("## 问题地图") < model.index("## 决策清单")
    problem_contract = model[model.index("## 问题地图") : model.index("## 决策清单")]
    for field in (
        "question:",
        "why_decisive:",
        "candidate_hypotheses:",
        "evidence_needed:",
        "disconfirming_evidence:",
        "dependencies:",
        "status:",
    ):
        assert field in problem_contract
    assert "current_judgment:" not in problem_contract
    assert "action:" not in problem_contract
    assert "文化生活及其他材料偏好只作为候选假设" in model


def test_native_subagent_dag_validates_assembly_before_independent_visual_editing():
    orchestration = read("report-orchestration.md")

    headings = (
        "## 波次 0：事实底稿与问题地图",
        "## 波次 1-3：问题驱动的专项研究",
        "## 波次 4：决策底稿与章节责任",
        "## 波次 5：专业章节纵向循环",
        "## 波次 6：全稿审校与定向返写",
        "## 波次 7：低损耗合编与装配验收",
        "## 波次 8：独立视觉证据编辑",
    )
    positions = [orchestration.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "用户明确确认前，不读取专项指标结果、不执行新指标、不启动 Subagent" in orchestration
    assert "每项重要决策只有一个章节所有者" in orchestration
    assert "失败时不得进入视觉渲染或导出" in orchestration
    assert "主 Agent、章节作者与渲染器都不兼任视觉策划" in orchestration
    assert "只能出现在章节标记之外" in orchestration
    assert "即使零图也保存" in orchestration


def test_quality_gate_prioritizes_analytical_depth_over_baseline_correctness():
    quality = read("quality-gates.md")

    assert quality.index("## 分析深度一票退修") < quality.index("## 正确性最低底线")
    for depth_failure in (
        "用户确认问题地图前已经启动专项研究",
        "正式大纲只是把人口、POI、夜光、路网或专家角色转换成章节名称",
        "项目特有资产、关系、约束或使用机制",
        "反例、失效条件和触发改判的信号",
        "牺牲什么、制造什么后续约束",
        "组织、内容生产、招商、服务交付或现场运营能力",
        "改向、缩减、暂停或退出的成本和办法",
        "替换项目名称后",
    ):
        assert depth_failure in quality

    for adversarial_gate in (
        "没有经过反方审查",
        "最强反驳",
        "静默忽略反方意见",
        "接受、部分接受或不成立",
        "原始反方意见和裁定只用于内部审校",
    ):
        assert adversarial_gate in quality

    assert "全部通过仍不代表报告有深度" in quality
    assert "不展示 Agent、Prompt、内部结构或工具日志" in quality
    assert "删除后，定位、空间、产品或运营决定是否变化" in quality


def test_specialists_return_natural_markdown_and_cover_required_decisions():
    roles = read("specialist-roles.md")

    for role in (
        "区域与人群分析师",
        "空间结构分析师",
        "定位与产品策略师",
        "空间功能策划师",
        "运营与分期策略师",
        "反方审查员",
        "分析深度审校员",
        "视觉证据编辑",
    ):
        assert f"## {role}" in roles

    for section in ("核心判断", "数据依据", "规划含义", "具体动作", "简短边界"):
        assert section in roles
    assert "机器 schema" in roles
    assert "不得全部写成待核实" in roles
    assert "不得只给措辞修补" in roles
    assert "只检查" not in roles
    assert "章节与关键判断" in roles
    assert "无重大反方意见" in roles
    assert "逐项将反方意见裁定为接受、部分接受或不成立" in roles
    assert "所有角色只在用户确认问题地图后启动" in roles
    assert "不按人口、POI、夜光、路网等数据类型分章" in roles
    assert "文化生活或文旅都不是固定菜单" in roles


def test_visual_workflow_is_owned_by_reference_and_independent_subagent():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = read("report-visual-workflow.md")

    assert "### 波次 7：低损耗合编与装配验收" in skill
    assert "### 波次 8：独立视觉证据编辑" in skill
    assert "启动前完整读取 `references/report-visual-workflow.md`" in skill
    for leaked_detail in (
        "poi.supply_structure",
        "poi.focused_accessibility",
        "中心 2 km",
        "Dijkstra",
        "4.5 km/h",
        "report-anchor:poi-route-map",
        "render_report_vega_visuals(history_id",
    ):
        assert leaked_detail not in skill

    for contract in (
        "本文件是报告视觉编排、插入、验收和失败降级的唯一事实来源",
        "正式综合报告每次都启动独立的视觉证据编辑 Subagent",
        "即使零图",
        "主 Agent 不替它选图",
        "确定性工具负责取数和渲染",
        "只能在章节边界之外",
        "视觉生成后重新运行 `validate_chapter_assembly.py`",
        "视觉失败不能触发分析正文降级",
    ):
        assert contract in workflow

    assert "2 km" not in workflow
    assert "4.5 km/h" not in workflow


def test_visual_quality_gate_delegates_details_to_visual_workflow():
    quality = read("quality-gates.md")

    visual_gate = quality[quality.index("## 视觉最低底线") : quality.index("## 最终删除测试")]
    assert "完整遵守 `report-visual-workflow.md`" in visual_gate
    assert "独立视觉 Subagent" in visual_gate
    assert "零图也要保存计划、manifest 和省略原因" in visual_gate
    assert "章节标记之外" in visual_gate
    assert "Dijkstra" not in visual_gate
    assert "4.5 km/h" not in visual_gate


def test_forward_tests_reject_correct_but_shallow_reports():
    forward_tests = read("adaptive-forward-tests.md")

    assert "## 对抗性深度测试" in forward_tests
    assert "即使事实、年份、范围和代理边界全部正确，章节也完整，仍必须退修" in forward_tests
    for missing_analysis in (
        "文化生活为何相对更优",
        "空间选择各自代价",
        "方向失败条件",
        "内容与现场运营能力缺口",
        "付出什么成本",
    ):
        assert missing_analysis in forward_tests
    assert "不需要编造数值阈值" in forward_tests
    assert "项目条件之间的机制、可推翻结论的反例、能力约束对顺序的影响以及可执行的改向路径" in forward_tests
    for process_gate in (
        "首次输出是待用户确认的问题地图",
        "确认前不启动专项研究",
        "简单项目不机械补齐六项",
        "当反证成立时，能够降级为条件性方向或被真实替代方案取代",
        "章节责任只在专项研究和 `decision_inventory` 完成后生成",
    ):
        assert process_gate in forward_tests


def test_forward_tests_challenge_one_sided_chapters_without_forcing_objections():
    forward_tests = read("adaptive-forward-tests.md")

    assert "## 反方审查对抗测试" in forward_tests
    assert "结构完整但单边论证的章节" in forward_tests
    for critique in (
        "低频展示加日常服务",
        "持续生产可重复内容",
        "排期、履约与现场协调能力",
        "可能降级定位并缩小首开范围",
    ):
        assert critique in forward_tests
    assert "不得为凑数量继续制造反对" in forward_tests
    assert "原始反方意见和裁定仍只保留在内部审校中" in forward_tests


def test_production_has_no_retired_v41_report_contract():
    forbidden = (
        "ChapterDeliveryPackage",
        "EditorialReview",
        "AnalysisRunV4",
        "spatial_business_report",
        "analysis-plan.json",
        "editorial-review.json",
        "report_visual_runs",
    )
    production_roots = (ROOT / "modules", ROOT / "router", ROOT / "store")
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for root in production_roots
        for path in root.rglob("*.py")
    )
    for token in forbidden:
        assert token not in corpus


def test_deprojected_example_demonstrates_decision_density_without_project_facts():
    example = read("report-example.md")

    assert "不好的写法" in example
    assert "好的写法" in example
    assert "候选定位比较" in example
    assert "空间机制" in example
    assert "条件性建筑建议" in example
    assert "分期" in example
    for depth_example in (
        "为什么推荐方向胜出",
        "反方审查示例",
        "方向何时失败",
        "多个空间选择的代价",
        "运营能力缺口",
        "改向成本与退出机制",
    ):
        assert depth_example in example
    assert "最终正文只呈现补强后的机制、失败条件和收缩路径" in example
    assert "长沙" not in example


def test_report_contract_keeps_raw_adversarial_review_internal():
    report = read("report-contract.md")

    assert "正式章节在交付前必须逐章经过反方审查和分析深度审校" in report
    assert "原始反方意见、裁定和内部返工过程不属于报告内容" in report
    assert "正文与附录不展示反方审查原文、裁定记录、角色名称或内部返工过程" in report
