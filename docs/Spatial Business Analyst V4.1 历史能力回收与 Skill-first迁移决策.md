# Spatial Business Analyst V4.1：历史能力回收与 Skill-first 迁移决策

> **状态：方向已确认，能力盘点与迁移待实施**
>
> **决策日期：2026-07-17**
>
> **适用范围：** `spatial-business-analyst` 历史版本中的分析智能、专业角色能力、工具使用方式、协作语义和报告表达能力如何迁入当前 Skill-first 架构。
>
> **与既有文档的关系：** 《Spatial Business Analyst V4.1 Skill-first方向调整决策》继续决定 Agent 运行方式；《Spatial Business Analyst V4.1 分析智能、指标知识与数据健康改造草案》继续提供业务理解、指标知识和数据健康目标；本文负责识别在架构收敛过程中遗漏的有效能力，并决定其在新架构中的正确归属。三者发生解释冲突时，不恢复 Python LLM 运行时，但应优先保留可验证的分析智能和专业工作方法。

## 1. 决策摘要

Spatial Business Analyst 从 Python 内部 LLM 编排转向 Codex Skill-first 的方向正确，但当前迁移并不完整。既有方向文档所称的“核心收敛已完成”，是指重复运行时已完成收敛；不代表历史分析智能、专业能力和报告方法已经全部迁移完成。

过去版本中的 Provider、Prompt phase、Python DAG 调度器、编辑循环、蓝图锁、证据快照和审计台账属于运行时与治理实现，不应恢复；但这些实现中承载的专业角色知识、指标组合方法、工具选择逻辑、上下文投影、依赖释放、定向退修、空间单元策划、经营验证和面向客户的表达能力不能随旧运行时一起丢失。

本次决策采用以下原则：

> **回收历史版本中的分析智能，不恢复历史版本的 Agent 运行时。**

目标链路收敛为：

```text
Codex 主 Agent 理解项目、盘点空间单元并提出决策问题
→ 主 Agent 规划专业任务、依赖和工具授权
→ 专业 Subagent 在授权范围内读取证据并按需调用工具
→ Subagent 直接产出可进入报告的普通语言专业内容
→ 主 Agent 验收证据、比较基准、空间覆盖、行动推导和可读性
→ 不合格内容退回原 Subagent 定向修改一次
→ 主 Agent 只基于 accepted 内容完成去重、排序、衔接和项目级综合
→ Python 校验引用与契约，确定性编译一份普通读者报告
→ 保存不可变 V4.1 run
```

最终只有一份面向业主、管理者和普通决策者的公开报告。专业 Agent 的交付同样应当人可读、可直接进入报告；结构化字段只用于保证完整性、追溯和验收，不应把最终报告变成机器记录或审计台账。

## 2. 为什么需要能力回收

### 2.1 架构迁移误伤了分析智能

旧版本把运行时机制和分析知识混在同一批 Python 模型、Prompt、测试和报告模板中。删除重复的 LLM 运行时是必要的，但如果只按文件和类删除，就可能同时丢失：

- 专业角色何时需要补做分析；
- 指标应该怎样组合，而不是逐项罗列；
- 多指标互相支持或冲突时怎样解释机制；
- 上下游章节之间真正需要传递什么；
- 哪些结论必须退回原专业作者；
- 如何把空间代理转成选址、布局、功能、投运和验证行动；
- 如何检查项目内部所有空间单元是否被处理；
- 如何把专业结果表达成普通读者能理解的项目方案。

这些不是旧运行时的附属品，而是 Spatial Business Analyst 的产品能力。

### 2.2 当前 Subagent 容易退化为文字代写者

当前 Skill 已规定主 Agent 准备真实证据并向 Subagent 投影授权材料，但尚未完整规定 Subagent 的工具权限和自主分析边界。如果所有指标选择、执行和比较均由主 Agent 完成，Subagent 只负责根据现成结果写文字，那么专业角色并未真正承担分析责任。

专业 Subagent 应能够在任务边界内：

