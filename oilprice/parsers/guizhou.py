from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


ZONE_CODE_MAP = {
    "一价区": "guizhou-1",
    "二价区": "guizhou-2",
    "三价区": "guizhou-3",
}
ZONE_ORDER = ["一价区", "二价区", "三价区"]
ZONE_BLOCK_RE = re.compile(r"(一价区|二价区|三价区)(.*?)(?=一价区|二价区|三价区|说明[：:]|$)", re.DOTALL)
NUMBER_RE = re.compile(r"[0-9]+\.[0-9]+")
GASOLINE_TABLE_RE = re.compile(r"[^\n。]{0,80}汽油[^\n。]{0,80}价格表")
DIESEL_TABLE_RE = re.compile(r"[^\n。]{0,80}柴油[^\n。]{0,80}价格表")


def parse_notice(text: str) -> dict[str, object]:
    zones = _extract_zones(_normalize_ocr_text(text))
    if zones:
        first_zone_items = zones[0]["items"]
        prices = {key: first_zone_items[key] for key in PRODUCT_ORDER if key in first_zone_items}
        return {
            "extracted_prices": prices,
            "extracted_zones": zones,
            "confidence": "medium" if all(_is_complete_zone(zone["items"]) for zone in zones) else "low",
        }

    result = parse_generic_notice(text)
    if not result.get("extracted_prices"):
        return {"confidence": "manual_required"}
    return result


def _extract_zones(text: str) -> list[dict[str, object]]:
    gasoline_section, diesel_section = _table_sections(text)
    if not gasoline_section or not diesel_section:
        return []

    gasoline_prices = _extract_gasoline_zone_prices(gasoline_section)
    diesel_prices = _extract_diesel_zone_prices(diesel_section)
    zones: list[dict[str, object]] = []

    for zone_name in ZONE_ORDER:
        items: dict[str, float] = {}
        gas = gasoline_prices.get(zone_name, {})
        for key in ("89", "92", "95"):
            if key in gas:
                items[key] = gas[key]
        diesel = diesel_prices.get(zone_name)
        if diesel is not None:
            items["0"] = diesel
        if not items:
            continue
        zones.append(
            {
                "zone_code": ZONE_CODE_MAP[zone_name],
                "zone_name": zone_name,
                "items": items,
            }
        )
    return zones


def _table_sections(text: str) -> tuple[str, str]:
    """Return gasoline and diesel table text without relying on attachment numbers."""

    gasoline_start = _table_start(text, GASOLINE_TABLE_RE, "附表1")
    diesel_start = _table_start(text, DIESEL_TABLE_RE, "附表2")
    if gasoline_start is None or diesel_start is None or gasoline_start >= diesel_start:
        return "", ""
    return text[gasoline_start:diesel_start], text[diesel_start:]


def _table_start(text: str, header_pattern: re.Pattern[str], legacy_marker: str) -> int | None:
    match = header_pattern.search(text)
    if match:
        return match.start()
    marker = text.find(legacy_marker)
    return marker if marker >= 0 else None


def _normalize_ocr_text(text: str) -> str:
    text = text.replace("＃", "#").replace("﹟", "#")
    text = text.replace("O号", "0号").replace("０号", "0号")
    text = text.replace("正5号", "+5号")
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _extract_gasoline_zone_prices(section: str) -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = {}
    for zone_name, block in ZONE_BLOCK_RE.findall(section):
        values = _decimal_values(block)
        if len(values) < 3:
            continue
        prices[zone_name] = {
            "89": values[0],
            "92": values[1],
            "95": values[2],
        }
    return prices


def _extract_diesel_zone_prices(section: str) -> dict[str, float]:
    prices: dict[str, float] = {}
    for zone_name, block in ZONE_BLOCK_RE.findall(section):
        values = _decimal_values(block)
        if not values:
            continue
        prices[zone_name] = values[0]
    return prices


def _decimal_values(text: str) -> list[float]:
    values: list[float] = []
    for raw in NUMBER_RE.findall(text):
        value = float(raw)
        if 5.0 < value < 15.0:
            values.append(value)
    return values


def _is_complete_zone(items: dict[str, float]) -> bool:
    return all(key in items for key in PRODUCT_ORDER)
