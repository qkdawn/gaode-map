from __future__ import annotations

from typing import Dict, List

REASONING_RUBRIC_STEPS: List[Dict[str, str]] = [
    {
        "key": "Observation",
        "label": "数据现象",
        "instruction": "指标、记录或 EvidenceNode 本身能直接说明什么，不把数值立即翻译成结论。",
    },
    {
        "key": "Mechanism",
        "label": "形成机制",
        "instruction": "解释这种现象可能由什么空间、交通、人口、业态或运营机制形成。",
    },
    {
        "key": "Alternative",
        "label": "替代解释",
        "instruction": "列出至少一种同样可能的解释，避免单因果和模板化判断。",
    },
    {
        "key": "Evidence Quality",
        "label": "证据质量",
        "instruction": "说明当前证据强弱、口径、年份、样本范围和不能证明的部分。",
    },
    {
        "key": "Implication",
        "label": "商业含义",
        "instruction": "只把证据能支撑的部分转成商业、空间或策划判断，并标出需要补充验证的部分。",
    },
]

EVIDENCE_AWARE_REASONING_PROMPT = """
Evidence-Aware Reasoning Skill：
对复杂分析问题，必须先在内部按五步法处理每类关键证据，再生成最终回答：
1. Observation：数据本身说明什么。
2. Mechanism：为什么可能形成这种现象。
3. Alternative：还有哪些可能解释。
4. Evidence Quality：当前证据强弱、口径、年份和局限。
5. Implication：对商业、空间或策划判断意味着什么。
规则：
- 不要直接把指标翻译成结论，例如不要从“人口高”直接跳到“商业好”。
- 不要使用“潜力强、生态成熟、商业迭代、能级提升”等空泛词，除非工具证据已经给出可核查支撑。
- 所有结论必须说明证据边界，区分“已被数据支持的判断”和“需要补充验证的判断”。
- 对 POI、人口、夜光、路网、H3 分别检查 Alternative 和 Evidence Quality。
- 夜光可以支持夜间活跃 proxy，但不能单独证明夜经济消费强；人口可以支持服务需求基底，但不能单独证明消费力；路网可达性好可能是穿行，不等于停留；POI 多可能是供给丰富，也可能是同质化或饱和。
- 最终 answer 不必逐项暴露五步法标题，但必须体现替代解释、证据质量和谨慎结论。
""".strip()

FINAL_SYNTHESIS_REASONING_INSTRUCTIONS: List[str] = [
    "复杂问题先在内部按 Evidence-Aware Reasoning 五步法分析工具结果：Observation、Mechanism、Alternative、Evidence Quality、Implication。",
    "最终回答不必逐项展示五步法标题，但必须体现替代解释、证据质量和证据边界。",
    "不要把指标直接翻译成结论；只写证据能够支撑的判断，并把需要补充验证的判断明确标出。",
]


def reasoning_rubric_payload() -> Dict[str, object]:
    return {
        "skill": "evidence_aware_reasoning",
        "steps": REASONING_RUBRIC_STEPS,
        "rules": [
            "不要直接把指标翻译成结论",
            "不要使用空泛商业套话",
            "必须说明证据边界",
            "必须区分数据支持判断与待验证判断",
            "复杂问题必须检查替代解释和证据质量",
        ],
    }

