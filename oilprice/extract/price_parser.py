from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


PRODUCT_ORDER = ["89", "92", "95", "0"]
PRODUCT_MARKERS = {
    "89": re.compile(r"(?:^|\n)\s*89\s*[#﹟号]?\s*(?:乙醇)?汽油", re.MULTILINE),
    "92": re.compile(r"(?:^|\n)\s*92\s*[#﹟号]?\s*(?:乙醇)?汽油", re.MULTILINE),
    "95": re.compile(r"(?:^|\n)\s*95\s*[#﹟号]?\s*(?:乙醇)?汽油", re.MULTILINE),
    "0": re.compile(r"(?:^|\n)\s*0\s*[#﹟号]?\s*(?:车用)?柴油", re.MULTILINE),
}
ANY_PRODUCT_MARKER = re.compile(
    r"(?:^|\n|；|;)\s*(?:89|92|95|0|﹣\s*10|-\s*10|﹣\s*20|-\s*20|﹣\s*35|-\s*35)\s*[#﹟号]?\s*(?:(?:乙醇)?汽油|(?:车用)?柴油)",
    re.MULTILINE,
)
NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def extract_prices(text: str) -> dict[str, float]:
    prices: dict[str, float] = {}
    for product, pattern in PRODUCT_MARKERS.items():
        match = pattern.search(text)
        if not match:
            continue
        segment = _product_segment(text, match.start(), match.end())
        value = _first_liter_price(segment)
        if value is not None:
            prices[product] = float(value)
    return prices


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
