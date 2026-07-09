# LLM 工具调用与 ESRI / Business Analyst 分析架构

本文说明当前 `/analysis` 主 Agent 如何让 LLM 调用工具，以及 ESRI / Business Analyst 分析在这套工具体系中的位置。

## 1. 总体结论

当前架构是：

```text
用户问题
-> 主 Agent 构建紧凑上下文
-> LLM 在 ReAct 循环中选择工具
-> 后端执行工具 adapter
-> ToolResult 回传给 LLM
-> LLM 决定继续调工具或进入最终回答
```

ESRI / Business Analyst 不是独立报告引擎，而是其中一个 Agent 工具：

```text
plan_business_analyst_analysis
```

它返回 `business_analyst_skeleton`，用来指导后续该查哪些证据、跳过哪些模型、守住哪些分析边界。

## 2. 工具调用主链路

主 Agent 工具注册入口：

```text
modules/agent/tools.py
```

当前 `get_tool_registry()` 注册的工具来源包括：

```text
foundation tools
business analyst tools
source evidence tools
retrieval tools
scope dataset tools
```

LLM 工具调用链路：

```text
1. get_tool_registry() 生成工具注册表
2. chat_completion_tools(registry) 转成 LLM 可见 tools schema
3. LLM 根据问题和上下文返回 tool call
4. execute_tool_call_step() 调用对应 registered.runner
5. runner 返回 ToolResult
6. ToolResult 被压缩成 observation 回到 LLM
7. 循环继续，直到 LLM 不再调用工具
8. finalizer 基于证据包生成最终回答
```

LLM 初始可见上下文包括：

```text
question
analysis_snapshot_digest
context_digest
artifact_catalog
tool_catalog
tools schema
```

工具结果回传时不会直接塞完整 artifacts，而是传：

```text
tool_name
status
result_summary
result
evidence
warnings
error
artifact_keys
```

## 3. 当前工具总表

当前主 Agent 注册表实际暴露 14 个 primary 工具，全部是只读安全工具。

| 工具 | 分类 | 层级 | 产物 | 作用 |
| --- | --- | --- | --- | --- |
| `read_current_scope` | 基础上下文 | L1 | `scope_polygon`, `isochrone_feature` | 读取当前范围、等时圈、polygon |
| `read_current_results` | 基础上下文 | L1 | 当前 POI/H3/路网/人口/夜光摘要 | 读取当前 snapshot 中已经存在的分析结果 |
| `plan_business_analyst_analysis` | ESRI / BA 分析骨架 | L2 | `business_analyst_skeleton` | 为商业诊断、业态机会、选址、竞品、客群问题生成分析骨架 |
| `list_selected_sources` | 已选来源证据 | L1 | `selected_sources` | 列出本轮已选来源，确认检索边界 |
| `search_selected_source_evidence` | 已选来源证据 | L1 | `selected_source_evidence_nodes` | 在已选文档、网页、图片、资料包、系统来源内搜索 EvidenceNode |
| `read_selected_source_evidence_node` | 已选来源证据 | L1 | `selected_source_evidence_nodes` | 按 node_id 读取已选来源证据节点 |
| `search_analysis_context` | 当前分析上下文检索 | L1 | `analysis_context_evidence_nodes` | 搜索当前会话结构化分析上下文 |
| `read_analysis_evidence_node` | 当前分析上下文检索 | L1 | `analysis_context_evidence_node` | 按 node_id 读取分析 EvidenceNode |
| `search_report_context` | 报告上下文检索 | L1 | `report_context_evidence_nodes` | 搜索当前会话已生成报告上下文 |
| `read_report_evidence_node` | 报告上下文检索 | L1 | `report_context_evidence_node` | 按 node_id 读取报告 EvidenceNode |
| `list_scope_datasets` | 当前范围数据源 | L1 | `scope_datasets` | 列出当前 history_id 下可查询的 POI、H3、人口、夜光、路网数据源 |
| `query_scope_dataset` | 当前范围数据源 | L1 | `scope_dataset_evidence_nodes` | 分页读取当前范围明细并转成 EvidenceNode |
| `aggregate_scope_dataset` | 当前范围数据源 | L1 | `scope_dataset_aggregate` | 对当前范围数据做受控聚合 |
| `read_scope_record` | 当前范围数据源 | L1 | `scope_dataset_evidence_nodes` | 按 record_id 读取单条 POI、cell、H3 或路网 feature |

## 4. 工具分类说明

### 4.1 基础上下文工具

工具：

```text
read_current_scope
read_current_results
```

用途：

