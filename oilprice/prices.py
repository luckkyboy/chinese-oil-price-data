from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from .io import emit_result, now_china_iso, read_json, repo_relative, write_json_batch_atomic
from .normalize.price_snapshot import PRODUCT_ORDER, build_snapshot
from .notices import SkipReason, filter_notices_for_adjustment_date, province_skip_reason
from .options import PriceOptions
from .payloads import PriceProvincePayload, PriceSnapshotPayload
from .paths import ROOT


def command_build_prices(args: argparse.Namespace) -> None:
    output_path = run_build_prices(PriceOptions.from_args(args))
    emit_result(output_path)


def run_build_prices(
    options: PriceOptions,
    *,
    additional_payloads: Mapping[Path, Any] | None = None,
) -> str:
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
        if not filter_notices_for_adjustment_date([extracted_notice], options.adjustment_date):
            continue
        notice_paths.append(path)
    snapshot = build_snapshot(options.adjustment_date, notice_paths)
    validate_requested_provinces(snapshot, options.province_codes, options.adjustment_date)
    validate_snapshot_zone_coverage(snapshot)
    output_path = (
        ROOT / "data/prices" / options.adjustment_date[:4] / f"{options.adjustment_date}.json"
    )
    if output_path.exists():
        existing_snapshot = read_json(output_path)
        snapshot = merge_price_snapshots(existing_snapshot, snapshot)
        validate_snapshot_zone_coverage(snapshot)
    summary_path = output_path.with_suffix(".summary.json")
    summary = build_price_summary(snapshot, output_path)
    latest_path = ROOT / "data/prices/latest.json"
    update_latest = should_update_latest(latest_path, options.adjustment_date)

    publication: dict[Path, Any] = {
        output_path: snapshot,
        summary_path: summary,
    }

    if update_latest:
        publication[latest_path] = {
            "latest": f"{options.adjustment_date[:4]}/{output_path.name}",
            "latest_summary": f"{options.adjustment_date[:4]}/{summary_path.name}",
            "adjustment_date": options.adjustment_date,
            "status": summary["status"],
            "updated_at": snapshot["updated_at"],
        }
    if additional_payloads:
        collisions = set(publication).intersection(additional_payloads)
        if collisions:
            labels = ", ".join(str(path) for path in sorted(collisions))
            raise ValueError(f"duplicate price publication target(s): {labels}")
        publication.update(additional_payloads)

    write_json_batch_atomic(publication)
    return str(output_path)


def validate_requested_provinces(
    snapshot: PriceSnapshotPayload,
    requested_codes: set[str] | None,
    adjustment_date: str,
) -> None:
    if requested_codes is None:
        return

    provinces = snapshot.get("provinces", [])
    incoming_codes = (
        {
            str(province.get("province_code") or "").strip()
            for province in provinces
            if isinstance(province, dict)
            and str(province.get("province_code") or "").strip()
        }
        if isinstance(provinces, list)
        else set()
    )
    missing_codes = sorted(requested_codes - incoming_codes)
    if missing_codes:
        raise RuntimeError(
            f"Incoming price snapshot for {adjustment_date} is missing requested "
            f"province codes: {', '.join(missing_codes)}"
        )


def validate_snapshot_zone_coverage(
    snapshot: PriceSnapshotPayload,
    region_root: Path | None = None,
) -> None:
    """Reject partial or mislabeled results for provinces with declared price zones."""

    resolved_region_root = region_root or ROOT / "data/regions"
    if not resolved_region_root.exists():
        return

    configured_zones: dict[str, dict[str, str]] = {}
    for region_path in sorted(resolved_region_root.glob("*.json")):
        if region_path.name == "regions.json":
            continue
        payload = read_json(region_path)
        province_code = str(payload.get("province_code") or "").strip()
        zones = payload.get("zones")
        if not province_code or not isinstance(zones, list):
            continue
        zone_names: dict[str, str] = {}
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            zone_code = str(zone.get("zone_code") or "").strip()
            zone_name = str(zone.get("zone_name") or "").strip()
            if zone_code:
                zone_names[zone_code] = zone_name
        if zone_names:
            configured_zones[province_code] = zone_names

    for province in snapshot.get("provinces", []):
        if not isinstance(province, dict):
            continue
        province_code = str(province.get("province_code") or "").strip()
        expected = configured_zones.get(province_code)
        if expected is None:
            continue

        raw_zones = province.get("zones")
        actual: dict[str, str] = {}
        if isinstance(raw_zones, list):
            for zone in raw_zones:
                if not isinstance(zone, dict):
                    continue
                zone_code = str(zone.get("zone_code") or "").strip()
                zone_name = str(zone.get("zone_name") or "").strip()
                if zone_code:
                    if zone_code in actual:
                        raise RuntimeError(
                            f"Duplicate price zone {zone_code} for province {province_code}"
                        )
                    actual[zone_code] = zone_name

        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected: {', '.join(unexpected)}")
            raise RuntimeError(
                f"Incomplete price zone coverage for province {province_code} "
                f"({'; '.join(details)})"
            )

        mislabeled = sorted(
            zone_code
            for zone_code, expected_name in expected.items()
            if actual.get(zone_code) != expected_name
        )
        if mislabeled:
            labels = ", ".join(
                f"{zone_code}: expected {expected[zone_code]!r}, got {actual.get(zone_code)!r}"
                for zone_code in mislabeled
            )
            raise RuntimeError(
                f"Price zone name mismatch for province {province_code} ({labels})"
            )


def should_update_latest(latest_path: Path, adjustment_date: str) -> bool:
    target_date = parse_iso_date(adjustment_date, "target adjustment_date")
    if not latest_path.exists():
        return True

    try:
        current_latest = read_json(latest_path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Existing latest price pointer is invalid: {latest_path}; refusing to overwrite it"
        ) from exc
    if not isinstance(current_latest, dict):
        raise ValueError(
            f"Existing latest price pointer is invalid: {latest_path}; refusing to overwrite it"
        )

    current_date = parse_iso_date(
        current_latest.get("adjustment_date"),
        f"existing latest adjustment_date in {latest_path}",
    )
    return target_date >= current_date


def parse_iso_date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"Invalid {label}: expected an ISO date in YYYY-MM-DD format")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {label} {value!r}: expected an ISO date in YYYY-MM-DD format"
        ) from exc
    if parsed.isoformat() != value:
        raise ValueError(f"Invalid {label} {value!r}: expected an ISO date in YYYY-MM-DD format")
    return parsed


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
        "status": "complete" if not missing_codes else "partial",
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
