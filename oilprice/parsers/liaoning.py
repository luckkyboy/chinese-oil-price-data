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

# Fallback patterns for garbled PDF text where Chinese characters are lost.
# Liaoning's PDF uses pypdfium2 which can lose CJK chars while preserving digits.
_GARBLED_TON = re.compile(r"^\s*(?:(\d{4,6})\s+(\d{4,6})\s*)$", re.MULTILINE)
_GARBLED_LABELED = re.compile(r"^\s*(92|95)\s+(\d{4,6})\s+(\d{4,6})\s*$", re.MULTILINE)

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
        prices = _extract_from_garbled_table(text)
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


def _extract_from_garbled_table(text: str) -> dict[str, float]:
    """Fallback for garbled PDF text where Chinese characters are lost.

    The PDF text extraction preserves digits but drops CJK chars, leaving
    unlabeled rows like ``10595  10895`` and labeled rows like ``92   11231  11549``.
    """
    lines = text.split("\n")

    # Find labeled rows (92, 95) and collect their retail ton prices
    labeled = {}  # product -> (line_idx, retail_ton_price)
    for i, line in enumerate(lines):
        m = _GARBLED_LABELED.search(line)
        if m:
            labeled[m.group(1)] = (i, float(m.group(3)))

    if not labeled:
        return {}

    # Collect all unlabeled two-number rows (wholesale retail)
    unlabeled_rows: list[tuple[int, float]] = []  # (line_idx, retail_price)
    for i, line in enumerate(lines):
        # Skip labeled rows and date-like lines
        if _GARBLED_LABELED.search(line):
            continue
        if re.search(r"\b20\d{2}\b", line):
            continue
        m = _GARBLED_TON.search(line)
        if m:
            unlabeled_rows.append((i, float(m.group(2))))

    prices: dict[str, float] = {}

    # 92 and 95: direct from labeled rows
    for product, label_row in labeled.items():
        idx, retail = label_row
        prices[product] = round(retail / LITER_CONVERSION[product], 2)

    # 89#: first unlabeled row that appears before 92
    if "92" in labeled and "89" not in prices:
        ninety_two_idx = labeled["92"][0]
        for idx, retail in unlabeled_rows:
            if idx < ninety_two_idx:
                prices["89"] = round(retail / LITER_CONVERSION["89"], 2)
                break

    # 0# diesel: first unlabeled row after 95 that isn't 89
    if "95" in labeled and "0" not in prices:
        ninety_five_idx = labeled["95"][0]
        for idx, retail in unlabeled_rows:
            if idx > ninety_five_idx:
                # Verify the price is in diesel range after conversion
                liter = retail / LITER_CONVERSION["0"]
                if 7.0 < liter < 10.0:
                    prices["0"] = round(liter, 2)
                    break

    return prices


def _normalize_text(text: str) -> str:
    text = text.replace("／", "/")
    text = text.replace("＋", "+").replace("－", "-")
    return re.sub(r"[ \t\r\f\v]+", " ", text)
