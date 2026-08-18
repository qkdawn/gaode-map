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

1. 当前仓库的“城市更新决策支持 Agent”源码生成 95 个 N8N 节点。方法链路由动态决策规划、证据路由、受控串并行取证、单元研究备忘录、跨单元报告蓝图、分节写作、受限全局编辑、图件生成和报告投递组成。节点数量是实现事实，不是方法贡献。
2. 2026-08-14 的历史成功运行 `825d012f-3585-4acf-babf-2e26bc94b80e` 完成了旧版 12 个固定分析步骤，数据库中保存了约 59,218 字符的 ready 报告和 4 个视觉资产。该事实证明旧链路可运行，不证明当前动态链路已经通过端到端验收，也不证明生成质量优于基线。
3. 该次运行的项目上下文包含 2,635 个 POI、1,294 个路网节点、1,354 条路网边、439 个人口网格、439 个夜光网格及多份项目文档。不同数据的年份、坐标类型、覆盖完整性和缺失原因并不完全一致。
4. 当前模型侧空间数据入口已收敛为 `analyze_spatial_evidence`，支持 `scope`、`accessibility`、`direction`、`neighborhood`、`rank`、`relationship` 和 `inspect` 七种语义；旧 `project_context/query_data` 与直线距离分带 `distance` 不再作为模型工具。`accessibility` 在保存等时圈最大范围内使用 Valhalla 嵌套 contour 形成时间层。项目文档由 `read_project_document` 分页读取，文献由 `search_literature_evidence` 按需查询，实时互联网搜索与文献库保持独立。
5. 当前 GraphRAG 来源清单有 18 份 PDF。2026-08-18 的本地覆盖校验确认索引包含 18 个文档、265 个文本单元、9,177 个实体、11,939 条关系、504 个社区和 504 份社区报告；该事实只证明索引覆盖，不证明跨语言召回或综合答案质量。
6. 2026-08-18 的动态链路运行 `990025f2-685d-4b6d-ab8a-f51d21894b56` 因完整 `decision_unit` 在节点间丢失而失败；运行 `d4da9a3f-b663-403d-8760-11d32bb6158f` 生成了三个动态决策单元和三个零空间证据的有限备忘录，随后因蓝图 `decision_logic` 覆盖不完整而失败。两个根因均已在源码中修复并由相关测试覆盖，但数据库恢复后的完整运行尚未完成。
7. 第二次动态运行的空间工具失败源于远程 MySQL 访问被当前 VPN/TUN 路由影响。该故障不能用于评价空间接口、Agent 策略或模型能力。
8. 当前项目已有 N8N 与 MultiCa 两类实现经验；观察上结构化工作流产出更完整，但尚未形成相同输入、模型、预算和重复次数下的公平比较数据。

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
| 数据库增强多智能体方法 | 智能体通过受控工具读取、计算和引用多源数据库，而非只接收一次性文本摘要 | 数据驱动智能体、智慧规划大脑 |
| 区域分析报告 | 围绕统一空间范围形成数据诊断、空间解释、边界条件与决策建议的结构化报告 | 自动规划成果、最终规划方案 |
| 证据可追溯性 | 报告中的事实与指标能够定位到数据集、查询、文档位置或计算结果 | 可信度 |
| 空间一致性 | 报告使用的数据、计算与结论遵守相同范围、坐标、年份和统计口径 | 空间准确性 |

## Forbidden claims

- 不得写“系统已经显著提升区域分析报告质量”，除非完成预注册或明确协议下的重复对照实验。
- 不得写“生成结果等同于规划师结论”或“可以替代规划师”。
- 不得将单一长沙案例推广为跨城市普遍结论。
- 不得把 POI、夜光、人口或路网指标直接解释为消费需求、客流、因果机制或财务可行性。
- 不得以报告长度、节点数量或智能体数量单独证明质量。
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
