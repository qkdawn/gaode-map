# ArcGIS MCP 与 V4 报告视觉设计

## 1. 文档目的

本文定义 `spatial-business-analyst` V4 未来接入 ArcGIS 的正式边界：用我们控制的受限 MCP 服务和 V4 深模块，生产可复用空间分析结果与专业报告视觉资产。它是后续实现的唯一设计依据，不描述当前代码已经具备的能力，也不改变 V4 已发布的运行工件。

本设计解决的不是“让 Agent 获得一个任意 GIS 工具箱”，而是让专业章节作者能够在既有的 V4 工作流中按需发现、查看详情、执行受限能力并引用结果：

```text
指标目录 → 指标详情 → 执行 → 稳定 result ID / asset ID → 章节引用 → 报告编译
```

V4 最终仍输出 `report/assets/*.svg`。这里的替换对象是当前直接本地 SVG 渲染调用链，而不是将公开资产格式改为 PNG、JPG 或未归档的在线地图。

## 2. 目标与非目标

### 2.1 目标

- 所有报告视觉统一经受限 ArcGIS 报告视觉链路产生：空间地图经受限 GIS 操作生成，非地图图表经受限 `report_chart` 布局能力生成。
- 空间叠加、空间统计和网络上下文在适用时生成可复用的新 `result ID`，而不是只返回一次性的图片。
- 保留已有 V4 的目录、详情、执行、来源索引、章节引用和 SVG 安全边界；章节作者始终只面对语义化业务能力。
- 将 ArcGIS Pro、ArcPy、Enterprise、Location Services、临时工作区、投影修复、缓存、重试和异常处理隐藏在下层。
- 以现有本机 ArcGIS bridge（当前配置目标为 `127.0.0.1:18081`）为演进基础，建设我们控制的受认证 MCP 服务和健康检查。

### 2.2 非目标

- 不向 V4 Agent 暴露通用 ArcGIS MCP、任意 REST 转发、Portal item、Feature Service、字段名、查询条件、renderer JSON、ArcPy 参数、token 或任务日志。
- 不允许 Agent 自由猜 buffer、距离阈值、空间权重、分类方法、字段映射或统计模型；所有分析只能调用被批准的模板。
- 不让图表、地图或空间代理数据替代章节作者的专业判断，也不把 POI、人口、夜光、道路句法、叠加或网络结果外推为消费、客流、营收、投资回报或确定性选址结论。
- 不保留当前本地 SVG renderer 作为正式切换后的 fallback；受限服务不可用必须显式失败或不可用。

## 3. 架构与职责

```text
V4 章节作者 / 主分析师
  → 指标目录 → 指标详情 → 执行 → result ID / asset ID
  → MetricToolService
  → ArcGISSpatialToolModule
  → 受限 ArcGIS MCP Client
  → 本机受限 ArcGIS MCP / 既有 ArcGIS bridge
  → ArcGIS Pro / ArcPy / 已批准的 ArcGIS 服务
```

### 3.1 V4 公开层

`MetricToolService` 保持章节作者唯一的工具入口。目录只提供工具 ID、名称、用途、适用问题、主要空间单元、行动目标和实现状态；详情才提供输入、输出、口径、范围、限制、误用边界、不可用语义和可生成资产。

V4 公开层不出现 `arcgis.*` 供应商工具。目录中出现的只是由 V4 拥有的语义化能力，例如专题制图、共位区识别、空间集聚诊断、研究区网络上下文和报告图表。

### 3.2 `ArcGISSpatialToolModule`

`ArcGISSpatialToolModule` 是 V4 唯一认识 ArcGIS 的深模块。它负责：

- 解析 V4 材料、数据集、历史结果与 `result ID`，形成经过批准的空间图层或图表数据视图；
- 推断并校验研究范围、空间参考、时间范围、输入完整性和操作模板；
- 规范化参数，计算稳定的 result / asset 签名，并在 `source-index` 中复用同一输入的既有产物；
- 调用受限 MCP，规范化供应商错误和不可用原因；
- 将结构化结果、摘要、输入来源、范围、限制、状态和资产引用写回 V4 `SourceIndex`；
- 对返回的 SVG 执行大小、格式与安全校验，再归档为 V4 报告资产。

它不负责章节正文、主分析师审校、跨章推荐或最终报告编译。

### 3.3 受限 MCP 服务

