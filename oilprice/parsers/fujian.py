from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


PRODUCT_MARKERS = {
    "89": re.compile(r"(?:^|\n)\s*车用?\s*89\s*号\s*汽油", re.MULTILINE),
    "92": re.compile(r"(?:^|\n)\s*车用?\s*92\s*号\s*汽油", re.MULTILINE),
    "95": re.compile(r"(?:^|\n)\s*车用?\s*95\s*号\s*汽油", re.MULTILINE),
    "0": re.compile(r"(?:^|\n)\s*车用?\s*0\s*号\s*柴油", re.MULTILINE),
}
ANY_PRODUCT_MARKER = re.compile(
    r"(?:^|\n)\s*车用?\s*(?:89|92|95|0|-10)\s*号\s*(?:汽油|柴油)",
    re.MULTILINE,
)
NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    if result.get("extracted_prices"):
        return result

    prices: dict[str, float] = {}
    for product, pattern in PRODUCT_MARKERS.items():
        match = pattern.search(text)
        if not match:
            continue
        segment = _product_segment(text, match.start(), match.end())
        value = _first_liter_price(segment)
        if value is not None:
            prices[product] = float(value)

    if not prices:
        return {"confidence": "manual_required"}

    return {
        "extracted_prices": prices,
        "extracted_zones": [
            {
                "zone_code": "default",
                "zone_name": "默认价区",
                "items": {key: prices[key] for key in PRODUCT_ORDER if key in prices},
            }
        ],
        "confidence": "medium" if len(prices) == len(PRODUCT_ORDER) else "low",
    }


def _product_segment(text: str, start: int, marker_end: int) -> str:
    next_match = ANY_PRODUCT_MARKER.search(text, marker_end)
    end = next_match.start() if next_match else len(text)
    return text[start:end]


def _first_liter_price(segment: str) -> Decimal | None:
    for raw_value in NUMBER_RE.findall(segment):
        if "." not in raw_value:
            continue
        try:
            value = Decimal(raw_value)
        except InvalidOperation:
            continue
        if Decimal("0") < value < Decimal("30"):
            return value
    return None
