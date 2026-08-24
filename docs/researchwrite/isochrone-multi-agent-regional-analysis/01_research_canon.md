# Research canon

## Literature facts

1. 等时圈可将真实交通网络上的旅行时间转化为可达范围。Lahoorpoor 与 Levinson 使用 5、10、15 分钟步行等时圈评估车站入口变化对人口与就业可达性的影响，说明入口位置和网络结构会改变服务范围，圆形缓冲区不能替代网络可达范围。[1]
2. 多源城市空间数据需要在明确空间单元内完成投影、分辨率和统计口径对齐。Melchiorri 等构建全球城市中心数据库时，通过栅格对齐、分区统计和空间连接整合人口、夜光、可达性和环境变量，说明多源数据整合本身是方法环节，而非简单的数据拼接。[2]
3. 通用大语言模型缺少城市物理空间语料与专门空间认知能力。CityGPT 通过城市指令数据和 CityEval 评测城市语义、空间推理与综合任务，表明城市空间能力需要专门的数据和评价设计。[3]
4. PlanGPT 将本地数据库检索、规划领域数据与工具能力引入规划语言模型，支持“领域数据库能够改善规划任务适配”的研究方向，但其重点并非等时圈范围内的多源空间计算与长篇区域报告生成。[4]
5. 地理空间智能体可能生成直觉上合理但计算顺序错误的空间工作流。Spatial-Agent 将地理分析问题表示为可执行的概念转换图，并在地理空间基准上检验工作流正确性，说明空间报告生成不能只依赖自然语言推理。[5]
6. 层级智能体与专门地图工具可以降低复杂地理 API 带来的工具选择负担。MapAgent 将高层规划与地图工具执行分离，支持按专业角色和工具边界组织多智能体空间分析。[6]
7. 长篇报告生成存在“先写结论、后补引用”的风险。EFSG 在生成前封存证据池，并以句子级证据约束报告生成，说明检索、证据固定和成文之间需要明确阶段边界。[7]

## Experimental facts

1. 截至 2026-08-21，当前产品同时具有正常对话和完整报告两个 AI 入口。正常对话走项目内 `modules/agent` 主循环；完整报告由 68 个 N8N 节点编排，通用模型和 MCP 通讯运行在 Codex Harness 上。双运行时是当前实现状态，不是长期目标。
2. 当前十二单元契约已通过真实运行 `b8a2df1a-0e36-48a3-8f63-877b0014686f` 完成端到端验收：12 个专业决策单元、1 份统一蓝图、9 个章节、5 张数据图件以及有效 Markdown/DOCX 均已生成。该事实证明复杂成果链可执行，不证明城市空间智能体整体优于基线。

