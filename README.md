# gaode-map

## 1. 当前状态
- 后端：FastAPI（`main.py`）
- 前端：Vue 3 + Vite（`frontend/`）
- Analysis 主链路：`/analysis`。开发态由 FastAPI 代理 Vite 源码页面，生产态返回镜像内 `static/frontend/index.html`
- Legacy：`/analysis-legacy` 已下线
- 运行时图表产物目录：`runtime/generated_charts/`

## 2. 目录（核心）
- `core/`：配置、异常、通用模型；跨业务域共享空间工具集中在 `core/spatial.py`
- `router/`：HTTP 路由聚合（按 domain 拆分）
- `modules/`：业务域实现（`poi`/`population`/`nightlight`/`h3`/`road`/`isochrone`/`export`/`providers`）
- `store/`：数据库与仓储
- `frontend/`：前端源码（Vite 构建）
- `static/frontend/`：生产前端构建产物目录（由 Vite 输出，不提交）
- `runtime/`：运行时数据（图表、临时文件）
- `../scripts/check_repo_hygiene.sh`：仓库卫生检查
- `tests/`：`api` / `domain` / `integration` / `e2e`

## 3. 本地启动

### 3.1 后端依赖
```bash
cd /mnt/d/Coding/map_analyse/gaode-map
uv sync
# 或: pip install -r requirements.txt
```
- `uv sync` 负责安装/同步依赖
- 测试执行统一使用 `bash ../scripts/run_pytest.sh ...`，避免在 WSL/沙箱环境下依赖 `uv run pytest`

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
- `http://localhost:8000/map?...`：常规地图页
- `http://localhost:8000/docs`：OpenAPI 文档
- `http://localhost:8000/health`：健康检查

## 5. 主要接口（分析链路）
- `GET /api/v1/config`
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
- 地图：`AMAP_WEB_SERVICE_KEY`、`AMAP_JS_API_KEY`、`AMAP_JS_SECURITY_CODE`、`TIANDITU_KEY`
- 路网/等时圈：`DEPTHMAPX_CLI_PATH`、`OVERPASS_ENDPOINT`、`VALHALLA_BASE_URL`
- 人口分析：`POPULATION_DATA_DIR`、`POPULATION_PREVIEW_MAX_SIZE`
- 夜光分析：`NIGHTLIGHT_DATA_DIR`、`NIGHTLIGHT_PREVIEW_MAX_SIZE`
- 数据库：`DB_URL` 保存账号、密码、库名等稳定信息；`DB_HOST` 用于覆盖 `DB_URL` 中的主机地址。数据库公网 IP 是动态地址，启动前按当前可用 IP 更新 `.env` 里的 `DB_HOST`，不要在文档中写死具体 IP。
- 图表输出目录覆盖：`CHART_OUTPUT_DIR`（可选，默认 `runtime/generated_charts/`）

### 人口数据目录
- Docker 启动时，默认把宿主机 `E:/PeopleData` 挂到容器内 `/mapdata/population`
- Docker 启动时，默认把宿主机 `E:/NightlightData` 挂到容器内 `/mapdata/nightlight`
- 可通过 `POPULATION_DATA_HOST_DIR` 覆盖宿主机目录
- 容器内应用读取目录由 `POPULATION_DATA_DIR` 控制，默认 `/mapdata/population`
- 夜光处理后目录由 `NIGHTLIGHT_DATA_DIR` 控制，默认 `/mapdata/nightlight/processed`

## 7. 测试与仓库卫生
```bash
cd /mnt/d/Coding/map_analyse/gaode-map
bash ../scripts/run_pytest.sh
bash ../scripts/run_pytest.sh tests/domain/test_poi_query_limit.py
bash ../scripts/run_pytest.sh tests/domain
bash ../scripts/check_repo_hygiene.sh
```
- 当前仓库默认通过 `pytest.ini` 使用 `-q -s -p no:cacheprovider`
- `../scripts/run_pytest.sh` 会为每次运行设置独立的 Linux 临时目录和 `--basetemp`，减少 WSL/沙箱环境下的 capture 临时文件问题
- `../scripts/run_pytest.sh` 默认设置 `PYTHONDONTWRITEBYTECODE=1`，避免测试运行污染仓库内 `__pycache__/` 和 `*.pyc`

## 8. 维护约束
- `router/*` 只保留 HTTP 边界、依赖注入和响应编排；采样、几何裁剪、坐标转换、缓存键生成等逻辑统一下沉到 `modules/*` 或 `core/*`。
- 共享空间逻辑统一收敛到 `core/spatial.py`，不要在 `population`、`nightlight`、`road`、`isochrone`、`poi` 中复制 polygon/坐标处理变体。
- 空间业务新增代码优先落到 `facade`、`dataset`、`render`、`aggregate`、`bridge`、`cache`、`geometry`、`overpass` 等现有子职责文件，不继续扩写热点单文件。
- `modules/road/core.py` 只保留 facade 编排；Depthmap 命令、指标统计、GeoJSON/WebGL 序列化、进度状态分别维护在 `depthmap.py`、`metrics.py`、`serialize.py`、`progress.py`。
- `modules/h3/analysis.py` 只保留 facade 编排；类别规则、统计计算、ArcGIS 桥接封装分别维护在 `category_rules.py`、`stats.py`、`arcgis_facade.py`。
- `modules/history/service.py` 是 history 业务规则入口；`store/history_repo.py` 只保留 CRUD/查询，不再承载覆盖、去重和坐标恢复策略。
- 仓库卫生检查会校验热点文件体量阈值与运行时垃圾文件，提交前执行 `bash ../scripts/check_repo_hygiene.sh`。

## 9. Docker
```bash
cd /mnt/d/Coding/map_analyse/gaode-map
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
- `docker-compose.yml` 是基础拓扑，默认使用镜像内代码和生产前端构建产物
- `docker-compose.dev.yml` 只覆盖开发差异：后端挂载源码并使用 `uvicorn --reload`，前端由 Vite dev server 提供，`/analysis` 由后端代理到 Vite
- `docker-compose.prod.yml` 只覆盖生产差异：设置重启策略和生产 DB 默认 host
- 生产镜像会在 Docker 多阶段构建中自动执行前端 `npm ci` 和 `npm run build`
- 运行容器直接加载镜像内的 `static/frontend/`，不依赖宿主机预先打包

### 9.1 构建产物约定
- `frontend/` 存放 Vue + Vite 源码
- `static/frontend/` 存放生产部署产物，由 Vite 输出
- `static/frontend/` 不提交到仓库；开发态不读取它，生产态通过 Docker 多阶段构建生成
