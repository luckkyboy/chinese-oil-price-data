from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER, extract_prices
from oilprice.parsers.generic import parse_notice as parse_generic_notice


PRODUCT_LINE_PATTERNS = {
    "89": re.compile(r"^\s*89\s*[#﹟号]?", re.IGNORECASE),
    "92": re.compile(r"^\s*92\s*[#﹟号]?", re.IGNORECASE),
    "95": re.compile(r"^\s*95\s*[#﹟号]?", re.IGNORECASE),
    "0": re.compile(r"^\s*0\s*[#﹟号]?", re.IGNORECASE),
}
LITER_PRICE_RE = re.compile(r"[0-9]+\.[0-9]+")


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    if result.get("extracted_prices"):
        return result

    prices = extract_prices(text) or _extract_table_row_prices(text)
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


def _extract_table_row_prices(text: str) -> dict[str, float]:
    prices: dict[str, float] = {}
    lines = _normalize_ocr_text(text).splitlines()

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        for product, pattern in PRODUCT_LINE_PATTERNS.items():
            if product in prices:
                continue
            if not pattern.search(line):
                continue
            scan_text = "\n".join(lines[index : index + 4])
            liter_price = _find_liter_price(scan_text)
            if liter_price is not None:
                prices[product] = liter_price
    return prices


def _normalize_ocr_text(text: str) -> str:
    text = text.replace("＃", "#").replace("﹟", "#")
    text = text.replace("O号", "0号").replace("０号", "0号")
    text = text.replace("正5号", "+5号")
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _find_liter_price(text: str) -> float | None:
    for raw in LITER_PRICE_RE.findall(text):
        value = float(raw)
        if 5.0 < value < 15.0:
            return value
    return None
