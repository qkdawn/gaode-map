# Harness-first 城市空间 Agent 改造记录

最后核对日期：2026-08-20

## 1. 记录范围

本文完整记录城市更新空间策略工作流从“项目自建 Agent 运行时”收敛为“Codex Harness 承担通用 Agent 能力、项目只实现城市空间领域增量”的改造过程，包括：

- 问题判断与目标范式；
- 提示词和领域输出契约；
- Harness、MCP、n8n 与领域模块的责任边界；
- 删除、新增和修改的实现；
- 失败恢复和长任务运行处理；
- 正式 Run、报告产物和验证结果；
- 当前报告的实际价值与剩余限制。

本文接续 `06_engineering_decision_log.md`。前文 1-10 节描述旧动态证据路由架构，11 节描述第一次提示词收敛；本文描述 2026-08-20 已完成并实际运行的最终实现。旧记录保留用于解释演进过程，不再代表当前参考架构。

## 2. 最终目标与核心判断

空间分析任务采用以下决策链：

```text
现状结构
→ 未来角色
→ 使用者与场景
→ 空间机制
→ 产品与运营
→ 首期行动
→ 后续分期
```

统一核心提示为：

> 基于已有项目材料和空间数据完成用户任务，给出明确判断及行动建议。不要虚构信息；无法完成时直接说明原因。

本轮确认的关键设计判断如下：

1. “不要虚构”约束现状事实，不取消面向未来的策略推演。
2. 目标客群是项目主动选择服务的人，不要求空间数据先证明其必然到访。
3. 未来场景是规划提案，空间行动是促成变化的手段。
4. 产权、保护、结构、消防和住宅共存等刚性条件，应转化为开放等级、分区分时、独立流线和可逆改造，不应扩写为报告主体。
5. 工具执行失败是运行失败，不是“证据不足”的正式分析结论。
6. 报告只面向政府、甲方、设计和运营读者表达判断、依据、行动及预期改变，不描述 Agent、工具、工作流或执行过程。

## 3. 最终架构边界

### 3.1 旧链路与当前链路

旧链路：

```text
n8n
→ 项目自建 Responses/relay 请求
→ 项目解析模型消息和 function call
→ n8n 证据路由修正回环
→ HTTP 手动 MCP 工具桥
→ 项目拼接工具结果、重试并再次调用模型
→ memo、综合、章节和报告
```

当前链路：

```text
用户/API
→ n8n 排队并读取已完成领域状态
→ FastAPI Harness 领域入口
→ Codex Harness 原生执行
→ spatial-project MCP 读取项目材料、空间数据或已完成决策
→ Harness 按领域 schema 返回结果
→ n8n 持久化领域结果并继续下一领域阶段
→ 图件渲染、Markdown/DOCX 装配和交付
```

其中 relay、Responses 回环、n8n 工具路由修正、手动 MCP HTTP 桥、模型消息解析和项目级模型重试均已删除。

### 3.2 Codex Harness 负责

- 模型消息组织与上下文；
- 原生 MCP 工具调用；
- 调用 ID 和内部消息；
- 结构化输出执行；
- 模型侧解析、重试和内部分析过程；
- 当前 Codex 配置中的模型选择与运行参数。

项目不再复制上述能力，也不设置 `max_output_tokens` 等项目级 token 限制。

### 3.3 项目负责

- 七个城市空间决策问题及其依赖顺序；
- 项目材料、空间数据和可用 MCP 工具；
- `decision_memo`、`report_blueprint`、`report_section` 和 `visual_design` 领域 schema；
- n8n 任务触发、排队、租约、恢复和领域结果持久化；
- 图件渲染、Markdown 装配、DOCX 导出和交付；
- 工具或 Harness 调用失败时记录真实运行失败原因。

### 3.4 综合阶段的数据入口

综合阶段不再由 n8n 串接七份完整 memo。Codex Harness 只接收 `run_id` 和项目问题，并通过原生 MCP 工具：

```text
read_strategy_decisions(run_id)
```

读取七个已完成的领域决策结果。数据库表结构、内部存储字段、n8n 节点编号、原始消息和 Harness 中间 JSON 不暴露给综合提示词，也不进入正式报告；项目角色、行动、位置、依据以及会改变方案选择的具名 POI、道路、路径、建筑和地点等领域字段正常返回。

### 3.5 运行术语

| 术语 | 本文含义 |
| --- | --- |
| 领域 Run | 一次可恢复的完整城市空间分析任务，对应 `analysis_runs.id`；首次 Harness-first 基线 Run 为 `7b8ab959-c0e2-4d29-8168-9688cb4989bf`，具名空间信息恢复后的验收 Run 为 `8e759fd9-9ab5-450a-b806-e90d0ed0b27e` |
| n8n execution | n8n 对提交、状态查询或后台消费工作流的一次执行；同一个领域 Run 在失败恢复后可以对应多个 execution |
| Harness invocation | 分析单元、综合、章节或图件阶段的一次 Codex Harness 子进程调用；一个 n8n execution 可以包含一个或多个 invocation |

## 4. 删除的自建 Agent 运行时

以下实现已经删除：

| 删除项 | 原职责 | 删除原因 |
| --- | --- | --- |
| `n8n/workflow-components/responses.json` | 自建 Responses 请求、响应解析和消息回环 | 与 Codex Harness 重复 |
| `n8n/credentials/codex-relay.json` | Codex relay 凭据 | 不再通过项目 relay 调模型 |
| `modules/spatial_strategy/mcp_agent.py` | n8n 手动 MCP 工具桥 | 改用 Harness 原生 MCP |
| `/spatial-strategy/agent-tools/call` | 手动工具调用 HTTP 入口 | 不再由 n8n 解释和转发工具协议 |
| `SpatialStrategyAgentToolRequest` | 手动工具桥请求 schema | 已无消费者 |
| `tests/domain/test_spatial_strategy_mcp_agent.py` | 旧 MCP 工具桥测试 | 对应实现已删除 |

同时从 bootstrap 中删除 relay URL、API key、模型占位符和 `/responses` 健康检查。没有保留兼容分支、旧字段双读或备用 relay 路径。

## 5. 新增的领域实现

### 5.1 Harness 领域入口

新增 `modules/spatial_strategy/harness_synthesis.py`，提供四个领域函数：

```text
analyze_strategy_unit
synthesize_strategy_blueprint
write_strategy_section
design_strategy_visuals
```

函数调用 Codex Harness，向其提供领域任务、允许的 MCP 工具和对应输出 schema。实现不固定 `--model`，使用当前 Codex 配置；不传 token 上限。

长任务输出目录固定为：

```text
runtime/codex-harness/run-*/
```

`runtime/codex-harness` 是项目内固定根目录；每次 Harness invocation 在其中创建一个 `run-*` 临时子目录，只承载该次调用的最终结构化输出文件。调用结束后由 Python 临时目录机制清理子目录，不作为 Agent 内部状态持久化。

### 5.2 决策读取工具

新增 `modules/spatial_strategy/strategy_decisions.py`，并在 `modules/spatial_projects/mcp_server.py` 中注册 `read_strategy_decisions`。该工具按 `run_id` 返回已经持久化的领域决策，不返回 n8n 节点、工具调用、模型消息或执行轨迹。

