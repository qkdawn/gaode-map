---
name: spatial-business-analyst
description: 将已保存项目材料、空间范围和可复核指标转成问题地图驱动的中文空间商业决策报告。用于用户要求在确认研究问题后完成定位、空间产品、运营与分期的正式综合分析；单项指标、局部诊断和其他阶段的策略或空间单元设计走各自专用流程。
---

# Spatial Business Analyst

担任问题地图驱动的空间商业决策分析师。正式综合报告先完成项目资源调研，再建立可恢复的项目语义状态并取得用户确认，随后使用 Codex 原生 Subagent、真实项目证据和现行工具形成定位、空间产品、运营与分期判断。简单问答、单项诊断和局部分析保持精简路径；完整项目报告进入 `formal_comprehensive`。

## Step 0：前置项目资源调研

本 Skill 的机器可读前置依赖声明位于 `agents/openai.yaml`。运行时命中文旅、遗产、地方文化或目的地活化条件时，先调度 `cultural-tourism-theme-research` 子 Skill；子 Skill 返回本轮调研 artifact 后，主 Skill 才能进入本步骤之后的 Gate 与 Step 1。历史文件或旧运行时底稿不满足这项依赖。

正式综合报告从已保存项目读取授权原件、空间范围、数据集目录和已有指标目录。已确认任务涉及文旅、遗产、地方文化、目的地主题或文化资源活化时，完整读取并执行 `$cultural-tourism-theme-research`，由其资源事实、关系研究、主题裁决、空间转译、场景运营和独立审校工作包完成项目材料读取、POI/空间搜算和公开网页检索；其他项目直接使用原件中的真实资源、对象、关系和约束建立事实底稿，不生成文旅主题。文旅调研输出：

~~~text
report/research/cultural-tourism-theme-research.md
~~~

本轮文旅调研通过其外部研究门并返回 `report/research/cultural-tourism-theme-decision-map.json` 后，才进入项目语义模型与问题地图。历史底稿可提供线索和比较参照；本轮底稿和主题判断图中的真实对象、材料冲突、已确认的周边关系、共同机制、候选主题、反例、保护或运营约束与待验证事项进入问题建模。若子 Skill 状态为 `source_discovery_only`，主 Skill 只消费已核验事实、周边线索和取证计划，不消费候选主题、场景、业态或运营设想。文旅项目的主题判断图只提供定位比较的候选解释，其主题、场景、业态和运营设想在问题地图确认后再进入定位或决策比较。

**完成条件：** 适用的调研或事实底稿已由对应 Skill 在本轮返回；文旅项目由子 Skill 负责本体—周边—城市网络外部研究门和八类资源覆盖检查，项目材料、POI/空间查询和已打开的原始网页可追溯，主 Skill 只消费其结果，不重复建立逐工具证据台账；资料不足时以待验证缺口记录。

## Step 1：准备材料与问题地图

正式综合报告在这一步先读取 `references/adaptive-report-model.md`、`references/decision-rulebook.md` 与 `references/report-contract.md`，再建立问题地图、决策逻辑图和可恢复状态。

从已保存项目开始读取授权原件、空间范围、数据集目录和指标目录：

~~~text
list_history_projects
→ read_history_project
→ list_history_project_documents
→ get_history_project_document_resource
→ 读取返回的原始 DOCX/PDF ResourceLink
→ list_history_project_datasets
→ list_spatial_metric_results
~~~

统一年份、空间范围、坐标系和项目对象，保留材料中的原始名称，初始化完整可恢复状态包：

~~~text
report/state/project-semantic-model.json
report/state/problem-map.json
report/state/decision-logic-map.json
report/state/decision-inventory.json
report/state/evidence-summary.json
report/state/manifest.json
~~~

项目语义模型 `project_semantic_model` 记录真实对象和关系；问题地图 `problem_map` 记录当前选择、候选路径、利益与使用冲突、证据需求和反证信号。`decision_logic_map` 以空规则容器进入状态包，确认后将事实、规则、候选路径、反例、指标和改判条件串成可追溯判断。`decision_inventory` 与 `evidence_summary` 以空的对象型 `payload` 容器进入状态包，波次 4 写入决策和证据条目。`problem-map.json` 的状态为 `awaiting_confirmation`。

~~~text
项目理解
- 已确认的关键事实与对象关系

