from pathlib import Path

import yaml

from modules.agent.skill_catalog import list_agent_skills


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "spatial-business-analyst"


def test_spatial_business_analyst_is_codex_skill_not_app_executor():
    skills = {skill.id: skill for skill in list_agent_skills()}

    assert {"spatial-project-data", "spatial-business-analyst", "spatial-unit-planning", "spatial-client-presentation"}.issubset(skills)
    assert skills["spatial-business-analyst"].executable is False
    assert skills["spatial-business-analyst"].diagnostic == "Skill 尚未注册执行器"
    assert all(not skills[skill_id].executable for skill_id in {"spatial-project-data", "spatial-unit-planning", "spatial-client-presentation"})


def test_spatial_business_skill_focuses_on_codex_workflow_and_reader_report():
    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for phrase in (
        "Codex 原生 Subagent",
        "工作定位",
        "定位与产品策略师",
        "空间功能策划师",
        "运营与分期策略师",
        "自然 Markdown",
        "list_spatial_metric_results",
        "视觉证据编辑 Subagent",
        "report-visual-workflow.md",
        "直接保存 Markdown",
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
        "spatial-unit-programming.md",
        "specialist-roles.md",
        "report-orchestration.md",
        "report-example.md",
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
