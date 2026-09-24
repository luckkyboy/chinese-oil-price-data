from __future__ import annotations

import re
from oilprice.extract.price_parser import extract_prices, normalize_price_text, select_liter_price
from oilprice.parsers.table import merge_prices, single_zone_result


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


def parse_notice(text: str) -> dict[str, object]:
    text = normalize_price_text(text)
    prices: dict[str, float] = {}
    for product, pattern in PRODUCT_MARKERS.items():
        match = pattern.search(text)
        if not match:
            continue
        segment = _product_segment(text, match.start(), match.end())
        value = select_liter_price(segment)
        if value is not None:
            prices[product] = float(value)

    return single_zone_result(merge_prices(extract_prices(text), prices))


def _product_segment(text: str, start: int, marker_end: int) -> str:
    next_match = ANY_PRODUCT_MARKER.search(text, marker_end)
    end = next_match.start() if next_match else len(text)
    return text[start:end]