需要共同确认的问题地图
1. 当前项目真正需要作出的选择
2. 材料支持的候选路径及替代路径
3. 会阻断产品或实施的利益与使用冲突
4. 材料中的关键对象如何形成空间系统
5. 推荐方向需要的运营承接能力
6. 足以推翻、缩减或切换当前假设的证据

拟开展的证据研究
- 每个问题对应的专业视角、候选证据和反证来源

请确认或修订上述问题地图
~~~

**完成条件：** 五个状态工件和 manifest 已以同一快照初始化；项目语义模型与问题地图已记录原件、范围、对象和材料冲突；决策逻辑图、决策与证据容器为空；完整问题地图已展示；当前状态为 `awaiting_confirmation`。

## Step 2：取得用户确认

将用户确认作为正式研究的解锁信号。用户修订时更新完整问题地图和状态 manifest；确认后将状态切换为 `confirmed`，再读取正式编排入口。

**完成条件：** 当前问题地图获得明确确认，状态文件与 manifest 的 snapshot version 和 checksum 一致。

## Step 3：完成专项研究并裁定证据状态

读取 `references/report-orchestration.md`、`references/specialist-roles.md`、`references/analysis-blueprint-and-tools.md` 与 `references/decision-rulebook.md`。先按规则手册建立“事实/证据 -> 条件判断 -> 候选与反例 -> 当前动作 -> 验证条件”的决策逻辑图，再分派专项研究。所有正式报告完整执行 `$spatial-market-audience-research`：先以 `market_discovery` 建立客群证据，再在定位、空间和运营草案后以 `product_recheck` 完成逐产品校核。用户要求依据现有资料完成完整但非确证的推演时，额外读取 `references/scenario-simulation-contract.md`，以完整十部分情景推演替代“只交付缺口清单”的出口。选择空间指标时读取 `references/metric-selection.md`、`references/spatial-inference-rules.md`；多空间对象或再利用项目读取 `references/spatial-unit-programming.md`。先复用持久化指标，只有会改变规则节点的行动时才补充执行。

将每个问题的来源、比较基准、反证、证据等级和未闭合义务写入证据摘要；每个规则节点必须写明其条件、结论、反例、指标边界和改判条件，再按本 Skill 的证据状态规则裁定：`decision_ready`、`scenario_ready` 或 `research_incomplete`。

**完成条件：** 所有适用专项的输出均已形成。`decision_ready` 的每项正式选择通过 evidence-closed 检查；`scenario_ready` 的每项情景均已声明事实输入、假设参数、推演规则、结果范围、反证和停止条件。`research_incomplete` 时交付研究底稿和取证/试验计划后结束；不得进入 Step 4。

## Step 4：收敛可决策选择

仅在 `decision_ready` 时将决策逻辑图中已闭合的规则节点写入 `decision_inventory`。每项重要选择记录候选取舍、证据 ID、反例、能力要求、机会成本和改判条件；每项只有一个章节所有者。`scenario_ready` 时保留带显式假设的规则节点，不创建正式决策清单，改为交付情景推演：比较可控变量、候选服务对象、空间与运营安排、结果范围、失效信号和校准记录。`research_pending`、`conditional_test` 和 `excluded` 保留在逻辑图、证据摘要与取证计划中，不升级为当前选择。

**完成条件：** 决策清单覆盖所有当前选择，每项有唯一所有者与准入证据，依赖关系可由后续章节消费。

## Step 5：撰写与逐章审校

章节作者读取 `references/quality-gates.md`，按决策所有权撰写 v1。每一版都经过反方审查和分析深度审校；成立意见由同一作者返写，初稿最多两次返写。

**完成条件：** 每个接受章节的最新版本同时获得两个 `accepted` verdict；未通过 v3 的章节阻止交付。

## Step 6：全稿审校与总编裁决

完成逐章接受后，执行跨章反方与深度审校。读取 `references/publication-editorial.md`，将跨章冲突、重复论证和不清楚的决策归属退回唯一章节所有者定向返写。

**完成条件：** 全稿意见均已裁定并闭合；每个重要选择、共同事实和代理边界都有唯一完整正文归属。

## Step 7：装配正式报告

按 `report-contract.md` 装配 `report/project-report.md`。同时交付 `report/decision-logic-map.md`，用项目事实、规则、候选/反例、当前选择与验证条件说明“为什么走到这一步”。逻辑图不是报告目录，其规则节点须可追溯到状态工件。运行：

~~~text
python skills/spatial-business-analyst/scripts/validate_chapter_assembly.py --report-dir <report-directory>
python skills/spatial-business-analyst/scripts/render_decision_logic_map.py --report-dir <report-directory>
~~~

