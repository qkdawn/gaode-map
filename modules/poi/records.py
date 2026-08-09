from __future__ import annotations

import math
import re
from typing import Any

from core.poi_taxonomy import get_poi_taxonomy, normalize_typecode


POI_RECORD_FIELDS = (
    "poi_id",
    "name",
    "category",
    "subcategory",
    "typecode",
    "address",
    "location",
    "year",
    "source",
)

_TYPE_PARTS = re.compile(r"[;|,，/]+")


class PoiRecordContractError(ValueError):
    pass


def _text(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def _location(value: Any) -> list[float] | None:
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        return None
    if len(parts) < 2:
        return None
    try:
        lon, lat = float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return [lon, lat]


def poi_semantics(value: dict[str, Any]) -> dict[str, str]:
    """Resolve named labels without discarding the producer's original typecode."""
    raw_type = _text(value.get("type"))
    typecode = normalize_typecode(value.get("typecode") or raw_type)
    named_parts = [part.strip() for part in _TYPE_PARTS.split(raw_type) if part.strip()]
    if len(named_parts) == 1 and normalize_typecode(named_parts[0]) == named_parts[0]:
        named_parts = []

    taxonomy = get_poi_taxonomy().resolve_typecode(typecode)
    category = _text(value.get("category")) or (named_parts[0] if named_parts else "")
    subcategory = _text(value.get("subcategory")) or (named_parts[1] if len(named_parts) > 1 else "")
    if taxonomy is not None:
        category = category or taxonomy.main_category
        subcategory = subcategory or taxonomy.subcategory
    return {
        "category": category,
        "subcategory": subcategory,
        "typecode": typecode,
    }


def complete_poi_record(
    value: dict[str, Any],
    *,
    year: Any = None,
    source: Any = None,
) -> dict[str, Any]:
    semantics = poi_semantics(value)
    raw_year = value.get("year") if value.get("year") not in (None, "") else year
    try:
        normalized_year = int(raw_year)
    except (TypeError, ValueError):
        normalized_year = raw_year
    record = {
        "poi_id": _text(value.get("poi_id") or value.get("id") or value.get("uid")),
        "name": _text(value.get("name")),
        **semantics,
        "address": _text(value.get("address")),
        "location": _location(value.get("location")),
        "year": normalized_year,
        "source": _text(value.get("source") or source),
    }
    validate_complete_poi_record(record)
    return record


def validate_complete_poi_record(value: Any) -> None:
    if not isinstance(value, dict):
        raise PoiRecordContractError("poi_record_must_be_object")
    missing = [field for field in POI_RECORD_FIELDS if field not in value]
    if missing:
        raise PoiRecordContractError("poi_record_missing_fields:" + ",".join(missing))

    required_text = ("poi_id", "name", "category", "subcategory", "typecode", "source")
    empty = [field for field in required_text if not _text(value.get(field))]
    if empty:
        raise PoiRecordContractError("poi_record_empty_fields:" + ",".join(empty))
    if normalize_typecode(value.get("category")) == _text(value.get("category")):
        raise PoiRecordContractError("poi_category_must_be_named")
    if len(normalize_typecode(value.get("typecode"))) != 6:
        raise PoiRecordContractError("poi_typecode_invalid")
    if _location(value.get("location")) is None:
        raise PoiRecordContractError("poi_location_invalid")
    try:
        int(value.get("year"))
    except (TypeError, ValueError):
        raise PoiRecordContractError("poi_year_invalid") from None
    if not isinstance(value.get("address"), str):
        raise PoiRecordContractError("poi_address_must_be_string")


def validate_complete_poi_records(
    records: Any,
    *,
    year: Any,
    source: Any,
) -> None:
    if not isinstance(records, list):
        raise PoiRecordContractError("poi_records_must_be_array")
    expected_source = _text(source)
    try:
        expected_year = int(year)
    except (TypeError, ValueError):
        expected_year = year
    seen: set[str] = set()
    for record in records:
        validate_complete_poi_record(record)
        poi_id = _text(record.get("poi_id"))
        if poi_id in seen:
            raise PoiRecordContractError(f"poi_id_duplicate:{poi_id}")
        seen.add(poi_id)
        if record.get("year") != expected_year:
            raise PoiRecordContractError(f"poi_year_mismatch:{poi_id}")
        if _text(record.get("source")) != expected_source:
            raise PoiRecordContractError(f"poi_source_mismatch:{poi_id}")
