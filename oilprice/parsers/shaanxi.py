from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


GAS_ZONE_NAME_RE = re.compile(r"(中北部价区|陕南价区)")
DIESEL_ZONE_NAME_RE = re.compile(r"(西安市区|其他价区)")
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

    gas_zone_names = GAS_ZONE_NAME_RE.findall(gas_section)
    diesel_zone_names = DIESEL_ZONE_NAME_RE.findall(diesel_section)
    gas_values = _decimal_values(gas_section)
    diesel_values = _decimal_values(diesel_section)

    if len(gas_zone_names) < 2 or len(gas_values) < 6 or len(diesel_values) < 8:
        return []

    zones: list[dict[str, object]] = []
    for index in range(2):
        items = {
            "89": gas_values[index * 3],
            "92": gas_values[index * 3 + 1],
            "95": gas_values[index * 3 + 2],
            "0": diesel_values[index * 4],
        }
        diesel_zone = diesel_zone_names[index] if index < len(diesel_zone_names) else f"柴油区{index + 1}"
        zones.append(
            {
                "zone_code": f"shaanxi-{index + 1}",
                "zone_name": gas_zone_names[index],
                "items": items,
                "note": f"柴油对应：{diesel_zone}",
            }
        )
    return zones


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
