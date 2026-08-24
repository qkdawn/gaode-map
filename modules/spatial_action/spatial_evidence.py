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
from shapely.geometry import Polygon, mapping, shape
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
    EqualWeightFacility,
    EqualWeightSupplyDemandAccessibilityService,
    FocusedPoiAccessibilityService,
    FocusedPoiCandidate,
    FocusedPoiTypeGroup,
    PopulationDemandPoint,
)
from modules.spatial_action.metric_tools import MetricToolService
from modules.spatial_action.nightlight_evidence import (
    build_nightlight_accessibility_profile,
    build_nightlight_change_profile,
    build_nightlight_direction_profile,
    build_nightlight_inspect_profile,
    build_nightlight_neighborhood_profile,
    build_nightlight_rank_profile,
    build_nightlight_scope_profile,
)
from modules.spatial_action.poi_evidence import (
    build_poi_category_colocation_profile,
    build_poi_direction_profile,
    build_poi_inspect_profile,
    build_poi_neighborhood_profile,
    build_poi_scope_profile,
)
from modules.spatial_action.road_network_routing import LocalRoadNetworkRouter, RoadNetworkRoutingUnavailable
from modules.spatial_action.source_index import SourceIndex
from modules.spatial_projects.service import SpatialProjectService
from modules.timeseries.nightlight_series import get_nightlight_timeseries


# v18 changes named POI candidate selection to preserve category coverage and
# prefer role-specific facilities within each category.
# Keep earlier artifacts immutable and give the new semantics a distinct
# deterministic identity instead of reusing results produced by v11-v17.
SCHEMA_VERSION = "spatial_evidence/v18"
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
POPULATION_MEASURES = ("count", "density", "share")
SELECTOR_DIMENSIONS = {
    "poi.category", "poi.subcategory", "population.sex",
    "population.age_band", "population.measure", "road.class", "road.radius", "road.object", "year",
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
    "limitations",
    "interpretation",
    "interpretation_basis",
    "semantics",
    "comparison_semantics",
    "weight_semantics",
    "facility_weight_semantics",
    "count_semantics",
    "capacity_semantics",
    "time_series_semantics",
    "no_road_metric_semantics",
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


def supported_poi_category_labels() -> tuple[str, ...]:
    """Return the stable POI category labels accepted by spatial selectors."""

    return tuple(sorted({label for _group_id, label in _POI_CATEGORY_CATALOG.values()}))


def _resolve_poi_category(value: Any) -> tuple[str, str] | None:
    return _POI_CATEGORY_CATALOG.get(str(value or "").strip().casefold())


def _selected_poi_category(selectors: Sequence[Any]) -> tuple[str, str] | None:
    categories = _selected_poi_categories(selectors)
    return categories[0] if len(categories) == 1 else None


def _selected_poi_categories(selectors: Sequence[Any]) -> tuple[tuple[str, str], ...]:
    values = [
        value
        for selector in selectors
        if getattr(selector, "dimension", None) == "poi.category"
        for value in getattr(selector, "values", ())
    ]
    return tuple(
        category
        for value in values
        if (category := _resolve_poi_category(value)) is not None
    )

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
        "population.age_band", "population.measure", "road.class", "road.radius", "road.object", "year",
    ]
    values: list[str | int] = Field(
        min_length=1,
        max_length=20,
        description=(
            "筛选值。poi.category 通常使用一个主业态；POI 类别关系问题使用两个主业态。支持公司、旅游、交通、商务住宅、自然、购物、"
            "餐饮、体育、医疗、住宿、政府机构、科教文化及其高德主类名称。"
        ),
    )

    @model_validator(mode="after")
    def validate_domain_values(self) -> "SpatialEvidenceSelector":
        values = [str(value).strip().lower() for value in self.values]
        if self.dimension == "population.sex":
            if len(values) != 1:
                raise ValueError("population_sex_requires_exactly_1_value")
            if not set(values) <= set(POPULATION_SEXES):
                raise ValueError("population_sex_must_be_total_male_or_female")
        if self.dimension == "population.age_band":
            if len(values) != 1:
                raise ValueError("population_age_band_requires_exactly_1_value")
            if not set(values) <= {"all", *POPULATION_AGE_BANDS}:
                raise ValueError("population_age_band_unsupported")
        if self.dimension == "population.measure":
            if len(values) != 1:
                raise ValueError("population_measure_requires_exactly_1_value")
            if values[0] not in POPULATION_MEASURES:
                raise ValueError("population_measure_unsupported")
        if self.dimension == "poi.category":
            if not 1 <= len(self.values) <= 2:
                raise ValueError("poi_category_requires_one_or_two_values")
            categories = [_resolve_poi_category(value) for value in self.values]
            if any(category is None for category in categories):
                raise ValueError("poi_category_unsupported")
            if len(set(categories)) != len(categories):
                raise ValueError("poi_categories_must_be_distinct")
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


def _validate_population_selector_cardinality(selectors: Sequence[SpatialEvidenceSelector]) -> None:
    for dimension, error in (
        ("population.sex", "population_sex_requires_exactly_1_value"),
        ("population.age_band", "population_age_band_requires_exactly_1_value"),
    ):
        value_count = sum(
            len(selector.values)
            for selector in selectors
            if selector.dimension == dimension
        )
        if value_count > 1:
            raise ValueError(error)


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
    "population.structure",
    "population.change",
    "nightlight.intensity",
    "nightlight.change",
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
    named_poi_roles: list[NamedPoiRole] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_mode(self) -> "SpatialDomainComputationRequest":
        _validate_population_selector_cardinality(self.selectors)
        poi_categories = _selected_poi_categories(self.selectors)
        poi_category_relationship = (
            self.analysis == "relationship"
            and self.fact_domains == ["poi"]
            and len(poi_categories) == 2
        )
        if len(set(self.fact_domains)) != len(self.fact_domains):
            raise ValueError("fact_domains_must_be_unique")
        if len(set(self.evidence_dimensions)) != len(self.evidence_dimensions):
            raise ValueError("evidence_dimensions_must_be_unique")
        if self.analysis in {"accessibility", "direction"} and not self.fact_domains:
            raise ValueError(f"{self.analysis}_requires_fact_domains")
        if self.analysis == "rank" and len(self.fact_domains) != 1:
            raise ValueError("rank_requires_exactly_1_fact_domain")
        if (
            self.analysis == "relationship"
            and not poi_category_relationship
            and not 2 <= len(self.fact_domains) <= 4
        ):
            raise ValueError("relationship_requires_2_to_4_fact_domains")
        if len(poi_categories) == 2 and not poi_category_relationship:
            raise ValueError("two_poi_categories_only_supported_for_poi_relationship")
        if poi_category_relationship and self.evidence_dimensions not in ([], ["poi.supply"]):
            raise ValueError("poi_category_relationship_requires_poi_supply_dimension")
        allow_default_population_rank = (
            self.analysis == "rank"
            and self.fact_domains == ["population"]
            and not self.evidence_dimensions
        )
        if (
            self.analysis in {"rank", "relationship"}
            and len(self.evidence_dimensions) != len(self.fact_domains)
            and not allow_default_population_rank
            and not poi_category_relationship
        ):
            raise ValueError(f"{self.analysis}_requires_one_dimension_per_fact_domain")
        if self.analysis == "neighborhood" and (not self.fact_domains or not self.record_refs):
            raise ValueError("neighborhood_requires_fact_domains_and_record_refs")
        if self.analysis == "inspect" and not self.record_refs:
            raise ValueError("inspect_requires_record_refs")
        if self.analysis not in {"neighborhood", "inspect"} and self.record_refs:
            raise ValueError("record_refs_only_supported_for_neighborhood_or_inspect")
        if self.named_poi_roles and "poi" not in self.fact_domains:
            raise ValueError("named_poi_roles_require_poi_domain")
        if "comparable_supply" in self.named_poi_roles and not poi_categories:
            raise ValueError("comparable_supply_requires_poi_category_selector")
        if self.analysis != "accessibility" and self.travel_time_bands_min:
            raise ValueError("travel_time_bands_min_only_supported_for_accessibility")
        population_measures = {
            str(value).strip().lower()
            for selector in self.selectors
            if selector.dimension == "population.measure"
            for value in selector.values
        }
        if population_measures and (self.analysis != "rank" or self.fact_domains != ["population"]):
            raise ValueError("population_measure_only_supported_for_population_rank")
        if "share" in population_measures and not any(
            selector.dimension in {"population.sex", "population.age_band"}
            and any(str(value).strip().lower() not in {"all", "total"} for value in selector.values)
            for selector in self.selectors
        ):
            raise ValueError("population_share_requires_selected_subgroup")
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
        if self.analysis in {"rank", "relationship"} and self.evidence_dimensions:
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
        _validate_population_selector_cardinality(self.selectors)
        if len(_selected_poi_categories(self.selectors)) > 1:
            raise ValueError("two_poi_categories_require_domain_relationship_request")
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
        population_measures = {
            str(value).strip().lower()
            for selector in self.selectors
            if selector.dimension == "population.measure"
            for value in selector.values
        }
        if population_measures and self.analysis != "rank":
            raise ValueError("population_measure_only_supported_for_population_rank")
        if population_measures and not all(metric_id.startswith("population.") for metric_id in self.metric_ids):
            raise ValueError("population_measure_requires_population_metric")
        if "share" in population_measures and not any(
            selector.dimension in {"population.sex", "population.age_band"}
            and any(str(value).strip().lower() not in {"all", "total"} for value in selector.values)
            for selector in self.selectors
        ):
            raise ValueError("population_share_requires_selected_subgroup")
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
        _binding("population.profile", "人口规模、性别与年龄结构", "profile", [_POPULATION], ["population_total"], "sum"),
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
        CatalogScopeBinding("nightlight.brightness_context", (_NIGHTLIGHT,)),
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
        EvidenceDimensionBinding("population.scale", "population", "人口规模", "等时圈内人口规模或所选年龄性别人群", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding("population.structure", "population", "人口结构", "等时圈内年龄与性别结构", ("scope", "accessibility", "direction", "neighborhood", "rank", "inspect")),
        EvidenceDimensionBinding("population.change", "population", "人口变化", "等时圈内人口规模与结构的年份变化", ("scope",)),
        EvidenceDimensionBinding("nightlight.intensity", "nightlight", "夜间亮度", "保存等时圈内的亮度构成及空间差异", _ALL_SPATIAL_ANALYSES),
        EvidenceDimensionBinding(
            "nightlight.change", "nightlight", "夜光变化", "等时圈内年度亮度增减、中心迁移和局部变化",
            ("scope", "direction", "neighborhood", "rank", "inspect"),
        ),
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
            ("population.scale", "population.structure", "population.change"),
        ),
        FactDomainCapability(
            "nightlight",
            "等时圈内夜间亮度",
            "保存等时圈内的亮度构成、可达分带、方向、邻域和跨域错位，不替代真实活动或消费",
            (_NIGHTLIGHT,),
            _ALL_SPATIAL_ANALYSES,
            ("nightlight.intensity", "nightlight.change"),
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
        "rank": ("poi.supply",),
        "relationship": ("poi.supply",),
    },
    "population": {
        "scope": ("population.scale", "population.structure"),
        "accessibility": ("population.scale", "population.structure"),
        "direction": ("population.scale", "population.structure"),
        "neighborhood": ("population.scale", "population.structure"),
        "rank": ("population.scale",),
        "relationship": ("population.scale",),
        "inspect": ("population.scale", "population.structure"),
    },
    "nightlight": {
        "scope": ("nightlight.intensity",),
        "accessibility": ("nightlight.intensity",),
        "direction": ("nightlight.intensity",),
        "neighborhood": ("nightlight.intensity",),
        "inspect": ("nightlight.intensity",),
        "rank": ("nightlight.intensity",),
        "relationship": ("nightlight.intensity",),
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
        "rank": ("road.to_movement",),
        "relationship": ("road.to_movement",),
    },
}

