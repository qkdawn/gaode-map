from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class NightlightBaseRequest(BaseModel):
    polygon: list = Field(..., description="Polygon ring or multi-ring polygon coordinates")
    coord_type: Literal["gcj02", "wgs84"] = Field("gcj02", description="Input coordinate system")
    year: Optional[int] = Field(None, description="Nightlight dataset year; null means manifest default")


class NightlightOverviewRequest(NightlightBaseRequest):
    pass


class NightlightGridRequest(NightlightBaseRequest):
    pass


class NightlightRasterRequest(NightlightBaseRequest):
    scope_id: Optional[str] = Field(None, description="Optional scope cache key from overview")


class NightlightLayerRequest(NightlightBaseRequest):
    scope_id: Optional[str] = Field(None, description="Optional scope cache key from grid/overview")
    view: Literal["radiance", "hotspot", "gradient"] = Field("radiance")


class NightlightYearOption(BaseModel):
    year: int
    label: str


class NightlightMetaResponse(BaseModel):
    available_years: List[NightlightYearOption] = Field(default_factory=list)
    default_year: int = 0


class NightlightOverviewSummary(BaseModel):
    total_radiance: float = 0.0
    mean_radiance: float = 0.0
    max_radiance: float = 0.0
    lit_pixel_ratio: float = 0.0
    p90_radiance: float = 0.0
    valid_pixel_count: int = 0
    lit_pixel_count: int = 0


class NightlightOverviewResponse(BaseModel):
    scope_id: str
    year: int
    summary: NightlightOverviewSummary


class NightlightLegendStop(BaseModel):
    ratio: float
    color: str
    value: float
    label: Optional[str] = None


class NightlightLegend(BaseModel):
    title: str = ""
    kind: Literal["continuous", "categorical"] = "continuous"
    unit: str = "nWatts/(cm^2 sr)"
    min_value: float = 0.0
    max_value: float = 0.0
    stops: List[NightlightLegendStop] = Field(default_factory=list)


class NightlightSelectedDescriptor(BaseModel):
    year: int
    year_label: str
    view: str = "radiance"
    view_label: str = "夜光辐亮"
    unit: str = "nWatts/(cm^2 sr)"


class NightlightLayerAnalysis(BaseModel):
    core_hotspot_count: int = 0
    secondary_hotspot_count: int = 0
    emerging_hotspot_count: int = 0
    transition_count: int = 0
    low_light_count: int = 0
    hotspot_cell_ratio: float = 0.0
    peak_radiance: float = 0.0
    peak_cell_id: Optional[str] = None
    max_distance_km: float = 0.0
    core_band_count: int = 0
    middle_band_count: int = 0
    fringe_band_count: int = 0
    peak_to_edge_ratio: float = 0.0
    economic_activity_intensity_level: Literal["low", "medium", "medium_high", "high"] = "low"
    economic_activity_summary_text: str = ""
    sector_direction_analysis: Dict[str, Any] = Field(default_factory=dict)


class NightlightGridResponse(BaseModel):
    scope_id: str
    year: int
    cell_count: int = 0
    features: List[Dict[str, Any]] = Field(default_factory=list)


class NightlightLayerCell(BaseModel):
    cell_id: str
    value: float = 0.0
    valid_pixel_count: int = 0
    has_data: bool = False
    class_key: Optional[str] = None
    class_label: Optional[str] = None
    fill_color: str = "#0f172a"
    stroke_color: str = "#1f2937"
    fill_opacity: float = 0.0
    label: str = ""


class NightlightLayerResponse(BaseModel):
    scope_id: str
    year: int
    selected: NightlightSelectedDescriptor
    summary: NightlightOverviewSummary
    analysis: NightlightLayerAnalysis = Field(default_factory=NightlightLayerAnalysis)
    legend: NightlightLegend
    cells: List[NightlightLayerCell] = Field(default_factory=list)


class NightlightRasterResponse(BaseModel):
    scope_id: str
    year: int
    selected: NightlightSelectedDescriptor
    summary: NightlightOverviewSummary
    image_url: Optional[str] = None
    bounds_gcj02: List[List[float]] = Field(default_factory=list)
    legend: NightlightLegend
