from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


GAS_ZONE_NAMES = ("中北部价区", "陕南价区")
DIESEL_ZONE_NAMES = ("西安市区", "其他价区")
GAS_ZONE_BLOCK_RE = re.compile(
    r"(中北部价区|陕南价区)(.*?)(?=中北部价区|陕南价区|$)",
    re.DOTALL,
)
DIESEL_ZONE_BLOCK_RE = re.compile(
    r"(西安市区|其他价区)(.*?)(?=西安市区|其他价区|$)",
    re.DOTALL,
)
ZONE_COMBINATIONS = (
    ("shaanxi-1", "中北部价区（西安市区）", "中北部价区", "西安市区"),
    ("shaanxi-2", "陕南价区", "陕南价区", "其他价区"),
    ("shaanxi-3", "中北部价区（西安市区外）", "中北部价区", "其他价区"),
)
NUMBER_RE = re.compile(r"[0-9]+\.[0-9]+")


def parse_notice(text: str) -> dict[str, object]:
    zones = _extract_zones(_normalize_text(text))
    if zones:
        first_items = zones[0]["items"]
        prices = {key: first_items[key] for key in PRODUCT_ORDER if key in first_items}
        return {
            "extracted_prices": prices,
            "extracted_zones": zones,
            "confidence": "medium" if all(_is_complete(zone["items"]) for zone in zones) else "low",
        }

    result = parse_generic_notice(text)
    if not result.get("extracted_prices"):
        return {"confidence": "manual_required"}
    return result


def _extract_zones(text: str) -> list[dict[str, object]]:
    gas_section, diesel_section = _split_sections(text)
    if not gas_section or not diesel_section:
        return []

    gas_prices = _extract_zone_rows(gas_section, GAS_ZONE_BLOCK_RE, value_count=3)
    diesel_prices = _extract_zone_rows(diesel_section, DIESEL_ZONE_BLOCK_RE, value_count=4)
    if any(zone_name not in gas_prices for zone_name in GAS_ZONE_NAMES) or any(
        zone_name not in diesel_prices for zone_name in DIESEL_ZONE_NAMES
    ):
        return []

    zones: list[dict[str, object]] = []
    for zone_code, zone_name, gas_zone_name, diesel_zone_name in ZONE_COMBINATIONS:
        gas_values = gas_prices[gas_zone_name]
        diesel_values = diesel_prices[diesel_zone_name]
        items = {
            "89": gas_values[0],
            "92": gas_values[1],
            "95": gas_values[2],
            "0": diesel_values[0],
        }
        zones.append(
            {
                "zone_code": zone_code,
                "zone_name": zone_name,
                "items": items,
                "note": f"汽油对应：{gas_zone_name}；柴油对应：{diesel_zone_name}",
            }
        )
    return zones


def _extract_zone_rows(
    section: str,
    pattern: re.Pattern[str],
    *,
    value_count: int,
) -> dict[str, list[float]]:
    rows: dict[str, list[float]] = {}
    for zone_name, block in pattern.findall(section):
        values = _decimal_values(block)
        if len(values) >= value_count and zone_name not in rows:
            rows[zone_name] = values[:value_count]
    return rows


def _split_sections(text: str) -> tuple[str, str]:
    gas_match = re.search(r"汽\s*油", text)
    if not gas_match:
        return "", ""
    diesel_match = re.search(r"柴\s*油", text[gas_match.end() :])
    if not diesel_match:
        return "", ""
    diesel_start = gas_match.end() + diesel_match.start()
    return text[gas_match.start() : diesel_start], text[diesel_start:]


def _normalize_text(text: str) -> str:
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("O号", "0号").replace("０号", "0号")
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _decimal_values(text: str) -> list[float]:
    values: list[float] = []
    for raw in NUMBER_RE.findall(text):
        value = float(raw)
        if 5.0 < value < 15.0:
            values.append(value)
    return values


def _is_complete(items: dict[str, float]) -> bool:
    return all(key in items for key in PRODUCT_ORDER)
