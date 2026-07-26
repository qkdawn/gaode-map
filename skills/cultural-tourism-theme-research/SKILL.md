---
name: cultural-tourism-theme-research
description: 基于项目原始材料、项目周边空间、POI 与空间搜算、档案和原始公开网页，完成可追溯的文旅资源、在地关系与主题调研。用于完整项目分析前的文旅、遗产、地方文化或目的地活化研究，尤其适用于需要检索项目周边真实文化网络、历史脉络和潜在协作对象的场景。
---

# Cultural Tourism Theme Research

完成项目调研，不把项目名称、著名资源或宣传口号当成主题结论。先读取 `references/research-workflow.md`、`references/specialist-workpacks.md`、`references/theme-decision-contract.md`、`references/external-research-protocol.md`、`references/research-coverage-ledger.md`、`references/web-discovery-protocol.md` 和 `references/prompt-completeness-contract.md`，再按其完整流程执行。

使用 `references/specialist-workpacks.md` 的 Codex 原生 Subagent 编排：工作包 1 先建立资源事实底稿，工作包 2 和 3 并行研究周边空间网络与历史社会关系，工作包 4 作唯一的主题裁决，工作包 5 和 6 依次完成空间与运营转译，工作包 7 独立审校。内部备忘录不替代最终主题报告。

## 执行步骤

1. **建立资源事实底稿。** 工作包 1 从项目原始材料提取八类资源、对象别名、地址、时间和约束，先形成提示词规定的资源表；不得跳过资源梳理而直接生成主题。
2. **并行研究关系。** 工作包 2 用项目范围、已保存 POI 与可用空间结果补充本体和周边资源的空间位置与关系；工作包 3 核验历史、社会、生产生活和地方价值关系。需要网页核验时，按 `web-discovery-protocol.md` 进行发现和正文追溯；检索记录用于补强来源和说明缺口，不是进入后续提示词阶段的资格条件。
3. **裁决主题。** 工作包 4 依据资源评分、关系网络、覆盖台账和主张登记表选择主题或作出“不形成单一主叙事”的裁决，并按 `theme-decision-contract.md` 写入主题判断图。事实结论不得越过其来源边界；资料不足项明确标为“待验证”，但不阻断后续策划假设。
4. **转译与审校。** 工作包 5 和 6 分别完成叙事空间结构、场景与运营转化；工作包 7 独立审校。随后复制 `assets/cultural-tourism-report-template.md` 到 `report/research/cultural-tourism-theme-research.md`，按顺序装配全部十二部分。对故事线、节点、游线、场景和运营逐项使用 `prompt-completeness-contract.md` 的字段验收；不得以总述、合并列或全局风险说明替代逐项内容。交付前同时运行 `scripts/validate_theme_delivery.py report/research/cultural-tourism-theme-research.md` 和 `scripts/validate_theme_decision_map.py report/research/cultural-tourism-theme-decision-map.json`；逐条回填失败项，直到通过；不得交付仍含 `[[TODO]]` 的报告。

## 输入与输出

作为 `spatial-business-analyst` 的前置依赖时，本 Skill 由 Agent 运行时显式启动，结果以 `cultural_tourism_research` artifact 回传；不得把已有同项目文件或历史运行时产物当作本轮完成信号。

读取项目原始材料、项目位置与空间范围、可用数据集和保护约束。先调用 `read_history_project`；`list_history_project_documents` 的成功结果在 `documents` 字段中，将其与 `read_history_project.documents` 互为清单回退来源。对每个原始 DOCX/PDF 使用 `get_history_project_document_resource` 获得 `spatial-document://` 资源，再读取二进制并用可用的 DOCX/PDF 解析能力提取正文。资源是原始文件，不是不可用证据；不得因目录工具失败就把可读取的原始文档写成“未取得”。只有资源读取或文档解析也失败时，才记录实际错误并降为待验证。

缺少项目位置、范围或原始材料时，先明确缺口，不能用公开网页猜测项目对象。

**项目身份隔离。** 若本轮无法读取项目原始材料正文，或正文未能明确项目本体身份，则坐标、等时圈、POI 名称和周边网页只能说明“范围背景”或“研究线索”，不能将附近机构、街道、地标或文保对象命名为项目本体，不能据此选择项目主叙事、项目级资源或项目定位。报告标题和第一部分必须写明“项目本体身份待验证”；外部对象按 `contextual_resource` 或 `research_lead` 进入背景研究。仍完成主题、场景和运营提出，但仅作为范围背景的 `H/V` 候选，且不得表示已适用于项目。只有原始项目材料、权属/文保建档或可定位的一手来源明确项目与对象的关系后，才能形成项目级主题和实施建议。

项目原始材料可作为其明确记载的资源、条件、约束和项目意图的直接证据，必须标注材料名称、章节或页码及其说明边界；不得把材料未明确记载的历史关系、当代活动或运营能力自行补足。POI 通常读取 `current:dataset:poi`；记录数据年份、保存时间、上游来源和查询范围。高德仅可作为快照的上游来源标识，本次调研不实时抓取高德 POI。使用 `query_history_project_dataset`、`aggregate_history_project_dataset`、`poi.supply_structure` 和 `poi.focused_accessibility` 时保留范围、年份、类别组、距离或时间阈值与数据来源。

网页检索优先使用 Exa MCP：用 `web_search_exa` 建立候选来源池，再用 `web_fetch_exa` 读取候选原页正文；仅在 Exa 无法读取、页面需要交互、附件无法解析或遇到验证码时才使用浏览器兜底。优先选择政府、统计、文保、地方志、馆藏、项目或经营主体的资料。搜索摘要、二手转述和无法打开的页面仅用于发现来源。外部网页不导入项目数据库，也不要求转成 `SourceRecord` 或 `EvidenceNode`。项目材料资源表必须先行建立；外部研究按 `references/research-workflow.md`、`web-discovery-protocol.md` 和 `external-research-protocol.md` 并行补强，不得取代或阻断提示词的资源梳理与后续转译。

保存调研底稿至：

```text
report/research/cultural-tourism-theme-research.md
report/research/cultural-tourism-theme-decision-map.json
```

每项进入判断的公开资料直接保留来源标题、链接、发布或更新日期（可见时）、访问日期、相关原文或数据定位、空间范围和可说明边界。每项空间观察保留数据源、年份、查询范围、类别与参数。将事实、空间观察、合理推断、策划假设和待验证事项明确区分。

## 交付范围

作为其他分析的输入时，交付提示词规定的八类资源表、评分、关系分析、主题转译和主题判断图；在项目范围或用户问题涉及周边关系时，再附覆盖台账、研究问题、检索日志、周边对象表和来源分级。外部研究提高事实判断强度，但不得阻断主题、场景或运营候选的提出；其缺口应成为候选的验证事项与风险。

历史调研底稿可用于发现线索和比较变化。本轮底稿以本轮完成的八类资源清单为依据。

## 与主分析的边界

本 Skill 可以独立交付完整调研报告。作为 `spatial-business-analyst` 的前置步骤时，主 Skill只将主题判断图和调研底稿中的真实对象、材料冲突、资源关系、候选主题、反例、保护或运营约束和待验证事项用于建立项目语义模型、问题地图和决策逻辑图。不得把主题、场景、业态或运营设想直接写成已确认的定位或决策。

所有阶段都必须执行。资料不足时，事实判断写“待验证”，同时仍完成后续主题、故事线、空间、场景和运营提出；将它们标为“合理推断”或“策划假设”，列明验证事项与风险。不得为了完成资源数量、主题数量或场景数量而编造事实，也不得把策划假设写成已确认事实。
