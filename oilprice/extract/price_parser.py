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
    r"(?<![0-9])(?:(?:89|92|95|98)\s*[#﹟号]?\s*(?:(?:乙醇)?汽油|VIB?\b)|"
    r"(?:[+-]\s*)?[0-9]{1,2}\s*[#﹟号]?\s*(?:(?:车用)?柴油|VI\b))|"
    r"^\s*(?:89|92|95|98|[+-]?\s*[0-9]{1,2})\s*[#号]?[ \t]*(?=\n|$)",
    re.MULTILINE,
)
NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
ADJUSTED_TO_PRICE_RE = re.compile(r"调整为\s*(?:每升)?\s*([0-9]+(?:\.[0-9]+)?)\s*元")
RETAIL_PRICE_RE = re.compile(
    r"(?:最高零售(?:价格|价)|零售(?:价格|价)|售价|现价)\s*(?:为|是|[:：])?\s*"
    r"(?:每升)?\s*([0-9]+(?:\.[0-9]+)?)\s*元"
)
CHANGE_RE = re.compile(r"上调|下调|上涨|下降|降低|提高|涨幅|降幅|调整幅度|增加|减少|涨价|降价")


def normalize_price_text(text: str) -> str:
    return (text.replace("＃", "#").replace("﹟", "#").replace("／", "/")
            .replace("O#", "0#").replace("０#", "0#")
            .replace("O号", "0号").replace("０号", "0号")
            .replace("﹣", "-").replace("－", "-").replace("＋", "+"))


def extract_prices(text: str) -> dict[str, float]:
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
    return prices


def _product_segment(text: str, start: int, marker_end: int) -> str:
    next_match = ANY_PRODUCT_MARKER.search(text, marker_end)
    end = next_match.start() if next_match else len(text)
    sentence_end = re.search(r"[。；;]", text[marker_end:end])
    if sentence_end:
        end = marker_end + sentence_end.start()
    return text[start:end]


def select_liter_price(segment: str) -> Decimal | None:
    # Explicit current-price labels take precedence over old prices and deltas.
    for pattern in (ADJUSTED_TO_PRICE_RE, RETAIL_PRICE_RE):
        values = {
            value for match in pattern.finditer(segment)
            if (value := _decimal_liter_price(match.group(1), allow_integer=True)) is not None
        }
        if values:
            return next(iter(values)) if len(values) == 1 else None

    # An unlabelled number in a change statement is not evidence of a price.
    if CHANGE_RE.search(segment) or re.search(r"原价|调整前|由\s*[0-9]", segment):
        return None
    values = {
        value for raw in NUMBER_RE.findall(segment)
        if (value := _decimal_liter_price(raw)) is not None
    }
    return next(iter(values)) if len(values) == 1 else None


def _decimal_liter_price(raw_value: str, *, allow_integer: bool = False) -> Decimal | None:
    if not allow_integer and "." not in raw_value:
        return None
    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        return None
    if Decimal("0") < value < Decimal("30"):
        return value
    return None
