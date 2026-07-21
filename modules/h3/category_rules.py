from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.poi_taxonomy import get_poi_taxonomy, normalize_typecode

CategoryKey = str
CategoryRule = Tuple[CategoryKey, str, Tuple[str, ...]]

def build_category_rules() -> List[CategoryRule]:
    """Expose the legacy H3 rule shape from the shared taxonomy resolver."""

    rules = get_poi_taxonomy().category_rules()
    if rules:
        return rules
    return [
        ("group-7", "餐饮", ("05",)),
        ("group-6", "购物", ("06",)),
        ("group-4", "商务住宅", ("12",)),
        ("group-3", "交通", ("15",)),
        ("group-2", "旅游", ("11",)),
        ("group-13", "科教文化", ("14",)),
        ("group-10", "医疗", ("09",)),
    ]


CATEGORY_RULES: List[CategoryRule] = build_category_rules()
CATEGORY_KEYS: Tuple[str, ...] = tuple(item[0] for item in CATEGORY_RULES)
_TYPECODE_TO_CATEGORY: Dict[str, str] = {}
_PREFIX2_TO_CATEGORY: Dict[str, str] = {}
for category_key, _label, typecodes in CATEGORY_RULES:
    for code in typecodes:
        _TYPECODE_TO_CATEGORY.setdefault(code, category_key)
        if len(code) >= 2:
            _PREFIX2_TO_CATEGORY.setdefault(code[:2], category_key)


def empty_category_counts() -> Dict[CategoryKey, int]:
    return {key: 0 for key in CATEGORY_KEYS}


def infer_category_key(type_text: Optional[str]) -> Optional[CategoryKey]:
    if not type_text:
        return None
    code = normalize_typecode(type_text)
    if len(code) < 2:
        return None
    if code in _TYPECODE_TO_CATEGORY:
        return _TYPECODE_TO_CATEGORY[code]
    return _PREFIX2_TO_CATEGORY.get(code[:2])
