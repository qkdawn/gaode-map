from __future__ import annotations

from typing import Any, Iterable


def normalize_year(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if 1000 <= year <= 9999 else None


def available_business_years(values: Iterable[Any]) -> list[int]:
    return sorted({year for value in values if (year := normalize_year(value)) is not None})


def resolve_business_year(available_years: Iterable[Any], requested: Any = None) -> int | None:
    requested_year = normalize_year(requested)
    if requested_year is not None:
        return requested_year
    years = available_business_years(available_years)
    return years[-1] if years else None
