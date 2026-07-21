# V4.1 决策问题与指标选择

## 单一规则

> 一个决策问题使用一个互补指标组合；一个指标只有在比较后改变行动，才值得进入报告。

指标组合的唯一知识来源是 metric-catalog.yaml 中的 decision_metric_bundles。不要把指标组合复制成新的报告流程或机器章节契约。

## 使用方式

1. 先确定 `decision_question`，再从目录选择最接近的组合；不要从已有数据反推章节。
2. 通过 `MetricToolService` 的 `catalog() → detail(tool_id) → execute(...)` 获取真实结果，已有 result ID 必须复用。
3. POI、人口、夜光、路网等跨源解释使用统一观察总体、共同空间单元、年份说明和比较基准。
4. finding 写清观察、比较基准、空间机制、决策影响和证据链接；可用 `metric_ids` 记录实际采用的指标，但 Python 不负责规划或裁决指标组合。
5. 删除某指标后，如果 finding、action 和 validation condition 都不变，就不把该指标写入公开报告。
6. 缺失直接数据时写 limitation 和验证条件，不用代理指标强行替代。
7. 年龄结构只使用 `population.age_structure`：返回完整五段、年份和占比，解释居住背景；不得把它改写成客流、支付能力或消费偏好。
8. 需要盘点经保存 15 分钟 walking 等时圈几何核验后的互补配套或同类对标结构时，先从已审校结论选择类别组，再执行 `poi.supply_structure`。每组必须包含 `group_id`、`title`、`role`、当前 POI 快照实际存在的 `type_codes` 与 `statement_ref`；`role` 只能是 `complementary_anchor` 或 `comparison_supply`，每个角色最多六组，且 typecode 不得跨组重复。工具从 `share/type_map.json` 解析真实主类／附属类，只统计被 15 分钟 walking Polygon/MultiPolygon `covers` 的 POI；若保存路网与项目几何中心可用，再补充不超过五分钟的连续道路可达数量。缺少路网或路径时保留等时圈数量并省略五分钟值，不用直线距离替代。
9. 需要在报告展示具体附近真实 POI、道路距离或路径时，再选择并执行 `poi.focused_accessibility`。它同样由已审校结论提供 `groups`（角色、类型组名称、当前快照存在的类别值或 typecode 前缀与必填 `statement_ref`）；工具以项目 Polygon/MultiPolygon 几何中心点为唯一 origin，在中心 2 km 内直线最近的 30 个候选上使用保存的 `current:dataset:road_edges` 建图、吸附并运行本地 Dijkstra 最短路径，最终仅返回不超过 15 分钟的连续道路路径。分钟按统一 4.5 km/h 参考步行速度换算；路径保留真实道路段的转折与曲线，不能以直线、Bezier、速度假设或 POI 数量替代。
10. 两个 POI 工具分工不可混用：`poi.supply_structure` 回答“当前 15 分钟范围内有什么供给结构”，`poi.focused_accessibility` 回答“哪些具体重点 POI 能沿真实道路到达”。两者都不决定项目定位、合作对象、客流、消费、营收、市场规模或综合评分。

## 主 Agent 审校

主 Agent 按 Skill 语义检查，而不是依赖 Python 指标调度器：

- 是否使用目录建议的互补指标，而非单指标罗列；
- 是否在同口径下比较；
- 是否同时解释支持、冲突和无覆盖；
- 是否真正改变空间、内容、运营或验证行动；
- 是否把人口、POI、夜光、路网误写成客流、消费、营收或 ROI。

Python 只保留通用职责：指标目录读取与执行、真实结果保存、资源授权和视觉数据准备。报告判断与写作由 Codex 主 Agent 和原生 Subagent 完成。
