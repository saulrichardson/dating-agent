from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree


@dataclass(frozen=True)
class AccessibilityNode:
    class_name: Optional[str]
    resource_id: Optional[str]
    text: Optional[str]
    content_desc: Optional[str]


def extract_accessibility_nodes(page_source_xml: str, *, limit: int = 500) -> list[AccessibilityNode]:
    """
    Extract a lightweight "accessibility-ish" view of the current screen from
    Android's UIAutomator XML (Appium /source).

    This does NOT attempt to infer message direction or UI structure.
    It's a quick way to validate "is the text accessible at all?" before we
    invest in app-specific locators.
    """
    if not page_source_xml.strip():
        return []

    try:
        root = ElementTree.fromstring(page_source_xml)
    except Exception as e:
        raise ValueError(f"Failed to parse page source XML: {e}") from e

    nodes: list[AccessibilityNode] = []
    for el in root.iter():
        if len(nodes) >= limit:
            break

        attrib = el.attrib or {}
        class_name = attrib.get("class")
        resource_id = attrib.get("resource-id")
        text = attrib.get("text")
        content_desc = attrib.get("content-desc")

        nodes.append(
            AccessibilityNode(
                class_name=class_name or None,
                resource_id=resource_id or None,
                text=text or None,
                content_desc=content_desc or None,
            )
        )

    return nodes


def extract_accessible_strings(page_source_xml: str, *, limit: int = 500) -> list[str]:
    """
    Return a de-duplicated, ordered list of visible/accessible strings
    (from `text` and `content-desc`) on the current screen.
    """
    nodes = extract_accessibility_nodes(page_source_xml, limit=limit)

    seen: set[str] = set()
    out: list[str] = []
    for node in nodes:
        for candidate in (node.text, node.content_desc):
            if not candidate:
                continue
            normalized = candidate.strip()
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
    return out