受限服务只负责 ArcGIS / ArcPy 的技术执行。它部署在受控本机地址，沿用 bridge 的认证、超时、导出大小、隔离工作区和任务清理责任，并新增活的认证健康检查。

服务不提供任意图层读取、任意 GP 工具调用、任意 ArcPy 执行、任意 URL 访问或任意 SVG / renderer 注入。任何运行时数据集和布局都必须由深模块引用批准的 V4 资源，并由服务端映射到受控内部实现。

### 3.4 已核验的本机 Host Bridge 基线（2026 年 7 月 17 日）

本机服务已可访问，但它只是受限 MCP 的演进起点，**不能直接被当作 V4 正式执行契约**。本次只做不含秘密的健康和 OpenAPI 核验，得到的现状如下：

| 项目 | 已核验现状 | 对 V4 的含义 |
| --- | --- | --- |
| 配置与健康检查 | 配置目标为 `127.0.0.1:18081`；认证、ArcGIS Python、主脚本、导出脚本、道路句法脚本和 H3 缓存均已配置；`GET /health` 返回 HTTP 200。 | 说明本机执行环境具备可继续建设的基础，不等于每种 ArcGIS 能力均实际可用。 |
| 当前公开操作 | OpenAPI 标题为 `ArcGIS Host Bridge`，当前只声明 `POST /v1/arcgis/h3/analyze`、`POST /v1/arcgis/h3/export`、`POST /v1/arcgis/road-syntax/webgl` 三类操作。 | 这些是 bridge 技术接口，不是章节作者可见的 V4 指标工具。 |
| H3 分析 | 现有 H3 分析可返回 Gi*、LISA、Global Moran 和预览 SVG。 | 后续应归入 `spatial_pattern`，并转换为 V4 `result ID`、限制和可选 `asset ID`；预览 SVG 不能直接视为报告资产。 |
| H3 导出 | 当前导出面向 GPKG 或 ArcGIS package。 | 尚不是可控布局、图例和安全校验后的 `report/assets/*.svg` 报告制图能力。 |
| 道路句法表达 | 当前道路接口只产出面向前端交互的 WebGL 图层。 | 道路 Choice / Integration 数值继续由既有道路句法链路计算；正式报告专题图仍需新增批准的 ArcGIS 布局模板。 |
| GWR | 仓库已有调用端契约，但运行中的 bridge OpenAPI 未声明对应服务端操作。 | GWR 不是当前可用能力；需要补齐服务端、许可、适用性门槛和诊断输出后，才能作为 `spatial_pattern` 的受控模板。 |
| 规划中的端点 | 当前未发现能力目录、报告地图、网络、栅格、作业、资产或诊断端点。 | 它们都是未来受限 MCP / bridge 建设内容，不能在 V4 catalog 中标为已实现。 |

上线前必须完成以下安全整改：

1. 当前服务进程实际监听 `0.0.0.0:18081`，与配置目标的回环地址不同；正式服务必须绑定 `127.0.0.1`，或在明确部署网段下同时强制认证与防火墙隔离。
2. 当前健康响应包含 Python 与脚本路径等内部诊断；对 V4 或任何非受控调用方只能返回认证后的安全状态摘要，详细诊断仅留在受控运行日志。
3. 当前技术接口的请求或响应可包含运行路径、`trace_id` 等执行细节；受限 MCP 必须由深模块吸收这些细节，绝不能写入 `source-index.json`、章节文件或报告。

## 4. MCP 内部契约

MCP 只暴露一个固定操作入口：

```text
arcgis.execute_report_operation
```

它的 `operation` 为固定枚举：

```text
thematic_map
spatial_overlay
spatial_pattern
network_context
report_chart
```

调用请求由 `ArcGISSpatialToolModule` 构造，至少包含：请求 ID、操作和版本、批准模板 ID、规范化输入资源引用、研究范围、时间范围以及布局语义。它不接受自由 ArcPy 代码、服务 URL、图层 ID、字段表达式、任意 renderer 或自由空间统计参数。

服务端响应只允许三种状态：

| 状态 | 语义 | V4 处理 |
| --- | --- | --- |
| `available` | 受控操作完成，返回受限结构化结果和/或 SVG | 生成或复用 V4 `result ID`、`asset ID`，登记来源、范围和限制 |
| `unavailable` | 输入、数据、环境或适用条件不满足 | 写入明确的不可用原因，不造替代数值、不调用旧 renderer |
| `failed` | 受控服务未完成或输出未通过校验 | 返回安全的诊断摘要，V4 不暴露供应商异常和内部配置 |

