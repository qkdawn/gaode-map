from __future__ import annotations

from typing import Any, Dict, List, Optional


DEFAULT_POI_YEARS = [2020, 2022, 2024]


def normalize_years(years: Any) -> List[int]:
    normalized: List[int] = []
    for item in years or []:
        try:
            year = int(item)
        except (TypeError, ValueError):
            continue
        if year not in (2020, 2022, 2024, 2026):
            continue
        normalized.append(year)
    unique = sorted(set(normalized))
    return unique or DEFAULT_POI_YEARS[:]


def normalize_type_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


def build_category_matchers(categories: List[Any]) -> Dict[str, Dict[str, Any]]:
    matchers: Dict[str, Dict[str, Any]] = {}
    for category in categories or []:
        cat_id = str(getattr(category, "id", "") or "").strip()
        if not cat_id:
            continue
        codes: List[str] = []
        for raw in str(getattr(category, "types", "") or "").split("|"):
            code = normalize_type_code(raw)
            if code and code not in codes:
                codes.append(code)
        matchers[cat_id] = {
            "id": cat_id,
            "name": str(getattr(category, "name", "") or cat_id),
            "codes": codes,
        }
    return matchers


def resolve_category_id(type_text: Any, matchers: Dict[str, Dict[str, Any]]) -> str:
    code = normalize_type_code(type_text)
    if not code:
        return ""
    for cat_id, matcher in matchers.items():
        for candidate in matcher.get("codes") or []:
            if code == candidate or code.startswith(candidate) or code[:2] == candidate[:2]:
                return cat_id
    return ""


def poi_exact_key(poi: Dict[str, Any]) -> str:
    poi_id = str((poi or {}).get("id") or "").strip()
    if poi_id:
        return f"id:{poi_id}"
    name = str((poi or {}).get("name") or "").strip()
    location = (poi or {}).get("location")
    if isinstance(location, (list, tuple)) and len(location) >= 2:
        try:
            return f"name_loc:{name}|{float(location[0]):.6f},{float(location[1]):.6f}"
        except (TypeError, ValueError):
            pass
    return f"name:{name}"


def deduplicate_pois(pois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for poi in pois or []:
        key = poi_exact_key(poi)
        if key in seen:
            continue
        seen.add(key)
        result.append(poi)
    return result


def select_display_year(results_by_year: List[Dict[str, Any]]) -> Optional[int]:
    successful = [
        int(item["year"])
        for item in results_by_year or []
        if int(item.get("count") or 0) > 0
    ]
    return max(successful) if successful else None


def build_summary_by_year(
    results_by_year: List[Dict[str, Any]],
    categories: List[Any],
) -> List[Dict[str, Any]]:
    matchers = build_category_matchers(categories)
    summaries: List[Dict[str, Any]] = []
    for item in results_by_year or []:
        counts = {cat_id: 0 for cat_id in matchers.keys()}
        for poi in item.get("pois") or []:
            cat_id = resolve_category_id((poi or {}).get("type"), matchers)
            if cat_id:
                counts[cat_id] = counts.get(cat_id, 0) + 1
        summaries.append(
            {
                "year": int(item.get("year")),
                "source": item.get("source") or "local",
                "count": int(item.get("count") or 0),
                "category_counts": counts,
            }
        )
    return summaries


def build_category_summary(
    pois: List[Dict[str, Any]],
    categories: List[Any],
) -> List[Dict[str, Any]]:
    matchers = build_category_matchers(categories)
    counts = {cat_id: 0 for cat_id in matchers.keys()}
    for poi in pois or []:
        cat_id = resolve_category_id((poi or {}).get("type"), matchers)
        if cat_id:
            counts[cat_id] = counts.get(cat_id, 0) + 1
    return [
        {
            "id": cat_id,
            "name": str(matcher.get("name") or cat_id),
            "count": int(counts.get(cat_id, 0)),
        }
        for cat_id, matcher in matchers.items()
    ]
