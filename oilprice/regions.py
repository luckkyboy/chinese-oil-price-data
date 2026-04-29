from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json


def resolve_zone(region_path: Path, name: str, parent: str | None = None) -> dict[str, Any] | None:
    payload = read_json(region_path)
    normalized_name = _normalize_area_name(name)
    normalized_parent = _normalize_area_name(parent) if parent else None

    # Exact county/city matches should win over broader prefecture rules.
    for zone in payload.get("zones", []):
        for area in zone.get("areas", []):
            if _area_matches(area, normalized_name, normalized_parent):
                return zone

    if normalized_parent:
        for zone in payload.get("zones", []):
            for area in zone.get("areas", []):
                if _parent_area_covers(area, normalized_name, normalized_parent):
                    return zone
    return None


def _area_matches(area: dict[str, Any], name: str, parent: str | None) -> bool:
    area_name = _normalize_area_name(area["name"])
    area_parent = _normalize_area_name(area.get("parent")) if area.get("parent") else None

    if area_name != name:
        return False
    if parent and area_parent and area_parent != parent:
        return False
    return True


def _parent_area_covers(area: dict[str, Any], name: str, parent: str) -> bool:
    if area.get("level") not in {"prefecture", "city"}:
        return False
    if _normalize_area_name(area["name"]) != parent:
        return False
    for excluded in area.get("excludes", []):
        if _area_matches(excluded, name, parent):
            return False
    return True


def _normalize_area_name(value: str | None) -> str:
    if not value:
        return ""
    suffixes = [
        "藏族羌族自治州",
        "彝族自治州",
        "藏族自治州",
        "自治州",
        "地区",
        "市",
        "县",
        "区",
    ]
    normalized = value.strip()
    for suffix in suffixes:
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized
