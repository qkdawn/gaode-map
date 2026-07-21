from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict


class AgentSkillView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    description: str = ""
    color: str = ""
    executable: bool = False
    diagnostic: str = ""


def _skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    return yaml.safe_load(parts[1]) or {} if len(parts) == 3 else {}


def list_agent_skills() -> list[AgentSkillView]:
    result: list[AgentSkillView] = []
    root = _skills_root()
    if not root.exists():
        return result
    for skill_file in sorted(root.glob("*/SKILL.md")):
        try:
            meta = _frontmatter(skill_file)
            interface_file = skill_file.parent / "agents" / "openai.yaml"
            interface_doc = yaml.safe_load(interface_file.read_text(encoding="utf-8")) or {} if interface_file.exists() else {}
            interface = interface_doc.get("interface") if isinstance(interface_doc.get("interface"), dict) else {}
            skill_id = str(meta.get("name") or skill_file.parent.name).strip()
            result.append(AgentSkillView(
                id=skill_id,
                display_name=str(interface.get("display_name") or skill_id).strip(),
                description=str(interface.get("short_description") or meta.get("description") or "").strip(),
                color=str(interface.get("brand_color") or "").strip(),
                executable=False,
                diagnostic="Skill 尚未注册执行器",
            ))
        except (OSError, yaml.YAMLError, TypeError, ValueError):
            continue
    return result


def get_agent_skill(skill_id: str, *, require_executable: bool = True) -> AgentSkillView:
    normalized = str(skill_id or "").strip()
    skill = next((item for item in list_agent_skills() if item.id == normalized), None)
    if skill is None:
        raise ValueError(f"未知 Skill：{normalized}")
    if require_executable and not skill.executable:
        raise ValueError(f"Skill {normalized} 尚未注册执行器")
    return skill
