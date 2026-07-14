from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


class RoadSyntaxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = Field(
        None,
        description="Optional client run id for progress polling",
    )
    polygon: list = Field(
        ...,
        description="Output polygon ring or multi-ring polygon coordinates",
    )
    coord_type: Literal["gcj02", "wgs84"] = Field(
        "gcj02",
        description="Input coordinate system of polygon",
    )
    mode: Literal["walking", "bicycling", "driving"] = Field(
        "walking",
        description="Travel mode used to select highway classes",
    )
    graph_model: Literal["segment", "axial"] = Field(
        "segment",
        description="Graph model for road-syntax analysis: segment/axial",
    )
    highway_filter: Literal["mode", "all", "major"] = Field(
        "all",
        description="Road filtering strategy: mode=filter by travel mode, all=include all OSM highway classes, major=main roads only",
    )
    include_geojson: bool = Field(
        True,
        description="Whether to include road edge GeoJSON in response",
    )
    max_edge_features: int | None = Field(
        None,
        ge=100,
        le=5000,
        description="Maximum number of road edge features in GeoJSON output (null means no cap)",
    )
    merge_geojson_edges: bool = Field(
        True,
        description="Whether to merge adjacent road segments for rendering performance",
    )
    merge_bucket_step: float = Field(
        0.025,
        ge=0.005,
        le=0.2,
        description="Bucket step used when merging edges by accessibility score",
    )
    radii_m: List[int] = Field(
        default_factory=lambda: [600, 800],
        description="Local analysis radii in meters, e.g. [600, 800]",
    )
    metric: Literal["choice", "integration"] = Field(
        "choice",
        description="Default metric for frontend rendering",
    )
    tulip_bins: int | None = Field(
        None,
        ge=4,
        le=1024,
        description="Optional tulip angle bins override for depthmapX segment analysis",
    )
    use_arcgis_webgl: bool = Field(
        False,
        description="Whether to run ArcGIS bridge post-processing and return WebGL-ready road features",
    )
    arcgis_timeout_sec: int = Field(
        20,
        ge=5,
        le=3600,
        description="ArcGIS bridge timeout in seconds",
    )
    arcgis_metric_field: str | None = Field(
        None,
        description="Preferred metric field used by ArcGIS WebGL styling (e.g. accessibility_score)",
    )


class RoadSyntaxNode(BaseModel):
    node_id: str
    location: List[float] = Field(..., min_length=2, max_length=2, description="[lng, lat]")
    degree: int = 0
    closeness: float = 0.0
    choice: float = 0.0
    choice_raw: float = 0.0


class RoadSyntaxSummary(BaseModel):
    node_count: int = 0
    edge_count: int = 0
    rendered_edge_count: int = 0
    edge_merge_ratio: float = 1.0
    network_length_km: float = 0.0
    avg_degree: float = 0.0
    avg_closeness: float = 0.0
    avg_choice: float = 0.0
    avg_accessibility_global: float = 0.0
    avg_connectivity: float = 0.0
    avg_control: float = 0.0
    avg_depth: float = 0.0
    control_source_column: str = ""
    control_valid_count: int = 0
    depth_source_column: str = ""
    depth_valid_count: int = 0
    avg_intelligibility: float = 0.0
    avg_intelligibility_r2: float = 0.0
    avg_integration_global: float = 0.0
    avg_choice_global: float = 0.0
    avg_integration_local: float = 0.0
    avg_choice_local: float = 0.0
    avg_integration_by_radius: Dict[str, float] = Field(default_factory=dict)
    avg_choice_by_radius: Dict[str, float] = Field(default_factory=dict)
    radius_labels: List[str] = Field(default_factory=list)
    mode: str = "walking"
    coord_type: str = "gcj02"
    default_metric: str = "choice"
    default_radius_label: str = "global"
    analysis_engine: str = "depthmapxcli"
    road_orientation_analysis: Dict[str, Any] = Field(default_factory=dict)
    road_grid: Dict[str, Any] = Field(default_factory=dict)


class RoadSyntaxFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class RoadSyntaxNodeGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: List[float] = Field(default_factory=lambda: [0.0, 0.0], min_length=2, max_length=2)


class RoadSyntaxNodeProperties(BaseModel):
    node_id: str = ""
    degree: int = 0
    degree_score: float = 0.0
    integration_global: float = 0.0


class RoadSyntaxNodeFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: RoadSyntaxNodeGeometry = Field(default_factory=RoadSyntaxNodeGeometry)
    properties: RoadSyntaxNodeProperties = Field(default_factory=RoadSyntaxNodeProperties)


class RoadSyntaxNodeFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: List[RoadSyntaxNodeFeature] = Field(default_factory=list)
    count: int = 0


class RoadSyntaxScatterPoint(BaseModel):
    x: float = 0.0
    y: float = 0.0


class RoadSyntaxRegression(BaseModel):
    slope: float = 0.0
    intercept: float = 0.0
    r: float = 0.0
    r2: float = 0.0
    n: int = 0


class RoadSyntaxDiagnostics(BaseModel):
    intelligibility_scatter: List[RoadSyntaxScatterPoint] = Field(default_factory=list)
    regression: RoadSyntaxRegression = Field(default_factory=RoadSyntaxRegression)


class RoadSyntaxWebGLPayload(BaseModel):
    enabled: bool = False
    backend: str = "none"
    status: str = "disabled"
    metric_field: str = ""
    coord_type: str = "gcj02"
    roads: RoadSyntaxFeatureCollection = Field(default_factory=RoadSyntaxFeatureCollection)
    elapsed_ms: float = 0.0


class RoadSyntaxResponse(BaseModel):
    summary: RoadSyntaxSummary
    top_nodes: List[RoadSyntaxNode] = Field(default_factory=list)
    roads: RoadSyntaxFeatureCollection = Field(default_factory=RoadSyntaxFeatureCollection)
    road_edges: RoadSyntaxFeatureCollection = Field(default_factory=RoadSyntaxFeatureCollection)
    road_grid: RoadSyntaxFeatureCollection = Field(default_factory=RoadSyntaxFeatureCollection)
    nodes: RoadSyntaxNodeFeatureCollection = Field(default_factory=RoadSyntaxNodeFeatureCollection)
    diagnostics: RoadSyntaxDiagnostics = Field(default_factory=RoadSyntaxDiagnostics)
    webgl: RoadSyntaxWebGLPayload = Field(default_factory=RoadSyntaxWebGLPayload)
