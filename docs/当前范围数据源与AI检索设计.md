# 当前范围数据源与 AI 检索设计

## 1. 背景

`/analysis` 里的 AI 需要回答两类问题：

1. 解释已经算好的分析结果，例如人口结构、夜光活力、路网句法、H3 热点和选址建议。
2. 查询当前分析范围内的全量明细数据，例如“这个范围里有哪些餐饮 POI”“夜光最高的 cell 是哪些”“路网指标最高的路段有哪些”。

这两类问题不能使用同一种输入方式。已经算好的分析结果适合压缩成 `EvidenceNode` 给 AI 引用；范围内全量数据不适合直接塞进 prompt，而应作为可查询数据源，由 AI 通过受控工具检索、聚合、分页读取。

这里的 MySQL 不是产品语义。MySQL 只是可能的数据存储介质之一。产品语义应该是“当前范围数据源”：所有查询都必须被限定在当前 `history_id`、当前空间范围、当前年份或数据版本内，不能让 AI 扫描整个库。

## 2. 当前存储现状

当前系统里的范围数据主要有三种位置。

### 2.1 POI 专用持久化表

POI 当前有专门的持久化表：

- 表：`poi_results`
- 关键维度：`history_id`、`source`、`year`
- 数据字段：`poi_data`
- 摘要字段：`summary`

这意味着 `current:dataset:poi` 可以从 `poi_results` 中按当前历史记录、数据源和年份读取完整 POI 列表。

### 2.2 通用分析产物表

人口、夜光、路网、H3 和部分栅格产物没有各自独立的专表，当前主要通过通用分析产物表保存：

- 表：`analysis_artifacts`
- 关键维度：`history_id`、`artifact_type`、`params_hash`、`scope_fingerprint`、`data_version`
- 数据字段：`payload`
- 摘要字段：`summary`

当前前端会把部分分析结果持久化为 artifact：

| 当前范围数据源 | 典型 artifact_type | 内容 |
| --- | --- | --- |
| `current:dataset:population` | `population` | 人口 overview、summary、grid、grid evidence、layer、year、view |
| `current:dataset:nightlight` | `nightlight` | 夜光 overview、summary、grid、layer、raster、year、view |
| `current:dataset:road` | `road_syntax` | 路网 summary、diagnostics、roads、nodes、webgl、mode、metric |
| `current:dataset:h3` | `poi_h3_grid` / `poi_raster_grid` | H3 或共享栅格 feature、summary、charts、year、参数 |
| `current:scope` | `scope` | 当前等时圈或空间范围信息 |

因此，AI 未来查询人口、夜光、路网和 H3 明细时，应从 `analysis_artifacts` 中读取当前范围对应的 artifact payload，而不是直接查询某个全局业务表。

### 2.3 当前保存完整性

当前已经保存的数据不是完全同一种粒度：

| 数据 | 当前是否保存明细 | 当前保存形态 | 适合 AI 查询的程度 |
| --- | --- | --- | --- |
| POI | 是 | `poi_results.poi_data` 保存当前范围 POI 列表；按 `history_id + source + year` 区分 | 可以直接作为 `current:dataset:poi` 的明细查询底座 |
| H3 / POI 栅格 | 是 | `analysis_artifacts.payload.grid.features` 保存 `poi_h3_grid` 或 `poi_raster_grid` 的 feature 列表 | 可以作为 `current:dataset:h3` 查询底座 |
| 人口 | 是 | `analysis_artifacts.payload.grid.features` 保存完整人口 base grid geometry；`payload.layer.cells` 保存当前视图 cell 指标；`grid_evidence` 保存 Top/Low 等抽样证据 | 重新跑分析后的新 artifact 可作为 `current:dataset:population` 查询底座 |
| 夜光 | 是 | `analysis_artifacts.payload.grid.features` 保存完整夜光 base grid geometry；`payload.layer.cells` 保存当前视图 cell 指标；`raster` 保存预览信息 | 重新跑分析后的新 artifact 可作为 `current:dataset:nightlight` 查询底座 |
| 路网 | 是 | `analysis_artifacts.payload.roads.features` 和 `payload.nodes.features` 保存路段与节点 FeatureCollection | 可以作为 `current:dataset:road` 查询底座 |

