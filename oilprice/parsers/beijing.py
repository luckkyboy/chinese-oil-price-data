from __future__ import annotations

from oilprice.extract.price_parser import PRODUCT_ORDER, extract_prices


def parse_notice(text: str) -> dict[str, object]:
    prices = extract_prices(text)
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
        "confidence": "high" if {"89", "92", "95", "0"}.issubset(prices) else "medium",
    }
