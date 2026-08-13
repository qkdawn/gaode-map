from pathlib import Path

import yaml

from modules.agent.skill_catalog import list_agent_skills
from modules.agent.capability_catalog import get_analysis_capability


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "spatial-business-analyst"
RESEARCH_SKILL_ROOT = ROOT / "skills" / "cultural-tourism-theme-research"
MARKET_SKILL_ROOT = ROOT / "skills" / "spatial-market-audience-research"


def test_spatial_business_analyst_registers_dependency_executor():
    skills = {skill.id: skill for skill in list_agent_skills()}

    assert "spatial-business-analyst" in skills
    assert skills["spatial-business-analyst"].executable is True
    assert skills["spatial-business-analyst"].dependencies[0].skill_id == "cultural-tourism-theme-research"
    assert "spatial-market-audience-research" in skills
    assert skills["spatial-market-audience-research"].executable is True
    assert skills["spatial-market-audience-research"].diagnostic == ""
    assert skills["spatial-business-analyst"].dependencies[1].skill_id == "spatial-market-audience-research"
    assert skills["spatial-business-analyst"].dependencies[1].stage == "market_discovery"
    assert [stage.stage for stage in skills["spatial-business-analyst"].workflow_stages] == [
        "preflight",
        "market_discovery",
        "decision_evidence",
        "product_recheck",
        "visual_editorial",
    ]


def test_client_decision_spatial_strategy_is_owned_by_n8n_service():
    skills = {skill.id: skill for skill in list_agent_skills()}
    capability = get_analysis_capability("client-decision-spatial-strategy")

    assert "client-decision-spatial-strategy" not in skills
    assert capability.executor_type == "service"
    assert capability.executor_id == "n8n-spatial-strategy"
    assert capability.display_name == "自适应空间决策分析"
    assert capability.estimated_stages == 1


def test_spatial_business_skill_focuses_on_codex_workflow_and_reader_report():
    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for phrase in (
        "Codex 原生 Subagent",
        "定位、空间产品、运营与分期",
        "始终交付 `report/project-report.md`",
        "list_spatial_metric_results",
        "report/state/manifest.json",
        "report-visual-workflow.md",
        "正式报告默认保存 Markdown",
    ):
        assert phrase in skill_text

    for implementation_detail in (
        "V3",
        "ChapterDeliveryPackage",
        "ChapterAssignment",
        "EditorialReview",
        "publish_spatial_business_run",
        "analysis-plan.json",
        "ReportAssembly",
        "source-index.json",
        "artifact 白名单",
        "审计台账",
    ):
        assert implementation_detail not in skill_text

    for reference in (
        "analysis-blueprint-and-tools.md",
        "quality-gates.md",
        "report-contract.md",
        "publication-editorial.md",
        "spatial-unit-programming.md",
        "specialist-roles.md",
        "report-orchestration.md",
        "report-visual-workflow.md",
    ):
        assert (SKILL_ROOT / "references" / reference).is_file()
        assert reference in skill_text


def test_spatial_business_skill_agent_metadata_is_standard_and_invokes_skill():
    metadata = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]
    assert interface["display_name"] == "Spatial Business Analyst"
    assert 25 <= len(interface["short_description"]) <= 80
    assert "$spatial-business-analyst" in interface["default_prompt"]


def test_cultural_tourism_theme_research_skill_has_standard_metadata_and_workflow():
    skill_text = (RESEARCH_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    metadata = yaml.safe_load((RESEARCH_SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]

    assert "cultural-tourism-theme-research" in skill_text
    assert "references/research-workflow.md" in skill_text
    assert "report/research/cultural-tourism-theme-research.md" in skill_text
    assert "query_history_project_dataset" in skill_text
    assert "aggregate_history_project_dataset" in skill_text
    assert "poi.supply_structure" in skill_text
    assert "poi.focused_accessibility" in skill_text
    assert "## 执行步骤" in skill_text
    assert "八类资源" in skill_text
    assert "项目材料资源表必须先行建立" in skill_text
    assert "历史调研底稿可用于发现线索和比较变化" in skill_text
    assert interface["display_name"] == "文旅主题调研"
    assert 25 <= len(interface["short_description"]) <= 80
    assert "$cultural-tourism-theme-research" in interface["default_prompt"]


def test_spatial_market_audience_research_skill_has_standard_metadata_and_two_stage_outputs():
    skill_text = (MARKET_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    workflow = (MARKET_SKILL_ROOT / "references" / "research-workflow.md").read_text(encoding="utf-8")
    workpacks = (MARKET_SKILL_ROOT / "references" / "specialist-workpacks.md").read_text(encoding="utf-8")
    metadata = yaml.safe_load((MARKET_SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]

    assert "market_discovery" in skill_text
    assert "product_recheck" in skill_text
    assert "report/research/spatial-market-audience-research.md" in skill_text
    assert "report/research/spatial-product-market-recheck.md" in skill_text
    assert "项目条件" in workflow
    assert "候选客群假设" in workflow
    assert "市场母体、客源圈与流向" in workflow
    assert "产品市场再校核" in workflow
    assert "目标客群与行为综合师" in workpacks
    assert "产品市场再校核分析师" in workpacks
    assert interface["display_name"] == "空间市场与客群研究"
    assert 25 <= len(interface["short_description"]) <= 80
    assert "$spatial-market-audience-research" in interface["default_prompt"]