- 判断现有证据是否足够；
- 读取本角色需要的指标知识卡；
- 调用被明确授权的指标或数据工具；
- 进行同口径比较；
- 解释空间机制；
- 形成可直接进入报告的专业内容。

### 2.3 结构化交付被误解成机器化输出

`ChapterDeliveryPackage` 的目的应是让专业交付可验收，而不是要求 Subagent 输出普通读者难以理解的机器对象。

Codex 原生协作中的理想交付是“结构化、普通语言、可追溯的报告模块”：

- 正文首先回答项目问题；
- 表格直接说明空间怎么用、服务谁、为什么、有什么前提；
- finding、evidence ID、比较口径和限制作为紧凑追溯信息保留；
- accepted 内容能够直接进入最终报告；
- 主 Agent 不需要重新代写或翻译专业结论。

### 2.4 报告编译过度暴露内部工作结构

如果编译器把 finding、证据链接、行动、限制和验证字段逐项展开成长表，报告虽然可追溯，却更像 Agent 工作底稿。最终报告必须先回答：

1. 这个项目整体应该怎么做；
2. 每栋建筑、庭院、路径和花园分别做什么；
3. 为什么这样安排；
4. 先做什么、后做什么；
5. 哪些建议有条件；
6. 如何验证，何时继续或停止。

专业指标、参数和证据说明应放在判断之后，而不是占据报告入口。

## 3. 目标协作模型

### 3.1 主 Agent 的前期责任

主 Agent 负责项目级理解和协作规划，不替代所有专业角色完成分析。

主 Agent 必须：

- 读取用户问题、真实项目材料、空间范围和已有结果；
- 判断 `b2c`、`b2b` 或 `mixed`，识别付款方、使用者、需求单位和履约方式；
- 明确当前需要推动的选址、布局、空间功能、服务范围、店型、容量、产品、渠道或投运决策；
- 建立完整空间单元清单，区分系统层、组团层和单元层；
- 识别建筑、庭院、道路、花园、围墙、门禁、居民和后勤接口；
- 提出待验证假设；
- 规划 3–6 个具有专业判断责任的任务；
- 为任务设置 `context`、`finding`、`decision` 依赖；
- 为每个任务提供角色专属材料、结果和工具授权；
- 组织并行波次、验收、一次定向退修和最终综合。

### 3.2 专业 Subagent 的责任

专业 Subagent 不是自由写作者，也不是只负责润色现成结论的文案角色。每个 Subagent 必须：

- 只回答当前 `decision_question`；
- 只读取授权材料和必要上游输出；
- 在授权工具范围内补充专业分析；
- 对真实数据使用统一比较基准；
- 区分 measured、proxy、hypothesis 和 unknown；
- 解释指标之间的支持、冲突及空间机制；
- 将判断转化为项目影响、空间功能、行动和验证条件；
- 用普通语言提交可直接进入报告的专业模块；
- 明确证据链接、局限和仍需核实的问题；
- 数据不足时标记 `blocked`、`conditional` 或 `hold`，不得补造。

### 3.3 主 Agent 的最终综合责任

主 Agent 只基于 accepted 专业交付完成：

- 执行摘要；
- 项目空间总策略；
- 跨章一致性检查；
- 建筑与空间单元功能总表；
- 重复内容合并；
- 章节顺序和衔接；
- 分期行动与验证闸门；
- 对专业分歧的显式呈现或退修处理。

主 Agent 不得：

- 给未分析的空间单元补造功能；
- 把条件性建议改成确定性结论；
- 改写 accepted 专业判断的含义；
- 在没有 accepted 来源时新增商业结论；
- 遇到专业冲突时静默选择一方；
- 为了报告顺滑而删除重要限制和停止条件。

### 3.4 Python 的责任

Python 继续作为领域数据面和确定性执行层，负责：

- 读取真实项目材料和保存数据；
- 指标 `catalog/detail/execute`；
- 数据健康、几何修复、范围归一化和结果复用；
- 生成稳定 result ID；
- 校验分析计划、章节交付、证据引用、空间覆盖和审校工件；
- 确定性编译报告；
- 保存不可变 run。

Python 不负责：

