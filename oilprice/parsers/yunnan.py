from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


LITER_ROW_RE = re.compile(r"[0-9]+\.[0-9]+")
ZONE_NAMES = ["一价区", "二价区", "三价区", "四价区", "五价区", "六价区", "七价区"]


def parse_notice(text: str) -> dict[str, object]:
    zones = _extract_zone_rows(text)
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


def _extract_zone_rows(text: str) -> list[dict[str, object]]:
    zones: list[dict[str, object]] = []
    lines = _normalize_text(text).splitlines()

    for line in lines:
        row = line.strip()
        if not row:
            continue
        decimals = [float(raw) for raw in LITER_ROW_RE.findall(row) if 5.0 < float(raw) < 15.0]
        if len(decimals) < 4:
            continue
        liters = decimals[-4:]
        zone_index = len(zones)
        zone_name = ZONE_NAMES[zone_index] if zone_index < len(ZONE_NAMES) else f"{zone_index + 1}价区"
        zones.append(
            {
                "zone_code": f"yunnan-{zone_index + 1}",
                "zone_name": zone_name,
                "items": {
                    "89": liters[0],
                    "92": liters[1],
                    "95": liters[2],
                    "0": liters[3],
                },
            }
        )
    return zones


def _normalize_text(text: str) -> str:
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _is_complete(items: dict[str, float]) -> bool:
    return all(key in items for key in PRODUCT_ORDER)