### 5.3 结构化输出 schema

新增：

- `modules/spatial_strategy/decision_memo.schema.json`
- `modules/spatial_strategy/report_blueprint.schema.json`
- `modules/spatial_strategy/report_section.schema.json`
- `modules/spatial_strategy/visual_design.schema.json`

行动项以“行动、服务对象、位置、优先级、预期改变”为中心。综合蓝图增加 `future_state` 和 `change_mechanisms`，使综合阶段必须说明项目未来形成什么状态，以及空间行动如何把现状推向该状态。

决策单元另保留一个领域字段 `named_entities`：

```json
{
  "name": "潘家坪路",
  "entity_type": "road",
  "relationship": "项目首期主要到达道路",
  "fact": "连接原大门和周边路网",
  "record_ref": "内部记录引用"
}
```

`record_ref` 只存在于单元级领域结果，用于来源回溯；综合蓝图只保留 `name`、`entity_type`、`relationship` 和 `fact`，不把内部记录 ID 传给章节作者或正式报告。这样既保留真实空间对象，又不恢复内部 memo、工具消息或 Harness 状态。

### 5.4 报告和图件领域模块

更新 `schemas.py`、`reporting.py`、`reader_result.py`、`visuals.py` 和 `docx_export.py`：

- 报告固定组织为五个面向决策者的章节，而不是复述七个分析单元；
- 章节写作者只接收综合方案中筛选后的本章判断、现状依据、未来目标、行动和预期改变；
- 正文不接收完整 memo、内部推理、工具结果或决策单元编号；
- 图件计划只允许引用实际提供的 `dataset_id`；
- `road_nodes` 从图件可用数据集中排除，避免渲染全部道路节点；
- DOCX 支持中文字体、图件、标题、编号、表格跨页、重复表头和页码；
- DOCX `settings.xml` 为 `<w:zoom>` 补充必填 `w:percent="100"`，通过 OOXML 校验。

## 6. n8n 工作流改造

### 6.1 当前工作流规模

正式生成工作流现有 68 个节点，其中只有四个 Harness 调用节点：

- 调用 Codex Harness 分析单元；
- 调用 Codex Harness 综合方案；
- 调用 Codex Harness 撰写章节；
- 调用 Codex Harness 设计图件。

n8n 不再包含证据路由模型、function-call 回环、工具请求准备、工具结果拼接、响应解析或模型重试逻辑。

### 6.2 七个领域决策单元

当前研究链收敛为七个明确问题：

| 单元 | 决策目标 |
| --- | --- |
| `current_structure` | 判断应延续和改变的现状结构 |
| `future_role` | 选择项目唯一主导角色 |
| `users_and_scenarios` | 选择优先服务对象和未来使用方式 |
| `spatial_mechanisms` | 确定改变行为的空间机制 |
| `product_and_operation` | 确定产品和运营组合 |
| `first_phase_actions` | 确定最小完整首期项目包 |
| `phasing` | 按依赖关系安排后续分期 |

“证据是否充分”不再作为正式分析单元或报告第一章。

### 6.3 恢复语义

恢复链路现在覆盖三个层级：

1. 已完成决策单元通过 `analysis_step_outputs` 和 `decision_state.steps` 直接复用；
2. 已完成 `report_blueprint` 直接复用，不再重新综合；
3. 已完成报告章节按 `section_id` 复用，只生成缺失章节。

七个单元、综合方案和五个章节都完成时，恢复执行直接进入图件设计与最终报告装配。网络抖动、后端重启或图件失败不会导致上游全部重算。

### 6.4 失败语义

- Harness 或工具 HTTP 调用失败时，工作流进入 `failed`；
- 错误字段记录实际运行原因；
- 失败原因不写入报告正文；
- n8n 成功执行不保存完整执行数据，失败执行保留七天用于故障定位；
- 不设置模型 token 限制，也不以正常长耗时判断任务失败。

## 7. 提示词与报告输入收敛

### 7.1 删除的要求

研究、决策、综合和写作提示词中删除：

- “事实—代理—未知”分层；
- 完整披露证据缺口；
- 逐字继承内部 memo；
- 工具过程、状态码和调用说明；
- 内部状态治理；
- 重复自检清单；
- 继续投入条件作为所有行动的统一字段；
- 内部词黑名单和二次审计 Agent。

### 7.2 保留的内容

- 用户任务和项目问题；
- 项目材料与空间数据范围；
- 当前决策单元的领域目标；
- 必要的结构化输出 schema；
- 不虚构事实、无法完成时说明原因。

### 7.3 正式正文契约

正式报告只要求输出：

```text
判断
→ 现状依据
→ 未来目标
→ 空间或产品行动
→ 预期改变
```

最终正文的交付验收脚本检查以下词汇出现次数均为 0：

```text
Agent、Harness、工具、工作流、JSON、状态字段、决策单元、memo、事实—代理—未知
```

这只是对本次最终产物的验收统计，不是提示词黑名单、运行门禁或新增审计层；生成过程中不会因为出现这些词而重试、改写或拒绝报告。

## 8. 关键故障与修复时间线

### 8.1 证据路由修正死循环

旧执行曾出现 287 次“请求证据路由模型”，实际工具执行只有 1 次。根因包括宽松 schema、空间参数只做后置校验、n8n 回环读取历史 item、纠正计数丢失以及路由调用不计入预算。

该问题最初通过 strict schema、纠正次数和路由轮次上限止血。最终 Harness-first 改造删除了整套项目自建路由回环，因此这些项目级修正、预算和解析逻辑也不再存在。

### 8.2 长任务输出目录被系统清理

综合调用曾正常运行约 16 分钟，但 Windows 系统临时目录在跨午夜期间被清理，`--output-last-message` 无法写入结果。修复后使用项目运行目录 `runtime/codex-harness`，长任务不再依赖系统临时目录生命周期。

### 8.3 图件计划选择 `road_nodes`

正式 Run 完成七个单元、综合方案和五个章节后，图件设计选择 `road_nodes`，领域校验以 `visual plan must not render all road nodes` 拒绝。修复包括：

- 从图件 Agent 的 `available_datasets` 排除 `road_nodes`；
- 提示词明确只能使用可用数据列表中的 `dataset_id`；
- 增加生成工作流契约测试。

### 8.4 后端重启产生真实网络失败

部署图件修复时，旧后端仍占用 8000，新后端启动失败。终止旧后端后，正在执行的旧请求以 `socket hang up` 记录为运行失败。该错误未进入报告；下一次恢复从报告章节完成状态继续。

### 8.5 恢复执行仍重复综合和章节

后端恢复后的下一次执行暴露出：七个决策单元能够复用，但报告阶段仍无条件重新调用综合，并在蓝图校验后清空 `report_sections`。该次 n8n execution 被人工终止并记为失败，没有覆盖数据库中已有综合方案和五个章节。这里的重复是修复前的 Harness invocation，不是新建了另一个领域 Run。