- 模拟专业作者；
- 模拟总编；
- 维护作者或编辑 Prompt phase；
- 构建通用 Agent 消息总线；
- 实现 Codex Subagent 生命周期；
- 实现 LLM 退修循环；
- 猜测建筑功能或补写专业判断。

## 4. 历史能力回收矩阵

| 历史能力 | 价值 | 当前状态或风险 | Skill-first 正确归属 | 决策 |
|---|---|---|---|---|
| 项目商业理解 | 明确谁付款、谁使用、需求单位和履约方式 | V4.1 已保留，但需要贯穿角色任务 | 主 Agent 工作流、business model references | 保留并强化 |
| 指标知识卡 | 让 Agent 知道测量内容、适用问题、比较方式和误读边界 | 已有 catalog/detail 设计 | Python 提供卡片，Skill 负责选择和解释 | 保留 |
| 指标组合解释 | 避免逐指标罗列，解释支持、冲突和空间机制 | 部分散落在旧 Prompt 和分析规则 | analysis recipes、角色卡、质量门槛 | 回收 |
| 项目内部比较 | 候选点同口径比较，单一区域内部比较 | V4.1 已定义，执行一致性仍需检查 | 指标工具、ChapterAssignment、质量闸门 | 保留并验证 |
| 专业角色投影 | 降低上下文泄漏和无关信息干扰 | 当前有授权材料概念 | 主 Agent 投影和任务输入契约 | 保留 |
| context/finding/decision 依赖 | 控制上游信息释放和专业责任 | 当前主要是 Skill 文字语义 | report orchestration reference | 回收语义，不恢复 Python 调度器 |
| DAG 波次并行 | 提高独立任务效率 | Codex 可原生分派，当前 Skill 已描述 | 主 Agent 原生 Subagent 调度 | 保留 |
| 原作者定向退修 | 防止总编代写专业结论 | 当前 Skill 已保留 | 主 Agent 验收流程 | 保留 |
| 总编只裁决不代写 | 保护专业责任和结论来源 | 已定义，但最终报告表达仍需落实 | 质量门槛、editorial review、报告契约 | 保留并强化 |
| Subagent 自主工具使用 | 让专业角色真正完成分析，而非文字代写 | 当前未形成完整授权契约 | ChapterAssignment 工具权限 | 新增并约束 |
| 稳定 result ID | 保证结论可追溯到真实执行结果 | V4.1 已保留 | Python 指标层和 source index | 保留 |
| 空间单元完整盘点 | 确保所有建筑和非建筑空间都有处理结果 | 独立空间功能策划资料中已有，尚未成为主 Skill 强制门槛 | 主 Agent 前置清单、空间功能角色、覆盖校验 | 回收并设为必选 |
| 系统—组团—单元三级分析 | 防止把“一路一院一园”和单栋建筑混在同一层级 | 既有空间功能策划矩阵已定义 | spatial-unit-programming reference | 回收 |
| 项目组合检查 | 识别功能重复、配套缺失、居民冲突和动线断裂 | 当前报告未稳定呈现 | 专业交付和项目级综合 | 回收 |
| 经营验证条件 | 数据不足时转为踏勘、访谈、试运营和停止条件 | V4.1 已有原则 | Subagent 交付、质量门槛和行动表 | 保留并强化 |
| 普通语言专业交付 | 减少主 Agent 二次翻译和结论漂移 | 当前交付偏结构化字段 | ChapterDeliveryPackage 的 reader-facing 内容 | 新增 |
| 面向普通读者的单一报告 | 让业主直接理解项目怎么做 | 当前报告偏专业长表 | report contract 和确定性编译器 | 重构表达顺序 |
| V3 蓝图锁 | 固化运行计划和审计边界 | 增加运行时复杂度 | 无 | 不恢复 |
| V3 证据快照与执行谱系 | 强审计与可复现治理 | 超出当前 demo 需要 | 无；保留 V4.1 source index/result ID 即可 | 不恢复 |
| Python Provider 和 Prompt phase | 在应用内部模拟 LLM 运行时 | 与 Codex 重复建设 | 无 | 不恢复 |
| Python DAG/消息总线/编辑循环 | 管理 Agent 生命周期和退修 | 与 Codex 原生能力重复 | Codex 主 Agent | 不恢复 |
| V3/V4 兼容分支 | 读取旧 payload 和旧 artifact | 增加认知负担和契约漂移 | 无 | 不恢复 |

