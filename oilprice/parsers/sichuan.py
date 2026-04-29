from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from oilprice.extract.price_parser import PRODUCT_ORDER


ZONE_DEFS = [
    ("sichuan-1", "一价区"),
    ("sichuan-2", "二价区"),
    ("sichuan-3", "三价区"),
]
PRODUCT_MARKERS = {
    "89": re.compile(r"(?:^|\n)\s*89\s*[#﹟号]?\s*(?:乙醇)?汽油", re.MULTILINE),
    "92": re.compile(r"(?:^|\n)\s*92\s*[#﹟号]?\s*(?:乙醇)?汽油", re.MULTILINE),
    "95": re.compile(r"(?:^|\n)\s*95\s*[#﹟号]?\s*(?:乙醇)?汽油", re.MULTILINE),
    "0": re.compile(r"(?:^|\n|；|;)\s*0\s*[#﹟号]?\s*(?:车用)?柴油", re.MULTILINE),
}
ANY_PRODUCT_MARKER = re.compile(
    r"(?:^|\n|；|;)\s*(?:89|92|95|0|﹣\s*10|-\s*10|﹣\s*20|-\s*20|﹣\s*35|-\s*35)\s*[#﹟号]?\s*(?:(?:乙醇)?汽油|(?:车用)?柴油)",
    re.MULTILINE,
)
NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def parse_notice(text: str) -> dict[str, object]:
    zone_items = {zone_code: {} for zone_code, _ in ZONE_DEFS}

    for product, pattern in PRODUCT_MARKERS.items():
        match = pattern.search(text)
        if not match:
            continue
        liter_prices = _liter_prices(_product_segment(text, match.start(), match.end()))
        for (zone_code, _), price in zip(ZONE_DEFS, liter_prices[: len(ZONE_DEFS)]):
            zone_items[zone_code][product] = float(price)

    zones = [
        {
            "zone_code": zone_code,
            "zone_name": zone_name,
            "items": {key: zone_items[zone_code][key] for key in PRODUCT_ORDER if key in zone_items[zone_code]},
        }
        for zone_code, zone_name in ZONE_DEFS
        if zone_items[zone_code]
    ]

    if not zones:
        return {"confidence": "manual_required"}

    first_zone_prices = zones[0]["items"]
    return {
        "extracted_prices": first_zone_prices,
        "extracted_zones": zones,
        "confidence": "high" if len(zones) == len(ZONE_DEFS) else "medium",
    }


def _product_segment(text: str, start: int, marker_end: int) -> str:
    next_match = ANY_PRODUCT_MARKER.search(text, marker_end)
    end = next_match.start() if next_match else len(text)
    return text[start:end]


def _liter_prices(segment: str) -> list[Decimal]:
    values: list[Decimal] = []
    for raw_value in NUMBER_RE.findall(segment):
        if "." not in raw_value:
            continue
        try:
            value = Decimal(raw_value)
        except InvalidOperation:
            continue
        if Decimal("0") < value < Decimal("30"):
            values.append(value)
    return values