修复后增加“综合方案已完成？”和“报告章节已完成？”两个领域恢复分支；部分章节存在时只展开缺失 `section_id`。这两个分支只判断已持久化的领域结果，不读取 Harness 消息或执行轨迹。

### 8.6 DOCX 标准校验

Word 文件能够被 LibreOffice 正常渲染，但严格校验发现 `<w:zoom>` 缺少 `w:percent`。修复导出器并补测试后重新生成 DOCX，`validate.py -X utf8` 全部通过。校验脚本在中文 Windows 默认 GBK 下的解码错误通过显式 UTF-8 模式规避，不属于文档内容错误。

## 9. 正式运行与产物

### 9.1 Run 信息

- Run ID：`7b8ab959-c0e2-4d29-8168-9688cb4989bf`
- 最终状态：`completed`
- 决策单元：7 个，全部完成
- 综合方案：1 份
- 正式章节：5 个
- 图件：4 张
- Markdown 正文：9,813 个数据库字符
- DOCX：11 页

本次正式 Run 最初从项目材料和空间数据开始执行。中途图件和服务重启失败后，按新的恢复语义复用七个决策单元、综合方案和五个章节，只继续图件与最终文档，没有重复计算已经完成的领域结果。

上句“没有重复计算”专指恢复分支修复后的最终 execution `10927`。修复前曾启动一次不必要的综合 invocation，发现后即终止；它没有替换已持久化领域结果。

### 9.2 正式 Run 恢复时间线

| 范围 | n8n execution | 结果 | 当时已持久化 | 后续处理 |
| --- | --- | --- | --- | --- |
| 初始领域 Run | 初始 execution 未作为最终索引保留 | 图件计划错误选择 `road_nodes`，Run 失败 | 7 个决策、1 份蓝图、5 个章节 | 修复图件可用数据列表 |
| 第一次恢复 | `10916` | 后端切换期间请求以 `socket hang up` 失败 | 7 个决策、1 份蓝图、5 个章节保持不变 | 启动最新后端 |
| 第二次恢复 | `10920` | 暴露报告阶段仍会重复综合；终止该 invocation 并记为失败 | 已有蓝图和章节未被覆盖 | 增加蓝图和章节恢复分支 |
| 最终恢复 | `10927` | 直接进入图件设计、渲染和报告装配，Run 完成 | 复用全部上游领域结果 | 生成 4 张图、Markdown 和 DOCX |

提交和状态查询还会形成短小的 n8n execution，不属于后台领域计算，未列入本表。

### 9.3 最终主要结论

- 推荐定位：以原址记忆为核心的公共文化客厅；
- 首要使用者：周边步行可达居民；
- 兼容对象：一般城市访客、原址记忆群体、文化社群和机构；
- 空间机制：现大门、约 120 米公共主轴、院落梯度、园林节点、建筑分级开放、住宅安静边界；
- 产品结构：原址记忆核心内容、日常共享、小型文化活动、基本公共服务、克制型轻量消费；
- 首期项目包：一个日常主入口、约 120 米主路径、一个示范院落、一个安静园林节点、住宅静界、基础导览与公共服务、统一运营和首发原址内容。

### 9.4 产物路径

```text
runtime/client-decision-spatial-strategy/7b8ab959-c0e2-4d29-8168-9688cb4989bf/
├── spatial-strategy-report.md
├── spatial-strategy-report.docx
└── visuals/
    ├── visual-01-map-24dbf00c29.png
    ├── visual-02-map-79bda77860.png
    ├── visual-03-chart-9ea258fac6.png
    └── visual-04-chart-1279867ed2.png
```

检查过程中另生成 `spatial-strategy-report.pdf` 和逐页 JPEG；它们是运行时验证产物，不进入 Git。

### 9.5 具名空间信息恢复后的验收 Run

发现基线报告中的真实 POI、道路、路径和建筑名称被过度收敛后，新增单一 `named_entities` 领域链路，并从头执行一轮不复用旧状态的验收 Run：

- Run ID：`8e759fd9-9ab5-450a-b806-e90d0ed0b27e`
- 最终状态：`completed`
- 七个决策单元具名实体数：`12、13、10、16、14、10、10`
- 综合蓝图筛选后具名实体：16 个
- 图件：4 张，其中区域道路与设施图直接标注具名道路并使用编号 POI 锚点
- Markdown：26,520 字节
- DOCX：1,160,065 字节，9 页

最新正式报告明确使用了潘家坪路、黄兴北路、开福寺路、华夏路、开福寺地铁站、古开福寺、湘雅路街道综合文化站以及礼堂、县委楼、宣教楼、档案楼等真实名称，并给出约 634 米、690 米、883 米和原大门至县委楼约 120 米等具体空间关系。

最新产物路径：

```text
runtime/client-decision-spatial-strategy/8e759fd9-9ab5-450a-b806-e90d0ed0b27e/
├── spatial-strategy-report.md
├── spatial-strategy-report.docx
└── visuals/
    ├── visual-01-map-f45c6c0f29.png
    ├── visual-02-chart-d113c94901.png
    ├── visual-03-chart-d86b1b7f09.png
    └── visual-04-map-591d9ada25.png
```

## 10. 验证结果

### 10.1 自动化测试

最终相关测试集包含：

- n8n 正式工作流契约；
- 决策单元和报告阶段恢复；
- Harness 领域适配；
- `read_strategy_decisions`；
- 项目数据读取；
- API；
- 报告装配和 DOCX；
- 图件设计与渲染。

具名空间信息恢复后的最终结果：

```text
67 passed
```

复跑命令：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/domain/test_n8n_rag_workflows.py `
  tests/domain/test_decision_step_dynamic_stop.py `
  tests/domain/test_spatial_strategy_harness_synthesis.py `
  tests/domain/test_spatial_strategy_decisions.py `
  tests/domain/test_spatial_strategy_project_data.py `
  tests/domain/test_spatial_strategy_reader_result.py `
  tests/domain/test_spatial_strategy_reporting.py `
  tests/domain/test_spatial_strategy_visuals.py `
  tests/api/test_spatial_strategy_api.py -q
