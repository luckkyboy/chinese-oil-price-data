from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER


ZONE_BLOCK_RE = re.compile(
    r"（[一二三]）\s*(拉萨价区|昌都价区|阿里价区)(.*?)(?=（[一二三]）\s*(?:拉萨价区|昌都价区|阿里价区)|二、|$)",
    re.DOTALL,
)

ZONE_CODE_MAP = {
    "拉萨价区": "xizang-lasa",
    "昌都价区": "xizang-changdu",
    "阿里价区": "xizang-ali",
}

PRODUCT_LABEL_PATTERNS = {
    "89": re.compile(r"(?:^|\s)89号汽油"),
    "92": re.compile(r"(?:^|\s)92号汽油"),
    "95": re.compile(r"(?:^|\s)95号汽油"),
    "0": re.compile(r"(?:^|\s)0号柴油"),
}

# Always use the value after "为" as the current adjusted liter price.
LITER_ADJUST_PATTERN = re.compile(
    r"每升由([0-9]+(?:\.[0-9]+)?)元(?:上调|下调)?为([0-9]+(?:\.[0-9]+)?)元"
)


def parse_notice(text: str) -> dict[str, object]:
    zones = _extract_zone_prices(text)
    if not zones:
        return {"confidence": "manual_required"}

    return {
        "extracted_zones": zones,
        "confidence": "medium",
    }


def _extract_zone_prices(text: str) -> list[dict[str, object]]:
    zones: list[dict[str, object]] = []
    for match in ZONE_BLOCK_RE.finditer(text):
        zone_name = match.group(1)
        block = match.group(2)
        items = _extract_zone_items(block)
        if not items:
            continue
        zones.append(
            {
                "zone_code": ZONE_CODE_MAP[zone_name],
                "zone_name": zone_name,
                "items": {key: items[key] for key in PRODUCT_ORDER if key in items},
            }
        )
    return zones


def _extract_zone_items(block: str) -> dict[str, float]:
    items: dict[str, float] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        liter_match = LITER_ADJUST_PATTERN.search(line)
        if not liter_match:
            continue
        for product, label_pattern in PRODUCT_LABEL_PATTERNS.items():
            if not label_pattern.search(line):
                continue
            # group(2) is adjusted current price.
            items[product] = float(liter_match.group(2))
            break
    return items
