from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from .crawl.browser_client import BrowserSession
from .discovery_pipeline import run_discover, validate_requested_province_codes
from .extraction_pipeline import run_extract_files
from .fetch_pipeline import run_fetch
from .io import emit_result, read_json, repo_relative
from .notices import (
    SkipReason,
    pending_province_codes_from_summary,
    province_code_for_slug,
    province_skip_reason,
    read_notice_map,
    notice_index_payload,
    write_notice_index,
)
from .options import DiscoverOptions, ExtractFilesOptions, ExtractOptions, FetchOptions, PriceOptions
from .paths import ROOT
from .payloads import EnabledSource
from .prices import run_build_prices
from .regions import resolve_zone
from .sources import load_enabled_sources
from .validation import validate_json_project


logger = logging.getLogger(__name__)


def command_extract(args: argparse.Namespace) -> None:
    index_path = run_extract(ExtractOptions.from_args(args))
    emit_result(index_path)


def run_extract(options: ExtractOptions) -> str:
    enabled_sources = load_enabled_sources(options.sources_path)
    validate_requested_province_codes(enabled_sources, options.province_codes)
    pending_codes: set[str] | None = None
    if not options.force:
        pending_codes = pending_province_codes_from_summary(options.adjustment_date)

    sources_by_province: dict[str, EnabledSource] = {}
    for item in enabled_sources:
        sources_by_province.setdefault(str(item["province_code"]), item)

    target_sources: list[EnabledSource] = []
    for province_code, item in sources_by_province.items():
        province_name = str(item["province_name"])
        skip_reason = province_skip_reason(province_code, options.province_codes, pending_codes)
        if skip_reason == SkipReason.NOT_SELECTED:
            continue
        if skip_reason == SkipReason.NOT_PENDING:
            logger.info(
                f"[skip] {province_name} ({province_code}) is not pending for "
                f"{options.adjustment_date}"
            )
            continue
        target_sources.append(item)

    notices_by_id = read_notice_map(options.index_path)
    options.index_path.parent.mkdir(parents=True, exist_ok=True)

    if not target_sources:
        logger.info(f"[extract] no target provinces for {options.adjustment_date}; skip build")
        return str(options.index_path)

    logger.info(
        f"[extract] shared CloakBrowser session start index={repo_relative(options.index_path, ROOT)}",
    )
    processed_province_codes: set[str] = set()
    with BrowserSession(headless=True) as browser_session:
        for item in target_sources:
            province_code = str(item["province_code"])
            province_name = str(item["province_name"])

            province_start = time.perf_counter()
            province_index = options.index_path.with_name(f"{province_code}.discover.json")
            run_discover(
                DiscoverOptions(
                    sources_path=options.sources_path,
                    index_path=province_index,
                    adjustment_date=options.adjustment_date,
                    timeout=options.timeout,
                    force=True,
                    province_codes={province_code},
                    browser_session=browser_session,
                )
            )
            discovered_index = read_json(province_index)
            discovered_notices = [
                notice
                for notice in discovered_index.get("notices", [])
                if isinstance(notice, dict)
            ]
            discovery_errors = discovered_index.get("errors", [])
            if discovery_errors or not discovered_notices:
                reasons = []
                if discovery_errors:
                    reasons.append(_format_discovery_errors(discovery_errors))
                if not discovered_notices:
                    reasons.append("no notices found")
                raise RuntimeError(
                    f"discovery failed for {province_name} ({province_code}): "
                    + "; ".join(reasons)
                )
            logger.info(
                f"[extract] {province_name} ({province_code}) discover "
                f"notices={len(discovered_notices)} elapsed={_elapsed(province_start)}"
            )

            fetch_start = time.perf_counter()
            run_fetch(
                FetchOptions(
                    index_path=province_index,
                    adjustment_date=options.adjustment_date,
                    timeout=options.timeout,
                    force=True,
                    province_codes={province_code},
                    browser_session=browser_session,
                )
            )
            logger.info(
                f"[extract] {province_name} ({province_code}) fetch "
                f"elapsed={_elapsed(fetch_start)}"
            )

            extract_start = time.perf_counter()
            run_extract_files(
                ExtractFilesOptions(
                    index_path=province_index,
                    adjustment_date=options.adjustment_date,
                    force=True,
                    province_codes={province_code},
                )
            )
            logger.info(
                f"[extract] {province_name} ({province_code}) extract "
                f"elapsed={_elapsed(extract_start)}"
            )

            staged_notices_by_id = read_notice_map(province_index)
            merged_notices_by_id = {
                notice_id: notice
                for notice_id, notice in notices_by_id.items()
                if str(notice.get("province_code", "") or "") != province_code
            }
            merged_notices_by_id.update(staged_notices_by_id)
            notices_by_id = merged_notices_by_id
            processed_province_codes.add(province_code)
            logger.info(
                f"[extract] {province_name} ({province_code}) staged "
                f"notices={len(staged_notices_by_id)} total={_elapsed(province_start)}"
            )

    if processed_province_codes:
        price_start = time.perf_counter()
        candidate_index = options.index_path.with_name(f".{options.index_path.name}.candidate")
        write_notice_index(candidate_index, notices_by_id)
        try:
            run_build_prices(
                PriceOptions(
                    index_path=candidate_index,
                    adjustment_date=options.adjustment_date,
                    province_codes=processed_province_codes,
                ),
                additional_payloads={
                    options.index_path: notice_index_payload(notices_by_id),
                },
            )
        finally:
            candidate_index.unlink(missing_ok=True)
        logger.info(
            f"[price] provinces={','.join(sorted(processed_province_codes))} "
            f"elapsed={_elapsed(price_start)}"
        )

    return str(options.index_path)


