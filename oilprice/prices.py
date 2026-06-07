from __future__ import annotations

import argparse
from pathlib import Path

from .io import emit_result, now_china_iso, read_json, repo_relative, write_json
from .normalize.price_snapshot import PRODUCT_ORDER, build_snapshot
from .notices import SkipReason, province_skip_reason
from .options import PriceOptions
from .payloads import PriceProvincePayload, PriceSnapshotPayload
from .paths import ROOT


def command_build_prices(args: argparse.Namespace) -> None:
    output_path = run_build_prices(PriceOptions.from_args(args))
    emit_result(output_path)


def run_build_prices(options: PriceOptions) -> str:
    index = read_json(options.index_path)
    notice_paths = []
    for notice in index.get("notices", []):
        province_code = str(notice.get("province_code", "") or "")
        if province_skip_reason(province_code, options.province_codes, None) == SkipReason.NOT_SELECTED:
            continue
        if not notice.get("extracted_path"):
            continue
        path = ROOT / str(notice["extracted_path"]).lstrip("/")
        extracted_notice = read_json(path)
        if extracted_notice.get("published_at") != options.adjustment_date:
            continue
        notice_paths.append(path)
    snapshot = build_snapshot(options.adjustment_date, notice_paths)
    output_path = (
        ROOT / "data/prices" / options.adjustment_date[:4] / f"{options.adjustment_date}.json"
    )
    if output_path.exists():
        existing_snapshot = read_json(output_path)
        snapshot = merge_price_snapshots(existing_snapshot, snapshot)
    write_json(output_path, snapshot)
    summary_path = output_path.with_suffix(".summary.json")
    summary = build_price_summary(snapshot, output_path)
    write_json(summary_path, summary)

    latest_path = ROOT / "data/prices/latest.json"
    write_json(
        latest_path,
        {
            "latest": f"{options.adjustment_date[:4]}/{output_path.name}",
            "latest_summary": f"{options.adjustment_date[:4]}/{summary_path.name}",
            "adjustment_date": options.adjustment_date,
            "updated_at": snapshot["updated_at"],
        },
    )
    return str(output_path)


def build_price_summary(snapshot: PriceSnapshotPayload, price_path: Path) -> dict[str, object]:
    source_registry = read_json(ROOT / "data/sources/provinces.json")
    registry_provinces = source_registry.get("provinces", [])
    registry_by_code: dict[str, str] = {}
    for province in registry_provinces:
        if not isinstance(province, dict):
            continue
        province_code = str(province.get("province_code") or "").strip()
        province_name = str(province.get("province_name") or "").strip()
        if province_code:
            registry_by_code[province_code] = province_name

    success_codes = {
        str(province.get("province_code") or "").strip()
        for province in snapshot.get("provinces", [])
        if isinstance(province, dict) and str(province.get("province_code") or "").strip()
    }
    missing_codes = sorted(code for code in registry_by_code if code not in success_codes)

    return {
        "adjustment_date": snapshot.get("adjustment_date"),
        "price_file": repo_relative(price_path, ROOT),
        "provinces_total": len(registry_by_code),
        "provinces_success": len(success_codes),
        "provinces_missing": missing_codes,
    }


def merge_price_snapshots(
    existing: PriceSnapshotPayload,
    incoming: PriceSnapshotPayload,
) -> PriceSnapshotPayload:
    merged = dict(existing)

    for key in ("adjustment_date", "effective_from", "timezone", "unit", "currency"):
        if key in incoming:
            merged[key] = incoming[key]

    existing_map: dict[str, PriceProvincePayload] = {}
    for province in existing.get("provinces", []):
        if not isinstance(province, dict):
            continue
        code = str(province.get("province_code") or "").strip()
        if code:
            existing_map[code] = province

    for province in incoming.get("provinces", []):
        if not isinstance(province, dict):
            continue
        code = str(province.get("province_code") or "").strip()
        if code:
            existing_map[code] = province

    merged_provinces = sorted(existing_map.values(), key=lambda item: str(item.get("province_code", "")))
    merged["provinces"] = merged_provinces
    merged["products"] = collect_products_from_provinces(merged_provinces)
    merged["updated_at"] = incoming.get("updated_at", now_china_iso())
    return merged


def collect_products_from_provinces(provinces: list[PriceProvincePayload]) -> list[str]:
    found: set[str] = set()
    for province in provinces:
        zones = province.get("zones")
        if not isinstance(zones, list):
            continue
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            items = zone.get("items")
            if not isinstance(items, dict):
                continue
            for product in items:
                found.add(str(product))
    return [product for product in PRODUCT_ORDER if product in found]
