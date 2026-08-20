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

## 12. 剩余限制与下一步

### 12.1 报告内容限制

- “条件”出现 37 次，“核验”出现 19 次，语言仍偏保守；
- “不能证明”出现 4 次，虽然不再支配全文，但仍可进一步压缩；
- 不能完成 13 栋建筑逐栋功能分配，因为缺少建筑编号对应的测绘、产权、结构、保护、消防和实际占用资料；
- 没有工程量、投资额、租金、运营成本和收入模型，不能支持投资决策；
- “重点年龄人口空间分布”实际为年龄结构汇总，图名应改为“重点年龄人口结构”；
- 首期项目包表格信息密度较高，汇报版可压缩为一页项目包和一页实施路线。

### 12.2 后续有效补充

下一步不应继续增加通用 Agent 治理层，而应补充会直接改变空间决策的项目输入：

1. 建筑编号、面积、楼层、结构、保护要素、消防和当前使用状态；
2. 入口、院落、住宅和后勤流线的现场测绘；
3. 业主、住户、运营主体和文化内容伙伴的真实约束；
4. 首期工程量、资金上限和运营成本；
5. 试开放后的到达、停留、复访、安全事件和住户反馈。

获得这些输入后，应新增建筑级功能分配和项目级财务核算，而不是把空间代理指标扩写成客流或收益结论。

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

正式运行已经证明该链路能够从项目材料和空间数据形成“现状依据—未来目标—空间策略—行动方案”的完整报告，并在图件或网络失败后从已完成领域结果恢复。下一阶段的质量提升重点应是建筑、工程、运营和财务输入，而不是继续增加提示词治理、审计层或自建 Harness 能力。
