from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "spatial-business-analyst"
MARKET_ROOT = ROOT / "skills" / "spatial-market-audience-research"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_formal_workflow_has_one_reader_output_and_full_professional_chain() -> None:
    skill = _read(SKILL_ROOT / "SKILL.md")
    contract = _read(SKILL_ROOT / "references" / "report-contract.md")
    editorial = _read(SKILL_ROOT / "references" / "publication-editorial.md")

    assert "始终交付 `report/project-report.md`" in skill
    assert "唯一读者交付物" in contract
    assert "目标结果与核心矛盾 → 项目角色与关键能力 → 定位与价值承诺 → 部署样板工作流 → 空间运行边界 → 一期部署与学习闭环 → 复制与扩展决策门" in editorial
    assert "专项底稿各自成立，但正文没有说明" in _read(SKILL_ROOT / "references" / "quality-gates.md")


def test_missing_implementation_evidence_downgrades_claims_without_stopping_report() -> None:
    skill = _read(SKILL_ROOT / "SKILL.md")
    gates = _read(SKILL_ROOT / "references" / "quality-gates.md")

    assert "而不是正式报告的交付门槛" in skill
    assert "直接证据缺口只降低结论强度" in gates
    assert "不得把整章降为取证或试验设计" in gates


def test_market_research_exhausts_public_categories_before_parameterizing_gaps() -> None:
    market_skill = _read(MARKET_ROOT / "SKILL.md")
    workflow = _read(MARKET_ROOT / "references" / "research-workflow.md")

    for category in ("统计", "政策规划", "文保档案", "片区供给", "直接及区域竞品", "文化机构或机构采购", "公开价格与活动"):
        assert category in market_skill
    assert "原始查询 → 行政区与主题重组查询 → 机构或来源替代查询" in workflow
    assert "searched_no_usable_source" in workflow
    assert "不阻止完成候选比较" in workflow


def test_phase_one_budget_uses_public_benchmarks_without_claiming_a_quote() -> None:
    rules = _read(SKILL_ROOT / "references" / "decision-rulebook.md")
    gates = _read(SKILL_ROOT / "references" / "quality-gates.md")
    workflow = _read(MARKET_ROOT / "references" / "research-workflow.md")

    for source in ("公开采购/中标", "公开招聘薪酬", "供应商公开报价"):
        assert source in workflow
    assert "低位、基准和高位区间" in rules
    assert "不得写成项目已获报价、批准预算或最终合同金额" in rules
    assert "条件性启动预算包" in gates


def test_phase_one_is_a_visible_bundle_and_summary_leads_with_value() -> None:
    rules = _read(SKILL_ROOT / "references" / "decision-rulebook.md")
    editorial = _read(SKILL_ROOT / "references" / "publication-editorial.md")

    assert "服务界面、至少一个可讲述或可使用的内容单元、以及一个可运营的空间单元" in rules
    assert "价值路径的受益者、当前状态、期望改变和一期部署样板" in editorial
    assert "事实性空间身份" in rules


def test_single_value_path_prevents_a_risk_exclusion_report() -> None:
    path = _read(SKILL_ROOT / "references" / "value-path.md")
    contract = _read(SKILL_ROOT / "references" / "report-contract.md")
    rules = _read(SKILL_ROOT / "references" / "decision-rulebook.md")
    gates = _read(SKILL_ROOT / "references" / "quality-gates.md")
    editorial = _read(SKILL_ROOT / "references" / "publication-editorial.md")

    assert "唯一拥有" in path
    assert "不重复填写项目价值、取舍或资源流向" in contract
    assert "不另建取舍字段或风险叙事" in gates
    assert "一期部署样板" in editorial


def test_visual_contract_forbids_historical_asset_copy_and_requires_bundle_audit() -> None:
    workflow = _read(SKILL_ROOT / "references" / "report-visual-workflow.md")

    assert "不得复制到本轮报告" in workflow
    assert "history_id" in workflow and "report_id" in workflow and "run_id" in workflow
    assert "SHA-256" in workflow
    assert "validate_report_visuals.py" in workflow
    assert "每个 `report-visual` 块都有唯一 generated manifest 项" in workflow


def test_logic_chain_contract_rejects_research_outline_and_requires_phase_one_closure() -> None:
    skill = _read(SKILL_ROOT / "SKILL.md")
    rules = _read(SKILL_ROOT / "references" / "decision-rulebook.md")
    editorial = _read(SKILL_ROOT / "references" / "publication-editorial.md")
    gates = _read(SKILL_ROOT / "references" / "quality-gates.md")
    forward_tests = _read(SKILL_ROOT / "references" / "adaptive-forward-tests.md")

    assert "要回答的问题 -> 为谁创造什么价值 -> 证据与反证 -> 当前判断 -> 由此限定的下一步问题" in skill
    assert "上游判断" in rules and "六段方案推导链" in rules
    assert "伴生承接区、线路节点、专题参观或社区文化场所" in rules
    assert "目标使用者、核心体验或服务、空间与服务承接" in rules
    assert "不能按专业研究分类装配" in _read(SKILL_ROOT / "references" / "report-contract.md")
    assert "不得用共同限制、风险清单或研究过程替代项目故事和方案" in editorial
    assert "项目角色资格不足时仍保留" in gates
    assert "只有踏勘、取证或试点任务时，必须判为非完整一期闭环" in forward_tests
