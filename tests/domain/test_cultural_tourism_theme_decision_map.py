from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "cultural-tourism-theme-research"
    / "scripts"
    / "validate_theme_decision_map.py"
)
SPEC = importlib.util.spec_from_file_location("validate_theme_decision_map", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _node() -> dict[str, object]:
    return {
        "id": "T1",
        "decision_question": "哪个共同机制可以组织资源？",
        "when": ["桥、港、街镇形成可追溯的贸易与聚居关系。"],
        "judgment": "以商港文化作为候选主叙事。",
        "action": "供主分析比较主题与空间承接路径。",
        "alternatives": ["资源名称并列"],
        "counterexample": "缺少真实关系时改为专题叙事。",
        "evidence_refs": ["source:heritage:1"],
        "limitations": ["POI 不能证明历史真实性。"],
        "validation": "以文保档案与地方志核验关系链。",
        "status": "conditional",
        "metric_refs": [],
    }


def test_accepts_theme_judgment_with_boundary():
    payload = {
        "schema": "cultural-tourism-theme-decision-map",
        "project_identity": "confirmed",
        "status": "ready",
        "nodes": [_node()],
    }

    assert MODULE.validate(payload) == []


def test_rejects_metric_without_inference_boundary():
    node = _node()
    node["metric_refs"] = [{"result_id": "result:1", "tool_id": "poi.supply_structure"}]
    payload = {
        "schema": "cultural-tourism-theme-decision-map",
        "project_identity": "confirmed",
        "status": "ready",
        "nodes": [node],
    }

    assert "metric reference lacks provenance, effect or inference boundary" in MODULE.validate(payload)
