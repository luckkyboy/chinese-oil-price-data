from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


ROW_PATTERNS = {
    "89": re.compile(
        r"89\s*号车用汽油[^\n]*\n\s*([0-9]{4,6}(?:\.[0-9]+)?)\s*\n\s*([0-9]+(?:\.[0-9]+)?)"
    ),
    "92": re.compile(
        r"92\s*号车用汽油[^\n]*\n\s*([0-9]{4,6}(?:\.[0-9]+)?)\s*\n\s*([0-9]+(?:\.[0-9]+)?)"
    ),
    "95": re.compile(
        r"95\s*号车用汽油[^\n]*\n\s*([0-9]{4,6}(?:\.[0-9]+)?)\s*\n\s*([0-9]+(?:\.[0-9]+)?)"
    ),
    "0": re.compile(
        r"0\s*号车用柴油[^\n]*\n\s*([0-9]{4,6}(?:\.[0-9]+)?)\s*\n\s*([0-9]+(?:\.[0-9]+)?)"
    ),
}


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    base_prices = result.get("extracted_prices")
    prices: dict[str, float] = dict(base_prices) if isinstance(base_prices, dict) else {}

    normalized = _normalize_text(text)
    table_prices = _extract_prices_from_table(normalized)
    prices.update(table_prices)
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


def _extract_prices_from_table(text: str) -> dict[str, float]:
    prices: dict[str, float] = {}
    for product, pattern in ROW_PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        # group(1) is ton price, group(2) is liter price.
        prices[product] = float(match.group(2))
    return prices


def _normalize_text(text: str) -> str:
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse wide spaces and preserve line structure for table row parsing.
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines)