ROAD_SCOPE_METRIC_IDS: dict[EvidenceDimension, tuple[str, ...]] = {
    "road.to_movement": ("road.nain",),
    "road.through_movement": ("road.nach",),
    "road.connectivity": ("road.connectivity",),
    "road.network_density": ("road.network_size", "road.network_density"),
    "road.orientation": ("road.orientation",),
    "road.quality": ("road.quality",),
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
        nightlight_layer: Callable[..., Mapping[str, Any]] | None = None,
        nightlight_timeseries: Callable[[list, str, str, str], Mapping[str, Any]] | None = None,
    ) -> None:
        self._projects = projects or SpatialProjectService()
        self._datasets = self._projects.datasets
        self._metric_catalog = metric_catalog
        self._isochrone_contours = isochrone_contours or fetch_valhalla_isochrone_contours
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
        project: Mapping[str, Any] | None = None,
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
        project = dict(project) if isinstance(project, Mapping) else self._projects.read_history_project(normalized_history_id)
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
                named_poi_roles=domain_query.named_poi_roles,
            )
            result = self.analyze(history_id=normalized_history_id, request=request_payload, project=project)
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
        equal_weight_balance_requested = (
            domain_query.analysis == "accessibility"
            and {"poi", "population"} <= set(domain_query.fact_domains)
            and _selected_poi_category(domain_query.selectors) is not None
            and "poi.supply" in selected_dimensions["poi"]
            and "population.scale" in selected_dimensions["population"]
        )
        if equal_weight_balance_requested:
            computations.append(self._equal_weight_supply_demand_profile(
                history_id=normalized_history_id,
                project=project,
                available=available,
                request=domain_query,
            ))
            used_metric_ids.append("poi.population_equal_weight_accessibility")
        nightlight_semantic_operation = (
            len(domain_query.fact_domains) == 1
            and domain_query.fact_domains[0] == "nightlight"
            and domain_query.analysis in {"accessibility", "direction", "neighborhood", "rank", "inspect"}
        )
        poi_category_relationship = (
            domain_query.analysis == "relationship"
            and domain_query.fact_domains == ["poi"]
            and len(_selected_poi_categories(domain_query.selectors)) == 2
        )
        if poi_category_relationship:
            computations.append(self._poi_category_relationship_profile(
                history_id=normalized_history_id,
                project=project,
                available=available,
                request=domain_query,
            ))
            used_metric_ids.append("poi.category_colocation_quotient")
        elif nightlight_semantic_operation:
            for dimension in selected_dimensions["nightlight"]:
                computations.append(self._nightlight_operation_profile(
                    normalized_history_id,
                    project,
                    available,
                    domain_query,
                    (dimension,),
                ))
                used_metric_ids.append(
                    "nightlight.change_profile"
                    if dimension == "nightlight.change"
                    else "nightlight.semantic_profile"
                )
        elif domain_query.analysis == "relationship":
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
                if domain == "poi":
                    poi_dimensions = selected_dimensions[domain]
                    profile_dimensions = tuple(
                        dimension
                        for dimension in poi_dimensions
                        if dimension in {"poi.supply", "poi.mix"}
                    )
                    if profile_dimensions:
                        computations.append(self._poi_scope_profile(
                            project,
                            normalized_history_id,
                            available,
                            profile_dimensions,
                            domain_query.selectors,
                        ))
                        if "poi.supply" in profile_dimensions:
                            used_metric_ids.extend(["poi.count", "poi.category_count", "poi.grid_density"])
                        if "poi.mix" in profile_dimensions:
                            used_metric_ids.append("poi.local_entropy")
                    if "poi.category_specialization" in poi_dimensions:
                        execute(
                            [domain],
                            ["poi.category_specialization"],
                            self._dimension_metric_ids(
                                "poi.category_specialization",
                                "scope",
                                domain_query.selectors,
                            ),
                        )
                    temporal_profile = self._poi_temporal_profile(normalized_history_id, project)
                    if temporal_profile is not None:
                        computations.append(temporal_profile)
                        used_metric_ids.append("poi.multi_year_count")
                    continue
                if domain == "nightlight":
                    nightlight_dimensions = selected_dimensions[domain]
                    if "nightlight.intensity" in nightlight_dimensions:
                        nightlight_result = self._nightlight_scope_profile(
                            project,
                            normalized_history_id,
                            available,
                        )
                        nightlight_result["evidence_dimensions"] = ["nightlight.intensity"]
                        computations.append(_bounded_model_response(nightlight_result))
                        used_metric_ids.extend([
                            "nightlight.total_radiance", "nightlight.mean_radiance", "nightlight.max_radiance",
                            "nightlight.p90", "nightlight.lit_pixel_ratio", "nightlight.spatial_profile",
                            "nightlight.sector_profile",
                        ])
                    if "nightlight.change" in nightlight_dimensions:
                        computations.append(self._nightlight_operation_profile(
                            normalized_history_id,
                            project,
                            available,
                            domain_query,
                            ("nightlight.change",),
                        ))
                        used_metric_ids.append("nightlight.change_profile")
                    continue
                if domain == "road":
                    road_dimensions = selected_dimensions[domain]
                    computations.append(self._road_scope_profile(
                        project,
                        normalized_history_id,
                        available,
                        road_dimensions,
                    ))
                    used_metric_ids.extend(
                        metric_id
                        for dimension in road_dimensions
                        for metric_id in ROAD_SCOPE_METRIC_IDS[dimension]
                    )
                    continue
                if domain == "population":
                    population_dimensions = selected_dimensions[domain]
                    current_dimensions = tuple(
                        dimension for dimension in population_dimensions if dimension != "population.change"
                    )
                    if current_dimensions:
                        metrics = (
                            ("population.profile",)
                            if "population.structure" in current_dimensions
                            else self._dimension_metric_ids("population.scale", "scope", domain_query.selectors)
                        )
                        execute([domain], current_dimensions, metrics)
                    if "population.change" in population_dimensions:
                        computations.append(self._population_temporal_profile(normalized_history_id, project))
                        used_metric_ids.append("population.temporal_profile")
                    continue
                for dimension in selected_dimensions[domain]:
                    metrics = self._dimension_metric_ids(dimension, "scope", domain_query.selectors)
                    if metrics:
                        execute([domain], [dimension], metrics)
        elif domain_query.analysis == "inspect" and not domain_query.fact_domains:
            execute([], [], [])
        else:
            for domain in domain_query.fact_domains:
                dimensions = selected_dimensions[domain]
                if (
                    domain == "poi"
                    and _POI in available
                    and domain_query.analysis in {"direction", "inspect"}
                ):
                    computations.append(self._poi_operation_profile(
                        history_id=normalized_history_id,
                        project=project,
                        available=available,
                        request=domain_query,
                        dimensions=dimensions,
                    ))
                    used_metric_ids.append(f"poi.{domain_query.analysis}_profile")
                    continue
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

        selector_payload = [selector.model_dump(mode="json") for selector in domain_query.selectors]
        for item in computations:
            item.setdefault("selectors", selector_payload)
            if str(item.get("status") or "") in {"unavailable", "failed"} and not item.get("unavailable_reason"):
                reasons = item.get("limitations") if isinstance(item.get("limitations"), list) else []
                first_reason = next((str(reason).strip() for reason in reasons if str(reason).strip()), "")
                if first_reason:
                    item["unavailable_reason"] = first_reason
        statuses = [str(item.get("status") or "unavailable") for item in computations]
        unavailable_reasons = list(dict.fromkeys(
            str(item.get("unavailable_reason") or "").strip()
            for item in computations
            if str(item.get("unavailable_reason") or "").strip()
        ))
        status = "available" if statuses and all(value == "available" for value in statuses) else (
            "partial" if any(value == "available" for value in statuses) else "unavailable"
        )
        result_id = spatial_domain_result_id(project, domain_query)
        response = {
            "schema_version": SCHEMA_VERSION,
            "result_id": result_id,
            "status": status,
            "analysis": domain_query.analysis,
            "selectors": selector_payload,
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
            "unavailable_reasons": unavailable_reasons,
            "limitations": [
                limitation
                for item in computations
                for limitation in item.get("limitations", [])
                if str(limitation).strip()
            ],
            "method": {"kind": "domain_owned_spatial_evidence", "internal_metrics_hidden": True},
            "provenance": self._provenance(project, {}, available),
        }
        if domain_query.named_poi_roles and _POI in available:
            records, _, _ = self._load_records(normalized_history_id, {_POI})
            _scope_geometry, center = self._scope_geometry(project)
            if center is not None:
                response["named_poi_candidates"] = self._named_poi_candidates(
                    domain_query,
                    records,
                    center,
                )
        return _bounded_model_response(response)

    def _poi_category_relationship_profile(
        self,
        *,
        history_id: str,
        project: Mapping[str, Any],
        available: set[str],
        request: SpatialDomainComputationRequest,
    ) -> dict[str, Any]:
        categories = _selected_poi_categories(request.selectors)
        scope_geometry, center = self._scope_geometry(project)
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        base = {
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({
                "snapshot_id": snapshot_id,
                "kind": "poi_category_colocation",
                "categories": categories,
            })[:24],
            "analysis": "relationship",
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply"],
        }
        if scope_geometry is None or center is None or _POI not in available:
            return {
                **base,
                "status": "unavailable",
                "summary": {},
                "relationship": {},
                "coverage": {"complete": False},
                "limitations": ["当前项目没有可用于等时圈内 POI 类别关系分析的保存范围或 POI 快照。"],
                "method": {"kind": "poi_category_colocation_quotient", "executed": False},
                "provenance": {"snapshot_id": snapshot_id},
            }
        records, years, warnings = self._load_records(history_id, {_POI})
        profile = build_poi_category_colocation_profile(
            records.get(_POI, []),
            scope_geometry,
            categories,
            named_pair_limit=request.top_k,
        )
        category_pair = profile["category_pair"]
        has_both_categories = all(int(item.get("poi_count") or 0) > 0 for item in category_pair)
        has_quotients = all(item.get("clq") is not None for item in profile["directed_colocation"])
        status = "available" if has_both_categories and has_quotients else "unavailable"
        limitations = [
            *warnings,
            "CLQ 仅描述等时圈内两类 POI 的最近邻共位倾向，不表示因果、客流或统计显著性。",
            "CLQ 可能非对称，因此分别返回两个方向；最近邻等距时按目标类别占比分摊。",
        ]
        if not has_both_categories:
            limitations.append("所选两个 POI 类别必须在当前保存等时圈内都至少存在一个点。")
        return _bounded_model_response({
            **base,
            "status": status,
            "summary": {
                "category_pair": category_pair,
                "categorized_poi_count": profile["categorized_poi_count"],
                "uncategorized_poi_count": profile["uncategorized_poi_count"],
            },
            "groups": profile["directed_colocation"],
            "relationship": {
                "kind": "directed_category_colocation",
                "directed_colocation": profile["directed_colocation"],
            },
            "named_spatial_objects": profile["named_nearest_pairs"],
            "coverage": {
                "complete": status == "available" and profile["uncategorized_poi_count"] == 0,
                "categorized_poi_count": profile["categorized_poi_count"],
                "uncategorized_poi_count": profile["uncategorized_poi_count"],
                "selected_category_counts": {
                    item["key"]: item["poi_count"]
                    for item in category_pair
                },
            },
            "limitations": limitations,
            "method": {
                "kind": "poi_category_colocation_quotient",
                "spatial_universe": "saved_isochrone",
                "neighbor_rule": "nearest_other_poi_with_fractional_tie_handling",
                "formula": "P(nearest_neighbor_is_B_given_source_is_A)/(N_B/(N-1))",
                "directional": True,
                "significance_test": False,
                "internal_method_selected_by": "poi_domain_executor",
            },
            "provenance": self._provenance(project, years, {_POI}),
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
                )
            if analysis == "accessibility":
                return ("poi.count",)
            return ("poi.count", "poi.category_count", "poi.grid_density") if analysis == "scope" else ("poi.grid_density",)
        if dimension == "poi.mix":
            if analysis in {"neighborhood", "inspect"}:
                return ("poi.local_entropy", "poi.neighbor_mean_entropy")
            return ("poi.local_entropy",)
        if dimension == "poi.category_specialization":
            if _selected_poi_category(selectors) is None:
                raise ValueError("poi_category_specialization_requires_poi_category")
            return ("poi.category_lq",)
        if dimension == "population.structure":
            return ("population.profile",)
        if dimension == "population.change":
            return ()
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
        if dimension == "nightlight.change":
            return ()
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
                    "reachable_poi_count": 0,
                    "cumulative_reachable_count": [],
                    **dict(details or {}),
                },
                "groups": [],
                "named_spatial_objects": [],
                "coverage": {"complete": False, "reachable_poi_count": 0},
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
        poi_records = [
            record
            for record in records.get(_POI, [])
            if record.geometry is not None
            and not record.geometry.is_empty
            and scope_geometry.covers(record.geometry)
        ]
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
        reporting_minutes = tuple(
            float(end)
            for _, end in (request.travel_time_bands_min or DEFAULT_TRAVEL_TIME_BANDS_MIN)
        )
        result = FocusedPoiAccessibilityService(
            router,
            max_candidate_distance_m=max_duration_s * DEFAULT_WALKING_SPEED_M_PER_S,
            max_walking_duration_s=max_duration_s,
            max_results_per_group=request.top_k,
            reporting_minutes=reporting_minutes,
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
        reachable_count = group.reachable_poi_count if group is not None else 0
        cumulative_counts = [
            {"minutes": minutes, "count": count}
            for minutes, count in (group.reachable_count_by_minutes if group is not None else ())
        ]
        omission_reason = group.omission_reason if group is not None else result.error_reason
        if not named_objects:
            outside_time_limit_count = group.outside_time_limit_count if group is not None else 0
            return unavailable(
                (
                    "所选业态没有设施能在请求时间内沿已持久化路网到达。"
                    if omission_reason == "no_reachable_poi_within_time"
                    else "所选业态没有形成沿已持久化路网的可达路径；未使用直线距离或模拟路径替代。"
                ),
                details={
                    "route_status": "unavailable",
                    "candidates_considered": candidates_considered,
                    "route_failures": route_failures,
                    "outside_time_limit_count": outside_time_limit_count,
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
                "reachable_poi_count": reachable_count,
                "cumulative_reachable_count": cumulative_counts,
                "named_facility_count": len(named_objects),
                "candidates_considered": candidates_considered,
                "route_failures": route_failures,
                "outside_time_limit_count": group.outside_time_limit_count if group is not None else 0,
                "max_walking_time_min": max_minutes,
                "route_status": "available",
                "facility_weight_semantics": "one_equal_weight_per_facility",
            },
            "groups": [{
                "category": {"key": category_key, "label": category_label},
                "status": "available",
                "matched_typecodes": list(group.matched_type_codes) if group is not None else [],
                "reachable_poi_count": reachable_count,
                "cumulative_reachable_count": cumulative_counts,
                "named_facility_count": len(named_objects),
            }],
            "named_spatial_objects": named_objects,
            "coverage": {
                "complete": route_failures == 0,
                "reachable_poi_count": reachable_count,
                "named_facility_count": len(named_objects),
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
                "spatial_universe": "saved_isochrone",
                "count_semantics": "all_route_verified_facilities_not_named_sample_count",
            },
            "provenance": self._provenance(project, years, set(records)),
            "fact_domains": ["poi"],
            "evidence_dimensions": ["poi.supply"],
            "year": years.get(_POI),
        }

    def _equal_weight_supply_demand_profile(
        self,
        *,
        history_id: str,
        project: Mapping[str, Any],
        available: set[str],
        request: SpatialDomainComputationRequest,
    ) -> dict[str, Any]:
        """Compare equal-weight facilities with reachable population demand."""

        selected_category = _selected_poi_category(request.selectors)
        if selected_category is None:
            raise ValueError("equal_weight_accessibility_requires_one_poi_category")
        category_key, category_label = selected_category
        required_sources = {_POI, _POPULATION, _ROAD_EDGES}
        scope_geometry, center = self._scope_geometry(project)
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")

        def unavailable(reason: str, *, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
            return {
                "schema_version": SCHEMA_VERSION,
                "result_id": "spatial:" + _digest({
                    "snapshot_id": snapshot_id,
                    "kind": "equal_weight_supply_demand_accessibility",
                    "category": selected_category,
                })[:24],
                "status": "unavailable",
                "analysis": "accessibility",
                "fact_domains": ["poi", "population"],
                "evidence_dimensions": ["poi.supply", "population.scale"],
                "summary": {
                    "selected_category": {"key": category_key, "label": category_label},
                    **dict(details or {}),
                },
                "groups": [],
                "coverage": {"complete": False, **dict(details or {})},
                "limitations": [reason],
                "method": {
                    "kind": "equal_weight_supply_demand_accessibility",
                    "executed": False,
                    "facility_weight_semantics": "one_equal_weight_per_facility",
                    "spatial_universe": "saved_isochrone",
                },
                "provenance": {"snapshot_id": snapshot_id},
            }

        missing_sources = sorted(required_sources - available)
        if missing_sources:
            return unavailable("等权供需可达分析缺少已持久化数据源：" + "、".join(missing_sources) + "。")
        if scope_geometry is None or center is None:
            return unavailable("当前项目没有可用于等权供需可达分析的保存等时圈。")

        records, years, warnings = self._load_records(history_id, required_sources)
        selected_facility_records = [
            record
            for record in self._selected_records(records.get(_POI, []), request.selectors, _POI)
            if record.geometry is not None
            and not record.geometry.is_empty
            and scope_geometry.covers(record.geometry)
        ]
        if not selected_facility_records:
            return unavailable("所选 POI 类别在当前保存等时圈内没有设施。")
        facilities = [
            EqualWeightFacility(
                facility_id=self._record_ref(record),
                name=str(record.properties.get("name") or record.title or record.record_id),
                location=(float(record.geometry.centroid.x), float(record.geometry.centroid.y)),
            )
            for record in selected_facility_records
        ]

        demand_points = []
        for record in records.get(_POPULATION, []):
            if record.geometry is None or record.geometry.is_empty:
                continue
            clipped = record.geometry.intersection(scope_geometry)
            if clipped.is_empty or not self._has_measure_overlap(record.geometry, scope_geometry):
                continue
            population = self._population_target_value([record], clipped, "population.total")
            if population is None or population <= 0:
                continue
            point = clipped.centroid
            demand_points.append(PopulationDemandPoint(
                demand_id=self._record_ref(record),
                location=(float(point.x), float(point.y)),
                population=float(population),
            ))
        if not demand_points:
            return unavailable("当前保存等时圈内没有可用于等权供需分析的正值人口需求格网。")

        road_records = records.get(_ROAD_EDGES, [])
        try:
            router = LocalRoadNetworkRouter(
                record.geometry
                for record in road_records
                if record.geometry is not None and not record.geometry.is_empty
            )
        except RoadNetworkRoutingUnavailable as exc:
            return unavailable(f"已持久化路网无法建立等权供需可达路径网络：{exc}。")
        reporting_minutes = tuple(
            float(end)
            for _, end in (request.travel_time_bands_min or DEFAULT_TRAVEL_TIME_BANDS_MIN)
        )
        try:
            profile = EqualWeightSupplyDemandAccessibilityService(router).analyze(
                facilities=facilities,
                demand_points=demand_points,
                reporting_minutes=reporting_minutes,
                demand_result_limit=request.top_k,
            )
        except ValueError as exc:
            return unavailable(str(exc))
        if profile["within_max_catchment_pair_count"] <= 0:
            return unavailable(
                "设施与人口格网之间没有能在请求最大时间内由当前保存路网验证的组合，未使用直线距离替代。",
                details={
                    "facility_count": len(facilities),
                    "population_unit_count": len(demand_points),
                    "route_pair_count": profile["route_pair_count"],
                },
            )
        complete = profile["failed_facility_origins"] == 0
        limitations = [
            *warnings,
            "所有设施按一个等权单位计算；结果用于比较相对供需可达差异。",
            "人口为 WorldPop 格网估计，并按与保存等时圈的面积交叠比例分配，不是逐户实测。",
        ]
        if not complete:
            limitations.append("部分设施起点无法接入保存路网；对应组合按不可达处理，未用直线距离补齐。")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({
                "snapshot_id": snapshot_id,
                "kind": "equal_weight_supply_demand_accessibility",
                "category": selected_category,
                "bands": reporting_minutes,
            })[:24],
            "status": "available",
            "analysis": "accessibility",
            "fact_domains": ["poi", "population"],
            "evidence_dimensions": ["poi.supply", "population.scale"],
            "summary": {
                "selected_category": {"key": category_key, "label": category_label},
                "facility_count": profile["facility_count"],
                "population_unit_count": profile["population_unit_count"],
                "total_population": profile["total_population"],
                "equal_weight_facility_count": profile["equal_weight_facility_count"],
                "supply_basis": "equal_weight_facility_proxy",
                "facility_weight_semantics": "one_equal_weight_per_facility",
                "bands": profile["bands"],
            },
            "groups": profile["bands"],
            "named_spatial_objects": [
                {**item, "object_type": "facility"}
                for item in profile["facilities"][: request.top_k]
            ],
            "highlights": profile["demand_units"],
            "coverage": {
                "complete": complete,
                "route_pair_count": profile["route_pair_count"],
                "within_max_catchment_pair_count": profile["within_max_catchment_pair_count"],
                "failed_facility_origins": profile["failed_facility_origins"],
            },
            "limitations": limitations,
            "method": {
                "kind": "equal_weight_supply_demand_accessibility",
                "spatial_universe": "saved_isochrone",
                "routing_algorithm": "saved_local_road_network_shortest_path",
                "walking_speed_km_h": 4.5,
                "step_1": "one_equal_facility_weight/sum(reachable_population)",
                "step_2": "sum(reachable_facility_supply_demand_ratios)",
                "catchments": "cumulative_requested_time_band_endpoints",
                "output_unit": "equal_weight_facilities_per_1000_residents",
                "facility_weight_semantics": "one_equal_weight_per_facility",
                "internal_method_selected_by": "poi_domain_executor",
            },
            "provenance": self._provenance(project, years, required_sources),
            "year": {
                "poi": years.get(_POI),
                "population": years.get(_POPULATION),
            },
        })

    def _poi_scope_profile(
        self,
        project: Mapping[str, Any],
        history_id: str,
        available: set[str],
        dimensions: Sequence[EvidenceDimension],
        selectors: Sequence[SpatialEvidenceSelector],
    ) -> dict[str, Any]:
        scope_geometry, _ = self._scope_geometry(project)
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        if scope_geometry is None or scope_geometry.is_empty or _POI not in available:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "analysis": "scope",
                "summary": {},
                "coverage": {"complete": False},
                "limitations": ["当前项目没有可用于等时圈内 POI 分析的保存范围或 POI 快照。"],
                "method": {"kind": "poi_isochrone_scope_profile", "executed": False},
                "provenance": {"snapshot_id": snapshot_id},
                "fact_domains": ["poi"],
                "evidence_dimensions": list(dimensions),
            }
        sources = {_POI}
        if "poi.mix" in dimensions and _H3 in available:
            sources.add(_H3)
        records, years, warnings = self._load_records(history_id, sources)
        selected_pois = self._selected_records(records.get(_POI, []), selectors, _POI)
        profile = build_poi_scope_profile(
            selected_pois,
            scope_geometry,
            h3_records=records.get(_H3, []),
        )
        summary: dict[str, Any] = {}
        if "poi.supply" in dimensions:
            summary["supply"] = {
                key: profile[key]
                for key in (
                    "poi_count", "area_km2", "density_poi_per_km2", "category_count",
                    "categorized_poi_count", "uncategorized_poi_count", "categories", "subcategories",
                )
            }
        if "poi.mix" in dimensions:
            summary["mix"] = profile["mix"]
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({
                "snapshot_id": snapshot_id,
                "kind": "poi_isochrone_scope_profile",
                "dimensions": list(dimensions),
            })[:24],
            "status": "available",
            "analysis": "scope",
            "summary": summary,
            "coverage": {
                "complete": profile["uncategorized_poi_count"] == 0,
                "poi_count": profile["poi_count"],
                "categorized_poi_count": profile["categorized_poi_count"],
                "uncategorized_poi_count": profile["uncategorized_poi_count"],
            },
            "limitations": [*warnings, "POI 描述设施供给，不代表客流、消费或设施容量。"],
            "method": {
                "kind": "poi_isochrone_scope_profile",
                "spatial_universe": "saved_isochrone",
                "point_inclusion": "saved_isochrone_covers_poi_point",
                "entropy_scope": "all_categorized_pois_within_saved_isochrone",
                "internal_metrics_hidden": True,
            },
            "provenance": self._provenance(project, years, sources),
            "fact_domains": ["poi"],
            "evidence_dimensions": list(dimensions),
        })

    def _poi_operation_profile(
        self,
        *,
        history_id: str,
        project: Mapping[str, Any],
        available: set[str],
        request: SpatialDomainComputationRequest,
        dimensions: Sequence[EvidenceDimension],
    ) -> dict[str, Any]:
        scope_geometry, center = self._scope_geometry(project)
        if scope_geometry is None or center is None or _POI not in available:
            return self._unavailable(
                SpatialEvidenceRequest(
                    analysis=request.analysis,
                    metric_ids=["poi.count"],
                    record_refs=request.record_refs,
                ),
                project,
                "当前项目没有可用于等时圈内 POI 分析的保存范围或 POI 快照。",
            )
        sources = {_POI}
        if request.analysis == "inspect":
            sources.update({_H3, _POI_GRID} & available)
        records, years, warnings = self._load_records(history_id, sources)
        selected_pois = self._selected_records(records.get(_POI, []), request.selectors, _POI)
        selected_pois = [
            record
            for record in selected_pois
            if record.geometry is not None and scope_geometry.covers(record.geometry)
        ]
        query = SpatialEvidenceRequest(
            analysis=request.analysis,
            metric_ids=["poi.count"],
            record_refs=request.record_refs,
        )
        if request.analysis == "direction":
            profile = build_poi_direction_profile(selected_pois, scope_geometry, center)
            result = self._response(
                query=query,
                project=project,
                scope=self._scope_summary(project, scope_geometry, center),
                summary=profile["summary"],
                groups=profile["groups"],
                coverage={
                    "complete": bool(selected_pois),
                    "poi_count": len(selected_pois),
                    "direction_count": len(profile["groups"]),
                },
                evidence=[],
                limitations=[*warnings, "POI 方向分布按设施等权计算，不代表设施容量、客流或服务能力。"],
                method={
                    "kind": "poi_direction_distribution",
                    "spatial_universe": "saved_isochrone",
                    "sector_count": 8,
                    "weight_semantics": "equal_weight_facility_proxy",
                },
                provenance=self._provenance(project, years, {_POI}),
            )
            result["fact_domains"] = ["poi"]
            result["evidence_dimensions"] = list(dimensions)
            return _bounded_model_response(result)

        target_records = [
            record
            for source_id in (_H3, _POI_GRID)
            for record in records.get(source_id, [])
            if self._matches_ref(self._record_ref(record), request.record_refs)
            and record.geometry is not None
            and self._has_measure_overlap(record.geometry, scope_geometry)
        ]
        profile = build_poi_inspect_profile(
            targets=target_records,
            poi_records=selected_pois,
            scope_geometry=scope_geometry,
            named_limit=request.top_k,
        )
        if not target_records:
            return self._unavailable(query, project, "指定 record_refs 不是当前等时圈内可检查的 POI 网格。")
        named_objects = [
            {**facility, "object_type": "poi"}
            for facility in profile["named_facilities"]
        ]
        result = self._response(
            query=query,
            project=project,
            scope=self._scope_summary(project, scope_geometry, center),
            summary=profile["summary"],
            groups=profile["groups"],
            named_spatial_objects=named_objects,
            coverage={
                "complete": len(target_records) == len(request.record_refs),
                "matched_target_count": len(target_records),
            },
            evidence=[],
            limitations=[*warnings, "具名设施仅来自当前保存等时圈内 POI 快照。"],
            method={
                "kind": "poi_grid_inspect",
                "spatial_universe": "saved_isochrone",
                "facility_expansion": "inside_target_then_nearest_in_scope",
            },
            provenance=self._provenance(project, years, sources),
        )
        result["fact_domains"] = ["poi"]
        result["evidence_dimensions"] = list(dimensions)
        return _bounded_model_response(result)

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
        history_id: str,
        project: Mapping[str, Any],
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
                "evidence_dimensions": ["population.change"],
            }

        descriptor = next(
            (
                item
                for item in project.get("datasets") or []
                if isinstance(item, Mapping) and str(item.get("source_id") or "") == _POPULATION
            ),
            {},
        )
        available_years = sorted({
            int(year)
            for year in descriptor.get("available_years") or []
            if str(year).isdigit() and 2024 <= int(year) <= 2026
        })
        if len(available_years) < 2:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "analysis": "scope",
                "summary": {},
                "coverage": {"complete": False, "year_count": len(available_years)},
                "limitations": ["人口时序没有形成至少两个可比较年份。"],
                "method": {"kind": "population_temporal_profile", "executed": False},
                "provenance": {},
                "fact_domains": ["population"],
                "evidence_dimensions": ["population.change"],
            }

        records_by_year: dict[int, list[ScopeRecord]] = {}
        try:
            for year in available_years:
                records, _, selected_year = self._datasets.load_scope_records(
                    history_id=history_id,
                    source_id=_POPULATION,
                    year=year,
                    require_geometry_metadata=True,
                )
                if int(selected_year) == year:
                    records_by_year[year] = [
                        record
                        for record in records
                        if record.geometry is not None
                        and not record.geometry.is_empty
                        and self._has_measure_overlap(record.geometry, scope_geometry)
                    ]
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
                "evidence_dimensions": ["population.change"],
            }

        series = [
            self._population_temporal_series_item(year, records_by_year[year], scope_geometry)
            for year in sorted(records_by_year)
        ]
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
                "evidence_dimensions": ["population.change"],
            }
        first, last = series[0], series[-1]
        period = f"{first['year']}-{last['year']}"

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
        spatial_change = self._population_spatial_change(
            records_by_year[int(first["year"])],
            records_by_year[int(last["year"])],
            scope_geometry,
        )
        summary = {
            "period": period,
            "series": series,
            f"change_{first['year']}_{last['year']}": {
                "total_population": change("total_population"),
                "male_total": change("male_total"),
                "female_total": change("female_total"),
                "average_density": change("average_density"),
                "age_group_ratio": age_ratio_change,
            },
            "spatial_change": spatial_change,
        }
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({"snapshot_id": snapshot_id, "kind": "population_temporal_profile", "period": period})[:24],
            "status": "available",
            "analysis": "scope",
            "summary": summary,
            "coverage": {
                "complete": (
                    len(series) == len(available_years)
                    and all(len(item["age_distribution"]) == len(POPULATION_AGE_BANDS) for item in series)
                ),
                "year_count": len(series),
                "age_band_count_by_year": {
                    item["year"]: len(item["age_distribution"])
                    for item in series
                },
                "spatial_unit_count": spatial_change["cell_count"],
            },
            "limitations": [],
            "method": {
                "kind": "population_temporal_profile",
                "period": period,
                "spatial_change_view": "allocated_population_delta_for_stable_cells",
                "spatial_aggregation": "geometry_intersection_aggregation",
                "boundary_cell_policy": "allocate_extensive_values_by_intersection_fraction",
                "scope_geometry": "complete_polygon_or_multipolygon",
                "internal_metrics_hidden": True,
            },
            "provenance": {
                "snapshot_id": snapshot_id,
                "source_ids": [_POPULATION],
                "selected_years": {_POPULATION: sorted(records_by_year)},
            },
            "fact_domains": ["population"],
            "evidence_dimensions": ["population.change"],
        })

    def _population_temporal_series_item(
        self,
        year: int,
        records: Sequence[ScopeRecord],
        scope_geometry: BaseGeometry,
    ) -> dict[str, Any]:
        profile = self._population_profile_for_geometry(records, scope_geometry)
        age_distribution = [
            {
                "age_band": item["age_band"],
                "age_band_label": item["age_band_label"],
                "total": item["total"],
                "male": item["male"],
                "female": item["female"],
                "ratio": item["share"],
            }
            for item in profile["age_distribution"]
        ]
        top_age = max(age_distribution, key=lambda item: float(item.get("total") or 0.0), default=None)
        return {
            "year": str(year),
            "total_population": profile["total_population"],
            "male_total": profile["sex_totals"]["male"],
            "female_total": profile["sex_totals"]["female"],
            "male_ratio": profile["sex_ratios"]["male"],
            "female_ratio": profile["sex_ratios"]["female"],
            "average_density": profile["density_person_per_km2"],
            "age_distribution": age_distribution,
            "age_group_totals": {
                key: value["population"] for key, value in profile["age_groups"].items()
            },
            "age_group_ratios": {
                key: value["share"] for key, value in profile["age_groups"].items()
            },
            "top_age_band": top_age["age_band"] if top_age else None,
            "top_age_band_label": top_age["age_band_label"] if top_age else None,
        }

    def _population_spatial_change(
        self,
        first_records: Sequence[ScopeRecord],
        last_records: Sequence[ScopeRecord],
        scope_geometry: BaseGeometry,
    ) -> dict[str, Any]:
        def allocated(records: Sequence[ScopeRecord]) -> dict[str, float]:
            values: dict[str, float] = {}
            for record in records:
                clipped = record.geometry.intersection(scope_geometry)
                if clipped.is_empty:
                    continue
                value = self._population_target_value([record], clipped, "population.total")
                if value is not None:
                    values[record.record_id] = float(value)
            return values

        first_values = allocated(first_records)
        last_values = allocated(last_records)
        common_ids = sorted(set(first_values) & set(last_values))
        class_counts = Counter()
        for record_id in common_ids:
            delta = last_values[record_id] - first_values[record_id]
            class_counts["increase" if delta > 1e-9 else "decrease" if delta < -1e-9 else "stable"] += 1
        return {
            "cell_count": len(common_ids),
            "class_counts": dict(class_counts),
            "cell_matching": "stable_record_id_intersection",
        }

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

    def _nightlight_operation_profile(
        self,
        history_id: str,
        project: Mapping[str, Any],
        available: set[str],
        request: SpatialDomainComputationRequest,
        dimensions: Sequence[EvidenceDimension],
    ) -> dict[str, Any]:
        """Run the nightlight question semantic for one spatial operation."""

        scope_geometry, center = self._scope_geometry(project)
        if scope_geometry is None or center is None or _NIGHTLIGHT not in available:
            return self._nightlight_unavailable(
                project,
                "当前项目没有可用于等时圈内夜光分析的保存范围或夜光快照。",
                analysis=request.analysis,
            )
        records, years, warnings = self._load_records(history_id, {_NIGHTLIGHT})
        nightlight_records = records.get(_NIGHTLIGHT, [])
        if not nightlight_records:
            return self._nightlight_unavailable(
                project,
                "当前夜光快照没有可用于空间比较的有效单元。",
                analysis=request.analysis,
            )

        if dimensions == ("nightlight.change",):
            descriptor = next(
                (
                    item
                    for item in project.get("datasets") or []
                    if isinstance(item, Mapping) and str(item.get("source_id") or "") == _NIGHTLIGHT
                ),
                {},
            )
            available_years = sorted({
                int(year)
                for year in descriptor.get("available_years") or []
                if str(year).isdigit() and 2023 <= int(year) <= 2025
            })
            records_by_year: dict[int, list[ScopeRecord]] = {}
            for year in available_years:
                yearly, _, selected_year = self._datasets.load_scope_records(
                    history_id=history_id,
                    source_id=_NIGHTLIGHT,
                    year=year,
                    require_geometry_metadata=True,
                )
                if int(selected_year) == year:
                    records_by_year[year] = yearly
            profile = build_nightlight_change_profile(
                records_by_year,
                scope_geometry,
                center,
                analysis=request.analysis,
                record_refs=request.record_refs,
                neighbor_steps=request.neighbor_steps,
                rank_order=request.rank_order,
                top_k=request.top_k,
            )
            if profile["summary"].get("year_count", 0) < 2:
                return self._nightlight_unavailable(
                    project,
                    "夜光变化需要至少两个可比较年度快照。",
                    analysis=request.analysis,
                )
            if request.analysis == "neighborhood" and not profile["groups"]:
                return self._nightlight_unavailable(
                    project,
                    "指定的夜光格网记录不存在或不在保存等时圈内。",
                    analysis=request.analysis,
                )
            if request.analysis == "inspect" and not profile["highlights"]:
                return self._nightlight_unavailable(
                    project,
                    "指定的夜光格网记录不存在或不在可比较年度的共同格网中。",
                    analysis=request.analysis,
                )
            change_query = SpatialEvidenceRequest(
                analysis=request.analysis,
                metric_ids=["nightlight.mean_radiance"],
                record_refs=request.record_refs,
            )
            result = self._response(
                query=change_query,
                project=project,
                scope=self._scope_summary(project, scope_geometry, center),
                summary=profile["summary"],
                groups=profile["groups"],
                highlights=profile["highlights"],
                coverage={
                    "complete": True,
                    "year_count": len(records_by_year),
                    "matched_cell_count": profile["summary"]["matched_cell_count"],
                },
                evidence=[],
                limitations=["结果只描述已保存年度间的亮度增减、中心迁移和局部变化。"],
                method={
                    "kind": "nightlight_descriptive_change",
                    "spatial_universe": "saved_isochrone",
                    "cell_matching": "stable_cell_id_intersection",
                },
                provenance=self._provenance(project, {_NIGHTLIGHT: available_years}, {_NIGHTLIGHT}),
            )
            result["fact_domains"] = ["nightlight"]
            result["evidence_dimensions"] = ["nightlight.change"]
            return _bounded_model_response(result)

        if request.analysis == "accessibility":
            band_geometries, limitation = self._accessibility_band_geometries(
                SpatialEvidenceRequest(
                    analysis="accessibility",
                    metric_ids=["nightlight.mean_radiance"],
                    travel_time_bands_min=request.travel_time_bands_min,
                ),
                project,
                center,
                scope_geometry,
            )
            if limitation:
                return self._nightlight_unavailable(project, limitation, analysis=request.analysis)
            profile = build_nightlight_accessibility_profile(nightlight_records, scope_geometry, band_geometries)
            groups = profile["groups"]
            summary = profile["summary"]
            method = {
                "kind": "nightlight_accessibility_bands",
                "spatial_universe": "saved_isochrone",
                "travel_time_method": "valhalla_nested_isochrone_contours",
                "incremental_bands": True,
            }
            coverage = {"complete": bool(groups), "spatial_unit_count": summary.get("valid_cell_count", 0)}
        elif request.analysis == "direction":
            profile = build_nightlight_direction_profile(nightlight_records, scope_geometry, center)
            groups = profile["groups"]
            summary = profile["summary"]
            method = {
                "kind": "nightlight_direction_profile",
                "spatial_universe": "saved_isochrone",
                "sector_count": 8,
                "boundary_cell_policy": "split_by_sector_intersection_area",
            }
            coverage = {
                "complete": bool(groups),
                "spatial_unit_count": summary.get("valid_cell_count", 0),
            }
        elif request.analysis == "neighborhood":
            profile = build_nightlight_neighborhood_profile(
                nightlight_records,
                scope_geometry,
                request.record_refs,
                neighbor_steps=request.neighbor_steps,
            )
            groups = profile["groups"]
            summary = profile["summary"]
            if summary["target_count"] == 0:
                return self._nightlight_unavailable(
                    project,
                    "指定的夜光格网记录不存在或不在保存等时圈内。",
                    analysis=request.analysis,
                )
            method = {"kind": "nightlight_local_contrast"}
            coverage = {"complete": summary["target_count"] == len(request.record_refs), "target_count": summary["target_count"]}
        elif request.analysis == "rank":
            profile = build_nightlight_rank_profile(
                nightlight_records,
                scope_geometry,
                center,
                rank_order=request.rank_order,
                top_k=request.top_k,
            )
            groups = []
            summary = profile["summary"]
            highlights = profile["highlights"]
            method = {"kind": "nightlight_cell_rank", "combined_score": False}
            coverage = {"complete": bool(highlights), "valid_cell_count": summary["valid_cell_count"]}
        else:
            profile = build_nightlight_inspect_profile(
                nightlight_records,
                scope_geometry,
                center,
                request.record_refs,
            )
            groups = []
            summary = profile["summary"]
            highlights = profile["highlights"]
            if summary["matched_record_count"] == 0:
                return self._nightlight_unavailable(
                    project,
                    "指定的夜光格网记录不存在或不在保存等时圈内。",
                    analysis=request.analysis,
                )
            method = {"kind": "nightlight_cell_inspect"}
            coverage = {"complete": summary["matched_record_count"] == len(request.record_refs), "matched_record_count": summary["matched_record_count"]}

        if request.analysis not in {"rank", "inspect"}:
            highlights = []
        evidence = [
            self._evidence(project, SpatialEvidenceRequest(
                analysis=request.analysis,
                metric_ids=["nightlight.mean_radiance"],
                record_refs=request.record_refs,
            ), f"nightlight:{request.analysis}:{index}", ["nightlight.mean_radiance"], [], item)
            for index, item in enumerate(groups[:20])
        ]
        result = self._response(
            query=SpatialEvidenceRequest(
                analysis=request.analysis,
                metric_ids=["nightlight.mean_radiance"],
                record_refs=request.record_refs,
            ),
            project=project,
            scope=self._scope_summary(project, scope_geometry, center),
            summary=summary,
            groups=groups,
            highlights=highlights,
            coverage=coverage,
            evidence=evidence,
            limitations=[*warnings, "夜光仅描述亮度及其空间差异，不代表真实客流、消费或营业。"],
            method=method,
            provenance=self._provenance(project, years, {_NIGHTLIGHT}),
        )
        result["fact_domains"] = ["nightlight"]
        result["evidence_dimensions"] = list(dimensions)
        return _bounded_model_response(result)

    def _nightlight_scope_profile(
        self,
        project: Mapping[str, Any],
        history_id: str,
        available: set[str],
    ) -> dict[str, Any]:
        """Build current-year nightlight facts inside the saved isochrone."""

        scope_geometry, _ = self._scope_geometry(project)
        if scope_geometry is None or scope_geometry.is_empty:
            return self._nightlight_unavailable(project, "当前项目没有可用于夜光分析的保存范围。")
        records, years, record_warnings = self._load_records(history_id, {_NIGHTLIGHT} & available)
        spatial_distribution = build_nightlight_scope_profile(
            records.get(_NIGHTLIGHT, []),
            scope_geometry,
        )
        coordinates = _polygon_payload(scope_geometry)
        selected_year = years.get(_NIGHTLIGHT)
        try:
            layer = self._nightlight_layer(coordinates, "wgs84", year=selected_year, view="radiance")
        except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return self._nightlight_unavailable(
                project,
                f"夜光领域计算失败：{type(exc).__name__}。",
            )

        layer_year = int(_number(layer.get("year")) or 0) or None
        if selected_year is not None and layer_year != int(selected_year):
            return self._nightlight_unavailable(
                project,
                f"实时夜光图层年份 {layer_year or '未知'} 与保存快照年份 {selected_year} 不一致。",
            )
        raw_summary = layer.get("summary") if isinstance(layer.get("summary"), Mapping) else {}
        raw_analysis = layer.get("analysis") if isinstance(layer.get("analysis"), Mapping) else {}
        raw_sector = raw_analysis.get("sector_direction_analysis")
        sector = raw_sector if isinstance(raw_sector, Mapping) else {}
        summary = {
            "spatial_distribution": spatial_distribution,
            "snapshot": {
                "year": layer_year,
                "total_radiance": _rounded(_number(raw_summary.get("total_radiance"))),
                "mean_radiance": _rounded(_number(raw_summary.get("mean_radiance"))),
                "max_radiance": _rounded(_number(raw_summary.get("max_radiance"))),
                "p90_radiance": _rounded(_number(raw_summary.get("p90_radiance"))),
                "lit_pixel_ratio": _rounded(_number(raw_summary.get("lit_pixel_ratio"))),
                "valid_pixel_count": int(_number(raw_summary.get("valid_pixel_count")) or 0),
            },
            "brightness_profile": {
                "peak_radiance": _rounded(_number(raw_analysis.get("peak_radiance"))),
                "peak_cell_id": str(raw_analysis.get("peak_cell_id") or "") or None,
                "peak_to_edge_ratio": _rounded(_number(raw_analysis.get("peak_to_edge_ratio"))),
                "dominant_direction": str(sector.get("dominant_direction") or "") or None,
                "secondary_direction": str(sector.get("secondary_direction") or "") or None,
                "dominant_share": _rounded(_number(sector.get("dominant_share"))),
                "secondary_share": _rounded(_number(sector.get("secondary_share"))),
            },
        }
        quality = spatial_distribution.get("quality_diagnostics")
        quality_limitation = quality.get("limitation") if isinstance(quality, Mapping) else None
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({"snapshot_id": snapshot_id, "kind": "nightlight_scope_profile", "year": layer_year})[:24],
            "status": "available",
            "analysis": "scope",
            "summary": summary,
            "coverage": {
                "complete": bool(layer_year) and bool(spatial_distribution.get("valid_cell_count")),
                "spatial_unit_count": int(spatial_distribution.get("valid_cell_count") or 0),
            },
            "limitations": [
                *record_warnings,
                "夜光仅描述等时圈内当前年份亮度及其空间差异，不代表真实客流、消费、营业或具体业态。",
                *([str(quality_limitation)] if quality_limitation else []),
            ],
            "method": {
                "kind": "nightlight_scope_profile",
                "spatial_universe": "saved_isochrone",
                "persisted_cell_profile": bool(spatial_distribution["valid_cell_count"]),
                "current_layer_calls": 1,
                "spatial_aggregation": "area_weighted_intersection",
                "boundary_cell_policy": "clip_cells_to_saved_isochrone",
                "internal_metrics_hidden": True,
            },
            "provenance": self._provenance(project, years, {_NIGHTLIGHT}),
            "fact_domains": ["nightlight"],
            "evidence_dimensions": ["nightlight.intensity"],
        })

    @staticmethod
    def _nightlight_unavailable(
        project: Mapping[str, Any],
        limitation: str,
        *,
        analysis: str = "scope",
    ) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "unavailable_reason": limitation,
            "analysis": analysis,
            "summary": {},
            "coverage": {"complete": False},
            "limitations": [limitation],
            "method": {"kind": "nightlight_semantic_operation", "executed": False},
            "provenance": {"snapshot_id": snapshot_id},
            "fact_domains": ["nightlight"],
            "evidence_dimensions": ["nightlight.intensity"],
        }

    def _road_scope_profile(
        self,
        project: Mapping[str, Any],
        history_id: str,
        available: set[str],
        dimensions: Sequence[EvidenceDimension],
    ) -> dict[str, Any]:
        """Read only the selected parts of one persisted road result."""

        selected = tuple(dict.fromkeys(dimensions))
        movement_dimensions = {
            dimension for dimension in selected
            if dimension in {"road.to_movement", "road.through_movement"}
        }
        required_sources = {_ROAD_EDGES}
        if movement_dimensions:
            required_sources.add(_ROAD_CORRIDORS)
        if "road.connectivity" in selected:
            required_sources.add(_ROAD_NODES)
        if "road.network_density" in selected:
            required_sources.add(_ROAD_GRID)
        road_sources = required_sources & available
        records, _, warnings = self._load_records(history_id, road_sources)
        edges = records.get(_ROAD_EDGES, [])
        nodes = records.get(_ROAD_NODES, [])
        grid = records.get(_ROAD_GRID, [])
        corridors = records.get(_ROAD_CORRIDORS, [])
        if not edges:
            return self._road_unavailable(
                project,
                "当前项目没有可读取的已持久化路网线段结果。",
                selected,
            )

        dataset_summaries = {
            str(item.get("source_id") or ""): item.get("summary")
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and isinstance(item.get("summary"), Mapping)
        }
        source_summary = dataset_summaries.get(_ROAD_EDGES) or dataset_summaries.get(_ROAD_GRID) or {}
        radii = self._road_available_radii(edges) if movement_dimensions else []
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
            profile: dict[str, Any] = {"radius": radius}
            if "road.to_movement" in movement_dimensions:
                profile["nain"] = self._distribution(nain_values, len(edges))
            if "road.through_movement" in movement_dimensions:
                profile["nach"] = self._distribution(nach_values, len(edges))
            radius_profiles.append(profile)

        default_profile = next((item for item in radius_profiles if item["radius"] == "global"), None)
        if default_profile is None and radius_profiles:
            default_profile = radius_profiles[0]
        core_background = (
            self._road_core_background(edges, str(default_profile["radius"]), movement_dimensions)
            if default_profile
            else {}
        )

        orientation = source_summary.get("road_orientation_analysis") if "road.orientation" in selected else {}
        if "road.orientation" in selected and (not isinstance(orientation, Mapping) or not orientation):
            orientation = build_road_orientation_analysis([
                {
                    "type": "Feature",
                    "geometry": record.geometry.__geo_interface__,
                    "properties": dict(record.properties),
                }
                for record in edges
                if record.geometry is not None and not record.geometry.is_empty
            ])
        orientation_rows = (
            orientation.get("orientation_rows")
            if isinstance(orientation, Mapping) and isinstance(orientation.get("orientation_rows"), list)
            else []
        )

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
        summary: dict[str, Any] = {}
        if "road.connectivity" in selected or "road.network_density" in selected:
            network: dict[str, Any] = {"edge_count": len(edges)}
            if "road.connectivity" in selected:
                network.update({
                    "node_count": len(nodes) or int(_number(source_summary.get("node_count")) or 0),
                    "mean_connectivity": _rounded(sum(connectivity) / len(connectivity) if connectivity else None),
                })
            if "road.network_density" in selected:
                density_values = [
                    value for record in grid
                    if (value := _number(record.properties.get("road_length_km_per_km2"))) is not None
                ]
                network.update({
                    "network_length_km": _rounded(network_length_km),
                    "density": self._distribution(density_values, len(grid)),
                })
            summary["network"] = network
        if movement_dimensions:
            selected_corridors = [
                record for record in corridors
                if (
                    str(record.properties.get("metric") or "") == "nain"
                    and "road.to_movement" in movement_dimensions
                ) or (
                    str(record.properties.get("metric") or "") == "nach"
                    and "road.through_movement" in movement_dimensions
                )
            ]
            summary.update({
                "radius_profiles": radius_profiles,
                "core_background": core_background,
                "continuous_corridors": {
                    "corridor_count": len(selected_corridors),
                    "by_metric": {
                        metric: sum(str(record.properties.get("metric") or "") == metric for record in selected_corridors)
                        for metric in (
                            ["nain"] if movement_dimensions == {"road.to_movement"}
                            else ["nach"] if movement_dimensions == {"road.through_movement"}
                            else ["nain", "nach"]
                        )
                    },
                    "total_length_km": _rounded(sum(
                        _number(record.properties.get("length_m")) or 0.0 for record in selected_corridors
                    ) / 1000.0),
                },
            })
        if "road.orientation" in selected:
            summary["orientation"] = {
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
            }
        if "road.network_density" in selected:
            summary["grid_coverage"] = {
                "cell_count": len(grid),
                "covered_cell_count": len(covered_grid),
                "no_road_cell_count": max(0, len(grid) - len(covered_grid)),
                "metric_valid_cell_count": grid_metric_valid,
                "no_road_metric_semantics": "null_not_zero",
            }
        if "road.quality" in selected:
            summary["quality"] = {
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
            }
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        return _bounded_model_response({
            "schema_version": SCHEMA_VERSION,
            "result_id": "spatial:" + _digest({
                "snapshot_id": snapshot_id,
                "kind": "road_scope_profile",
                "dimensions": selected,
            })[:24],
            "status": "available",
            "analysis": "scope",
            "summary": summary,
            "coverage": {
                "complete": bool(summary),
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
                "core_network_rule": "selected_movement_metric_at_or_above_same_radius_p75" if movement_dimensions else "not_requested",
            },
            "provenance": {"snapshot_id": snapshot_id, "source_ids": sorted(road_sources)},
            "fact_domains": ["road"],
            "evidence_dimensions": list(selected),
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
    def _road_core_background(
        edges: Sequence[ScopeRecord],
        radius: str,
        dimensions: set[EvidenceDimension],
    ) -> dict[str, Any]:
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
        use_nain = "road.to_movement" in dimensions
        use_nach = "road.through_movement" in dimensions
        core = [
            record for record, nain, nach in rows
            if (use_nain and nain is not None and nain_p75 is not None and nain >= nain_p75)
            or (use_nach and nach is not None and nach_p75 is not None and nach >= nach_p75)
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

        result = {
            "radius": radius,
            "core": payload(core),
            "background": payload(background),
        }
        if use_nain:
            result["nain_p75"] = _rounded(nain_p75)
        if use_nach:
            result["nach_p75"] = _rounded(nach_p75)
        return result

    @staticmethod
    def _road_unavailable(
        project: Mapping[str, Any],
        limitation: str,
        dimensions: Sequence[EvidenceDimension],
    ) -> dict[str, Any]:
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
            "evidence_dimensions": list(dimensions),
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
        project: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_history_id = str(history_id or "").strip()
        if not normalized_history_id:
            raise ValueError("history_id_required")
        query = request if isinstance(request, SpatialEvidenceRequest) else SpatialEvidenceRequest.model_validate(request)
        project = dict(project) if isinstance(project, Mapping) else self._projects.read_history_project(normalized_history_id)
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

        if (
            query.metric_ids
            and all(metric_id.startswith("population.") for metric_id in query.metric_ids)
            and (
                "population.profile" in query.metric_ids
                or query.analysis in {"rank", "neighborhood", "inspect"}
            )
        ):
            return self._population_semantic_result(
                query=query,
                project=project,
                scope=scope,
                records=records,
                years=years,
                warnings=warnings,
                center=center,
                scope_geometry=scope_geometry,
            )

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
            return with_named_pois(self._neighborhood_result(query, project, scope, rows, records, years, warnings))
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
                "spatial_aggregation": "geometry_intersection_aggregation",
                "boundary_cell_policy": "allocate_extensive_values_by_intersection_fraction",
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
        age_distribution = [
            {
                "age_band": band,
                "age_band_label": get_age_band_label(band),
                "total": _rounded(total(METRIC_BINDINGS[f"population.age.{band}.total"])),
                "male": _rounded(total(METRIC_BINDINGS[f"population.age.{band}.male"])),
                "female": _rounded(total(METRIC_BINDINGS[f"population.age.{band}.female"])),
            }
            for band in POPULATION_AGE_BANDS
        ]
        age_groups = {
            "child_0_14": sum(float(item["total"] or 0.0) for item in age_distribution if int(item["age_band"]) < 15),
            "working_15_64": sum(float(item["total"] or 0.0) for item in age_distribution if 15 <= int(item["age_band"]) < 65),
            "senior_65_plus": sum(float(item["total"] or 0.0) for item in age_distribution if int(item["age_band"]) >= 65),
        }
        area_km2 = _area_km2(geometry)
        for item in age_distribution:
            value = float(item["total"] or 0.0)
            item["share"] = _rounded(value / population_total if population_total > 0 else None)
        return {
            "total_population": _rounded(population_total),
            "area_km2": _rounded(area_km2),
            "density_person_per_km2": _rounded(population_total / area_km2 if area_km2 > 0 else None),
            "sex_totals": {
                "total": _rounded(population_total),
                "male": _rounded(male_total),
                "female": _rounded(female_total),
            },
            "sex_ratios": {
                "male": _rounded(male_total / population_total if population_total > 0 else None),
                "female": _rounded(female_total / population_total if population_total > 0 else None),
            },
            "age_groups": {
                key: {
                    "population": _rounded(value),
                    "share": _rounded(value / population_total if population_total > 0 else None),
                }
                for key, value in age_groups.items()
            },
            "age_distribution": age_distribution,
        }

    def _population_semantic_result(
        self,
        *,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        records: Mapping[str, list[ScopeRecord]],
        years: Mapping[str, int | None],
        warnings: list[str],
        center: tuple[float, float],
        scope_geometry: BaseGeometry,
    ) -> dict[str, Any]:
        population_records = self._selected_records(records.get(_POPULATION, []), query.selectors, _POPULATION)
        population_records = [
            record for record in population_records
            if self._has_measure_overlap(record.geometry, scope_geometry)
        ]
        if not population_records:
            return self._unavailable(query, project, "当前等时圈内没有可用人口格网。", scope=scope)
        target_metric_id = self._population_target_metric_id(query.selectors)
        if query.analysis == "scope":
            profile = self._population_profile_for_geometry(population_records, scope_geometry)
            profile["target_population"] = self._population_target_value(
                population_records, scope_geometry, target_metric_id
            )
            profile["target_metric_id"] = target_metric_id
            return self._population_response(
                query, project, scope, years, warnings,
                summary={"population": profile},
                coverage={"complete": True, "spatial_unit_count": len(population_records)},
                method={"kind": "population_scope", "boundary_cell_policy": "intersection_area_fraction"},
            )
        if query.analysis == "accessibility":
            return self._population_accessibility_result(
                query, project, scope, population_records, years, warnings,
                center, scope_geometry, target_metric_id,
            )
        if query.analysis == "direction":
            groups = []
            scope_target_population = float(
                self._population_target_value(population_records, scope_geometry, target_metric_id) or 0.0
            )
            for direction, geometry in self._population_direction_geometries(center, scope_geometry):
                profile = self._population_profile_for_geometry(population_records, geometry)
                compact = self._compact_population_profile(profile)
                target_population = self._population_target_value(
                    population_records, geometry, target_metric_id
                )
                compact["target_population"] = target_population
                compact["target_population_share"] = _rounded(
                    float(target_population or 0.0) / scope_target_population
                    if scope_target_population > 0
                    else None
                )
                groups.append({"key": direction, "label": DIRECTION_LABELS[direction], **compact})
            dominant = max(groups, key=lambda item: float(item.get("target_population") or 0.0), default=None)
            return self._population_response(
                query, project, scope, years, warnings,
                summary={
                    "target_metric_id": target_metric_id,
                    "dominant_distribution_direction": dominant["key"] if dominant else None,
                    "dominant_distribution_direction_label": dominant["label"] if dominant else None,
                    "distribution": self._population_directional_distribution(
                        population_records,
                        scope_geometry,
                        target_metric_id,
                    ),
                },
                groups=groups,
                coverage={"complete": True, "direction_count": len(groups)},
                method={
                    "kind": "population_distribution_direction",
                    "allocation": "sector_intersection_area_fraction",
                    "semantics": "residential_population_location_not_observed_travel_origin",
                },
            )
        if query.analysis == "rank":
            rank_measure = self._population_rank_measure(query.selectors)
            ranked = []
            for record in population_records:
                geometry = record.geometry.intersection(scope_geometry)
                target_population = self._population_target_value([record], geometry, target_metric_id)
                profile = self._population_profile_for_geometry([record], geometry)
                total_population = float(profile.get("total_population") or 0.0)
                area_km2 = float(profile.get("area_km2") or 0.0)
                rank_value = (
                    float(target_population or 0.0)
                    if rank_measure == "count"
                    else float(target_population or 0.0) / area_km2
                    if rank_measure == "density" and area_km2 > 0
                    else float(target_population or 0.0) / total_population
                    if rank_measure == "share" and total_population > 0
                    else 0.0
                )
                ranked.append((rank_value, record, profile, target_population))
            ranked.sort(key=lambda item: item[0], reverse=query.rank_order == "highest")
            highlights = [
                {
                    "record_ref": self._record_ref(record),
                    "title": record.title,
                    "identity": self._record_identity(record),
                    "target_metric_id": target_metric_id,
                    "target_population": _rounded(target_population),
                    "target_density_person_per_km2": _rounded(
                        float(target_population or 0.0) / float(profile.get("area_km2") or 0.0)
                        if float(profile.get("area_km2") or 0.0) > 0
                        else None
                    ),
                    "target_share_of_grid_population": _rounded(
                        float(target_population or 0.0) / float(profile.get("total_population") or 0.0)
                        if float(profile.get("total_population") or 0.0) > 0
                        else None
                    ),
                    "rank_measure": rank_measure,
                    "rank_value": _rounded(rank_value),
                    "population": self._compact_population_profile(profile, include_age_distribution=False),
                    "reason": f"按{self._population_rank_measure_label(rank_measure)}"
                    + ("从高到低" if query.rank_order == "highest" else "从低到高")
                    + "排列的人口网格",
                }
                for rank_value, record, profile, target_population in ranked[: query.top_k]
            ]
            return self._population_response(
                query, project, scope, years, warnings,
                summary={
                    "target_metric_id": target_metric_id,
                    "rank_order": query.rank_order,
                    "rank_measure": rank_measure,
                    "rank_unit": self._population_rank_measure_unit(rank_measure),
                },
                highlights=highlights,
                coverage={"complete": True, "spatial_unit_count": len(population_records)},
                method={"kind": "population_grid_rank", "boundary_cell_policy": "intersection_area_fraction"},
            )
        if query.analysis == "neighborhood":
            return self._population_neighborhood_semantic_result(
                query, project, scope, population_records, years, warnings,
                scope_geometry, target_metric_id,
            )
        if query.analysis == "inspect":
            selected = [
                record for record in population_records
                if self._matches_ref(self._record_ref(record), query.record_refs)
            ][:20]
            highlights = []
            for record in selected:
                geometry = record.geometry.intersection(scope_geometry)
                profile = self._population_profile_for_geometry([record], geometry)
                adjacent = self._population_adjacent_records(record, population_records, steps=1)
                adjacent_values = [
                    float(self._population_target_value(
                        [neighbor], neighbor.geometry.intersection(scope_geometry), target_metric_id
                    ) or 0.0)
                    for neighbor in adjacent
                ]
                target_population = self._population_target_value([record], geometry, target_metric_id)
                neighbor_mean = sum(adjacent_values) / len(adjacent_values) if adjacent_values else None
                highlights.append({
                    "record_ref": self._record_ref(record),
                    "title": record.title,
                    "identity": self._record_identity(record),
                    "target_metric_id": target_metric_id,
                    "year": record.properties.get("year") or record.time_scope.get("year") or years.get(_POPULATION),
                    "target_population": target_population,
                    "population": profile,
                    "neighborhood": {
                        "adjacent_grid_count": len(adjacent),
                        "neighbor_mean_target_population": _rounded(neighbor_mean),
                        "target_delta_from_neighbor_mean": _rounded(
                            float(target_population or 0.0) - neighbor_mean
                            if neighbor_mean is not None
                            else None
                        ),
                    },
                    "reason": "指定人口网格明细",
                })
            if not highlights:
                return self._unavailable(query, project, "没有找到指定的人口网格。", scope=scope)
            return self._population_response(
                query, project, scope, years, warnings,
                summary={"matched_record_count": len(highlights), "target_metric_id": target_metric_id},
                highlights=highlights,
                named_spatial_objects=[
                    {
                        "record_ref": item["record_ref"],
                        "title": item["title"],
                        "identity": item["identity"],
                    }
                    for item in highlights
                ],
                coverage={"complete": len(highlights) == len(query.record_refs)},
                method={"kind": "population_grid_inspect", "boundary_cell_policy": "intersection_area_fraction"},
            )
        return self._unavailable(query, project, "人口结构不支持该空间操作。", scope=scope)

    def _population_accessibility_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        population_records: Sequence[ScopeRecord],
        years: Mapping[str, int | None],
        warnings: list[str],
        center: tuple[float, float],
        scope_geometry: BaseGeometry,
        target_metric_id: str,
    ) -> dict[str, Any]:
        band_geometries, limitation = self._accessibility_band_geometries(
            query, project, center, scope_geometry
        )
        if limitation:
            return self._unavailable(query, project, limitation, scope=scope)
        reachable_geometry: BaseGeometry | None = None
        for _, geometry in band_geometries:
            reachable_geometry = geometry if reachable_geometry is None else reachable_geometry.union(geometry)
        if reachable_geometry is None or reachable_geometry.is_empty:
            return self._unavailable(query, project, "分层等时圈内没有可计算的人口范围。", scope=scope)
        reachable_profile = self._population_profile_for_geometry(population_records, reachable_geometry)
        reachable_total = float(reachable_profile.get("total_population") or 0.0)
        groups = []
        cumulative = []
        cumulative_geometry: BaseGeometry | None = None
        for band, geometry in band_geometries:
            profile = self._population_profile_for_geometry(population_records, geometry)
            incremental = float(profile.get("total_population") or 0.0)
            cumulative_geometry = geometry if cumulative_geometry is None else cumulative_geometry.union(geometry)
            cumulative_profile = self._population_profile_for_geometry(population_records, cumulative_geometry)
            key = f"{_format_band_value(band[0])}-{_format_band_value(band[1])}min"
            groups.append({
                "key": key,
                "time_band_min": [band[0], band[1]],
                "incremental_population": _rounded(incremental),
                "share_of_reachable_population": _rounded(incremental / reachable_total if reachable_total > 0 else None),
                "target_population": self._population_target_value(population_records, geometry, target_metric_id),
                "structure": self._compact_population_profile(profile),
            })
            cumulative.append({
                "time_min": band[1],
                "population": cumulative_profile.get("total_population"),
                "target_population": self._population_target_value(
                    population_records, cumulative_geometry, target_metric_id
                ),
            })
        return self._population_response(
            query, project, scope, years, warnings,
            summary={
                "target_metric_id": target_metric_id,
                "reachable_population": reachable_profile,
                "cumulative": cumulative,
            },
            groups=groups,
            coverage={"complete": True, "band_count": len(groups), "geometry_coverage": "disjoint_bands"},
            method={
                "kind": "population_accessibility",
                "travel_time_method": "valhalla_nested_isochrone_contours",
                "population_allocation": "intersection_area_fraction",
            },
        )

    def _population_neighborhood_semantic_result(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        population_records: Sequence[ScopeRecord],
        years: Mapping[str, int | None],
        warnings: list[str],
        scope_geometry: BaseGeometry,
        target_metric_id: str,
    ) -> dict[str, Any]:
        targets = [
            record for record in population_records
            if self._matches_ref(self._record_ref(record), query.record_refs)
        ]
        if not targets:
            return self._unavailable(query, project, "指定 record_refs 不属于当前等时圈人口网格。", scope=scope)
        population_by_ref = {
            self._record_ref(record): float(
                self._population_target_value(
                    [record],
                    record.geometry.intersection(scope_geometry),
                    target_metric_id,
                ) or 0.0
            )
            for record in population_records
        }
        focus_threshold = _quantile(list(population_by_ref.values()), 0.75)
        focus_records = [
            record
            for record in population_records
            if population_by_ref[self._record_ref(record)] > 0
            and population_by_ref[self._record_ref(record)] >= focus_threshold
        ]
        focus_refs = {self._record_ref(record) for record in focus_records}
        groups = []
        for target in targets[:20]:
            neighbors = self._population_adjacent_records(
                target,
                population_records,
                steps=query.neighbor_steps,
            )
            target_geometry = target.geometry.intersection(scope_geometry)
            target_profile = self._population_profile_for_geometry([target], target_geometry)
            target_population = self._population_target_value([target], target_geometry, target_metric_id)
            neighbor_values = [
                float(self._population_target_value(
                    [neighbor],
                    neighbor.geometry.intersection(scope_geometry),
                    target_metric_id,
                ) or 0.0)
                for neighbor in neighbors
            ]
            neighbor_geometry: BaseGeometry | None = None
            for neighbor in neighbors:
                clipped = neighbor.geometry.intersection(scope_geometry)
                neighbor_geometry = clipped if neighbor_geometry is None else neighbor_geometry.union(clipped)
            neighbor_profile = (
                self._population_profile_for_geometry(neighbors, neighbor_geometry)
                if neighbor_geometry is not None and not neighbor_geometry.is_empty
                else self._population_profile_for_geometry([], Polygon())
            )
            neighbor_mean = sum(neighbor_values) / len(neighbor_values) if neighbor_values else None
            target_density = float(target_profile.get("density_person_per_km2") or 0.0)
            neighbor_density = float(neighbor_profile.get("density_person_per_km2") or 0.0)
            target_ref = self._record_ref(target)
            connected_focus_records = (
                self._population_focus_component(target, focus_records, scope_geometry)
                if target_ref in focus_refs
                else []
            )
            groups.append({
                "key": target_ref,
                "neighbor_count": len(neighbors),
                "target_metric_id": target_metric_id,
                "target": {
                    "target_population": target_population,
                    "population": self._compact_population_profile(target_profile),
                },
                "neighbors": {
                    "grid_count": len(neighbors),
                    "target_population_total": _rounded(sum(neighbor_values)),
                    "target_population_mean_per_grid": _rounded(neighbor_mean),
                    "population": self._compact_population_profile(neighbor_profile),
                },
                "comparison": {
                    "target_population_delta_from_neighbor_mean": _rounded(
                        float(target_population or 0.0) - neighbor_mean
                        if neighbor_mean is not None
                        else None
                    ),
                    "target_to_neighbor_mean_ratio": _rounded(
                        float(target_population or 0.0) / neighbor_mean
                        if neighbor_mean and neighbor_mean > 0
                        else None
                    ),
                    "density_delta_person_per_km2": _rounded(
                        target_density - neighbor_density
                        if neighbors
                        else None
                    ),
                },
                "focus_continuity": {
                    "target_is_focus_grid": target_ref in focus_refs,
                    "focus_threshold": _rounded(focus_threshold),
                    "connected_focus_grid_count": len(connected_focus_records),
                    "connected_focus_population": _rounded(sum(
                        population_by_ref[self._record_ref(record)]
                        for record in connected_focus_records
                    )),
                    "continuous_focus_area": len(connected_focus_records) > 1,
                },
            })
        return self._population_response(
            query, project, scope, years, warnings,
            summary={
                "target_count": len(targets),
                "neighbor_steps": query.neighbor_steps,
                "focus_grid_count": len(focus_records),
                "focus_threshold": _rounded(focus_threshold),
            },
            groups=groups,
            coverage={"complete": True, "target_count": len(targets)},
            method={
                "kind": "population_grid_neighborhood_comparison",
                "adjacency": "grid_geometry",
                "comparison": "descriptive_target_vs_neighbors",
                "focus_rule": "descriptive_saved_isochrone_p75",
                "statistical_significance": "not_computed",
            },
        )

    def _population_response(
        self,
        query: SpatialEvidenceRequest,
        project: Mapping[str, Any],
        scope: dict[str, Any],
        years: Mapping[str, int | None],
        warnings: Sequence[str],
        *,
        summary: Mapping[str, Any],
        coverage: Mapping[str, Any],
        method: Mapping[str, Any],
        groups: Sequence[Mapping[str, Any]] = (),
        highlights: Sequence[Mapping[str, Any]] = (),
        named_spatial_objects: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=dict(summary),
            groups=list(groups),
            highlights=list(highlights),
            named_spatial_objects=list(named_spatial_objects),
            coverage=dict(coverage),
            evidence=[],
            limitations=list(warnings) + [
                "人口格网内部按均匀分布假设进行相交面积分配。",
                "人口来自 WorldPop 格网模型估计，并非逐户实测；不代表实际到访、客流或消费。",
            ],
            method={**method, "spatial_universe": "saved_isochrone"},
            provenance=self._provenance(project, years, {_POPULATION}),
        )

    @classmethod
    def _population_target_metric_id(cls, selectors: Sequence[SpatialEvidenceSelector]) -> str:
        return next(iter(cls._population_metric_ids(selectors)), "population.total")

    def _population_target_value(
        self,
        records: Sequence[ScopeRecord],
        geometry: BaseGeometry,
        metric_id: str,
    ) -> float | None:
        return _rounded(self._metric_value_for_geometry(METRIC_BINDINGS[metric_id], records, geometry))

    @staticmethod
    def _compact_population_profile(
        profile: Mapping[str, Any],
        *,
        include_age_distribution: bool = True,
    ) -> dict[str, Any]:
        compact = {
            "total_population": profile.get("total_population"),
            "area_km2": profile.get("area_km2"),
            "density_person_per_km2": profile.get("density_person_per_km2"),
            "sex_totals": profile.get("sex_totals"),
            "sex_ratios": profile.get("sex_ratios"),
            "age_groups": profile.get("age_groups"),
        }
        if include_age_distribution:
            compact["age_distribution"] = [
                {
                    "age_band": item.get("age_band"),
                    "population": item.get("total"),
                    "share": item.get("share"),
                }
                for item in profile.get("age_distribution") or []
                if isinstance(item, Mapping)
            ]
        return compact

    def _population_adjacent_records(
        self,
        target: ScopeRecord,
        population_records: Sequence[ScopeRecord],
        *,
        steps: int,
    ) -> list[ScopeRecord]:
        members = {self._record_ref(target): target}
        frontier = [target]
        for _ in range(steps):
            next_frontier = []
            for candidate in population_records:
                candidate_ref = self._record_ref(candidate)
                if candidate_ref in members:
                    continue
                if any(
                    item.geometry.buffer(1e-12).intersects(candidate.geometry.buffer(1e-12))
                    for item in frontier
                ):
                    members[candidate_ref] = candidate
                    next_frontier.append(candidate)
            frontier = next_frontier
        members.pop(self._record_ref(target), None)
        return list(members.values())

    def _population_focus_component(
        self,
        target: ScopeRecord,
        focus_records: Sequence[ScopeRecord],
        scope_geometry: BaseGeometry,
    ) -> list[ScopeRecord]:
        focus_by_ref = {self._record_ref(record): record for record in focus_records}
        target_ref = self._record_ref(target)
        if target_ref not in focus_by_ref:
            return []
        component = {target_ref: focus_by_ref[target_ref]}
        frontier = [focus_by_ref[target_ref]]
        while frontier:
            current = frontier.pop()
            current_geometry = current.geometry.intersection(scope_geometry)
            for candidate_ref, candidate in focus_by_ref.items():
                if candidate_ref in component:
                    continue
                candidate_geometry = candidate.geometry.intersection(scope_geometry)
                if current_geometry.buffer(1e-12).intersects(candidate_geometry.buffer(1e-12)):
                    component[candidate_ref] = candidate
                    frontier.append(candidate)
        return list(component.values())

    @classmethod
    def _population_rank_measure(cls, selectors: Sequence[SpatialEvidenceSelector]) -> str:
        return next(iter(cls._selector_values(selectors, "population.measure")), "count")

    @staticmethod
    def _population_rank_measure_label(measure: str) -> str:
        return {"count": "人数", "density": "人口密度", "share": "所选人群占比"}[measure]

    @staticmethod
    def _population_rank_measure_unit(measure: str) -> str:
        return {"count": "person", "density": "person_per_km2", "share": "ratio"}[measure]

    def _population_directional_distribution(
        self,
        records: Sequence[ScopeRecord],
        scope_geometry: BaseGeometry,
        metric_id: str,
    ) -> dict[str, Any]:
        origin = scope_geometry.centroid
        lon0 = float(origin.x)
        lat0 = float(origin.y)
        radius_m = 6_371_008.8
        longitude_scale = math.cos(math.radians(lat0))
        samples: list[tuple[float, float, float]] = []
        for record in records:
            clipped = record.geometry.intersection(scope_geometry)
            if clipped.is_empty:
                continue
            weight = float(self._population_target_value([record], clipped, metric_id) or 0.0)
            if weight <= 0:
                continue
            point = clipped.centroid
            x = radius_m * math.radians(float(point.x) - lon0) * longitude_scale
            y = radius_m * math.radians(float(point.y) - lat0)
            samples.append((x, y, weight))
        total_weight = sum(weight for _, _, weight in samples)
        if total_weight <= 0:
            return {
                "target_metric_id": metric_id,
                "weighted_center_wgs84": None,
                "standard_deviation_ellipse": None,
                "weighted_cell_count": 0,
            }
        mean_x = sum(x * weight for x, _, weight in samples) / total_weight
        mean_y = sum(y * weight for _, y, weight in samples) / total_weight
        variance_x = sum(weight * (x - mean_x) ** 2 for x, _, weight in samples) / total_weight
        variance_y = sum(weight * (y - mean_y) ** 2 for _, y, weight in samples) / total_weight
        covariance_xy = sum(
            weight * (x - mean_x) * (y - mean_y)
            for x, y, weight in samples
        ) / total_weight
        trace = variance_x + variance_y
        delta = math.sqrt(max(0.0, (variance_x - variance_y) ** 2 + 4.0 * covariance_xy ** 2))
        major_variance = max(0.0, (trace + delta) / 2.0)
        minor_variance = max(0.0, (trace - delta) / 2.0)
        if abs(covariance_xy) > 1e-12:
            vector_x = major_variance - variance_y
            vector_y = covariance_xy
        elif variance_x >= variance_y:
            vector_x, vector_y = 1.0, 0.0
        else:
            vector_x, vector_y = 0.0, 1.0
        orientation = math.degrees(math.atan2(vector_x, vector_y)) % 180.0
        center_lon = lon0 + math.degrees(mean_x / (radius_m * longitude_scale))
        center_lat = lat0 + math.degrees(mean_y / radius_m)
        return {
            "target_metric_id": metric_id,
            "weighted_center_wgs84": [round(center_lon, 6), round(center_lat, 6)],
            "standard_deviation_ellipse": {
                "major_axis_standard_distance_m": round(math.sqrt(major_variance), 1),
                "minor_axis_standard_distance_m": round(math.sqrt(minor_variance), 1),
                "orientation_degrees_clockwise_from_north": round(orientation, 1),
            },
            "weighted_cell_count": len(samples),
            "total_weight": _rounded(total_weight),
        }

    @staticmethod
    def _population_direction_geometries(
        center: tuple[float, float],
        scope_geometry: BaseGeometry,
    ) -> list[tuple[str, BaseGeometry]]:
        min_x, min_y, max_x, max_y = scope_geometry.bounds
        radius = max(math.hypot(x - center[0], y - center[1]) for x, y in (
            (min_x, min_y), (min_x, max_y), (max_x, min_y), (max_x, max_y),
        )) * 4.0
        angles = {"E": 0.0, "NE": 45.0, "N": 90.0, "NW": 135.0, "W": 180.0, "SW": 225.0, "S": 270.0, "SE": 315.0}
        result = []
        for direction in DIRECTION_CODES:
            angle = angles[direction]
            low = math.radians(angle - 22.5)
            high = math.radians(angle + 22.5)
            sector = Polygon([
                center,
                (center[0] + math.cos(low) * radius, center[1] + math.sin(low) * radius),
                (center[0] + math.cos(high) * radius, center[1] + math.sin(high) * radius),
                center,
            ])
            result.append((direction, sector.intersection(scope_geometry)))
        return result

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
        records: Mapping[str, list[ScopeRecord]],
        years: Mapping[str, int | None],
        warnings: list[str],
    ) -> dict[str, Any]:
        targets = [row for row in rows if self._matches_ref(row.record_ref, query.record_refs)]
        groups = []
        highlights = []
        named_spatial_objects: list[dict[str, Any]] = []
        scope_geometry, _ = self._scope_geometry(project)
        source_records = {
            self._record_ref(record): record
            for values in records.values()
            for record in values
        }
        selected_pois = self._selected_records(records.get(_POI, []), query.selectors, _POI)
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
            target_record = source_records.get(target.record_ref)
            if (
                target_record is not None
                and target.source_id == _H3
                and scope_geometry is not None
                and selected_pois
            ):
                neighbor_records = [
                    record
                    for member in members
                    if member.record_ref != target.record_ref
                    if (record := source_records.get(member.record_ref)) is not None
                ]
                poi_context = build_poi_neighborhood_profile(
                    target=target_record,
                    neighbors=neighbor_records,
                    poi_records=selected_pois,
                    scope_geometry=scope_geometry,
                    named_limit=query.top_k,
                )
                payload["poi_context"] = poi_context
                for facility in poi_context["named_facilities"]:
                    named_spatial_objects.append({
                        **facility,
                        "object_type": "poi",
                        "target_record_ref": target.record_ref,
                    })
            groups.append(payload)
            highlights.append(self._highlight(target, query.metric_ids, reason=f"{query.neighbor_steps}级邻域目标"))
        if not targets:
            return self._unavailable(query, project, "指定 record_refs 不属于本次分析空间单元。", scope=scope)
        evidence = [
            self._evidence(project, query, f"neighborhood:{group['key']}", query.metric_ids, [group["key"]], group["values"])
            for group in groups
        ]
        coverage = self._row_coverage(rows, query.metric_ids)
        summary: dict[str, Any] = {
            "target_count": len(targets),
            "neighbor_steps": query.neighbor_steps,
            "spatial_universe": "saved_isochrone",
            "comparison_semantics": "target_h3_vs_in_scope_neighbors",
        }
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary=summary,
            groups=groups,
            highlights=highlights,
            named_spatial_objects=named_spatial_objects[:20],
            coverage=coverage,
            evidence=evidence,
            limitations=warnings + self._row_coverage_limitations(coverage),
            method={
                "kind": (
                    "road_edge_topology"
                    if rows and rows[0].source_id == _ROAD_EDGES
                    else "h3_k_ring_or_geometry_adjacency"
                    if rows and rows[0].source_id == _H3
                    else "geometry_adjacency"
                ),
                "neighbor_steps": query.neighbor_steps,
                "spatial_universe": "saved_isochrone",
                "comparison": "descriptive_target_vs_neighbors",
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
        if not complete:
            return self._unavailable(
                query,
                project,
                "当前等时圈内没有同时包含所选事实的共同空间单元。",
                scope=scope,
            )
        relationship = {
            "spatial_unit_count": len(complete),
            "distributions": {
                metric_id: self._distribution(
                    [self._row_metric_value(row, metric_id) for row in complete],
                    len(complete),
                )
                for metric_id in query.metric_ids
            },
            "unit_values": [
                {
                    "record_ref": row.record_ref,
                    "values": {
                        metric_id: _rounded(self._row_metric_value(row, metric_id))
                        for metric_id in query.metric_ids
                    },
                }
                for row in complete[:80]
            ],
        }
        coverage = self._row_coverage(rows, query.metric_ids)
        return self._response(
            query=query,
            project=project,
            scope=scope,
            metrics=self._metric_descriptors(query.metric_ids),
            summary={"common_valid_cell_count": len(complete)},
            relationship=relationship,
            coverage=coverage,
            evidence=[],
            limitations=(
                warnings
                + self._row_coverage_limitations(coverage)
                + ["返回共同空间单元的数值事实，不生成高低共位类别或因果判断。"]
            ),
            method={
                "correlation": False,
                "combined_score": False,
                "spatial_universe": "saved_isochrone",
            },
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
                    if role in {"regional_anchor", "daily_service"}:
                        return (
                            str(item.properties.get("category") or "") in seen_categories,
                            self._poi_direction(item, center) in seen_directions,
                            *base,
                        )
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
    ) -> tuple[int, int, int, int, float, str, str]:
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
            self._named_poi_role_quality(record, role),
            identity_rank,
            distance,
            str(record.properties.get("name") or record.title or "").casefold(),
            record.record_id,
        )

    @staticmethod
    def _named_poi_role_quality(record: ScopeRecord, role: NamedPoiRole) -> int:
        """Prefer actual public-facing facilities over generic category matches."""

        if role == "comparable_supply":
            return 0
        category = str(record.properties.get("category") or "")
        text = " ".join(
            str(value or "")
            for value in (
                record.properties.get("subcategory"),
                record.properties.get("name"),
                record.title,
            )
        )
        preferred: dict[str, tuple[str, ...]] = {
            "交通设施服务": ("地铁", "火车站", "公交", "客运", "机场", "港口", "码头"),
            "风景名胜": ("遗址", "纪念", "博物", "景区"),
            "科教文化服务": ("学校", "小学", "中学", "大学", "幼儿园", "图书馆", "博物馆", "文化馆", "展览馆"),
            "政府机构及社会团体": ("政府机关", "公共服务中心", "居民委员会", "社区委员会", "街道办"),
            "医疗保健服务": ("综合医院", "社区卫生", "卫生院", "诊所", "药房", "药店", "急救"),
            "购物服务": ("便民商店", "便利店", "超市", "市场", "菜场"),
            "体育休闲服务": ("体育场", "运动场", "体育馆", "健身"),
            "生活服务": ("生活服务", "家政", "维修", "洗衣", "养老"),
        }
        if role == "daily_service":
            preferred["科教文化服务"] = ("学校", "小学", "中学", "大学", "幼儿园", "图书馆")
        discouraged = [
            "停车场",
            "出入口",
            "医疗美容",
            "培训机构",
            "建设中",
            "风景名胜相关",
            "设计院",
            "建筑设计",
            "传媒有限公司",
            "商会",
            "协会",
        ]
        if role == "daily_service":
            discouraged.append("博物馆")
        name = str(record.properties.get("name") or record.title or "")
        typecode = str(record.properties.get("typecode") or "")
        if category == "风景名胜" and typecode.startswith("1102"):
            return 0 if any(term in name for term in ("寺", "遗址", "故居", "纪念")) else 1
        if role == "daily_service" and category == "科教文化服务":
            if "建设中" in text:
                return 2
            if any(term in text for term in ("小学", "中学", "大学")):
                return 0
            if "幼儿园" in text:
                return 1
        if any(keyword in text for keyword in discouraged):
            return 2
        if any(keyword in text for keyword in preferred.get(category, ())):
            return 0
        return 1

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
                        if binding.aggregate == "sum" and geometry.geom_type not in {"Point", "MultiPoint"}
                        else 1.0
                    )
                else:
                    candidates = indexes.get(source_id, _RecordIndex([])).query(clipped_geometry)
                    values[metric_id] = self._value_for_unit(
                        binding,
                        clipped_geometry,
                        candidates,
                        allocate_areal_overlap=binding.metric_id.startswith("population."),
                    )
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
        cumulative_poi_counts = {
            metric_id: 0.0
            for metric_id in query.metric_ids
            if metric_id == "poi.count"
        }
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
            for metric_id in cumulative_poi_counts:
                cumulative_poi_counts[metric_id] += float(values.get(metric_id) or 0.0)
                values[metric_id] = round(cumulative_poi_counts[metric_id], 6)
            cumulative_poi_mode = bool(cumulative_poi_counts) and len(cumulative_poi_counts) == len(query.metric_ids)
            key = (
                f"within-{_format_band_value(band[1])}min"
                if cumulative_poi_mode
                else f"{_format_band_value(band[0])}-{_format_band_value(band[1])}min"
            )
            group = {
                "key": key,
                "spatial_unit_count": (
                    int(values["poi.count"])
                    if cumulative_poi_mode
                    else sum(
                        self._has_measure_overlap(record.geometry, geometry)
                        for record in base_records
                    )
                ),
                "values": values,
            }
            if cumulative_poi_mode:
                group["cumulative_time_min"] = band[1]
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
                "poi_count_mode": "cumulative_within_time" if cumulative_poi_counts else None,
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
        if records and all(
            record.geometry is not None
            and record.geometry.geom_type in {"Polygon", "MultiPolygon"}
            for record in records
        ):
            return self._value_for_unit(
                binding,
                geometry,
                records,
                allocate_areal_overlap=True,
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
        if (
            query.analysis == "neighborhood"
            and any(metric_id.startswith("poi.") or metric_id == "spatial.neighbor_density_delta" for metric_id in query.metric_ids)
        ):
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
    def _row_metric_value(row: _SpatialRow, metric_id: str) -> float:
        return float(row.values[metric_id]) * row.aggregation_factors.get(metric_id, 1.0)

    @staticmethod
    def _group_payload(key: str, rows: Sequence[_SpatialRow], metric_ids: Sequence[str]) -> dict[str, Any]:
        values = {}
        for metric_id in metric_ids:
            binding = METRIC_BINDINGS[metric_id]
            numeric = [
                SpatialEvidenceService._row_metric_value(row, metric_id)
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
    def _highlight(
        row: _SpatialRow,
        metric_ids: Sequence[str],
        *,
        reason: str,
        apply_aggregation_factors: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "record_ref": row.record_ref,
            "title": row.title,
            "identity": row.identity,
            "centroid_wgs84": [round(row.centroid[0], 6), round(row.centroid[1], 6)],
            "straight_line_distance_m": round(row.distance_m, 1),
            "direction": row.direction,
            "values": {
                metric_id: _rounded(
                    SpatialEvidenceService._row_metric_value(row, metric_id)
                    if apply_aggregation_factors
                    else row.values.get(metric_id)
                )
                if row.values.get(metric_id) is not None
                else None
                for metric_id in metric_ids
            },
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
    def _provenance(
        project: Mapping[str, Any],
        years: Mapping[str, int | Sequence[int] | None],
        source_ids: Iterable[str],
    ) -> dict[str, Any]:
        snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
        sources = sorted(source_id for source_id in source_ids if source_id)
        datasets_by_source = {
            str(item.get("source_id")): item
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("source_id") or "") in sources
        }
        data_versions = {
            source_id: {
                str(key): item[key]
                for key in (
                    "version", "dataset_version", "data_version", "selected_year",
                    "snapshot_id", "unit", "resolution", "available_years",
                )
                if item.get(key) not in (None, "")
            }
            for source_id, item in datasets_by_source.items()
        }
        selected_years = {
            source_id: (
                years[source_id]
                if source_id in years and years[source_id] is not None
                else datasets_by_source.get(source_id, {}).get("selected_year")
            )
            for source_id in sources
        }
        return {
            "snapshot_id": snapshot_id,
            "source_ids": sources,
            "selected_years": selected_years,
            "data_versions": data_versions,
            "result_checksum": "sha256:" + _digest({
                "snapshot_id": snapshot_id,
                "sources": sources,
                "years": selected_years,
                "data_versions": data_versions,
            }),
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
            unavailable_reason=limitation,
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
        unavailable_reason: str = "",
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
            "selectors": [selector.model_dump(mode="json") for selector in query.selectors],
            "unavailable_reason": unavailable_reason,
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
    source = dict(response)
    if str(source.get("status") or "") in {"unavailable", "failed"} and not source.get("unavailable_reason"):
        limitations = source.get("limitations") if isinstance(source.get("limitations"), list) else []
        first_reason = next((str(item).strip() for item in limitations if str(item).strip()), "")
        if first_reason:
            source["unavailable_reason"] = first_reason
    projected = _safe_value(source)
    if not isinstance(projected, dict):
        return {"status": "unavailable"}

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
        projected["provenance"] = _compact_provenance(projected.get("provenance"))
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


def _compact_provenance(value: Any) -> dict[str, Any]:
    provenance = value if isinstance(value, Mapping) else {}
    data_versions = provenance.get("data_versions") if isinstance(provenance.get("data_versions"), Mapping) else {}
    compact_versions = {
        str(source_id): {
            str(key): item[key]
            for key in (
                "version", "dataset_version", "data_version", "selected_year",
                "snapshot_id", "unit", "resolution", "available_years",
            )
            if isinstance(item, Mapping) and item.get(key) not in (None, "")
        }
        for source_id, item in data_versions.items()
    }
    return {
        "snapshot_id": str(provenance.get("snapshot_id") or ""),
        "source_ids": list(provenance.get("source_ids") or []),
        "selected_years": dict(provenance.get("selected_years") or {}),
        "data_versions": compact_versions,
        "result_checksum": str(provenance.get("result_checksum") or ""),
    }


_AGENT_RESULT_DROP_KEYS = {
    "evidence",
    "limitations",
    "interpretation",
    "interpretation_basis",
    "semantics",
    "comparison_semantics",
    "weight_semantics",
    "facility_weight_semantics",
    "count_semantics",
    "capacity_semantics",
    "time_series_semantics",
    "no_road_metric_semantics",
    "used_metric_ids",
    "metrics",
    "metric_id",
    "metric_ids",
    "target_metric_id",
    "tool_id",
    "tool_version",
    "pattern_counts",
    "dimension_labels",
    "question_semantics",
    "correlation_computed",
    "combined_score_computed",
    "classification_basis",
    "conflict",
    "joint_high",
    "joint_low",
    "high_low",
    "low_high",
    "reason",
    "source_locator",
    "source_type",
    "brightness_pattern",
    "brightness_context",
    "brightness_context_level",
    "brightness_context_summary_text",
    "brightness_class",
    "hotspot_class",
}


_AGENT_FACT_KEY_ALIASES = {
    "clq": "colocation_ratio",
    "poi.count": "poi_count",
    "poi.category_count": "category_count",
    "poi.grid_count": "poi_count",
    "poi.grid_density": "poi_density_per_km2",
    "poi.category_density": "poi_density_per_km2",
    "poi.local_entropy": "shannon_entropy",
    "poi.neighbor_mean_density": "neighbor_mean_density_per_km2",
    "poi.neighbor_mean_entropy": "neighbor_mean_entropy",
    "poi.category_lq": "category_specialization_ratio",
    "spatial.neighbor_density_delta": "neighbor_density_delta_per_km2",
    "population.total": "population_count",
    "population.profile": "population_profile",
    "population.male": "population_count",
    "population.female": "population_count",
    "nightlight.mean_radiance": "mean_radiance",
    "nightlight.total_radiance": "total_radiance",
    "nightlight.max_radiance": "max_radiance",
    "nightlight.p90": "p90_radiance",
    "nightlight.lit_pixel_ratio": "lit_pixel_ratio",
    "road.network_size": "road_length_m",
    "road.network_density": "road_density_km_per_km2",
    "road.connectivity": "connectivity",
    "road.control": "control",
    "road.mean_depth": "mean_depth",
    "road.degree": "degree",
    "road.nain": "to_movement",
    "road.nach": "through_movement",
    "road.nain.selected_radius": "to_movement",
    "road.nach.selected_radius": "through_movement",
}


def _agent_fact_key(raw_key: Any) -> str | None:
    key = str(raw_key)
    normalized = key.lower()
    if normalized.startswith("population.age."):
        return "population_count"
    if normalized in {"spatial.gi_star", "spatial.lisa", "spatial.lisa_z"}:
        return None
    return _AGENT_FACT_KEY_ALIASES.get(normalized, key)

_AGENT_METHOD_FACT_KEYS = {
    "spatial_universe",
    "travel_time_bands_min",
    "travel_mode",
    "spatial_unit_assignment",
    "spatial_aggregation",
    "neighbor_steps",
    "period",
    "cell_matching",
    "point_inclusion",
    "output_unit",
    "walking_speed_km_h",
    "missing_values",
    "extensive_metric_allocation",
    "population_allocation",
}


def _agent_public_projection(value: Any, *, key: str = "") -> Any:
    """Keep the Agent-facing contract factual while hiding executor internals."""

    if isinstance(value, Mapping):
        if key == "method":
            return {
                str(raw_key): _agent_public_projection(item, key=str(raw_key).lower())
                for raw_key, item in value.items()
                if str(raw_key).lower() in _AGENT_METHOD_FACT_KEYS
            }
        projected: dict[str, Any] = {}
        for raw_key, item in value.items():
            normalized_key = str(raw_key).lower()
            if normalized_key in _AGENT_RESULT_DROP_KEYS:
                continue
            public_key = _agent_fact_key(raw_key)
            if public_key is None:
                continue
            public_value = _agent_public_projection(item, key=normalized_key)
            if public_key in projected and projected[public_key] != public_value:
                existing = projected[public_key]
                projected[public_key] = (
                    [*existing, public_value]
                    if isinstance(existing, list)
                    else [existing, public_value]
                )
            else:
                projected[public_key] = public_value
        return projected
    if isinstance(value, (list, tuple)):
        if key == "fact_domains":
            return [
                _agent_public_projection(item.get("domain"), key="domain")
                if isinstance(item, Mapping) and item.get("domain") is not None
                else _agent_public_projection(item, key=key)
                for item in value
            ]
        if key == "evidence_dimensions":
            return [
                _agent_public_projection(item.get("dimension"), key="dimension")
                if isinstance(item, Mapping) and item.get("dimension") is not None
                else _agent_public_projection(item, key=key)
                for item in value
            ]
        return [_agent_public_projection(item, key=key) for item in value]
    return value


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
            "status", "year", "period", "level", "snapshot", "brightness_pattern", "brightness_context",
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


def _dataset_available_years(project: Mapping[str, Any], source_id: str) -> list[int]:
    descriptor = next(
        (
            item
            for item in project.get("datasets") or []
            if isinstance(item, Mapping) and str(item.get("source_id") or "") == source_id
        ),
        {},
    )
    return sorted({
        int(year)
        for year in descriptor.get("available_years") or []
        if str(year).isdigit()
    })


def _polygon_payload(geometry: BaseGeometry) -> list:
    polygons = (
        [geometry]
        if isinstance(geometry, Polygon)
        else [part for part in getattr(geometry, "geoms", ()) if isinstance(part, Polygon)]
    )
    rings = [
        [[float(x), float(y)] for x, y in polygon.exterior.coords]
        for polygon in polygons
        if not polygon.is_empty
    ]
    if not rings:
        raise ValueError("scope_geometry_requires_polygon")
    return rings[0] if len(rings) == 1 else rings


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (GEOSException, TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None else None


def spatial_data_identity(project: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the stable dataset identity used for result reproducibility."""

    identity: list[dict[str, Any]] = []
    for item in project.get("datasets") or []:
        if not isinstance(item, Mapping):
            continue
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        row: dict[str, Any] = {"source_id": source_id}
        for key in (
            "version", "dataset_version", "data_version", "selected_year",
            "snapshot_id", "unit", "resolution", "available_years",
            "record_count", "checksum", "artifact_id",
        ):
            if item.get(key) not in (None, ""):
                row[key] = item[key]
        identity.append(row)
    return sorted(identity, key=lambda item: str(item["source_id"]))


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


def spatial_domain_result_id(
    project: Mapping[str, Any],
    request: SpatialDomainComputationRequest | Mapping[str, Any],
) -> str:
    """Return the stable identity for one domain computation without executing it."""

    domain_query = (
        request
        if isinstance(request, SpatialDomainComputationRequest)
        else SpatialDomainComputationRequest.model_validate(request)
    )
    snapshot_id = str((project.get("snapshot") or {}).get("snapshot_id") or project.get("history_id") or "")
    return "spatial:" + _digest({
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "data_identity": spatial_data_identity(project),
        "request": domain_query.model_dump(mode="json"),
    })[:24]


__all__ = [
    "CATALOG_SCOPE_BINDINGS",
    "EVIDENCE_DIMENSION_BINDINGS",
    "FACT_DOMAIN_CAPABILITIES",
    "EvidenceDimension",
    "FactDomain",
    "METRIC_BINDINGS",
    "NamedPoiRole",
    "SCHEMA_VERSION",
    "spatial_data_identity",
    "SpatialDomainComputationRequest",
    "SpatialEvidenceRequest",
    "SpatialEvidenceSelector",
    "SpatialEvidenceService",
    "spatial_domain_result_id",
]