def _format_discovery_errors(raw_errors: object) -> str:
    if not isinstance(raw_errors, list):
        return f"invalid discovery errors payload: {raw_errors}"

    details = []
    for error in raw_errors:
        if not isinstance(error, dict):
            details.append(str(error))
            continue
        stage = str(error.get("stage") or "unknown")
        url = str(error.get("url") or "unknown URL")
        message = str(error.get("message") or error.get("error_type") or "unknown error")
        details.append(f"{stage} error for {url}: {message}")
    return " | ".join(details) or "unknown discovery error"


def command_validate_json(args: argparse.Namespace) -> None:
    paths = [Path(path) for path in args.paths]
    result = validate_json_project(paths or None, root=ROOT)
    if not result.ok:
        raise SystemExit(
            f"JSON data contract validation failed with {len(result.issues)} error(s):\n"
            f"{result.format_errors()}"
        )
    emit_result(f"valid JSON data contract files: {result.files_checked}")


def command_lookup_price(args: argparse.Namespace) -> None:
    region_path = ROOT / "data/regions" / f"{args.province}.json"
    price_path = ROOT / "data/prices" / args.adjustment_date[:4] / f"{args.adjustment_date}.json"
    province_code = province_code_for_slug(args.province)
    zone = None
    if region_path.exists():
        zone = resolve_zone(region_path, args.area, parent=args.parent)
        if not zone:
            raise SystemExit(f"area not found in {region_path}: {args.area}")

    price_payload = read_json(price_path)
    for province in price_payload.get("provinces", []):
        if province_code and province["province_code"] != province_code:
            continue
        if not zone:
            zones = province.get("zones", [])
            if len(zones) != 1:
                raise SystemExit(f"missing region mapping for multi-zone province: {args.province}")
            zone = zones[0]
        for price_zone in province.get("zones", []):
            if price_zone["zone_code"] != zone["zone_code"]:
                continue
            items = price_zone.get("items", {})
            result = {
                "province_name": province["province_name"],
                "area": args.area,
                "zone_code": zone["zone_code"],
                "zone_name": zone["zone_name"],
                "prices": items,
            }
            if args.product:
                result["price"] = items.get(args.product)
            emit_result(result)
            return

    raise SystemExit(f"zone not found in {price_path}: {zone['zone_code']}")


def _elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.1f}s"
