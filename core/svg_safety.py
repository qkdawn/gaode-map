"""SVG security boundary for externally produced report assets."""

from __future__ import annotations

import base64
import re
from xml.etree import ElementTree

URL_PATTERN = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_MAX_INLINE_PNG_BYTES = 1_500_000


def validate_safe_svg(svg: str) -> None:
    """Reject active content, external resources, and malformed SVG."""
    if not isinstance(svg, str) or not svg.strip():
        raise ValueError("report visual SVG must be a non-empty string")
    lowered = svg.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("report visual SVG must not contain document type or entity declarations")
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("report visual SVG is not well-formed XML") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise ValueError("report visual SVG root element must be svg")
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in {"script", "foreignobject"}:
            raise ValueError(f"report visual SVG contains forbidden element: {tag}")
        if tag == "style":
            _validate_reference_text(element.text or "")
        for raw_name, raw_value in element.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].lower()
            value = str(raw_value or "").strip()
            if name.startswith("on"):
                raise ValueError(f"report visual SVG contains forbidden event handler: {name}")
            if name in {"href", "src"} and value and not value.startswith("#"):
                _validate_embedded_png(value)
                continue
            _validate_reference_text(value)


def _validate_embedded_png(value: str) -> None:
    if not value.startswith("data:image/png;base64,"):
        raise ValueError("report visual SVG contains an external or unsupported image")
    encoded = value.split(",", 1)[1]
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("report visual SVG image data is malformed") from exc
    if not decoded.startswith(b"\x89PNG\r\n\x1a\n") or len(decoded) > _MAX_INLINE_PNG_BYTES:
        raise ValueError("report visual SVG image data is not an approved PNG")


def _validate_reference_text(value: str) -> None:
    lowered = value.lower()
    if "@import" in lowered:
        raise ValueError("report visual SVG contains an external style import")
    if re.search(r"(^|[\s:'\"(])(?:https?:|file:|data:|//)", lowered):
        raise ValueError("report visual SVG contains an external resource reference")
    for match in URL_PATTERN.finditer(value):
        if not match.group(2).strip().startswith("#"):
            raise ValueError("report visual SVG contains an external URL reference")
