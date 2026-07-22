from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from oilprice.io import now_china_iso, read_json
from oilprice.payloads import (
    NoticePayload,
    PriceProvincePayload,
    PriceSnapshotPayload,
    PriceSourcePayload,
    ZonePayload,
)
from oilprice.paths import ROOT


PRODUCT_ORDER = ["89", "92", "95", "0"]
SOURCE_SORT_FIELDS = (
    "notice_id",
    "url",
    "raw_sha256",
    "adapter",
    "parser_version",
    "extracted_at",
    "published_at",
    "adjustment_date",
    "confidence",
    "name",
    "title",
)


def build_snapshot(adjustment_date: str, notice_paths: list[Path]) -> PriceSnapshotPayload:
    provinces_by_code: dict[str, PriceProvincePayload] = {}

    for path in sorted(notice_paths, key=lambda item: item.as_posix()):
        notice = read_json(path)
        zones = _normalize_zones(notice.get("extracted_zones") or _default_zone(notice))
        if not zones:
            continue

        province_code = str(notice["province_code"])
        province_name = str(notice["province_name"])
        source = _price_source(notice)
        existing = provinces_by_code.get(province_code)
        if existing is None:
            provinces_by_code[province_code] = {
                "province_code": province_code,
                "province_name": province_name,
                "sources": [source],
                "zones": zones,
            }
            continue

        if existing["province_name"] != province_name:
            labels = sorted(
                {
                    *(_source_label(item) for item in existing["sources"]),
                    _source_label(source),
                }
            )
            raise RuntimeError(
                f"Conflicting province names for province {province_code}: "
                f"{existing['province_name']!r} != {province_name!r}; notices: "
                + ", ".join(labels)
            )

        if existing["zones"] != zones:
            labels = sorted(
                {
                    *(_source_label(item) for item in existing["sources"]),
                    _source_label(source),
                }
            )
            raise RuntimeError(
                f"Conflicting price results for province {province_code} from notices: "
                + ", ".join(labels)
            )

        existing["sources"] = _merge_sources(existing["sources"], [source])

    provinces = sorted(provinces_by_code.values(), key=lambda item: item["province_code"])
    products = {
        product
        for province in provinces
        for zone in province["zones"]
        for product in zone.get("items", {})
    }

    effective_date = date.fromisoformat(adjustment_date) + timedelta(days=1)

    return {
        "adjustment_date": adjustment_date,
        "effective_from": f"{effective_date.isoformat()}T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "unit": "CNY/L",
        "currency": "CNY",
        "products": [key for key in PRODUCT_ORDER if key in products],
        "provinces": provinces,
        "updated_at": now_china_iso(),
    }


def _normalize_zones(raw_zones: object) -> list[ZonePayload]:
    if not isinstance(raw_zones, list):
        return []

    zones: list[ZonePayload] = []
    for raw_zone in raw_zones:
        if not isinstance(raw_zone, dict):
            continue
        raw_items = raw_zone.get("items")
        items = raw_items if isinstance(raw_items, dict) else {}
        zones.append(
            {
                "zone_code": str(raw_zone["zone_code"]),
                "zone_name": str(raw_zone["zone_name"]),
                "items": {key: items[key] for key in PRODUCT_ORDER if key in items},
                "missing_products": [key for key in PRODUCT_ORDER if key not in items],
            }
        )
    return sorted(zones, key=lambda item: (item["zone_code"], item["zone_name"]))


def _price_source(notice: NoticePayload) -> PriceSourcePayload:
    source: PriceSourcePayload = {
        "name": _source_name(notice),
        "url": str(notice["source_url"]),
    }
    optional_values = {
        "notice_id": notice.get("notice_id"),
        "title": notice.get("title"),
        "raw_sha256": notice.get("raw_sha256") or notice.get("sha256"),
        "adapter": notice.get("adapter"),
        "parser_version": notice.get("parser_version"),
        "extracted_at": notice.get("extracted_at"),
        "published_at": notice.get("published_at"),
        "adjustment_date": notice.get("adjustment_date"),
        "confidence": notice.get("confidence"),
    }
    for key, value in optional_values.items():
        text = str(value or "").strip()
        if text:
            source[key] = text  # type: ignore[literal-required]
    return source


def _merge_sources(
    existing: list[PriceSourcePayload],
    incoming: list[PriceSourcePayload],
) -> list[PriceSourcePayload]:
    sources_by_key = {
        _source_sort_key(source): source
        for source in [*existing, *incoming]
    }
    return [sources_by_key[key] for key in sorted(sources_by_key)]


def _source_sort_key(source: PriceSourcePayload) -> tuple[str, ...]:
    return tuple(str(source.get(field) or "") for field in SOURCE_SORT_FIELDS)


def _source_label(source: PriceSourcePayload) -> str:
    return str(source.get("notice_id") or source.get("url") or "<unknown>")


def _default_zone(notice: NoticePayload) -> list[ZonePayload]:
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


def _source_name(notice: NoticePayload) -> str:
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
