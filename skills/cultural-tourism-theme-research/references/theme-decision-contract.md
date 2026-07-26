# 主题判断图契约

主题研究除十二部分调研报告外，必须交付 `report/research/cultural-tourism-theme-decision-map.json`。它将资源、关系研究和主题裁决压缩为主分析可消费的条件结论；它不是项目定位、空间方案、业态清单或实施承诺。

```yaml
schema: cultural-tourism-theme-decision-map
project_identity: confirmed | context_only
status: ready | source_discovery_only
nodes:
  - id: T1
    decision_question: 哪个共同机制可以组织项目资源？
    when: []
    judgment: 候选主叙事或不形成单一主叙事的裁决
    action: 对后续定位比较产生的候选主题输入
    alternatives: []
    counterexample: 条件不成立时的替代主题或退出原因
    evidence_refs: []
    metric_refs: []
    limitations: []
    validation: 会确认、缩减或推翻主题判断的证据
    status: supported | conditional | excluded
```

节点必须覆盖：共同机制、至少一个被排除或缩减的替代主题、资源和关系证据、保护/社区/运营约束与明确验证动作。`metric_refs` 只在已保存空间指标会改变主题相关的空间关系判断时出现；每项记录 `result_id`、`tool_id`、`observation`、`comparison_basis`、`decision_effect` 与 `does_not_prove`。POI、路径、夜光或人口不证明历史真实性、文化认同、游客需求或主题适配。

`project_identity: context_only` 或 `status: source_discovery_only` 时，所有节点都只能作为范围背景的候选解释。主 `spatial-business-analyst` 只将 `supported` 或 `conditional` 节点的事实、共同机制、候选主题、反例、约束和验证条件写入其决策逻辑图；它仍自行裁决项目定位、产品、空间和运营。
