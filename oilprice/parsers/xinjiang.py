from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


GASOLINE_MARKERS = ("汽油(国ⅥA)", "汽油（国ⅥA）")
DIESEL_MARKERS = ("柴油(国Ⅵ)", "柴油（国Ⅵ）")
RETAIL_MARKER = "最高零售价"
NUMBER_RE = re.compile(r"[0-9]{4,6}")

# 新疆公告价格表按元/吨发布，按常用折算系数换算为元/升。
GASOLINE_LITER_PER_TON = 1351
DIESEL_LITER_PER_TON = 1176


def parse_notice(text: str) -> dict[str, object]:
    result = parse_generic_notice(text)
    base_prices = result.get("extracted_prices")
    prices: dict[str, float] = dict(base_prices) if isinstance(base_prices, dict) else {}

    normalized = _normalize_text(text)
    table_prices = _extract_table_prices(normalized)
    prices.update(table_prices)
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


def _extract_table_prices(text: str) -> dict[str, float]:
    gasoline_section = _between_markers(text, GASOLINE_MARKERS, DIESEL_MARKERS)
    diesel_section = _from_marker(text, DIESEL_MARKERS)

    gasoline_prices = _retail_values(gasoline_section, expected_count=3)
    diesel_prices = _retail_values(diesel_section, expected_count=5)

    prices: dict[str, float] = {}
    if len(gasoline_prices) >= 3:
        prices["89"] = _ton_to_liter(gasoline_prices[0], GASOLINE_LITER_PER_TON)
        prices["92"] = _ton_to_liter(gasoline_prices[1], GASOLINE_LITER_PER_TON)
        prices["95"] = _ton_to_liter(gasoline_prices[2], GASOLINE_LITER_PER_TON)
    if diesel_prices:
        prices["0"] = _ton_to_liter(diesel_prices[0], DIESEL_LITER_PER_TON)
    return prices


def _retail_values(section: str, expected_count: int) -> list[float]:
    marker_index = section.find(RETAIL_MARKER)
    if marker_index < 0:
        return []
    tail = section[marker_index + len(RETAIL_MARKER) :]
    raw_values = NUMBER_RE.findall(tail)
    values = [float(raw) for raw in raw_values[:expected_count]]
    return values if len(values) == expected_count else []


def _between_markers(text: str, start_markers: tuple[str, ...], end_markers: tuple[str, ...]) -> str:
    start = _find_first_marker(text, start_markers)
    if start < 0:
        return ""
    end = _find_first_marker(text[start:], end_markers)
    if end < 0:
        return text[start:]
    return text[start : start + end]


def _from_marker(text: str, markers: tuple[str, ...]) -> str:
    start = _find_first_marker(text, markers)
    return text[start:] if start >= 0 else ""


def _find_first_marker(text: str, markers: tuple[str, ...]) -> int:
    hits = [text.find(marker) for marker in markers if text.find(marker) >= 0]
    return min(hits) if hits else -1


def _ton_to_liter(value: float, liter_per_ton: int) -> float:
    if value < 100:
        return round(value, 2)
    return round(value / liter_per_ton, 2)


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("＃", "#").replace("﹟", "#")
    return re.sub(r"[ \t\f\v]+", " ", text)
