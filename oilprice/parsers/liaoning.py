from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER, extract_prices
from oilprice.parsers.generic import parse_notice as parse_generic_notice


TON_PRICE_PATTERNS = {
    "89": re.compile(r"汽油标准品\s*([0-9]{4,6})\s*([0-9]{4,6})"),
    "92": re.compile(r"92\s*号车用汽油\s*([0-9]{4,6})\s*([0-9]{4,6})"),
    "95": re.compile(r"95\s*号车用汽油\s*([0-9]{4,6})\s*([0-9]{4,6})"),
    "0": re.compile(r"柴油标准品\s*([0-9]{4,6})\s*([0-9]{4,6})"),
}

# Liaoning notices publish retail prices in CNY/ton. Convert to CNY/L for snapshot consistency.
LITER_CONVERSION = {
    "89": 1339.0,
    "92": 1317.0,
    "95": 1317.0,
    "0": 1158.0,
}


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    if result.get("extracted_prices"):
        return result

    prices = extract_prices(text)
    if not prices:
        prices = _extract_from_ton_prices(text)
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


def _extract_from_ton_prices(text: str) -> dict[str, float]:
    prices: dict[str, float] = {}
    normalized = _normalize_text(text)
    for product, pattern in TON_PRICE_PATTERNS.items():
        match = pattern.search(normalized)
        if not match:
            continue
        ton_price = float(match.group(2))
        liter = ton_price / LITER_CONVERSION[product]
        prices[product] = round(liter, 2)
    return prices


def _normalize_text(text: str) -> str:
    text = text.replace("／", "/")
    text = text.replace("＋", "+").replace("－", "-")
    return re.sub(r"[ \t\r\f\v]+", " ", text)
