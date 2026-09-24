"""Shared single-zone table parsing, with bounded rows and conflict checks."""
from __future__ import annotations

import re
from collections.abc import Mapping

from oilprice.extract.price_parser import (
    PRODUCT_ORDER, extract_prices, normalize_price_text, select_liter_price,
)
from oilprice.payloads import ParsedNoticePayload


ROW_START = re.compile(
    r"^\s*(?:国[A-Z0-9ⅥB]+)?\s*[+-]?[0-9]{1,2}\s*(?:[#号]|汽油|柴油|$)"
)


def merge_prices(*candidates: Mapping[str, float]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for candidate in candidates:
        for product, value in candidate.items():
            if product in prices and prices[product] != value:
                raise ValueError(
                    f"Conflicting parsed prices for product {product}: {prices[product]} != {value}"
                )
            prices[product] = value
    return prices


def single_zone_result(prices: dict[str, float]) -> ParsedNoticePayload:
    if not prices:
        return {"confidence": "manual_required"}
    items = {key: prices[key] for key in PRODUCT_ORDER if key in prices}
    return {
        "extracted_prices": items,
        "extracted_zones": [{"zone_code": "default", "zone_name": "默认价区", "items": items}],
        "confidence": "medium" if len(items) == len(PRODUCT_ORDER) else "low",
    }


def parse_table_notice(
    text: str,
    patterns: Mapping[str, re.Pattern[str]],
    *,
    scan_lines: int,
) -> ParsedNoticePayload:
    text = normalize_price_text(text).replace("正5号", "+5号").replace("－", "-").replace("＋", "+")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = text.splitlines()
    table_prices: dict[str, float] = {}
    for index, line in enumerate(lines):
        for product, pattern in patterns.items():
            if not pattern.search(line):
                continue
            end = min(len(lines), index + scan_lines)
            for next_index in range(index + 1, end):
                if ROW_START.search(lines[next_index]):
                    end = next_index
                    break
            price = select_liter_price("\n".join(lines[index:end]))
            if price is not None:
                table_prices = merge_prices(table_prices, {product: float(price)})
    return single_zone_result(merge_prices(extract_prices(text), table_prices))