这意味着重新跑分析后，POI、H3、人口、夜光和路网都具备作为 scoped dataset 查询底座的持久化数据。当前变更只补齐保存底座；`list_scope_datasets`、`query_scope_dataset`、`aggregate_scope_dataset` 和 `read_scope_record` 等 AI 查询工具后续再实现。

### 2.4 运行时上下文

Agent 执行过程中还会维护运行时 artifacts / snapshot，例如：

- `current_pois`
- `current_population`
- `current_population_summary`
- `current_nightlight`
- `current_nightlight_summary`
- `current_road`
- `current_road_summary`
- `current_poi_h3`
- `current_poi_h3_grid`
- `current_poi_h3_summary`

这些是当前会话内的运行时上下文，适合用于即时回答和构造 EvidenceNode，但不能被当成稳定数据库表。需要跨会话恢复或被 AI 稳定查询的内容，应通过 `poi_results` 或 `analysis_artifacts` 回读。

## 3. 来源模型

来源是产品语义，不绑定单一存储。AI 面向的是 `source_id`，不是数据库表名。

### 3.1 分析结果来源

`current:analysis:*` 表示已经算好的分析结论，主要用于解释、归纳和引用。

建议保留这些来源：

- `current:analysis:poi_h3`
- `current:analysis:population`
- `current:analysis:nightlight`
- `current:analysis:road`
- `current:analysis:site_selection`
- `current:analysis:frontend_map_search_context`

这些来源应输出紧凑的 `EvidenceNode`，例如摘要、关键指标、Top cell、代表路段、候选点和诊断文本。AI 不应通过这些来源读取全量 payload。

### 3.2 当前范围数据源

`current:dataset:*` 表示当前范围内可查询的明细数据。

建议定义这些来源：

- `current:dataset:poi`
- `current:dataset:population`
- `current:dataset:nightlight`
- `current:dataset:road`
- `current:dataset:h3`

这些来源用于受控查询、聚合和分页读取。AI 可以通过工具问它们“有多少”“哪些最高”“按类别统计”“读取某一条记录”，但不能直接获得完整原始 payload。

### 3.3 Source 与 EvidenceNode

每个 dataset source 至少需要表达：

| 字段 | 含义 |
| --- | --- |
| `source_id` | 例如 `current:dataset:poi` |
| `source_kind` | `system` |
| `title` | 用户可读名称，例如 `当前范围 POI` |
| `status` | `ready`、`pending`、`failed` |
| `record_count` | 当前范围内可查询记录数 |
| `time_scope` | 年份或版本信息 |
| `storage_ref` | 内部存储引用，不直接暴露给最终回答 |
| `query_capabilities` | 可过滤、排序、聚合的字段 |

工具查询结果必须转成 `EvidenceNode`，并包含：

- `source_id`
- `source_type`
- `content`
- `metadata`
- `locator`
- `evidence_level`
- `warnings`
- `citation`

## 4. 查询设计

AI 不应执行任意 SQL。范围数据查询应通过受控工具完成。

### 4.1 `list_scope_datasets`

用途：列出当前 `history_id` 下可用的范围数据源。

输入：

- `history_id`

输出：

- source 列表
- 数据年份或版本
- 记录数
- 可查询字段
- 存储状态
- warnings

### 4.2 `query_scope_dataset`

用途：分页读取当前范围内的明细记录。

输入：

- `source_id`
- `filters`
- `sort`
- `limit`
- `offset`

约束：

- 只能使用白名单字段。
- 默认限制返回条数。
- 必须返回 `total_count` 或 `has_more`，避免 AI 误以为读完了所有记录。

### 4.3 `aggregate_scope_dataset`

用途：对当前范围数据做受控聚合。

输入：

- `source_id`
- `group_by`
- `metrics`
- `filters`
- `top_k`

示例能力：

- POI 按类别计数。
- 人口 cell 按密度取 TopN。
- 夜光 cell 按辐射值取 TopN。
- 路网 feature 按 `choice`、`integration`、`connectivity` 排序或聚合。

