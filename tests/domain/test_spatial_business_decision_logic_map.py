from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "spatial-business-analyst"
    / "scripts"
    / "render_decision_logic_map.py"
)
SPEC = importlib.util.spec_from_file_location("render_decision_logic_map", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_renders_rule_chain_with_metric_boundary(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    logic_map = {
        "state_id": "decision_logic_map",
        "payload": {
            "status": "ready",
            "value_path": {
                "desired_outcome": "形成可验证的夜间公共文化服务。",
                "deployable_workflow": {"service": "小容量夜间文化活动"},
            },
            "rules": [
                {
                    "id": "R7",
                    "decision_question": "夜间内容是否进入首期开业？",
                    "when": ["日间到访可留存且安全空间可运营。"],
                    "judgment": "先测试夜间内容。",
                    "action": "设置小容量夜间活动。",
                    "alternatives": ["直接建设大型夜游工程"],
                    "counterexample": "缺少交通与餐饮承接时暂不进入。",
                    "limitations": ["夜光不证明夜间消费。"],
                    "validation": "以到场、停留和支付记录决定扩容。",
                    "status": "conditional",
                    "metric_refs": [
                        {
                            "result_id": "result:night:1",
                            "tool_id": "nightlight.sector_profile",
                            "observation": "南侧夜光弱于项目周边。",
                            "comparison_basis": "同一方向距离带。",
                            "decision_effect": "优先核验南侧夜间界面。",
                            "does_not_prove": "夜间消费。",
                        }
                    ],
                }
            ],
        },
    }
    (state_dir / "decision-logic-map.json").write_text(json.dumps(logic_map, ensure_ascii=False), encoding="utf-8")

    output = MODULE.render(tmp_path)

    svg = output.read_text(encoding="utf-8")
    assert output.name == "decision-logic-map.svg"
    assert "R7" in svg
    assert "nightlight.sector_profile" in svg
    assert "夜光不证明夜间消费" in svg
    assert "结论与动作" in svg
    assert "验证与边界" in svg
    assert "形成可验证的夜间公共文化服务" in svg
    assert "小容量夜间文化活动" in svg
