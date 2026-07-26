# 分析蓝图、对象与工具边界

## 项目理解

主 Agent 从用户要求和授权原件提取：

- 明确目标；
- 多项材料共同支持的工作目标；
- 保护、安全、既有使用者和合规底线；
- 会改变规划选择的目标张力；
- 本轮需要回答的定位、客群、空间和运营问题。

未知收入、客流和投资目标不自动补值，也不阻止工作定位和可逆规划建议。

## 分析对象

按项目实际情况识别区域、比较空间单元、利益相关者、内容/服务/运营机制以及材料中出现的空间对象。先保留原始名称，再在 `project_semantic_model` 中赋予可多选的通用角色和关系。对象清单以材料事实为边界，只用于保证影响决策的对象得到覆盖，不能取代策略。

## 共同事实底稿

主 Agent 在分派前整理：

~~~text
项目目标与本体
→ 数据范围与期间
→ 人群和供给事实
→ 空间结构事实
→ 材料冲突与口径修正
→ 当前需要推进的决策
~~~

向 Subagent 只投影当前角色所需的事实、结果、对象关系和上游结论。`project_semantic_model` 与 `decision_inventory` 是内部编排契约，不作为最终报告章节或机器发布包展示。

问题地图确认后，所有正式报告使用 `$spatial-market-audience-research` 把人口、供给、外部可达、竞争和直接需求证据组织为目标客群与产品任务。定位、空间和运营初稿完成后，再由该 Skill 执行产品市场再校核。内部空间结构分析只处理项目入口、连接、停留、流线与承载，不重复外部客源圈判断。

## 数据到决策

每个重要判断形成：

~~~text
观察
→ 与什么比较
→ 可能机制
→ 对项目意味着什么
→ 当前规划动作
→ 简短边界
~~~

示例：

> 周边通用餐饮和购物供给集中，项目核心资产又具有不可复制的历史与空间特征。因此首期不复制大体量通用商业，而以核心资产内容建立差异化，用小体量日常服务延长使用。POI 只能说明设施供给，不能证明现有商户经营表现。

## 工具边界

### 项目与原件

- list_history_projects
- read_history_project
- list_history_project_documents
- get_history_project_document_resource
- list_history_project_datasets

原始 DOCX/PDF 必须通过 ResourceLink 读取。

### 已有结果与指标

- list_spatial_metric_results
- read_spatial_metric_result
- spatial_metric_catalog
- spatial_metric_detail
- execute_spatial_metric

先复用，后补缺口。指标只有在改变定位、空间或运营动作时才进入正文。

### 数据明细与空间查询

- query_history_project_dataset
- aggregate_history_project_dataset

邻近查询必须使用 spatial 条件。不要读取全量记录后本地估算距离或空间包含关系。

### 视觉

- check_arcgis_report_status
- create_spatial_report_visual
- get_spatial_report_visual_asset

视觉工具只生成和读取图，不判断地图是否正确。主 Agent 必须实际检查成图；失败时省略。

## 共同空间比较

跨 POI、人口、夜光和路网解释时，尽量使用共同范围、空间单元和时间口径。必须区分：

- 多项证据共同支持；
- 证据错位或冲突；
- 数据无覆盖；
- 现场仍需核实。

方向或距离矩阵不可用时，不发布虚构排名；可使用已成功取得的载体、网格、道路、服务范围和项目空间关系完成较低粒度判断。
