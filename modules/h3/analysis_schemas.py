from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from .schemas import GridResponse


class PoiLike(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    location: List[float] = Field(..., min_length=2, max_length=2, description="[lng, lat]")
    type: Optional[str] = None


class H3MetricsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    polygon: list = Field(
        ...,
        description="Polygon ring or multi-ring polygon coordinates",
    )
    resolution: int = Field(10, ge=0, le=15, description="H3 resolution")
    coord_type: Literal["gcj02", "wgs84"] = Field(
        "gcj02",
        description="Input coordinate system of polygon",
    )
    include_mode: Literal["intersects", "inside"] = Field(
        "intersects",
        description="Grid include strategy against source polygon",
    )
    min_overlap_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Minimum overlap ratio (0~1), used when include_mode=intersects",
    )
    pois: List[PoiLike] = Field(default_factory=list, description="POI list for aggregation")
    poi_coord_type: Literal["gcj02", "wgs84"] = Field(
        "gcj02",
        description="Coordinate system of POI locations",
    )
    use_arcgis: bool = Field(
        True,
        description="Deprecated. ArcGIS engine is always used and this field is ignored.",
    )
    arcgis_timeout_sec: int = Field(
        240,
        ge=30,
        le=1800,
        description="ArcGIS bridge timeout in seconds",
    )
    run_id: Optional[str] = Field(
        None,
        description="Optional progress run id for polling real-time H3 analysis progress",
    )


class H3AnalysisSummary(BaseModel):
    grid_count: int = Field(0, ge=0)
    poi_count: int = Field(0, ge=0)
    avg_density_poi_per_km2: float = 0.0
    avg_local_entropy: float = 0.0
    global_moran_i_density: Optional[float] = None
    global_moran_z_score: Optional[float] = None
    analysis_engine: Literal["arcgis"] = "arcgis"
    arcgis_status: Optional[str] = None
    spatial_statistics_method: Dict[str, Any] = Field(default_factory=dict)
    arcgis_report_maps: Dict[str, Any] = Field(default_factory=dict)
    gi_render_meta: Dict[str, Any] = Field(default_factory=dict)
    lisa_render_meta: Dict[str, Any] = Field(default_factory=dict)
    gi_z_stats: Dict[str, Any] = Field(default_factory=dict)
    lisa_i_stats: Dict[str, Any] = Field(default_factory=dict)


class CategoryDistribution(BaseModel):
    labels: List[str] = Field(default_factory=list)
    values: List[int] = Field(default_factory=list)


class DensityHistogram(BaseModel):
    bins: List[str] = Field(default_factory=list)
    counts: List[int] = Field(default_factory=list)


class H3AnalysisCharts(BaseModel):
    category_distribution: CategoryDistribution
    density_histogram: DensityHistogram


class H3MetricsResponse(BaseModel):
    grid: GridResponse
    summary: H3AnalysisSummary
    charts: H3AnalysisCharts


class H3ExportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: Literal["gpkg", "arcgis_package"] = Field(
        "gpkg",
        description="Export format: gpkg or arcgis_package(zip: lpk+mpk)",
    )
    include_poi: bool = Field(
        True,
        description="Whether POI points should be included in export layers",
    )
    style_mode: Literal["density", "gi_z", "lisa_i"] = Field(
        "density",
        description="Active style mode used to prepare exported rendering fields",
    )
    grid_features: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="H3 grid features (GeoJSON Feature list)",
    )
    poi_features: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="POI point features (GeoJSON Feature list)",
    )
    style_meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional render metadata from frontend (breaks/colors)",
    )
    arcgis_timeout_sec: int = Field(
        300,
        ge=30,
        le=3600,
        description="ArcGIS export timeout in seconds",
    )