公开 V4 工件不得保存 Portal item ID、服务 URL、图层字段、token、临时文件路径、ArcPy 参数、renderer JSON、任务日志或供应商堆栈。

## 5. V4 结果与资产模型

### 5.1 结果与资产的区别

- `thematic_map` 与 `report_chart` 只生产 `asset ID`。它们表达已经存在的结果或数据视图，不产生新的分析结论或新的 `result ID`。
- `spatial_overlay`、`spatial_pattern` 与 `network_context` 在满足前置条件时生产新的稳定 `result ID`，并可同时生产一个或多个 `asset ID`。
- 每个章节只引用其实际使用的材料、结果和资产，不重复计算或重新描述底层技术口径。

### 5.2 稳定签名与复用

result 签名由语义工具 ID、工具版本、规范化参数、输入 `result ID` / 来源、研究范围和时间范围组成。asset 签名由依赖资源、视觉语义、布局版本和渲染版本组成。同一签名必须复用已登记产物。

`SourceIndexItem.source_ids` 记录一个结果或资产依赖的上游资源。资产的公开 payload 只保存文件名、SVG、资产类别、视觉语义以及必要的范围说明；ArcGIS 的实现细节留在受限服务内部。

### 5.3 SVG 安全与发布

返回 SVG 在成为 `report/assets/*.svg` 前必须通过统一校验。拒绝脚本、事件处理器、外部 URL、嵌入式活动内容、未受控资源引用和超出导出大小限制的内容。任何 SVG 失败都使该操作进入 `failed`，不会回退到旧本地 SVG 渲染入口。

## 6. 五类受限能力

| 能力 | V4 可见语义 | 输入 | 输出 | 判断边界 |
| --- | --- | --- | --- | --- |
| `thematic_map` | 将已有空间结果制作成专业专题图 | 已有 `result ID`、研究范围、批准主题样式 | `asset ID` | 不产生新数值或结论 |
| `spatial_overlay` | 识别已知空间代理在研究范围内的共位、交集或聚合区 | 至少两个已有结果、批准叠加模板、研究范围 | 新 `result ID`，可选 `asset ID` | 只描述共同出现、覆盖或空间关系 |
| `spatial_pattern` | 检验空间集聚、离散、热点或局部关系 | 已有结果、空间单元、批准统计模板 | 新 `result ID`，可选 `asset ID` | 必须披露变量、邻接规则、样本与显著性限制 |
| `network_context` | 比较研究区、道路走廊或区域的网络覆盖、服务区和可达性 | 研究范围/走廊、批准网络场景、目标设施类别 | 新 `result ID`，可选 `asset ID` | 不等同于客流或商业收益 |
| `report_chart` | 将归档材料或结果制作成非地图报告图表 | 已归档数据视图、批准图表语义 | `asset ID` | 不新建分析结果，不暗示超出数据支持的结论 |

### 6.1 `thematic_map`

专题图覆盖道路 Choice / Integration、POI 密度、人口密度、夜光、H3、分析范围、候选区和其他已归档空间结果。它只能把既有结果以批准的布局、分类和图例呈现出来；没有新的阈值判断、空间叠加或统计推断时，不创建新结果。

### 6.2 `spatial_overlay`

叠加只允许透明、预定义且可解释的模板，例如研究范围裁切、已归档道路结构值与 POI 高值网格的共位、候选区与限制区叠加。模板必须固定其空间单元、阈值来源、聚合方式和最小可解释范围。Agent 不得自由选择 buffer、字段、权重、阈值或 dissolve 规则。

其结论只能表述为“这些空间代理在同一区域共同出现”“该范围落入已定义限制区”或“该候选范围被某类条件覆盖”，不能表述为确定的客流、消费或收益。

### 6.3 `spatial_pattern`

空间统计支持 Global Moran’s I、Gi*、LISA，并将既有 H3 与 GWR 的 ArcGIS 能力收敛到相同的 V4 结果契约。结果必须公开其变量、空间单元、邻接或距离规则、样本规模、显著性、适用限制和不可用条件。

GWR 或局部回归只有在样本量、变量数量、共线性、空间单元质量和模型适用条件均满足时才可调用；不满足时返回 `unavailable`。任何统计关联都不能被写成因果、消费、客流、营收或投资回报结论。