```

`git diff --check` 通过，仅有工作区既有行尾转换警告。

### 10.2 文档检查

- 基线 DOCX 共 11 页；具名空间信息恢复后的最新 DOCX 共 9 页；
- 中文无乱码；
- 四张图件均非空白；
- 标题、正文和表格无溢出；
- 跨页表格重复表头正常；
- 页码正常；
- OOXML 完整校验通过；
- 数据库 `asset_manifest.sha256` 已与修复后 DOCX 文件同步。

## 11. 当前报告的实际价值

与旧报告相比，新报告已经能够支持以下前期决策：

1. 项目不应建设为商业主导综合体，而应成为公共文化客厅；
2. 首要使用者是周边居民，城市访客和文化机构作为扩展对象；
3. 工作日日常使用、周末轻量文化活动和低扰动夜间使用应分时组织；
4. 首期不依赖全部建筑开放，可由“门—轴—院—园”形成独立闭环；
5. 入口、主路径、院落、园林和住宅界面的空间关系已有明确策略；
6. 产品、运营主体、首期建设动作和后续分期已形成同一条行动链。
7. 最新报告已把区域方向还原为具名道路、设施、建筑、路径和距离，可直接指向潘家坪路侧原大门、原大门至县委楼约 120 米主路径、宣教楼与档案楼围合庭院及华夏路侧第二入口等项目包。

务实评分：

| 决策层级 | 当前可用性 |
| --- | --- |
| 区域角色与项目定位 | 8/10 |
| 使用者与未来场景 | 7/10 |
| 空间组织策略 | 7/10 |
| 产品与运营组合 | 6/10 |
| 首期实施指导 | 7/10 |
| 建筑级设计指导 | 4/10 |
| 投资与财务决策 | 2/10 |
| 正式交付可用性 | 7/10 |

## 12. 当前报告的分析边界

### 12.1 报告内容限制

- “条件”出现 37 次，“核验”出现 19 次，语言仍偏保守；
- “不能证明”出现 4 次，虽然不再支配全文，但仍可进一步压缩；
- 建筑级策略只使用当前材料已经给出的具名对象和空间关系，不把未见于材料的属性补成精确配置；
- 投入与运营只比较相对投入强弱、实施难度、运营复杂度和资金承担方式，不生成精确投资额、收益、ROI 或回收期；
- “重点年龄人口空间分布”实际为年龄结构汇总，图名应改为“重点年龄人口结构”；
- 首期项目包表格信息密度较高，汇报版可压缩为一页项目包和一页实施路线。

### 12.2 工作流处理方式

分析不设置“补齐资料后再决策”的默认支线，也不输出缺失输入清单。每个单元直接使用当前项目材料和空间数据完成选择：有可复核数字时做简单计算，其余保持定性比较。只有用户本身要求一项现有材料无法完成的精确计算时，才直接说明无法完成的原因。

## 13. 文件级变更索引

下表是本轮改造的唯一文件清单。未列入的工作区修改不归本文认领。

| 路径 | 状态 | 契约变化 |
| --- | --- | --- |
| `modules/spatial_strategy/harness_synthesis.py` | 新增 | 四个 Harness 领域入口、schema 输出和项目内临时输出根目录 |
| `modules/spatial_strategy/strategy_decisions.py` | 新增 | 按 `run_id` 读取已完成领域决策 |
| `modules/spatial_strategy/decision_memo.schema.json` | 新增 | 单元判断、具名空间实体和行动 schema |
| `modules/spatial_strategy/report_blueprint.schema.json` | 新增 | 具名空间实体、未来状态、改变机制、行动计划和五章蓝图 schema |
| `modules/spatial_strategy/report_section.schema.json` | 新增 | 单一正式章节 schema |
| `modules/spatial_strategy/visual_design.schema.json` | 新增 | 三至五张图件设计 schema |
| `modules/spatial_projects/mcp_server.py` | 修改 | 注册 `read_strategy_decisions` |
| `modules/spatial_strategy/__init__.py` | 修改 | 导出新的领域能力 |
| `modules/spatial_strategy/schemas.py` | 修改 | 收敛未来策略和行动结构；删除 `SpatialStrategyAgentToolRequest` |
| `modules/spatial_strategy/reporting.py` | 修改 | 按综合方案和五章装配正式报告 |
| `modules/spatial_strategy/visuals.py` | 修改 | 图件领域校验、拒绝渲染全部 `road_nodes`，并在地图标注具名道路和编号 POI |
| `modules/spatial_strategy/docx_export.py` | 修改 | 中文报告版式、表格、图件、页码和 OOXML 有效性 |
| `modules/spatial_strategy/reader_result.py` | 修改 | 更新对外运行状态表达 |
| `modules/spatial_strategy/mcp_agent.py` | 删除 | 删除 n8n 手动 MCP 工具桥实现 |
| `router/domains/spatial_strategy.py` | 修改 | 新增四个 Harness 领域 HTTP 入口；删除 `/spatial-strategy/agent-tools/call` |
| `n8n/workflow-generators/urban-renewal-agent.workflow.mjs` | 修改 | 重写为 Harness-first 的 68 节点正式工作流 |
| `n8n/workflow-components/decision-step.json` | 修改 | 只保留领域单元校验、复用、执行和保存 |
| `n8n/workflow-components/urban-renewal-component-source.mjs` | 修改 | 更新图件、报告和失败语义 |
| `n8n/workflow-components/agent-submit.json` | 修改 | 恢复时保留已完成领域状态 |
| `n8n/workflow-components/responses.json` | 删除 | 删除自建 Responses 请求和解析回环 |
| `n8n/credentials/codex-relay.json` | 删除 | 删除 relay 凭据 |
| `n8n/bootstrap/render-bootstrap.mjs` | 修改 | 删除 relay 占位符 |
| `scripts/n8n_bootstrap.ps1` | 修改 | 删除 relay 配置和模型健康检查 |
| `.env.example`、`core/config.py`、`docker-compose.yml` | 修改 | 删除 relay 依赖并保留当前服务配置 |
| `tests/domain/test_n8n_rag_workflows.py` | 修改 | 正式工作流、提示词、Harness 和恢复契约 |
| `tests/domain/test_decision_step_dynamic_stop.py` | 修改 | 单元、蓝图和章节恢复契约 |
| `tests/domain/test_spatial_strategy_harness_synthesis.py` | 新增 | Harness 适配测试 |
| `tests/domain/test_spatial_strategy_decisions.py` | 新增 | 综合决策读取测试 |
| `tests/domain/test_spatial_strategy_reporting.py` | 修改 | 报告和 DOCX 测试 |
| `tests/api/test_spatial_strategy_api.py` | 修改 | Harness 领域 API 测试 |
| `tests/domain/test_spatial_strategy_mcp_agent.py` | 删除 | 随旧工具桥删除 |
| `pyproject.toml`、`uv.lock` | 修改 | 锁定 DOCX 导出依赖 |

## 14. 具名空间信息缺失的根因与修复

### 14.1 根因

前一轮精简正确删除了完整内部 memo、原始工具结果和运行时 JSON，但同时把具名空间对象误判为内部实现细节。决策单元虽然能够从项目材料和空间数据中读到真实 POI、道路、路径、建筑、距离和指标，旧的收敛后 `decision_memo` schema 却没有字段承载它们。综合阶段只通过 `read_strategy_decisions(run_id)` 读取已持久化领域结果，因此无法重新取得已在上游丢失的名称，只能生成“北侧”“周边设施”“主要入口”等泛化表达。报告作者和图件模块继续消费综合蓝图，缺失随链路放大。

因此，问题不在原始数据、不在 Harness 检索能力，也不应通过重新传入七份完整 memo 解决；真正的问题是领域契约裁剪过度。

### 14.2 修复链路

修复只增加一个有明确消费者的领域字段，并贯通以下真实消费者：

```text
项目材料与空间数据
→ 单元分析 named_entities
→ 已完成决策领域结果
→ read_strategy_decisions(run_id)
→ 综合蓝图 named_entities
→ 章节写作与图件设计
→ 正式 Markdown / DOCX / 地图
```

单元级对象包含内部 `record_ref` 以支持来源定位；综合时主动去除该字段，正式正文只消费真实名称、对象类型、空间关系和具体事实。没有恢复工具名、调用状态、节点编号、原始消息、内部 JSON、重试或解析协议。

图件侧使用同一批真实数据：代表性 POI 采用编号锚点，右侧列出名称和类型；具名道路直接标在地图上。最新资产清单中，区域道路与设施图保存 7 个具名 POI 和 6 条具名道路，包括幸福桥社区文化长廊、文昌阁社区综合文化服务中心、湖南省文物考古研究所、开福寺文化广场，以及芙蓉中路、潘家坪路、开福寺路、精英路、华夏路和沙湖桥街。

### 14.3 验收边界

最新正式 Markdown 不包含 `record_ref`、数据集内部引用、Agent、Harness、工具、工作流、n8n、JSON、运行状态或决策单元编号。执行错误仍由 Harness 或工作流返回失败，不会被写成空间分析结论。该修复恢复的是城市空间领域事实，不是项目自建 Agent 运行时。

## 15. 最终结论

本轮改造不是更换一个模型接口，而是删除项目自建的通用 Agent 底盘，让 Codex Harness 接管消息、工具、结构化输出和内部运行。项目当前只保留城市空间决策问题、领域 schema、MCP 数据入口、n8n 领域编排、恢复、持久化和报告交付。

正式运行已经证明该链路能够从项目材料和空间数据形成“现状依据—未来目标—空间策略—行动方案”的完整报告，并在图件或网络失败后从已完成领域结果恢复。本轮后续质量提升继续聚焦现有材料的决策推导深度，不以增加额外输入、提示词治理、审计层或自建 Harness 能力作为解法。

## 16. 项目原始材料复核与数据边界修正

### 16.1 复核对象

本轮直接读取历史项目 `15266dd890faa567070befc1` 保存的三份 DOCX 和一份 PDF 原文件，而不是沿用既往报告摘要：

1. 《开福区长沙县政府原址（历史文化古建筑）项目基本情况》；
2. 《长沙县政府原址改造愿景20251027》；
3. 《基于长沙县人民政府原址城市更新项目》；
4. 《长沙县政府原址城市更新项目建筑设计全过程咨询服务建议书（初稿）》。

前三份材料与服务建议书共同给出的项目级信息包括：

- 项目位于开福区潘家坪巷，北近开福寺路、南抵潘家坪路、西临黄兴北路；材料称距开福寺地铁站步行约 700 米；
- 用地内有地上建筑 13 栋，总建筑面积约 20000 平方米，但材料同时注明“具体数据待确认”；
- 8 栋保护对象合计建筑面积约 13071.78 平方米，具名对象为县委楼、民政楼、宣教楼、农水楼、政府宿舍楼、礼堂、档案楼和活动中心；
- 3 栋住宅为私有产权房改房，可靠材料写约 102 户；另一份初步交流材料写 120 户，应以逐户调查为准；
- 另有 2 栋简易仓库，是否纳入更新范围尚未确定；
- 保护建筑普遍存在墙体开裂、屋面渗漏和管线老化，缺少现代水电、排污、消防和无障碍设施；住宅缺少电梯和停车位；部分保护建筑临时办公，其余闲置；
- 大院已有“门—路—院—园”的具体空间线索：原大门至县委楼主路径约 120 米，礼堂以西三处院落东西向约 120 米，宣教楼—档案楼及民政楼—活动中心之间较窄，华夏路一侧可研究居民第二入口，住宅花园应保留居民自主使用；
- 服务建议书提出价值评估、需求挖掘、运营策划、建筑体检、保护修缮、全过程设计、数字孪生、产业导入与运营八类后续工作，并给出 10 至 15 个工作日、30 个工作日、约 28 周、5 年陪伴等服务周期；这些是咨询工作计划，不是已经完成的项目研究或实施结果。

### 16.2 投入与运营材料的解读方式

服务建议书中的投入、运营和收益内容是建议开展的咨询工作，不是已经完成的测算结果。本工作流不因此生成数据缺口清单，也不等待另一套投资经营输入；它直接根据当前材料和空间方案，对候选路径的相对投入强弱、实施难度、运营复杂度和资金承担方式作简单判断。

### 16.3 对决策链描述的修正

前述项目材料盘点只用于确认当前案例的真实内容，不能把其中的建筑名称、数量、面积或住户口径固化为通用提示词或阶段契约。此前将数据来源预设为“政策、建筑、产权、保护和居民条件”或另设“项目经营数据”入口也不准确：不同项目会提供不同材料，Agent 应先读取当前项目已有材料，再根据实际内容开展分析，不能先想象材料类别和字段。

后续统一改为：

```text
项目材料：读取当前项目已经提供的原始材料，使用其中会影响判断的具体对象、数字、空间关系、现状条件和方案设想。不预设材料类别或固定字段。

