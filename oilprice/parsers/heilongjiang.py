from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


PRODUCT_MARKERS = {
    "89": re.compile(r"^\s*E?\s*89\s*号", re.IGNORECASE),
    "92": re.compile(r"^\s*E?\s*92\s*号", re.IGNORECASE),
    "95": re.compile(r"^\s*E?\s*95\s*号", re.IGNORECASE),
    "0": re.compile(r"^\s*0\s*号", re.IGNORECASE),
}
INTEGER_RE = re.compile(r"[0-9]{4,6}")
# Heilongjiang notices provide retail prices in CNY/ton for the table image.
# Conversion factors are calibrated to the provincial published ton->liter examples.
LITER_CONVERSION = {
    "89": 1311.0,
    "92": 1311.0,
    "95": 1296.5,
    "0": 1184.0,
}


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    base_prices = result.get("extracted_prices")
    prices: dict[str, float] = dict(base_prices) if isinstance(base_prices, dict) else {}

    ton_prices = _extract_retail_ton_prices(text)
    for product, ton_price in ton_prices.items():
        prices[product] = round(ton_price / LITER_CONVERSION[product], 2)

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


def _extract_retail_ton_prices(text: str) -> dict[str, float]:
    lines = _normalized_lines(text)
    prices: dict[str, float] = {}
    for index, line in enumerate(lines):
        for product, marker in PRODUCT_MARKERS.items():
            if product in prices or not marker.search(line):
                continue
            pair = _collect_two_ton_numbers(lines, index)
            if not pair:
                continue
            # Table row order: [批发价, 零售价], we need retail.
            prices[product] = float(pair[1])
    return prices


def _normalized_lines(text: str) -> list[str]:
    normalized = text.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("O号", "0号").replace("０号", "0号")
    return [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in normalized.split("\n") if line.strip()]


def _collect_two_ton_numbers(lines: list[str], start: int) -> tuple[int, int] | None:
    numbers: list[int] = []
    for offset in range(0, 7):
        index = start + offset
        if index >= len(lines):
            break
        for raw in INTEGER_RE.findall(lines[index]):
            value = int(raw)
            if 1000 <= value <= 20000:
                numbers.append(value)
                if len(numbers) == 2:
                    return numbers[0], numbers[1]
    return None
