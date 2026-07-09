# 技术执行型分析 Agent 开发计划

## 1. 目标定位

本项目的 AI 模块不是通用聊天机器人，也不是只做解释的分析副驾，而是服务于 `/analysis` 工作台的技术执行型分析 Agent。

它的核心职责是：

- 理解用户提出的业务问题
- 先把现有能力预处理、封装为可调用工具
- 自动把问题翻译成可执行的能力链，而不是机械翻译成 GIS 步骤
- 直接调用 GIS 工具、现有业务能力和数据处理能力完成分析
- 在执行过程中持续补充上下文和证据
- 对结果进行质量审计和结构化输出
- 在必要时继续追加后续分析，而不是停留在计划层

第一版以“右侧 AI 助手面板”为主要交互入口，绑定当前 analysis 会话，不做跨分析会话的持续长记忆。

一句话定义：

> 用户提出问题，Agent 自动拆解为可执行任务，并调用 GIS 工具与系统已有能力直接完成处理；只有在输入缺失、目标不清或风险过高时才向用户追问。

---

## 2. 总体设计原则

### 2.1 产品原则

- Agent 只服务当前地图分析任务，不做开放式闲聊
- Agent 默认直接执行，而不是默认先确认
- Agent 输出以“执行结果 + 证据 + 风险 + 建议”为主
- Agent 结论必须引用事实字段，不能把推测写成事实
- Agent 必须遵守 GIS 分析解释边界，不能直接推断人口、客流、消费能力、经营收益
- 只有在关键信息缺失、成本过高、或存在多条分歧路径时才打断用户
- Agent 的执行单元不是单纯 GIS 算法步骤，而是“工具化后的能力”

### 2.2 工程原则

- 复用现有 `isochrone`、`poi`、`h3`、`road`、`population`、`nightlight`、`export` 能力
- `router` 只做 HTTP 边界，Agent 业务逻辑下沉到 `modules/agent`
- 先把系统已有能力整理成稳定工具接口，再让 Agent 去编排调用
- 先做单 orchestrator 的多阶段流水线，不急于上真正并行多 agent
- 会话状态优先由前端持有，后端保持轻状态编排
- 模型层做 provider 抽象，但 V1 先落一个 OpenAI-compatible provider

### 2.3 Harness 架构原则

借鉴 OpenHarness 的核心思想，本项目中的 Agent 不直接操作底层模块，而是运行在一个轻量 harness 之上。

职责划分如下：

- 模型
  - 负责理解问题、选择能力链、决定下一步动作
- Harness Runtime
  - 负责上下文装配、工具调用、执行控制、权限治理、轨迹记录
- Tool Registry
  - 负责暴露可调用工具，而不是让模型直接扫描代码
- Governance
  - 负责限制高成本工具、处理风险确认、控制自动执行边界

一句话理解：

> 模型负责“做什么”，harness 负责“怎么安全地做”。

---

## 3. 架构映射

本方案将设计图中的角色落成单一 Agent 编排流水线中的不同阶段，而不是一开始做多个独立自治 Agent。

### 3.1 图中角色到系统模块的映射

- 门卫节点
  - 对应 `gate`
  - 负责判断问题是否明确、是否缺关键输入、是否允许直接开工
- 工具文档搜索员
  - 对应 `context retriever`
  - 负责检索当前 analysis 快照、已有结构化分析结果、GIS 知识片段
- 能力工具化层
  - 对应 `tool registry`
  - 负责把已有 GIS 能力、业务模块能力、数据读取能力、结果处理能力包装成统一工具接口
- 规划师
  - 对应 `llm tool loop`
  - 负责基于上下文决定是否调用工具、调用哪些工具以及何时停止
- 工具执行器
  - 对应 `executor`
  - 负责调用白名单工具并串联多步执行
- 审计员
  - 对应 `auditor`
  - 负责检查证据充分性、解释边界、结果质量，必要时触发补充执行
- 综合决策师
  - 对应 `synthesizer`
  - 负责把结果组织成结构化结论卡片
- 多层工作记忆
  - 对应当前会话状态、研究笔记、关键证据、任务状态
