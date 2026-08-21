# 路网空间句法 Agent 工具架构

## 结论

路网不单独建立 Agent，也不为 `rank`、`neighborhood` 等操作分别建立 Agent。业务或章节 Agent 只调用现有空间工具 Agent；空间工具 Agent 通过一个确定性工具读取已经保存的路网分析结果。

```text
业务/章节 Agent
  -> analyze_spatial_question
  -> Spatial Tool Agent
  -> compute_spatial_evidence
  -> road 确定性执行器
  -> 已持久化 road_syntax 结果
```

## 数据模型

事实域只有四个：`poi`、`population`、`nightlight`、`road`。空间操作只有七个：`scope`、`accessibility`、`direction`、`neighborhood`、`rank`、`relationship`、`inspect`。具名道路和路段是 `inspect` 或 `rank` 返回的对象，不是事实域。

道路语义维度包括：

- `road.to_movement`：到达潜力，读取 NAIN。
- `road.through_movement`：穿行潜力，读取 NACH。
- `road.connectivity`：直接拓扑连接。
- `road.network_density`：单位空间道路长度。
- `road.orientation`：道路自身走向，只用于 `scope` 范围诊断。
- `road.quality`：拓扑、边界与结果质量，只用于 `scope` 范围诊断。

`rank` 和 `relationship` 必须显式指定维度，不能由工具在 Integration 与 Choice 之间猜测。

## 一次计算，多次读取

路网句法在正式分析任务中计算一次并保存为 `road_syntax` artifact。空间证据工具只读取以下持久化数据集，不触发 depthmapX 重算：

- `current:dataset:road_edges`：道路排序、道路拓扑邻域、道路核查。
- `current:dataset:road_corridors`：按同一半径 NAIN/NACH 上四分位线段及共享节点形成的连续廊道。
- `current:dataset:road_nodes`：节点度数和节点核查。
- `current:dataset:road_grid`：道路与人口、POI、夜光的共享格网关系。

1354 条道路和 1294 个节点保留为网络对象；439 个共享格网用于跨事实域共位、方向汇总和可达范围聚合。道路不会先被完全栅格化再做句法计算。句法先在线段网络上计算，之后才把结果按长度加权聚合到共享格网。

## 计算边界

depthmapX 输入使用以项目中心建立的本地米制坐标，局部半径按米解释。分析上下文在保存范围外扩最大局部半径，减少边界截断；最终道路结果仍裁切回用户保存范围并还原为 WGS84。

原始 depthmapX 值与渲染色阶分开保存。Agent 使用 NAIN/NACH 等分析字段，0–1 min-max 值只服务地图渲染和当前图内相对展示，不能作为跨项目或跨运行的可比较指标。

`rank` 默认以道路线段为对象。用户明确询问连续骨架或廊道时，Spatial Tool Agent 增加 `road.object=corridor`；密度排名使用共享格网，不能回退为线段总长度。`road.object` 只选择排名统计单元：线段支持 NAIN/NACH/连通性，廊道支持 NAIN/NACH，格网支持 NAIN/NACH/连通性/密度。节点核查由 `inspect` 的稳定 `record_ref` 指定，不再增加重复对象筛选。显式对象不存在时返回不可用，不静默替换对象。

路网质量结果包含连通分量、最大连通分量占比、端点、高连接节点、边界裁切线段和上下文/输出线段比例。NAIN/NACH 的 Node Count 与 Total Depth 原值随线段一起保存，便于复核标准化指标。

## 方法依据

- [depthmapX 官方说明](https://github.com/SpaceGroupUCL/depthmapX/blob/master/docs/about.md)：道路中心线可以直接作为 segment map 导入，并按角度、道路距离或线段步数执行网络分析。
- [Hillier、Yang 与 Turner（2012）](https://discovery.ucl.ac.uk/id/eprint/1389938/)：提出对 least-angle choice 等指标进行标准化，以支持不同规模空间系统之间的比较；本系统据此保留 NAIN/NACH 和它们的原始计算量。

因此，共享格网是句法计算后的跨域汇总与关系分析载体，不替代线段网络本身。
