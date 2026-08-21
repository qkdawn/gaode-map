from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.errors import GEOSException
from shapely.geometry import Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, transform
from shapely.strtree import STRtree

from core.poi_taxonomy import get_poi_taxonomy
from modules.providers.amap.utils.transform_posi import gcj02_to_wgs84
from modules.population.registry import age_band_keys, get_age_band_label
from modules.isochrone.adapter import ValhallaIsochroneUnavailable, fetch_valhalla_isochrone_contours
from modules.nightlight.service import get_nightlight_layer
from modules.road.metrics import build_road_orientation_analysis
from modules.scope_datasets.service import ScopeRecord
from modules.spatial_action.focused_poi_accessibility import (
    DEFAULT_WALKING_SPEED_M_PER_S,
    FocusedPoiAccessibilityService,
    FocusedPoiCandidate,
    FocusedPoiTypeGroup,
)
from modules.spatial_action.metric_tools import MetricToolService
from modules.spatial_action.road_network_routing import LocalRoadNetworkRouter, RoadNetworkRoutingUnavailable
from modules.spatial_action.source_index import SourceIndex
from modules.spatial_projects.service import SpatialProjectService
from modules.timeseries.population_series import get_population_timeseries
from modules.timeseries.nightlight_series import get_nightlight_timeseries


SCHEMA_VERSION = "spatial_evidence/v7"
DEFAULT_ISOCHRONE_TIME_MIN = 15.0
DEFAULT_TRAVEL_TIME_BANDS_MIN = ((0.0, 5.0), (5.0, 10.0), (10.0, 15.0))
DIRECTION_CODES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
DIRECTION_LABELS = {
    "N": "北",
    "NE": "东北",
    "E": "东",
    "SE": "东南",
    "S": "南",
    "SW": "西南",
    "W": "西",
    "NW": "西北",
}
POPULATION_AGE_BANDS = tuple(age_band_keys())
POPULATION_SEXES = ("total", "male", "female")
SELECTOR_DIMENSIONS = {
    "poi.category", "poi.subcategory", "population.sex",
    "population.age_band", "road.class", "road.radius", "road.object", "year",
}
NamedPoiRole = Literal["regional_anchor", "comparable_supply", "daily_service"]
_POI_ROLE_CATEGORIES: dict[NamedPoiRole, tuple[str, ...]] = {
    "regional_anchor": (
        "交通设施服务",
        "风景名胜",
        "科教文化服务",
        "政府机构及社会团体",
        "医疗保健服务",
        "体育休闲服务",
    ),
    "comparable_supply": (),
    "daily_service": (
        "生活服务",
        "医疗保健服务",
        "科教文化服务",
        "购物服务",
        "交通设施服务",
        "政府机构及社会团体",
        "体育休闲服务",
        "餐饮服务",
    ),
}
_POI_ROLE_TYPECODE_PREFIXES: dict[NamedPoiRole, tuple[str, ...]] = {
    "regional_anchor": ("15", "11", "14", "13", "09", "08"),
    "comparable_supply": (),
    "daily_service": ("07", "09", "14", "06", "15", "13", "08", "05"),
}
FORBIDDEN_OUTPUT_KEYS = {
    "geometry",
    "coordinates",
    "features",
    "featurecollection",
    "database",
    "connection",
    "file_path",
    "path",
}
MODEL_RESPONSE_CHAR_LIMIT = 24000
MODEL_STRING_CHAR_LIMIT = 1200
MODEL_LIST_ITEM_LIMIT = 20


def _poi_category_catalog() -> dict[str, tuple[str, str]]:
    catalog: dict[str, tuple[str, str]] = {}
    aliases = {
        "公司企业": "公司",
        "风景名胜": "旅游",
        "交通设施服务": "交通",
        "购物服务": "购物",
        "餐饮服务": "餐饮",
        "体育休闲服务": "体育",
        "医疗保健服务": "医疗",
        "住宿服务": "住宿",
        "政府机构及社会团体": "政府机构",
        "科教文化服务": "科教文化",
    }
    rules = get_poi_taxonomy().category_rules()
    labels = {label: (group_id, label) for group_id, label, _ in rules}
    for group_id, label, _ in rules:
        catalog[group_id.casefold()] = (group_id, label)
        catalog[label.casefold()] = (group_id, label)
    for alias, label in aliases.items():
        if label in labels:
            catalog[alias.casefold()] = labels[label]
    return catalog


_POI_CATEGORY_CATALOG = _poi_category_catalog()


def _resolve_poi_category(value: Any) -> tuple[str, str] | None:
    return _POI_CATEGORY_CATALOG.get(str(value or "").strip().casefold())


def _selected_poi_category(selectors: Sequence[Any]) -> tuple[str, str] | None:
    values = [
        value
        for selector in selectors
        if getattr(selector, "dimension", None) == "poi.category"
        for value in getattr(selector, "values", ())
    ]
    return _resolve_poi_category(values[0]) if len(values) == 1 else None

DATASET_FIELD_CATALOG = {
    "current:dataset:poi": {
        "dataset_id": "poi",
        "identity_fields": ["name", "category", "subcategory", "typecode", "address", "year", "source"],
        "measure_fields": [],
    },
    "current:dataset:h3": {
        "dataset_id": "h3",
        "identity_fields": ["h3_id", "year"],
        "measure_fields": [
            "poi_count", "density_poi_per_km2", "category_counts", "subcategory_counts",
            "local_entropy", "neighbor_mean_density", "neighbor_mean_entropy",
            "gi_star_z_score", "lisa_i",
        ],
    },
    "current:dataset:poi_grid": {
        "dataset_id": "poi_grid",
        "identity_fields": ["cell_id", "year"],
        "measure_fields": ["poi_count", "density_poi_per_km2", "category_counts", "dominant_category_name"],
    },
    "current:dataset:population": {
        "dataset_id": "population",
        "identity_fields": ["cell_id", "year", "source"],
        "measure_fields": ["population_total", "male_total", "female_total", "age_total", "age_male", "age_female"],
    },
    "current:dataset:nightlight": {
        "dataset_id": "nightlight",
        "identity_fields": ["cell_id", "year", "unit", "has_data", "source"],
        "measure_fields": ["radiance"],
    },
    "current:dataset:road_nodes": {
        "dataset_id": "road_nodes",
        "identity_fields": ["node_id"],
        "measure_fields": ["degree"],
    },
    "current:dataset:road_edges": {
        "dataset_id": "road_edges",
        "identity_fields": ["road_name", "road_class", "from_node", "to_node"],
        "measure_fields": [
            "length_m", "metrics.integration", "metrics.choice", "metrics.connectivity",
            "metrics.depth", "metrics.control", "integration_global", "choice_global",
            "nain_global", "nach_global", "nain_r600", "nach_r600", "nain_r800", "nach_r800",
            "node_count_global", "total_depth_global", "node_count_r600", "total_depth_r600",
        ],
    },
    "current:dataset:road_corridors": {
        "dataset_id": "road_corridors",
        "identity_fields": ["corridor_id", "metric", "radius", "road_names", "edge_count"],
        "measure_fields": [
            "length_m", "threshold", "mean_value", "max_value", "nain_global", "nach_global",
            "nain_r600", "nach_r600", "nain_r800", "nach_r800", "member_edge_ids",
        ],
    },
    "current:dataset:road_grid": {
        "dataset_id": "road_grid",
        "identity_fields": ["cell_id"],
        "measure_fields": [
            "road_length_km", "road_length_km_per_km2", "road_segment_count", "road_choice",
            "road_integration", "road_connectivity", "road_control", "road_depth",
            "road_nain", "road_nach",
        ],
    },
}


class SpatialEvidenceSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: Literal[
        "poi.category", "poi.subcategory", "population.sex",
        "population.age_band", "road.class", "road.radius", "road.object", "year",
    ]
    values: list[str | int] = Field(
        min_length=1,
        max_length=20,
        description=(
            "筛选值。poi.category 使用一个主业态；支持公司、旅游、交通、商务住宅、自然、购物、"
            "餐饮、体育、医疗、住宿、政府机构、科教文化及其高德主类名称。"
        ),
    )

    @model_validator(mode="after")
    def validate_domain_values(self) -> "SpatialEvidenceSelector":
        values = [str(value).strip().lower() for value in self.values]
        if self.dimension == "population.sex" and not set(values) <= set(POPULATION_SEXES):
            raise ValueError("population_sex_must_be_total_male_or_female")
        if self.dimension == "population.age_band" and not set(values) <= {"all", *POPULATION_AGE_BANDS}:
            raise ValueError("population_age_band_unsupported")
        if self.dimension == "poi.category":
            if len(self.values) != 1:
                raise ValueError("poi_category_requires_exactly_one_value")
            if _resolve_poi_category(self.values[0]) is None:
                raise ValueError("poi_category_unsupported")
        if self.dimension == "road.radius":
            if len(values) != 1:
                raise ValueError("road_radius_requires_exactly_1_value")
            if values[0] != "global" and re.fullmatch(r"r?[1-9]\d*", values[0]) is None:
                raise ValueError("road_radius_must_be_global_or_positive_metres")
        if self.dimension == "road.object":
            if len(values) != 1:
                raise ValueError("road_object_requires_exactly_1_value")
            if values[0] not in {"segment", "corridor", "grid"}:
                raise ValueError("road_object_unsupported")
        return self


class NamedRecordQuery(BaseModel):
    """Filter named spatial records without assigning project importance."""

    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1, max_length=80)
    dataset: Literal["poi", "road_edges"] = "poi"
    names: list[str] = Field(default_factory=list, max_length=20)
    text_query: str = Field(default="", max_length=200)
    categories: list[str] = Field(default_factory=list, max_length=20)
    subcategories: list[str] = Field(default_factory=list, max_length=20)
    typecodes: list[str] = Field(default_factory=list, max_length=20)
    within_record_refs: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=20)


FactDomain = Literal["poi", "population", "nightlight", "road"]
EvidenceDimension = Literal[
    "poi.supply",
    "poi.mix",
    "poi.category_specialization",
    "population.scale",
    "population.profile",
    "nightlight.intensity",
    "road.to_movement",
    "road.through_movement",
    "road.connectivity",
    "road.network_density",
    "road.orientation",
    "road.quality",
]

class SpatialDomainComputationRequest(BaseModel):
    """Domain-level spatial request; concrete indicators stay inside the service."""

    model_config = ConfigDict(extra="forbid")

    analysis: Literal["scope", "accessibility", "direction", "neighborhood", "rank", "relationship", "inspect"]
    fact_domains: list[FactDomain] = Field(default_factory=list, max_length=4)
    evidence_dimensions: list[EvidenceDimension] = Field(default_factory=list, max_length=8)
    selectors: list[SpatialEvidenceSelector] = Field(default_factory=list, max_length=8)
    travel_time_bands_min: list[tuple[float, float]] | None = Field(default=None, max_length=6)
    neighbor_steps: int = Field(default=1, ge=1, le=3)
    rank_order: Literal["highest", "lowest"] = "highest"
    top_k: int = Field(default=10, ge=1, le=20)
    record_refs: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_mode(self) -> "SpatialDomainComputationRequest":
        if len(set(self.fact_domains)) != len(self.fact_domains):
            raise ValueError("fact_domains_must_be_unique")
        if len(set(self.evidence_dimensions)) != len(self.evidence_dimensions):
            raise ValueError("evidence_dimensions_must_be_unique")
        if self.analysis in {"accessibility", "direction"} and not self.fact_domains:
            raise ValueError(f"{self.analysis}_requires_fact_domains")
        if self.analysis == "rank" and len(self.fact_domains) != 1:
            raise ValueError("rank_requires_exactly_1_fact_domain")
        if self.analysis == "relationship" and not 2 <= len(self.fact_domains) <= 4:
            raise ValueError("relationship_requires_2_to_4_fact_domains")
        if self.analysis in {"rank", "relationship"} and len(self.evidence_dimensions) != len(self.fact_domains):
            raise ValueError(f"{self.analysis}_requires_one_dimension_per_fact_domain")
        if self.analysis == "neighborhood" and (not self.fact_domains or not self.record_refs):
            raise ValueError("neighborhood_requires_fact_domains_and_record_refs")
        if self.analysis == "inspect" and not self.record_refs:
            raise ValueError("inspect_requires_record_refs")
        if self.analysis not in {"neighborhood", "inspect"} and self.record_refs:
            raise ValueError("record_refs_only_supported_for_neighborhood_or_inspect")
        if self.analysis != "accessibility" and self.travel_time_bands_min:
            raise ValueError("travel_time_bands_min_only_supported_for_accessibility")
        selected_poi_category = _selected_poi_category(self.selectors)
        if self.analysis == "accessibility" and "poi" in self.fact_domains and selected_poi_category is not None:
            explicit_poi_dimensions = {
                dimension
                for dimension in self.evidence_dimensions
                if EVIDENCE_DIMENSION_BINDINGS[dimension].domain == "poi"
            }
            if explicit_poi_dimensions and explicit_poi_dimensions != {"poi.supply"}:
                raise ValueError("poi_category_accessibility_requires_poi_supply_dimension")
        road_objects = {
            str(value).strip().lower()
            for selector in self.selectors
            if selector.dimension == "road.object"
            for value in selector.values
        }
        if road_objects and self.analysis != "rank":
            raise ValueError("road_object_only_supported_for_rank")
        if road_objects and self.fact_domains != ["road"]:
            raise ValueError("road_object_requires_road_fact_domain")
        if "segment" in road_objects and not set(self.evidence_dimensions) <= {
            "road.to_movement", "road.through_movement", "road.connectivity",
        }:
            raise ValueError("road_segment_rank_dimension_unsupported")
        if "corridor" in road_objects and not set(self.evidence_dimensions) <= {
            "road.to_movement", "road.through_movement",
        }:
            raise ValueError("road_corridor_rank_requires_movement_dimension")
        if "grid" in road_objects and not set(self.evidence_dimensions) <= {
            "road.to_movement", "road.through_movement", "road.connectivity", "road.network_density",
        }:
            raise ValueError("road_grid_rank_dimension_unsupported")
        selected_domains = set(self.fact_domains)
        if self.analysis in {"rank", "relationship"}:
            dimension_domains = [str(dimension).split(".", 1)[0] for dimension in self.evidence_dimensions]
            if set(dimension_domains) != selected_domains or len(set(dimension_domains)) != len(dimension_domains):
                raise ValueError(f"{self.analysis}_requires_one_dimension_per_fact_domain")
        for dimension in self.evidence_dimensions:
            owner = str(dimension).split(".", 1)[0]
            if owner not in selected_domains:
                raise ValueError(f"evidence_dimension_requires_fact_domain:{dimension}")
            capability = FACT_DOMAIN_CAPABILITIES.get(owner)
            if capability is None or dimension not in capability.dimensions:
                raise ValueError(f"unsupported_evidence_dimension:{dimension}")
            dimension_binding = EVIDENCE_DIMENSION_BINDINGS[dimension]
            if self.analysis not in dimension_binding.supported_analyses:
                raise ValueError(f"dimension_not_supported_for_{self.analysis}:{dimension}")
        _validate_travel_time_bands(self.travel_time_bands_min)
        return self


class SpatialEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: Literal["scope", "accessibility", "direction", "neighborhood", "rank", "relationship", "inspect"]
    metric_ids: list[str] = Field(default_factory=list, max_length=64)
    selectors: list[SpatialEvidenceSelector] = Field(default_factory=list, max_length=8)
    travel_time_bands_min: list[tuple[float, float]] | None = Field(default=None, max_length=6)
    neighbor_steps: int = Field(default=1, ge=1, le=3)
    rank_order: Literal["highest", "lowest"] = "highest"
    top_k: int = Field(default=10, ge=1, le=20)
    record_refs: list[str] = Field(default_factory=list, max_length=20)
    named_record_queries: list[NamedRecordQuery] = Field(default_factory=list, max_length=4)
    named_poi_roles: list[NamedPoiRole] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_mode(self) -> "SpatialEvidenceRequest":
        count = len(self.metric_ids)
        if self.analysis in {"accessibility", "direction"} and not 1 <= count <= 64:
            raise ValueError(f"{self.analysis}_requires_1_to_64_metrics")
        if self.analysis == "rank" and count != 1:
            raise ValueError("rank_requires_exactly_1_metric")
        if self.analysis == "relationship" and not 2 <= count <= 4:
            raise ValueError("relationship_requires_2_to_4_metrics")
        if self.analysis == "neighborhood" and (not 1 <= count <= 64 or not self.record_refs):
            raise ValueError("neighborhood_requires_metrics_and_record_refs")
        if self.analysis == "inspect" and not (self.record_refs or self.named_record_queries):
            raise ValueError("inspect_requires_record_refs_or_named_record_queries")
        if self.analysis not in {"neighborhood", "inspect"} and self.record_refs:
            raise ValueError("record_refs_only_supported_for_neighborhood_or_inspect")
        if self.analysis != "inspect" and self.named_record_queries:
            raise ValueError("named_record_queries_only_supported_for_inspect")
        if self.analysis != "accessibility" and self.travel_time_bands_min:
            raise ValueError("travel_time_bands_min_only_supported_for_accessibility")
        _validate_travel_time_bands(self.travel_time_bands_min)
        return self


def _validate_travel_time_bands(bands: Sequence[tuple[float, float]] | None) -> None:
    if not bands:
        return
    previous_end = 0.0
    for index, (start, end) in enumerate(bands):
        if start < 0 or end <= start or (index == 0 and start != 0) or start != previous_end:
            raise ValueError("travel_time_bands_min_must_start_at_zero_and_be_contiguous")
        previous_end = end


@dataclass(frozen=True)
class MetricBinding:
    metric_id: str
    label: str
    unit: str
    source_ids: tuple[str, ...]
    fields: tuple[str, ...]
    aggregate: Literal["sum", "mean", "max", "p90", "ratio_positive"]
    h3_native: bool = False
    supported_analyses: tuple[str, ...] = (
        "scope",
        "accessibility",
        "direction",
        "neighborhood",
        "rank",
        "relationship",
        "inspect",
    )


@dataclass(frozen=True)
class CatalogScopeBinding:
    """Explicit range-summary strategy for catalog metrics not native to this API."""

    metric_id: str
    source_ids: tuple[str, ...]


def _binding(
    metric_id: str,
    label: str,
    unit: str,
    source_ids: Sequence[str],
    fields: Sequence[str],
    aggregate: Literal["sum", "mean", "max", "p90", "ratio_positive"],
    *,
    h3_native: bool = False,
    supported: Sequence[str] | None = None,
) -> MetricBinding:
    return MetricBinding(
        metric_id=metric_id,
        label=label,
        unit=unit,
        source_ids=tuple(source_ids),
        fields=tuple(fields),
        aggregate=aggregate,
        h3_native=h3_native,
        supported_analyses=tuple(supported or MetricBinding.__dataclass_fields__["supported_analyses"].default),
    )


_POI = "current:dataset:poi"
_H3 = "current:dataset:h3"
_POI_GRID = "current:dataset:poi_grid"
_POPULATION = "current:dataset:population"
_NIGHTLIGHT = "current:dataset:nightlight"
_ROAD_NODES = "current:dataset:road_nodes"
_ROAD_EDGES = "current:dataset:road_edges"
_ROAD_CORRIDORS = "current:dataset:road_corridors"
_ROAD_GRID = "current:dataset:road_grid"


