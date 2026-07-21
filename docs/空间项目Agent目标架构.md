# 空间项目 Agent 目标架构

## 1. 架构目的

本文件定义空间项目 Agent 的目标架构、职责边界和成果关系。它服务于后续产品设计、数据建设、AI 调用和成果验收。

系统以项目为组织单位。一个项目拥有明确范围、锁定的数据快照、确认的空间单元、可追溯证据、可恢复的运行记录和可审定的成果。商业报告、空间单元策划和甲方汇报 PPT 都从同一项目快照获取事实依据。

## 2. 架构总览

<div style="width:100%;max-width:1200px;box-sizing:border-box;position:relative;background:#fafbfc;padding:20px;border-radius:6px;border:1px solid #e5e7eb;overflow-x:auto;">
<style scoped>
.spa-arch-wrapper{display:flex;gap:12px;min-width:900px}.spa-arch-sidebar{width:170px;flex-shrink:0}.spa-arch-main{flex:1;min-width:0}.spa-arch-title{text-align:center;font-size:20px;font-weight:700;color:#1f2937;margin-bottom:14px}.spa-arch-layer{margin:8px 0;padding:12px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.04)}.spa-arch-layer-title{font-size:13px;font-weight:700;margin-bottom:8px;text-align:center}.spa-arch-grid{display:grid;gap:8px}.spa-arch-grid-2{grid-template-columns:repeat(2,1fr)}.spa-arch-grid-3{grid-template-columns:repeat(3,1fr)}.spa-arch-box{border-radius:4px;padding:8px;text-align:center;font-size:11px;font-weight:600;line-height:1.35;color:#1f2937;background:#fff;border:1px solid #e5e7eb}.spa-arch-box small{display:block;margin-top:3px;font-size:10px;font-weight:400;color:#4b5563}.spa-arch-box.highlight{border:2px solid #6b7280;background:#f9fafb}.spa-arch-user{background:#eff6ff;border:2px solid #3b82f6}.spa-arch-user .spa-arch-layer-title{color:#1d4ed8}.spa-arch-app{background:#fffbeb;border:2px solid #d97706}.spa-arch-app .spa-arch-layer-title{color:#92400e}.spa-arch-ai{background:#f0fdf4;border:2px solid #16a34a}.spa-arch-ai .spa-arch-layer-title{color:#15803d}.spa-arch-data{background:#fdf2f8;border:2px solid #db2777}.spa-arch-data .spa-arch-layer-title{color:#9d174d}.spa-arch-output{background:#f5f3ff;border:2px solid #7c3aed}.spa-arch-output .spa-arch-layer-title{color:#5b21b6}.spa-arch-sidebar-panel{border-radius:6px;padding:10px;background:#fff;border:1px solid #d1d5db;margin-bottom:8px}.spa-arch-sidebar-title{font-size:12px;font-weight:700;text-align:center;color:#1f2937;margin-bottom:6px}.spa-arch-sidebar-item{font-size:10px;text-align:center;color:#374151;background:#f9fafb;padding:6px;border-radius:3px;margin:4px 0;border:1px solid #e5e7eb}
</style>
<div class="spa-arch-title">空间项目 Agent 目标架构</div>
<div class="spa-arch-wrapper">
<div class="spa-arch-sidebar"><div class="spa-arch-sidebar-panel"><div class="spa-arch-sidebar-title">调用与审阅</div><div class="spa-arch-sidebar-item">Codex 与 ChatGPT</div><div class="spa-arch-sidebar-item">策划与分析人员</div><div class="spa-arch-sidebar-item">甲方决策者</div></div><div class="spa-arch-sidebar-panel"><div class="spa-arch-sidebar-title">外部资料</div><div class="spa-arch-sidebar-item">高德与本地 POI</div><div class="spa-arch-sidebar-item">人口、夜光与路网</div><div class="spa-arch-sidebar-item">项目文件与外部证据</div></div></div>
<div class="spa-arch-main"><div class="spa-arch-layer spa-arch-user"><div class="spa-arch-layer-title">调用与人工工作台</div><div class="spa-arch-grid spa-arch-grid-3"><div class="spa-arch-box highlight">MCP 调用面<small>AI 查询、启动任务、取得成果</small></div><div class="spa-arch-box">分析工作台<small>地图、证据、任务和成果审阅</small></div><div class="spa-arch-box">项目审批<small>确认范围、方案和汇报材料</small></div></div></div><div class="spa-arch-layer spa-arch-app"><div class="spa-arch-layer-title">空间项目服务</div><div class="spa-arch-grid spa-arch-grid-3"><div class="spa-arch-box">项目与范围<small>项目身份、边界、任务要求</small></div><div class="spa-arch-box highlight">数据快照与空间单元<small>锁定事实版本与单元清单</small></div><div class="spa-arch-box">运行与成果库<small>任务状态、版本、文件和审批</small></div></div></div><div class="spa-arch-layer spa-arch-ai"><div class="spa-arch-layer-title">专业工作流</div><div class="spa-arch-grid spa-arch-grid-3"><div class="spa-arch-box">商业分析<small>商圈、机会业态与选址判断</small></div><div class="spa-arch-box">空间单元策划<small>逐单元方案与项目组合校验</small></div><div class="spa-arch-box">汇报材料<small>叙事、页面、PPT 与证据附录</small></div></div></div><div class="spa-arch-layer spa-arch-data"><div class="spa-arch-layer-title">数据与证据</div><div class="spa-arch-grid spa-arch-grid-3"><div class="spa-arch-box">空间数据<small>POI、人口、夜光、路网和格网</small></div><div class="spa-arch-box">项目资料<small>文档、图片、地图和任务书</small></div><div class="spa-arch-box">证据台账<small>来源、时间、质量、限制和定位</small></div></div></div><div class="spa-arch-layer spa-arch-output"><div class="spa-arch-layer-title">审定成果</div><div class="spa-arch-grid spa-arch-grid-3"><div class="spa-arch-box">商业报告</div><div class="spa-arch-box">空间策划矩阵</div><div class="spa-arch-box">PPTX、预览与证据附录</div></div></div></div>
<div class="spa-arch-sidebar"><div class="spa-arch-sidebar-panel"><div class="spa-arch-sidebar-title">质量治理</div><div class="spa-arch-sidebar-item">范围、时间和来源</div><div class="spa-arch-sidebar-item">数据缺口与代理边界</div><div class="spa-arch-sidebar-item">单元覆盖与组合校验</div></div><div class="spa-arch-sidebar-panel"><div class="spa-arch-sidebar-title">成果治理</div><div class="spa-arch-sidebar-item">人工审定</div><div class="spa-arch-sidebar-item">版本与重新审查</div><div class="spa-arch-sidebar-item">访问与操作记录</div></div></div>
</div>
</div>

图中的中间五层构成产品主链。左侧对象提供调用、审阅和资料，右侧规则约束项目事实、成果质量和人员责任。

## 3. 架构决策

### 3.1 MCP 是 AI 的主调用面

Codex、ChatGPT 和其他获准的 AI 助手通过 MCP 查询项目数据、读取证据、启动专业任务、查询运行状态和取得成果文件。MCP 只暴露项目语义，例如“读取项目数据目录”或“生成商业报告”，不让调用方了解存储结构和内部分析步骤。

MCP 的读取能力应服务于范围、数据目录、统计、异常记录、空间单元和证据。需要生成报告、策划或 PPT 的调用应创建可追踪的任务，并返回任务状态和成果引用。AI 不应直接写入或覆盖已经审定的成果。

### 3.2 Skill 规定方法，不保存项目事实

Skill 用于规定复杂任务的专业步骤、证据要求、禁止推断和输出质量。商业分析、城市更新策划和 PPT 叙事都可以拥有各自的 Skill。

Skill 不承担项目数据、空间单元、成果版本、访问控制或人工审批。它从项目服务取得经过筛选的事实和证据，在规定的方法边界内组织分析。

### 3.3 分析工作台承担人工判断

`/analysis` 是人员查看地图、检查数据质量、确认空间单元、审阅结论和批准成果的工作台。它可以调用与 MCP 相同的项目服务，但不拥有另一套事实来源。

项目负责人和专业人员应在三个节点作出明确决定：确认分析范围和数据版本、确认核心策划方向、确认进入甲方汇报阶段的成果。

### 3.4 Plugin 和 ChatGPT App 服务于后续分发

Plugin 用于打包 MCP、Skill、说明和默认配置。ChatGPT App 用于在 ChatGPT 内展示地图、任务状态、报告摘要或成果预览。它们都建立在稳定的 MCP 和项目服务之上，不承担项目事实和专业判断。

## 4. 核心业务对象

| 对象 | 定义 | 关系 |
| --- | --- | --- |
| 项目 | 一个委托任务及其范围、任务要求和参与者 | 项目拥有数据快照、空间单元和成果 |
| 数据快照 | 某次分析使用的锁定事实版本 | 报告、策划和 PPT 都引用同一快照 |
| 数据集目录 | 快照中每类数据的范围、时间、来源、质量和缺口说明 | 使用者据此判断数据是否可用于任务 |
| 空间单元集 | 经确认的地块、建筑、庭院、街区或节点清单 | 每个单元拥有明确状态和策划结果 |
| 证据 | 可定位的项目事实、计算结果、外部资料或现场观察 | 结论和图表引用证据 |
| 运行任务 | 一次商业分析、单元策划或 PPT 生成活动 | 任务固定输入快照并产出版本化成果 |
| 成果 | 报告、策划矩阵、PPT、预览和附录 | 成果拥有草稿、待审、已审和过期状态 |

这些对象组成单一事实链：项目确定范围，数据快照锁定依据，空间单元承接空间判断，证据支撑结论，运行任务生成成果，人员审定成果后用于交付。

## 5. 数据与证据层

数据与证据层向所有专业工作流提供同一套项目事实。它包含空间数据、项目资料和外部证据三部分。

- 空间数据包括 POI、人口、夜光、路网、等时圈、格网和空间分析结果；
- 项目资料包括任务书、规划资料、调研文件、图纸、图片和既有成果；
- 外部证据包括经过选择和记录的政策、案例、公开资料与现场观察。

数据集目录必须说明范围、时间、来源、口径、质量、覆盖情况和缺口。系统将事实、计算结果、推断和假设分开保存。AI 可以引用事实和计算结果，也可以提出推断或假设，但必须标明前提和验证任务。

完整明细保留在项目数据主体中。AI 按任务读取统计、异常、代表对象和单条记录，避免把大量原始数据直接变成提示词内容。

## 6. 专业工作流层

### 6.1 商业分析工作流

输入包括分析范围、锁定数据快照、目标问题和已选资料。工作流围绕商圈、市场潜力、供需缺口、机会业态、竞争、客群和选址适配组织判断。

输出包括模型状态、主要信号、证据、数据缺口、验证计划和商业报告。人口、夜光、POI 和道路指标只能作为各自定义范围内的代理信息，报告不得把它们改写成销售额、真实客流、市场份额或投资回报。

### 6.2 空间单元策划工作流

输入包括确认的空间单元集、锁定数据快照、项目任务书、约束和项目级定位。工作流先形成项目整体方向，再为各空间单元给出候选功能、首选建议、排除方向、运营要求、风险和验证事项。

输出包括逐单元策划结果、单元状态、地图表达和项目组合校验。系统必须说明全部合格单元的处理结果，登记排除和受阻原因，避免遗漏单元。

### 6.3 甲方汇报工作流

输入包括经过人工审定的商业报告、空间单元策划、项目资料和视觉素材。工作流将结论组织为甲方能够阅读、判断和批准的叙事结构，并生成页面内容、地图、图表、PPTX、预览和证据附录。

甲方汇报只消费经过审定的事实和结论。草稿、待验证假设和已过期成果不能直接进入正式汇报。

## 7. 成果生命周期

项目成果按以下顺序形成：

1. 项目负责人确认范围、任务要求、资料和空间单元；
2. 专业人员检查数据目录并锁定本轮数据快照；
3. Agent 基于快照生成商业报告或空间单元策划草稿；
4. 专业人员审定核心结论、推荐方向和验证事项；
5. Agent 使用已审定成果生成甲方汇报材料；
6. 项目团队保存成果版本、证据关系和审批记录。

上游数据、范围或空间单元发生变化后，系统保留已有成果，并将受影响成果标记为需要重新审查。使用者可以比较不同版本，而不丢失当时的判断依据。

## 8. 质量与治理

系统通过以下规则保护成果质量：

- 每个正式结论都引用项目证据或明确的计算结果；
- 数据不足时，Agent 降低结论等级并列出补充资料和验证工作；
- 每个合格空间单元都拥有策划结果、排除记录或受阻记录；
- 人工审定决定哪些结论可以进入正式报告和甲方 PPT；
- 成果保留来源、输入快照、运行记录、审批状态和版本关系；
- 调用方只能访问其获准项目的数据和成果。

专业人员负责判断项目结论和风险，甲方负责作出项目决策。Agent 负责组织数据、执行分析方法、生成草稿和保留证据链。

## 9. 架构边界

本架构不把通用聊天记录作为项目事实来源，也不让单个提示词承担数据治理、专业分析和成果交付。项目服务拥有事实与版本，Skill 约束方法，MCP 提供调用，工作台支持人员审阅。

首期不承诺官方 ESRI 数据能力、投资级收益预测、自动代替甲方审批、建筑施工设计或公开多租户运营。项目可以在后续阶段接入获准数据源、ChatGPT App 或 Plugin，但这些扩展不改变本文件定义的职责边界。

## 10. 与其他文档的关系

- [空间项目 Agent 最终目标](空间项目Agent最终目标.md) 定义产品要达到的业务结果；
- 本文件定义实现这些结果时各层承担的职责和成果之间的关系；
- 商业分析、城市更新策划、证据接入和 PPT 生成文档分别记录各专业工作流的详细规则；
- 后续开发文档可以定义数据结构、接口、任务状态和测试方案，但不得改变本文件确定的职责边界。
