"""
配置管理模块
使用Pydantic Settings从环境变量加载配置
"""

from pathlib import Path
from typing import List, Literal
from urllib.parse import quote_plus, urlsplit, urlunsplit
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    应用配置类
    从环境变量加载配置，支持类型转换和验证
    """

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # 未声明的 env 变量忽略，不抛出校验错误
    )

    # 应用配置
    app_host: str = "0.0.0.0"  # 应用主机地址，默认0.0.0.0（允许外部访问）
    app_port: int = 8000  # 应用端口，默认8000
    app_base_url: str = "http://localhost:8000"  # 基础URL，用于生成完整的访问链接

    # API密钥配置
    api_keys: List[str] = ["dev-only-key-change-in-production"]  # API密钥列表，用于访问鉴权

    # 文件存储配置
    static_dir: str = str(Path(__file__).resolve().parent.parent / "static")  # 静态资源根目录
    templates_dir: str = str(Path(__file__).resolve().parent.parent / "templates")  # Jinja模板目录
    template_name: str = "map_with_filters.html"  # 默认模板文件名
    file_lifetime_hours: int = Field(
        168,
        validation_alias="FILE_LIFETIME_HOURS",
        description="Generated file retention period in hours",
    )
    cleanup_interval_hours: int = Field(
        24,
        validation_alias="CLEANUP_INTERVAL_HOURS",
        description="Background cleanup interval in hours",
    )
    db_url: str = Field("", validation_alias="DB_URL", description="Database connection string")
    db_host: str = Field("", validation_alias="DB_HOST", description="Database host override")
    db_port: int = Field(13306, validation_alias="DB_PORT", description="Database port")
    db_user: str = Field("map_app", validation_alias="DB_USER", description="Database user")
    db_password: str = Field("", validation_alias="DB_PASSWORD", description="Database password")
    db_name: str = Field("gaode_deploy", validation_alias="DB_NAME", description="Database name")
    db_driver: str = Field("mysql+pymysql", validation_alias="DB_DRIVER", description="SQLAlchemy database driver")
    db_query: str = Field("charset=utf8mb4", validation_alias="DB_QUERY", description="Database URL query string")

    @property
    def sqlalchemy_database_uri(self) -> str:
        db_url = str(self.db_url or "").strip()
        db_host = str(self.db_host or "").strip()
        if db_host and db_url:
            db_url = self._replace_database_url_host(db_url, db_host, self.db_port)
        elif db_host:
            db_url = self._build_database_url_from_parts(db_host)
        if not db_url:
            raise ValueError("DB_URL is required, or configure DB_HOST with DB_USER/DB_PASSWORD/DB_NAME.")
        if db_url.lower().startswith("sqlite"):
            raise ValueError("SQLite is no longer supported. Configure DB_URL with mysql+pymysql://...")
        return db_url

    def _build_database_url_from_parts(self, host: str) -> str:
        if not str(self.db_password or "").strip():
            raise ValueError("DB_PASSWORD is required when DB_HOST is used without DB_URL.")
        user = quote_plus(str(self.db_user or ""))
        password = quote_plus(str(self.db_password or ""))
        database = str(self.db_name or "").strip().lstrip("/")
        query = str(self.db_query or "").strip().lstrip("?")
        url = f"{self.db_driver}://{user}:{password}@{host}:{int(self.db_port)}/{database}"
        return f"{url}?{query}" if query else url

    @staticmethod
    def _replace_database_url_host(db_url: str, host: str, port: int) -> str:
        parts = urlsplit(db_url)
        userinfo, sep, hostport = parts.netloc.rpartition("@")
        current_port = str(port or "")
        if not current_port and ":" in hostport:
            current_port = hostport.rsplit(":", 1)[1]
        next_hostport = f"{host}:{current_port}" if current_port else host
        next_netloc = f"{userinfo}{sep}{next_hostport}" if sep else next_hostport
        return urlunsplit((parts.scheme, next_netloc, parts.path, parts.query, parts.fragment))

    # 高德地图API配置
    amap_web_service_key: str = Field(
        "",
        validation_alias="AMAP_WEB_SERVICE_KEY",
        description="高德 Web 服务（Web API）Key，支持多个Key用英文逗号分隔",
    )
    amap_js_api_key: str = Field(
        "",
        validation_alias="AMAP_JS_API_KEY",
        description="高德 Web JS API Key",
    )
    amap_js_security_code: str = Field(
        "",
        validation_alias="AMAP_JS_SECURITY_CODE",
        description="高德 JS 安全码（若未开启可留空）",
    )
    tianditu_key: str = Field(
        "",
        validation_alias="TIANDITU_KEY",
        description="天地图 Web 瓦片服务 Key（tk）",
    )

    def model_post_init(self, __context) -> None:
        if not str(self.amap_js_api_key or "").strip() and str(self.amap_web_service_key or "").strip():
            self.amap_js_api_key = str(self.amap_web_service_key or "").split(",", 1)[0].strip()

    # AI Agent provider 配置
    ai_enabled: bool = Field(
        False,
        validation_alias="AI_ENABLED",
        description="是否启用 LLM provider（未启用时 Agent tool loop 不可用）",
    )
    ai_provider: Literal["deepseek", "openai_compatible"] = Field(
        "deepseek",
        validation_alias="AI_PROVIDER",
        description="Agent 使用的 AI provider 类型，支持 deepseek 或 openai_compatible",
    )
    ai_base_url: str = Field(
        "",
        validation_alias="AI_BASE_URL",
        description="LLM provider API 基础地址，例如 https://api.deepseek.com",
    )
    ai_api_key: str = Field(
        "",
        validation_alias="AI_API_KEY",
        description="LLM provider API Key",
    )
    ai_model: str = Field(
        "",
        validation_alias="AI_MODEL",
        description="Agent 使用的模型名，例如 deepseek-v4-flash",
    )
    ai_thinking_enabled: bool = Field(
        True,
        validation_alias="AI_THINKING_ENABLED",
        description="是否为 DeepSeek chat completions 启用 thinking mode 并流式展示 reasoning_content",
    )
    ai_timeout_s: int = Field(
        60,
        validation_alias="AI_TIMEOUT_S",
        description="AI provider 请求超时时间（秒）",
    )
    ai_max_context_turns: int = Field(
        12,
        validation_alias="AI_MAX_CONTEXT_TURNS",
        description="发送给 LLM tool loop 的最大历史轮次数",
    )
    ai_max_tool_steps: int = Field(
        8,
        validation_alias="AI_MAX_TOOL_STEPS",
        description="LLM tool-calling loop 最大工具步数",
    )
    ai_max_tool_errors: int = Field(
        2,
        validation_alias="AI_MAX_TOOL_ERRORS",
        description="LLM tool-calling loop 连续工具错误上限",
    )
    ai_max_replans: int = Field(
        2,
        validation_alias="AI_MAX_REPLANS",
        description="Agent 在审计未通过时允许重新规划的最大次数",
    )

    # 本地历史数据查询服务配置
    local_query_base_url: str = Field(
        "http://127.0.0.1:8001",
        validation_alias="LOCAL_QUERY_BASE_URL",
        description="本地历史数据查询服务地址",
    )
    local_query_coord_system: Literal["gcj02", "wgs84"] = Field(
        "gcj02",
        validation_alias="LOCAL_QUERY_COORD_SYSTEM",
        description="本地历史数据查询服务使用的坐标系（location 字段）",
    )

    # CORS跨域配置
    cors_origins: List[str] = ["*"]  # 允许访问的域名列表

    # 等时圈（Isochrone）配置
    valhalla_base_url: str = Field(
        "http://127.0.0.1:8002",
        validation_alias="VALHALLA_BASE_URL",
        description="Valhalla 路由引擎基础地址",
    )
    valhalla_timeout_s: int = Field(
        60,
        validation_alias="VALHALLA_TIMEOUT_S",
        description="Valhalla 请求超时时间（秒）",
    )
    overpass_endpoint: str = Field(
        "http://overpass/api/interpreter",
        validation_alias="OVERPASS_ENDPOINT",
        description="Local Overpass API endpoint",
    )
    overpass_query_timeout_s: int = Field(
        60,
        validation_alias="OVERPASS_QUERY_TIMEOUT_S",
        description="Timeout passed to Overpass QL [timeout] (seconds)",
    )
    overpass_http_timeout_s: int = Field(
        90,
        validation_alias="OVERPASS_HTTP_TIMEOUT_S",
        description="HTTP read timeout for Overpass request (seconds)",
    )
    overpass_retry_count: int = Field(
        1,
        validation_alias="OVERPASS_RETRY_COUNT",
        description="Retry times for Overpass timeout/runtime errors",
    )
    overpass_cache_ttl_s: int = Field(
        45,
        validation_alias="OVERPASS_CACHE_TTL_S",
        description="In-process cache TTL for Overpass responses (seconds)",
    )
    overpass_cache_max_entries: int = Field(
        16,
        validation_alias="OVERPASS_CACHE_MAX_ENTRIES",
        description="Maximum in-process cached Overpass query entries",
    )
    city_boundary_dir: str = Field(
        "/mapdata/boundaries",
        validation_alias="CITY_BOUNDARY_DIR",
        description="Directory containing local city boundary GeoJSON files",
    )
    population_data_dir: str = Field(
        str(Path(__file__).resolve().parent.parent / "runtime" / "population_data"),
        validation_alias="POPULATION_DATA_DIR",
        description="Directory containing population GeoTIFF files",
    )
    population_data_year: str = Field(
        "2026",
        validation_alias="POPULATION_DATA_YEAR",
        description="Population dataset year to read from the population data directory",
    )
    population_preview_max_size: int = Field(
        2048,
        validation_alias="POPULATION_PREVIEW_MAX_SIZE",
        description="Maximum preview PNG size for population raster outputs",
    )
    nightlight_data_dir: str = Field(
        "/mapdata/nightlight/processed",
        validation_alias="NIGHTLIGHT_DATA_DIR",
        description="Directory containing processed Black Marble GeoTIFF files and manifest",
    )
    nightlight_preview_max_size: int = Field(
        2048,
        validation_alias="NIGHTLIGHT_PREVIEW_MAX_SIZE",
        description="Maximum preview PNG size for nightlight raster outputs",
    )

    # ArcGIS HTTP bridge config
    arcgis_bridge_enabled: bool = Field(
        True,
        validation_alias="ARCGIS_BRIDGE_ENABLED",
        description="Whether ArcGIS HTTP bridge is enabled",
    )
    arcgis_bridge_base_url: str = Field(
        "",
        validation_alias="ARCGIS_BRIDGE_BASE_URL",
        description="ArcGIS bridge base URL",
    )
    arcgis_bridge_port: int = Field(
        18081,
        validation_alias="ARCGIS_BRIDGE_PORT",
        description="ArcGIS bridge port exposed by the host bridge service",
    )
    arcgis_bridge_token: str = Field(
        "",
        validation_alias="ARCGIS_BRIDGE_TOKEN",
        description="Shared token used in X-ArcGIS-Token header",
    )
    arcgis_bridge_timeout_s: int = Field(
        300,
        validation_alias="ARCGIS_BRIDGE_TIMEOUT_S",
        description="ArcGIS bridge request timeout in seconds",
    )
    arcgis_export_timeout_s: int = Field(
        600,
        validation_alias="ARCGIS_EXPORT_TIMEOUT_S",
        description="ArcGIS export timeout in seconds",
    )
    arcgis_export_max_mb: int = Field(
        512,
        validation_alias="ARCGIS_EXPORT_MAX_MB",
        description="Maximum export file size accepted from bridge (MB)",
    )
    arcgis_python_path: str = Field(
        "",
        validation_alias="ARCGIS_PYTHON_PATH",
        description="ArcGIS Python runtime path used by the host bridge",
    )
    arcgis_script_path: str = Field(
        "",
        validation_alias="ARCGIS_SCRIPT_PATH",
        description="ArcGIS H3 pipeline script path used by the host bridge",
    )
    arcgis_road_syntax_sdna_script_path: str = Field(
        "",
        validation_alias="ARCGIS_ROAD_SYNTAX_SDNA_SCRIPT_PATH",
        description="ArcGIS road syntax SDNA script path used by the host bridge",
    )

    # depthmapX CLI config
    depthmapx_cli_path: str = Field(
        "depthmapXcli",
        validation_alias="DEPTHMAPX_CLI_PATH",
        description="Executable path of depthmapXcli",
    )
    depthmapx_timeout_s: int = Field(
        300,
        validation_alias="DEPTHMAPX_TIMEOUT_S",
        description="Timeout for one depthmapXcli command (seconds)",
    )
    depthmapx_tulip_bins: int = Field(
        1024,
        validation_alias="DEPTHMAPX_TULIP_BINS",
        description="Tulip bins for segment tulip analysis (4-1024)",
    )
    road_syntax_global_edge_cap: int = Field(
        22000,
        validation_alias="ROAD_SYNTAX_GLOBAL_EDGE_CAP",
        description="Max input edges for global road-syntax major profile",
    )


settings = Settings()