- 上下文工程
  - 对应上下文提取、压缩、证据构建、预算控制
- 控制平面
  - 对应状态机、工具治理、上下文预算、终止条件

### 3.2 V1 的关键取舍

V1 明确不做以下内容：

- 不做真正并发多 agent 协作
- 不做向量数据库
- 不做数据库持久化对话
- 不做自动无限循环推理
- 不做任意工具开放发现
- 不让 Agent 直接触发导出专业包等高成本操作

---

## 4. 系统流程

### 4.0 Agent Loop

借鉴 harness 设计，整个 Agent 不应只看成一次性请求响应，而应视为一个受控 loop：

1. 用户输入问题
2. harness 装配上下文
3. 模型输出下一步能力链或工具调用意图
4. harness 校验工具权限、前置条件和风险等级
5. harness 执行工具
6. harness 将工具结果、轨迹和证据回注给模型
7. 如果还需要继续执行，则进入下一轮 loop
8. 达到终止条件后输出结果

因此，本项目的执行闭环不是纯 prompt chain，而是“模型决策 + harness 执行控制”的循环。

### 4.1 主流程

1. 用户在 `/analysis` 右侧 AI 面板输入问题
2. Agent 进入门卫阶段，判断问题是否足够明确
3. 如果问题不明确，则只提出最少量澄清问题
4. 如果问题明确，则进入上下文工程阶段
5. 上下文工程从当前 analysis 会话中提取事实、摘要、限制条件
6. 规划师把问题翻译成可执行能力链
7. 工具执行器直接调用 GIS 工具、已有业务能力和数据处理能力
8. 每一步执行结果写入工作记忆和中间证据
9. 审计员检查结果质量；若证据不足，则自动追加后续分析
10. 综合决策师输出结构化结论卡片
11. 若存在更高收益的下一步分析，则给出建议，但不阻塞本轮回答

### 4.2 问题分流策略

用户问题分三类：

- 可直接执行
  - 当前问题明确，且能力链可以直接开工
- 需补充澄清
  - 缺少地点、范围、时间、交通方式等关键输入
- 需风险确认
  - 操作明显高成本、耗时过长、或存在多条重要分支需要用户选择

默认主路径是“可直接执行”，不是“先确认再执行”。

---

## 5. 阶段设计

控制平面使用一组收敛阶段描述本轮 Agent 进展；阶段只表达用户可感知的运行位置，不再保留独立 Planner / Auditor / Replanner 状态机。

### 5.1 状态定义

- `gating`
  - 问题明确性判断
- `clarifying`
  - 正在组织澄清问题
- `executing`
  - 正在按上下文窗口调用工具或读取证据
- `synthesizing`
  - 正在执行最终证据检索和自然回答生成
- `requires_clarification`
  - 缺关键输入，等待用户补充
- `requires_risk_confirmation`
  - 高成本工具需要用户确认
- `answered`
  - 已输出最终回答
- `failed`
  - 当前轮失败

### 5.2 终止条件

满足任一条件即停止本轮：

- 已经给出足够完整的执行结果
- 缺少必要信息且已向用户提出澄清问题
- 遇到高风险操作且已请求用户确认
- 审计通过且没有必须补跑的后续步骤
- 工具失败且无可恢复路径

### 5.4 Governance 模式

借鉴 harness 的治理思路，本项目的执行控制建议分成三种模式：

- `auto`
  - 默认模式，允许自动执行普通工具
- `guarded`
  - 对高成本工具、长耗时工具进行风险确认
- `readonly`
  - 仅允许读取已有结果和做结果处理，不允许触发新计算

这三种模式不是模型自己决定，而由 harness runtime 根据工具元数据和上下文状态控制。

### 5.3 收敛规则

当前主链路不再维护独立 Planner 回退层。运行时只允许三类明确收敛：

- 执行前发现缺输入，直接进入澄清结果
- 预处理来源直答失败，直接返回失败，不进入完整工具循环
- ReAct 工具循环失败、风险确认或完成后，分别进入失败、确认或最终综合

审计阶段只负责标注证据缺口和解释边界；是否补证据应由同一轮 ReAct 工具窗口完成，不恢复旧式 replan 循环。