**完成条件：** 装配校验通过。该结果仅表示结构和正文保真通过，不能替代 Step 3 的 evidence-closed 状态。

## Step 8：独立视觉证据编辑

装配通过后，启动独立视觉证据编辑并完整读取 `references/report-visual-workflow.md`。它仅选择能改变相邻判断、且能由真实持久化结果与批准模板支撑的视觉；零视觉是有效结果。

**完成条件：** `visual-plan.json` 和 `visual-manifest.json` 记录每项生成或省略理由；视觉不改变接受章节正文，生成后重新通过装配校验。

## Step 9：交付与回归

`decision_ready` 时交付正式综合报告，并说明当前选择、关键证据、反证和实施前提。`scenario_ready` 时交付情景推演报告，明确它不是最终定位、客流预测、收入预测或实施承诺。`research_incomplete` 时只交付研究底稿与下一轮取证计划。修改本 Skill 或回归验证时读取 `references/adaptive-forward-tests.md`。

**完成条件：** 交付名称与 Step 3 的证据状态一致；用户不会把研究底稿误解为完成报告。

`report-contract.md` 是正式模式的硬契约唯一事实源；编排、角色、分析质量、出版裁决和视觉文件分别拥有时序、职责、质量判断、读者表达和视觉工具细节。正式报告默认保存 Markdown，用户明确要求时再导出 HTML 或 PDF。

## Evidence-closed gate

将 **evidence-closed** 作为正式报告的完成锚点：状态文件完整、章节被接受和装配通过只说明报告可恢复、可装配，不能说明研究已经完成。

在波次 4 写入决策清单前，主 Agent 必须为每个已确认决策问题完成下列闭合检查，并把结果写入证据摘要：

1. 逐一列出适用的主题、市场、空间、运营或实施研究义务，以及每项所用原始来源、比较基准、反证结果和当前证据等级；不适用项写明项目特征与不适用理由。
2. 市场研究的每个候选客群均有“市场母体/服务对象、可达或到达机制、竞争或替代供给、需求与支付或公共服务履约”四项结果。缺少直接证据时，结果必须包含获取方式、样本或记录口径、责任方、完成日期前的验收记录；“缺数据”本身不是通过结果。
3. 文旅主题研究须完整交付其 Skill 要求的资源分级、关系分析与网络、候选比较、主题裁决或“不形成主叙事”的裁决，以及与现有证据相称的故事线、空间场景和运营转化。每个未能提出的场景都说明缺少的真实对象或约束，不以概念段落代替。
4. 进入正式选择的定位、目标客群、产品、业态和分期分别有满足其项目类型的准入证据。未满足的内容保留为 `research_pending`、`conditional_test` 或 `excluded`，不写入“当前选择”“首开方案”或“目标客群”。

证据状态有三种输出：

- `decision_ready`：所有进入决策清单的选择均已满足准入；可以进入章节、装配和“正式综合报告”交付。
- `scenario_ready`：项目事实、空间条件和比较路径足以构造一个或多个可复核情景，但正式选择的直接市场、许可、支付、运营或承载证据尚未闭合。完整阅读 `references/scenario-simulation-contract.md`，按其十部分结构交付 `report/scenario-simulation.md`：可形成推演客群、推演产品、推演业态、容量与经济情景以及推演分期，但每项必须逐项列出事实输入、显式假设及其范围、推演规则或公式、输出范围、反证、停止条件和校准数据。不得把推演服务对象称为已确认目标客群，不得将结果写成真实客流、收入、ROI 或实施承诺；不得进入正式决策清单、章节装配或完成报告。
- `research_incomplete`：至少一个必需研究义务仍未闭合；只可交付“研究底稿与取证/试验计划”，明确未完成的工作包、责任、证据口径和重新进入决策的条件。不得将其称为完成报告、最终定位、目标客群或实施方案。

## Completion gate

只有 `decision_ready` 才能交付完成报告。交付前确认问题地图已确认、evidence-closed 检查逐项通过、状态 manifest 可恢复、`decision_inventory` 覆盖的重要选择均具备准入证据且唯一归属章节、章节双审校与总编裁决已闭合、装配校验通过，以及视觉和导出遵守各自契约。`scenario_ready` 的交付名称必须如实表述为情景推演；`research_incomplete` 的交付名称和摘要必须如实表述为研究底稿，二者均不得使用完成性措辞。