METRIC_BINDINGS = {
    item.metric_id: item
    for item in [
        _binding("poi.count", "POI 数量", "places", [_POI], ["__count__"], "sum"),
        _binding("poi.category_count", "POI 分类数量", "places", [_POI], ["__count__"], "sum"),
        _binding("poi.grid_count", "网格 POI 数量", "places", [_POI_GRID, _H3, _POI], ["poi_count"], "sum"),
        _binding("poi.grid_density", "POI 网格密度", "places/km2", [_POI_GRID, _H3, _POI], ["density_poi_per_km2", "density"], "mean"),
        _binding("poi.category_density", "POI 分类密度", "places/km2", [_POI_GRID, _H3, _POI], ["__category_density__"], "mean"),
        _binding("population.total", "总人口", "person", [_POPULATION], ["population_total"], "sum"),
        _binding("population.profile", "人口规模、性别与年龄结构", "profile", [_POPULATION], ["population_total"], "sum", supported=["scope"]),
        _binding("population.male", "男性总人口", "person", [_POPULATION], ["male_total"], "sum"),
        _binding("population.female", "女性总人口", "person", [_POPULATION], ["female_total"], "sum"),
        *[
            _binding(
                f"population.age.{band}.{sex}",
                f"{get_age_band_label(band)}{'总人口' if sex == 'total' else ('男性' if sex == 'male' else '女性')}",
                "person",
                [_POPULATION],
                [f"age_{sex}.{band}"],
                "sum",
            )
            for band in POPULATION_AGE_BANDS
            for sex in POPULATION_SEXES
        ],
        _binding("nightlight.mean_radiance", "平均夜光辐亮度", "nW/(cm2 sr)", [_NIGHTLIGHT], ["radiance"], "mean"),
        _binding("nightlight.total_radiance", "夜光辐亮度总量", "nW/(cm2 sr)", [_NIGHTLIGHT], ["radiance"], "sum"),
        _binding("nightlight.max_radiance", "最大夜光辐亮度", "nW/(cm2 sr)", [_NIGHTLIGHT], ["radiance"], "max"),
        _binding("nightlight.p90", "夜光 P90", "nW/(cm2 sr)", [_NIGHTLIGHT], ["radiance"], "p90"),
        _binding("nightlight.lit_pixel_ratio", "亮灯单元比例", "ratio", [_NIGHTLIGHT], ["radiance"], "ratio_positive"),
        _binding("road.network_size", "路网长度", "m", [_ROAD_GRID, _ROAD_EDGES, _ROAD_CORRIDORS], ["road_length_km", "length_m"], "sum"),
        _binding("road.network_density", "路网密度", "km/km2", [_ROAD_GRID], ["road_length_km_per_km2"], "mean"),
        _binding("road.connectivity", "路网连通性", "index", [_ROAD_GRID, _ROAD_EDGES], ["road_connectivity", "metrics.connectivity"], "mean"),
        _binding("road.control", "路网控制值", "index", [_ROAD_GRID, _ROAD_EDGES], ["road_control", "metrics.control"], "mean"),
        _binding("road.mean_depth", "路网平均深度", "index", [_ROAD_GRID, _ROAD_EDGES], ["road_depth", "metrics.depth"], "mean"),
        _binding("road.degree", "路网节点度数", "connections", [_ROAD_NODES], ["degree"], "mean"),
        _binding("road.nain", "标准化角度整合度 NAIN", "index", [_ROAD_GRID, _ROAD_EDGES, _ROAD_CORRIDORS], ["road_nain", "nain_global"], "mean"),
        _binding("road.nach", "标准化角度选择度 NACH", "index", [_ROAD_GRID, _ROAD_EDGES, _ROAD_CORRIDORS], ["road_nach", "nach_global"], "mean"),
        _binding("road.nain.selected_radius", "指定半径标准化角度整合度 NAIN", "index", [_ROAD_EDGES, _ROAD_CORRIDORS], ["selected_radius_nain"], "mean"),
        _binding("road.nach.selected_radius", "指定半径标准化角度选择度 NACH", "index", [_ROAD_EDGES, _ROAD_CORRIDORS], ["selected_radius_nach"], "mean"),
        _binding("poi.local_entropy", "POI 局部混合熵", "index", [_H3], ["local_entropy"], "mean", h3_native=True),
        _binding("poi.neighbor_mean_density", "邻域平均 POI 密度", "places/km2", [_H3], ["neighbor_mean_density"], "mean", h3_native=True),
        _binding("poi.neighbor_mean_entropy", "邻域平均混合熵", "index", [_H3], ["neighbor_mean_entropy"], "mean", h3_native=True),
        _binding(
            "poi.category_lq",
            "所选 POI 业态区位商",
            "index",
            [_H3],
            ["selected_category_lq"],
            "mean",
            h3_native=True,
        ),
        _binding("spatial.gi_star", "Getis-Ord Gi*", "z-score", [_H3], ["gi_star_z_score", "gi_star_value"], "mean", h3_native=True),
        _binding("spatial.lisa", "局部 Moran", "index", [_H3], ["lisa_i", "lisa_z_score"], "mean", h3_native=True),
        _binding("spatial.lisa_z", "局部 Moran z 值", "z-score", [_H3], ["lisa_z_score"], "mean", h3_native=True),
        _binding("spatial.neighbor_density_delta", "网格相对邻域密度差", "places/km2", [_H3], ["__neighbor_delta__"], "mean", h3_native=True),
    ]
}

# These metrics are executed by the existing domain metric executor, but are
# intentionally registered here one by one.  The model still sees only the
# semantic spatial-evidence contract; no alternate request shape is exposed.
CATALOG_SCOPE_BINDINGS = {
    item.metric_id: item
    for item in [
        CatalogScopeBinding("poi.multi_year_count", (_POI,)),
        CatalogScopeBinding("poi.local_entropy_normalized", (_POI_GRID, _H3, _POI)),
        CatalogScopeBinding("spatial.global_moran_i_density", (_H3, _POI_GRID)),
        CatalogScopeBinding("grid.type", (_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT, _ROAD_GRID)),
        CatalogScopeBinding("grid.opportunity_flag", (_H3,)),
        CatalogScopeBinding("nightlight.total_radiance", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.mean_radiance", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.max_radiance", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.p90", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.lit_pixel_ratio", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.hotspot_class", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.hotspot_ratio", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.spatial_profile", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.sector_profile", (_NIGHTLIGHT,)),
        CatalogScopeBinding("nightlight.activity_level", (_NIGHTLIGHT,)),
        CatalogScopeBinding("road.node_degree", (_ROAD_NODES, _ROAD_EDGES, _ROAD_GRID)),
        CatalogScopeBinding("road.orientation", (_ROAD_EDGES, _ROAD_GRID)),
        CatalogScopeBinding("road.intelligibility", (_ROAD_EDGES, _ROAD_GRID)),
        CatalogScopeBinding("isochrone.reachable_area", (_ROAD_EDGES,)),
        CatalogScopeBinding("timeseries.population_change", (_POPULATION,)),
        CatalogScopeBinding("timeseries.population_density_change", (_POPULATION,)),
        CatalogScopeBinding("timeseries.age_shift", (_POPULATION,)),
        CatalogScopeBinding("timeseries.nightlight_change", (_NIGHTLIGHT,)),
        CatalogScopeBinding("timeseries.hotspot_shift", (_NIGHTLIGHT,)),
        CatalogScopeBinding("gwr.nightlight_spatial_model", (_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT)),
        CatalogScopeBinding("gwr.model_fit", (_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT)),
        CatalogScopeBinding("poi.kernel_density", (_POI_GRID, _H3, _POI)),
        CatalogScopeBinding("poi.open_close_rate", (_POI,)),
        CatalogScopeBinding("access.network_reachable_area", (_ROAD_EDGES,)),
        CatalogScopeBinding("spatial.thematic_visual", ()),
        CatalogScopeBinding("report.decision_visual", ()),
        CatalogScopeBinding("regional.directional_evidence_matrix", (_POI, _POPULATION, _NIGHTLIGHT, _ROAD_EDGES, _ROAD_GRID)),
        CatalogScopeBinding("poi.supply_structure", (_POI, _ROAD_EDGES)),
        CatalogScopeBinding("poi.focused_accessibility", (_POI, _ROAD_EDGES)),
    ]
}


@dataclass(frozen=True)
class FactDomainCapability:
    domain: FactDomain
    label: str
    description: str
    source_ids: tuple[str, ...]
    supported_analyses: tuple[str, ...]
    dimensions: tuple[EvidenceDimension, ...]


@dataclass(frozen=True)
class EvidenceDimensionBinding:
    dimension: EvidenceDimension
    domain: FactDomain
    label: str
    description: str
    supported_analyses: tuple[str, ...]


_ALL_SPATIAL_ANALYSES = (
    "scope", "accessibility", "direction", "neighborhood", "rank", "relationship", "inspect",
)


