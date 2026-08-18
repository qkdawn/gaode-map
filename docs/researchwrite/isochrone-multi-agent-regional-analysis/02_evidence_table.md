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
| 当前系统已实现动态决策单元、证据路由、单元备忘录和跨单元报告蓝图 | 当前 95 节点 workflow 生成器与契约测试 | evidence-backed | 方法、前期基础 | 尚未在数据库恢复后完成新版端到端成功运行 | evidence-backed |
| 空间分带已由中心直线距离改为 Valhalla 嵌套等时圈层 | `spatial_evidence.py`、严格 Valhalla contour 适配器、MCP/N8N 契约与领域测试 | evidence-backed | 方法、空间一致性 | contour 只能给出时间区间，仍受 Valhalla 路网版本和单元归类规则影响 | evidence-backed |
| 当前 GraphRAG 索引覆盖来源清单中的 18 份 PDF | `source_manifest.json` 与 2026-08-18 `verify_graphrag_index.py` 输出 | evidence-backed | 数据与知识库基础 | 覆盖完整不等于召回和综合正确 | evidence-backed |
| 动态链路能够在空间工具失败时避免伪造本地空间事实 | run `d4da...f8f` 的三个零证据 `decision_memo` | evidence-backed | 失败行为、风险控制 | 只有一次故障运行，且备忘录仍存在冗长的缺失说明 | evidence-backed |
| 动态决策分解能减少章节重复并提高论证递进 | 待完成固定十二步与动态单元的匹配对照 | hypothesis | 科学问题、实验 | 可能只是改变章节组织，不改变有效信息量 | hypothesis |
| 有界工作简报能在控制上下文的同时保留关键数字和具名对象 | 待测关键事实与名称召回率 | hypothesis | 方法、消融 | 压缩可能删除决定性细节 | hypothesis |
| 证据工具串并行能降低端到端取证时延 | 待记录串行与最多三路并行的时延和失败率 | hypothesis | 方法、性能实验 | 外部服务尾延迟和限流可能抵消收益 | hypothesis |
| 数据库增强方法将提高报告空间一致性和数值正确性 | 待完成基线与消融实验 | hypothesis | 科学问题、预期结果 | 可能受模型、提示词和案例难度影响 | hypothesis |
| 多智能体分工将提高跨维度分析完整性 | 待完成单智能体对照和专家盲评 | hypothesis | 研究目标、实验 | 可能只增加篇幅与成本 | hypothesis |
| 方法可迁移至不同城市和等时圈参数 | 待完成跨案例、跨阈值压力测试 | unsupported | 预期成果、风险 | 当前证据仅来自长沙案例 | unsupported |
