from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def extract_ui_elements(page_source: str, *, limit: int = 80) -> list[dict[str, str]]:
    root = ET.fromstring(page_source)
    elements: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for node in root.iter():
        item = _element_from_node(node.attrib)
        if item is None:
            continue
        key = (item.get("selector", ""), item.get("text", ""), item.get("class_name", ""), item.get("bounds", ""))
        if key in seen:
            continue
        seen.add(key)
        elements.append(item)
        if len(elements) >= limit:
            break

    return elements


def _element_from_node(attrs: dict[str, Any]) -> dict[str, str] | None:
    if _attr(attrs, "displayed") == "false" or _attr(attrs, "enabled") == "false":
        return None

    text = _clean(_attr(attrs, "text"))
    resource_id = _clean(_attr(attrs, "resource-id", "resourceId"))
    content_desc = _clean(_attr(attrs, "content-desc", "contentDescription"))
    class_name = _clean(_attr(attrs, "class"))
    bounds = _clean(_attr(attrs, "bounds"))
    clickable = _attr(attrs, "clickable") == "true"
    focusable = _attr(attrs, "focusable") == "true"
    input_like = "EditText" in class_name

    if not (text or resource_id or content_desc):
        return None
    if not (clickable or focusable or input_like or _is_common_target(class_name, text)):
        return None

    selector = _best_selector(resource_id, content_desc)
    label = text or content_desc or _short_resource_id(resource_id) or _short_class_name(class_name)
    item = {
        "label": label,
        "selector": selector,
        "text": text,
        "resource_id": resource_id,
        "accessibility_id": content_desc,
        "class_name": class_name,
        "bounds": bounds,
        "role": _role(class_name, clickable, input_like),
        "confidence": _confidence(selector, text),
    }
    return {key: value for key, value in item.items() if value}


def _best_selector(resource_id: str, content_desc: str) -> str:
    if resource_id:
        return f"id={resource_id}"
    if content_desc:
        return f"accessibility_id={content_desc}"
    return ""


def _confidence(selector: str, text: str) -> str:
    if selector:
        return "high"
    if text:
        return "text"
    return "low"


def _role(class_name: str, clickable: bool, input_like: bool) -> str:
    if input_like:
        return "input"
    if "Button" in class_name:
        return "button"
    if "CheckBox" in class_name or "Switch" in class_name:
        return "toggle"
    if clickable:
        return "tap target"
    if "TextView" in class_name:
        return "text"
    return "element"


def _is_common_target(class_name: str, text: str) -> bool:
    if text and "TextView" in class_name:
        return True
    return any(
        marker in class_name
        for marker in (
            "Button",
            "CheckBox",
            "EditText",
            "ImageButton",
            "RadioButton",
            "Spinner",
            "Switch",
        )
    )


def _attr(attrs: dict[str, Any], *names: str) -> str:
    for name in names:
        value = attrs.get(name)
        if value is not None:
            return str(value)
    return ""


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _short_resource_id(resource_id: str) -> str:
    return resource_id.rsplit("/", 1)[-1] if resource_id else ""


def _short_class_name(class_name: str) -> str:
    return class_name.rsplit(".", 1)[-1] if class_name else ""
