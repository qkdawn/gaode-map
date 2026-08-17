# Evidence table

| Claim | Evidence/source | Strength | Usable section | Risk | Status |
|---|---|---|---|---|---|
| 等时圈能够比圆形缓冲区更真实地表达网络可达范围 | Lahoorpoor & Levinson 2020 [1] | evidence-backed | 背景、方法 | 车站场景不能直接等同所有城市更新项目 | evidence-backed |
| 多源空间数据需要统一空间范围、投影和统计单元 | Melchiorri et al. 2024 [2] | evidence-backed | 现状、方法 | 全球城市中心数据库与项目级等时圈尺度不同 | evidence-backed |
| 通用 LLM 的城市空间认知需要专门数据和评测 | CityGPT 2024 [3] | evidence-backed | 现状、科学问题 | 城市认知基准不等同长篇规划报告 | evidence-backed |
| 本地数据库检索和领域工具适用于规划语言任务 | PlanGPT 2024 [4] | plausible-inference | 现状、创新点 | 论文披露的任务与当前系统不完全相同 | plausible-inference |
| 地理空间智能体需要可执行工作流而非纯文本推理 | Spatial-Agent 2026 [5] | evidence-backed | 现状、方法 | 基准问答与区域报告生成存在任务差异 | evidence-backed |
| 层级多智能体有助于组织复杂地图工具 | MapAgent 2025 [6] | plausible-inference | 现状、方法 | 仍需在本研究任务上做消融 | plausible-inference |
| 证据先于成文有助于避免生成后补引用 | EFSG 2026 [7] | evidence-backed | 方法、创新点 | 现有句子级指标不能直接覆盖规划判断质量 | evidence-backed |
| 当前系统能够完成端到端区域分析报告生成 | 本地 run `825d...b80e`：12 步完成、报告 ready、4 张图 | evidence-backed | 前期基础、可行性 | 只有一个成功案例 | evidence-backed |
| 当前系统能够读取并保存结构化空间证据 | N8N 工作流、数据库 schema 与领域测试 | evidence-backed | 方法、可行性 | 能调用工具不等于正确使用工具 | evidence-backed |
| 数据库增强方法将提高报告空间一致性和数值正确性 | 待完成基线与消融实验 | hypothesis | 科学问题、预期结果 | 可能受模型、提示词和案例难度影响 | hypothesis |
| 多智能体分工将提高跨维度分析完整性 | 待完成单智能体对照和专家盲评 | hypothesis | 研究目标、实验 | 可能只增加篇幅与成本 | hypothesis |
| 方法可迁移至不同城市和等时圈参数 | 待完成跨案例、跨阈值压力测试 | unsupported | 预期成果、风险 | 当前证据仅来自长沙案例 | unsupported |