EVIDENCE_DIMENSION_BINDINGS: dict[EvidenceDimension, EvidenceDimensionBinding] = {
    item.dimension: item
    for item in [
        EvidenceDimensionBinding("poi.supply", "poi", "设施供给", "设施数量和空间密度", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding("poi.mix", "poi", "设施混合", "设施类别混合程度", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding(
            "poi.category_specialization", "poi", "业态专业化", "指定 POI 类别的区位商",
            _ALL_SPATIAL_ANALYSES,
        ),
        EvidenceDimensionBinding("population.scale", "population", "人口规模", "人口规模或所选年龄性别人口", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding("population.profile", "population", "人口结构", "人口年龄、性别和时序结构", ("scope", "inspect")),
        EvidenceDimensionBinding("nightlight.intensity", "nightlight", "夜间亮度", "夜间亮度强度及空间分布", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding("road.to_movement", "road", "到达潜力", "指定网络半径的标准化角度整合度 NAIN", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding("road.through_movement", "road", "穿行潜力", "指定网络半径的标准化角度选择度 NACH", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding("road.connectivity", "road", "局部连接", "道路的直接拓扑连接", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding("road.network_density", "road", "路网密度", "单位空间内的道路长度", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding("road.orientation", "road", "道路走向", "道路自身的方向结构，不表示项目锚点方向", ("scope",)),
        EvidenceDimensionBinding("road.quality", "road", "路网质量", "拓扑、边界和句法结果有效性诊断", ("scope",)),
    ]
}


FACT_DOMAIN_CAPABILITIES: dict[FactDomain, FactDomainCapability] = {
    item.domain: item
    for item in [
        FactDomainCapability(
            "poi",
            "POI与设施供给",
            "设施数量、类别结构、集中程度和相对供给差异",
            (_POI, _POI_GRID, _H3),
            _ALL_SPATIAL_ANALYSES,
            ("poi.supply", "poi.mix", "poi.category_specialization"),
        ),
        FactDomainCapability(
            "population",
            "人口规模与结构",
            "人口规模、年龄结构及其空间覆盖",
            (_POPULATION,),
            _ALL_SPATIAL_ANALYSES,
            ("population.scale", "population.profile"),
        ),
        FactDomainCapability(
            "nightlight",
            "夜光与夜间活动背景",
            "夜间亮度强度、梯度和方向背景，不替代真实活动或消费",
            (_NIGHTLIGHT,),
            _ALL_SPATIAL_ANALYSES,
            ("nightlight.intensity",),
        ),
        FactDomainCapability(
            "road",
            "路网结构",
            "路网中心性、潜在穿行性、连接和方向结构",
            (_ROAD_EDGES, _ROAD_CORRIDORS, _ROAD_GRID, _ROAD_NODES),
            _ALL_SPATIAL_ANALYSES,
            (
                "road.to_movement", "road.through_movement", "road.connectivity",
                "road.network_density", "road.orientation", "road.quality",
            ),
        ),
    ]
}

DEFAULT_DIMENSIONS: dict[FactDomain, dict[str, tuple[EvidenceDimension, ...]]] = {
    "poi": {
        "scope": ("poi.supply", "poi.mix"),
        "accessibility": ("poi.supply",),
        "direction": ("poi.supply", "poi.mix"),
        "neighborhood": ("poi.supply", "poi.mix"),
        "inspect": ("poi.supply", "poi.mix"),
    },
    "population": {
        "scope": ("population.profile",),
        "accessibility": ("population.scale",),
        "direction": ("population.scale",),
        "neighborhood": ("population.scale",),
        "inspect": ("population.scale",),
    },
    "nightlight": {
        "scope": ("nightlight.intensity",),
        "accessibility": ("nightlight.intensity",),
        "direction": ("nightlight.intensity",),
        "neighborhood": ("nightlight.intensity",),
        "inspect": ("nightlight.intensity",),
    },
    "road": {
        "scope": (
            "road.to_movement", "road.through_movement", "road.connectivity",
            "road.network_density", "road.orientation", "road.quality",
        ),
        "accessibility": ("road.network_density", "road.connectivity"),
        "direction": ("road.to_movement", "road.through_movement", "road.connectivity", "road.network_density"),
        "neighborhood": ("road.to_movement", "road.through_movement", "road.connectivity"),
        "inspect": (),
    },
}


@dataclass
class _SpatialRow:
    record_ref: str
    source_id: str
    record_id: str
    title: str
    geometry: BaseGeometry
    centroid: tuple[float, float]
    distance_m: float
    direction: str
    area_km2: float
    values: dict[str, float | None]
    aggregation_factors: dict[str, float]
    identity: dict[str, Any]


class _RecordIndex:
    def __init__(self, records: Sequence[ScopeRecord]) -> None:
        self.records = [record for record in records if record.geometry is not None and not record.geometry.is_empty]
        self.geometries = [record.geometry for record in self.records]
        self.tree = STRtree(self.geometries) if self.geometries else None

    def query(self, geometry: BaseGeometry) -> list[ScopeRecord]:
        if self.tree is None:
            return []
        return [self.records[int(index)] for index in self.tree.query(geometry)]


class SpatialEvidenceService:
    """One semantic spatial evidence interface over heterogeneous project datasets."""

    def __init__(
        self,
        *,
        projects: SpatialProjectService | None = None,
        metric_catalog: MetricToolService | None = None,
        isochrone_contours: Callable[[tuple[float, float], Iterable[float], str], Mapping[float, BaseGeometry]] | None = None,
        population_timeseries: Callable[[list, str, str, str], Mapping[str, Any]] | None = None,
        nightlight_layer: Callable[..., Mapping[str, Any]] | None = None,
        nightlight_timeseries: Callable[[list, str, str, str], Mapping[str, Any]] | None = None,
    ) -> None:
        self._projects = projects or SpatialProjectService()
        self._datasets = self._projects.datasets
        self._metric_catalog = metric_catalog
        self._isochrone_contours = isochrone_contours or fetch_valhalla_isochrone_contours
        self._population_timeseries = population_timeseries or get_population_timeseries
        self._nightlight_layer = nightlight_layer or get_nightlight_layer
        self._nightlight_timeseries = nightlight_timeseries or get_nightlight_timeseries

    def _catalog(self) -> MetricToolService:
        if self._metric_catalog is None:
            self._metric_catalog = MetricToolService()
        return self._metric_catalog

    def compute_domains(
        self,
        *,
        history_id: str,
        request: SpatialDomainComputationRequest | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Compute domain profiles without exposing the internal metric catalog."""

        domain_query = (
            request
            if isinstance(request, SpatialDomainComputationRequest)
            else SpatialDomainComputationRequest.model_validate(request)
        )
        normalized_history_id = str(history_id or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        project = self._projects.read_history_project(normalized_history_id)
        available = {
            str(item.get("source_id") or "")
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("status") or "") == "ready"
        }
        if domain_query.analysis == "scope" and not domain_query.fact_domains:
            scope_geometry, center = self._scope_geometry(project)
            if scope_geometry is None or center is None:
                internal = SpatialEvidenceRequest(analysis="scope")
                return self._unavailable(internal, project, "当前项目没有可用的保存范围。")
            return self._domain_overview(domain_query, project, self._scope_summary(project, scope_geometry, center), available)

        computations: list[dict[str, Any]] = []
        used_metric_ids: list[str] = []

        def execute(
            domains: Sequence[FactDomain],
            dimensions: Sequence[EvidenceDimension],
            metric_ids: Sequence[str],
        ) -> None:
            request_payload = SpatialEvidenceRequest(
                analysis=domain_query.analysis,
                metric_ids=list(dict.fromkeys(metric_ids)),
                selectors=domain_query.selectors,
                travel_time_bands_min=domain_query.travel_time_bands_min,
                neighbor_steps=domain_query.neighbor_steps,
                rank_order=domain_query.rank_order,
                top_k=domain_query.top_k,
                record_refs=domain_query.record_refs,
            )
            result = self.analyze(history_id=normalized_history_id, request=request_payload)
            result["fact_domains"] = list(domains)
            result["evidence_dimensions"] = list(dimensions)
            computations.append(result)
            used_metric_ids.extend(request_payload.metric_ids)

        selected_dimensions: dict[FactDomain, tuple[EvidenceDimension, ...]] = {
            domain: tuple(
                dimension
                for dimension in domain_query.evidence_dimensions
                if EVIDENCE_DIMENSION_BINDINGS[dimension].domain == domain
            ) or DEFAULT_DIMENSIONS.get(domain, {}).get(domain_query.analysis, ())
            for domain in domain_query.fact_domains
        }
        if domain_query.analysis == "relationship":
            dimensions = [dimension for domain in domain_query.fact_domains for dimension in selected_dimensions[domain]]
            metrics = [
                metric
                for dimension in dimensions
                for metric in self._dimension_metric_ids(dimension, domain_query.analysis, domain_query.selectors)
            ]
            execute(domain_query.fact_domains, dimensions, metrics)
        elif domain_query.analysis == "rank":
            domain = domain_query.fact_domains[0]
            dimension = selected_dimensions[domain][0]
            execute([domain], [dimension], self._dimension_metric_ids(dimension, "rank", domain_query.selectors))
        elif domain_query.analysis == "scope":
            for domain in domain_query.fact_domains:
                if domain == "nightlight":
                    computations.append(self._nightlight_scope_profile(project))
                    used_metric_ids.extend([
                        "nightlight.total_radiance", "nightlight.mean_radiance", "nightlight.max_radiance",
                        "nightlight.p90", "nightlight.lit_pixel_ratio", "nightlight.hotspot_profile",
                        "nightlight.direction_profile", "nightlight.activity_level", "nightlight.temporal_profile",
                    ])
                    continue
                if domain == "road":
                    computations.append(self._road_scope_profile(project, normalized_history_id, available))
                    used_metric_ids.extend([
                        "road.network_size", "road.nain", "road.nach", "road.connectivity",
                        "road.orientation", "road.quality",
                    ])
                    continue
                for dimension in selected_dimensions[domain]:
                    metrics = self._dimension_metric_ids(dimension, "scope", domain_query.selectors)
                    if metrics:
                        execute([domain], [dimension], metrics)
                if domain == "poi":
                    temporal_profile = self._poi_temporal_profile(normalized_history_id, project)
                    if temporal_profile is not None:
                        computations.append(temporal_profile)
                        used_metric_ids.append("poi.multi_year_count")
                if "population.profile" in selected_dimensions[domain]:
                    computations.append(self._population_temporal_profile(project, domain_query))
                    used_metric_ids.append("population.temporal_profile")
        elif domain_query.analysis == "inspect" and not domain_query.fact_domains:
            execute([], [], [])
        else:
            for domain in domain_query.fact_domains:
                dimensions = selected_dimensions[domain]
                if (
                    domain_query.analysis == "accessibility"
                    and domain == "poi"
                    and dimensions == ("poi.supply",)
                    and _selected_poi_category(domain_query.selectors) is not None
                ):
                    computations.append(self._focused_poi_accessibility_result(
                        history_id=normalized_history_id,
                        project=project,
                        available=available,
                        request=domain_query,
                    ))
                    used_metric_ids.append("poi.focused_accessibility")
                    continue
                metrics = [
                    metric
                    for dimension in dimensions
                    for metric in self._dimension_metric_ids(dimension, domain_query.analysis, domain_query.selectors)
                ]
                execute([domain], dimensions, metrics)

        statuses = [str(item.get("status") or "unavailable") for item in computations]
        status = "available" if statuses and all(value == "available" for value in statuses) else (
            "partial" if any(value == "available" for value in statuses) else "unavailable"
        )
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "request": domain_query.model_dump(mode="json"),
            })[:24],
            "status": status,
            "analysis": domain_query.analysis,
            "fact_domains": [self._domain_descriptor(domain, available) for domain in domain_query.fact_domains],
            "evidence_dimensions": [
                self._dimension_descriptor(dimension)
                for domain in domain_query.fact_domains
                for dimension in selected_dimensions[domain]
            ],
            "domain_results": computations,
            "used_metric_ids": list(dict.fromkeys(used_metric_ids)),
            "coverage": {
                "complete": bool(computations) and all(value == "available" for value in statuses),
                "computation_count": len(computations),
                "available_computation_count": sum(value == "available" for value in statuses),
            },
            "limitations": [
                limitation
                for item in computations
                for limitation in item.get("limitations", [])
                if str(limitation).strip()
            ],
            "method": {"kind": "domain_owned_spatial_evidence", "internal_metrics_hidden": True},
            "provenance": self._provenance(project, {}, available),
        })

    def _dimension_metric_ids(
        self,
        dimension: EvidenceDimension,
        analysis: str,
        selectors: Sequence[SpatialEvidenceSelector],
    ) -> tuple[str, ...]:
        if dimension == "poi.supply":
            if analysis in {"neighborhood", "inspect"}:
                return (
                    "poi.grid_density",
                    "poi.neighbor_mean_density",
                    "spatial.neighbor_density_delta",
                    "spatial.gi_star",
                    "spatial.lisa",
                    "spatial.lisa_z",
                )
            return ("poi.count", "poi.category_count", "poi.grid_density") if analysis == "scope" else ("poi.grid_density",)
        if dimension == "poi.mix":
            if analysis in {"neighborhood", "inspect"}:
                return ("poi.local_entropy", "poi.neighbor_mean_entropy")
            return ("poi.local_entropy",)
        if dimension == "poi.category_specialization":
            if _selected_poi_category(selectors) is None:
                raise ValueError("poi_category_specialization_requires_poi_category")
            return ("poi.category_lq",)
        if dimension == "population.profile":
            return ("population.profile",) if analysis == "scope" else ("population.total",)
        if dimension == "population.scale":
            selected = self._population_metric_ids(selectors)
            if analysis in {"rank", "relationship"} and len(selected) > 1:
                raise ValueError(f"{analysis}_requires_one_population_series")
            return selected or ("population.total",)
        if dimension == "nightlight.intensity":
            if analysis == "scope":
                return (
                    "nightlight.total_radiance", "nightlight.mean_radiance", "nightlight.max_radiance",
                    "nightlight.p90", "nightlight.lit_pixel_ratio", "nightlight.hotspot_class",
                    "nightlight.hotspot_ratio", "nightlight.spatial_profile", "nightlight.sector_profile",
                )
            return ("nightlight.mean_radiance",)
        if dimension in {"road.to_movement", "road.through_movement"}:
            radius_selected = bool(self._selector_values(selectors, "road.radius"))
            if dimension == "road.to_movement":
                return ("road.nain.selected_radius",) if radius_selected else ("road.nain",)
            return ("road.nach.selected_radius",) if radius_selected else ("road.nach",)
        if dimension == "road.connectivity":
            return ("road.connectivity",)
        if dimension == "road.network_density":
            return (
                ("road.network_size", "road.network_density")
                if analysis == "accessibility"
                else ("road.network_density",)
            )
        if dimension == "road.orientation":
            return ("road.orientation",) if analysis == "scope" else ()
        if dimension == "road.quality":
            return ("road.intelligibility",) if analysis == "scope" else ()
        raise ValueError(f"unsupported_evidence_dimension:{dimension}")

    @staticmethod
    def _selector_values(
        selectors: Sequence[SpatialEvidenceSelector],
        dimension: str,
    ) -> tuple[str, ...]:
        return tuple(
            str(value).strip().lower()
            for selector in selectors
            if selector.dimension == dimension
            for value in selector.values
        )

    def _focused_poi_accessibility_result(
        self,
        *,
        history_id: str,
        project: Mapping[str, Any],
        available: set[str],
        request: SpatialDomainComputationRequest,
    ) -> dict[str, Any]:
        """Resolve one selected POI category over the persisted local road network."""

        selected_category = _selected_poi_category(request.selectors)
        if selected_category is None:
            raise ValueError("focused_poi_accessibility_requires_poi_category")
        category_key, category_label = selected_category
        required_sources = {_POI, _ROAD_EDGES}
        missing_sources = sorted(required_sources - available)
        scope_geometry, center = self._scope_geometry(project)
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")

        def unavailable(reason: str, *, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "analysis": "accessibility",
                "summary": {
                    "selected_category": {"key": category_key, "label": category_label},
                    "route_verified_poi_count": 0,
                    **dict(details or {}),
                },
                "groups": [],
                "named_spatial_objects": [],
                "coverage": {"complete": False, "route_verified_poi_count": 0},
                "limitations": [reason],
                "method": {
                    "kind": "route_verified_poi_accessibility",
                    "routing_algorithm": "local_road_network_shortest_path",
                    "road_source_id": _ROAD_EDGES,
                    "road_model_executed": False,
                    "depthmapx_executed": False,
                    "local_route_graph_built": False,
                    "route_geometry_returned": False,
                },
                "provenance": {"snapshot_id": snapshot_id},
                "fact_domains": ["poi"],
                "evidence_dimensions": ["poi.supply"],
            }

        if missing_sources:
            return unavailable("专项 POI 可达性缺少已持久化数据源：" + "、".join(missing_sources) + "。")
        if scope_geometry is None or center is None:
            return unavailable("当前项目没有可用于本地路网计算的 Polygon 或 MultiPolygon 范围。")

        records, years, warnings = self._load_records(history_id, required_sources)
        poi_records = records.get(_POI, [])
        road_records = records.get(_ROAD_EDGES, [])
        if not poi_records or not road_records:
            return unavailable("专项 POI 可达性需要非空的 POI 与路网持久化结果。")

        taxonomy_rule = next(
            (
                (label, type_codes)
                for group_id, label, type_codes in get_poi_taxonomy().category_rules()
                if group_id == category_key
            ),
            None,
        )
        if taxonomy_rule is None or not taxonomy_rule[1]:
            return unavailable("所选 POI 主业态没有可用的 taxonomy typecode 映射。")
        _, type_codes = taxonomy_rule
        candidates = [
            candidate
            for record in poi_records
            if (candidate := self._focused_poi_candidate(record)) is not None
        ]
        if not candidates:
            return unavailable("当前 POI 快照没有带有效点位和 typecode 的记录。")

        try:
            router = LocalRoadNetworkRouter(
                record.geometry
                for record in road_records
                if record.geometry is not None and not record.geometry.is_empty
            )
        except RoadNetworkRoutingUnavailable as exc:
            return unavailable(f"已持久化路网无法建立本地路径网络：{exc}。")

        max_minutes = max(
            (float(end) for _, end in (request.travel_time_bands_min or DEFAULT_TRAVEL_TIME_BANDS_MIN)),
            default=DEFAULT_ISOCHRONE_TIME_MIN,
        )
        max_duration_s = max_minutes * 60.0
        result = FocusedPoiAccessibilityService(
            router,
            max_candidate_distance_m=max_duration_s * DEFAULT_WALKING_SPEED_M_PER_S,
            max_walking_duration_s=max_duration_s,
        ).analyze(
            analysis_geometry=mapping(scope_geometry),
            groups=[FocusedPoiTypeGroup(
                group_id=category_key,
                title=category_label,
                role="category_supply",
                type_codes=tuple(type_codes),
                statement_ref="request:selector:poi.category",
            )],
            pois=candidates,
        )
        group = result.groups[0] if result.groups else None
        named_objects = [
            {
                "record_ref": f"{_POI}/{poi.poi_id}",
                "object_type": "poi",
                "name": poi.name,
                "category": category_label,
                "poi_typecode": poi.poi_type,
                "address": poi.address,
                "walking_distance_m": round(poi.walking_distance_m, 1),
                "walking_time_min": round(poi.walking_duration_s / 60.0, 2),
                "road_path_distance_m": round(poi.route_length_m, 1),
                "origin_access_distance_m": round(poi.origin_snap_distance_m, 1),
                "destination_access_distance_m": round(poi.destination_snap_distance_m, 1),
                "route_status": "available",
                "road_source_id": _ROAD_EDGES,
            }
            for poi in (group.pois if group is not None else ())
        ]
        candidates_considered = group.candidates_considered if group is not None else 0
        route_failures = group.route_failures if group is not None else 0
        omission_reason = group.omission_reason if group is not None else result.error_reason
        if not named_objects:
            return unavailable(
                "所选业态没有形成沿已持久化路网的可达路径；未使用直线距离或模拟路径替代。",
                details={
                    "route_status": "unavailable",
                    "candidates_considered": candidates_considered,
                    "route_failures": route_failures,
                    "omission_reason": omission_reason,
                },
            )

        limitations = [
            "总步行距离由起点接驳、已持久化道路最短路径和终点接驳三段构成；时间按 4.5 km/h 换算，不代表实时路况、入口开放状态或人流。"
        ]
        limitations.extend(str(item) for item in warnings if str(item).strip())
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "available",
            "analysis": "accessibility",
            "summary": {
                "selected_category": {"key": category_key, "label": category_label},
                "origin_wgs84": [round(float(result.origin[0]), 6), round(float(result.origin[1]), 6)] if result.origin else None,
                "route_verified_poi_count": len(named_objects),
                "candidates_considered": candidates_considered,
                "route_failures": route_failures,
                "max_walking_time_min": max_minutes,
                "route_status": "available",
            },
            "groups": [{
                "category": {"key": category_key, "label": category_label},
                "status": "available",
                "matched_typecodes": list(group.matched_type_codes) if group is not None else [],
                "route_verified_poi_count": len(named_objects),
            }],
            "named_spatial_objects": named_objects,
            "coverage": {
                "complete": True,
                "route_verified_poi_count": len(named_objects),
                "candidates_considered": candidates_considered,
                "route_failures": route_failures,
            },
            "limitations": limitations,
            "method": {
                "kind": "route_verified_poi_accessibility",
                "routing_algorithm": "local_road_network_shortest_path",
                "origin": "saved_scope_polygon_centroid",
                "road_source_id": _ROAD_EDGES,
                "poi_source_id": _POI,
                "poi_taxonomy_source": "share/type_map.json",
                "walking_speed_km_h": 4.5,
                "walking_distance_components": [
                    "origin_access_distance_m",
                    "road_path_distance_m",
                    "destination_access_distance_m",
                ],
                "max_walking_time_min": max_minutes,
                "road_model_executed": False,
                "depthmapx_executed": False,
                "local_route_graph_built": True,
                "persisted_result_reads": [_POI, _ROAD_EDGES],
                "route_geometry_returned": False,
            },
            "provenance": self._provenance(project, years, set(records)),
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply"],
            "year": years.get(_POI),
        }

    @staticmethod
    def _focused_poi_candidate(record: ScopeRecord) -> FocusedPoiCandidate | None:
        geometry = record.geometry
        if geometry is None or geometry.is_empty:
            return None
        point = geometry.centroid
        try:
            location = (float(point.x), float(point.y))
        except (TypeError, ValueError):
            return None
        raw = record.raw if isinstance(record.raw, Mapping) else {}
        properties = record.properties if isinstance(record.properties, Mapping) else {}
        poi_type = (
            raw.get("typecode") or properties.get("typecode")
            or raw.get("type") or properties.get("type")
        )
        if poi_type in (None, ""):
            return None
        return FocusedPoiCandidate(
            poi_id=str(record.record_id),
            name=str(raw.get("name") or properties.get("name") or record.title or "").strip(),
            poi_type=str(poi_type).strip(),
            location=location,
            address=str(raw.get("address") or properties.get("address") or "").strip() or None,
        )

    @classmethod
    def _population_metric_ids(
        cls,
        selectors: Sequence[SpatialEvidenceSelector],
    ) -> tuple[str, ...]:
        sexes = cls._selector_values(selectors, "population.sex")
        bands = cls._selector_values(selectors, "population.age_band")
        if not sexes and not bands:
            return ()
        resolved_sexes = sexes or ("total",)
        resolved_bands = bands or ("all",)
        metric_ids: list[str] = []
        for band in resolved_bands:
            for sex in resolved_sexes:
                if band == "all":
                    metric_id = "population.total" if sex == "total" else f"population.{sex}"
                else:
                    metric_id = f"population.age.{band}.{sex}"
                if metric_id not in metric_ids:
                    metric_ids.append(metric_id)
        return tuple(metric_ids)

    def _domain_overview(
        self,
        query: SpatialDomainComputationRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        available: set[str],
    ) -> dict[str, Any]:
        domains = [self._domain_descriptor(domain, available) for domain in FACT_DOMAIN_CAPABILITIES]
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "request": query.model_dump(mode="json"),
            })[:24],
            "status": "available",
            "analysis": query.analysis,
            "scope": scope,
            "fact_domains": domains,
            "summary": {
                "available_domain_count": sum(item["available"] for item in domains),
                "domain_count": len(domains),
            },
            "coverage": {"complete": True, "available_dataset_count": len(available)},
            "limitations": [],
            "method": {"kind": "spatial_evidence_domain_catalog", "scope_policy": "current_saved_scope_only"},
            "provenance": self._provenance(project, {}, available),
        })

    def _population_temporal_profile(
        self,
        project: Mapping[str, Any],
        query: SpatialDomainComputationRequest,
    ) -> dict[str, Any]:
        scope_geometry, _ = self._scope_geometry(project)
        if scope_geometry is None or scope_geometry.is_empty:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "analysis": "scope",
                "summary": {},
                "coverage": {"complete": False},
                "limitations": ["当前项目没有可用于人口时序分析的保存范围。"],
                "method": {"kind": "population_temporal_profile", "executed": False},
                "provenance": {},
                "fact_domains": ["population"],
                "evidence_dimensions": ["population.profile"],
            }
        polygon = max(
            list(scope_geometry.geoms) if scope_geometry.geom_type == "MultiPolygon" else [scope_geometry],
            key=lambda geometry: geometry.area,
        )
        coordinates = [[float(x), float(y)] for x, y in polygon.exterior.coords]
        try:
            raw = self._population_timeseries(coordinates, "wgs84", "2024-2026", "population_delta")
        except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "analysis": "scope",
                "summary": {},
                "coverage": {"complete": False},
                "limitations": [f"2024–2026 人口时序计算失败：{type(exc).__name__}。"],
                "method": {"kind": "population_temporal_profile", "executed": False},
                "provenance": {},
                "fact_domains": ["population"],
                "evidence_dimensions": ["population.profile"],
            }
        series = []
        for item in raw.get("series", []):
            if not isinstance(item, Mapping) or str(item.get("year") or "") not in {"2024", "2025", "2026"}:
                continue
            age_totals = item.get("age_group_totals") if isinstance(item.get("age_group_totals"), Mapping) else {}
            age_ratios = item.get("age_group_ratios") if isinstance(item.get("age_group_ratios"), Mapping) else {}
            age_distribution = [
                {
                    "age_band": str(row.get("age_band") or ""),
                    "age_band_label": str(row.get("age_band_label") or row.get("age_band") or ""),
                    "total": _rounded(_number(row.get("total"))),
                    "male": _rounded(_number(row.get("male"))),
                    "female": _rounded(_number(row.get("female"))),
                    "ratio": _rounded(_number(row.get("ratio"))),
                }
                for row in item.get("age_distribution") or []
                if isinstance(row, Mapping) and str(row.get("age_band") or "") in POPULATION_AGE_BANDS
            ]
            series.append({
                "year": str(item.get("year")),
                "total_population": _rounded(_number(item.get("total_population"))),
                "male_total": _rounded(_number(item.get("male_total"))),
                "female_total": _rounded(_number(item.get("female_total"))),
                "male_ratio": _rounded(_number(item.get("male_ratio"))),
                "female_ratio": _rounded(_number(item.get("female_ratio"))),
                "average_density": _rounded(_number(item.get("average_density"))),
                "age_distribution": age_distribution,
                "age_group_totals": {
                    key: _rounded(_number(age_totals.get(key)))
                    for key in ("child_0_14", "working_15_64", "senior_65_plus")
                },
                "age_group_ratios": {
                    key: _rounded(_number(age_ratios.get(key)))
                    for key in ("child_0_14", "working_15_64", "senior_65_plus")
                },
                "top_age_band": str(item.get("top_age_band") or "") or None,
                "top_age_band_label": str(item.get("top_age_band_label") or item.get("dominant_age_band") or "") or None,
            })
        series.sort(key=lambda item: item["year"])
        if len(series) < 2:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "analysis": "scope",
                "summary": {},
                "coverage": {"complete": False, "year_count": len(series)},
                "limitations": ["人口时序没有形成至少两个可比较年份。"],
                "method": {"kind": "population_temporal_profile", "executed": False},
                "provenance": {},
                "fact_domains": ["population"],
                "evidence_dimensions": ["population.profile"],
            }
        first, last = series[0], series[-1]

        def change(field: str) -> dict[str, float | None]:
            before = _number(first.get(field))
            after = _number(last.get(field))
            delta = after - before if before is not None and after is not None else None
            rate = delta / before if delta is not None and before not in (None, 0) else None
            return {"from": _rounded(before), "to": _rounded(after), "delta": _rounded(delta), "rate": _rounded(rate)}

        age_ratio_change = {}
        first_age = first.get("age_group_ratios") if isinstance(first.get("age_group_ratios"), Mapping) else {}
        last_age = last.get("age_group_ratios") if isinstance(last.get("age_group_ratios"), Mapping) else {}
        for key in ("child_0_14", "working_15_64", "senior_65_plus"):
            before = _number(first_age.get(key))
            after = _number(last_age.get(key))
            age_ratio_change[key] = {
                "from": _rounded(before),
                "to": _rounded(after),
                "percentage_point_delta": _rounded((after - before) * 100 if before is not None and after is not None else None),
            }
        layer = raw.get("layer") if isinstance(raw.get("layer"), Mapping) else {}
        layer_summary = layer.get("summary") if isinstance(layer.get("summary"), Mapping) else {}
        summary = {
            "period": "2024-2026",
            "series": series,
            "change_2024_2026": {
                "total_population": change("total_population"),
                "male_total": change("male_total"),
                "female_total": change("female_total"),
                "average_density": change("average_density"),
                "age_group_ratio": age_ratio_change,
            },
            "spatial_change": {
                "cell_count": int(layer_summary.get("cell_count") or 0),
                "class_counts": dict(layer_summary.get("class_counts") or {}),
            },
        }
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({"snapshot_id": snapshot_id, "kind": "population_temporal_profile", "period": "2024-2026"})[:24],
            "status": "available",
            "analysis": "scope",
            "summary": summary,
            "coverage": {
                "complete": all(len(item["age_distribution"]) == len(POPULATION_AGE_BANDS) for item in series),
                "year_count": len(series),
                "age_band_count_by_year": {
                    item["year"]: len(item["age_distribution"])
                    for item in series
                },
                "spatial_unit_count": summary["spatial_change"]["cell_count"],
            },
            "limitations": [],
            "method": {
                "kind": "population_temporal_profile",
                "period": "2024-2026",
                "spatial_change_view": "population_delta",
                "spatial_aggregation": "intersecting_full_cells",
                "boundary_cell_policy": "include_full_cell_value",
                "internal_metrics_hidden": True,
            },
            "provenance": {
                "snapshot_id": snapshot_id,
                "source_ids": ["population:raster:2024", "population:raster:2025", "population:raster:2026"],
            },
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.profile"],
        })

    def _poi_temporal_profile(
        self,
        history_id: str,
        project: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        descriptor = next(
            (
                item
                for item in project.get("datasets") or []
                if isinstance(item, Mapping) and str(item.get("source_id") or "") == _POI
            ),
            {},
        )
        available_years = sorted({
            int(year)
            for year in descriptor.get("available_years") or []
            if _number(year) is not None
        })
        if len(available_years) < 2:
            return None

        snapshots: list[dict[str, Any]] = []
        warnings: list[str] = []
        for year in available_years:
            try:
                records, _, selected_year = self._datasets.load_scope_records(
                    history_id=history_id,
                    source_id=_POI,
                    year=year,
                )
            except (LookupError, ValueError) as exc:
                warnings.append(f"{year}:{exc}")
                continue
            categories = Counter(
                str(record.properties.get("category") or "").strip()
                for record in records
                if str(record.properties.get("category") or "").strip()
            )
            snapshots.append({
                "year": int(selected_year or year),
                "poi_count": len(records),
                "category_count": len(categories),
            })
        if len(snapshots) < 2:
            return None
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "available",
            "analysis": "scope",
            "summary": {
                "snapshots": snapshots,
                "snapshot_count": len(snapshots),
                "latest_year": snapshots[-1]["year"],
            },
            "coverage": {
                "complete": len(snapshots) == len(available_years),
                "available_years": available_years,
                "loaded_years": [item["year"] for item in snapshots],
            },
            "limitations": [
                *warnings,
                "跨年 POI 数量仅表示各期保存快照的记录覆盖，不能直接解释为开闭店、客流或市场增长。",
            ],
            "method": {
                "kind": "persisted_poi_snapshot_comparison",
                "source_id": _POI,
                "entity_change_computed": False,
                "snapshot_counts_only": True,
            },
            "provenance": {
                "snapshot_id": snapshot_id,
                "source_ids": [_POI],
                "selected_years": {_POI: [item["year"] for item in snapshots]},
                "result_checksum": "sha256:" + _digest({
                    "snapshot_id": snapshot_id,
                    "source_id": _POI,
                    "snapshots": snapshots,
                }),
            },
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply"],
        }

    def _nightlight_scope_profile(self, project: Mapping[str, Any]) -> dict[str, Any]:
        """Build one bounded nightlight result from one current layer and one time series."""

        scope_geometry, _ = self._scope_geometry(project)
        if scope_geometry is None or scope_geometry.is_empty:
            return self._nightlight_unavailable(project, "当前项目没有可用于夜光分析的保存范围。")
        polygon = max(
            list(scope_geometry.geoms) if scope_geometry.geom_type == "MultiPolygon" else [scope_geometry],
            key=lambda geometry: geometry.area,
        )
        coordinates = [[float(x), float(y)] for x, y in polygon.exterior.coords]
        try:
            layer = self._nightlight_layer(coordinates, "wgs84", view="hotspot")
            temporal = self._nightlight_timeseries(coordinates, "wgs84", "2023-2025", "radiance_delta")
        except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return self._nightlight_unavailable(
                project,
                f"2023–2025 夜光领域计算失败：{type(exc).__name__}。",
            )

        raw_summary = layer.get("summary") if isinstance(layer.get("summary"), Mapping) else {}
        raw_analysis = layer.get("analysis") if isinstance(layer.get("analysis"), Mapping) else {}
        raw_sector = raw_analysis.get("sector_direction_analysis")
        sector = raw_sector if isinstance(raw_sector, Mapping) else {}
        series = []
        for item in temporal.get("series", []):
            if not isinstance(item, Mapping):
                continue
            year = int(_number(item.get("year")) or 0)
            if year not in {2023, 2024, 2025}:
                continue
            series.append({
                "year": year,
                "total_radiance": _rounded(_number(item.get("total_radiance"))),
                "mean_radiance": _rounded(_number(item.get("mean_radiance"))),
                "max_radiance": _rounded(_number(item.get("max_radiance"))),
                "p90_radiance": _rounded(_number(item.get("p90_radiance"))),
                "lit_pixel_ratio": _rounded(_number(item.get("lit_pixel_ratio"))),
            })
        series.sort(key=lambda item: item["year"])

        def change(field: str) -> dict[str, float | None]:
            before = _number(series[0].get(field)) if series else None
            after = _number(series[-1].get(field)) if series else None
            delta = after - before if before is not None and after is not None else None
            rate = delta / before if delta is not None and before not in (None, 0) else None
            return {"from": _rounded(before), "to": _rounded(after), "delta": _rounded(delta), "rate": _rounded(rate)}

        temporal_layer = temporal.get("layer") if isinstance(temporal.get("layer"), Mapping) else {}
        temporal_summary = temporal_layer.get("summary") if isinstance(temporal_layer.get("summary"), Mapping) else {}
        activity_level = str(raw_analysis.get("economic_activity_intensity_level") or "").strip() or None
        summary = {
            "snapshot": {
                "year": int(_number(layer.get("year")) or 0) or None,
                "total_radiance": _rounded(_number(raw_summary.get("total_radiance"))),
                "mean_radiance": _rounded(_number(raw_summary.get("mean_radiance"))),
                "max_radiance": _rounded(_number(raw_summary.get("max_radiance"))),
                "p90_radiance": _rounded(_number(raw_summary.get("p90_radiance"))),
                "lit_pixel_ratio": _rounded(_number(raw_summary.get("lit_pixel_ratio"))),
                "valid_pixel_count": int(_number(raw_summary.get("valid_pixel_count")) or 0),
            },
            "spatial_pattern": {
                "core_hotspot_count": int(_number(raw_analysis.get("core_hotspot_count")) or 0),
                "secondary_hotspot_count": int(_number(raw_analysis.get("secondary_hotspot_count")) or 0),
                "emerging_hotspot_count": int(_number(raw_analysis.get("emerging_hotspot_count")) or 0),
                "low_light_count": int(_number(raw_analysis.get("low_light_count")) or 0),
                "hotspot_cell_ratio": _rounded(_number(raw_analysis.get("hotspot_cell_ratio"))),
                "peak_radiance": _rounded(_number(raw_analysis.get("peak_radiance"))),
                "peak_cell_id": str(raw_analysis.get("peak_cell_id") or "") or None,
                "peak_to_edge_ratio": _rounded(_number(raw_analysis.get("peak_to_edge_ratio"))),
                "dominant_direction": str(sector.get("dominant_direction") or "") or None,
                "secondary_direction": str(sector.get("secondary_direction") or "") or None,
                "dominant_share": _rounded(_number(sector.get("dominant_share"))),
                "secondary_share": _rounded(_number(sector.get("secondary_share"))),
            },
            "activity_background": {
                "level": activity_level,
                "semantics": "nightlight_brightness_proxy_not_observed_activity",
            },
            "temporal": {
                "period": "2023-2025",
                "series": series,
                "change_2023_2025": {
                    field: change(field)
                    for field in (
                        "total_radiance", "mean_radiance", "max_radiance",
                        "p90_radiance", "lit_pixel_ratio",
                    )
                },
                "spatial_change": {
                    "cell_count": int(_number(temporal_summary.get("cell_count")) or 0),
                    "class_counts": dict(temporal_summary.get("class_counts") or {}),
                },
            },
        }
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({"snapshot_id": snapshot_id, "kind": "nightlight_scope_profile", "period": "2023-2025"})[:24],
            "status": "available",
            "analysis": "scope",
            "summary": summary,
            "coverage": {
                "complete": bool(series),
                "year_count": len(series),
                "spatial_unit_count": summary["temporal"]["spatial_change"]["cell_count"],
            },
            "limitations": ["夜光活动等级仅是亮度空间背景代理，不代表真实客流、消费、营业或具体业态。"],
            "method": {
                "kind": "nightlight_scope_profile",
                "current_layer_calls": 1,
                "timeseries_calls": 1,
                "period": "2023-2025",
                "spatial_aggregation": "intersecting_full_cells",
                "boundary_cell_policy": "include_full_cell_value",
                "internal_metrics_hidden": True,
            },
            "provenance": {
                "snapshot_id": snapshot_id,
                "source_ids": ["nightlight:raster:2023", "nightlight:raster:2024", "nightlight:raster:2025"],
            },
            "fact_domains": ["nightlight"],
            "evidence_dimensions": ["nightlight.intensity"],
        })

    @staticmethod
    def _nightlight_unavailable(project: Mapping[str, Any], limitation: str) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "analysis": "scope",
            "summary": {},
            "coverage": {"complete": False},
            "limitations": [limitation],
            "method": {"kind": "nightlight_scope_profile", "executed": False},
            "provenance": {"snapshot_id": snapshot_id},
            "fact_domains": ["nightlight"],
            "evidence_dimensions": ["nightlight.intensity"],
        }

    def _road_scope_profile(
        self,
        project: Mapping[str, Any],
        history_id: str,
        available: set[str],
    ) -> dict[str, Any]:
        """Summarize one persisted road run without invoking the road model again."""

        road_sources = {_ROAD_EDGES, _ROAD_CORRIDORS, _ROAD_NODES, _ROAD_GRID} & available
        records, _, warnings = self._load_records(history_id, road_sources)
        edges = records.get(_ROAD_EDGES, [])
        nodes = records.get(_ROAD_NODES, [])
        grid = records.get(_ROAD_GRID, [])
        corridors = records.get(_ROAD_CORRIDORS, [])
        if not edges:
            return self._road_unavailable(project, "当前项目没有可读取的已持久化路网线段结果。")

        dataset_summaries = {
            str(item.get("source_id") or ""): item.get("summary")
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and isinstance(item.get("summary"), Mapping)
        }
        source_summary = dataset_summaries.get(_ROAD_EDGES) or dataset_summaries.get(_ROAD_GRID) or {}
        radii = self._road_available_radii(edges)
        radius_profiles = []
        for radius in radii:
            suffix = "global" if radius == "global" else f"r{radius}"
            nain_values = [
                value for record in edges
                if (value := _number(record.properties.get(f"nain_{suffix}"))) is not None
            ]
            nach_values = [
                value for record in edges
                if (value := _number(record.properties.get(f"nach_{suffix}"))) is not None
            ]
            radius_profiles.append({
                "radius": radius,
                "nain": self._distribution(nain_values, len(edges)),
                "nach": self._distribution(nach_values, len(edges)),
            })

        default_profile = next((item for item in radius_profiles if item["radius"] == "global"), None)
        if default_profile is None and radius_profiles:
            default_profile = radius_profiles[0]
        core_background = self._road_core_background(edges, str(default_profile["radius"])) if default_profile else {}

        orientation = source_summary.get("road_orientation_analysis")
        if not isinstance(orientation, Mapping) or not orientation:
            orientation = build_road_orientation_analysis([
                {
                    "type": "Feature",
                    "geometry": record.geometry.__geo_interface__,
                    "properties": dict(record.properties),
                }
                for record in edges
                if record.geometry is not None and not record.geometry.is_empty
            ])
        orientation_rows = orientation.get("orientation_rows") if isinstance(orientation.get("orientation_rows"), list) else []

        covered_grid = [
            record for record in grid
            if record.properties.get("road_has_data") is True
            or any(_number(record.properties.get(field)) is not None for field in ("road_nain", "road_nach", "road_connectivity"))
        ]
        grid_metric_valid = {
            field: sum(_number(record.properties.get(field)) is not None for record in grid)
            for field in ("road_nain", "road_nach", "road_connectivity")
        }
        network_length_km = _number(source_summary.get("network_length_km"))
        if network_length_km is None:
            network_length_km = sum(_number(record.properties.get("length_m")) or 0.0 for record in edges) / 1000.0
        connectivity = [
            value for record in edges
            if (value := self._direct_record_value(METRIC_BINDINGS["road.connectivity"], record)) is not None
        ]
        summary = {
            "network": {
                "edge_count": len(edges),
                "node_count": len(nodes) or int(_number(source_summary.get("node_count")) or 0),
                "network_length_km": _rounded(network_length_km),
                "mean_connectivity": _rounded(sum(connectivity) / len(connectivity) if connectivity else None),
            },
            "radius_profiles": radius_profiles,
            "core_background": core_background,
            "continuous_corridors": {
                "corridor_count": len(corridors),
                "by_metric": {
                    metric: sum(str(record.properties.get("metric") or "") == metric for record in corridors)
                    for metric in ("nain", "nach")
                },
                "total_length_km": _rounded(sum(
                    _number(record.properties.get("length_m")) or 0.0 for record in corridors
                ) / 1000.0),
            },
            "orientation": {
                "dominant": str(orientation.get("dominant_orientation") or "") or None,
                "secondary": str(orientation.get("secondary_orientation") or "") or None,
                "rows": [
                    {
                        "label": str(row.get("label") or ""),
                        "length_km": _rounded(_number(row.get("length_km"))),
                        "length_share": _rounded(_number(row.get("length_share"))),
                        "edge_count": int(_number(row.get("edge_count")) or 0),
                    }
                    for row in orientation_rows[:8]
                    if isinstance(row, Mapping)
                ],
            },
            "grid_coverage": {
                "cell_count": len(grid),
                "covered_cell_count": len(covered_grid),
                "no_road_cell_count": max(0, len(grid) - len(covered_grid)),
                "metric_valid_cell_count": grid_metric_valid,
                "no_road_metric_semantics": "null_not_zero",
            },
            "quality": {
                "analysis_engine": str(source_summary.get("analysis_engine") or "depthmapx_persisted_result"),
                "analysis_context_margin_m": _rounded(_number(source_summary.get("analysis_context_margin_m"))),
                "context_edge_count": int(_number(source_summary.get("context_edge_count")) or 0),
                "output_edge_count": int(_number(source_summary.get("output_edge_count")) or len(edges)),
                "rendered_edge_count": int(_number(source_summary.get("rendered_edge_count")) or len(edges)),
                "edge_merge_ratio": _rounded(_number(source_summary.get("edge_merge_ratio"))),
                "intelligibility_r": _rounded(_number(source_summary.get("avg_intelligibility"))),
                "intelligibility_r2": _rounded(_number(source_summary.get("avg_intelligibility_r2"))),
                "topology": _compact_value(
                    source_summary.get("quality_diagnostics")
                    if isinstance(source_summary.get("quality_diagnostics"), Mapping)
                    else {}
                ),
            },
        }
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({"snapshot_id": snapshot_id, "kind": "road_scope_profile"})[:24],
            "status": "available",
            "analysis": "scope",
            "summary": summary,
            "coverage": {
                "complete": bool(radius_profiles),
                "edge_count": len(edges),
                "grid_cell_count": len(grid),
                "covered_grid_cell_count": len(covered_grid),
            },
            "limitations": list(dict.fromkeys(warnings)),
            "method": {
                "kind": "persisted_road_scope_profile",
                "road_model_executed": False,
                "persisted_result_reads": sorted(road_sources),
                "missing_values": "excluded_not_zero_filled",
                "core_network_rule": "edge_nain_or_nach_at_or_above_same_radius_p75",
            },
            "provenance": {"snapshot_id": snapshot_id, "source_ids": sorted(road_sources)},
            "fact_domains": ["road"],
            "evidence_dimensions": list(FACT_DOMAIN_CAPABILITIES["road"].dimensions),
        })

    @staticmethod
    def _road_available_radii(edges: Sequence[ScopeRecord]) -> list[str]:
        radii: set[str] = set()
        for record in edges:
            for key in record.properties:
                match = re.fullmatch(r"(?:nain|nach)_(global|r\d+)", str(key))
                if match:
                    radii.add(match.group(1).removeprefix("r"))
        return sorted(radii, key=lambda value: (value != "global", int(value) if value.isdigit() else 0))

    @staticmethod
    def _distribution(values: Sequence[float], total_count: int) -> dict[str, Any]:
        if not values:
            return {"valid_count": 0, "missing_count": total_count}
        return {
            "valid_count": len(values),
            "missing_count": max(0, total_count - len(values)),
            "min": _rounded(min(values)),
            "p25": _rounded(_quantile(values, 0.25)),
            "median": _rounded(_quantile(values, 0.5)),
            "p75": _rounded(_quantile(values, 0.75)),
            "max": _rounded(max(values)),
            "mean": _rounded(sum(values) / len(values)),
        }

    @staticmethod
    def _road_core_background(edges: Sequence[ScopeRecord], radius: str) -> dict[str, Any]:
        suffix = "global" if radius == "global" else f"r{radius}"
        rows = []
        for record in edges:
            nain = _number(record.properties.get(f"nain_{suffix}"))
            nach = _number(record.properties.get(f"nach_{suffix}"))
            if nain is None and nach is None:
                continue
            rows.append((record, nain, nach))
        nain_values = [value for _, value, _ in rows if value is not None]
        nach_values = [value for _, _, value in rows if value is not None]
        nain_p75 = _quantile(nain_values, 0.75) if nain_values else None
        nach_p75 = _quantile(nach_values, 0.75) if nach_values else None
        core = [
            record for record, nain, nach in rows
            if (nain is not None and nain_p75 is not None and nain >= nain_p75)
            or (nach is not None and nach_p75 is not None and nach >= nach_p75)
        ]
        core_ids = {record.record_id for record in core}
        background = [record for record, _, _ in rows if record.record_id not in core_ids]

        def payload(records: Sequence[ScopeRecord]) -> dict[str, Any]:
            return {
                "edge_count": len(records),
                "network_length_km": _rounded(sum(
                    _number(record.properties.get("length_m")) or 0.0 for record in records
                ) / 1000.0),
            }

        return {
            "radius": radius,
            "nain_p75": _rounded(nain_p75),
            "nach_p75": _rounded(nach_p75),
            "core": payload(core),
            "background": payload(background),
        }

    @staticmethod
    def _road_unavailable(project: Mapping[str, Any], limitation: str) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "analysis": "scope",
            "summary": {},
            "coverage": {"complete": False},
            "limitations": [limitation],
            "method": {"kind": "persisted_road_scope_profile", "road_model_executed": False},
            "provenance": {"snapshot_id": snapshot_id},
            "fact_domains": ["road"],
            "evidence_dimensions": list(FACT_DOMAIN_CAPABILITIES["road"].dimensions),
        }

    @staticmethod
    def _domain_descriptor(domain: FactDomain, available: set[str]) -> dict[str, Any]:
        binding = FACT_DOMAIN_CAPABILITIES[domain]
        required_count = 1
        available_count = sum(source_id in available for source_id in binding.source_ids)
        return {
            "domain": domain,
            "label": binding.label,
            "description": binding.description,
            "available": available_count >= required_count,
            "supported_analyses": list(binding.supported_analyses),
            "evidence_dimensions": list(binding.dimensions),
        }

    @staticmethod
    def _dimension_descriptor(dimension: EvidenceDimension) -> dict[str, Any]:
        binding = EVIDENCE_DIMENSION_BINDINGS[dimension]
        return {
            "dimension": binding.dimension,
            "fact_domain": binding.domain,
            "label": binding.label,
            "description": binding.description,
        }

    def analyze(
        self,
        *,
        history_id: str,
        request: SpatialEvidenceRequest | Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_history_id = str(history_id or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        query = request if isinstance(request, SpatialEvidenceRequest) else SpatialEvidenceRequest.model_validate(request)
        project = self._projects.read_history_project(normalized_history_id)
        scope_geometry, center = self._scope_geometry(project)
        if scope_geometry is None:
            return self._unavailable(query, project, "当前项目没有可用的保存范围。")
        if center is None:
            return self._unavailable(query, project, "当前项目范围没有可解析的分析中心。")
        available = {
            str(item.get("source_id") or "")
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("status") or "") == "ready"
        }
        scope = self._scope_summary(project, scope_geometry, center)
        if query.analysis == "scope" and not query.metric_ids and not query.named_poi_roles:
            return self._overview(query, project, scope, available)

        registered_metric_ids = set(METRIC_BINDINGS) | set(CATALOG_SCOPE_BINDINGS)
        unknown = sorted(set(query.metric_ids) - registered_metric_ids)
        if unknown:
            raise ValueError("unsupported_metric_ids:" + ",".join(unknown))
        if "poi.category_lq" in query.metric_ids and _selected_poi_category(query.selectors) is None:
            raise ValueError("poi_category_lq_requires_exactly_one_poi_category")
        catalog_scope_metrics = (
            [metric_id for metric_id in query.metric_ids if metric_id in CATALOG_SCOPE_BINDINGS]
            if query.analysis == "scope"
            else []
        )
        unsupported = sorted(
            metric_id
            for metric_id in query.metric_ids
            if metric_id in METRIC_BINDINGS and query.analysis not in METRIC_BINDINGS[metric_id].supported_analyses
        )
        if unsupported:
            raise ValueError(f"metrics_not_supported_for_{query.analysis}:" + ",".join(unsupported))
        if catalog_scope_metrics:
            if query.analysis != "scope":
                return self._unavailable(
                    query,
                    project,
                    "目录指标已登记为范围汇总策略，不支持本次空间分组模式。",
                    scope=scope,
                )
            if len(catalog_scope_metrics) != len(query.metric_ids):
                raise ValueError("scope_mixed_native_and_catalog_metrics_not_supported")
            result = self._catalog_scope_result(query, project, scope)
            if result.get("status") == "available" and query.named_poi_roles and _POI in available:
                records, _, _ = self._load_records(normalized_history_id, {_POI} & available)
                result["named_poi_candidates"] = self._named_poi_candidates(query, records, center)
                return _bounded_model_response(result)
            return result

        required_sources = self._required_sources(query, available)
        records, years, warnings = self._load_records(normalized_history_id, required_sources)
        self._prepare_derived_metric_values(query, records, scope_geometry)
        missing_metrics = self._missing_metric_sources(query.metric_ids, records)
        if missing_metrics:
            return self._unavailable(
                query,
                project,
                "请求指标缺少可用数据集：" + ", ".join(missing_metrics),
                scope=scope,
            )
        def with_named_pois(result: dict[str, Any]) -> dict[str, Any]:
            if result.get("status") == "available" and query.named_poi_roles:
                result["named_poi_candidates"] = self._named_poi_candidates(query, records, center)
                return _bounded_model_response(result)
            return result

        if query.analysis == "scope":
            return with_named_pois(
                self._scope_result(query, project, scope, records, years, warnings, scope_geometry)
            )
        if query.analysis == "inspect":
            return with_named_pois(
                self._inspect_result(query, project, scope, records, years, warnings, scope_geometry)
            )
        if query.analysis == "accessibility":
            return with_named_pois(
                self._accessibility_result(
                    query,
                    project,
                    scope,
                    records,
                    years,
                    warnings,
                    center,
                    scope_geometry,
                )
            )

        base_source = self._base_source(query, records)
        base_records = records.get(base_source, []) if base_source else []
        if not base_source or not base_records:
            return self._unavailable(query, project, "当前数据无法形成该模式所需的可定位空间单元。", scope=scope)
        rows = self._spatial_rows(query, base_source, base_records, records, center, scope_geometry)
        if not rows:
            return self._unavailable(query, project, "当前范围内没有可用于本次分析的空间单元。", scope=scope)
        if query.analysis == "rank":
            return with_named_pois(self._rank_result(query, project, scope, rows, years, warnings))
        if query.analysis == "neighborhood":
            return with_named_pois(self._neighborhood_result(query, project, scope, rows, years, warnings))
        if query.analysis == "relationship":
            return with_named_pois(self._relationship_result(query, project, scope, rows, years, warnings))
        return with_named_pois(self._grouped_result(query, project, scope, rows, years, warnings))

    def _overview(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        available: set[str],
    ) -> dict[str, Any]:
        catalog = {item.tool_id: item for item in self._catalog().catalog()}
        metrics = []
        registered_metric_ids = set(METRIC_BINDINGS) | set(CATALOG_SCOPE_BINDINGS)
        metric_ids = [metric_id for metric_id in catalog if metric_id in registered_metric_ids]
        metric_ids.extend(metric_id for metric_id in METRIC_BINDINGS if metric_id not in catalog)
        for metric_id in metric_ids:
            binding = METRIC_BINDINGS.get(metric_id)
            item = catalog.get(metric_id)
            catalog_binding = CATALOG_SCOPE_BINDINGS.get(metric_id)
            source_ids = binding.source_ids if binding else (catalog_binding.source_ids if catalog_binding else ())
            data_status = "ready" if any(source in available for source in source_ids) else "unavailable"
            if catalog_binding and not source_ids:
                data_status = "ready"
            supported_analyses = list(binding.supported_analyses) if binding else ["scope"]
            analysis_profile = (
                "all"
                if supported_analyses == list(MetricBinding.__dataclass_fields__["supported_analyses"].default)
                else ",".join(supported_analyses)
            )
            metrics.append({
                "metric_id": metric_id,
                "available": data_status == "ready",
                "analyses": analysis_profile,
            })
        datasets = [
            {
                "dataset_id": DATASET_FIELD_CATALOG.get(str(item.get("source_id") or ""), {}).get("dataset_id", ""),
                "title": str(item.get("title") or ""),
                "year": item.get("selected_year"),
                "record_count": int(item.get("record_count") or 0),
                "status": str(item.get("status") or ""),
                "identity_fields": DATASET_FIELD_CATALOG.get(str(item.get("source_id") or ""), {}).get("identity_fields", []),
                "measure_fields": DATASET_FIELD_CATALOG.get(str(item.get("source_id") or ""), {}).get("measure_fields", []),
            }
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("source_id") or "") in DATASET_FIELD_CATALOG
        ]
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=metrics,
            summary={
                "catalog_metric_count": len(metrics),
                "available_metric_count": sum(item["available"] for item in metrics),
                "datasets": datasets,
            },
            coverage={"complete": True, "available_dataset_count": len(available)},
            limitations=[],
            method={"kind": "spatial_evidence_catalog", "scope_policy": "current_saved_scope_only"},
            provenance=self._provenance(project, {}, available),
        )

    def _catalog_scope_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
    ) -> dict[str, Any]:
        """Run explicitly registered catalog range strategies behind the semantic contract."""
        catalog = self._catalog()
        if not hasattr(catalog, "execute"):
            return self._unavailable(query, project, "目录执行器当前不可用。", scope=scope)
        source_index = SourceIndex(run_id=str(project.get("history_id") or ""), project_name=str(project.get("project_name") or ""))
        history_detail = dict(project)
        raw_scope = project.get("scope")
        if isinstance(raw_scope, Mapping):
            raw_scope = raw_scope.get("polygon") or raw_scope.get("coordinates")
        if isinstance(raw_scope, list):
            history_detail["polygon"] = raw_scope[0] if raw_scope and isinstance(raw_scope[0], list) and raw_scope[0] and isinstance(raw_scope[0][0], (list, tuple)) else raw_scope
        project_documents = {"project_name": project.get("project_name", ""), "documents": project.get("documents", [])}
        parameters = {"selectors": [selector.model_dump(mode="json") for selector in query.selectors]}
        summary: dict[str, Any] = {}
        evidence: list[dict[str, Any]] = []
        limitations: list[str] = []
        statuses: list[str] = []
        result_records: list[dict[str, Any]] = []
        used_sources: set[str] = set()
        for metric_id in query.metric_ids:
            item = next((entry for entry in catalog.catalog() if entry.tool_id == metric_id), None)
            if item is None:
                statuses.append("unavailable")
                limitations.append(f"目录中没有指标 {metric_id} 的执行定义。")
                continue
            try:
                result = catalog.execute(
                    tool_id=metric_id,
                    history_id=str(project.get("history_id") or ""),
                    history_detail=history_detail,
                    project_documents=project_documents,
                    source_index=source_index,
                    parameters=parameters,
                    project_anchors=project.get("params") if isinstance(project.get("params"), Mapping) else {},
                )
                status = str(result.status)
                statuses.append(status)
                structured = _compact_value(result.structured_result or {"summary": result.summary})
                if isinstance(structured, dict):
                    # Keep domain result metadata alongside the metric payload so saved
                    # isochrone responses remain auditable without exposing geometry.
                    structured.setdefault("result_id", result.result_id)
                    structured.setdefault("tool_id", result.tool_id)
                    structured.setdefault("tool_version", result.tool_version)
                    structured.setdefault("status", result.status)
                    structured.setdefault("input_sources", list(result.input_sources))
                    structured.setdefault("spatial_scope", _compact_value(result.spatial_scope))
                    structured.setdefault("time_scope", _compact_value(result.time_scope))
                    structured.setdefault("limitations", list(result.limitations))
                summary[metric_id] = structured
                used_sources.update(str(source) for source in result.input_sources if str(source).strip())
                result_records.append({
                    "metric_id": metric_id,
                    "result_id": result.result_id,
                    "tool_version": result.tool_version,
                    "status": result.status,
                    "input_sources": list(result.input_sources),
                    "spatial_scope": _compact_value(result.spatial_scope),
                    "time_scope": _compact_value(result.time_scope),
                })
                limitations.extend(str(value) for value in result.limitations if str(value).strip())
                evidence.append(self._evidence(project, query, f"metric:{metric_id}", [metric_id], [], summary[metric_id]))
            except (LookupError, ValueError, TypeError) as exc:
                statuses.append("unavailable")
                limitations.append(f"{metric_id} 执行不可用：{type(exc).__name__}。")
        status = "available" if any(value == "available" for value in statuses) else "unavailable"
        provenance = self._provenance(project, {}, used_sources)
        provenance["results"] = result_records
        provenance["data_versions"] = {
            str(item.get("source_id")): {
                str(key): item[key]
                for key in ("version", "dataset_version", "data_version", "selected_year", "snapshot_id")
                if item.get(key) not in (None, "")
            }
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("source_id") or "") in used_sources
        }
        params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        route_version = {
            str(key): params[key]
            for key in ("mode", "time_min", "road_version", "route_provider", "network_version", "data_version")
            if params.get(key) not in (None, "")
        }
        if route_version:
            provenance["analysis_parameters"] = route_version
        return self._response(
            query=query,
            project=project,
            scope=scope,
            status=status,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=summary,
            coverage={"complete": all(value == "available" for value in statuses), "metric_statuses": dict(zip(query.metric_ids, statuses))},
            evidence=evidence,
            limitations=limitations,
            method={
                "kind": "catalog_scope_strategy",
                "scope_policy": "current_saved_scope_only",
                "isochrone_mode": "scope + isochrone.reachable_area or access.network_reachable_area",
            },
            provenance=provenance,
        )

    def _scope_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        records: Mapping[str, list[ScopeRecord]],
        years: Mapping[str, int | None],
        warnings: list[str],
        scope_geometry: BaseGeometry,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        evidence: list[dict[str, Any]] = []
        highlights: list[dict[str, Any]] = []
        used_sources: set[str] = set()
        skipped = 0
        metric_record_counts: dict[str, int] = {}
        valid_value_counts: dict[str, int] = {}
        center = tuple(scope["center_wgs84"])
        limitations = list(warnings)
        for metric_id in query.metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            source_id = self._metric_source(binding, records, query)
            selected = self._selected_records(records.get(source_id, []), query.selectors, source_id)
            in_scope = [
                record
                for record in selected
                if self._has_measure_overlap(record.geometry, scope_geometry)
            ]
            values = [self._direct_record_value(binding, record) for record in in_scope]
            numeric = [value for value in values if value is not None]
            skipped += len(values) - len(numeric)
            metric_record_counts[metric_id] = len(in_scope)
            valid_value_counts[metric_id] = len(numeric)
            if metric_id == "population.profile":
                summary[metric_id] = self._population_profile_for_geometry(in_scope, scope_geometry)
            else:
                summary[metric_id] = self._metric_value_for_geometry(binding, in_scope, scope_geometry)
            if source_id:
                used_sources.add(source_id)
            evidence.append(self._evidence(project, query, f"metric:{metric_id}", [metric_id], [], summary[metric_id]))
            remaining = max(0, query.top_k - len(highlights))
            representative = [
                record
                for record in self._representative_records(binding, records, query)
                if self._has_measure_overlap(record.geometry, scope_geometry)
            ]
            for record in representative[:remaining]:
                row = self._row_from_record(record, center, [metric_id])
                if row is not None:
                    highlights.append(self._highlight(row, [metric_id], reason=f"{metric_id} 具名记录"))
        limitations.extend(self._metric_coverage_limitations(metric_record_counts, valid_value_counts))
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=summary,
            highlights=highlights,
            coverage={
                "complete": skipped == 0,
                "metric_spatial_unit_count": metric_record_counts,
                "valid_value_count": valid_value_counts,
                "skipped_value_count": skipped,
                "missing_values": "excluded_not_zero_filled",
            },
            evidence=evidence,
            limitations=limitations,
            method={
                "kind": "scope_intersection_aggregation",
                "scope_policy": "saved_scope_geometry_only",
                "spatial_aggregation": "intersecting_full_cells",
                "boundary_cell_policy": "include_full_cell_value",
                "line_aggregation": "intersection_length_or_length_weighted",
                "missing_values": "excluded_not_zero_filled",
            },
            provenance=self._provenance(project, years, used_sources),
        )

    def _population_profile_for_geometry(
        self,
        records: Sequence[ScopeRecord],
        geometry: BaseGeometry,
    ) -> dict[str, Any]:
        def total(binding: MetricBinding) -> float:
            return float(self._metric_value_for_geometry(binding, records, geometry) or 0.0)

        population_total = total(METRIC_BINDINGS["population.total"])
        male_total = total(METRIC_BINDINGS["population.male"])
        female_total = total(METRIC_BINDINGS["population.female"])
        return {
            "total_population": _rounded(population_total),
            "sex_totals": {
                "total": _rounded(population_total),
                "male": _rounded(male_total),
                "female": _rounded(female_total),
            },
            "age_distribution": [
                {
                    "age_band": band,
                    "age_band_label": get_age_band_label(band),
                    "total": _rounded(total(METRIC_BINDINGS[f"population.age.{band}.total"])),
                    "male": _rounded(total(METRIC_BINDINGS[f"population.age.{band}.male"])),
                    "female": _rounded(total(METRIC_BINDINGS[f"population.age.{band}.female"])),
                }
                for band in POPULATION_AGE_BANDS
            ],
        }

    def _representative_records(
        self,
        binding: MetricBinding,
        records: Mapping[str, list[ScopeRecord]],
        query: SpatialEvidenceRequest,
    ) -> list[ScopeRecord]:
        source_id = self._metric_source(binding, records, query)
        selected = self._selected_records(records.get(source_id, []), query.selectors, source_id)

        def sort_key(record: ScopeRecord) -> tuple[float, str, str]:
            value = self._direct_record_value(binding, record)
            if value is None and source_id == _POI and binding.metric_id.startswith("poi."):
                value = 1.0
            return (-(value if value is not None else float("-inf")), record.title, record.record_id)

        ordered = sorted(selected, key=sort_key)
        if source_id not in {_POI, _ROAD_EDGES}:
            return ordered
        distinct: list[ScopeRecord] = []
        seen_names: set[str] = set()
        identity_field = "name" if source_id == _POI else "road_name"
        named = [record for record in ordered if str(record.properties.get(identity_field) or "").strip()]
        for record in named or ordered:
            name = str(record.properties.get(identity_field) or record.title or record.record_id).strip()
            identity_key = name.casefold()
            if identity_key in seen_names:
                continue
            seen_names.add(identity_key)
            distinct.append(record)
        return distinct

    def _row_from_record(
        self,
        record: ScopeRecord,
        center: tuple[float, float],
        metric_ids: Sequence[str],
    ) -> _SpatialRow | None:
        geometry = record.geometry
        if geometry is None or geometry.is_empty:
            return None
        centroid = geometry.centroid
        if centroid.is_empty:
            return None
        distance, direction = _distance_direction(center, (centroid.x, centroid.y))
        values: dict[str, float | None] = {}
        for metric_id in metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            value = self._direct_record_value(binding, record) if record.source_id in binding.source_ids else None
            if value is None and record.source_id == _POI and metric_id.startswith("poi."):
                value = 1.0
            values[metric_id] = value
        return _SpatialRow(
            record_ref=self._record_ref(record),
            source_id=record.source_id,
            record_id=record.record_id,
            title=record.title,
            geometry=geometry,
            centroid=(centroid.x, centroid.y),
            distance_m=distance,
            direction=direction,
            area_km2=_area_km2(geometry),
            values=values,
            aggregation_factors={metric_id: 1.0 for metric_id in metric_ids},
            identity=self._record_identity(record),
        )

    def _grouped_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        rows: list[_SpatialRow],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        groups: list[dict[str, Any]] = []
        for direction in DIRECTION_CODES:
            members = [row for row in rows if row.direction == direction]
            payload = self._group_payload(direction, members, query.metric_ids)
            payload["label"] = DIRECTION_LABELS[direction]
            groups.append(payload)
        evidence = [
            self._evidence(project, query, f"group:{group['key']}", query.metric_ids, [], group["values"])
            for group in groups
        ]
        primary_metric = query.metric_ids[0]
        representative_rows = sorted(
            (row for row in rows if row.values.get(primary_metric) is not None),
            key=lambda row: (-float(row.values[primary_metric]), row.record_ref),
        )[: query.top_k]
        coverage = self._row_coverage(rows, query.metric_ids)
        provenance = self._provenance(project, years, {row.source_id for row in rows})
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=self._group_payload("overall", rows, query.metric_ids)["values"],
            groups=groups[:32],
            highlights=[
                self._highlight(row, query.metric_ids, reason=f"{query.analysis} 中 {primary_metric} 高值记录")
                for row in representative_rows
            ],
            coverage=coverage,
            evidence=evidence[:32],
            limitations=warnings + self._row_coverage_limitations(coverage),
            method={
                "kind": f"{query.analysis}_grouping",
                "direction_sectors": 8,
                "missing_values": "excluded_not_zero_filled",
            },
            provenance=provenance,
        )

    def _rank_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        rows: list[_SpatialRow],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        metric_id = query.metric_ids[0]
        valid = [row for row in rows if row.values.get(metric_id) is not None]
        if not valid:
            return self._unavailable(
                query,
                project,
                f"{METRIC_BINDINGS[metric_id].label}没有可用于排名的有效记录。",
                scope=scope,
            )
        valid.sort(key=lambda row: float(row.values[metric_id]), reverse=query.rank_order == "highest")
        highlights = [self._highlight(row, query.metric_ids, reason=f"{metric_id} {query.rank_order}") for row in valid[: query.top_k]]
        evidence = [
            self._evidence(project, query, f"record:{row.record_ref}", [metric_id], [row.record_ref], row.values)
            for row in valid[: query.top_k]
        ]
        coverage = self._row_coverage(rows, query.metric_ids)
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary={"ranked_metric": metric_id, "order": query.rank_order, "valid_record_count": len(valid)},
            highlights=highlights,
            coverage=coverage,
            evidence=evidence,
            limitations=warnings + self._row_coverage_limitations(coverage),
            method={"kind": "single_metric_rank", "normalization": "none", "combined_score": False},
            provenance=self._provenance(project, years, {row.source_id for row in rows}),
        )

    def _neighborhood_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        rows: list[_SpatialRow],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        targets = [row for row in rows if self._matches_ref(row.record_ref, query.record_refs)]
        groups = []
        highlights = []
        for target in targets[:20]:
            neighborhood = {target.record_ref: target}
            frontier = [target]
            for _ in range(query.neighbor_steps):
                next_frontier = []
                for candidate in rows:
                    if candidate.record_ref in neighborhood:
                        continue
                    if any(self._neighbors(item, candidate, query.neighbor_steps) for item in frontier):
                        neighborhood[candidate.record_ref] = candidate
                        next_frontier.append(candidate)
                frontier = next_frontier
            members = list(neighborhood.values())
            payload = self._group_payload(target.record_ref, members, query.metric_ids)
            payload["target_values"] = dict(target.values)
            payload["neighbor_count"] = max(0, len(members) - 1)
            groups.append(payload)
            highlights.append(self._highlight(target, query.metric_ids, reason=f"{query.neighbor_steps}级邻域目标"))
        if not targets:
            return self._unavailable(query, project, "指定 record_refs 不属于本次分析空间单元。", scope=scope)
        evidence = [
            self._evidence(project, query, f"neighborhood:{group['key']}", query.metric_ids, [group["key"]], group["values"])
            for group in groups
        ]
        coverage = self._row_coverage(rows, query.metric_ids)
        summary: dict[str, Any] = {"target_count": len(targets), "neighbor_steps": query.neighbor_steps}
        if any(row.source_id == _H3 for row in rows):
            h3_summary = self._dataset_summary(project, _H3)
            moran_i = _number(h3_summary.get("global_moran_i_density"))
            moran_z = _number(h3_summary.get("global_moran_z_score"))
            if moran_i is not None:
                summary["density_spatial_autocorrelation"] = {
                    "global_moran_i": moran_i,
                    "global_moran_z_score": moran_z,
                    "significance_status": "available" if moran_z is not None else "not_available",
                    "statistic_scope": "all_persisted_h3_cells",
                    "spatial_unit_count": int(_number(h3_summary.get("grid_count")) or len(rows)),
                    "poi_count_in_spatial_units": int(_number(h3_summary.get("poi_count")) or 0),
                }
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=summary,
            groups=groups,
            highlights=highlights,
            coverage=coverage,
            evidence=evidence,
            limitations=warnings + self._row_coverage_limitations(coverage),
            method={
                "kind": "road_edge_topology" if rows and rows[0].source_id == _ROAD_EDGES else "geometry_adjacency",
                "neighbor_steps": query.neighbor_steps,
                "local_statistics": "persisted_h3_spatial_statistics" if rows and rows[0].source_id == _H3 else None,
                "spatial_statistics_recomputed": False,
            },
            provenance=self._provenance(project, years, {row.source_id for row in rows}),
        )

    @staticmethod
    def _neighbors(left: _SpatialRow, right: _SpatialRow, steps: int) -> bool:
        """Use H3's canonical k-ring when both records expose H3 cell IDs."""
        if left.source_id == _ROAD_EDGES and right.source_id == _ROAD_EDGES:
            left_nodes = {str(left.identity.get("from_node") or ""), str(left.identity.get("to_node") or "")} - {""}
            right_nodes = {str(right.identity.get("from_node") or ""), str(right.identity.get("to_node") or "")} - {""}
            return bool(left_nodes & right_nodes)
        if left.source_id == _H3 and right.source_id == _H3:
            try:
                import h3

                cell = str(left.record_id)
                if hasattr(h3, "grid_disk"):
                    return str(right.record_id) in {str(item) for item in h3.grid_disk(cell, steps)}
                if hasattr(h3, "k_ring"):
                    return str(right.record_id) in {str(item) for item in h3.k_ring(cell, steps)}
            except (ImportError, ValueError, TypeError):
                pass
        return left.geometry.buffer(1e-12).intersects(right.geometry.buffer(1e-12))

    def _relationship_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        rows: list[_SpatialRow],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        complete = [row for row in rows if all(row.values.get(metric_id) is not None for metric_id in query.metric_ids)]
        if len(complete) < 20:
            return self._unavailable(
                query,
                project,
                f"共同有效空间单元只有 {len(complete)} 个，少于关系分析要求的 20 个。",
                scope=scope,
            )
        thresholds = {
            metric_id: {
                "p25": _quantile([float(row.values[metric_id]) for row in complete], 0.25),
                "p75": _quantile([float(row.values[metric_id]) for row in complete], 0.75),
            }
            for metric_id in query.metric_ids
        }
        patterns = {"joint_high": [], "joint_low": [], "conflict": [], "middle": []}
        for row in complete:
            states = []
            for metric_id in query.metric_ids:
                value = float(row.values[metric_id])
                threshold = thresholds[metric_id]
                states.append("high" if value >= threshold["p75"] else "low" if value <= threshold["p25"] else "middle")
            pattern = "joint_high" if all(state == "high" for state in states) else "joint_low" if all(state == "low" for state in states) else "conflict" if "high" in states and "low" in states else "middle"
            patterns[pattern].append(row)
        relationship = {
            "spatial_unit_count": len(complete),
            "thresholds": thresholds,
            "pattern_counts": {key: len(value) for key, value in patterns.items()},
            "correlation_computed": False,
            "combined_score_computed": False,
        }
        highlighted = (patterns["joint_high"] + patterns["conflict"] + patterns["joint_low"])[: query.top_k]
        highlights = [
            self._highlight(row, query.metric_ids, reason=next(key for key, values in patterns.items() if row in values))
            for row in highlighted
        ]
        evidence = [
            self._evidence(project, query, f"relationship:{key}", query.metric_ids, [row.record_ref for row in values[: query.top_k]], {"count": len(values)})
            for key, values in patterns.items()
        ]
        coverage = self._row_coverage(rows, query.metric_ids)
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary={"common_valid_cell_count": len(complete)},
            highlights=highlights,
            relationship=relationship,
            coverage=coverage,
            evidence=evidence,
            limitations=(
                warnings
                + self._row_coverage_limitations(coverage)
                + ["分位共位仅描述空间共同出现，不表示因果关系。"]
            ),
            method={"kind": "p25_p75_colocation", "correlation": False, "combined_score": False},
            provenance=self._provenance(project, years, {row.source_id for row in rows}),
        )

    def _inspect_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        records: Mapping[str, list[ScopeRecord]],
        years: Mapping[str, int | None],
        warnings: list[str],
        scope_geometry: BaseGeometry,
    ) -> dict[str, Any]:
        center = tuple(scope["center_wgs84"])
        selected_by_source = {
            source_id: self._selected_records(values, query.selectors, source_id)
            for source_id, values in records.items()
        }
        selected_refs = {
            source_id: {self._record_ref(record) for record in values}
            for source_id, values in selected_by_source.items()
        }
        indexes = {source_id: _RecordIndex(values) for source_id, values in selected_by_source.items()}
        matches = [
            record
            for values in records.values()
            for record in values
            if self._matches_ref(self._record_ref(record), query.record_refs)
        ][:20]
        highlights = []
        evidence = []
        for record in matches:
            centroid = record.geometry.centroid if record.geometry is not None else None
            if centroid is None or centroid.is_empty:
                continue
            distance, direction = _distance_direction(center, (centroid.x, centroid.y))
            values = {}
            for metric_id in query.metric_ids:
                binding = METRIC_BINDINGS[metric_id]
                source_id = self._metric_source(binding, selected_by_source, query)
                if source_id == record.source_id:
                    values[metric_id] = (
                        self._direct_record_value(binding, record)
                        if self._record_ref(record) in selected_refs.get(source_id, set())
                        else None
                    )
                else:
                    unit_geometry = record.geometry.intersection(scope_geometry)
                    candidates = indexes.get(source_id, _RecordIndex([])).query(unit_geometry)
                    values[metric_id] = self._value_for_unit(binding, unit_geometry, candidates)
            row = _SpatialRow(
                record_ref=self._record_ref(record), source_id=record.source_id, record_id=record.record_id,
                title=record.title, geometry=record.geometry, centroid=(centroid.x, centroid.y), distance_m=distance,
                direction=direction, area_km2=_area_km2(record.geometry), values=values,
                aggregation_factors={metric_id: 1.0 for metric_id in query.metric_ids},
                identity=self._record_identity(record),
            )
            highlight = self._highlight(row, query.metric_ids, reason="指定空间记录")
            attributes = self._record_attributes(record)
            if attributes:
                highlight["attributes"] = attributes
            highlights.append(highlight)
            evidence.append(self._evidence(project, query, f"record:{row.record_ref}", query.metric_ids, [row.record_ref], values))
        remaining = max(0, min(20, query.top_k) - len(highlights))
        grid_sources = {_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT, _ROAD_GRID}
        for target in matches:
            if remaining <= 0 or target.source_id not in grid_sources:
                continue
            for related, relation in self._named_relations(target, records, limit=remaining):
                row = self._row_from_record(related, center, query.metric_ids)
                if row is None:
                    continue
                highlight = self._highlight(row, query.metric_ids, reason="目标单元具名空间关系")
                attributes = self._record_attributes(related)
                if attributes:
                    highlight["attributes"] = attributes
                highlight["relation_to_target"] = {
                    "target_record_ref": self._record_ref(target),
                    "kind": relation,
                    "distance_m": _geometry_distance_m(target.geometry, related.geometry),
                }
                highlights.append(highlight)
                evidence.append(
                    self._evidence(
                        project,
                        query,
                        f"relation:{self._record_ref(target)}:{row.record_ref}",
                        query.metric_ids,
                        [self._record_ref(target), row.record_ref],
                        {"relation": relation, "values": row.values},
                    )
                )
                remaining -= 1
                if remaining <= 0:
                    break
        if not highlights:
            return self._unavailable(query, project, "没有找到指定的空间记录。", scope=scope)
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary={
                "matched_record_count": len(matches),
                "related_named_record_count": max(0, len(highlights) - len(matches)),
            },
            highlights=highlights,
            named_spatial_objects=[
                {
                    "record_ref": item["record_ref"],
                    "title": item["title"],
                    "identity": item.get("identity", {}),
                    "attributes": item.get("attributes", {}),
                    "relation_to_target": item.get("relation_to_target"),
                }
                for item in highlights
            ],
            coverage={"complete": len(matches) == len(query.record_refs), "matched_record_count": len(matches)},
            evidence=evidence,
            limitations=warnings,
            method={
                "kind": "stable_record_lookup_with_named_relations",
                "relations": ["contained_poi", "intersecting_road", "nearest_poi", "nearest_road"],
                "geometry_returned": False,
            },
            provenance=self._provenance(project, years, {record.source_id for record in matches}),
        )

    def _named_relations(
        self,
        target: ScopeRecord,
        records: Mapping[str, list[ScopeRecord]],
        *,
        limit: int,
    ) -> list[tuple[ScopeRecord, str]]:
        """Project a grid target to bounded, named POI and road facts."""
        geometry = target.geometry
        if geometry is None or geometry.is_empty or limit <= 0:
            return []

        poi_records = [
            record
            for record in records.get(_POI, [])
            if record.geometry is not None
            and not record.geometry.is_empty
            and str(record.properties.get("name") or record.title or "").strip()
        ]
        road_records = [
            record
            for record in records.get(_ROAD_EDGES, [])
            if record.geometry is not None
            and not record.geometry.is_empty
            and str(record.properties.get("road_name") or record.title or "").strip()
        ]
        related: list[tuple[ScopeRecord, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(record: ScopeRecord, relation: str) -> None:
            identity = str(
                record.properties.get("name")
                or record.properties.get("road_name")
                or record.title
                or record.record_id
            ).strip().casefold()
            key = (record.source_id, identity)
            if not identity or key in seen or len(related) >= limit:
                return
            seen.add(key)
            related.append((record, relation))

        for record in sorted(poi_records, key=lambda item: (item.title, item.record_id)):
            if geometry.intersects(record.geometry):
                add(record, "contained_poi")
        for record in sorted(road_records, key=lambda item: (str(item.properties.get("road_name") or item.title), item.record_id)):
            if geometry.intersects(record.geometry):
                add(record, "intersecting_road")

        # Fill any remaining response capacity with the closest named context.
        # This is a deterministic fact projection, not a recommendation to query further.
        if len(related) < limit:
            for record in sorted(poi_records, key=lambda item: (geometry.distance(item.geometry), item.title, item.record_id)):
                if geometry.intersects(record.geometry):
                    continue
                add(record, "nearest_poi")
                if len(related) >= limit:
                    break
        if len(related) < limit:
            for record in sorted(road_records, key=lambda item: (geometry.distance(item.geometry), str(item.properties.get("road_name") or item.title), item.record_id)):
                if geometry.intersects(record.geometry):
                    continue
                add(record, "nearest_road")
                if len(related) >= limit:
                    break
        return related

    def _named_poi_candidates(
        self,
        query: SpatialEvidenceRequest,
        records: Mapping[str, list[ScopeRecord]],
        center: tuple[float, float],
    ) -> dict[str, list[dict[str, Any]]]:
        pois = [
            record
            for record in records.get(_POI, [])
            if record.geometry is not None
            and not record.geometry.is_empty
            and str(record.properties.get("name") or record.title or "").strip()
        ]
        selectors = [
            selector
            for selector in query.selectors
            if selector.dimension in {"poi.category", "poi.subcategory"}
        ]
        result: dict[str, list[dict[str, Any]]] = {}
        limit = min(6, max(1, query.top_k))
        for role in dict.fromkeys(query.named_poi_roles):
            candidates = [
                record
                for record in pois
                if (
                    (role == "comparable_supply" and (not selectors or self._poi_matches_selectors(record, selectors)))
                    or (role != "comparable_supply" and self._poi_matches_role(record, role))
                )
            ]
            ranked = sorted(
                candidates,
                key=lambda record: self._named_poi_sort_key(record, role, selectors, center),
            )
            selected: list[ScopeRecord] = []
            seen_names: set[str] = set()
            seen_categories: set[str] = set()
            seen_directions: set[str] = set()
            while ranked and len(selected) < limit:
                def diversified_key(item: ScopeRecord) -> tuple[Any, ...]:
                    base = self._named_poi_sort_key(item, role, selectors, center)
                    return (
                        base[0],
                        base[1],
                        str(item.properties.get("category") or "") in seen_categories,
                        self._poi_direction(item, center) in seen_directions,
                        *base[2:],
                    )

                record = min(
                    ranked,
                    key=diversified_key,
                )
                ranked.remove(record)
                name = str(record.properties.get("name") or record.title or "").strip()
                if name.casefold() in seen_names:
                    continue
                seen_names.add(name.casefold())
                seen_categories.add(str(record.properties.get("category") or ""))
                seen_directions.add(self._poi_direction(record, center))
                selected.append(record)
            result[role] = [self._named_poi_payload(record, role, selectors, center) for record in selected]
        return result

    @staticmethod
    def _poi_matches_role(record: ScopeRecord, role: NamedPoiRole) -> bool:
        category = str(record.properties.get("category") or "")
        typecode = str(record.properties.get("typecode") or "")
        return category in _POI_ROLE_CATEGORIES[role] or typecode[:2] in _POI_ROLE_TYPECODE_PREFIXES[role]

    @staticmethod
    def _poi_matches_selectors(
        record: ScopeRecord,
        selectors: Sequence[SpatialEvidenceSelector],
    ) -> bool:
        for selector in selectors:
            field = "category" if selector.dimension == "poi.category" else "subcategory"
            if selector.dimension == "poi.category":
                record_category = _resolve_poi_category(record.properties.get(field))
                selected_categories = {_resolve_poi_category(value) for value in selector.values}
                if record_category not in selected_categories:
                    return False
            elif str(record.properties.get(field) or "") not in {str(value) for value in selector.values}:
                return False
        return True

    @staticmethod
    def _poi_direction(record: ScopeRecord, center: tuple[float, float]) -> str:
        centroid = record.geometry.centroid
        return _distance_direction(center, (centroid.x, centroid.y))[1]

    def _named_poi_sort_key(
        self,
        record: ScopeRecord,
        role: NamedPoiRole,
        selectors: Sequence[SpatialEvidenceSelector],
        center: tuple[float, float],
    ) -> tuple[int, int, int, float, str, str]:
        category = str(record.properties.get("category") or "")
        typecode = str(record.properties.get("typecode") or "")
        category_order = _POI_ROLE_CATEGORIES[role]
        prefix_order = _POI_ROLE_TYPECODE_PREFIXES[role]
        category_rank = category_order.index(category) if category in category_order else len(category_order) + 1
        prefix = typecode[:2]
        typecode_rank = prefix_order.index(prefix) if prefix in prefix_order else len(prefix_order) + 1
        selector_rank = 0 if selectors and self._poi_matches_selectors(record, selectors) else 1
        identity_rank = 0 if typecode and record.properties.get("subcategory") else 1
        centroid = record.geometry.centroid
        distance, _ = _distance_direction(center, (centroid.x, centroid.y))
        return (
            selector_rank if role == "comparable_supply" else 0,
            min(category_rank, typecode_rank),
            identity_rank,
            distance,
            str(record.properties.get("name") or record.title or "").casefold(),
            record.record_id,
        )

    def _named_poi_payload(
        self,
        record: ScopeRecord,
        role: NamedPoiRole,
        selectors: Sequence[SpatialEvidenceSelector],
        center: tuple[float, float],
    ) -> dict[str, Any]:
        centroid = record.geometry.centroid
        distance, direction = _distance_direction(center, (centroid.x, centroid.y))
        category = str(record.properties.get("category") or "")
        subcategory = str(record.properties.get("subcategory") or "")
        typecode = str(record.properties.get("typecode") or "")
        basis = [f"高德分类为{category or '未分类'}" + (f"/{subcategory}" if subcategory else "")]
        if selectors and self._poi_matches_selectors(record, selectors):
            basis.append("符合本次POI类别筛选")
        if category in _POI_ROLE_CATEGORIES[role] or typecode[:2] in _POI_ROLE_TYPECODE_PREFIXES[role]:
            basis.append(f"功能类型符合{role}候选范围")
        basis.append(f"位于项目{DIRECTION_LABELS[direction]}侧约{round(distance):.0f}米")
        return {
            "record_ref": self._record_ref(record),
            "name": str(record.properties.get("name") or record.title or ""),
            "category": category,
            "subcategory": subcategory,
            "typecode": typecode,
            "direction": direction,
            "straight_line_distance_m": round(distance, 1),
            "role": role,
            "selection_basis": basis,
        }

    def _spatial_rows(
        self,
        query: SpatialEvidenceRequest,
        base_source: str,
        base_records: Sequence[ScopeRecord],
        records: Mapping[str, list[ScopeRecord]],
        center: tuple[float, float],
        scope_geometry: BaseGeometry,
    ) -> list[_SpatialRow]:
        selected_by_source = {
            source_id: self._selected_records(values, query.selectors, source_id)
            for source_id, values in records.items()
        }
        selected_refs = {
            source_id: {self._record_ref(record) for record in values}
            for source_id, values in selected_by_source.items()
        }
        indexes = {source_id: _RecordIndex(values) for source_id, values in selected_by_source.items()}
        rows = []
        for base in base_records:
            geometry = base.geometry
            if geometry is None or geometry.is_empty or not self._has_measure_overlap(geometry, scope_geometry):
                continue
            clipped_geometry = geometry.intersection(scope_geometry)
            centroid = geometry.centroid
            distance, direction = _distance_direction(center, (centroid.x, centroid.y))
            values: dict[str, float | None] = {}
            aggregation_factors: dict[str, float] = {}
            for metric_id in query.metric_ids:
                binding = METRIC_BINDINGS[metric_id]
                source_id = self._metric_source(binding, selected_by_source, query)
                if source_id == base_source:
                    values[metric_id] = (
                        self._direct_record_value(binding, base)
                        if self._record_ref(base) in selected_refs.get(source_id, set())
                        else None
                    )
                    aggregation_factors[metric_id] = (
                        self._geometry_overlap_fraction(geometry, scope_geometry)
                        if binding.aggregate == "sum" and geometry.geom_type in {"LineString", "MultiLineString"}
                        else 1.0
                    )
                else:
                    candidates = indexes.get(source_id, _RecordIndex([])).query(clipped_geometry)
                    values[metric_id] = self._value_for_unit(binding, clipped_geometry, candidates)
                    aggregation_factors[metric_id] = 1.0
            rows.append(_SpatialRow(
                record_ref=self._record_ref(base), source_id=base_source, record_id=base.record_id,
                title=base.title, geometry=geometry, centroid=(centroid.x, centroid.y), distance_m=distance,
                direction=direction, area_km2=_area_km2(geometry), values=values,
                aggregation_factors=aggregation_factors,
                identity=self._record_identity(base),
            ))
        return rows

    def _accessibility_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        records: Mapping[str, list[ScopeRecord]],
        years: Mapping[str, int | None],
        warnings: list[str],
        center: tuple[float, float],
        scope_geometry: BaseGeometry,
    ) -> dict[str, Any]:
        band_geometries, limitation = self._accessibility_band_geometries(
            query,
            project,
            center,
            scope_geometry,
        )
        if limitation:
            return self._unavailable(query, project, limitation, scope=scope)

        base_source = self._base_source(query, records)
        base_records = records.get(base_source, []) if base_source else []
        if not base_source or not base_records:
            return self._unavailable(
                query,
                project,
                "当前数据无法形成可达性分析所需的空间单元。",
                scope=scope,
            )

        selected_by_metric: dict[str, tuple[MetricBinding, list[ScopeRecord]]] = {}
        for metric_id in query.metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            source_id = self._metric_source(binding, records, query)
            selected_by_metric[metric_id] = (
                binding,
                self._selected_records(records.get(source_id, []), query.selectors, source_id),
            )

        groups: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        for band_index, (band, geometry) in enumerate(band_geometries):
            values = {
                metric_id: self._accessibility_metric_value(
                    binding,
                    selected,
                    band_geometries,
                    band_index,
                )
                for metric_id, (binding, selected) in selected_by_metric.items()
            }
            key = f"{_format_band_value(band[0])}-{_format_band_value(band[1])}min"
            group = {
                "key": key,
                "spatial_unit_count": sum(
                    self._has_measure_overlap(record.geometry, geometry)
                    for record in base_records
                ),
                "values": values,
            }
            groups.append(group)
            evidence.append(self._evidence(project, query, f"group:{key}", query.metric_ids, [], values))

        summary = {
            metric_id: self._metric_value_for_geometry(binding, selected, scope_geometry)
            for metric_id, (binding, selected) in selected_by_metric.items()
        }
        scope_units = [
            record
            for record in base_records
            if self._has_measure_overlap(record.geometry, scope_geometry)
        ]
        allocated_units = [
            record
            for record in scope_units
            if any(self._has_measure_overlap(record.geometry, geometry) for _, geometry in band_geometries)
        ]
        allocation_assumptions = []
        if any(
            binding.aggregate == "sum"
            and any(
                record.geometry is not None
                and record.geometry.geom_type in {"Polygon", "MultiPolygon"}
                for record in selected
            )
            for binding, selected in selected_by_metric.values()
        ):
            allocation_assumptions.append("uniform_distribution_within_polygon_record")

        provenance = self._provenance(project, years, {
            record.source_id
            for _, selected in selected_by_metric.values()
            for record in selected
        })
        project_params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        scope_time_min = _number(project_params.get("time_min")) or DEFAULT_ISOCHRONE_TIME_MIN
        provenance["travel_time_model"] = {
            "provider": "valhalla",
            "mode": self._project_travel_mode(project),
            "requested_contour_times_min": [end for (start, end), _ in band_geometries],
            "exact_point_duration_returned": False,
        }
        limitations = list(warnings)
        if allocation_assumptions:
            limitations.append("面状总量按对象与时间环带的相交面积比例分配，假设对象内部均匀分布。")
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=summary,
            groups=groups,
            coverage={
                "complete": len(allocated_units) == len(scope_units),
                "spatial_unit_count": len(scope_units),
                "allocated_spatial_unit_count": len(allocated_units),
                "unallocated_spatial_unit_count": len(scope_units) - len(allocated_units),
                "geometry_coverage": "disjoint_bands_partition_requested_scope",
            },
            evidence=evidence,
            limitations=limitations,
            method={
                "kind": "accessibility_intersection_aggregation",
                "travel_time_bands_min": [list(band) for band, _ in band_geometries],
                "travel_mode": self._project_travel_mode(project),
                "travel_time_method": "valhalla_nested_isochrone_contours",
                "spatial_unit_assignment": "geometry_intersection_with_disjoint_time_bands",
                "extensive_metric_allocation": "intersection_fraction",
                "outer_band_boundary": "requested_valhalla_contour_clipped_to_saved_project_scope",
                "allocation_assumptions": allocation_assumptions,
                "missing_values": "excluded_not_zero_filled",
            },
            provenance=provenance,
        )

    def _accessibility_band_geometries(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        center: tuple[float, float],
        scope_geometry: BaseGeometry,
    ) -> tuple[list[tuple[tuple[float, float], BaseGeometry]], str | None]:
        mode = self._project_travel_mode(project)
        if mode not in {"walking", "driving", "bicycling"}:
            return [], "当前项目没有可供 Valhalla 重建分层等时圈的有效出行方式。"
        bands = self._travel_time_bands(query, project)
        params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        scope_time_min = _number(params.get("time_min")) or DEFAULT_ISOCHRONE_TIME_MIN
        if bands[-1][1] > scope_time_min + 1e-9:
            raise ValueError("travel_time_bands_exceed_saved_isochrone")
        contour_times = [end for _, end in bands]
        try:
            contours = self._isochrone_contours(center, contour_times, mode)
        except (ValhallaIsochroneUnavailable, TypeError, ValueError) as exc:
            return [], f"Valhalla 无法返回完整的分层等时圈：{exc}；未使用圆形或直线距离回退。"

        result: list[tuple[tuple[float, float], BaseGeometry]] = []
        covered: BaseGeometry | None = None
        try:
            for band in bands:
                raw_contour = contours.get(band[1])
                if raw_contour is None or raw_contour.is_empty:
                    return [], "Valhalla 返回的分层等时圈不完整；未使用圆形或直线距离回退。"
                cumulative = raw_contour.intersection(scope_geometry)
                if cumulative.is_empty:
                    return [], "Valhalla 分层等时圈与当前保存范围不相交。"
                geometry = cumulative if covered is None else cumulative.difference(covered)
                covered = cumulative if covered is None else covered.union(cumulative)
                result.append((band, geometry))
        except GEOSException as exc:
            return [], f"Valhalla 分层等时圈无法形成有效环带：{exc}。"
        return result, None

    def _accessibility_metric_value(
        self,
        binding: MetricBinding,
        records: Sequence[ScopeRecord],
        band_geometries: Sequence[tuple[tuple[float, float], BaseGeometry]],
        band_index: int,
    ) -> float | None:
        if records and all(
            record.geometry is not None and record.geometry.geom_type in {"Point", "MultiPoint"}
            for record in records
        ):
            selected = []
            for record in records:
                assigned_index = next(
                    (
                        index
                        for index, (_, geometry) in enumerate(band_geometries)
                        if geometry.covers(record.geometry)
                    ),
                    None,
                )
                if assigned_index == band_index:
                    selected.append(record)
            values = [self._direct_record_value(binding, record) for record in selected]
            return self._aggregate_values(binding, [value for value in values if value is not None])
        return self._value_for_unit(
            binding,
            band_geometries[band_index][1],
            records,
            allocate_areal_overlap=True,
        )

    def _metric_value_for_geometry(
        self,
        binding: MetricBinding,
        records: Sequence[ScopeRecord],
        geometry: BaseGeometry,
    ) -> float | None:
        if records and all(
            record.geometry is not None and record.geometry.geom_type in {"Point", "MultiPoint"}
            for record in records
        ):
            covered = [
                record
                for record in records
                if record.geometry is not None and geometry.covers(record.geometry)
            ]
            if binding.metric_id == "poi.category_count":
                return float(len({
                    str(record.properties.get("category") or "").strip()
                    for record in covered
                    if str(record.properties.get("category") or "").strip()
                }))
            values = [
                self._direct_record_value(binding, record)
                for record in covered
            ]
            return self._aggregate_values(binding, [value for value in values if value is not None])
        areal_records = [
            record
            for record in records
            if record.geometry is not None
            and record.geometry.geom_type in {"Polygon", "MultiPolygon"}
            and self._has_measure_overlap(record.geometry, geometry)
        ]
        if areal_records and len(areal_records) == len(records):
            values = [
                (value, float(record.geometry.area))
                for record in areal_records
                if (value := self._direct_record_value(binding, record)) is not None
            ]
            if not values:
                return None
            numeric = [value for value, _ in values]
            if binding.aggregate in {"sum", "max", "p90", "ratio_positive"}:
                return self._aggregate_values(binding, numeric)
            total_area = sum(area for _, area in values)
            return (
                sum(value * area for value, area in values) / total_area
                if total_area > 0
                else self._aggregate_values(binding, numeric)
            )
        return self._value_for_unit(binding, geometry, records)

    @staticmethod
    def _has_measure_overlap(record_geometry: BaseGeometry | None, geometry: BaseGeometry) -> bool:
        if record_geometry is None or record_geometry.is_empty or geometry.is_empty:
            return False
        intersection = record_geometry.intersection(geometry)
        if intersection.is_empty:
            return False
        if record_geometry.geom_type in {"Point", "MultiPoint"}:
            return True
        if record_geometry.geom_type in {"LineString", "MultiLineString"}:
            return intersection.length > 0
        return intersection.area > 0

    @staticmethod
    def _geometry_overlap_fraction(record_geometry: BaseGeometry, geometry: BaseGeometry) -> float:
        intersection = record_geometry.intersection(geometry)
        if intersection.is_empty:
            return 0.0
        if record_geometry.geom_type in {"Point", "MultiPoint"}:
            return 1.0
        if record_geometry.geom_type in {"LineString", "MultiLineString"}:
            return (
                float(intersection.length) / float(record_geometry.length)
                if record_geometry.length > 0
                else 0.0
            )
        return (
            float(intersection.area) / float(record_geometry.area)
            if record_geometry.area > 0
            else 0.0
        )

    @staticmethod
    def _project_travel_mode(project: Mapping[str, Any]) -> str:
        params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        mode = str(params.get("mode") or "walking").strip().lower()
        return {"walk": "walking", "pedestrian": "walking", "cycling": "bicycling", "bicycle": "bicycling", "auto": "driving"}.get(mode, mode)

    @staticmethod
    def _travel_time_bands(
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
    ) -> tuple[tuple[float, float], ...]:
        if query.travel_time_bands_min:
            return tuple(query.travel_time_bands_min)
        params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        scope_time_min = _number(params.get("time_min")) or DEFAULT_ISOCHRONE_TIME_MIN
        if abs(scope_time_min - DEFAULT_ISOCHRONE_TIME_MIN) < 1e-9:
            return DEFAULT_TRAVEL_TIME_BANDS_MIN
        step = scope_time_min / 3.0
        return ((0.0, step), (step, step * 2.0), (step * 2.0, scope_time_min))

    def _value_for_unit(
        self,
        binding: MetricBinding,
        unit: BaseGeometry,
        candidates: Sequence[ScopeRecord],
        *,
        allocate_areal_overlap: bool = False,
    ) -> float | None:
        if not candidates:
            return None
        if binding.source_ids[0] == _POI or all(record.geometry is not None and record.geometry.geom_type == "Point" for record in candidates):
            included = [record for record in candidates if record.geometry is not None and unit.covers(record.geometry)]
            if binding.metric_id == "poi.category_count":
                return float(len({
                    str(record.properties.get("category") or "").strip()
                    for record in included
                    if str(record.properties.get("category") or "").strip()
                }))
            if binding.metric_id in {"poi.count", "poi.grid_count"}:
                return float(len(included))
            if binding.metric_id in {"poi.grid_density", "poi.category_density"}:
                area = _area_km2(unit)
                return float(len(included)) / area if area > 0 else None
        weighted: list[tuple[float, float]] = []
        contributions: list[float] = []
        for record in candidates:
            if record.geometry is None or not unit.intersects(record.geometry):
                continue
            value = self._direct_record_value(binding, record)
            if value is None:
                continue
            intersection = unit.intersection(record.geometry)
            if intersection.is_empty:
                continue
            if record.geometry.geom_type in {"LineString", "MultiLineString"}:
                weight = float(intersection.length)
                fraction = weight / float(record.geometry.length) if record.geometry.length > 0 else 0.0
            elif record.geometry.geom_type in {"Point", "MultiPoint"}:
                weight = 1.0
                fraction = 1.0
            else:
                if allocate_areal_overlap:
                    weight = float(intersection.area)
                    fraction = weight / float(record.geometry.area) if record.geometry.area > 0 else 0.0
                else:
                    weight = float(record.geometry.area)
                    fraction = 1.0
            if weight <= 0:
                continue
            if binding.aggregate == "sum":
                contributions.append(value * fraction)
            else:
                weighted.append((value, weight))
        if binding.aggregate == "sum":
            return sum(contributions) if contributions else None
        if not weighted:
            return None
        if binding.aggregate == "max":
            return max(value for value, _ in weighted)
        if binding.aggregate == "p90":
            return _quantile([value for value, _ in weighted], 0.9)
        if binding.aggregate == "ratio_positive":
            return sum(1 for value, _ in weighted if value > 0) / len(weighted)
        total_weight = sum(weight for _, weight in weighted)
        return sum(value * weight for value, weight in weighted) / total_weight if total_weight > 0 else None

    def _direct_record_value(self, binding: MetricBinding, record: ScopeRecord) -> float | None:
        if binding.fields == ("__count__",):
            return 1.0
        if binding.fields == ("__category_density__",):
            counts = record.properties.get("category_counts")
            if isinstance(counts, Mapping):
                total = sum(_number(value) or 0.0 for value in counts.values())
                area = _number(record.properties.get("area_km2")) or (_area_km2(record.geometry) if record.geometry else 0.0)
                return total / area if area > 0 else None
            return None
        if binding.fields == ("__neighbor_delta__",):
            density = _number(record.properties.get("density_poi_per_km2"))
            if density is None:
                density = _number(record.properties.get("density"))
            neighbor = _number(record.properties.get("neighbor_mean_density"))
            return density - neighbor if density is not None and neighbor is not None else None
        for field in binding.fields:
            value: Any = record.properties
            for part in field.split("."):
                value = value.get(part) if isinstance(value, Mapping) else None
            numeric = _number(value)
            if numeric is not None:
                if binding.metric_id == "road.network_size" and field == "road_length_km":
                    return numeric * 1000.0
                return numeric
        return None

    def _selected_records(
        self,
        records: Sequence[ScopeRecord],
        selectors: Sequence[SpatialEvidenceSelector],
        source_id: str,
    ) -> list[ScopeRecord]:
        selected = list(records)
        for selector in selectors:
            expected = {str(value) for value in selector.values}
            if selector.dimension == "year":
                selected = [record for record in selected if str(record.properties.get("year") or record.time_scope.get("year") or "") in expected]
            elif selector.dimension == "poi.category" and source_id == _POI:
                expected_categories = {_resolve_poi_category(value) for value in selector.values}
                selected = [
                    record
                    for record in selected
                    if _resolve_poi_category(record.properties.get("category")) in expected_categories
                ]
            elif selector.dimension == "poi.subcategory" and source_id == _POI:
                selected = [record for record in selected if str(record.properties.get("subcategory") or "") in expected]
            elif selector.dimension == "road.class" and source_id == _ROAD_EDGES:
                selected = [record for record in selected if str(record.properties.get("road_class") or "") in expected]
        return selected

    def _load_records(
        self,
        history_id: str,
        available: set[str],
    ) -> tuple[dict[str, list[ScopeRecord]], dict[str, int | None], list[str]]:
        records: dict[str, list[ScopeRecord]] = {}
        years: dict[str, int | None] = {}
        warnings: list[str] = []
        for source_id in (_POI, _H3, _POI_GRID, _POPULATION, _NIGHTLIGHT, _ROAD_NODES, _ROAD_EDGES, _ROAD_CORRIDORS, _ROAD_GRID):
            if source_id not in available:
                continue
            try:
                values, _, selected_year = self._datasets.load_scope_records(
                    history_id=history_id,
                    source_id=source_id,
                    require_geometry_metadata=True,
                )
            except (LookupError, ValueError) as exc:
                warnings.append(f"{source_id}:{exc}")
                continue
            records[source_id] = values
            years[source_id] = selected_year
            warnings.extend(warning for record in values for warning in record.warnings)
        return records, years, sorted(set(warnings))

    @staticmethod
    def _required_sources(query: SpatialEvidenceRequest, available: set[str]) -> set[str]:
        required: set[str] = set()
        for metric_id in query.metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            referenced_source = next(
                (
                    source_id
                    for source_id in binding.source_ids
                    if source_id in available
                    and any(str(record_ref).startswith(source_id + "/") for record_ref in query.record_refs)
                ),
                "",
            )
            if query.analysis in {"neighborhood", "inspect"} and referenced_source:
                required.add(referenced_source)
            else:
                required.update(source_id for source_id in binding.source_ids if source_id in available)
        if query.named_poi_roles:
            required.add(_POI)
        if query.analysis == "inspect":
            referenced_sources = {
                source_id
                for record_ref in query.record_refs
                for source_id in available
                if str(record_ref).startswith(source_id + "/")
            }
            for record_ref in query.record_refs:
                for source_id in available:
                    if str(record_ref).startswith(source_id + "/"):
                        required.add(source_id)
            if query.named_record_queries:
                required.update({_POI, _ROAD_EDGES} & available)
            if referenced_sources & {_H3, _POI_GRID, _POPULATION, _NIGHTLIGHT, _ROAD_GRID}:
                required.update({_POI, _ROAD_EDGES} & available)
        return required & available

    @staticmethod
    def _missing_metric_sources(
        metric_ids: Sequence[str], records: Mapping[str, Sequence[ScopeRecord]]
    ) -> list[str]:
        return [
            metric_id
            for metric_id in metric_ids
            if not any(records.get(source_id) for source_id in METRIC_BINDINGS[metric_id].source_ids)
        ]

    def _prepare_derived_metric_values(
        self,
        query: SpatialEvidenceRequest,
        records: Mapping[str, list[ScopeRecord]],
        scope_geometry: BaseGeometry,
    ) -> None:
        """Materialize derived cell values that require same-scope context."""

        radius_values = self._selector_values(query.selectors, "road.radius")
        if radius_values and {
            "road.nain.selected_radius", "road.nach.selected_radius",
        } & set(query.metric_ids):
            radius = radius_values[0]
            radius_label = radius if radius == "global" or radius.startswith("r") else f"r{radius}"
            for source_id in (_ROAD_EDGES, _ROAD_CORRIDORS):
                for record in records.get(source_id, []):
                    record.properties = {
                        **record.properties,
                        "selected_radius_nain": _number(record.properties.get(f"nain_{radius_label}")),
                        "selected_radius_nach": _number(record.properties.get(f"nach_{radius_label}")),
                    }

        if "poi.category_lq" not in query.metric_ids:
            return
        selected_category = _selected_poi_category(query.selectors)
        if selected_category is None:
            return
        selected_category_key, selected_category_label = selected_category
        cells = [
            record
            for record in records.get(_H3, [])
            if self._has_measure_overlap(record.geometry, scope_geometry)
            and isinstance(record.properties.get("category_counts"), Mapping)
        ]
        cell_totals = {
            cell.record_id: int(_number(cell.properties.get("poi_count")) or sum(
                int(_number(value) or 0)
                for value in cell.properties["category_counts"].values()
            ))
            for cell in cells
        }
        global_total = sum(cell_totals.values())
        global_category_count = sum(
            int(_number(cell.properties["category_counts"].get(selected_category_key)) or 0)
            for cell in cells
        )
        if global_total <= 0 or global_category_count <= 0:
            for cell in cells:
                cell.properties = {**cell.properties, "selected_category_lq": None}
            return
        global_share = global_category_count / global_total
        for cell in cells:
            counts = cell.properties["category_counts"]
            cell_total = cell_totals[cell.record_id]
            category_count = int(_number(counts.get(selected_category_key)) or 0)
            value = (category_count / cell_total) / global_share if cell_total > 0 else None
            cell.properties = {
                **cell.properties,
                "selected_category_lq": round(value, 6) if value is not None else None,
                "selected_category_key": selected_category_key,
                "selected_category_label": selected_category_label,
            }

    def _base_source(self, query: SpatialEvidenceRequest, records: Mapping[str, list[ScopeRecord]]) -> str:
        bindings = [METRIC_BINDINGS[metric_id] for metric_id in query.metric_ids]
        if query.analysis == "neighborhood":
            for source_id, values in records.items():
                if any(self._matches_ref(self._record_ref(record), query.record_refs) for record in values):
                    return source_id
        road_objects = self._selector_values(query.selectors, "road.object")
        if query.analysis == "rank" and road_objects:
            object_source = {
                "segment": _ROAD_EDGES,
                "corridor": _ROAD_CORRIDORS,
                "grid": _ROAD_GRID,
            }.get(road_objects[0], "")
            return object_source if object_source and records.get(object_source) else ""
        if query.analysis == "rank" and bindings and all(binding.metric_id == "road.network_density" for binding in bindings):
            return _ROAD_GRID if records.get(_ROAD_GRID) else ""
        if (
            query.analysis in {"rank", "neighborhood"}
            and bindings
            and all(binding.metric_id.startswith("road.") for binding in bindings)
            and all(_ROAD_EDGES in binding.source_ids for binding in bindings)
            and records.get(_ROAD_EDGES)
        ):
            return _ROAD_EDGES
        if any(binding.h3_native for binding in bindings) and records.get(_H3):
            return _H3
        if bindings:
            common_sources = set(bindings[0].source_ids)
            for binding in bindings[1:]:
                common_sources.intersection_update(binding.source_ids)
            for source_id in bindings[0].source_ids:
                if source_id in common_sources and records.get(source_id):
                    return source_id
        for source_id in (_POPULATION, _NIGHTLIGHT, _POI_GRID, _ROAD_GRID, _H3):
            if records.get(source_id):
                return source_id
        if bindings:
            return next((source for source in bindings[0].source_ids if records.get(source)), "")
        return ""

    @staticmethod
    def _metric_source(binding: MetricBinding, records: Mapping[str, Sequence[ScopeRecord]], query: SpatialEvidenceRequest) -> str:
        dimensions = {selector.dimension for selector in query.selectors}
        road_objects = SpatialEvidenceService._selector_values(query.selectors, "road.object")
        if query.analysis in {"neighborhood", "inspect"}:
            referenced_source = next(
                (
                    source_id
                    for source_id in binding.source_ids
                    if records.get(source_id)
                    and any(str(record_ref).startswith(source_id + "/") for record_ref in query.record_refs)
                ),
                "",
            )
            if referenced_source:
                return referenced_source
        if binding.h3_native and records.get(_H3):
            return _H3
        if binding.metric_id.startswith("poi.") and dimensions & {"poi.category", "poi.subcategory"} and records.get(_POI):
            return _POI
        if (
            binding.metric_id.startswith("road.")
            and query.analysis in {"rank", "neighborhood", "inspect"}
            and road_objects == ("corridor",)
            and records.get(_ROAD_CORRIDORS)
        ):
            return _ROAD_CORRIDORS
        if (
            binding.metric_id.startswith("road.")
            and query.analysis in {"neighborhood", "inspect"}
        ):
            referenced_source = next(
                (
                    source_id
                    for source_id in (_ROAD_EDGES, _ROAD_CORRIDORS, _ROAD_NODES, _ROAD_GRID)
                    if any(str(record_ref).startswith(source_id + "/") for record_ref in query.record_refs)
                    and records.get(source_id)
                    and source_id in binding.source_ids
                ),
                "",
            )
            if referenced_source:
                return referenced_source
        if (
            binding.metric_id.startswith("road.")
            and query.analysis in {"rank", "neighborhood", "inspect"}
            and records.get(_ROAD_EDGES)
            and _ROAD_EDGES in binding.source_ids
        ):
            return _ROAD_EDGES
        if binding.metric_id.startswith("road.") and dimensions & {"road.class", "road.radius"} and records.get(_ROAD_EDGES):
            return _ROAD_EDGES
        return next((source_id for source_id in binding.source_ids if records.get(source_id)), "")

    @staticmethod
    def _group_payload(key: str, rows: Sequence[_SpatialRow], metric_ids: Sequence[str]) -> dict[str, Any]:
        values = {}
        for metric_id in metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            numeric = [
                float(row.values[metric_id]) * row.aggregation_factors.get(metric_id, 1.0)
                for row in rows
                if row.values.get(metric_id) is not None
            ]
            values[metric_id] = SpatialEvidenceService._aggregate_values(binding, numeric)
        return {"key": key, "cell_count": len(rows), "values": values}

    @staticmethod
    def _aggregate_values(binding: MetricBinding, values: Sequence[float]) -> float | None:
        if not values:
            return None
        if binding.aggregate == "sum":
            return round(sum(values), 6)
        if binding.aggregate == "max":
            return round(max(values), 6)
        if binding.aggregate == "p90":
            return round(_quantile(values, 0.9), 6)
        if binding.aggregate == "ratio_positive":
            return round(sum(1 for value in values if value > 0) / len(values), 6)
        return round(sum(values) / len(values), 6)

    @staticmethod
    def _metric_descriptors(metric_ids: Sequence[str]) -> list[dict[str, Any]]:
        return [
            {
                "metric_id": metric_id,
                "label": METRIC_BINDINGS[metric_id].label if metric_id in METRIC_BINDINGS else metric_id,
                "unit": METRIC_BINDINGS[metric_id].unit if metric_id in METRIC_BINDINGS else "catalog_result",
            }
            for metric_id in metric_ids
        ]

    @staticmethod
    def _row_coverage(rows: Sequence[_SpatialRow], metric_ids: Sequence[str]) -> dict[str, Any]:
        valid = {metric_id: sum(row.values.get(metric_id) is not None for row in rows) for metric_id in metric_ids}
        return {
            "complete": all(count == len(rows) for count in valid.values()),
            "spatial_unit_count": len(rows),
            "valid_value_count": valid,
            "missing_values": "excluded_not_zero_filled",
        }

    @staticmethod
    def _row_coverage_limitations(coverage: Mapping[str, Any]) -> list[str]:
        total = int(coverage.get("spatial_unit_count") or 0)
        valid = coverage.get("valid_value_count")
        if total <= 0 or not isinstance(valid, Mapping):
            return []
        return SpatialEvidenceService._metric_coverage_limitations(
            {str(metric_id): total for metric_id in valid},
            {str(metric_id): int(count or 0) for metric_id, count in valid.items()},
        )

    @staticmethod
    def _metric_coverage_limitations(
        totals: Mapping[str, int],
        valid: Mapping[str, int],
    ) -> list[str]:
        limitations = []
        for metric_id, total in totals.items():
            valid_count = int(valid.get(metric_id) or 0)
            if valid_count < total:
                label = METRIC_BINDINGS.get(metric_id).label if metric_id in METRIC_BINDINGS else metric_id
                limitations.append(
                    f"{label}仅有 {valid_count}/{total} 个空间单元包含有效值；缺失值已排除，未按零值填充。"
                )
        return limitations

    @staticmethod
    def _highlight(row: _SpatialRow, metric_ids: Sequence[str], *, reason: str) -> dict[str, Any]:
        payload = {
            "record_ref": row.record_ref,
            "title": row.title,
            "identity": row.identity,
            "centroid_wgs84": [round(row.centroid[0], 6), round(row.centroid[1], 6)],
            "straight_line_distance_m": round(row.distance_m, 1),
            "direction": row.direction,
            "values": {metric_id: _rounded(row.values.get(metric_id)) for metric_id in metric_ids},
            "reason": reason,
        }
        return payload

    @staticmethod
    def _record_identity(record: ScopeRecord) -> dict[str, Any]:
        descriptor = DATASET_FIELD_CATALOG.get(record.source_id, {})
        identity: dict[str, Any] = {
            "dataset_id": descriptor.get("dataset_id", "spatial_record"),
            "display_name": record.title,
        }
        for field_name in descriptor.get("identity_fields", []):
            value: Any = record.properties
            for part in str(field_name).split("."):
                value = value.get(part) if isinstance(value, Mapping) else None
            if value not in (None, "", []):
                identity[str(field_name)] = value
        cleaned = _safe_value(identity)
        return cleaned if isinstance(cleaned, dict) else {"display_name": record.title}

    @staticmethod
    def _record_attributes(record: ScopeRecord) -> dict[str, Any]:
        """Return only catalogued measures for inspect responses."""
        descriptor = DATASET_FIELD_CATALOG.get(record.source_id, {})
        attributes: dict[str, Any] = {}
        for field_name in descriptor.get("measure_fields", []):
            value: Any = record.properties
            for part in str(field_name).split("."):
                value = value.get(part) if isinstance(value, Mapping) else None
            if value not in (None, "", []):
                attributes[str(field_name)] = _compact_value(value)
        cleaned = _safe_value(attributes)
        return cleaned if isinstance(cleaned, dict) else {}

    @staticmethod
    def _scope_summary(project: Mapping[str, Any], geometry: BaseGeometry, center: tuple[float, float]) -> dict[str, Any]:
        params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        return {
            "scope_ref": "current",
            "scope_type": str((project.get("params") or {}).get("scope_type") or "saved_project_scope"),
            "center_wgs84": [round(center[0], 6), round(center[1], 6)],
            "area_km2": round(_area_km2(geometry), 6),
            "travel_mode": str(params.get("mode") or "") or None,
            "time_min": _number(params.get("time_min")),
            "geometry_returned": False,
        }

    @staticmethod
    def _dataset_summary(project: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
        return next(
            (
                summary
                for dataset in project.get("datasets") or []
                if isinstance(dataset, Mapping)
                and str(dataset.get("source_id") or "") == source_id
                and isinstance((summary := dataset.get("summary")), Mapping)
            ),
            {},
        )

    @staticmethod
    def _scope_geometry(project: Mapping[str, Any]) -> tuple[BaseGeometry | None, tuple[float, float] | None]:
        raw_scope: Any = project.get("scope")
        if isinstance(raw_scope, Mapping):
            raw_scope = raw_scope.get("polygon") or raw_scope.get("geometry") or raw_scope
        if isinstance(raw_scope, list):
            coordinates = raw_scope
            if coordinates and all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in coordinates):
                coordinates = [coordinates]
            raw_scope = {"type": "Polygon", "coordinates": coordinates}
        try:
            geometry = shape(raw_scope) if isinstance(raw_scope, Mapping) else None
        except (TypeError, ValueError):
            geometry = None
        if geometry is None or geometry.is_empty:
            return None, None
        params = project.get("params") if isinstance(project.get("params"), Mapping) else {}
        declared = str(params.get("coord_type") or params.get("coordinate_system") or "wgs84").lower()
        if declared == "gcj02":
            geometry = transform(lambda x, y, z=None: gcj02_to_wgs84(float(x), float(y)), geometry)
        raw_center = params.get("center")
        center = None
        if isinstance(raw_center, (list, tuple)) and len(raw_center) >= 2:
            try:
                center = (float(raw_center[0]), float(raw_center[1]))
                if declared == "gcj02":
                    center = gcj02_to_wgs84(*center)
            except (TypeError, ValueError):
                center = None
        if center is None:
            centroid = geometry.centroid
            center = (float(centroid.x), float(centroid.y)) if not centroid.is_empty else None
        return geometry, center

    @staticmethod
    def _record_ref(record: ScopeRecord) -> str:
        return f"{record.source_id}/{record.record_id}"

    @staticmethod
    def _matches_ref(record_ref: str, requested: Sequence[str]) -> bool:
        return record_ref in requested

    def _evidence(
        self,
        project: Mapping[str, Any],
        query: SpatialEvidenceRequest,
        key: str,
        metric_ids: Sequence[str],
        record_refs: Sequence[str],
        content: Any,
    ) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        evidence_id = "spatial:" + _digest({"snapshot_id": snapshot_id, "analysis": query.analysis, "key": key, "metrics": list(metric_ids), "content": content})[:24]
        return {
            "evidence_id": evidence_id,
            "title": "项目空间证据",
            "source_type": "project_spatial_evidence",
            "source_locator": f"spatial_evidence:{snapshot_id}:{query.analysis}:{key}",
            "metric_ids": list(metric_ids),
            "record_refs": list(record_refs)[:20],
            "content": _safe_value(content),
        }

    @staticmethod
    def _provenance(project: Mapping[str, Any], years: Mapping[str, int | None], source_ids: Iterable[str]) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        sources = sorted(source_id for source_id in source_ids if source_id)
        return {
            "snapshot_id": snapshot_id,
            "source_ids": sources,
            "selected_years": {source_id: years.get(source_id) for source_id in sources},
            "result_checksum": "sha256:" + _digest({"snapshot_id": snapshot_id, "sources": sources, "years": dict(years)}),
        }

    def _unavailable(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        limitation: str,
        *,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._response(
            query=query,
            project=project,
            scope=scope or {},
            status="unavailable",
            metrics=self._metric_descriptors(query.metric_ids),
            coverage={"complete": False},
            limitations=[limitation],
            method={"kind": query.analysis, "executed": False},
            provenance=self._provenance(project, {}, set()),
        )

    @staticmethod
    def _response(
        *,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        status: Literal["available", "unavailable", "failed"] = "available",
        metrics: list[dict[str, Any]] | None = None,
        summary: dict[str, Any] | None = None,
        groups: list[dict[str, Any]] | None = None,
        highlights: list[dict[str, Any]] | None = None,
        named_spatial_objects: list[dict[str, Any]] | None = None,
        relationship: dict[str, Any] | None = None,
        coverage: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        limitations: list[str] | None = None,
        method: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        metric_payload = [dict(item) for item in (metrics or [])]
        method_payload = dict(method or {})
        selected_category = _selected_poi_category(query.selectors)
        if "poi.category_lq" in query.metric_ids and selected_category:
            category_key, category_label = selected_category
            for item in metric_payload:
                if item.get("metric_id") == "poi.category_lq":
                    item["selected_category"] = {"key": category_key, "label": category_label}
            method_payload["category_lq"] = {
                "selected_category": {"key": category_key, "label": category_label},
                "formula": "(cell_category_count/cell_poi_count)/(scope_category_count/scope_poi_count)",
                "minimum_cell_poi_count": 1,
                "smoothing_alpha": 0,
                "empty_cell_value": None,
                "absent_selected_category_value": 0,
            }
        response = {
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": snapshot_id,
                "request": query.model_dump(mode="json"),
            })[:24],
            "status": status,
            "analysis": query.analysis,
            "scope": scope,
            "metrics": metric_payload,
            "summary": summary or {},
            "groups": groups or [],
            "highlights": highlights or [],
            "named_spatial_objects": named_spatial_objects or [],
            "relationship": relationship or {},
            "coverage": coverage or {},
            "evidence": evidence or [],
            "limitations": list(dict.fromkeys(str(item) for item in (limitations or []) if str(item).strip())),
            "method": method_payload,
            "provenance": provenance or {},
        }
        return _bounded_model_response(response)


def _safe_value(value: Any, *, key: str = "") -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            normalized_key = str(raw_key).lower()
            if normalized_key in FORBIDDEN_OUTPUT_KEYS:
                continue
            cleaned = _safe_value(item, key=normalized_key)
            if cleaned is not _OMIT:
                result[str(raw_key)] = cleaned
        return result
    if isinstance(value, (list, tuple)):
        limit = 80 if key == "metrics" else MODEL_LIST_ITEM_LIMIT
        cleaned = [_safe_value(item, key=key) for item in list(value)[:limit]]
        return [item for item in cleaned if item is not _OMIT]
    if isinstance(value, str):
        if _looks_like_geometry_string(value) or _looks_like_internal_path_or_connection(value):
            return _OMIT
        return value[:MODEL_STRING_CHAR_LIMIT]
    return value


class _OmitValue:
    pass


_OMIT = _OmitValue()


def _looks_like_geometry_string(value: str) -> bool:
    """Reject serialized GeoJSON/WKT even when it is hidden inside a string."""
    normalized = value.strip().lower()
    if not normalized:
        return False
    has_geometry_key = any(
        marker in normalized
        for marker in ('"geometry"', "'geometry'", '"coordinates"', "'coordinates'", '"features"', "'features'")
    )
    has_geometry_type = any(
        token in normalized
        for token in ("polygon", "multipolygon", "linestring", "multilinestring", "point", "multipoint")
    )
    return (
        normalized.startswith(("polygon(", "multipolygon(", "linestring(", "multilinestring(", "point(", "multipoint("))
        or has_geometry_key and has_geometry_type
        or ('"type"' in normalized or "'type'" in normalized) and has_geometry_type
        or normalized.startswith(("{\"type\":", "{ 'type':"))
    )


def _looks_like_internal_path_or_connection(value: str) -> bool:
    """Reject local paths and connection URLs hidden in free-text fields."""
    normalized = value.strip()
    if not normalized:
        return False
    if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:app|home|tmp|var|Users|mnt)(?:/|$))", normalized):
        return True
    return bool(re.match(r"^(?:postgres(?:ql)?|mysql|mariadb|redis|sqlite)://", normalized, re.IGNORECASE))
def _bounded_model_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Project a spatial result into a small, geometry-free model response."""
    projected = _safe_value(response)
    if not isinstance(projected, dict):
        return {"status": "unavailable", "limitations": ["空间结果投影失败。"]}

    for key, limit in (("groups", 12), ("highlights", 20), ("named_spatial_objects", 20), ("evidence", 20)):
        if isinstance(projected.get(key), list):
            projected[key] = projected[key][:limit]
    if isinstance(projected.get("evidence"), list):
        for item in projected["evidence"]:
            if isinstance(item, dict) and isinstance(item.get("content"), (dict, list)):
                item["content"] = _safe_value(item["content"])

    def serialized_size() -> int:
        return len(json.dumps(projected, ensure_ascii=False, separators=(",", ":"), default=str))

    # Trim the least useful payloads first while preserving the response contract.
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT and isinstance(projected.get("evidence"), list):
        for item in projected["evidence"]:
            if isinstance(item, dict) and "content" in item:
                item["content"] = str(item["content"])[:240]
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT and isinstance(projected.get("highlights"), list):
        projected["highlights"] = projected["highlights"][:10]
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT and isinstance(projected.get("groups"), list):
        projected["groups"] = projected["groups"][:8]
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT:
        original_method = projected.get("method") or {}
        projected["method"] = {
            key: original_method[key]
            for key in (
                "kind", "direction_sectors", "travel_time_bands_min", "travel_mode",
                "travel_time_method", "spatial_unit_assignment", "extensive_metric_allocation",
                "outer_band_boundary", "allocation_assumptions", "neighbor_steps",
                "spatial_aggregation", "boundary_cell_policy", "line_aggregation",
                "period", "current_layer_calls", "timeseries_calls", "internal_metrics_hidden",
                "road_model_executed", "persisted_result_reads", "core_network_rule",
                "missing_values", "combined_score", "category_lq",
                "requested_contour_times_min", "routing_algorithm", "road_source_id",
                "walking_distance_components", "max_walking_time_min",
                "depthmapx_executed", "local_route_graph_built",
                "local_statistics", "spatial_statistics_recomputed",
            )
            if key in original_method
        }
        projected["method"].setdefault("kind", "spatial_evidence")
        projected["provenance"] = {"snapshot_id": str((projected.get("provenance") or {}).get("snapshot_id", ""))}
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT and projected.get("summary"):
        projected["summary"] = _compact_summary_for_model(projected["summary"])
        projected["evidence"] = []
        if isinstance(projected.get("highlights"), list):
            projected["highlights"] = projected["highlights"][:5]
        if isinstance(projected.get("groups"), list):
            projected["groups"] = projected["groups"][:4]
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT and projected.get("summary"):
        projected["summary"] = _flatten_summary_for_model(projected["summary"], max_items=40)
    if serialized_size() > MODEL_RESPONSE_CHAR_LIMIT:
        projected["summary"] = _flatten_summary_for_model(projected.get("summary") or response.get("summary") or {}, max_items=16)
        projected["highlights"] = []
        projected["groups"] = []
        projected["relationship"] = _compact_summary_for_model(projected.get("relationship") or {})
    return projected


def _compact_summary_for_model(value: Any, *, depth: int = 0) -> Any:
    """Keep decision-bearing summary fields while bounding verbose nested payloads."""

    if depth >= 4:
        if isinstance(value, Mapping):
            return {str(key): _compact_summary_for_model(item, depth=depth + 1) for key, item in list(value.items())[:8]}
        if isinstance(value, (list, tuple)):
            return [_compact_summary_for_model(item, depth=depth + 1) for item in list(value)[:4]]
        return str(value)[:160] if isinstance(value, str) else value
    if isinstance(value, Mapping):
        priority = (
            "status", "year", "period", "level", "snapshot", "spatial_pattern", "activity_background",
            "temporal", "series", "change_2023_2025", "change_2024_2026", "spatial_change",
            "summary", "analysis", "result_id", "tool_id", "tool_version",
        )
        keys = [key for key in priority if key in value]
        keys.extend(key for key in value if key not in keys)
        return {
            str(key): _compact_summary_for_model(value[key], depth=depth + 1)
            for key in keys[:24]
        }
    if isinstance(value, (list, tuple)):
        return [_compact_summary_for_model(item, depth=depth + 1) for item in list(value)[:8]]
    if isinstance(value, str):
        return value[:320]
    return value


def _flatten_summary_for_model(value: Any, *, max_items: int) -> dict[str, Any]:
    """Last-resort projection that remains informative instead of erasing summary."""

    flattened: dict[str, Any] = {}

    def visit(item: Any, path: str) -> None:
        if len(flattened) >= max_items:
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, f"{path}.{key}" if path else str(key))
                if len(flattened) >= max_items:
                    break
            return
        if isinstance(item, (list, tuple)):
            for index, child in enumerate(item[:4]):
                visit(child, f"{path}[{index}]")
                if len(flattened) >= max_items:
                    break
            return
        if item is not None:
            flattened[path or "value"] = item[:160] if isinstance(item, str) else item

    visit(value, "")
    return {"compacted": True, "values": flattened}


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    """Bound catalog payloads before they enter the model context."""
    if depth >= 3:
        return str(value)[:1000]
    if isinstance(value, Mapping):
        return {str(key): _compact_value(item, depth=depth + 1) for key, item in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_compact_value(item, depth=depth + 1) for item in list(value)[:20]]
    if isinstance(value, str):
        return value[:4000]
    return value


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (GEOSException, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None else None


def _quantile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("quantile_requires_values")
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def _distance_direction(origin: tuple[float, float], target: tuple[float, float]) -> tuple[float, str]:
    lon0, lat0 = origin
    lon, lat = target
    latitude = math.radians((lat0 + lat) / 2.0)
    dx = (lon - lon0) * 111_320.0 * math.cos(latitude)
    dy = (lat - lat0) * 110_574.0
    distance = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dx, dy)) % 360.0
    direction = DIRECTION_CODES[int((bearing + 22.5) // 45.0) % len(DIRECTION_CODES)]
    return distance, direction


def _format_band_value(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")


def _geometry_distance_m(left: BaseGeometry, right: BaseGeometry) -> float | None:
    if left.is_empty or right.is_empty:
        return None
    if left.intersects(right):
        return 0.0
    try:
        left_point, right_point = nearest_points(left, right)
    except (TypeError, ValueError):
        return None
    distance, _ = _distance_direction(
        (float(left_point.x), float(left_point.y)),
        (float(right_point.x), float(right_point.y)),
    )
    return round(distance, 1)


def _area_km2(geometry: BaseGeometry | None) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    centroid = geometry.centroid
    scale_x = 111.32 * math.cos(math.radians(float(centroid.y)))
    scale_y = 110.574
    return abs(float(geometry.area)) * scale_x * scale_y


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "CATALOG_SCOPE_BINDINGS",
    "EVIDENCE_DIMENSION_BINDINGS",
    "FACT_DOMAIN_CAPABILITIES",
    "EvidenceDimension",
    "FactDomain",
    "METRIC_BINDINGS",
    "SCHEMA_VERSION",
    "SpatialDomainComputationRequest",
    "SpatialEvidenceRequest",
    "SpatialEvidenceSelector",
    "SpatialEvidenceService",
]