## 5. 工具能力决策

### 5.1 主 Agent 工具能力

主 Agent 保留项目级工具权限：

- 项目和历史资料读取；
- 空间单元盘点；
- 指标 `catalog()` 发现；
- 候选指标 `detail()` 阅读；
- 公共基础指标执行；
- result ID 和 source index 管理；
- 任务规划和工具授权；
- 交付校验；
- 报告编译；
- run-storage；
- 测试和运行目录检查。

### 5.2 Subagent 工具能力

Subagent 应具备任务级、角色级、范围受限的工具能力。工具权限必须随 `ChapterAssignment` 明确传递，而不是默认允许自由扫描和执行。

建议任务输入增加：

```yaml
ChapterAssignment:
  chapter_id:
  specialist_role:
  decision_question:
  authorized_resource_ids: []
  authorized_result_ids: []
  metric_knowledge_cards: []
  upstream_outputs: []
  dependency_boundaries: []
  tool_permissions:
    detail_tool_ids: []
    execute_tool_ids: []
    project_scope_id:
    allowed_unit_ids: []
    allowed_comparison_parameters: {}
    filesystem_access: none
    report_compilation: false
    run_storage: false
```

Subagent 可以：

- 读取授权资源；
- 读取指定指标知识卡；
- 查询授权 result ID；
- 执行明确授权的指标；
- 在指定分析范围和空间单元内比较；
- 返回新 result ID 并在专业交付中引用。

Subagent 不可以：

- 自由读取完整项目目录、完整 run 或完整 source index；
- 执行与当前决策问题无关的指标；
- 擅自改变空间范围、年份、分辨率或比较口径；
- 修改其他章节和最终审校；
- 编译报告或创建不可变 run；
- 创建新的专业 Agent；
- 将工具日志直接写入公开报告。

当前 Codex 的材料授权可能首先是协作契约，而不是文件系统级硬沙箱。因此还必须通过“最小上下文投影 + 参数范围限制 + result ID 校验 + 主 Agent 验收”共同控制越界风险。

## 6. 人可读的专业交付契约

专业交付应同时满足三个目标：

1. 普通读者能理解；
2. 主 Agent 能验收；
3. Python 能校验关键引用和覆盖关系。

建议将 `ChapterDeliveryPackage` 解释为结构化报告模块，而不是机器记录：

```yaml
ChapterDeliveryPackage:
  chapter_id:
  decision_question:
  reader_content:
    reader_takeaway:
    plain_language_summary:
    report_sections: []
    spatial_unit_decisions: []
    decision_tables: []
    actions: []
    validation_conditions: []
    limitations: []
  traceability:
    findings: []
    evidence_links: []
    comparison_baselines: []
    covered_unit_ids: []
    blocked_unit_ids: []
```

Codex 实际交付可以使用结构化 Markdown 表达。每个结论先使用普通语言说明，再附紧凑追溯信息。例如：

```markdown
## 礼堂建议承担什么功能

礼堂建议优先承担演出、展映、发布和社区公共活动，不建议直接改造成高频纯餐饮空间。

礼堂的大空间条件及其与西侧庭院的关系，使其比普通办公建筑更适合承接集中活动。但这一建议成立的前提是消防疏散、声学影响和运营成本可控。

### 建议行动

1. 开展建筑安全、消防和声学检查；
2. 组织一次小规模公共活动测试；
3. 记录布展成本、人员需求、噪声影响和居民反馈。

### 继续或停止条件

如果消防改造成本不可控，或者夜间噪声无法缓解，则停止将礼堂作为高频夜间活动空间。

- 判断编号：F-SPU-01
- 比较基准：与县委楼、宣教楼等现状建筑比较
- 证据：DOC-DESIGN-03、RESULT-ACCESS-02
```

