# 地图分析系统架构设计文档

基于 PRD，本文档详细定义了高德地图分析系统的技术实现细节。

## 1. 系统概览

本系统作为连接高精度地图数据（高德）与高级空间分析（PySAL/H3）的桥梁，并服务于轻量级前端。

### 核心原则
1.  **严格解耦 (Strict Decoupling)**：核心业务逻辑（网格/分析）绝不直接依赖地图供应商（高德）。
2.  **双坐标系契约 (Coordinate Contract)**：
    *   **对外/前端**：统一使用 **GCJ02**（与高德/AMap 一致）。
    *   **内部/存储/分析**：统一使用 **WGS84**。
    *   在边界层进行转换：进入系统时 GCJ02 → WGS84；返回前端时 WGS84 → GCJ02。
3.  **无状态后端 (Stateless Backend)**：Web 服务器 (FastAPI) 无状态，数据持久化存储在数据库中。

## 2. 技术栈标准

| 层级 | 组件 | 技术选型 | 理由 |
| :--- | :--- | :--- | :--- |
| **前端** | UI 框架 | **Vue 3 + TypeScript (Vite)** | 模块边界清晰，便于持续演进。 |
| | 样式 | **项目内样式系统（兼容层保留历史 CSS）** | 兼容迁移期与新前端并行。 |
| | 地图引擎 | **高德 JS API 2.0 (AMap)** | 国内数据覆盖最全。 |
| | 可视化 | **ECharts** | 强大的分析图表支持。 |
| **后端** | Web 框架 | **FastAPI** (Python 3.10+) | 高性能，原生支持异步。 |
| | 网格引擎 | **H3-py** | 业界标准的六边形网格算法。 |
| | 几何计算 | **Shapely** | 稳健的多边形/几何运算库。 |
| | 空间分析 | **PySAL** (`esda`, `mgwr`) | 科学严谨的空间计量经济学库。 |
| **数据** | 主存储 | **MySQL 8.0** | 持久化存储 POI 数据 (WGS84)。 |
| | 缓存/历史 | **MySQL** | 存储分析历史、去重 Hash、统计结果。 |

## 3. 模块设计 (Python Packages)

### 3.1 `modules.isochrone` (等时圈服务)
*   **职责**：生成可达性多边形。
*   **接口定义**：
    ```python
    def get_isochrone(center: PointWGS84, time_sec: int, mode: str) -> PolygonWGS84:
        # 1. API 输入默认 GCJ02 -> 转 WGS84
        # 2. 调用等时圈引擎 (Valhalla, WGS84)
        # 3. 返回 WGS84 多边形，出接口时再转回 GCJ02
    ```
*   **依赖**：`modules.providers.amap` (Provider 层统一封装)。

### 3.2 `modules.h3` (H3 网格服务)
*   **职责**：纯几何的空间分箱/填充逻辑。
*   **接口定义**：
    ```python
    def polyfill_polygon(polygon: PolygonGCJ02, resolution: int) -> List[str]:
        # 默认输入 GCJ02，多边形先转 WGS84 再做 H3 填充
        pass
    ```
*   **依赖**：`h3`, `shapely`. **严禁**依赖高德服务。

### 3.3 `modules.poi` (POI 数据服务)
*   **职责**：数据编排与流转。
*   **工作流**：
    1.  **查缓存**: 检查 MySQL 是否有该参数 Hash 的统计结果。
    2.  **Fetch & Transform**: 若未命中，调高德 API -> 获 GCJ02 -> **转 WGS84** 存库。
    3.  **Fast Return**: 优先将 **GCJ02 POI** 返回给前端（保证用户体验）。
    4.  **Background Task (异步落库)**:
        *   启动后台任务调用 `dao.save_pois_async(pois)`。
        *   **策略**: MySQL `UPSERT` (Insert on Duplicate Key Update)，使用 `amap_id` 作为唯一键进行**去重**。
    5.  **Save Stats**: 计算统计指标 -> 存入 MySQL。

### 3.4 `modules.road` / `modules.export` (空间分析与导出服务)
*   **职责**：科学计算。
*   **输入**: 带有聚合属性（如 POI 计数）的六边形列表。
*   **核心功能**:
    *   `calculate_kde()`: 核密度估计 (Kernel Density Estimation)。
    *   `run_gwr()`: 地理加权回归 (via PySAL)。

## 4. 数据模型

### 4.1 MySQL (持久层)
表名: `poi_data`
*   `id`: UUID
*   `amap_id`: String (唯一索引，用于去重)
*   `name`: String
*   `category`: String
*   `location`: Point (WGS84, 空间索引)
*   `properties`: JSON (存储额外属性)

### 4.2 MySQL (缓存/历史层)
表名: `analysis_history`
*   `hash`: String (参数 Hash: MD5 of center+time+mode)
*   `created_at`: Datetime
*   `result_stats`: JSON (例: `{"food": 50, "transport": 20}`)
*   `grid_data`: JSON (六边形的 GeoJSON 数据)

## 5. 目录结构（2026-03 规范化）

```text
gaode-map/
├── core/                    # 配置、异常、通用模型
├── router/                  # 路由聚合与依赖注入
├── modules/
│   ├── admin/
│   ├── isochrone/
│   ├── poi/
│   ├── h3/                  # H3 分析实现
│   ├── road/                # 路网分析实现
│   ├── export/              # 导出打包实现
│   └── providers/
│       └── amap/            # AMap Provider 实现
├── store/                   # 数据库与仓储
├── frontend/                # Vite + Vue3 + TS
├── templates/               # 兼容层模板
├── static/                  # 兼容层静态资源
└── tests/
    ├── api/
    ├── domain/
    ├── integration/
    └── e2e/
```

## 6. 前端架构 (Vite + Vue3 + TS)

*   `/analysis`：由 `frontend` 构建产物入口承载（`/static/frontend/index.html`）。
*   `frontend/src/main.ts`：Vue 应用入口。
*   `frontend/src/pages/analysis/App.vue`：analysis 页面壳与初始化流程（通过 `/api/v1/config` 拉配置）。
*   analysis 主链代码统一在 `frontend/src/features` 与 `frontend/src/map`。
*   旧模板入口 `templates/analysis.html` 与 `static/js/analysis/**` 已下线。
*   `/map` 页面仍保留兼容脚本：`static/js/map/*`（仅用于 map 模板链路）。
