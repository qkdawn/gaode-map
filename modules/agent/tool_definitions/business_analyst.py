from __future__ import annotations

from typing import Dict

from .common import RegisteredTool, _register, _tool_spec
from ..tool_adapters.business_analyst_tools import plan_business_analyst_analysis_tool


def register_business_analyst_tools(registry: Dict[str, RegisteredTool]) -> None:
    registry["plan_business_analyst_analysis"] = _register(
        _tool_spec(
            name="plan_business_analyst_analysis",
            description=(
                "为商业诊断、开放式业态机会、选址、竞品或客群问题生成 Business Analyst 分析骨架。"
                "返回模型路径、证据需求、可跳过分支和 guardrails；这是推理导航，不是报告模板。"
            ),
            category="information",
            layer="L2",
            ui_tier="capability",
            data_domain="commerce",
            capability_type="interpret",
            scene_type="facility_gap",
            llm_exposure="primary",
            evidence_contract=["business_analyst_skeleton"],
            applicable_scenarios=["区域商业诊断", "开放式业态机会筛选", "单业态选址预筛", "竞品影响判断", "客群适配判断"],
            cautions=[
                "只提供分析骨架，不直接生成最终报告。",
                "不得把 proxy 证据外推为真实客流、营收、消费力、市场份额或客户画像。",
                "只有用户明确要求 BA 报告或 scorecard 时，最终回答才展示报告式表格。",
            ],
            produces=["business_analyst_skeleton"],
            input_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "area_diagnosis", "opportunity_screening", "site_selection", "competition", "customer_fit"],
                    },
                    "question_type": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "selected_skill": {"type": "object"},
                    "candidate_skills": {"type": "array"},
                    "recommended_path": {"type": "array"},
                    "optional_branches": {"type": "object"},
                    "model_tool_map": {"type": "object"},
                    "skip_conditions": {"type": "object"},
                    "guardrails": {"type": "array"},
                    "missing_evidence_defaults": {"type": "array"},
                    "answer_guidance": {"type": "array"},
                },
                "additionalProperties": True,
            },
            readonly=True,
            cost_level="safe",
            risk_level="safe",
            cacheable=True,
        ),
        plan_business_analyst_analysis_tool,
    )
