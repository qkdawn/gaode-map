"""Shared resolver for the project's real POI category taxonomy.

``share/type_map.json`` is the single source of truth for the human-facing
main category and subcategory labels.  Domain modules should resolve typecodes
here rather than parse the configuration independently.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_TYPE_MAP_PATH = Path(__file__).resolve().parents[1] / "share" / "type_map.json"


@dataclass(frozen=True)
class PoiTaxonomyItem:
    group_id: str
    main_category: str
    item_id: str
    subcategory: str
    type_codes: tuple[str, ...]


def normalize_typecode(value: Any) -> str:
    """Return one six-digit POI code when one can be read from *value*."""

    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[:6] if len(digits) >= 6 else digits


class PoiTaxonomyResolver:
    """Resolved, immutable indexes for the checked-in POI taxonomy."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._items: list[PoiTaxonomyItem] = []
        self._by_typecode: dict[str, PoiTaxonomyItem] = {}
        self._by_item_id: dict[str, PoiTaxonomyItem] = {}
        self._by_label: dict[str, PoiTaxonomyItem] = {}
        self._group_codes: dict[str, list[str]] = {}
        for index, group in enumerate(raw.get("groups") or []):
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id") or f"group-{index + 1}").strip()
            main_category = str(group.get("title") or group_id).strip()
            codes_for_group: list[str] = []
            for item_index, item in enumerate(group.get("items") or []):
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or f"{group_id}-item-{item_index + 1}").strip()
                subcategory = str(item.get("label") or item_id).strip()
                codes = tuple(dict.fromkeys(
                    normalized
                    for raw_code in str(item.get("types") or "").split("|")
                    if (normalized := normalize_typecode(raw_code))
                ))
                if not codes:
                    continue
                entry = PoiTaxonomyItem(group_id, main_category, item_id, subcategory, codes)
                self._items.append(entry)
                self._by_item_id.setdefault(item_id, entry)
                self._by_label.setdefault(subcategory, entry)
                for code in codes:
                    self._by_typecode.setdefault(code, entry)
                    codes_for_group.append(code)
            self._group_codes[group_id] = list(dict.fromkeys(codes_for_group))

    @property
    def items(self) -> tuple[PoiTaxonomyItem, ...]:
        return tuple(self._items)

    def resolve_typecode(self, value: Any) -> PoiTaxonomyItem | None:
        return self._by_typecode.get(normalize_typecode(value))

    def resolve_item_or_label(self, value: Any) -> PoiTaxonomyItem | None:
        text = str(value or "").strip()
        return self._by_item_id.get(text) or self._by_label.get(text) or self.resolve_typecode(text)

    def category_rules(self) -> list[tuple[str, str, tuple[str, ...]]]:
        grouped: dict[str, tuple[str, list[str]]] = {}
        for entry in self._items:
            current = grouped.setdefault(entry.group_id, (entry.main_category, []))
            current[1].extend(entry.type_codes)
        return [
            (group_id, label, tuple(dict.fromkeys(codes)))
            for group_id, (label, codes) in grouped.items()
        ]


@lru_cache(maxsize=1)
def get_poi_taxonomy() -> PoiTaxonomyResolver:
    raw = json.loads(_TYPE_MAP_PATH.read_text(encoding="utf-8"))
    return PoiTaxonomyResolver(raw if isinstance(raw, dict) else {})