---

## 6. 上下文工程设计

### 6.1 上下文来源

Agent 的上下文只从当前 analysis 会话中提取，不跨仓库、不做泛搜索。

上下文来源包括：

- 当前等时圈或分析范围
- 当前 POI 列表和分类摘要
- 当前 H3 分析结果
- 当前路网句法结果
- 当前人口分析结果摘要
- 当前夜光分析结果摘要
- 当前 UI 面板状态
- 当前筛选条件、交通方式、时间阈值、数据源
- 当前前端已有分析摘要
- 当前历史记录快照（只读引用）

### 6.2 上下文压缩结果

上下文工程产出四类标准对象：

- `facts`
  - 客观指标和关键数值
- `analysis`
  - 各面板已有解释性摘要
- `limits`
  - 解释边界和禁止推断项
- `research_notes`
  - 面向当前轮次的简短中间笔记

### 6.3 上下文预算策略

为了避免上下文膨胀，采用以下裁剪规则：

- 不把大体积 GeoJSON 全量喂给模型
- 网格明细只保留统计摘要和必要 TopN 样本
- POI 明细默认保留摘要和代表样本，不保留全量
- 路网结果默认保留核心指标和主要异常项
- 历史会话只保留当前轮相关快照，不串入全部历史

### 6.4 与现有导出能力的复用关系

复用当前 export 模块中已经存在的 AI 结构化成果口径：

- `ai_report`
- `ai_facts`
- `ai_context`

但 Agent 不走 ZIP 导出链路，而是在内存中直接生成这些等价对象，作为上下文工程的标准输入。

---

## 7. 工具体系设计

### 7.1 白名单工具

V1 的工具不只包含 GIS 分析工具，还包含系统已有能力的工具化封装。

V1 工具注册表仅开放以下能力：

- `run_isochrone`
  - 触发等时圈分析
- `fetch_pois`
  - 获取 POI 数据
- `run_h3_metrics`
  - 触发 H3 分析
- `run_road_syntax`
  - 触发路网句法分析
- `read_population_summary`
  - 读取人口分析摘要
- `read_nightlight_summary`
  - 读取夜光分析摘要
- `read_history_snapshot`
  - 读取历史记录快照

### 7.2 工具分类

V1 工具按能力类型划分为四类：

- GIS 计算工具
  - 如等时圈、H3、路网句法
- 数据获取工具
  - 如 POI 获取、历史快照读取
- 结果读取工具
  - 如人口摘要、夜光摘要、已有前端分析摘要
- 数据处理工具
  - 如上下文压缩、证据提取、结果归一化、结构化整理

Agent 的任务不是只选 GIS 工具，而是从这些工具中组合出可执行能力链。

### 7.3 工具权限策略

- 默认允许 Agent 自动执行白名单分析工具
- 只在高成本操作或重要分支选择时请求用户确认
- 只读型工具可直接读取
- Agent 不得绕过白名单执行任意外部操作
- 工具层不允许自发现、不允许直接执行 shell、文件写入、任意外部调用

### 7.4 工具返回协议

所有工具统一返回以下结构：

- `tool_name`
- `status`
- `result`
- `evidence`
- `warnings`

这样便于审计员和综合决策师消费。

### 7.5 执行能力链模式

V1 支持以下串行执行模式：

- `理解问题 -> 读取上下文 -> 调等时圈 -> 调 POI -> 调 H3`
- `理解问题 -> 读取上下文 -> 调等时圈 -> 调路网`
- `理解问题 -> 读取上下文 -> 调 GIS 工具 -> 读取人口/夜光摘要 -> 做结果整合`
- `理解问题 -> 读取已有分析结果 -> 做证据提取与结构化输出`

后续如有需要，再扩展更复杂链路。

---

## 8. 多层工作记忆设计

V1 不引入独立数据库记忆系统，而是实现轻量工作记忆。

### 8.1 工作记忆分层

- 对话摘要
  - 当前轮之前的简要对话目标
- 研究笔记
  - 当前轮中间发现和上下文摘要
- 任务状态
  - 当前处于哪个阶段，哪些工具已执行
