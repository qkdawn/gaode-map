# gaode-map

## 1. 当前状态
- 后端：FastAPI（`main.py`）
- 前端：Vue 3 + Vite（`frontend/`）
- Analysis 主链路：`/analysis`。开发态由 FastAPI 代理 Vite 源码页面，生产态返回镜像内 `static/frontend/index.html`
- Legacy：`/analysis-legacy` 已下线
- 运行时图表产物目录：`runtime/generated_charts/`
- 当前数据源、Agent 工具、空间分析和 N8N 链路见 [`docs/当前系统能力完整说明.md`](docs/当前系统能力完整说明.md)

## 2. 目录（核心）
- `core/`：配置、异常、通用模型；跨业务域共享空间工具集中在 `core/spatial.py`
- `router/`：HTTP 路由聚合（按 domain 拆分）
- `modules/`：业务域实现（`poi`/`population`/`nightlight`/`h3`/`road`/`isochrone`/`export`/`providers`）
- `store/`：数据库与仓储
- `frontend/`：前端源码（Vite 构建）
- `static/frontend/`：生产前端构建产物目录（由 Vite 输出，不提交）
- `runtime/`：运行时数据（图表、临时文件）
- `tests/`：`api` / `domain` / `integration` / `e2e`

## 3. 本地启动

### 3.1 后端依赖
```bash
cd /mnt/d/Coding/map_analyse/gaode-map
uv sync
# 或: pip install -r requirements.txt
```
- `uv sync` 负责安装/同步依赖
- 测试使用当前项目 Python 环境执行；WSL 可使用 `uv run pytest ...`，Windows 可使用 `.venv\Scripts\python.exe -m pytest ...`

### 3.2 前端开发
```bash
cd /mnt/d/Coding/map_analyse/gaode-map/frontend
npm install
npm run dev
```
- 开发入口：`http://localhost:8000/analysis`
- 后端在 `FRONTEND_MODE=dev` 时代理 Vite；Vite 直接读取 `frontend/src`
- 开发态不要先构建 `static/frontend/`，避免后端服务旧 bundle

### 3.3 启动服务
```bash
cd /mnt/d/Coding/map_analyse/gaode-map
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3.4 Docker 开发模式
```bash
cd /mnt/d/Coding/map_analyse/gaode-map
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```
- 开发入口：`http://localhost:8000/analysis`
- Compose 开发模式会启动 Vite dev server，并让 FastAPI 代理它；不需要、也不应该预先执行 `npm run build`
- `static/frontend/` 不参与开发路径

## 4. 访问入口
- `http://localhost:8000/analysis`：分析工作台。开发态代理 Vite，生产态服务构建产物
- `http://localhost:5678`：n8n 自动化控制面。首次启动需要创建本地 owner 账号
- `http://localhost:8000/map?...`：常规地图页
- `http://localhost:8000/docs`：OpenAPI 文档
- `http://localhost:8000/health`：健康检查

## 5. 主要接口（分析链路）
- `GET /api/v1/config`
- `GET /api/v1/system/readiness`
- `POST /api/v1/analysis/isochrone`
- `POST /api/v1/analysis/pois`
- `POST /api/v1/analysis/h3-grid`
- `POST /api/v1/analysis/h3-metrics`
- `POST /api/v1/analysis/road-syntax`
- `GET /api/v1/analysis/road-syntax/progress`
- `POST /api/v1/analysis/export/bundle`
- `GET /api/v1/analysis/history`
- `GET /api/v1/analysis/history/{id}`

## 6. 关键环境变量
- 配置优先级：后端代码只读取 `core/config.py` 中的 `settings`；本地默认值来自根目录 `.env`；Docker Compose 只覆盖容器网络和容器内挂载路径，不再承载第二套业务默认值。
- 地图：`AMAP_WEB_SERVICE_KEY`、`AMAP_JS_API_KEY`、`AMAP_JS_SECURITY_CODE`、`TIANDITU_KEY`
- 路网/等时圈：`DEPTHMAPX_CLI_PATH`、`OVERPASS_ENDPOINT`、`VALHALLA_BASE_URL`
- 人口分析：`POPULATION_DATA_DIR`、`POPULATION_PREVIEW_MAX_SIZE`
- 夜光分析：`NIGHTLIGHT_DATA_DIR`、`NIGHTLIGHT_PREVIEW_MAX_SIZE`
- 数据库：`DB_URL` 保存账号、密码、库名等稳定信息；`DB_HOST` 用于覆盖 `DB_URL` 中的主机地址。数据库公网 IP 是动态地址，启动前按当前可用 IP 更新 `.env` 里的 `DB_HOST`，不要在文档中写死具体 IP。
- 图表输出目录覆盖：`CHART_OUTPUT_DIR`（可选，默认 `runtime/generated_charts/`）
- `POST /api/v1/analysis/road-syntax` 不再接受 `depthmap_cli_path`；depthmapX CLI 路径只从 `DEPTHMAPX_CLI_PATH` 或系统 `PATH` 解析。

