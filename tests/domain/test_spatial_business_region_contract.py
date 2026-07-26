from pathlib import Path


ROOT = Path(__file__).parents[2]
SKILL_ROOT = ROOT / "skills" / "spatial-business-analyst"
REFERENCES = SKILL_ROOT / "references"
RESEARCH_SKILL_ROOT = ROOT / "skills" / "cultural-tourism-theme-research"
MARKET_SKILL_ROOT = ROOT / "skills" / "spatial-market-audience-research"


def read(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def test_skill_drives_an_adaptive_decision_report():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    for phrase in (
        "定位、空间产品、运营与分期",
        "project_semantic_model",
        "problem_map",
        "decision_logic_map",
        "decision_inventory",
        "list_spatial_metric_results",
        "Codex 原生 Subagent",
        "请确认或修订上述问题地图",
        "publication-editorial.md",
        "总编裁决",
    ):
        assert phrase in skill

    assert "report-example.md" not in skill
    for legacy in (
        "ChapterDeliveryPackage",
        "ChapterAssignment",
        "EditorialReview",
        "publish_spatial_business_run",
        "revision_required",
        "analysis-plan.json",
    ):
        assert legacy not in skill


def test_problem_map_precedes_research_decisions_and_outline():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    model = read("adaptive-report-model.md")
    orchestration = read("report-orchestration.md")

    assert skill.index("## Step 0：前置项目资源调研") < skill.index("## Step 1：准备材料与问题地图")
    assert skill.index("$cultural-tourism-theme-research") < skill.index("`references/adaptive-report-model.md`")
    assert skill.index("`references/adaptive-report-model.md`") < skill.index("从已保存项目开始读取")
    assert "report/research/cultural-tourism-theme-research.md" in skill
    assert skill.index("空的对象型 `payload` 容器") < skill.index("## Step 2：取得用户确认")
    assert skill.index("report/state/problem-map.json") < skill.index("## Step 2：取得用户确认")
    assert skill.index("## Step 2：取得用户确认") < skill.index("## Step 3：完成专项研究并标注证据边界")
    assert skill.index("## Step 2：取得用户确认") < skill.index("$spatial-market-audience-research")
    assert "report/research/spatial-market-audience-research.md" in orchestration
    assert "report/research/spatial-product-market-recheck.md" in orchestration
    assert model.index("## 问题地图") < model.index("## 决策清单")
    assert "波次 0 将 `decision_logic_map`、`decision_inventory` 与 `evidence_summary` 初始化为对象型空容器" in model
    assert "波次 4 写入决策条目和证据摘要" in model
    assert "再列待确认问题及其研究价值，并据此组织研究视角、候选证据和反证来源" in model
    assert "`decision_inventory` 收敛后形成正式章节标题" in model
    assert "## 决策逻辑图" in model
    assert "decision-rulebook.md" in model
    assert "不得把问题改写成" not in model
    assert "项目语义模型与问题地图已完成，决策逻辑图、决策与证据容器为空" in orchestration
    assert "章节边界按决策关系组织，数据类型进入拥有相应决策的证据包" in orchestration
    assert "章节边界跟随决策关系，不跟随数据类型" not in orchestration

    problem_contract = model[model.index("## 问题地图") : model.index("## 决策逻辑图")]
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
    assert "## 自适应深度" not in model
    assert "## 边界表达" not in model


def test_report_contract_owns_only_hard_formal_contracts():
    report = read("report-contract.md")

    for concept in (
        "spatial-business-chapter-index",
        "spatial-business-state-manifest",
        "spatial-business-decision-logic-map",
        "adversarial_review_path",
        "depth_review_path",
        "state_manifest: \"state/manifest.json\"",
        "完整、逐字包含每个接受版本",
        "validate_chapter_assembly.py",
        "publication-editorial.md",
    ):
        assert concept in report

    for leaked_editorial_rule in (
        "## 最小逻辑主线",
        "## 决策闭环",
        "## 写作要求",
        "## 外部证据",
        "## 实施与运营",
        "## 边界与附录",
    ):
        assert leaked_editorial_rule not in report

    assert "把返写请求交回原章节作者" not in report
    assert "返写后的版本通过双审校后成为接受正文" not in report


def test_orchestration_uses_editor_instead_of_low_loss_assembly():
    orchestration = read("report-orchestration.md")

    headings = (
        "## 波次 0：事实底稿、问题地图与逻辑图容器",
        "## 波次 1-3：问题驱动的专项研究",
        "## 波次 4：决策底稿与章节责任",
        "## 波次 5：专业章节纵向循环",
        "## 波次 6：全稿审校与定向返写",
        "## 波次 7：总编裁决与出版装配",
        "## 波次 8：独立视觉证据编辑",
    )
    positions = [orchestration.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "低损耗合编" not in orchestration
    assert "publication-editorial.md" in orchestration
    assert "完成该文件定义的出版核对与定向返写循环" in orchestration
    assert "按 `report-contract.md` 装配" in orchestration
    assert orchestration.index("market_discovery") < orchestration.index("定位与产品策略师只消费")
    assert orchestration.index("定位与产品策略师只消费") < orchestration.index("product_recheck")
    assert orchestration.index("product_recheck") < orchestration.index("## 波次 4：决策底稿与章节责任")
    assert "主 Agent 在波次 4 作最终裁决" in orchestration
    assert "共同事实和证据边界的正文归属" not in orchestration
    assert "审校语言泄漏" not in orchestration


def test_quality_gate_owns_analysis_depth_and_evidence_discipline():
    quality = read("quality-gates.md")

    for heading in (
        "## 分析深度一票退修",
        "## 反方审查",
        "## 深度审校方法",
        "## 正确性与证据纪律",
        "## 证据删除测试",
    ):
        assert heading in quality
    assert "项目特有机制" in quality
    assert "真实候选方向" in quality
    assert "替换项目名称和专有对象后" in quality
    assert "项目条件 → 客群假设 → 客源圈/竞争/需求与支付验证" in quality
    assert "实际使用、政策任务、机构采购和服务履约" in quality
    assert "## 表达密度" not in quality
    assert "## 视觉最低底线" not in quality


def test_roles_keep_specialist_scope_and_delegate_shared_rules():
    roles = read("specialist-roles.md")

    for role in (
        "目标客群与行为综合师",
        "空间结构分析师",
        "定位与产品策略师",
        "空间功能策划师",
        "运营与分期策略师",
        "反方审查员",
        "分析深度审校员",
        "视觉证据编辑",
    ):
        assert f"## {role}" in roles

    assert "quality-gates.md" in roles
    assert "publication-editorial.md" in roles
    assert "每个正式章节必须完整解释" not in roles
    assert "判断；项目原件和空间证据及其比较基准" not in roles
    assert "文旅资源与叙事研究员" not in roles
    assert "文旅市场与客群验证研究员" not in roles
    assert "## 区域与人群分析师" not in roles
    assert "外部客源圈、市场流向和到访频率由市场 Skill 拥有" in roles


def test_project_resource_research_is_a_complete_pre_semantic_workflow():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    research_skill = (RESEARCH_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = (RESEARCH_SKILL_ROOT / "references" / "research-workflow.md").read_text(encoding="utf-8")
    workpacks = (RESEARCH_SKILL_ROOT / "references" / "specialist-workpacks.md").read_text(encoding="utf-8")

    assert "$cultural-tourism-theme-research" in skill
    assert "cultural-tourism-decision-workflow.md" not in skill
    assert not (REFERENCES / "cultural-tourism-decision-workflow.md").exists()
    assert "report/research/cultural-tourism-theme-research.md" in research_skill
    assert "SourceRecord" in research_skill
    assert "EvidenceNode" in research_skill
    assert "不要求转成" in research_skill
    for heading in (
        "## 第一阶段：资源全面收集",
        "## 第二阶段：核心资源筛选",
        "## 第三阶段：共同关系分析",
        "## 第四阶段：资源关系网络",
        "## 第五、六阶段：主题候选与筛选",
        "## 第七、八阶段：故事线与空间结构",
        "## 第九、十阶段：场景与运营转化",
        "## 输出与自检",
    ):
        assert heading in workflow
    for phrase in (
        "自然与地理",
        "物质文化",
        "历史过程",
        "人物与群体",
        "非物质文化",
        "产业与生产",
        "生活方式与日常",
        "精神与价值",
        "来源标题、链接、发布或更新日期",
        "不得为了完成资源数量、主题数量或场景数量而编造事实",
        "## 空间搜算与网页检索",
        "list_history_project_datasets",
        "query_history_project_dataset",
        "aggregate_history_project_dataset",
        "current:dataset:poi",
        "本次调研不实时抓取高德 POI",
        "poi.supply_structure",
        "poi.focused_accessibility",
        "### 八类资源的来源分工",
        "POI 数量不证明真实客流",
    ):
        assert phrase in workflow or phrase in research_skill

    assert "POI/空间搜算和公开网页检索" in skill
    assert "项目材料、POI/空间查询和已打开的原始网页可追溯" in skill
    assert "八类资源覆盖检查" in skill
    assert "历史底稿可提供线索和比较参照" in skill
    assert "specialist-workpacks.md" in research_skill
    for role in (
        "项目本体与八类资源证据分析师",
        "周边空间与文化网络分析师",
        "历史、社会与生产生活关系分析师",
        "主题与叙事综合师",
        "叙事空间转译分析师",
        "场景与运营转化分析师",
        "主题证据与转译审校员",
    ):
        assert role in workpacks
    assert "工作包 2 与工作包 3 在工作包 1 完成后并行执行" in workpacks
    assert "唯一拥有核心资源分级、资源关系网络和主题裁决" in workpacks


def test_market_research_is_a_complete_post_confirmation_two_stage_workflow():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    market_skill = (MARKET_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = (MARKET_SKILL_ROOT / "references" / "research-workflow.md").read_text(encoding="utf-8")
    workpacks = (MARKET_SKILL_ROOT / "references" / "specialist-workpacks.md").read_text(encoding="utf-8")

    assert "$spatial-market-audience-research" in skill
    assert skill.index("## Step 2：取得用户确认") < skill.index("$spatial-market-audience-research")
    assert "market_discovery" in market_skill
    assert "product_recheck" in market_skill
    assert "SourceRecord" not in market_skill
    assert "EvidenceNode" not in market_skill
    assert "SourceRecord" in workflow
    assert "EvidenceNode" in workflow
    assert "不要求转成" in workflow
    assert "第一步至第六步" in market_skill
    assert "第七步：产品市场再校核" in market_skill
    for heading in (
        "## 第一步：项目条件识别",
        "## 第二步：候选客群假设",
        "## 第三步：市场验证",
        "## 第四步：目标客群确定",
        "## 第五步：目标客群与行为链",
        "## 第六步：产品任务与候选业态",
        "## 第七步：产品市场再校核",
        "## 项目类型适配",
        "## 输出与自检",
    ):
        assert heading in workflow
    for role in (
        "项目条件与候选客群分析师",
        "市场母体、客源圈与流向验证分析师",
        "竞争供给与市场缺口分析师",
        "需求与支付验证分析师",
        "目标客群与行为综合师",
        "产品市场再校核分析师",
    ):
        assert role in workpacks
    assert "工作包 2、3、4 在工作包 1 完成后并行" in workpacks
    assert "第二次校核仍不成立" in workflow
    assert "第二次校核仍不成立" not in workpacks
    assert "市场母体" in workflow
    assert "宏观母体只能限定市场上限和结构" in workflow
    assert "多个产品是否争夺同一小客群" in workflow
    assert "没有明确客群的产品降级或退出" in workflow


def test_publication_editorial_is_the_single_source_for_reader_expression():
    editorial = read("publication-editorial.md")

    for concept in (
        "面向读者表达的唯一事实来源",
        "总编职责",
        "出版核对",
        "定向返写",
        "完成条件",
        "唯一完整正文归属",
        "项目对象、当前选择或下一步行动",
        "总编综合只引用接受章节",
        "就绪",
    ):
        assert concept in editorial

    for legacy_return_trigger in (
        "两个章节重复同一决策",
        "章节承担相同读者职责，无法形成连续主线",
        "标题或段落使用反方审查",
        "执行摘要、过渡或综合结论复述章节",
        "一段文本没有改变定位",
    ):
        assert legacy_return_trigger not in editorial

    revision_loop = "作者沿用原证据包生成新版本，通过双审校后回到出版装配。"
    assert editorial.count(revision_loop) == 1
    assert editorial.index("## 定向返写") < editorial.index(revision_loop)
    assert "并把发现的问题定向交回拥有相应决策的原作者" not in editorial


def test_forward_tests_cover_editorial_returns_and_preserved_assembly():
    forward_tests = read("adaptive-forward-tests.md")

    assert "## 总编裁决与出版装配对抗测试" in forward_tests
    assert "唯一完整正文归属" in forward_tests
    assert "退回原作者" in forward_tests
    assert "重新执行反方审查和深度审校" in forward_tests
    assert "完整包含关系" in forward_tests
    assert "低损耗装配" not in forward_tests
    assert "## 市场与客群链路前向测试" in forward_tests
    assert "没有支付或真实使用证据" in forward_tests
    assert "不机械生成游客、OTA、住宿或商业支付分析" in forward_tests
    assert "第二次校核仍不成立" in forward_tests


def test_report_example_is_retired_and_all_references_are_routed():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert not (REFERENCES / "report-example.md").exists()
    for reference in REFERENCES.glob("*.md"):
        assert f"references/{reference.name}" in skill, f"unreachable reference: {reference.name}"


def test_skill_hygiene_has_positive_steering():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert skill.count("**完成条件：**") == 10
    assert "始终交付 `report/project-report.md`" in skill
    assert "scenario_ready" not in skill
    assert "research_incomplete" not in skill
    assert "条件性建议" in skill


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


def test_skill_bundle_contains_only_reachable_current_assets():
    retired = (
        "references/analysis-recipes.md",
        "references/business-model-profiles.md",
        "references/decision-framework.md",
        "references/directional-spatial-fusion.md",
        "references/report-example.md",
        "scripts/render_report_visuals.py",
        "scripts/run_workspace.py",
    )
    for relative_path in retired:
        assert not (SKILL_ROOT / relative_path).exists()
