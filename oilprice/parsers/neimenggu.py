from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


WEST_MARKER = "附表1"
EAST_MARKER = "附表2"
WEST_TABLE_START_RE = re.compile(r"附表1\s*内蒙古自治区西部价区汽、柴油最高批发、零售价格表")
EAST_TABLE_START_RE = re.compile(r"附表2\s*内蒙古自治区东部价区汽、柴油最高批发、零售价格表")
SECTION_END_MARKERS = ("注：", "信息来源", "打印", "关闭")
MODEL_MARKERS = ("89号", "92号", "95号", "0号", "-10号", "-20号", "-35号")
NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    base_prices = result.get("extracted_prices")
    prices: dict[str, float] = dict(base_prices) if isinstance(base_prices, dict) else {}

    normalized = _normalize_text(text)
    zones = _extract_zones(normalized)
    if zones:
        prices.update(zones[0]["items"])
    if not prices:
        return {"confidence": "manual_required"}

    payload: dict[str, object] = {
        "extracted_prices": prices,
        "confidence": "low",
    }
    if zones:
        payload["extracted_zones"] = zones
        if all(all(product in zone["items"] for product in PRODUCT_ORDER) for zone in zones):
            payload["confidence"] = "medium"
    else:
        payload["extracted_zones"] = [
            {
                "zone_code": "default",
                "zone_name": "默认价区",
                "items": {key: prices[key] for key in PRODUCT_ORDER if key in prices},
            }
        ]
    return payload


def _extract_zones(text: str) -> list[dict[str, object]]:
    west_section, east_section = _table_sections(text)
    zones: list[dict[str, object]] = []

    west_items = _extract_zone_items(west_section)
    if west_items:
        zones.append({"zone_code": "west", "zone_name": "西部价区", "items": west_items})

    east_items = _extract_zone_items(east_section)
    if east_items:
        zones.append({"zone_code": "east", "zone_name": "东部价区", "items": east_items})
    return zones


def _table_sections(text: str) -> tuple[str, str]:
    west_match = WEST_TABLE_START_RE.search(text)
    east_match = EAST_TABLE_START_RE.search(text)
    if west_match and east_match and west_match.start() < east_match.start():
        return text[west_match.start() : east_match.start()], _slice_from(text[east_match.start() :], EAST_MARKER)
    return _slice_between(text, WEST_MARKER, EAST_MARKER), _slice_from(text, EAST_MARKER)


def _extract_zone_items(section: str) -> dict[str, float]:
    if not section:
        return {}
    items: dict[str, float] = {}
    for product, marker in (("89", "89号"), ("92", "92号"), ("95", "95号"), ("0", "0号")):
        liter = _extract_liter_value(section, marker)
        if liter is not None:
            items[product] = liter
    return items


def _extract_liter_value(section: str, marker: str) -> float | None:
    index = section.find(marker)
    if index < 0:
        return None
    end = len(section)
    for next_marker in MODEL_MARKERS:
        next_index = section.find(next_marker, index + len(marker))
        if next_index >= 0:
            end = min(end, next_index)
    segment = section[index:end]
    for raw in NUMBER_RE.findall(segment):
        if "." not in raw:
            continue
        value = float(raw)
        if 0 < value < 30:
            return value
    return None


def _slice_between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        return ""
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        return text[start:]
    return text[start:end]


def _slice_from(text: str, start_marker: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        return ""
    tail = text[start:]
    for marker in SECTION_END_MARKERS:
        end = tail.find(marker)
        if end > 0:
            return tail[:end]
    return tail


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[ \t\f\v]+", " ", text)