主 Agent 应直接使用 accepted 的正文和表格进行组装，不再次发明专业内容。

## 7. 空间单元能力必须进入主流程

对于城市更新、园区、多建筑、文旅和复合社区项目，主 Agent 必须在专业任务规划前建立空间单元清单。

至少区分：

- **系统层：** 主路径、整体开放体系、居民—游客—后勤流线；
- **组团层：** 建筑与庭院形成的功能组合；
- **单元层：** 每栋建筑、庭院、花园、围墙、门禁和辅助空间。

每个已确认单元必须得到以下状态之一：

```text
planned   已形成有证据和条件的功能建议
blocked   因产权、测绘、结构、消防、居民意愿或其他关键数据不足暂缓
excluded  有明确理由不进入本轮改造或运营范围
```

不得静默省略。报告发布前至少校验：

```yaml
SpatialUnitCoverage:
  reported_building_count:
  inventoried_building_count:
  planned_count:
  blocked_count:
  excluded_count:
  silently_omitted_count:
```

并执行项目组合检查：

```yaml
PortfolioCheck:
  duplicated_functions:
  missing_support_functions:
  public_space_continuity:
  resident_public_conflicts:
  day_night_balance:
  visitor_route:
  resident_route:
  logistics_route:
  fire_and_accessibility_dependencies:
  operational_dependencies:
  phased_activation_logic:
```

## 8. 单一普通读者报告

最终公开的 `report/project-report.md` 应直接面向业主、管理者和普通决策者，不额外生成一份“专业版”再翻译成“普通版”。

推荐固定阅读顺序：

```text
一句话结论
→ 项目整体应该怎么做
→ 项目空间总策略
→ 建筑与空间单元功能总表
→ 0—180 天行动
→ 建筑和空间单元详细卡片
→ 专业空间分析依据
→ 验证方法、限制与待确认事项
```

报告表达规则：

- 先写项目判断，再写指标名称；
- 先写空间和行动含义，再写专业参数；
- 所有技术术语第一次出现时用普通语言解释；
- 执行摘要不展示工具日志、资源索引、内部 ID 列表或数据健康长表；
- 建筑功能表应在报告前部出现；
- 所有条件性建议明确写出成立条件；
- 专业数值保留在依据部分，不制造伪精确经营结论；
- 不出现 `[[ref:...]]`、完整 source index、Provider 日志或 Agent 退修记录。

例如，不应先写：

```text
Moran I=0.394364，z=5.752525。
```

应先写：

```text
项目周边设施并非均匀分布，而是在部分方向形成连续集中区域。因此，现场踏勘应优先检查这些连续区域是否对应稳定人流和商业活动，而不是随机选择单个网格。空间自相关结果支持这一判断。
```

专业参数随后作为依据出现。

## 9. 明确不恢复的内容

以下能力和工件不因本次历史回收而恢复：

- `AnalysisBlueprint` 及蓝图锁；
- EvidenceSnapshot；
- execution lineage；
- 旧章节包和审计附录；
- Python Provider 抽象；
- Python 作者、编辑 Prompt phase；
- Python `asyncio` Agent 波次调度器；
- 自建 Agent 消息总线；
- Python 退修循环；
- V3/V4 双路径和旧字段 fallback；
- 公开报告中的完整资源索引、工具日志和审计台账。

若旧实现中包含有价值规则，应提取规则并迁入 Skill references、指标知识卡、专业角色卡、质量门槛或报告契约，而不是恢复旧类和旧 artifact。

## 10. 历史能力来源与回收方法

后续能力盘点至少检查以下来源：

1. 当前和 Git 历史中的 V3/V4 报告编排代码；
2. 已删除或改写的作者、编辑、投影和依赖相关测试；
3. V4.1 业务设计草案和 V4 目标架构；
4. `skills/spatial-business-analyst/references/` 中的指标选择、分析 recipes 和空间推理规则；
5. `docs/空间功能策划决策矩阵.md`；
6. `skills/spatial-unit-planning` 和 `skills/spatial-client-presentation`；
7. 历史真实 run、章节包和最终报告；
8. 用户对真实报告提出的遗漏空间单元、表格价值和可读性反馈。

