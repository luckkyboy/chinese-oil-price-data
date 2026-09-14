from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER


_ROW_PATTERN = re.compile(
    r"(?P<label>(?<![0-9+-])(?P<product>89|92|95|0)\s*号\s*(?:汽油|柴油))"
    r".*?元\s*/\s*升\s*(?P<price>[0-9]+(?:\.[0-9]+)?)",
    re.DOTALL,
)


def parse_notice(text: str) -> dict[str, object]:
    """Parse Shanghai's two-row-per-product HTML price table.

    The notice repeats 89/0 prices in the narrative before the table. Parsing
    the table row up to its 元/升 value avoids accidentally treating those
    wholesale prices as liter prices.
    """
    prices: dict[str, float] = {}
    for match in _ROW_PATTERN.finditer(text):
        product = match.group("product")
        # The narrative repeats 89/0 ton prices before the table. Keep the
        # last table match when a product occurs more than once.
        prices[product] = float(match.group("price"))

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
        "confidence": "high" if len(prices) == len(PRODUCT_ORDER) else "medium",
    }
