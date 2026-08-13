from __future__ import annotations

import re

from oilprice.extract.price_parser import PRODUCT_ORDER
from oilprice.parsers.generic import parse_notice as parse_generic_notice


ZONE_BLOCK_RE = re.compile(r"(一价区|二价区|三价区)(.*?)(?=一价区|二价区|三价区|$)", re.DOTALL)
DECIMAL_RE = re.compile(r"[0-9]+\.[0-9]+")
ZONE_CODE_MAP = {
    "一价区": "qinghai-1",
    "二价区": "qinghai-2",
    "三价区": "qinghai-3",
}


def parse_notice(text: str) -> dict[str, object]:
    zones = _extract_zones(_normalize_text(text))
    if zones:
        first_items = zones[0]["items"]
        prices = {key: first_items[key] for key in PRODUCT_ORDER if key in first_items}
        return {
            "extracted_prices": prices,
            "extracted_zones": zones,
            "confidence": "medium" if all(_is_complete(zone["items"]) for zone in zones) else "low",
        }

    result = parse_notice_fallback(text)
    if not result.get("extracted_prices"):
        return {"confidence": "manual_required"}
    return result


def parse_notice_fallback(text: str) -> dict[str, object]:
    return parse_generic_notice(text)


def _extract_zones(text: str) -> list[dict[str, object]]:
    zones: list[dict[str, object]] = []
    matches = list(ZONE_BLOCK_RE.finditer(text))
    if matches and ZONE_CODE_MAP[matches[0].group(1)] != "qinghai-1":
        prefix_decimals = _price_decimals(text[: matches[0].start()])
        # Some Qinghai tables render the first label as only "价区". Its
        # seven litre prices are still the values immediately before 二价区.
        if len(prefix_decimals) >= 7:
            first_zone_name = next(
                name for name, code in ZONE_CODE_MAP.items() if code == "qinghai-1"
            )
            zones.append(_zone_payload(first_zone_name, prefix_decimals[-7:]))

    for match in matches:
        zone_name, block = match.groups()
        decimals = _price_decimals(block)
        # Block format (liters only): 89L, 92L, 95L, 0L, -10L, -20L, -35L
        if len(decimals) < 4:
            continue
        zones.append(_zone_payload(zone_name, decimals))
    return zones


def _price_decimals(text: str) -> list[float]:
    return [float(raw) for raw in DECIMAL_RE.findall(text) if 5.0 < float(raw) < 15.0]


def _zone_payload(zone_name: str, decimals: list[float]) -> dict[str, object]:
    return {
        "zone_code": ZONE_CODE_MAP[zone_name],
        "zone_name": zone_name,
        "items": {
            "89": decimals[0],
            "92": decimals[1],
            "95": decimals[2],
            "0": decimals[3],
        },
    }


def _normalize_text(text: str) -> str:
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines)


def _is_complete(items: dict[str, float]) -> bool:
    return all(key in items for key in PRODUCT_ORDER)
