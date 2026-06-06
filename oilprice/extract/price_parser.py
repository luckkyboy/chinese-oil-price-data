from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


PRODUCT_ORDER = ["89", "92", "95", "0"]
_VIB_SUFFIX = r"(?:VIB\b|VI\b|(?:乙醇)?汽油)"
_DIESEL_SUFFIX = r"(?:VI\b|(?:车用)?柴油)"
PRODUCT_MARKERS = {
    "89": re.compile(rf"(?<![0-9])89\s*[#﹟号]?\s*{_VIB_SUFFIX}", re.MULTILINE),
    "92": re.compile(rf"(?<![0-9])92\s*[#﹟号]?\s*{_VIB_SUFFIX}", re.MULTILINE),
    "95": re.compile(rf"(?<![0-9])95\s*[#﹟号]?\s*{_VIB_SUFFIX}", re.MULTILINE),
    "0": re.compile(rf"(?<![0-9+-])0\s*[#﹟号]?\s*{_DIESEL_SUFFIX}", re.MULTILINE),
}
ANY_PRODUCT_MARKER = re.compile(
    r"(?<![0-9])(?:(?:89|92|95)\s*[#﹟号]?\s*(?:(?:乙醇)?汽油|VIB\b)|"
    r"(?:0|﹣\s*10|-\s*10|﹣\s*20|-\s*20|﹣\s*35|-\s*35)\s*[#﹟号]?\s*(?:(?:车用)?柴油|VI\b))",
    re.MULTILINE,
)
NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
ADJUSTED_TO_PRICE_RE = re.compile(r"调整为\s*(?:每升)?\s*([0-9]+(?:\.[0-9]+)?)\s*元")


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
    adjusted_to = ADJUSTED_TO_PRICE_RE.search(segment)
    if adjusted_to:
        value = _decimal_liter_price(adjusted_to.group(1))
        if value is not None:
            return value

    for raw_value in NUMBER_RE.findall(segment):
        value = _decimal_liter_price(raw_value)
        if value is not None:
            return value
    return None


def _decimal_liter_price(raw_value: str) -> Decimal | None:
    if "." not in raw_value:
        return None
    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        return None
    if Decimal("0") < value < Decimal("30"):
        return value
    return None
