from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


SENTENCE_PRICE_PATTERNS = {
    "89": re.compile(r"89\s*号(?:车用)?(?:乙醇)?汽油[^。；\n]*?调整到\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
    "92": re.compile(r"92\s*号(?:车用)?(?:乙醇)?汽油[^。；\n]*?调整到\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
    "95": re.compile(r"95\s*号(?:车用)?(?:乙醇)?汽油[^。；\n]*?调整到\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
    "0": re.compile(r"0\s*号(?:车用)?柴油[^。；\n]*?调整到\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
}

TABLE_PRICE_PATTERNS = {
    "89": re.compile(
        r"(?:汽油\s*)?89\s*号(?:（[^）]{0,12}）|\([^)]{0,12}\))?\s*[0-9]{4,5}\s*([0-9]+(?:\.[0-9]+)?)"
    ),
    "92": re.compile(
        r"(?:汽油\s*)?92\s*号(?:（[^）]{0,12}）|\([^)]{0,12}\))?\s*[0-9]{4,5}\s*([0-9]+(?:\.[0-9]+)?)"
    ),
    "95": re.compile(
        r"(?:汽油\s*)?95\s*号(?:（[^）]{0,12}）|\([^)]{0,12}\))?\s*[0-9]{4,5}\s*([0-9]+(?:\.[0-9]+)?)"
    ),
    "0": re.compile(
        r"(?:柴油\s*)?0\s*号(?:（[^）]{0,12}）|\([^)]{0,12}\))?\s*[0-9]{4,5}\s*([0-9]+(?:\.[0-9]+)?)"
    ),
}


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    base_prices = result.get("extracted_prices")
    prices: dict[str, float] = dict(base_prices) if isinstance(base_prices, dict) else {}

    normalized = _normalize_text(text)
    table_prices = _extract_table_prices(_likely_table_block(normalized))
    sentence_prices = _extract_sentence_prices(normalized)

    prices.update(table_prices)
    for product, value in sentence_prices.items():
        prices.setdefault(product, value)

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


def _extract_sentence_prices(text: str) -> dict[str, float]:
    prices: dict[str, float] = {}
    for product, pattern in SENTENCE_PRICE_PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        prices[product] = float(match.group(1))
    return prices


def _extract_table_prices(text: str) -> dict[str, float]:
    prices: dict[str, float] = {}
    for product, pattern in TABLE_PRICE_PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        prices[product] = float(match.group(1))
    return prices


def _likely_table_block(text: str) -> str:
    table_markers = ["附表", "价格表", "零售价", "元/升"]
    start = -1
    for marker in table_markers:
        start = text.find(marker)
        if start >= 0:
            break
    if start < 0:
        return text
    end = text.find("注：", start)
    if end < 0:
        end = len(text)
    return text[start:end]


def _normalize_text(text: str) -> str:
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("＃", "#").replace("﹟", "#")
    text = text.replace("／", "/")
    return re.sub(r"[ \t\r\f\v]+", " ", text)