### 6.4 `network_context`

网络能力面向研究范围、道路走廊和区域比较，可表达等时圈、服务区、网络覆盖、目标设施网络距离和路网约束下的区域差异。

当前仓库已接入保存等时圈面积的网络能力；只有在历史快照包含有效路网范围、出行方式和时间阈值时才返回 `available`，否则返回 `unavailable`。不得使用直线距离、项目边界或无来源的替代值伪装成网络结果。

### 6.5 `report_chart`

`report_chart` 通过同一受限 MCP 服务生成柱图、折线图、散点图、时间线、关系图和其他非地图报告表达图。服务端使用受批准的 ArcGIS Pro Layout / 图表布局模板，或等价的六个固定 ArcMap MXD 布局模板输出 SVG；V4 只提交可归档的数据视图与图表语义。

该能力统一替代当前 V4 直接 SVG 渲染入口。若批准模板无法表达请求，必须返回 `unavailable`，而不是临时生成未经治理的 SVG、改变图表口径或回退旧 renderer。

### 6.6 V4 语义工具与 Bridge 批准模板注册表

章节作者通过指标目录发现的是决策语义工具，而不是 ArcGIS 工具名。下表定义后续 catalog 与 bridge 内部模板之间的边界；表内的“内部模板”只供 `ArcGISSpatialToolModule` 选择和版本化，不能透传给作者侧。`implemented` 状态必须以真实数据、许可、执行与结果解释验证为准，不能因模板被规划而提前标记。

| V4 目录语义工具 | 对应固定 operation | Bridge 内部批准模板族 | 回答的项目问题 | 初始状态 / 关键约束 |
| --- | --- | --- | --- | --- |
| `spatial.thematic_visual` | `thematic_map` | 专题、优先级、热点/冷点、道路结构/覆盖、A/B 或前后比较、区位背景图 | 已有空间结果如何在研究范围内表达，哪些位置或差异需要读者关注？ | 已接入受控执行器；Bridge、几何快照或结果不满足时返回 `unavailable`，只能呈现已有结果。 |
| `spatial.overlay_relationship` | `spatial_overlay` | 范围裁切、道路结构与 POI 高值网格共位、候选区与限制区叠加、距离面、密度面、透明栅格/矢量叠加 | 已定义的空间代理、限制条件或覆盖关系在哪里共同出现？ | 按模板实现；空间单元、阈值来源、聚合和最小解释范围固定。 |
| `spatial.suitability_scenario` | `spatial_overlay` | 适宜性模型、重分类、加权叠加、地形或其他已批准约束面 | 在明确条件、阈值与权重的情景下，哪些区域具有较高空间匹配度？ | 按需且高门槛；权重必须来自用户、项目材料或明确情景假设，并记录敏感性检验状态；不能写成“最赚钱的位置”。 |
| `spatial.pattern_diagnosis` | `spatial_pattern` | Global Moran’s I、Gi*、LISA、Incremental Spatial Autocorrelation、OLS diagnostics、GWR | 已归档空间变量是否集聚、离散、显著，或存在局部空间关系？ | H3 统计优先收敛；GWR 需严格满足样本、共线性、残差、自相关、带宽及空间单元门槛。 |
| `spatial.network_context` | `network_context` | 服务区、OD Cost Matrix、覆盖缺口、Location-Allocation、路径/最近设施、网络上下文图 | 研究区、道路走廊或方案之间的网络覆盖、服务可达性和区域差异是什么？ | 后续实现；必须先确认路网数据、许可、方式、时间场景和目标设施定义。 |
| `report.decision_visual` | `report_chart` | 柱图、折线图、散点图、时间线、关系图和其他已批准的 ArcGIS Pro 图表布局 | 已归档数据如何以非地图视觉清楚解释比较、趋势、构成或关系？ | 已接入受控执行器；仍由批准模板导出 SVG，模板或 Bridge 不可用时返回 `unavailable`，不使用独立本地 chart renderer。 |

模板注册表应遵守以下规则：