空间数据库：分析项目周边的具名 POI、道路、距离、人口、夜光、路网结构和可达性关系，用于判断区域角色、供给空位、主要联系方向、服务对象和空间组织。

知识库：查找与当前问题相关的规划方法、空间策略和案例机制，用于比较候选定位、产品组织、空间利用和运营方式，不直接套用案例结论。

公开资料：仅在公开事实会影响判断时，核对现行政策、具名设施、交通节点、同类项目及相关机构的真实现状。

投入与运营分析：根据当前项目材料、空间数据和已形成的方案，比较不同方案的相对投入强度、实施难度、运营复杂度、责任关系、资金承担方式和持续运行逻辑。现有数字能够支持简单计算时直接计算；否则作定性判断，不虚构投资额、收入、收益率或回收期。
```

这意味着每个单元直接用已有材料作出当前选择。正式报告不把资料目录、缺失字段、补充调研或经营台账写成项目方案。

### 16.4 文档读取链路修复

原始 DOCX 中文可正常解析，旧数据库解析块的乱码通过重新解析四份原始材料已消除。PDF 在 Docling 转换页数不一致时，现仅对具有可读文本层的 PDF 使用文本解析回退。`read_project_document` 已能返回四份材料的可读中文。回归测试覆盖 DOCX 中文保留和文本 PDF 的页码与中文保留。

### 16.5 通用提示词的最终表述

- 项目材料没有通用的固定分类；当前项目提供什么，就读取和使用什么。
- 当前项目盘点中的建筑、院落、住户和服务周期只是本次案例事实，不进入通用 schema 或每个项目的预设输入。
- 投入与运营分析是现有材料上的简单项目选择，不是另一套财务数据采集或补输入工作流。

## 17. 统一方案基线与首单元范式修正

### 17.1 真实运行暴露的两个问题

新十二单元链路首次从头运行时，第一单元成功读取了 18 个具名对象、项目原文和具体数字，但结论仍将确权、定级、体检、核验和审批写成方案启动的默认前置条件。这说明内部标识 `policy_site` 仍在诱导“政策与场地准入审查”范式，与“现有材料直接转成适度空间选择”的目标冲突。该 run 被保留为失败记录，没有继续污染下游单元。

同时，十二个领域决策经综合后已经生成稳定的 `report_blueprint`，但九个章节和图件只能重新读取十二个单元。它们因此可能各自重新做总体取舍，使定位、客群、产品、空间、运营和分期发生漂移。

### 17.2 收敛后的单一契约

1. 第一单元从 `policy_site` 直接改名为 `project_basis`，不保留旧名兼容分支。材料中的不确定性转成适度、可逆的方案选择，不得把补调查、补资料、补核验或审批前置条件当成项目方案或默认行动。
2. 新增语义化领域工具 `read_strategy_blueprint(run_id)`，只返回已持久化的统一定位、未来状态、决策链、行动计划和九章任务。它不返回 `decision_state` 其他字段、Harness 消息、工具结果、执行轨迹或已写章节。
3. 章节作者先读取统一蓝图锁定总体方案，再按需读取领域决策和原始资料展开论证；不重新进行总体取舍。
4. 图件作者使用同一蓝图，每张图解释已经确定的选择或行动，不在图件阶段重新提出总体方案。

这一工具不是恢复完整 `solution JSON` 直传，而是为已成为稳定业务产物的综合蓝图提供一个窄且稳定的 Harness 读取入口。通讯、工具调用、上下文注入、重试和消息历史仍由 Codex Harness 负责。

## 18. n8n 一小时取消与断点恢复

### 18.1 根因

正式全链路运行两次在约一小时后被 n8n 标记为 `ManualExecutionCancelledError`。单个 Codex Harness 调用仍在正常工作，工作流也声明了 `executionTimeout: 14400`，但 n8n 2.34 的 `EXECUTIONS_TIMEOUT_MAX` 默认值为 3600 秒。队列 worker 取工作流时限和全局上限中的较小值，因此工作流自身的四小时设置没有生效。

取消不会经过工作流的失败节点，领域运行一度错误保留为 `running`。确认对应 n8n execution 已取消且 Harness 进程已经结束后，将领域运行标记为失败并调用既有恢复入口；恢复 execution 直接复用已完成的领域单元，没有重算前序结果。

### 18.2 修复

`docker-compose.yml` 的共享 n8n 环境增加：

```text
EXECUTIONS_TIMEOUT_MAX=${N8N_EXECUTIONS_TIMEOUT_MAX:-14400}
```

该配置同时作用于 n8n 主进程和 queue worker，使全局上限与工作流四小时时限一致。没有在业务工作流中增加定时器、影子重试、兼容分支或执行协议。契约测试直接断言该基础设施配置，防止容器重建后回退到默认一小时。

## 19. 图件失败语义与正式报告重建

### 19.1 空图报告的真实根因

完成十二个决策单元和综合蓝图后，图件阶段一度返回空资产。排查确认有两个连续失效点：

1. 本地 `.env` 中的 `DB_BIND_ADDRESS` 仍是旧 WLAN 地址 `192.168.3.57`，当前主机地址已变为 `192.168.3.62`，容器无法取得空间数据记录；
2. `build_spatial_strategy_visuals()` 将数据源读取失败转换为 `status=ready, assets=[]`，报告装配因此把没有图件的结果误判为成功。

第一项是本地部署配置失效，第二项是首次允许错误状态进入正式产物的代码根因。现在空间记录不可用时直接抛出 `visual_source_records_unavailable`；n8n 图件返回节点和报告装配共同要求三至五个真实图件。工具或数据源失败仍是运行失败，不会被扩写为正式报告中的“证据不足”。

### 19.2 报告装配修正

正式报告重建同时完成以下收敛：

- 项目名称提取不再把统一核心提示前缀并入标题；
- 删除章节正文中与外层结构重复的标题，并统一内层标题级别；
- 从已持久化定位决策生成候选定位比较表；
- DOCX 使用正式业务报告版式、固定表格几何、页眉页脚和章节内嵌图件；
- 正文只呈现判断、依据和行动建议，不出现 Agent、Harness、工具、工作流、内部状态、JSON 或决策单元编号。

### 19.3 最终产物与验收

运行 `770a2739-ecb6-490a-89d0-56a20d794a5b` 保留已完成的十二个决策单元和章节，只重新生成图件并装配报告。最终定位为“居民共生型县政原址公共文化院落”，空间结构为“一门一线三院一堂、住宅独立”。

数据库中的 `analysis_reports.asset_manifest.visual_assets` 保存四个图件，分别解释十五分钟 POI 供给结构、社区基本盘与预约节点、公共到达与居民通行界面、夜间活动背景与首期运营边界。图件使用 2635 条 POI、1354 条道路、439 个人口格网和 439 个夜光格网，保留潘家坪路、华夏路、开福寺路及幸福桥社区文化长廊等具名对象。

最终 DOCX 为 26 页，包含四张图件和一张候选定位比较表。逐页渲染检查确认无文字遮挡、表格断裂、图文分离、异常空白或末页截断。相关 n8n、API、MCP、空间策略、图件和报告契约测试共 `88 passed`，`git diff --check` 通过。

## 20. 七种空间分析语义的领域消费链

### 20.1 新报告暴露的问题

运行 `770a2739-ecb6-490a-89d0-56a20d794a5b` 确实读取了 POI、人口、道路、夜光、具名设施和部分方向结果，但空间证据主要用于排除普通商业、选择公共到达方向和限制夜间强度。真实时间圈、H3 或网格高低值、多指标关系、重点单元邻域及具名连接没有继续改变产品、布局和分期，正式图件也主要是全量数据背景图。

根因不在 `analyze_spatial_evidence` 的工具说明。该 MCP 已明确提供 `scope`、`accessibility`、`direction`、`neighborhood`、`rank`、`relationship` 和 `inspect` 七种语义。首次破坏约束的位置是决策单元消费者：十二个单元共用同一通用提示，没有实际调用各自的专项 Skill，也没有声明各单元必须回答的空间问题。后半程曾出现 `data_source_unavailable`，模型仍使用上游摘要完成领域结果，进一步造成空间信息泛化。

### 20.2 收敛后的编排

1. 十一个决策单元由仓库内的 `question`、`depends_on`、`decision_output`、`evidence_focus` 和 `spatial_questions` 完整定义领域任务；不保存 `skill_id`，Codex Harness 不读取本机专项 Skill。
2. 区域角色、供给空位、使用者和空间布局四个真实消费者分别接收方向背景、多指标关系与高低值、相邻单元和具名展开问题。
3. 这些问题描述需要作出的空间判断，不规定模型机械跑满七种模式。工具选择、调用、上下文、重试和消息历史继续由 Codex Harness 负责。
4. `spatial_layout` 直接依赖 `supply_gap`，使优先、排除和错位单元能够进入入口、路径、缓冲和连接断点的布局判断。
5. 恢复运行始终采用新的单元定义，只复用已经完成的领域结果；不保留旧 `decision_units` 兼容分支。

### 20.3 失败边界

空间 MCP 遇到数据库执行异常时直接抛出 `data_source_unavailable`，不再返回可被模型写入 `inputs_used` 的普通证据对象。Codex Harness 进程或最终结果出现该错误时，当前阶段直接失败。n8n 使用已有的阶段持久化和恢复能力继续执行，不在项目代码中增加工具重试、消息回环或影子运行时。

### 20.4 正式产物要求

正式正文不写七种分析模式或工具过程，但必须兑现其领域结果：真实步行时间圈、方向差异、重点空间单元、多指标共同高低值或错位、相邻连续与断裂，以及展开后的具名 POI、道路和连接关系。图件作者优先设计这些决策图，不以区域全量散点图代替空间选择。

## 21. 具名 POI 的领域选择与图件复用

### 21.1 根因

原始 POI 只保存名称、分类、typecode、地址和位置，不包含“知名度”。此前空间证据展开先按名称选择单元内 POI，再按距离补最近对象；图件渲染器又维护了包含具体地名的关键词和排除词，重新选择另一组节点。因此普通近邻可能挤掉真正影响区域角色的设施，正文与图件也可能各用一套具名对象。

### 21.2 单一选择链路

现有 `analyze_spatial_evidence` 保留七种分析模式，只增加三个通用 POI 候选角色：

- `regional_anchor`：区域交通、文化、公共服务等候选锚点；
- `comparable_supply`：与当前 selector 对应的同类或替代供给；
- `daily_service`：影响居民日常使用的服务节点。

工具依据当前 selector、高德 category/subcategory/typecode、距离和类别/方向多样性形成分层候选，返回稳定记录引用、真实名称、分类、方向、距离及选择依据。它不计算知名度，也不宣布某节点是地标。区域角色、空间流向、供给空位、使用者和空间布局单元按各自问题请求候选，由当前决策 Agent 完成最终取舍；只有官方等级、运营状态或区域影响力会改变判断时才核对公开资料。

候选选择由 `SpatialEvidenceService._named_poi_candidates()` 在空间证据模块内部完成，具体顺序为：

1. 只读取当前项目空间快照中具有有效几何和真实名称的 POI；
2. `regional_anchor` 和 `daily_service` 依据通用高德 category 或 typecode 前缀判断功能匹配，`comparable_supply` 依据当前 `poi.category` / `poi.subcategory` selector 判断同类供给；
3. 先比较角色功能匹配和分类身份完整度，再比较到项目中心的直线距离；名称不承担“知名度”或项目重要性排序；
4. 在已匹配候选中优先保留尚未出现的类别和方向，避免同一功能、同一方向的近邻连续占满结果；
5. 对名称去重，每个角色最多返回 `min(top_k, 6)` 个候选，调用方最多同时请求三个角色。

角色分类是跨项目语义，不是当前案例词表：

| 角色 | 通用分类范围 | selector 作用 |
|---|---|---|
| `regional_anchor` | 交通设施、风景名胜、科教文化、政府与社会组织、医疗、体育休闲 | 不要求 selector 命中，由区域性功能分类筛选 |
| `comparable_supply` | 不预设固定分类 | 直接使用当前 POI category/subcategory selector 识别同类或替代供给 |
| `daily_service` | 生活、医疗、科教文化、购物、交通、政府与社会组织、体育休闲、餐饮 | 不要求 selector 命中，由日常服务功能分类筛选 |

每个候选的稳定返回结构为：

```text
record_ref
name
category
subcategory
typecode
direction
straight_line_distance_m
role
selection_basis
```

`selection_basis` 只解释可复核的选择条件，包括高德分类、是否符合本次 selector、是否落在角色功能范围，以及相对项目的方向和距离。它不生成知名度、影响力分数或“地标”结论。以开福寺为例，只有当当前项目 POI 快照确实包含该记录，且它的分类或 typecode 与请求角色匹配时，它才可能进入候选；是否进入正式判断仍由决策单元结合当前任务作出。

### 21.3 MCP 领域入口

`modules/spatial_projects/mcp_server.py` 中既有 `analyze_spatial_evidence` 增加可选参数：

```text
named_poi_roles: list[regional_anchor | comparable_supply | daily_service]
```

该参数随其他领域查询参数进入 `SpatialEvidenceRequest`，没有新增工具，也没有改变 `scope`、`accessibility`、`direction`、`neighborhood`、`rank`、`relationship`、`inspect` 七种分析模式。只有分析结果可用且当前快照包含 POI 数据时，结果才附加 `named_poi_candidates`；候选生成、输入约束、数量上限和返回收敛均留在空间证据模块内部，MCP 层只负责稳定地暴露领域能力。

这一边界有两个目的：

- 决策 Agent 可以按问题请求“区域锚点”“同类供给”或“日常服务”，不需要知道高德分类表、typecode 前缀和去重排序规则；
- Harness 继续负责工具发现、调用通讯、结构化参数、上下文和执行失败，项目不复制或模拟这些通用运行时能力。

### 21.4 决策单元消费者

角色请求写入十二单元中真正消费具名空间关系的五个单元，其他单元不为展示完整性而机械请求 POI：

| 决策单元 | 请求角色 | 要改变的领域判断 |
|---|---|---|
| `regional_role` 项目类型与区域角色 | `regional_anchor` | 识别各步行圈中的区域节点、公共服务和居住背景，区分区域骨架、街坊分配与项目界面 |
| `market_flow` 公共使用与空间流向 | `regional_anchor` | 比较来源地、到达节点、潜在承接点和阻断关系 |
| `supply_gap` 具名供给与服务空位 | `comparable_supply`、`regional_anchor` | 判断真实替代、协同、重复供给和连接缺口 |
| `audience_use` 使用者与使用方式 | `daily_service` | 把候选使用者对应到真实来源节点、道路和项目到达关系 |
| `spatial_layout` 空间组织与具体落位 | `regional_anchor`、`daily_service` | 将外部到达、内部使用和居民界面落到入口方向、具体路径与连接对象 |

这些请求位于 n8n 的领域单元定义中，只描述各单元需要回答的问题，不要求模型按固定顺序跑工具，也不把候选直接写成结论。决策 Agent 仍可舍弃与当前判断无关的候选；下游只消费已进入稳定领域结果的具名实体和引用。

### 21.5 图件消费与失败语义

决策结果继续使用既有 `named_entities`，不增加平行 memo 字段。图件设计从已保存的 `record_ref` 选择 `named_record_refs`，渲染器只按稳定引用匹配原始 POI，不再按名称、距离、项目关键词或排除词判断重要性。引用不存在时图件直接失败，避免悄悄退回另一套节点选择。

`modules/spatial_strategy/visual_design.schema.json` 将 `named_record_refs` 定义为每张图最多十二个 `current:dataset:poi/...` 引用，并要求所有图件设计显式提供该字段。`modules/spatial_strategy/visuals.py` 在归一化时只允许 POI 地图使用这些引用；渲染时逐条核对引用是否能在当前 POI 数据中找到。任一引用缺失即抛出 `visual_named_record_refs_not_found`，无效引用格式或非 POI 图件携带引用也直接失败。

因此具名对象只有一次语义选择：决策阶段选择并保存稳定引用，图件阶段负责忠实渲染。图件渲染器不再维护“古开福寺”等项目关键词、排除词或另一套近邻规则，也不会在引用失效时偷偷替换为最近设施。

### 21.6 文件级落点

本轮改动集中在领域工具、消费者、图件契约和对应测试：

- `modules/spatial_action/spatial_evidence.py`：定义三个角色、请求字段、分类与 typecode 规则、候选选择和稳定返回结构；
- `modules/spatial_projects/mcp_server.py`：在既有 MCP 工具上暴露 `named_poi_roles`；
- `n8n/workflow-generators/urban-renewal-agent.workflow.mjs`：为五个真实消费者写入按任务区分的角色请求；
- `n8n/workflow-components/decision-step.json`、`n8n/workflow-components/urban-renewal-component-source.mjs`：由工作流生成器同步更新的正式组件；
- `modules/spatial_strategy/visual_design.schema.json`：定义 `named_record_refs` 图件设计契约；
- `modules/spatial_strategy/visuals.py`：删除项目专用选择规则，只按稳定引用匹配和渲染；
- `tests/domain/test_spatial_evidence.py`：覆盖角色枚举边界、功能优先于普通近邻、名称不改变不同距离候选的选择、selector 同类供给和方向多样性；
- `tests/domain/test_spatial_project_mcp.py`：覆盖 MCP schema 暴露三个角色；
- `tests/domain/test_decision_step_dynamic_stop.py`、`tests/domain/test_n8n_rag_workflows.py`：覆盖生成工作流中的角色请求和领域契约；
- `tests/domain/test_spatial_strategy_visuals.py`：覆盖只使用决策引用、不使用项目关键词及图件设计消费。

### 21.7 验证与运行边界

本轮已经重新生成 n8n 工作流，并完成以下验证：

- n8n 工作流契约和断点恢复测试通过；
- 空间证据、MCP、Codex Harness 消费边界和图件测试通过；
- `git diff --check` 通过；
- 未增加 token 限制、Harness 通讯协议、项目级工具重试或项目专用方案。

验证使用项目现有测试夹具，没有重新连接真实数据库生成正式报告。因此本节证明的是契约、选择机制、消费者映射和图件复用方式已经收敛；它不宣称当前真实 POI 快照一定包含某个具名节点，也不把测试候选写成正式分析结论。真实运行时，候选完全由当次项目 POI 快照、当前 selector 和决策 Agent 的领域判断共同决定。

这次改动没有增加 POI Agent、新的空间分析模式、知名度字段、项目专用词表、工具回环或 Harness 协议。正式正文仍不继承工具名、状态字段、内部 JSON 或决策单元编号。

### 21.8 当前工作流部署与真实运行前置检查（2026-08-21）

本节改动完成后已执行正式 bootstrap：生成器重新产出工作流，n8n 导入两个正式 workflow，同步生产 Webhook 注册并重启主进程、queue worker 和 task runner。数据库中的 `urbanRenewalDecisionSupportAgent` 处于 active 状态，共 68 个节点；导入后的节点定义包含 `regional_anchor`、`comparable_supply` 和 `daily_service` 三种角色请求。n8n schema smoke check 和正式 workflow 契约测试通过。

随后准备以 `history_id=15266dd890faa567070befc1` 创建全新 run。提交前的数据源检查没有通过：当前配置的远程 MySQL 端口在网络探测层可建立 TCP，但主机实际 MySQL 连接返回 `2003 connection refused`；经只绑定本机回环地址的临时 Docker 转发测试，MySQL 握手仍返回 `2013 lost connection`。这说明当前数据库公网入口没有提供可用 MySQL 会话，不能把问题归因于空间证据工具或 Agent 选择。

本次没有提交一个必然失败的新 run。`analysis_runs` 中 queued/running 数量保持为 0，最近完成的正式运行仍是 `770a2739-ecb6-490a-89d0-56a20d794a5b`。临时数据库转发容器已经删除，仓库 `.env` 未改写。待数据库当前公网入口恢复后，应先连续三次完成最小 `SELECT 1`，再创建全新 run，使五个具名 POI 消费单元、综合蓝图、图件和报告全部基于同一版新契约重新计算。

### 21.9 公网数据库真实运行验收（2026-08-21）

公网数据库入口恢复后，将 `.env` 的 `DB_HOST` 更新为 `175.0.133.26`，以 `history_id=15266dd890faa567070befc1` 创建全新运行 `b8a2df1a-0e36-48a3-8f63-877b0014686f`。本次没有新增 POI Agent、工具重试、Harness 协议或项目专用选择规则；运行使用当前领域语义工具、已激活的 68 节点 n8n 工作流和现有报告交付链路。

真实运行最终状态为 `completed`，12 个决策单元、统一 `report_blueprint`、9 个章节、5 个图件和 DOCX 均已完成。12 个决策单元的正式结果共保存 49 个具名实体引用；其中五个具名空间消费者实际按角色请求并消费了真实快照中的对象：`regional_role` 使用 `regional_anchor`，`market_flow` 使用 `regional_anchor`，`supply_gap` 使用 `comparable_supply` 与 `regional_anchor`，`audience_use` 使用 `daily_service`，`spatial_layout` 使用 `regional_anchor` 与 `daily_service`。本次结果中的代表性节点包括潘家坪(公交站)、岁宝百货(开福店)、华创国际广场、CFC富兴时代、乐贝亲子图书馆、幸福家园活动中心、紫凤小学、潘家坪路和华夏路；每个正式引用均保留 `record_ref`，并继续区分空间候选、协同触点和已验证使用之间的证据边界。

本次运行还暴露并定位了一个不属于领域工具的运行边界：`supply_gap`、`spatial_layout`、`investment_operation` 和 `phasing` 的 Codex 子进程均生成了完整、通过 `decision_memo.schema.json` 的领域 JSON，且其 MCP 调用日志没有失败事件；但子进程 stderr 同时包含模型读取源码、测试和文档时出现的字面量 `data_source_unavailable`，现有 Harness 适配检查对 stderr 做全文匹配，因而将这些成功结果误判为工具失败。没有修改 Harness，也没有在业务层增加规避分支；每次确认结果完整且引用有效后，使用既有阶段持久化结构和断点恢复入口保存该领域结果，再继续下一个阶段。该处理只恢复已生成的稳定领域产物，不重算前序单元，不改变工具失败语义。

最终报告记录状态为 `ready`，DOCX 产物为：

```text
runtime/client-decision-spatial-strategy/b8a2df1a-0e36-48a3-8f63-877b0014686f/spatial-strategy-report.docx
```

报告资产清单包含 5 张真实图件，覆盖区域角色协同、15 分钟 POI 供给结构、人口与使用者优先级、公共到达与空间布局、夜光背景与常态夜间边界。图件使用的 8 个 `named_record_refs` 全部存在于 12 个决策结果的 49 个引用中，没有发生引用缺失或偷偷替换；DOCX 文件为有效 OOXML ZIP，`word/document.xml` 含中文文本。报告和图件实际使用的空间快照为 2024 POI 2635 条、道路 1354 条、人口 439 个格网和夜光 439 个格网。

因此，本次真实运行证明的是：公网数据源已可用，具名 POI 角色选择已经由五个领域消费者实际执行，选定引用能够穿过决策、图件和 DOCX 交付链路，且 12 个单元的判断可以在同一运行中恢复并完成。stderr 全文误判属于现有 Harness 适配边界，已在本记录中保留证据；本轮没有把它伪装成空间证据不足，也没有通过项目代码重做 Harness。
