# 报告视觉工作流

本文件是报告视觉编排、插入、验收和失败降级的唯一事实来源。指标定义、算法参数和可解释边界由 `metric-selection.md`、`metric-catalog-index.yaml` 与 `metric-catalog.yaml` 拥有，本文件只引用，不复制。

## 独立视觉 Subagent

`formal_comprehensive` 正式综合报告每次都启动独立的视觉证据编辑 Subagent，即使最终选择零张视觉。简单问答、单项诊断和局部分析只在视觉会帮助回答当前问题时启动。

视觉 Subagent 只读取：

- 已通过 `validate_chapter_assembly.py` 的 `report/project-report.md`；
- 接受章节索引与 `decision_inventory`；
- 同一项目历史中已持久化的真实指标结果、数据范围和可用性；
- 当前已有视觉与资产清单。

它负责判断是否需要视觉、选择当前批准模板、确定视觉支持的判断与插入位置、形成计划并核验结果。它不得改写定位、章节正文或专业结论，不得补造指标、从 Markdown 猜数据、自写 Vega/Vega-Lite、SVG、文件路径或原始指标 payload。确定性工具负责取数和渲染，主 Agent 不替它选图或解释渲染失败。

## 视觉价值与零视觉

每个候选视觉必须回指一个已接受判断，并通过“删除后会改变相邻判断吗”检查。没有真实结果、批准模板、准确插入位置或明确决策价值时省略，不制作装饰图或占位图。

正式综合报告即使零图，也保存 `report/visual-plan.json` 和 `report/visual-manifest.json`。计划记录已完成评估但没有选择视觉；manifest 记录各候选的省略原因。零视觉是有效结果，不阻止 Markdown、HTML 或 PDF 交付。

## 指标与模板

先通过 `report_visual_template_catalog` 获取当前批准模板及输入契约，不把历史模板清单当成固定菜单。视觉涉及具体指标时，完整读取 `metric-selection.md` 和对应指标知识卡；所有空间范围、候选筛选、路由、速度、分钟、分组和几何规则以指标所有者为准，不在视觉提示词中另写一份。

视觉计划必须记录模板、准确位置、`statement_ref`、同一历史的持久化结果来源、支持与不能证明的事项、选图理由、生成或省略状态，以及目录允许的模板输入。渲染器只从持久化结果取数。

## 受控工具链

受限 Vega 报告视觉使用：

~~~text
report_visual_template_catalog
→ render_report_vega_visuals
→ get_report_vega_visual_asset
→ read_report_vega_visual_manifest
~~~

ArcGIS 报告地图使用：

~~~text
check_arcgis_report_status
→ create_spatial_report_visual
→ get_spatial_report_visual_asset
→ read_spatial_report_visual_manifest
~~~

两条链路相互独立，不能用 ArcGIS 工具代替受限 Vega 模板，也不能因为服务可用就认定成图正确。工具失败时保留文字判断并记录省略，不使用直线、猜测值、空白底图或其他替代视觉伪装成功。

## 插入与章节不可变性

正式综合报告的 `chapter:start` 与 `chapter:end` 标记之间必须逐字保留接受章节。视觉 Subagent 只能在章节边界之外，以及执行摘要、过渡或综合结论等主 Agent 可编辑区域插入视觉。

需要模板专属 `report-anchor` 时，视觉 Subagent 在所支持章节的结束标记之后创建锚点，再调用渲染器。不得在章节标记内部添加锚点、图片、题注或任何其他文本。简单报告没有接受章节不可变契约时，可以使用批准的正文语义锚点。

视觉生成后重新运行 `validate_chapter_assembly.py`。任何章节正文变化都阻止视觉验收和导出。

## 资产与验收

生成结果保存在 `report/assets/`，并更新 `report/visual-plan.json` 与 `report/visual-manifest.json`。每项生成或省略结果都必须可追溯到真实指标、模板版本、插入位置和相邻判断。

交付前必须读取实际资产和 manifest，检查：

- 真实要素、范围、图层、图例、方向、比例或距离参照符合模板语义；
- 标题、中文字体、轴标签、图例和题注清晰，没有乱码、裁切、遮挡或横向溢出；
- Markdown、HTML、PDF 及真实桌面、平板和移动视口能够解析相对 `assets/*`；
- 视觉没有把人口、POI、夜光、路网或其他代理升级为客流、消费、营收、合作或经营质量；
- 视觉没有改变接受章节正文，且确实支持相邻判断。

不满足时省略对应视觉并记录原因。视觉失败不能触发分析正文降级，也不能阻塞已有分析能够独立成立的报告。
