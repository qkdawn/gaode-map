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
    assert "资源与主题 → 区位、市场与竞争 → 客群与行为 → 定位路径比较 → 空间与产品 → 运营分期 → 产品市场再校核 → 实施验证门" in editorial
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


def test_visual_contract_forbids_historical_asset_copy_and_requires_bundle_audit() -> None:
    workflow = _read(SKILL_ROOT / "references" / "report-visual-workflow.md")

    assert "不得复制到本轮报告" in workflow
    assert "history_id" in workflow and "report_id" in workflow and "run_id" in workflow
    assert "SHA-256" in workflow
    assert "validate_report_visuals.py" in workflow
    assert "每个 `report-visual` 块都有唯一 generated manifest 项" in workflow
