from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


SENTENCE_PRICE_PATTERNS = {
    "89": re.compile(
        r"89\s*号(?:车用)?(?:乙醇)?汽油[^。；\n]*?调整为\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"
    ),
    "92": re.compile(
        r"92\s*号(?:车用)?(?:乙醇)?汽油[^。；\n]*?调整为\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"
    ),
    "95": re.compile(
        r"95\s*号(?:车用)?(?:乙醇)?汽油[^。；\n]*?调整为\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"
    ),
    "0": re.compile(r"0\s*号(?:车用)?柴油[^。；\n]*?调整为\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
}

DIRECT_PRICE_PATTERNS = {
    "89": re.compile(r"(?:我省)?\s*89\s*号(?:车用)?(?:乙醇)?汽油\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
    "92": re.compile(r"(?:我省)?\s*92\s*号(?:车用)?(?:乙醇)?汽油\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
    "95": re.compile(r"(?:我省)?\s*95\s*号(?:车用)?(?:乙醇)?汽油\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
    "0": re.compile(r"(?:我省)?\s*0\s*号(?:车用)?柴油\s*([0-9]+(?:\.[0-9]+)?)\s*元/升"),
}


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    base_prices = result.get("extracted_prices")
    prices: dict[str, float] = dict(base_prices) if isinstance(base_prices, dict) else {}

    sentence_prices = _extract_prices_from_adjustment_sentences(text)
    prices.update(sentence_prices)
    direct_prices = _extract_prices_from_direct_sentences(text)
    prices.update(direct_prices)
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


def _extract_prices_from_adjustment_sentences(text: str) -> dict[str, float]:
    normalized = _normalize_text(text)
    prices: dict[str, float] = {}
    for product, pattern in SENTENCE_PRICE_PATTERNS.items():
        match = pattern.search(normalized)
        if not match:
            continue
        prices[product] = float(match.group(1))
    return prices


def _extract_prices_from_direct_sentences(text: str) -> dict[str, float]:
    normalized = _normalize_text(text)
    prices: dict[str, float] = {}
    for product, pattern in DIRECT_PRICE_PATTERNS.items():
        match = pattern.search(normalized)
        if not match:
            continue
        prices[product] = float(match.group(1))
    return prices


def _normalize_text(text: str) -> str:
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("／", "/")
    return re.sub(r"[ \t\r\f\v]+", " ", text)