3. 历史动态路由实现曾生成 95 个 N8N 节点，并经历动态决策规划、证据路由和单元备忘录实验。节点数量是历史实现事实，不是当前架构，也不是方法贡献。
4. 2026-08-14 的历史成功运行 `825d012f-3585-4acf-babf-2e26bc94b80e` 完成了旧版 12 个固定分析步骤，数据库中保存了约 59,218 字符的 ready 报告和 4 个视觉资产。该事实只作为工程演进记录。
5. 历史运行的项目上下文包含 2,635 个 POI、1,294 个路网节点、1,354 条路网边、439 个人口网格、439 个夜光网格及多份项目文档。不同数据的年份、坐标类型、覆盖完整性和缺失原因并不完全一致。
6. 当前决策、章节和图件 Agent 的空间入口已收敛为 `analyze_spatial_question(history_id, question)`。可复用空间工具 Agent 负责理解问题、拆分子问题、选择证据域和空间关系，并通过 Codex Harness 按需多次调用内部 `compute_spatial_evidence`。后者支持 `scope`、`accessibility`、`direction`、`neighborhood`、`rank`、`relationship` 和 `inspect` 七种确定性计算关系，不接收问题，也不返回问题复述或自然语言结论。`accessibility` 在保存等时圈最大范围内使用 Valhalla 嵌套 contour 形成时间层。
7. 当前 GraphRAG 来源清单有 18 份 PDF。2026-08-18 的本地覆盖校验确认索引包含 18 个文档、265 个文本单元、9,177 个实体、11,939 条关系、504 个社区和 504 份社区报告；该事实只证明索引覆盖，不证明跨语言召回或综合答案质量。
8. 2026-08-18 的历史动态链路运行 `990025f2-685d-4b6d-ab8a-f51d21894b56` 因完整 `decision_unit` 在节点间丢失而失败；运行 `d4da9a3f-b663-403d-8760-11d32bb6158f` 生成了三个动态决策单元和三个零空间证据的有限备忘录，随后因蓝图 `decision_logic` 覆盖不完整而失败。这些失败属于历史架构演进证据，不代表当前十二单元 Harness-first 链路状态。
9. 第二次历史动态运行的空间工具失败源于远程 MySQL 访问被当时的 VPN/TUN 路由影响。该故障不能用于评价空间接口、Agent 策略或模型能力。
10. 当前项目已有 N8N 与 MultiCa 两类实现经验；观察上结构化工作流产出更完整，但尚未形成相同输入、模型、预算和重复次数下的公平比较数据。
11. 空间工具 Agent 面向七类证据域工作：POI供给、人口结构、夜间活动、路网结构、网络可达性、局部空间关系和具名空间对象。内部连接的 27 个原生指标绑定与 30 个目录策略是确定性实现能力，不是要求任何 Agent 从 57 项中先选一个。底层领域模块按证据域与空间关系确定具体度量，并在结果中披露实际指标供复核。
12. spatial-project MCP 当前注册 10 个工具，但通过阶段级 `enabled_tools` 形成不同可见面：决策、章节和图件 Agent 使用 `analyze_spatial_question`，并可通过 `read_spatial_evidence_result` 只读复核已持久化的 `computation_refs`；空间工具 Agent 只能看到 `compute_spatial_evidence`。正常对话当前注册 17 个项目内工具，其中 4 个范围数据集工具仍暴露较低层查询概念，后续应复用同一空间工具 Agent。
13. 空间计算、MCP 契约、空间工具 Agent 和报告 Harness 权限边界的相关测试已于 2026-08-21 通过。测试证明接口分层和确定性计算行为，不等于空间工具 Agent 的问题拆分与综合正确率已经得到实验评价。

## Model and system facts

1. 等时圈是分析范围，不等同于实际服务对象、真实使用者或市场需求。
2. 统一栅格用于跨数据源聚合与比较；POI 可保留点位并生成栅格化结果，H3 若启用则只是 POI 的一种可选六边形聚合方式，网格分辨率会影响空间异质性和边界效应。
3. POI、人口、路网和夜光分别描述设施分布、人口代理、网络结构与活动强度代理，不能互相替代。
4. 多智能体生成的规划解释属于模型输出，必须通过数据库重算、规则校验和专家评价验证。
5. 当前证据路由 Agent 每轮可选择一至三个相互独立的工具请求；真正的并行由 N8N 执行，存在参数依赖的请求跨轮串行。该限制只作用于取证，不限制研究和写作 Agent 的表达。
6. 当前成功运行只持久化研究框架、决策单元、决策备忘录、最小来源元数据、报告蓝图、报告节和最终产物；完整工具正文属于短期执行数据。该策略用于控制上下文和重复存储，其信息保真性仍需实验检验。

## Supervisor constraints

- 当前没有指定学校模板、基金类别、目标期刊或字数上限。
- 本稿按方法型、导师可读的研究 proposal 组织。
- 后续若转为开题报告或投稿论文，需要补充正式格式、作者信息、伦理与数据许可声明。

## Terminology definitions

