from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from oilprice.io import now_china_iso, read_json


PRODUCT_ORDER = ["89", "92", "95", "0"]
ROOT = Path(__file__).resolve().parents[2]


def build_snapshot(adjustment_date: str, notice_paths: list[Path]) -> dict[str, Any]:
    provinces: list[dict[str, Any]] = []
    products: set[str] = set()

    for path in notice_paths:
        notice = read_json(path)
        zones = notice.get("extracted_zones") or _default_zone(notice)
        if not zones:
            continue
        for zone in zones:
            products.update(zone.get("items", {}))
        provinces.append(
            {
                "province_code": notice["province_code"],
                "province_name": notice["province_name"],
                "sources": [
                    {
                        "name": _source_name(notice),
                        "url": notice["source_url"],
                    }
                ],
                "zones": [
                    {
                        "zone_code": zone["zone_code"],
                        "zone_name": zone["zone_name"],
                        "items": {
                            key: zone["items"][key]
                            for key in PRODUCT_ORDER
                            if key in zone.get("items", {})
                        },
                        "missing_products": [
                            key for key in PRODUCT_ORDER if key not in zone.get("items", {})
                        ],
                    }
                    for zone in zones
                ],
            }
        )

    effective_date = date.fromisoformat(adjustment_date) + timedelta(days=1)

    return {
        "adjustment_date": adjustment_date,
        "effective_from": f"{effective_date.isoformat()}T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "unit": "CNY/L",
        "currency": "CNY",
        "products": [key for key in PRODUCT_ORDER if key in products],
        "provinces": sorted(provinces, key=lambda item: item["province_code"]),
        "updated_at": now_china_iso(),
    }


def _default_zone(notice: dict[str, Any]) -> list[dict[str, Any]]:
    prices = notice.get("extracted_prices") or {}
    if not prices:
        return []
    return [
        {
            "zone_code": "default",
            "zone_name": "默认价区",
            "items": prices,
        }
    ]


def _source_name(notice: dict[str, Any]) -> str:
    if notice.get("source_name"):
        return str(notice["source_name"])

    sources_path = ROOT / "data/sources/provinces.json"
    if sources_path.exists():
        payload = read_json(sources_path)
        source_url = str(notice.get("source_url", ""))
        for province in payload.get("provinces", []):
            if province.get("province_code") != notice.get("province_code"):
                continue
            for source in province.get("sources", []):
                if source_url.startswith(source.get("base_url", "")):
                    return str(source.get("name", notice["province_name"]))

    return str(notice["province_name"])
