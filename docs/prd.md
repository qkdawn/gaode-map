## PRD：路网等时圈 + H3 网格化 + POI 数据 + 空间分析 Web 服务

> 目标：明确拆分“独立业务包”，确保核心逻辑与底层地图服务解耦，优先跑通核心链路。

---

### 1. 核心原则 (First Principles)
1.  **逻辑解耦 (Decoupling)**：核心算法（H3、几何计算）不依赖特定地图厂商 SDK。
2.  **坐标契约 (Coordinate Contract)**：
    *   **对外/前端交互**：统一使用 **GCJ02**（与高德/AMap 一致）。
    *   **内部逻辑/存储/分析**：统一使用 **WGS84**。
    *   仅在边界层进行 WGS84 <-> GCJ02 转换。
3.  **前端轻量化**：后端仅提供 JSON API，前端负责地图渲染逻辑 (Leaflet/Mapbox/AMap JS)。

---

### 2. 系统分层架构 (独立包结构)

系统分为 5 个逻辑层，物理上部署为 `gaode-map` (Python) 和 `search` (Java, 历史数据)。

#### A) 前端层 (Presentation Layer)
*   **定位**：`gaode-map/static` (Web App)
*   **职责**：
    *   SPA 风格应用 (Vue/Vanilla JS)。
    *   调用后端 REST API 获取 GeoJSON 数据。
    *   负责地图交互与图层叠加。

#### B) 等时圈服务层 (Isochrone Service)
*   **定位**：`gaode-map/modules/isochrone`
*   **职责**：提供“给定点在通过某种交通方式一定时间内能到达的区域”计算。
*   **解耦设计**：
    *   **Core API**：`get_isochrone_polygon(lat, lon, time, mode) -> WGS84 Polygon`
    *   **Adapter**：边界层处理 GCJ02 -> WGS84（调用引擎）-> WGS84 -> GCJ02（返回前端）。

#### C) 网格化服务层 (Grid H3 Service)
*   **定位**：`gaode-map/modules/h3`
*   **职责**：纯几何计算，不依赖任何地图 SDK。
*   **功能**：
    *   `polygon_to_hexagons(polygon_gcj02, resolution) -> [h3_index]`
    *   `enrich_hexagons(h3_indices, data_features)`

#### D) POI 数据层 (POI Data Service)
*   **定位**：`gaode-map/modules/poi` (数据管家)
*   **职责**：负责数据的获取、清洗、**双重落库**。
*   **工作流 (Workflow)**：
    1.  **Check Cache**: 查询 MySQL 是否有该不同参数(hash)的分析记录。如有，直接返回统计结果。
    2.  **Fetch & Transform**: 调高德 API -> 获 GCJ02 -> 转 **WGS84** 存库。
    3.  **Fast Return**: 优先返回 **GCJ02** 数据给前端渲染。
    4.  **Async Persistence**: **异步**将 POI 存入 MySQL。
        *   **Rule**: 使用 `amap_id` 进行**去重 (Upsert)**，防止数据冗余。
    5.  **Save Cache**: 计算统计指标 -> 存入 MySQL。

#### E) 分析服务层 (Spatial Analysis Layer)
*   **定位**：`gaode-map/modules/h3`、`gaode-map/modules/road`、`gaode-map/modules/export`
*   **职责**：接收网格化 POI 与路网数据，完成空间统计、空间句法与导出打包。

---

### 3. 用户交互流程 (Frontend Workflow)

1.  **初始化与输入**
    *   **核心交互**: 用户通过 **地点搜索 (POI Search)** 输入关键词（如“人民广场”），系统自动定位并设为中心点。
    *   **辅助交互**: 支持直接在地图上点击/拖拽微调中心点位置。
    *   设置参数：**等时圈时长** (如 15min)、**出行方式** (步行/驾车)。
    *   前端发起计算请求。

2.  **计算与反馈 (Progress Bar)**
    *   后端开始执行链式任务：`Isochrone` -> `Grid` -> `POI fetch` -> `Statistics`。
    *   前端显示**进度条** (Progress Bar)，实时反馈当前阶段 (由后端计算进度驱动)。

3.  **结果渲染**
    *   **地图主视图**：绘制生成的 **H3 六边形网格** (Hexagon Grid)。
    *   **POI 图层**：显示网格内的 POI 点位。支持按**分类** (Category) 筛选显示 (复用现有功能)。

4.  **空间分析与图表 (Right Sidebar)**
    *   界面提供“数据分析”功能区按钮。
    *   点击后触发分析计算 (如可达性评分、密度分布)。
    *   结果在**右侧边栏 (Right Sidebar)** 展示：
        *   统计图表 (ECharts/Chart.js)。
        *   摘要数据。

---

### 4. 交付物
1.  **Python Packages**: `isochrone`, `h3`, `poi`, `road`, `export`.
2.  **API Docs**: 定义清晰的 JSON 接口。
3.  **Java Service**: 仅作为历史数据仓库被调用。

---

### 5. 技术栈标准 (Technology Stack)
*   **前端**: 原生 HTML5 + Vanilla JS (ES Modules) + Tailwind CSS.
    *   **地图引擎**: 高德 JS API 2.0.
    *   **图表库**: ECharts.
*   **后端**: FastAPI (Python 3.10+).
    *   **核心计算**: `h3-py` (网格), `shapely` (几何).
    *   **空间分析**: **`PySAL`** (`esda`, `mgwr` - 空间计量/GWR).
*   **数据存储**:
    *   **MySQL**: 存储高德原始 POI 数据 (每次请求强制落库).
    *   **MySQL**: 存储分析缓存、Hash 签名与统计结果.
