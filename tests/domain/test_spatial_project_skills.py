from modules.agent.skill_catalog import list_agent_skills


def test_spatial_project_skills_are_discoverable_but_not_misrepresented_as_internal_executors():
    skills = {skill.id: skill for skill in list_agent_skills()}

    assert {"spatial-project-data", "spatial-business-analyst", "spatial-unit-planning", "spatial-client-presentation"}.issubset(skills)
    assert all(not skills[skill_id].executable for skill_id in {"spatial-project-data", "spatial-business-analyst", "spatial-unit-planning", "spatial-client-presentation"})
