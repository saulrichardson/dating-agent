from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree


@dataclass(frozen=True)
class UiXmlNodeMatch:
    class_name: Optional[str]
    resource_id: Optional[str]
    text: Optional[str]
    content_desc: Optional[str]
    bounds: Optional[tuple[int, int, int, int]]


_BOUNDS_RE = re.compile(r"\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]")


def parse_bounds(bounds_str: str) -> Optional[tuple[int, int, int, int]]:
    """
    Parse Android UIAutomator bounds string: "[x1,y1][x2,y2]".
    Returns (x1, y1, x2, y2) or None if parse fails.
    """
    match = _BOUNDS_RE.search(bounds_str)
    if not match:
        return None
    x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
    return x1, y1, x2, y2


def search_uiautomator_xml(
    page_source_xml: str,
    *,
    query: str,
    limit: int = 30,
) -> list[UiXmlNodeMatch]:
    """
    Search an Appium `/source` UIAutomator XML dump for nodes that contain `query`
    in any of: text, content-desc, resource-id, class name.

    This is a locator-discovery helper for prototyping (e.g., Hinge), not a runtime strategy.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    if not page_source_xml.strip():
        return []

    try:
        root = ElementTree.fromstring(page_source_xml)
    except Exception as e:
        raise ValueError(f"Failed to parse page source XML: {e}") from e

    q = query.strip().lower()
    matches: list[UiXmlNodeMatch] = []

    for el in root.iter():
        if len(matches) >= limit:
            break

        attrib = el.attrib or {}
        class_name = attrib.get("class") or None
        resource_id = attrib.get("resource-id") or None
        text = attrib.get("text") or None
        content_desc = attrib.get("content-desc") or None
        bounds = parse_bounds(attrib.get("bounds", "")) if attrib.get("bounds") else None

        haystack = " ".join(
            [
                (class_name or ""),
                (resource_id or ""),
                (text or ""),
                (content_desc or ""),
            ]
        ).lower()

        if q in haystack:
            matches.append(
                UiXmlNodeMatch(
                    class_name=class_name,
                    resource_id=resource_id,
                    text=text,
                    content_desc=content_desc,
                    bounds=bounds,
                )
            )

    return matches


def suggest_locator(node: UiXmlNodeMatch) -> Optional[tuple[str, str]]:
    """
    Suggest a locator (using, value) for an XML node match.
    """
    if node.resource_id:
        return "id", node.resource_id
    if node.content_desc:
        return "accessibility id", node.content_desc
    if node.text:
        # UiAutomator selector is often convenient for prototyping.
        safe = node.text.replace('"', '\\"')
        return "-android uiautomator", f'new UiSelector().textContains("{safe}")'
    return None