### 4.4 `read_scope_record`

用途：按记录 ID 读取单条 POI、cell、road feature 或 H3 cell 的详情。

输入：

- `source_id`
- `record_id`

输出：

- 单条记录的 EvidenceNode。
- 可复核 locator。
- 年份、数据版本和来源引用。

## 5. 年份与版本规则

年份和版本是当前范围数据源的强约束。

### 5.1 POI

POI 使用：

- `poi_results.year`
- `poi_results.source`
- `history_id`

AI 回答中引用 POI 时，应能说明数据年份和数据源，例如：

```text
当前范围 POI，2024 年，高德来源
```

### 5.2 分析 artifact

分析产物使用：

- `analysis_artifacts.params.year`
- `analysis_artifacts.payload.year`
- `analysis_artifacts.data_version`
- `analysis_artifacts.scope_fingerprint`

如果 payload 或 params 中存在年份，Source 和 EvidenceNode 都必须携带 `time_scope`。

建议结构：

```json
{
  "time_scope": {
    "year": 2024,
    "label": "2024 年",
    "granularity": "year",
    "confidence": "explicit"
  }
}
```

如果年份缺失，不允许默认猜测。应输出：

```json
{
  "time_scope": {
    "label": "未标注年份",
    "confidence": "missing"
  },
  "warnings": ["该来源未提供明确年份，回答时不能做跨年比较。"]
}
```

## 6. 旧数据库工具处理

旧的 `search_database_context` 和 `read_database_record` 不是目标 AI 查询能力，已经从主 AI 工具目录和外部工具目录移除。

主 AI 不再通过“查 MySQL 历史记录”回答 `/analysis` 用户问题。历史记录、artifact 和 Agent 会话摘要如果后续仍需要后台回溯，应作为后台管理或调试能力另建入口，不进入面向用户的工具规划链路。

以下能力必须由 scoped dataset 查询工具承担，不能通过旧数据库记录检索替代：

- 查询当前范围内所有 POI。
- 查询当前范围内人口 cell。
- 查询当前范围内夜光 cell。
- 查询当前范围内路网 feature。
- 对当前范围数据做字段过滤、TopN、分页和聚合。

原因是这些问题的产品边界不是“查数据库”，而是“查当前范围数据源”。实现上可以读取 `poi_results`、`analysis_artifacts`、运行时 artifacts 或其他存储，但工具接口必须隐藏这些内部差异。

后续替代目标能力是：

- `list_scope_datasets`
- `query_scope_dataset`
- `aggregate_scope_dataset`
- `read_scope_record`

这些工具应该只面向当前 `history_id`、当前范围、当前年份或数据版本，不暴露数据库表结构，也不允许 AI 扫描全库。

## 7. 回答规则

AI 使用当前范围数据源时必须遵守：

1. 只能描述“当前范围内”的数据，不能说查了整个库。
2. 具体 POI、cell、H3、路段必须来自查询结果或已读取的 EvidenceNode。
3. 年份不一致时必须说明，不得混合成同一结论。
4. 年份缺失时必须提示限制，不得进行跨年比较。
5. 数据库存储位置不能作为用户结论出现。用户应该看到的是来源、年份、指标和引用。
6. 全量 payload 不进入 prompt；AI 只能通过分页、聚合或单条读取工具获取必要证据。

## 8. 后续实现建议

后续实现 scoped dataset 查询时，建议新增独立 domain，例如 `modules/scope_datasets/`，由它负责：

- 从 `poi_results` 和 `analysis_artifacts` 发现当前范围数据源。
- 归一化不同 payload 的字段。
- 暴露白名单查询、聚合、分页和单条读取能力。
- 把查询结果转成 EvidenceNode。
- 在返回结果中携带年份、source_id、locator、citation 和 warnings。

这样可以保持路由层、Agent 工具层和存储层职责清楚：存储层只负责保存和读取，scope dataset 层负责把当前范围数据解释成可查询来源，Agent 只消费受控工具和 EvidenceNode。