- 关键证据
  - 关键指标、引用字段、证据链
- 动作队列
  - 已规划、已执行、待补跑的动作

### 8.2 绑定方式

工作记忆绑定：

- `conversation_id`
- `analysis_fingerprint`

其中：

- `conversation_id` 表示当前对话实例
- `analysis_fingerprint` 表示当前分析上下文版本

当主要分析结果变化时，前端重算 `analysis_fingerprint`，从而隔离旧上下文污染。

---

## 9. 后端模块规划

### 9.1 新增业务模块

新增 `modules/agent`，作为技术执行型分析 Agent 的业务主域。

当前拆分如下：

- `modules/agent/schemas.py`
- `modules/agent/runtime.py`
- `modules/agent/gate.py`
- `modules/agent/context_builder.py`
- `modules/agent/direct_context.py`
- `modules/agent/finalizer_evidence.py`
- `modules/agent/tools.py`
- `modules/agent/tool_definitions/`
- `modules/agent/tool_adapters/`
- `modules/agent/executor.py`
- `modules/agent/auditor.py`
- `modules/agent/synthesizer.py`
- `modules/agent/providers/llm_provider.py`

### 9.2 各模块职责

- `schemas.py`
  - 定义请求响应、卡片、执行记录、引用、错误模型
- `runtime.py`
  - 实现主链 `gate -> context -> llm tool loop -> auditor -> answer generation`
- `gate.py`
  - 判断是否能直接开工
- `context_builder.py`
  - 从 analysis 快照生成 `facts/analysis/limits/research_notes`
- `direct_context.py`
  - 处理前端已预处理来源的直接回答路径，跳过 gate 和工具循环
- `tools.py`
  - 汇总主 Agent 可见工具注册表
- `tool_definitions/`
  - 定义对 LLM 和外部 API 暴露的工具元数据
- `tool_adapters/`
  - 封装内部分析能力；未注册到 `tools.py` 的适配器只能由服务编排显式调用
- `executor.py`
  - 串行执行工具和结果标准化
- `auditor.py`
  - 检查证据链和解释边界，不承担 replan 职责
- `synthesizer.py`
  - 负责引用和 synthesis payload 整理，最终卡片由 LLM 主生成
- `providers/`
  - 通用 LLM provider 抽象，当前实现落在 DeepSeek chat completions tool calling
- `knowledge/`
  - GIS 知识库和业务规则库

### 9.4 Harness Runtime 职责

`runtime.py` 建议作为轻量 harness 核心，负责：

- 上下文装配
- 工具调用循环
- 最大步数控制
- 权限/风险模式控制
- 执行轨迹记录
- 错误恢复与中断条件

这部分是本项目最接近 OpenHarness 的层，但只保留与 GIS 业务相关的轻量能力，不引入 CLI、多 agent、MCP 全家桶。

### 9.3 路由层规划

新增 `router/domains/agent.py`。

路由层职责仅包括：

- 请求接收
- 参数校验
- 调用 `modules.agent.service`
- 返回标准响应

禁止在路由层内放规划、上下文、工具编排逻辑。

---

## 10. 前端工作台规划

### 10.1 入口位置

在 `/analysis` Step 2 “结果分析”阶段新增 `AI` 导航项，作为右侧执行型分析 Agent 面板。

### 10.2 面板结构

面板分四个区域：

- 对话输入区
- 执行轨迹区
- 结构化结论卡片区
- 快捷问题区

只有在必要时才显示：

- 澄清问题区
- 风险确认区

### 10.3 快捷问题模板

第一版内置以下模板：

- 总结这个区域的商业特征
- 哪里适合补充餐饮或零售
- 为什么这里路网表现差
- 下一步建议做什么分析

### 10.4 前端状态

前端维护以下状态：

- `conversation_id`
- `analysis_fingerprint`
- `messages`
- `execution_trace`
- `assistant_cards`
- `used_tools`
- `research_notes`
- `pending_clarification`
- `pending_risk_confirmation`

### 10.5 会话切换逻辑

当以下任一主结果变化时，需要重置或切换 Agent 会话：

