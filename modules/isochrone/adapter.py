import json
import logging
from typing import Iterable, List, Tuple, Union

import requests
from shapely.geometry import Point, Polygon, shape
from shapely.geometry.base import BaseGeometry

from core.config import settings

logger = logging.getLogger(__name__)


class ValhallaIsochroneUnavailable(RuntimeError):
    """Valhalla could not return every requested contour without approximation."""


def fetch_valhalla_isochrone_contours(
    center: tuple[float, float],
    time_bands_min: Iterable[float],
    mode: str,
) -> dict[float, BaseGeometry]:
    """Fetch exact nested Valhalla contours; never use the geometric fallback."""
    costing_map = {"walking": "pedestrian", "driving": "auto", "bicycling": "bicycle"}
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in costing_map:
        raise ValhallaIsochroneUnavailable("valhalla_isochrone_mode_unsupported")
    try:
        lon, lat = float(center[0]), float(center[1])
        times = sorted({float(value) for value in time_bands_min})
    except (IndexError, TypeError, ValueError) as exc:
        raise ValhallaIsochroneUnavailable("valhalla_isochrone_request_invalid") from exc
    if not times or any(value <= 0 for value in times):
        raise ValhallaIsochroneUnavailable("valhalla_isochrone_times_invalid")

    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": costing_map[normalized_mode],
        "contours": [{"time": value} for value in times],
        "polygons": True,
    }
    try:
        response = requests.post(
            f"{settings.valhalla_base_url}/isochrone",
            json=payload,
            timeout=settings.valhalla_timeout_s,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ValhallaIsochroneUnavailable("valhalla_isochrone_request_failed") from exc

    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list) or not features:
        raise ValhallaIsochroneUnavailable("valhalla_isochrone_features_missing")
    contours: dict[float, BaseGeometry] = {}
    unlabelled: list[BaseGeometry] = []
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
            continue
        try:
            geometry = shape(feature["geometry"])
        except (TypeError, ValueError):
            continue
        if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        raw_time = properties.get("contour", properties.get("time"))
        try:
            contour_time = float(raw_time)
        except (TypeError, ValueError):
            unlabelled.append(geometry)
            continue
        matched = next((value for value in times if abs(value - contour_time) < 1e-6), None)
        if matched is not None:
            contours[matched] = geometry

    # Older Valhalla builds may omit contour labels but preserve request order.
    if len(contours) != len(times) and len(features) == len(times) and len(unlabelled) == len(times):
        contours = dict(zip(times, unlabelled))
    missing = [value for value in times if value not in contours]
    if missing:
        raise ValhallaIsochroneUnavailable("valhalla_isochrone_contours_incomplete")
    return {value: contours[value] for value in times}

def _get_fallback_isochrone(center: Point, time_sec: int, mode: str) -> Polygon:
    """
    Fallback: Generate a simple buffer polygon (circle) based on estimated speed.
    Used when Valhalla service is unavailable.
    """
    # Speed estimates in km/h
    speeds = {
        "walking": 5.0,
        "bicycling": 15.0,
        "driving": 30.0
    }
    speed_kmh = speeds.get(mode, 5.0)
    
    # Distance = Speed * Time
    # time_sec to hours
    time_hours = time_sec / 3600.0
    distance_km = speed_kmh * time_hours
    
    # Simple conversion to degrees (approximate)
    # 1 degree latitude ~= 111 km
    # This is a rough estimation suitable for visual feedback/testing only.
    buffer_radius_deg = distance_km / 111.0
    
    logger.warning(f"Using Fallback Isochrone: Buffer {distance_km:.2f}km ({buffer_radius_deg:.5f} deg) for {mode}")
    
    return center.buffer(buffer_radius_deg)

def fetch_amap_isochrone(center: Point, time_sec: int, mode: str) -> Polygon:
    """
    Fetch isochrone polygon from Valhalla (Real Implementation).
    
    Args:
        center: Point in WGS84
        time_sec: Time in seconds (Valhalla expects minutes usually, we will convert)
        mode: 'walking', 'driving', 'bicycling' (Valhalla costing models)
        
    Returns:
        Polygon in WGS84
    """
    # 1. Map mode to Valhalla costing
    costing_map = {
        "walking": "pedestrian",
        "driving": "auto",
        "bicycling": "bicycle"
    }
    costing = costing_map.get(mode, "pedestrian")
    
    # 2. Prepare payload
    # Valhalla expects 'contours' with 'time' in minutes
    time_min = time_sec / 60
    
    payload = {
        "locations": [{"lat": center.y, "lon": center.x}],
        "costing": costing,
        "contours": [{"time": time_min}],
        "polygons": True  # Request polygon geometry output
    }
    
    url = f"{settings.valhalla_base_url}/isochrone"
    
    logger.info(f"Requesting Valhalla: {url} | Mode: {costing} | Time: {time_min}min")
    
    try:
        resp = requests.post(url, json=payload, timeout=settings.valhalla_timeout_s)
        resp.raise_for_status()
        data = resp.json()
        
        # 3. Parse Response
        # Valhalla returns a FeatureCollection. We expect at least one feature.
        features = data.get("features", [])
        if not features:
            logger.warning("Valhalla returned no isochrone features.")
            return Polygon()
            
        # Extract coordinates from the first feature (the isochrone)
        # Geometry type is usually 'Polygon' or 'MultiPolygon'
        geometry = features[0].get("geometry", {})
        coords = geometry.get("coordinates", [])
        
        if not coords:
            return Polygon()
            
        # Handle Polygon vs MultiPolygon
        # Simplication: Take the largest outer ring if complex, or just the first shell.
        # Valhalla Polygon structure: [ [ [lon, lat], ... ] ] (Outer ring)
        
        # Note: Shapely Polygon takes (shell, holes). 
        # Valhalla returns [shell, hole1, hole2...]
        if geometry.get("type") == "Polygon":
            shell = coords[0]
            holes = coords[1:] if len(coords) > 1 else []
            return Polygon(shell, holes)
            
        elif geometry.get("type") == "MultiPolygon":
            # For simplicity in this MVP, return the largest polygon or the union (if we had MultiPolygon support in type hint)
            # The interface defines return as Polygon. We take the first one (usually the main distinct region).
            shell = coords[0][0] # First polygon, first ring (shell)
            return Polygon(shell)
            
        return Polygon()

    except requests.RequestException as e:
        logger.error(f"Valhalla API connection failed: {e}")
        logger.warning("Valhalla service unavailable. Falling back to simple geometric approximation.")
        return _get_fallback_isochrone(center, time_sec, mode)