每项发现记录为：

```yaml
RecoveredCapability:
  capability_id:
  capability_name:
  historical_source:
  original_behavior:
  business_value:
  current_status: retained | partial | missing | obsolete
  target_owner: main_agent | subagent | skill_reference | python_domain | compiler
  migration_action:
  acceptance_evidence:
```

不要以“旧文件仍存在”证明能力已经保留。只有当前 Skill、契约、代码、测试和真实 run 能证明该行为时，才算完成迁移。

## 11. 实施顺序

### 阶段一：只读能力考古

- 检查历史实现、测试、Prompt、报告和专业资料；
- 形成完整 `RecoveredCapability` 清单；
- 标记 retained、partial、missing 和 obsolete；
- 不在盘点阶段恢复旧运行时。

### 阶段二：收敛 Skill 主流程

- 明确“主 Agent 分析与规划—Subagent 专业分析—主 Agent 验收与合成”；
- 将空间单元盘点设为适用项目的前置步骤；
- 增加专业 Subagent 工具权限；
- 明确人可读、可直接进入报告的交付要求；
- 更新依赖波次和一次退修规则。

### 阶段三：迁移专业知识

- 从旧 Prompt、旧代码和旧测试中提取指标组合、冲突解释和行动推导规则；
- 将其迁入 `analysis-recipes.md`、`spatial-inference-rules.md`、专业角色卡和新增空间功能 reference；
- 避免把专业知识重新写入 Python LLM 编排层。

### 阶段四：收敛校验和编译

- 校验空间单元不允许静默遗漏；
- 校验 blocked 单元说明缺口；
- 校验功能建议绑定 finding 和 evidence；
- 校验 action 由 finding 推出；
- 校验综合内容只引用 accepted 交付；
- 将建筑功能总表和近期行动放到报告前部；
- 将专业参数和证据详情移到后半部分。

### 阶段五：真实项目验收

- 使用保存的真实项目材料和空间结果；
- 创建新的不可变 run，不覆盖历史 run；
- 验证所有建筑及非建筑空间得到 planned、blocked 或 excluded 状态；
- 验证 Subagent 确实使用授权工具或授权结果完成专业分析；
- 验证最终报告可以被非 GIS、非数据分析背景的读者理解；
- 验证报告仍然可追溯，但不呈现内部工具日志和审计台账。

## 12. 验收标准

本次能力迁移只有在以下条件全部满足时才算完成：

1. 有一份可追踪的历史能力清单，说明每项能力的来源、现状、归属和验证方式；
2. 旧运行时没有恢复，Python 中不存在新的 LLM 作者、编辑或通用 Agent 调度器；
3. 主 Agent 工作流明确包含项目理解、空间单元盘点、任务规划、工具授权、验收、退修和综合；
4. 专业 Subagent 能在任务范围内读取证据并按授权调用工具；
5. Subagent 交付的是普通语言、可直接进入报告的专业模块；
6. 主 Agent 的综合只使用 accepted 内容，不代写新的专业判断；
7. 多建筑项目中的空间单元没有静默遗漏；
8. 指标结果说明比较基准，并能解释组合支持、冲突和项目影响；
9. 行动由 finding 推出，并包含验证、继续或停止条件；
10. 最终只公开一份普通读者报告，建筑与空间功能总表位于报告前部；
11. 技术指标、证据详情和限制仍可追溯，但不会淹没项目判断；
12. 使用真实保存数据生成新的不可变 run，并通过相关 Skill、domain、API、报告和 run-storage 测试。

## 13. 本次决策的边界

本文只确认历史能力回收和迁移方向，不在文档编写阶段修改现有 Skill、Python Schema、编译器、测试或真实 run。

后续实施不得以“快速恢复聪明能力”为由重新引入 V3 运行时，也不得以“保持 Skill-first 简单”为由继续丢弃已有的专业知识和分析行为。正确做法是逐项提取、明确归属、建立验收证据，然后迁入当前单一架构。