- 给 LLM 读取当前范围和已有分析摘要。
- 适合回答“当前范围是什么”“现在已经有哪些结果”“这些结果摘要是什么”。
- 也是 ESRI / BA 模型路径里 `TradeAreaModel` 和 `MarketPotentialModel` 常用的基础证据。

边界：

- 只读当前 snapshot。
- 不重新计算分析。
- 不返回完整大 payload。

### 4.2 已选来源证据工具

工具：

```text
list_selected_sources
search_selected_source_evidence
read_selected_source_evidence_node
```

用途：

- 只在用户本轮已选来源内检索。
- 覆盖文档、网页、图片、空间资料包、当前项目成果包和系统来源。
- 用于回答“这个来源说明什么”“这份材料能支撑哪些判断”“某页 PPT 应该引用哪条证据”。

推荐调用顺序：

```text
list_selected_sources
-> search_selected_source_evidence
-> read_selected_source_evidence_node
```

边界：

- 不能访问未选来源。
- 不能代表全库。
- 不能把来源摘要当作完整事实，必要时必须 read 节点。

### 4.3 当前分析 / 报告上下文检索工具

工具：

```text
search_analysis_context
read_analysis_evidence_node
search_report_context
read_report_evidence_node
```

用途：

- `analysis_context` 面向当前会话的结构化分析上下文。
- `report_context` 面向已经生成过的报告结论和报告证据。
- 适合追问“刚才这个结论依据是什么”“报告里某段怎么来的”“已有分析里有没有某个现象”。

推荐调用顺序：

```text
search_analysis_context
-> read_analysis_evidence_node

search_report_context
-> read_report_evidence_node
```

边界：

- 这是运行时上下文检索，不等同于持久来源索引。
- 不能替代当前范围数据源工具查询明细。

### 4.4 当前范围数据源工具

工具：

```text
list_scope_datasets
query_scope_dataset
aggregate_scope_dataset
read_scope_record
```

用途：

- 查询当前 `history_id`、当前空间范围、当前年份或数据版本下的明细数据。
- 覆盖 POI、H3、人口、夜光、路网。
- 适合 TopN、分类统计、局部差异、代表对象、单条记录核验。

推荐调用顺序：

```text
list_scope_datasets
-> aggregate_scope_dataset 或 query_scope_dataset
-> read_scope_record
```

典型问题：

- 当前范围餐饮 POI 有多少？
- 夜光最高的 cell 是哪些？
- 哪些路段 choice / integration 较高？
- 某个 H3 cell 具体是什么情况？

边界：

- 不是 SQL 全库查询。
- 只能查当前范围数据源。
- 年份缺失或数据版本不一致时，回答必须说明限制。

## 5. ESRI / Business Analyst 工具节

### 5.1 它在工具体系中的位置

ESRI / Business Analyst 当前对应工具：

```text
plan_business_analyst_analysis
```

工具属性：

```text
category = information
layer = L2
ui_tier = capability
data_domain = commerce
capability_type = interpret
scene_type = facility_gap
readonly = true
cost_level = safe
risk_level = safe
llm_exposure = primary
produces = business_analyst_skeleton
```

它是一个**分析骨架规划工具**，不是报告生成工具。

### 5.2 输入

工具输入：

```text
question
mode
question_type
```

`mode` 可选：

```text
auto
area_diagnosis
opportunity_screening
site_selection
competition
customer_fit
```

adapter 会从当前 `AnalysisSnapshot` 提取可用证据层：

```text
scope
poi
h3
population
nightlight
road
frontend_analysis
```

这些会组成 `BusinessAnalystInput`，再交给 `modules/business_analyst/planner.py`。

### 5.3 输出

输出产物：

```text
business_analyst_skeleton
```

核心字段：

```text
status
reason
selected_skill
candidate_skills
model_graph
recommended_path
path_relations
optional_branches
model_tool_map
skip_conditions
guardrails
missing_evidence_defaults
answer_guidance
```

注意：

- 不输出 `business_analyst_report`。
- 不输出固定报告章节。
- 不直接输出最终商业结论。
- 它只告诉主 Agent：应该按什么商业分析路径查证据和组织判断。

### 5.4 ESRI / BA 模型图

当前模型图：

| 模型 | 角色 | 作用 |
| --- | --- | --- |
| `TradeAreaModel` | boundary | 统一分析范围、商圈口径、空间边界 |
| `MarketPotentialModel` | demand | 用人口、夜光、POI、路网等 proxy 判断需求和活力基础 |
| `RetailGapModel` | supply_gap | 判断供给缺口、零售空白、空间错配 |
| `OpportunityCategoryScreeningModel` | opportunity_screening | 筛选可引入业态或商业方向 |
| `HuffGravityModel` | competition | 有候选点和竞品证据时，做相对吸引力 proxy |
| `CustomerProfileFitModel` | customer_fit | 判断人群和活动 proxy 是否匹配目标客群 |
| `SiteSuitabilityModel` | decision | 综合范围、需求、缺口、竞争、客群、可达性做适宜性判断 |