- 等时圈范围变化
- POI 主结果变化
- H3 主结果变化
- 路网主结果变化
- 人口主结果变化
- 夜光主结果变化

---

## 11. API 设计

### 11.1 新增接口

- `POST /api/v1/analysis/agent/turn`

### 11.2 请求体

请求体建议包含：

- `conversation_id`
- `analysis_fingerprint`
- `messages`
- `analysis_snapshot`
- `risk_confirmations`

其中 `analysis_snapshot` 应至少包含：

- scope / isochrone
- pois / poi_summary
- h3 summary / charts / grid_count
- road summary / diagnostics
- population summary
- nightlight summary
- frontend_analysis
- active panel
- current filters
- mode / time_min / source

### 11.3 响应体

响应体建议包含：

- `status`
- `assistant_cards`
- `execution_trace`
- `used_tools`
- `citations`
- `research_notes`
- `next_suggestions`
- `clarification_question`
- `risk_prompt`

### 11.4 状态值

- `executing`
- `answered`
- `requires_clarification`
- `requires_risk_confirmation`
- `failed`

---

## 12. 结构化输出协议

Agent 的输出不是单段聊天文本，而是结构化卡片。

### 12.1 卡片类型

- `summary`
  - 对当前问题的核心结论
- `evidence`
  - 引用哪些字段、哪些指标支撑结论
- `risk`
  - 哪些部分数据不足、边界不清、结论存在不确定性
- `recommendation`
  - 下一步建议做什么

### 12.2 执行轨迹输出

执行轨迹至少包含：

- 当前执行步骤
- 已完成工具列表
- 每步关键结果摘要
- 失败或跳过原因
- 是否存在自动补跑行为

---

## 13. GIS 知识库设计

V1 先采用本地文件规则库，而不是向量数据库。

### 13.1 知识库组成

建议在 `modules/agent/knowledge/` 下维护：

- 文档知识
- 术语知识
- 业务流程 JSON
- 指标字典关系表
- 经验案例模板

### 13.2 首批知识内容

首批重点沉淀：

- H3 指标解释
- 路网句法指标解释
- 人口分析指标解释
- 夜光分析指标解释
- 业务结论模板和禁止推断规则
- 常见用户问题到能力链模板的映射

---

## 14. 模型接入设计

### 14.1 Provider 抽象

采用统一 provider 抽象，保留多模型兼容空间。

首版配置项建议增加：

- `AI_ENABLED`
- `AI_PROVIDER`
- `AI_BASE_URL`
- `AI_API_KEY`
- `AI_MODEL`
- `AI_TIMEOUT_S`
- `AI_MAX_CONTEXT_TURNS`

### 14.2 V1 实现策略

V1 仅实现一个 `OpenAI-compatible` 适配器。

理由：

- 成本最低
- 兼容面广
- 后续切到 OpenAI、DeepSeek、通义兼容端点都方便

---

## 15. 分阶段实施计划

## Phase 0：规格冻结

目标：

- 固化本开发计划
- 冻结边界、术语、状态机、角色映射

交付物：

- `docs/agent开发.md`

验收标准：

- 文档达到可直接指导实现的程度
- 不留“到时候再决定”的关键设计空白

## Phase 1：最小骨架

目标：

- 搭建后端 Agent 模块和路由骨架
- 打通前后端最小调用链

任务：

- 新建 `modules/agent`
- 新建 `router/domains/agent.py`
- 新增配置项
- 提供一个会返回固定执行轨迹和结果卡片的假实现

验收标准：

- 前端可请求到 Agent 接口
- AI 面板能渲染固定执行轨迹和结构化结果

## Phase 2：上下文工程

目标：

- 把当前 analysis 数据标准化成 Agent 上下文

任务：

- 实现 `analysis_snapshot -> facts/analysis/limits/research_notes`
- 复用 export 的 AI 结构化口径
- 加入预算控制和裁剪逻辑

验收标准：

- 上下文输出稳定
- payload 体积可控
- 可针对 context builder 单独测试

## Phase 3：门卫与执行规划

目标：

- 让 Agent 能识别问题并稳定进入 LLM tool loop

任务：

- 实现 `gate`
- 实现 `llm tool loop`
- 覆盖典型问题与工具调用场景
- 产出标准化执行轨迹

