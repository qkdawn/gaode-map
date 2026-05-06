"""
High level entry to build the map request JSON payload.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple, Union
import time

from core.config import settings

from .get_around_place import get_around_place
from .get_city_place import get_city_place
from .get_position import get_position
from .local_query import query_local_around, query_local_city
from .utils.get_type_info import get_type_info, list_place_types, map_typecode_to_point_type
from .utils.transform_posi import wgs84_to_gcj02

logger = logging.getLogger(__name__)

# Default token used by the demo service.
DEFAULT_AUTH_HEADER = "gaode-map-plugin-2025-dev-only"
DEFAULT_CONCURRENCY = 2
# 类型切换时的请求间隔（秒），避免连续命中频控
TYPE_SWITCH_DELAY = 0.3


def generate_map_json(
    place: str,
    search_type: Literal["around", "city"] = "around",
    place_types: Optional[Sequence[str]] = None,
    radius: int = 1200,
    api_key: Optional[str] = None,
    auth_header: Optional[str] = None,
    mock_data: Optional[Dict] = None,
    max_concurrency: int = DEFAULT_CONCURRENCY,
    year: Optional[int] = None,
    source: Literal["gaode", "local"] = "gaode",
    pre_points_hook: Optional[
        Callable[[Dict, str, Optional[Sequence[str]]], Optional[Tuple[int, Dict]]]
    ] = None,
) -> Tuple[Dict, Optional[int]]:
    """
    Main entry to orchestrate Gaode requests and output a payload
    that matches `map请求示例.json`.
    - place: user provided text such as a city name or landmark
    - search_type: "around" searches near the place, "city" searches across the city
    - place_types: optional list of categories, e.g. ["公交站", "地铁站"], if  None, will use default place_types
    """
    type_configs = _resolve_type_config(search_type, place_types)
    logger.debug("Resolved type configurations: %s", type_configs)
    # Prepare mock structures if provided.
    mock_data = mock_data or {}
    geocode_mock = mock_data.get("geocode")
    around_pages_mock = mock_data.get("around_pages")
    city_info_mock = mock_data.get("city_info")
    city_pages_mock = mock_data.get("city_pages")

    if source == "local":
        center = get_position(place, api_key=api_key, mock_response=geocode_mock)
        if pre_points_hook:
            cached = pre_points_hook(center, search_type, place_types)
            if cached:
                cached_id, body = cached
                payload = {
                    "url": f"{settings.app_base_url}/api/v1/generate-map",
                    "method": "POST",
                    "header": {"Authorization": auth_header or DEFAULT_AUTH_HEADER},
                    "param": {},
                    "body": body,
                    "auth": None,
                }
                logger.debug("命中预生成数据: center+local")
                return payload, cached_id

        local_types = _merge_local_types(type_configs)
        logger.debug("Local query types: %s", local_types)
        if search_type == "around":
            pois = query_local_around(
                center=center,
                radius=radius,
                types=local_types,
                year=year,
            )
            points = [_local_poi_to_point(poi, year=year) for poi in pois]
        elif search_type == "city":
            adcode = center.get("adcode") or ""
            if not adcode:
                raise ValueError("本地 city 查询缺少 adcode")
            pois = query_local_city(
                adcode=adcode,
                city_name=center.get("city") or None,
                city_code=center.get("citycode") or None,
                types=local_types,
                year=year,
            )
            logger.debug("Local city pois: %s",  pois)
            points = [_local_poi_to_point(poi, year=year) for poi in pois]
        else:
            raise ValueError("search_type must be 'around' or 'city'")
    # Gaode source
    elif search_type == "around":
        center = get_position(place, api_key=api_key, mock_response=geocode_mock)
        if pre_points_hook:
            cached = pre_points_hook(center, search_type, place_types)
            if cached:
                cached_id, body = cached
                payload = {
                    "url": f"{settings.app_base_url}/api/v1/generate-map",
                    "method": "POST",
                    "header": {"Authorization": auth_header or DEFAULT_AUTH_HEADER},
                    "param": {},
                    "body": body,
                    "auth": None,
                }
                logger.debug("命中预生成数据: center+around")
                return payload, cached_id

        points = _collect_around_points(
            center=center,
            radius=radius,
            type_configs=type_configs,
            api_key=api_key,
            mock_pages=around_pages_mock,
            max_concurrency=max_concurrency,
        )
    elif search_type == "city":
        center = get_position(place, api_key=api_key, mock_response=geocode_mock)
        if pre_points_hook:
            cached = pre_points_hook(center, search_type, place_types)
            if cached:
                cached_id, body = cached
                payload = {
                    "url": f"{settings.app_base_url}/api/v1/generate-map",
                    "method": "POST",
                    "header": {"Authorization": auth_header or DEFAULT_AUTH_HEADER},
                    "param": {},
                    "body": body,
                    "auth": None,
                }
                logger.debug("命中预生成数据: center+city")
                return payload, cached_id

        center, points = _collect_city_points(
            place=place,
            type_configs=type_configs,
            api_key=api_key,
            mock_city=city_info_mock,
            mock_pages=city_pages_mock,
            max_concurrency=max_concurrency,
            center_override=center,
        )
    else:
        raise ValueError("search_type must be 'around' or 'city'")

    if year is not None:
        for point in points:
            point.setdefault("year", int(year))

    body = {"center": center, "points": points, "radius": radius}

    # city 模式附带 adcode 方便前端绘制行政边界
    if isinstance(center, dict) and center.get("adcode"):
        body["adcode"] = center["adcode"]
    payload = {
        "url": f"{settings.app_base_url}/api/v1/generate-map",
        "method": "POST",
        "header": {"Authorization": auth_header or DEFAULT_AUTH_HEADER},
        "param": {},
        "body": body,
        "auth": None,
    }

    logger.debug("Generated map JSON with %s points", len(points))
    return payload, None


def _resolve_type_config(
    search_type: Literal["around", "city"],
    place_types: Optional[Sequence[str]] = None,
) -> List[Dict[str, str]]:
    """
    Pick the Gaode types/keywords/point_type configuration.
    When place_types is not provided, use defaults defined in 02-修改请求.md.
    """
    candidates: List[str] = []
    if place_types:
        candidates.extend([item for item in place_types if item])

    if not candidates:
        # 默认值：around 使用 type_map.json 中的所有类型，city 用火车站（使用 doc/poi_type.md 中的中类名称）
        candidates = list_place_types() if search_type == "around" else ["火车站", "机场相关", "长途汽车站", "港口码头"]

    configs: List[Dict[str, str]] = []
    for item in candidates:
        types, keywords, point_type = get_type_info(item)
        configs.append(
            {
                "types": types,
                "keywords": keywords,
                "point_type": point_type,
            }
        )
    return configs

# 去重加兼容本地数据查询参数“/”
def _merge_local_types(type_configs: List[Dict[str, str]]) -> str:
    """
    Merge typecode strings for local query (join by '|').
    """
    codes: List[str] = []
    for cfg in type_configs:
        for code in (cfg.get("types") or "").split("|"):
            code = code.strip()
            if code:
                codes.append(code)
    unique = sorted(set(codes))
    return "/".join(unique)


def _local_poi_to_point(poi: Dict, year: Optional[int] = None) -> Dict:
    """
    Convert local POI schema to map point.
    """
    location = poi.get("location", "0,0")
    lng_str, lat_str = (location.split(",") + ["0", "0"])[:2]
    lng, lat = float(lng_str), float(lat_str)
    if settings.local_query_coord_system == "wgs84":
        lng, lat = wgs84_to_gcj02(lng, lat)
    point_type = map_typecode_to_point_type(poi.get("typecode", ""), "poi")

    point = {
        "lng": lng,
        "lat": lat,
        "name": poi.get("name", ""),
        "type": point_type,
        "distance": _safe_int(poi.get("distance")),
        "year": _safe_int(poi.get("year")) or year,
    }

    if poi.get("address"):
        lines = [part for part in poi["address"].split(";") if part]
        if lines:
            point["lines"] = lines

    return point


def _safe_int(value: Optional[Union[str, int]]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _collect_around_points(
    center: Dict,
    radius: int,
    type_configs: List[Dict[str, str]],
    api_key: Optional[str],
    mock_pages: Optional[List[Dict]],
    max_concurrency: int,
) -> List[Dict]:
    """
    针对每个类型单独请求，再合并结果；支持并发控制，避免一次性拼接 keywords/types。
    """
    if not type_configs:
        return []

    # 兼容：有 mock_pages 时沿用单次请求的路径，方便离线测试。
    if mock_pages is not None:
        cfg = type_configs[0]
        return get_around_place(
            center,
            radius=radius,
            types=cfg["types"],
            keywords=cfg["keywords"],
            point_type=cfg["point_type"],
            api_key=api_key,
            mock_pages=mock_pages,
        )

    points: List[Dict] = []
    workers = max(1, min(max_concurrency, len(type_configs)))

    if len(type_configs) == 1 or workers == 1:
        for idx, cfg in enumerate(type_configs):
            points.extend(
                get_around_place(
                    center,
                    radius=radius,
                    types=cfg["types"],
                    keywords=cfg["keywords"],
                    point_type=cfg["point_type"],
                    api_key=api_key,
                )
            )
            if idx < len(type_configs) - 1:
                time.sleep(TYPE_SWITCH_DELAY)
        return points

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_cfg = {
            executor.submit(
                get_around_place,
                center,
                radius,
                cfg["types"],
                cfg["keywords"],
                cfg["point_type"],
                api_key,
            ): cfg
            for cfg in type_configs
        }
        for future in as_completed(future_to_cfg):
            points.extend(future.result())

    return points


def _collect_city_points(
    place: str,
    type_configs: List[Dict[str, str]],
    api_key: Optional[str],
    mock_city: Optional[Dict],
    mock_pages: Optional[List[Dict]],
    max_concurrency: int,
    center_override: Optional[Dict] = None,
) -> Tuple[Dict, List[Dict]]:
    """
    城市级搜索：按 type_configs 列表单独请求并合并结果，支持并发控制。
    """
    if not type_configs:
        type_configs = [{"types": "", "keywords": "", "point_type": "train"}]

    # 有 mock 时沿用单次请求路径，确保兼容离线数据。
    if mock_pages is not None or mock_city is not None:
        cfg = type_configs[0]
        return get_city_place(
            place=place,
            types=cfg["types"],
            keywords=cfg["keywords"],
            point_type=cfg["point_type"],
            api_key=api_key,
            mock_city=mock_city,
            mock_pages=mock_pages,
            center=center_override,
        )

    # 单类型或并发度为 1 时串行。
    points: List[Dict] = []
    center: Optional[Dict] = None
    workers = max(1, min(max_concurrency, len(type_configs)))

    if len(type_configs) == 1 or workers == 1:
        for idx, cfg in enumerate(type_configs):
            c, ps = get_city_place(
                place=place,
                types=cfg["types"],
                keywords=cfg["keywords"],
                point_type=cfg["point_type"],
                api_key=api_key,
                mock_city=None,
                mock_pages=None,
                center=center_override,
            )
            center = center or c
            points.extend(ps)
            if idx < len(type_configs) - 1:
                time.sleep(TYPE_SWITCH_DELAY)
        return center or {"lng": 0, "lat": 0, "name": place, "type": "center"}, points

    # 并发请求不同类型。
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_cfg = {
            executor.submit(
                get_city_place,
                place,
                cfg["types"],
                cfg["keywords"],
                cfg["point_type"],
                api_key,
                None,
                None,
                center_override,
            ): cfg
            for cfg in type_configs
        }
        for future in as_completed(future_to_cfg):
            c, ps = future.result()
            center = center or c
            points.extend(ps)

    return center or {"lng": 0, "lat": 0, "name": place, "type": "center"}, points
