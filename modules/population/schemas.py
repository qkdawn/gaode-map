from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PopulationBaseRequest(BaseModel):
    polygon: list = Field(..., description="Polygon ring or multi-ring polygon coordinates")
    coord_type: Literal["gcj02", "wgs84"] = Field("gcj02", description="Input coordinate system")
    year: str = Field("2026", description="Population dataset year")


class PopulationOverviewRequest(PopulationBaseRequest):
    pass


class PopulationGridRequest(PopulationBaseRequest):
    pass


class PopulationRasterRequest(PopulationBaseRequest):
    sex: Literal["total", "male", "female"] = Field("total")
    age_band: Literal[
        "all",
        "00",
        "01",
        "05",
        "10",
        "15",
        "20",
        "25",
        "30",
        "35",
        "40",
        "45",
        "50",
        "55",
        "60",
        "65",
        "70",
        "75",
        "80",
        "85",
        "90",
    ] = Field("all")
    scope_id: Optional[str] = Field(None, description="Optional scope cache key from overview")


class PopulationLayerRequest(PopulationBaseRequest):
    scope_id: Optional[str] = Field(None, description="Optional scope cache key from grid/overview")
    view: Literal["density", "sex", "age", "overview"] = Field("density")
    sex_mode: Literal["male", "female"] = Field("male")
    age_mode: Literal["ratio", "dominant"] = Field("ratio")
    age_band: Literal[
        "all",
        "00",
        "01",
        "05",
        "10",
        "15",
        "20",
        "25",
        "30",
        "35",
        "40",
        "45",
        "50",
        "55",
        "60",
        "65",
        "70",
        "75",
        "80",
        "85",
        "90",
    ] = Field("25")


class PopulationMetaResponse(BaseModel):
    sex_options: List[Dict[str, str]] = Field(default_factory=list)
    age_band_options: List[Dict[str, str]] = Field(default_factory=list)
    default_sex: str = "total"
    default_age_band: str = "all"
    default_year: str = "2026"
    year_options: List[str] = Field(default_factory=lambda: ["2024", "2025", "2026"])


class PopulationAgeDistributionItem(BaseModel):
    age_band: str
    age_band_label: str
    total: float = 0.0
    male: float = 0.0
    female: float = 0.0


class PopulationOverviewSummary(BaseModel):
    total_population: float = 0.0
    male_total: float = 0.0
    female_total: float = 0.0
    male_ratio: float = 0.0
    female_ratio: float = 0.0


class PopulationOverviewResponse(BaseModel):
    scope_id: str
    summary: PopulationOverviewSummary
    sex_totals: Dict[str, float] = Field(default_factory=dict)
    age_distribution: List[PopulationAgeDistributionItem] = Field(default_factory=list)


class PopulationSelectedDescriptor(BaseModel):
    sex: str
    sex_label: str
    age_band: str
    age_band_label: str


class PopulationRasterSummary(BaseModel):
    selected_population: float = 0.0
    selected_ratio_of_total: float = 0.0
    nonzero_pixel_count: int = 0
    max_pixel_value: float = 0.0


class PopulationLegendStop(BaseModel):
    ratio: float
    color: str
    value: float
    label: Optional[str] = None


class PopulationLegend(BaseModel):
    title: str = ""
    kind: Literal["continuous", "categorical"] = "continuous"
    unit: str = "人口"
    min_value: float = 0.0
    max_value: float = 0.0
    stops: List[PopulationLegendStop] = Field(default_factory=list)


class PopulationRasterResponse(BaseModel):
    scope_id: str
    selected: PopulationSelectedDescriptor
    summary: PopulationRasterSummary
    image_url: Optional[str] = None
    bounds_gcj02: List[List[float]] = Field(default_factory=list)
    legend: PopulationLegend


class PopulationGridResponse(BaseModel):
    scope_id: str
    year: str
    source: str
    cell_count: int = 0
    features: List[Dict[str, Any]] = Field(default_factory=list)


class PopulationLayerSelectedDescriptor(BaseModel):
    view: str
    view_label: str
    sex_mode: Optional[str] = None
    sex_mode_label: Optional[str] = None
    age_mode: Optional[str] = None
    age_mode_label: Optional[str] = None
    age_band: str = "all"
    age_band_label: str = "全年龄"
    unit: str = "人口"


class PopulationLayerCell(BaseModel):
    cell_id: str
    value: float = 0.0
    fill_color: str = "#f3f4f6"
    stroke_color: str = "#d1d5db"
    fill_opacity: float = 0.0
    label: str = ""


class PopulationLayerResponse(BaseModel):
    scope_id: str
    selected: PopulationLayerSelectedDescriptor
    summary: Dict[str, Any] = Field(default_factory=dict)
    legend: PopulationLegend
    cells: List[PopulationLayerCell] = Field(default_factory=list)