### n8n、RAG 数据库与 LLM
- n8n 使用独立的 `n8n-postgres` 保存工作流和执行状态，业务知识与分析运行状态保存到 `rag-postgres`。
- `rag-postgres` 使用 pgvector，并按文件名顺序执行 `docker/rag-db/init/*.sql`；bootstrap 也会幂等重放这些 schema 文件，已有数据卷不需要手工迁移。
- n8n main 与 worker 使用 Redis queue mode；二者必须共享同一个 `N8N_ENCRYPTION_KEY`，并分别由 `n8n-runners`/`n8n-worker-runners` 外部 runner sidecar 执行 Code 节点。
- 本地入口由 `N8N_PORT` 决定（本工作区当前为 `http://localhost:5680`），RAG PostgreSQL 调试端口默认是 `15432`。
- 生产环境必须替换 `.env.example` 中的 n8n/RAG 密码、加密密钥和 `N8N_WEBHOOK_API_KEY`，并配置真实 `N8N_WEBHOOK_URL`。

首次启动或工作流文件更新后执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/n8n_bootstrap.ps1
```

脚本会启动 n8n 基础设施、应用 RAG schema、把临时数据库和 Codex relay 凭据加密导入 n8n，并只导入下述两个正式工作流。`N8N_MANAGEMENT_API_KEY` 必须使用本实例 owner 创建的 API Key，bootstrap 只用它按明确 ID 删除本项目的旧工作流，不会执行全量删除。删除旧工作流也会删除它们在 n8n 内的 execution 历史，但 `rag-postgres` 中的分析任务、章节和报告不受影响。默认从本机 `%USERPROFILE%\\.codex\\config.toml` 与 `auth.json` 读取 Codex CLI 当前的 `openai_base_url`、模型和 `OPENAI_API_KEY`；也可以用 `CODEX_RELAY_BASE_URL`、`CODEX_RELAY_MODEL`、`CODEX_RELAY_API_KEY` 覆盖。临时明文凭据只存在于容器 `/tmp`，导入后立即删除，不进入仓库或日志。

`CSU` 是旧 Agent 配置中的一个 OpenAI-compatible `AI_BASE_URL` 示例，不是 n8n 的必需网关，也不会被新工作流自动调用。两个正式画布都直接展示 Codex `/responses` 调用、模型重排、CPU-only FastEmbed 的 768 维中英文向量和必要的校验节点，语言模型密钥不会交给 embedding 服务。

当前只保留两个正式工作流：

- `城市更新决策支持 Agent`：同一画布包含任务提交、状态查询、动态决策单元、证据路由、受控串并行工具调用、研究备忘录、综合成稿、报告保存和飞书交付。入口继续使用 `POST /webhook/api/v1/n8n/spatial-strategy` 和 `GET /webhook/api/v1/n8n/spatial-strategy/status`。
- `城市更新公共知识库`：同一画布包含 `POST /webhook/api/v1/n8n/kb/ingest`、公共来源校验、原文解析、分块、Embedding 校验和事务发布。只接受政策、规划指引、案例、统计和研究资料；`project_document` 与测试资料会被拒绝。

项目文档不进入 pgvector，通过 `read_project_document` 按需分页读取；空间数据统一通过 `analyze_spatial_evidence` 获取；GraphRAG 文献与实时互联网保持独立工具入口。

浏览器不直接持有 `N8N_WEBHOOK_API_KEY`。分析工作台中的“十二步空间决策”能力调用 FastAPI 的 `POST /api/v1/analysis/spatial-strategy/runs`，并轮询 `GET /api/v1/analysis/spatial-strategy/runs/{run_id}`；后端代理再向 n8n 注入密钥、租户和访问组。该能力只保留 n8n 服务执行入口。

`scripts/n8n_bootstrap.ps1` 会在宿主机启动 embedding 服务并等待模型健康，再运行生成工作流契约测试。公共资料入库和 Agent 查询使用同一模型编码；模型或维度变化时必须清空旧向量并重建，不能混用不同模型的向量。

### 人口数据目录
- 根目录 `.env` 维护本地宿主机目录，例如 `POPULATION_DATA_DIR=E:/PeopleData`、`NIGHTLIGHT_DATA_DIR=E:/NightlightData/processed`
- Docker 启动时通过 `POPULATION_DATA_HOST_DIR`、`NIGHTLIGHT_DATA_HOST_DIR`、`CITY_BOUNDARY_HOST_DIR` 把宿主机目录挂到容器内
- 容器内应用读取目录由 Compose 覆盖为 `/mapdata/population`、`/mapdata/nightlight/processed`、`/mapdata/boundaries`

### Readiness
- `GET /api/v1/system/readiness` 用于解释当前运行环境为什么“能跑 / 不能跑”
- 当前会返回 `depthmapx`、`chart_output_dir`、`population_data_dir`、`nightlight_data_dir`、`arcgis_bridge` 五类检查
- readiness 只做本地配置、目录和可执行文件解析检查，不做远程服务探活

## 7. 测试与仓库卫生
```bash
cd /mnt/d/Coding/map_analyse/gaode-map
uv run pytest
uv run pytest tests/domain/test_poi_query_limit.py
uv run pytest tests/domain
git diff --check
```
- 当前仓库默认通过 `pytest.ini` 使用 `-q -s -p no:cacheprovider`
- Windows 环境可将上面的 `uv run pytest` 替换为 `.venv\Scripts\python.exe -m pytest`
- 提交前检查 `git status --short` 和 `git diff --check`，确认提交内容不包含构建产物、运行时垃圾或意外的空白错误

## 8. 维护约束
- `router/*` 只保留 HTTP 边界、依赖注入和响应编排；采样、几何裁剪、坐标转换、缓存键生成等逻辑统一下沉到 `modules/*` 或 `core/*`。
- 共享空间逻辑统一收敛到 `core/spatial.py`，不要在 `population`、`nightlight`、`road`、`isochrone`、`poi` 中复制 polygon/坐标处理变体。
- 空间业务新增代码优先落到 `facade`、`dataset`、`render`、`aggregate`、`bridge`、`cache`、`geometry`、`overpass` 等现有子职责文件，不继续扩写热点单文件。
- `modules/road/core.py` 只保留 facade 编排；Depthmap 命令、指标统计、GeoJSON/WebGL 序列化、进度状态分别维护在 `depthmap.py`、`metrics.py`、`serialize.py`、`progress.py`。
- `modules/h3/analysis.py` 只保留 facade 编排；类别规则、统计计算、ArcGIS 桥接封装分别维护在 `category_rules.py`、`stats.py`、`arcgis_facade.py`。
- `modules/history/service.py` 是 history 业务规则入口；`store/history_repo.py` 只保留 CRUD/查询，不再承载覆盖、去重和坐标恢复策略。
- 修改热点文件时遵守 `docs/目录约束.md` 中的体量阈值；提交前确认变更不包含运行时垃圾和禁止提交的构建产物。

## 9. Docker
```bash
cd /mnt/d/Coding/map_analyse/gaode-map
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
- `docker-compose.yml` 是基础拓扑，默认使用镜像内代码和生产前端构建产物
- `docker-compose.dev.yml` 只覆盖开发差异：后端挂载源码并使用 `uvicorn --reload`，前端由 Vite dev server 提供，`/analysis` 由后端代理到 Vite
- `docker-compose.prod.yml` 只覆盖生产差异：设置重启策略
- `.env.example` 是本地配置模板；`docker-compose.yml` 依赖 `.env` 提供宿主机路径和业务配置，只在容器网络和容器内路径上做覆盖
- 生产镜像会在 Docker 多阶段构建中自动执行前端 `npm ci` 和 `npm run build`
- 运行容器直接加载镜像内的 `static/frontend/`，不依赖宿主机预先打包

### 9.1 构建产物约定
- `frontend/` 存放 Vue + Vite 源码
- `static/frontend/` 存放生产部署产物，由 Vite 输出
- `static/frontend/` 不提交到仓库；开发态不读取它，生产态通过 Docker 多阶段构建生成
