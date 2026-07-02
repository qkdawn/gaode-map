"""Convenience exports for the Amap provider."""

from .gen_json import generate_map_json
from .get_around_place import get_around_place
from .get_city_place import get_city_place
from .get_position import get_position
from .regeo import reverse_geocode
from .utils.get_type_info import get_type_info
from .utils.merge_poi import merge_poi, poi_to_point

__all__ = [
    "generate_map_json",
    "get_around_place",
    "get_city_place",
    "get_position",
    "reverse_geocode",
    "get_type_info",
    "merge_poi",
    "poi_to_point",
]
