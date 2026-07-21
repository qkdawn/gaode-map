# 自适应项目模型与报告深度

## 项目语义模型

主 Agent 读取原始材料后建立内部 `project_semantic_model`。它只用于分析编排，不直接展示在报告中。

```yaml
objects:
  - source_name: 材料中的原始名称
    semantic_roles: [spatial_unit, built_asset]
    attributes: {}
    relationships: []
    evidence_refs: []
    confidence: explicit | inferred | unknown
```

可复用角色包括：`spatial_unit`、`built_asset`、`heritage_asset`、`residential_component`、`public_anchor`、`open_space`、`circulation_component`、`service_component`、`operations_component`、`ecological_component`、`phasing_target`。

角色由材料事实、对象关系和空间功能推断，不能由特定名称或关键词机械触发。正文保留 `source_name`；语义角色只用于检查遗漏、分派专家和组织比较。

## 问题地图

主 Agent 读完原始材料、项目范围、数据集目录和已有指标目录后，先建立 `problem_map`。它是需要用户确认的研究入口，不是目录、结论或最终报告内容。每项至少记录：

```yaml
id:
question:
why_decisive:
candidate_hypotheses: []
evidence_needed: []
disconfirming_evidence: []
dependencies: []
status: open | confirmed | removed
```

问题地图整体状态为 `awaiting_confirmation | confirmed`。用户确认前不得启动专项研究、读取专项结果明细、形成 `decision_inventory` 或生成正式大纲。用户修订时更新并重新展示完整问题地图，再次等待确认。

复杂项目应检查定位选择、替代路径、利益或使用冲突、空间系统、运营承接能力和推翻条件；这些是发现遗漏的视角，不是固定六项模板。简单项目只保留会改变行动的问题。文化生活及其他材料偏好只作为候选假设，不能预填为当前判断。

问题地图以自然 Markdown 展示：先列已确认的项目事实与对象关系，再列待确认问题及其研究价值，最后列每个问题需要的专业视角、候选证据和反证来源。不得把问题改写成“人口分析、POI 分析、路网分析”等数据任务，也不得出现正式章节标题。

## 决策清单

专项研究、候选比较、空间推演和运营能力分析完成后，主 Agent 才建立内部 `decision_inventory`。每项至少记录：

```yaml
id:
question:
stakeholders: []
evidence_refs: []
disconfirming_evidence_refs: []
alternatives: []
current_judgment:
action:
validation:
change_trigger:
status: closed | conditional
```

清单覆盖问题地图中实际得到研究的定位、使用者、供给与竞争、空间关系、可达性、利益冲突、内容产品、运营方式、实施顺序、经济或组织条件。尚未解决且会改变行动的问题不能伪装成关闭状态：继续研究，或形成带明确改判条件的条件性判断。只有完成这一步后才能生成正式大纲。

## 自适应深度

报告深度由对项目关键问题的解释力决定。对象数量及关系、需要裁决的利益冲突、备选路径数量、空间层级、运营阶段和证据组合用于发现需要深入分析的问题，不用于换算页数、字数、图数、字段数量或固定档位。

对每项重要决策，主 Agent 根据项目实际追问：证据通过什么机制支持判断；推荐为何优于真实候选方向；哪些反例、约束或条件会使其失效；各方案造成什么机会成本和后续限制；现有组织与运营能力能否承接；选择形成什么路径依赖以及如何改向、缩减、暂停或退出。不是每个简单问题都要机械回答全部问题，但凡答案会改变行动，就必须进入分析。

“判断 → 证据 → 方案 → 动作 → 验证”只描述推理关系，不是可机械填充的 schema。若替换项目名称后大部分结论仍成立，或分析没有产生新的机制、矛盾和行动优先级，说明关键决策仍未深入。主 Agent 应继续读取适用证据、请求内部专家意见或扩写对应分析，不通过重复背景、免责声明和新增字段增加虚假深度。简单项目可以合并章节，复杂项目可以展开到对象、组团、阶段和实施条件。

## 边界表达

正文直接表达当前判断和动作，不设免责声明、局限性或“建议进一步研究”章节。会改变行动的未知事项写成一次性的前置条件、验证动作或停止条件。数据年份、范围、证据等级和不能支持的事项进入图注、脚注或证据审计附录。

## 视觉选择

独立视觉 Subagent 从已闭合的决策中选择能改变相邻判断的证据表达，候选包括对象关系、供给/竞争、密度/可达性、路网/方向、功能承载、方案比较、首开系统、分期路线和运营验证。正式报告每次评估但允许零图；没有真实指标、批准模板或准确位置时记录省略，不制作占位或装饰图。具体工作流遵守 `report-visual-workflow.md`。
