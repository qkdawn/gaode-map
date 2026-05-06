from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field

class PoiRequest(BaseModel):
    polygon: list = Field(..., description="Polygon or multi-ring polygon payload (GCJ02)")
    keywords: str = Field(..., description="Search keywords, e.g. 'KFC|Starbucks'")
    types: str = Field(default="", description="POI Types code, optional")
    source: Literal["gaode", "local"] = Field(default="local", description="POI source")
    year: Optional[int] = Field(default=None, description="Year filter for local source")
    max_count: int = Field(default=0, description="Max number of POIs to return; 0 means no app-side limit")
    
    # History Context
    save_history: bool = Field(default=False, description="Whether to save the result to history")
    center: Optional[List[float]] = Field(None, description="Center point (GCJ02) [lng, lat]")
    time_min: Optional[int] = Field(None, description="Isochrone time")
    location_name: Optional[str] = Field(None, description="Name of the center location")
    mode: Optional[str] = Field("walking", description="Transport mode: walking, cycling, driving")

class PoiPoint(BaseModel):
    id: str
    name: str
    location: List[float] = Field(..., description="[lng, lat]")
    address: Optional[str] = None
    type: Optional[str] = None
    adname: Optional[str] = None
    year: Optional[int] = None
    lines: Optional[List[str]] = []

class PoiResponse(BaseModel):
    pois: List[PoiPoint]
    count: int


class PoiCategoryRequest(BaseModel):
    id: str = Field(..., description="Frontend category id")
    name: str = Field(default="", description="Category display name")
    types: str = Field(default="", description="Pipe-separated POI type codes")


class PoiMultiYearRequest(BaseModel):
    polygon: list = Field(..., description="Polygon or multi-ring polygon payload (GCJ02)")
    categories: List[PoiCategoryRequest] = Field(default_factory=list, description="Selected POI categories")
    years: List[int] = Field(default_factory=lambda: [2020, 2022, 2024], description="Requested POI years")
    max_count: int = Field(default=0, description="Max number of POIs per category fetch; 0 means no app-side limit")

    save_history: bool = Field(default=False, description="Whether to save the multi-year result to history")
    history_id: Optional[str] = Field(default=None, description="Existing history id to reuse when resaving")
    center: Optional[List[float]] = Field(None, description="Center point (GCJ02) [lng, lat]")
    time_min: Optional[int] = Field(None, description="Isochrone time")
    location_name: Optional[str] = Field(None, description="Name of the center location")
    mode: Optional[str] = Field("walking", description="Transport mode: walking, cycling, driving")


class PoiYearResult(BaseModel):
    year: int
    source: Literal["gaode", "local"] = "local"
    pois: List[dict] = Field(default_factory=list)
    count: int = 0


class PoiCategorySummaryRow(BaseModel):
    id: str
    name: str
    count: int = 0


class PoiYearSummary(BaseModel):
    year: int
    source: Literal["gaode", "local"] = "local"
    count: int = 0
    category_counts: Dict[str, int] = Field(default_factory=dict)


class PoiFetchError(BaseModel):
    year: int
    source: Literal["gaode", "local"] = "local"
    category: str
    error: str


class PoiMultiYearResponse(BaseModel):
    years: List[int] = Field(default_factory=list)
    selected_year: Optional[int] = None
    display_pois: List[dict] = Field(default_factory=list)
    results_by_year: List[PoiYearResult] = Field(default_factory=list)
    summary_by_year: List[PoiYearSummary] = Field(default_factory=list)
    category_summary: List[PoiCategorySummaryRow] = Field(default_factory=list)
    errors: List[PoiFetchError] = Field(default_factory=list)
    history_id: Optional[str] = None


class HistoryPoiYearResult(BaseModel):
    year: Optional[int] = Field(None, description="POI data year")
    source: Literal["gaode", "local"] = Field(default="local", description="POI source for this year")
    pois: List[dict] = Field(default_factory=list, description="POI records for the given year")


class HistorySaveRequest(BaseModel):
    history_id: Optional[str] = Field(
        default=None,
        description="Existing history id to reuse when resaving a restored history",
    )
    center: List[float] = Field(..., description="Center [lng, lat] (GCJ02)")
    polygon: list = Field(..., description="Polygon coordinates (GCJ02)") # Relaxed type to handle MultiPolygon if needed
    polygon_wgs84: Optional[list] = Field(
        default=None,
        description="Original history polygon coordinates (WGS84) preserved across restore/save",
    )
    drawn_polygon: Optional[List[List[float]]] = Field(
        default=None,
        description="Optional user-drawn polygon ring (GCJ02)"
    )
    pois: List[dict] = Field(..., description="List of POI objects")
    keywords: str = Field(default="")
    mode: str = Field(default="walking")
    time_min: int = Field(default=15)
    year: Optional[int] = Field(None, description="POI data year")
    years: Optional[List[int]] = Field(None, description="POI years already associated with this analysis")
    poi_results_by_year: Optional[List[HistoryPoiYearResult]] = Field(
        default=None,
        description="Optional multi-year POI snapshots to persist under the same history record",
    )
    location_name: Optional[str] = Field(None, description="Location name or coordinates for title")
    source: Optional[Literal["gaode", "local"]] = Field(default="local", description="POI source for this analysis")
    h3_result: Optional[dict] = Field(
        default=None,
        description="Deprecated snapshot payload field; accepted for compatibility and ignored on save",
    )
    road_result: Optional[dict] = Field(
        default=None,
        description="Deprecated snapshot payload field; accepted for compatibility and ignored on save",
    )
