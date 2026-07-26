# 自适应项目模型与报告深度

## 项目语义模型

主 Agent 读取原始材料后建立 `project_semantic_model`，并按 `report-contract.md` 的状态契约持久化到 `report/state/project-semantic-model.json`。它用于分析编排，不直接展示在报告中。

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

主 Agent 读完原始材料、项目范围、数据集目录和已有指标目录后，先建立 `problem_map` 并持久化到 `report/state/problem-map.json`。它是需要用户确认的研究入口，不是目录、结论或最终报告内容。每项至少记录：

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

问题地图整体状态为 `awaiting_confirmation | confirmed`。`awaiting_confirmation` 阶段完成项目理解和问题地图展示；用户确认后进入专项研究、专项结果明细、`decision_inventory` 与正式大纲。用户修订时更新并重新展示完整问题地图，再次等待确认。

复杂项目应检查定位选择、替代路径、利益或使用冲突、空间系统、运营承接能力和推翻条件；这些是发现遗漏的视角，不是固定六项模板。简单项目只保留会改变行动的问题。材料中的候选方向先作为待验证假设，当前判断由后续证据比较形成。

问题地图以自然 Markdown 展示：先列已确认的项目事实与对象关系，再列待确认问题及其研究价值，并据此组织研究视角、候选证据和反证来源。`decision_inventory` 收敛后形成正式章节标题。

## 决策逻辑图

问题地图确认后，主 Agent 按 `decision-rulebook.md` 建立 `decision_logic_map`，并持久化到 `report/state/decision-logic-map.json`。它先于决策清单，负责把事实、直接研究证据和必要的空间指标写成“条件到结论”的推理链；不是章节目录，也不把指标罗列为结论。

```yaml
status: ready
rules:
  - id: R1
    decision_question:
    when: []
    judgment:
    action:
    alternatives: []
    counterexample:
    evidence_refs: []
    metric_refs: []
    limitations: []
    validation:
    status: supported | conditional | excluded
```

每个 `metric_refs` 记录 result ID、tool ID、观察、比较基准、对行动的影响和不可证明事项。只有移除指标后会改变 `judgment`、`action` 或 `validation` 时，指标才进入逻辑图。`supported` 节点可在证据闭合后进入决策清单；`conditional` 和 `excluded` 节点保留候选、反例和改判路径，不升级为当前选择。

## 决策清单

波次 0 将 `decision_logic_map`、`decision_inventory` 与 `evidence_summary` 初始化为对象型空容器，以便 manifest 记录完整状态包。专项研究、候选比较、空间推演和运营能力分析完成后，先完成决策逻辑图，再在波次 4 写入决策条目和证据摘要，并持久化到 `report/state/decision-inventory.json` 与 `report/state/evidence-summary.json`；版本、快照和校验规则以 `report-contract.md` 为准。每项至少记录：

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
