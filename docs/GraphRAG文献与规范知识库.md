# GraphRAG 文献与规范知识库

这套知识库只承载开放获取论文和 UNESCO/ICOMOS 官方文件，不承载 POI、人口、路网、夜光、H3 或项目原文。空间数据库仍由原有空间分析工具负责。

## 采用的实现

使用 Microsoft GraphRAG（3.1.x）完成：

- 文本单元切分、实体与关系抽取；
- 图聚类与社区报告；
- Local Search（围绕具体实体及其邻接关系）；
- Global Search（跨社区主题综合）；
- DRIFT Search（社区摘要引导的多跳追问）。

原始 PDF 是文献事实源，PostgreSQL `kb_documents`/`kb_chunks` 只保留稳定 `source_id`、页码、章节和 URL 等定位信息，不重复承担这批资料的检索。GraphRAG 的实体、关系和社区摘要不能单独作为最终引用，最终引用必须回到原始 PDF 和页码/URL。

## 运行方式

GraphRAG 使用独立 Python 3.11/3.12 环境 `runtime/graphrag-venv`，避免把大型依赖装进地图后端：

```powershell
$workspace = 'runtime/graphrag-public-knowledge'
python -m venv runtime/graphrag-venv
& runtime/graphrag-venv/Scripts/python.exe -m pip install -r requirements-graphrag.txt
# 默认读取仓库根目录 .env 的 AI_BASE_URL、AI_MODEL、AI_API_KEY。
# 也可以用 GRAPHRAG_API_BASE、GRAPHRAG_CHAT_MODEL、GRAPHRAG_API_KEY 临时覆盖。
pwsh -File scripts/run_graphrag_public_knowledge.ps1 -Mode index
```

当前项目默认的语言模型网关是 `https://api.chat.csu.edu.cn/v1`，模型由 `.env` 的
`AI_MODEL` 决定（当前为 `DeepSeek-V4-Flash`）。Key 只从进程环境或本地 `.env` 读取，
不会写入 GraphRAG 配置或 Git。该网关如果返回 `403`，应先检查 Key 权限、来源 IP 和网关
访问策略；不要把 Key 复制到 `settings.yaml`。

直接维护或诊断 GraphRAG 时可以使用底层命令；章节 Agent 不接触这些实现模式：

```powershell
pwsh -File scripts/run_graphrag_public_knowledge.ps1 -Mode query -SearchMethod global -Query 'UNESCO 的 Historic Urban Landscape 原则在这些论文中如何被操作化？'
pwsh -File scripts/run_graphrag_public_knowledge.ps1 -Mode query -SearchMethod local -Query '哪些研究方法可以支持历史城区的等时圈分析？'
pwsh -File scripts/run_graphrag_public_knowledge.ps1 -Mode query -SearchMethod drift -Query '适应性再利用、步行可达性和街道活力之间有什么证据关系？'
```

GraphRAG 的模型和 API 地址应在工作区 `settings.yaml` 中配置为项目允许的 OpenAI-compatible endpoint；API key 只通过环境变量提供，不写入 Git 或知识库。

## N8N 接入边界

章节 Agent 通过 MCP 工具 `search_literature_evidence` 按需读取文献证据。`focused` 直接返回 GraphRAG 索引中的原文片段；`synthesis` 才执行完整跨文档综合。实时互联网继续由 `search_public_web` 和 `fetch_public_web_page` 独立处理，不与文献知识库合并。
N8N 只提交 `question`、`mode` 和 `top_k`，`history_id` 由工作流注入。后端在独立的
`runtime/graphrag-venv` 中执行查询，返回统一证据包；模型能看到文献标题、原文、稳定文本单元和页码估计，但看不到本地 PDF 路径、parquet、LanceDB 或模型配置。

`kb-retrieve` 不再作为这批文献的并行检索流程。空间事实仍走 POI/人口/路网/夜光/H3 工具，
不混入此 corpus。互联网最新证据仍通过章节 Agent 的 `search_public_web` 和
`fetch_public_web_page` 工具取得，和 GraphRAG 文献证据分开记录。