验收标准：

- 能稳定区分直接执行、澄清、风险确认三类场景

## Phase 4：工具执行与审计

目标：

- 接入 GIS 工具并保证输出可审计

任务：

- 接入等时圈、POI、H3、路网工具
- 接入只读人口、夜光、历史工具
- 实现 `auditor`
- 支持自动补跑一次后续分析

验收标准：

- 执行结果能附带证据
- 无证据结论可被拦截
- 边界外推断可被拦截
- 常见场景下 Agent 能自动完成分析闭环

## Phase 5：前端 AI 面板

目标：

- 完成 `/analysis` 中的 AI 执行闭环

任务：

- 新增 `AI` 导航项
- 增加对话区、执行轨迹区、结果卡片区、快捷问题区
- 处理会话状态与 fingerprint 切换

验收标准：

- 能完成“提问 -> 自动执行 -> 输出”的主流程
- 只有必要时才出现澄清或风险确认

## Phase 6：知识库与稳定性

目标：

- 提升回答稳定性和业务一致性

任务：

- 补充 GIS 知识库
- 增加失败降级逻辑
- 优化建议模板和术语解释
- 补充边界测试和异常测试

验收标准：

- 常见错误可优雅降级
- 业务口径保持稳定
- 输出质量明显优于纯 prompt 直答

---

## 16. 测试计划

### 16.1 API 测试

覆盖以下场景：

- 无 analysis 快照
- 直接执行型问题
- 需要澄清型问题
- 需要风险确认型问题
- 自动执行后成功输出
- 工具超时或失败
- provider 配置缺失

### 16.2 Domain 测试

重点测试：

- `gate` 分流正确性
- `context builder` 裁剪正确性
- `llm tool loop` 只调用白名单工具
- `auditor` 证据和边界校验
- `executor` 工具串联正确性
- `synthesizer` 输出结构稳定性

### 16.3 Frontend 测试

重点测试：

- AI 面板挂载
- 对话、执行轨迹、结果卡片渲染
- 澄清和风险确认交互
- analysis_fingerprint 变化后的会话切换
- 错误提示和降级展示

### 16.4 集成测试

至少覆盖以下问题链路：

- 总结这个区域的商业特征
- 哪里适合补充餐饮或零售
- 为什么这里路网表现差
- 下一步建议做什么分析

---

## 17. V1 范围边界

V1 只做以下能力：

- 当前 analysis 会话内的执行型分析 Agent
- 自动工具链执行
- 结构化结论卡片输出
- 执行轨迹展示
- 轻量工作记忆
- 本地规则知识库

V1 明确不做：

- 跨会话长期记忆
- 多 Agent 并行协作
- 向量数据库检索
- 自动无限循环执行
- 高成本专业导出自动触发
- 泛领域开放式问答

---

## 18. 验收标准

当满足以下条件时，认为 V1 可上线试用：

- 用户能在 `/analysis` 面板内通过 AI 提问
- Agent 能识别问题是否足够明确
- Agent 在明确场景下能自动完成分析能力链
- Agent 只有在关键输入缺失或风险过高时才追问
- 输出带有结构化结论、证据、风险和建议
- 前端能展示执行轨迹和主要中间结果
- 不越过业务解释边界
- 遇到失败时能明确说明原因并优雅降级

---

## 19. 当前默认实现决策

本计划默认采用以下实现决策：

- 入口为 `/analysis` 的右侧 AI 面板
- Agent 定位为“技术执行型分析 Agent”
- 默认直接执行白名单能力链
- 只有必要时才澄清或风险确认
- 会话绑定当前 analysis 上下文
- 输出以执行结果卡片和执行轨迹为主
- 后端采用单 orchestrator 多阶段流水线
- 模型层采用 provider 抽象
- 首个 provider 为 OpenAI-compatible
- 先完成“现有能力工具化”，再让 Agent 去编排调用
- GIS 知识库先用本地文件规则库
- 会话状态先不落库

这些决策作为 V1 的默认规范，后续若做 V2，再评估真正多 Agent 协作、向量检索和持久化记忆。