- 只有 `ArcGISSpatialToolModule` 可以把语义工具映射到模板；Agent 不选择字段、renderer、空间统计参数、缓存键或 ArcPy 操作。
- 模板的输入资源类型、空间单元、阈值来源、分类方法、布局版本、可用导出格式和不可用条件由模块维护，并通过指标详情以业务语言披露必要边界。
- 方案比较、优先级或适宜性只是一种受限情景表达，不取代章节作者对行动、验证与停止条件的专业判断。
- 道路句法数值不是由该注册表重算：它消费现有的 Choice / Integration 等归档结果；ArcGIS 负责其空间处理、正式制图、布局与导出。
- WebGL 仅服务前端交互，不是本注册表产生的报告视觉资产。

## 7. 运行、安全与不可用策略

- 本机受限服务必须提供经认证的健康检查；现有仅检查配置的 readiness 不能证明 ArcGIS 已可执行。
- 服务端负责输入大小、导出大小、超时、并发、隔离 workspace、临时数据删除和安全日志；V4 调用方不管理这些细节。
- 深模块只把必要的规范化数据交给服务端；服务端禁止访问未批准的本地路径、外部 URL 或任意账户资源。
- 任何依赖 ArcGIS 的结果都必须记录实际输入来源、研究范围、时间范围、限制和状态；失败或不可用不会阻塞与其无核心依赖关系的章节。
- 章节依赖该结果才能成立时，DAG 调度才阻塞或要求定向复核；否则作者应写明边界并完成独立分析。

## 8. 实施切换顺序

后续代码实施按以下顺序推进，不建立 V3 或旧 SVG 渲染兼容层：

1. 修正现有 bridge 的监听边界和健康响应，增加受认证、无内部路径泄漏的活健康检查，并建立固定操作枚举。
2. 将现有本机 bridge 演进为受限 MCP 服务；先补能力目录、批准模板发现、作业管理、资产读取和受控诊断边界，再逐项接入实际 ArcGIS 执行。
3. 在 `modules/spatial_action/` 建立 `ArcGISSpatialToolModule` 和 MCP client，收敛现有 ArcGIS bridge 调用。
4. 将 V4 语义能力写入指标目录与详情，并在 `MetricToolService` 中接入 result / asset 复用；目录状态必须反映实际 bridge 能力。
5. 先实现专题视觉、报告图表和现有 H3 空间统计的 V4 结果契约；再按真实数据条件逐步接入叠加、网络和高门槛统计模板。
6. 将报告资产生产完全切换到新深模块，删除 `render_report_visual`、`simple_map` 及其旧测试；不保留 fallback。
7. 更新 API、run storage、编译器和前端，以稳定 asset 引用展示已验证 SVG，并确保公开 run 仍只有 V4 五类工件。

## 9. 验收与测试

后续实现必须至少验证：

- MCP 只暴露固定操作，拒绝任意 ArcGIS、任意图层、任意字段、任意 URL 和任意参数调用。
- 指标目录和详情不泄漏供应商实现、图层、字段、token、投影或执行日志。
- 相同输入复用同一 `result ID` / `asset ID`；多个章节引用同一结果时不重复计算。
- 专题图和报告图表都生成安全 SVG，并进入唯一的 V4 `report/assets/` 工件链路。
- 叠加、统计和网络结果完整记录来源、范围、限制和不可用语义。
- ArcGIS 离线、无凭据、输入不足、统计不适用、输出超限或 SVG 不安全时，V4 明确返回 `unavailable` / `failed`，不回退旧 SVG 生成器。
- 正式 bridge 仅在受控地址监听；健康响应、V4 公开工件和作者侧工具详情均不泄漏本机路径、服务端 trace、供应商参数或执行日志。
- 目录状态表示仓库是否有执行路径；Bridge、数据或输入条件的临时不可用在运行结果中返回 `unavailable`，不得包装成可用数值或虚假 SVG。
- 相关 domain、API、frontend 测试和 `git diff --check` 通过，提交内容不包含 `runtime/` 或 `static/frontend/` 生成物。

## 10. 已锁定决策

- 第一阶段已实现受限 Bridge、六类报告视觉模板契约、V4 深模块与本地 renderer 删除；真实 ArcGIS 布局模板仍需在受控本机环境配置并完成烟雾验收。
- V4 继续公开 SVG 报告资产；替换的是直接本地渲染实现与调用契约。
- 所有报告视觉进入统一受限 MCP 链路；非地图视觉通过 `report_chart` 处理。
- ArcGIS bridge 是受限 MCP 服务的部署基础；官方或通用 Esri MCP 可作为人工 GIS 试验的供应商通道，但不是正式 V4 产品 API。
- `urban-strategy-stage1` 保持专项能力。