模型关系简化为：

```text
TradeAreaModel
-> MarketPotentialModel
-> RetailGapModel
-> OpportunityCategoryScreeningModel

RetailGapModel
-> SiteSuitabilityModel

HuffGravityModel / CustomerProfileFitModel
-> SiteSuitabilityModel
```

### 5.5 ESRI / BA 模型如何指导工具调用

`model_tool_map` 把 BA 模型映射到 Agent 工具：

| BA 模型 | required tools | optional tools |
| --- | --- | --- |
| `TradeAreaModel` | `read_current_results` | `read_current_scope` |
| `MarketPotentialModel` | `read_current_results` | `aggregate_scope_dataset`, `search_analysis_context` |
| `RetailGapModel` | `query_scope_dataset` | `aggregate_scope_dataset` |
| `OpportunityCategoryScreeningModel` | `read_current_results` | `aggregate_scope_dataset`, `query_scope_dataset`, `search_analysis_context` |
| `HuffGravityModel` | `query_scope_dataset` | `read_scope_record` |
| `CustomerProfileFitModel` | `read_current_results` | `aggregate_scope_dataset`, `search_analysis_context` |
| `SiteSuitabilityModel` | `query_scope_dataset` | `read_scope_record` |

关键点：

- 当前不是代码强制按模型链自动执行全部工具。
- `business_analyst_skeleton` 会进入 `artifact_catalog` 和 finalizer evidence payload。
- LLM 在 ReAct loop 中读取 `recommended_path`、`model_tool_map`、`skip_conditions` 和 `guardrails`。
- LLM 根据当前问题和证据缺口决定下一步调用哪些工具。

示例：

```text
用户问：这个区域适合引入什么业态？

1. LLM 调 plan_business_analyst_analysis
2. 返回 ba.open_opportunity_screening
3. recommended_path:
   TradeAreaModel -> MarketPotentialModel -> RetailGapModel -> OpportunityCategoryScreeningModel
4. LLM 调 read_current_results 获取当前摘要
5. LLM 调 aggregate_scope_dataset 对 POI 按 category 聚合
6. 必要时调 query_scope_dataset 查代表 POI 或缺口样本
7. Finalizer 结合 skeleton 和证据生成回答
```

### 5.6 Guardrails

BA 工具会把这些边界交给 LLM：

```text
population_not_spending_power
nightlight_not_sales
poi_not_business_performance
huff_proxy_not_market_share
customer_profile_requires_customer_data
no_revenue_without_source
recommendation_requires_validation
```

含义：

- 人口不是消费力。
- 夜光不是销售额。
- POI 数量不是经营表现。
- Huff proxy 不是真实市场份额。
- 没有真实客户数据时，不能声称客户画像。
- 没有来源时，不能输出营收、客流、销售预测。
- 推荐结论必须保留验证动作。

## 6. 快速模式与深度模式里的工具调用差异

### 6.1 快速模式

快速模式主要走：

```text
answer_quick_analysis
-> run_source_qa_loop
-> 已选来源证据工具 / 当前范围数据源工具
```

特点：

- 优先围绕已选来源和当前范围数据源回答。
- 工具调用少。
- 通常不完整展开 ESRI / BA skeleton。

### 6.2 深度模式

深度模式主要走：

```text
主 Agent turn
-> ReAct Tool Loop
-> plan_business_analyst_analysis 可被 LLM 主动调用
-> 根据 skeleton 继续调用其他证据工具
-> Auditor / Finalizer 综合
```

特点：

- 更适合商业诊断、业态机会、选址、竞品、客群问题。
- 可以先拿 BA skeleton，再查当前范围数据和证据节点。
- deep 不是固定报告模式，而是更强的证据补齐和边界校验循环。

## 7. 对外解释口径

可以这样解释：

```text
LLM 不是直接读取数据库或全量原始数据，而是在 Agent 提供的工具目录中选择只读工具。
基础工具读取当前范围和已有结果；
来源工具检索已选材料；
范围数据工具查询当前 history_id 下的 POI、H3、人口、夜光和路网明细；
ESRI / Business Analyst 工具则提供商业分析模型路径和 guardrails。
LLM 根据这些工具结果逐步补证据，最后生成有来源、有边界的分析结论。
```

一句话：

```text
ESRI 分析属于 LLM 工具调用体系中的 L2 商业分析骨架工具；它不直接生成报告，而是指导主 Agent 该按什么模型路径调用其他工具和组织证据。
```