| Canonical term | Definition | Avoided variants |
|---|---|---|
| 等时圈 | 从给定起点、出行方式和时间阈值出发，沿真实交通网络可到达的空间范围 | 服务半径、圆形缓冲区 |
| 多源空间数据库 | POI 点位及栅格化结果、人口、路网、夜光、统一栅格结果及项目空间数据的结构化集合；H3 聚合结果仅在启用 POI 专项分析时出现 | 大数据底座、全量城市数据 |
| 多源空间证据驱动智能体 | 智能体在项目范围约束下通过受控领域工具按需读取、计算、核验和引用多源空间证据，并将稳定判断复用于对话与复杂成果任务 | 智慧规划大脑、自动规划师 |
| 城市空间决策任务 | 围绕项目范围完成解释、比较、空间分析、证据核验、方案取舍和成果交付的任务集合 | 仅指报告生成 |
| 区域分析报告 | 围绕统一空间范围形成数据诊断、空间解释、边界条件与决策建议的结构化报告 | 自动规划成果、最终规划方案 |
| 证据可追溯性 | 智能体回答或成果中的事实与指标能够定位到数据集、查询、文档位置或计算结果 | 可信度 |
| 空间一致性 | 智能体任务使用的数据、计算与判断遵守相同范围、坐标、年份和统计口径 | 空间准确性 |

## Forbidden claims

- 不得写“系统已经显著提升区域分析报告质量”，除非完成预注册或明确协议下的重复对照实验。
- 不得写“生成结果等同于规划师结论”或“可以替代规划师”。
- 不得将单一长沙案例推广为跨城市普遍结论。
- 不得把 POI、夜光、人口或路网指标直接解释为消费需求、客流、因果机制或财务可行性。
- 不得以报告长度、节点数量或智能体数量单独证明质量。
- 不得用一次完整报告成功运行替代对正常对话、工具执行、空间分析和决策任务的独立评价。
- 不得把 MultiCa 的一次较弱产出解释为开放式多智能体方法普遍无效。

## Unresolved claims

- 多源空间数据库接入是否在匹配条件下提高报告事实正确性和规划可用性。
- 等时圈相较行政边界或圆形缓冲区是否改善报告的空间解释质量。
- 多智能体分工、状态持久化和质量门槛分别贡献多少增益。
- 方法能否迁移到不同城市、出行方式、时间阈值和项目类型。
- 专家评价与自动指标之间是否具有稳定相关性。

## References

1. Lahoorpoor, B. & Levinson, D. M. Catchment if you can: The effect of station entrance and exit locations on accessibility. *Journal of Transport Geography* 82, 102556 (2020). https://doi.org/10.1016/j.jtrangeo.2019.102556
2. Melchiorri, M. et al. The Multi-temporal and Multi-dimensional Global Urban Centre Database to Delineate and Analyse World Cities. *Scientific Data* 11 (2024). https://doi.org/10.1038/s41597-023-02691-1
3. Feng, J. et al. CityGPT: Empowering Urban Spatial Cognition of Large Language Models. arXiv:2406.13948 (2024). https://arxiv.org/abs/2406.13948
4. Zhu, H. et al. PlanGPT: Enhancing Urban Planning with Tailored Language Model and Efficient Retrieval. arXiv:2402.19273 (2024). https://arxiv.org/abs/2402.19273
5. Bao, R. et al. Spatial-Agent: Agentic Geo-spatial Reasoning with Scientific Core Concepts. *ACL 2026* (2026). https://arxiv.org/abs/2601.16965
6. Hasan, M. H. et al. MapAgent: A Hierarchical Agent for Geospatial Reasoning with Dynamic Map Tool Integration. arXiv:2509.05933 (2025). https://arxiv.org/abs/2509.05933
7. Gupta, S. & Bedi, J. EFSG: Evidence-First Structured Generation for Multilingual RAG Report Generation. *RAG4Reports 2026*, 99-102 (2026). https://doi.org/10.18653/v1/2026.rag4reports-1.14
