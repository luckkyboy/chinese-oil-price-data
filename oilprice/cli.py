from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .adapters.discovery_enhancers import discover_with_enhancer
from .adapters.generic import discover_from_html
from .crawl.http import build_discovery_headers, fetch_bytes, fetch_bytes_with_headers, save_raw
from .crawl.playwright_client import fetch_page_html
from .extract.attachments import attachment_suffix, find_attachment_links
from .extract.docx import docx_to_text
from .extract.html import html_to_text
from .extract.pdf import pdf_to_text
from .extract.xls import xls_to_text
from .io import now_china_iso, read_json, repo_relative, write_json
from .normalize.price_snapshot import PRODUCT_ORDER, build_snapshot
from .ocr.paddle import OcrUnavailableError, image_to_text
from .parsers import parse_notice
from .regions import resolve_zone
from .sources import load_enabled_sources


ROOT = Path(__file__).resolve().parents[1]


def command_discover(args: argparse.Namespace) -> None:
    source_path = ROOT / args.sources
    index_path = _notice_index_path(args)
    adjustment_date = getattr(args, "date", None) or getattr(args, "adjustment_date", None)
    enabled_sources = load_enabled_sources(source_path)
    force = bool(getattr(args, "force", False))
    pending_province_codes: set[str] | None = None
    if adjustment_date and not force:
        pending_province_codes = _pending_province_codes_from_summary(adjustment_date)
    notices: list[dict[str, object]] = []

    for item in enabled_sources:
        province_code = str(item["province_code"])
        if pending_province_codes is not None and province_code not in pending_province_codes:
            print(
                f"[skip] {item['province_name']} ({province_code}) is not pending for "
                f"{adjustment_date}"
            )
            continue
        source = item["source"]
        keywords = source.get("notice_keywords") or ["成品油", "汽油", "柴油"]
        enhancer = str(source.get("discovery_enhancer") or "")
        for list_url in source["list_urls"]:
            if enhancer:
                refs = discover_with_enhancer(
                    enhancer,
                    source=source,
                    list_url=list_url,
                    province_code=item["province_code"],
                    province_name=item["province_name"],
                    province_slug=item["slug"],
                    keywords=keywords,
                    timeout=args.timeout,
                )
            else:
                if str(source.get("list_fetch") or "").strip().lower() == "playwright":
                    html = _fetch_page_html_with_playwright(list_url, timeout=args.timeout)
                else:
                    content, _ = fetch_bytes_with_headers(
                        list_url,
                        timeout=args.timeout,
                        headers=build_discovery_headers(
                            str(source.get("base_url") or ""),
                            list_url,
                            str(source.get("cookie") or "") or None,
                        ),
                    )
                    html = content.decode("utf-8", errors="replace")
                refs = discover_from_html(
                    html=html,
                    list_url=list_url,
                    province_code=item["province_code"],
                    province_name=item["province_name"],
                    province_slug=item["slug"],
                    keywords=keywords,
                )
            for ref in refs:
                notice = {
                    "notice_id": ref.notice_id,
                    "province_code": ref.province_code,
                    "province_name": ref.province_name,
                    "source_name": source.get("name", item["province_name"]),
                    "adapter": source.get("adapter", "generic"),
                    "title": ref.title,
                    "source_url": ref.source_url,
                }
                if source.get("cookie"):
                    notice["cookie"] = source["cookie"]
                if source.get("detail_fetch"):
                    notice["detail_fetch"] = source["detail_fetch"]
                if ref.published_at:
                    notice["published_at"] = ref.published_at
                notices.append(notice)

    if adjustment_date:
        notices = _filter_notices_for_adjustment_date(notices, adjustment_date)

    write_json(index_path, {"updated_at": now_china_iso(), "notices": notices})
    print(index_path)


def command_fetch(args: argparse.Namespace) -> None:
    index_path = _notice_index_path(args)
    notice_root = index_path.parent
    index = read_json(index_path)
    fetched: list[dict[str, object]] = []

    for notice in index.get("notices", []):
        province_slug = _slug_from_notice(notice)
        notice_id = notice["notice_id"]
        headers = _notice_request_headers(notice)
        raw_path = notice_root / "raw" / province_slug / f"{notice_id}.html"
        sha256, _ = _save_notice_html(
            notice=notice,
            raw_path=raw_path,
            timeout=args.timeout,
            headers=headers,
        )
        raw_html = raw_path.read_text(encoding="utf-8", errors="replace")
        attachments = []
        embedded_pdf = _pdf_attachment_from_viewer_url(str(notice["source_url"]))
        if embedded_pdf:
            attachment_path = (
                notice_root
                / "raw"
                / province_slug
                / f"{notice_id}_attachment_1{attachment_suffix(embedded_pdf['url'])}"
            )
            try:
                attachment_sha256, _ = save_raw(
                    embedded_pdf["url"],
                    attachment_path,
                    timeout=args.timeout,
                    headers=headers,
                )
            except Exception as exc:
                print(
                    f"[warn] Attachment fetch failed for {notice['source_url']}: "
                    f"{embedded_pdf['url']} ({exc})"
                )
            else:
                attachments.append(
                    {
                        "url": embedded_pdf["url"],
                        "name": embedded_pdf.get("name"),
                        "type": "document",
                        "path": repo_relative(attachment_path, ROOT),
                        "sha256": attachment_sha256,
                    }
                )
        for index_number, attachment in enumerate(
            find_attachment_links(raw_html, notice["source_url"]),
            start=len(attachments) + 1,
        ):
            suffix = attachment_suffix(attachment["url"])
            attachment_path = (
                notice_root
                / "raw"
                / province_slug
                / f"{notice_id}_attachment_{index_number}{suffix}"
            )
            try:
                attachment_sha256, _ = save_raw(
                    attachment["url"],
                    attachment_path,
                    timeout=args.timeout,
                    headers=headers,
                )
            except Exception as exc:
                print(
                    f"[warn] Attachment fetch failed for {notice['source_url']}: "
                    f"{attachment['url']} ({exc})"
                )
                continue
            attachment_payload = {
                "url": attachment["url"],
                "name": attachment.get("name"),
                "type": attachment.get("type"),
                "path": repo_relative(attachment_path, ROOT),
                "sha256": attachment_sha256,
            }
            attachments.append(
                {key: value for key, value in attachment_payload.items() if value is not None}
            )
        updated = dict(notice)
        updated["raw_path"] = repo_relative(raw_path, ROOT)
        updated["sha256"] = sha256
        if attachments:
            updated["attachments"] = attachments
        fetched.append(updated)

    write_json(index_path, {"updated_at": now_china_iso(), "notices": fetched})
    print(index_path)


def command_extract(args: argparse.Namespace) -> None:
    index_path = _notice_index_path(args)
    notice_root = index_path.parent
    index = read_json(index_path)
    updated_notices: list[dict[str, object]] = []

    for notice in index.get("notices", []):
        raw_path = notice.get("raw_path")
        if not raw_path:
            updated_notices.append(notice)
            continue

        absolute_raw_path = ROOT / str(raw_path).lstrip("/")
        if not absolute_raw_path.exists():
            updated_notices.append(notice)
            continue

        text = html_to_text(absolute_raw_path.read_bytes())
        attachment_texts = []
        updated_attachments = []
        province_slug = _slug_from_notice(notice)
        for attachment in notice.get("attachments", []):
            updated_attachment = dict(attachment)
            attachment_path = attachment.get("path")
            if not attachment_path:
                updated_attachments.append(updated_attachment)
                continue
            absolute_attachment_path = ROOT / str(attachment_path).lstrip("/")
            if absolute_attachment_path.suffix.lower() == ".docx":
                attachment_text = docx_to_text(absolute_attachment_path)
                if attachment_text:
                    attachment_texts.append(attachment_text)
            elif absolute_attachment_path.suffix.lower() == ".xls":
                attachment_text = xls_to_text(absolute_attachment_path)
                if attachment_text:
                    attachment_texts.append(attachment_text)
            elif absolute_attachment_path.suffix.lower() == ".pdf":
                attachment_text = pdf_to_text(absolute_attachment_path)
                if attachment_text:
                    attachment_texts.append(attachment_text)
            elif _should_ocr_attachment(notice, attachment, absolute_attachment_path):
                try:
                    attachment_text = image_to_text(absolute_attachment_path)
                except OcrUnavailableError as exc:
                    updated_attachment["ocr_error"] = str(exc)
                else:
                    if attachment_text:
                        ocr_text_path = (
                            notice_root
                            / "extracted"
                            / province_slug
                            / f"{notice['notice_id']}_{absolute_attachment_path.stem}.ocr.txt"
                        )
                        ocr_text_path.parent.mkdir(parents=True, exist_ok=True)
                        ocr_text_path.write_text(attachment_text, encoding="utf-8")
                        updated_attachment["ocr_text_path"] = repo_relative(ocr_text_path, ROOT)
                        attachment_texts.append(attachment_text)
            updated_attachments.append(updated_attachment)
        combined_text = "\n\n".join([text, *attachment_texts])
        parsed = parse_notice(str(notice.get("adapter", "generic")), combined_text)
        parsed = _normalize_parsed_prices(parsed)
        extracted_path = notice_root / "extracted" / province_slug / f"{notice['notice_id']}.json"
        extracted_payload = {
            "notice_id": notice["notice_id"],
            "province_code": notice["province_code"],
            "province_name": notice["province_name"],
            "source_name": notice.get("source_name", notice["province_name"]),
            "adapter": notice.get("adapter", "generic"),
            "title": notice["title"],
            "published_at": parsed.get("adjustment_date") or notice.get("published_at"),
            "source_url": notice["source_url"],
            "raw_path": raw_path,
            "content_text": combined_text,
            "tables": [],
            "attachments": updated_attachments,
            "extracted_prices": parsed.get("extracted_prices"),
            "extracted_zones": parsed.get("extracted_zones"),
            "confidence": parsed.get("confidence", "manual_required"),
            "extracted_at": now_china_iso(),
        }
        extracted_payload = {key: value for key, value in extracted_payload.items() if value is not None}
        write_json(extracted_path, extracted_payload)

        updated = dict(notice)
        updated["extracted_path"] = repo_relative(extracted_path, ROOT)
        if updated_attachments:
            updated["attachments"] = updated_attachments
        updated_notices.append(updated)

    write_json(index_path, {"updated_at": now_china_iso(), "notices": updated_notices})
    print(index_path)


def command_build_prices(args: argparse.Namespace) -> None:
    index = read_json(_notice_index_path(args))
    notice_paths = []
    for notice in index.get("notices", []):
        if not notice.get("extracted_path"):
            continue
        path = ROOT / str(notice["extracted_path"]).lstrip("/")
        extracted_notice = read_json(path)
        if extracted_notice.get("published_at") != args.adjustment_date:
            continue
        notice_paths.append(path)
    snapshot = build_snapshot(args.adjustment_date, notice_paths)
    output_path = ROOT / "data/prices" / args.adjustment_date[:4] / f"{args.adjustment_date}.json"
    if output_path.exists():
        existing_snapshot = read_json(output_path)
        snapshot = _merge_price_snapshots(existing_snapshot, snapshot)
    write_json(output_path, snapshot)
    summary_path = output_path.with_suffix(".summary.json")
    summary = _build_price_summary(snapshot, output_path)
    write_json(summary_path, summary)

    latest_path = ROOT / "data/prices/latest.json"
    write_json(
        latest_path,
        {
            "latest": f"{args.adjustment_date[:4]}/{output_path.name}",
            "latest_summary": f"{args.adjustment_date[:4]}/{summary_path.name}",
            "adjustment_date": args.adjustment_date,
            "updated_at": snapshot["updated_at"],
        },
    )
    print(output_path)


def command_validate_json(args: argparse.Namespace) -> None:
    paths = [Path(path) for path in args.paths]
    if not paths:
        paths = [path for path in ROOT.rglob("*.json") if ".git" not in path.parts]
    for path in paths:
        json.loads(path.read_text(encoding="utf-8"))
    print(f"valid json files: {len(paths)}")


def command_lookup_price(args: argparse.Namespace) -> None:
    region_path = ROOT / "data/regions" / f"{args.province}.json"
    price_path = ROOT / "data/prices" / args.adjustment_date[:4] / f"{args.adjustment_date}.json"
    province_code = _province_code_for_slug(args.province)
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
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

    raise SystemExit(f"zone not found in {price_path}: {zone['zone_code']}")


def command_run_pipeline(args: argparse.Namespace) -> None:
    discover_args = argparse.Namespace(
        sources=args.sources,
        adjustment_date=args.adjustment_date,
        output=args.index,
        timeout=args.timeout,
        force=args.force,
    )
    fetch_args = argparse.Namespace(
        date=args.adjustment_date,
        index=args.index,
        timeout=args.timeout,
    )
    extract_args = argparse.Namespace(
        date=args.adjustment_date,
        index=args.index,
    )
    build_prices_args = argparse.Namespace(
        adjustment_date=args.adjustment_date,
        index=args.index,
    )

    print("[pipeline] discover")
    command_discover(discover_args)
    print("[pipeline] fetch")
    command_fetch(fetch_args)
    print("[pipeline] extract")
    command_extract(extract_args)
    print("[pipeline] price")
    command_build_prices(build_prices_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Chinese oil price data pipeline CLI.\n\n"
            "Typical flow for one adjustment date:\n"
            "  1) discover -> find official notice links\n"
            "  2) fetch    -> download raw notice pages and attachments\n"
            "  3) extract  -> parse structured price info from raw files\n"
            "  4) price    -> build / merge data/prices/{year}/{date}.json + summary\n\n"
            "You can run these steps separately, or use `pipeline` to run all in order."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser(
        "discover",
        help="Discover notice URLs from source registry.",
        description=(
            "Discover official notice links for a target date and write index JSON.\n\n"
            "Output defaults to:\n"
            "  tmp/notices/{date}/index.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    discover.add_argument(
        "--sources",
        default="data/sources/provinces.json",
        help="Path to source registry JSON. Default: %(default)s",
    )
    discover.add_argument(
        "date",
        help="Adjustment date (YYYY-MM-DD). Used for filtering and default index path.",
    )
    discover.add_argument(
        "--output",
        help="Custom index output path (overrides default tmp/notices/{date}/index.json).",
    )
    discover.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout in seconds. Default: %(default)s",
    )
    discover.add_argument(
        "--force",
        action="store_true",
        help="Ignore summary incremental skip and force discover for configured sources.",
    )
    discover.set_defaults(func=command_discover)

    fetch = subparsers.add_parser(
        "fetch",
        help="Fetch raw notice pages/attachments from index.",
        description=(
            "Read discovered notices from index.json and download raw HTML/files.\n\n"
            "Input index defaults to:\n"
            "  tmp/notices/{date}/index.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    fetch.add_argument(
        "date",
        help="Adjustment date (YYYY-MM-DD). Used to resolve default index path.",
    )
    fetch.add_argument(
        "--index",
        help="Explicit index path. If omitted, derive from --date.",
    )
    fetch.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout in seconds. Default: %(default)s",
    )
    fetch.set_defaults(func=command_fetch)

    extract = subparsers.add_parser(
        "extract",
        help="Extract text and structured prices from fetched files.",
        description=(
            "Read fetched raw files and parse structured prices into extracted JSON.\n\n"
            "Input index defaults to:\n"
            "  tmp/notices/{date}/index.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    extract.add_argument(
        "date",
        help="Adjustment date (YYYY-MM-DD). Used to resolve default index path.",
    )
    extract.add_argument(
        "--index",
        help="Explicit index path. If omitted, derive from --date.",
    )
    extract.set_defaults(func=command_extract)

    build_prices_cmd = subparsers.add_parser(
        "price",
        help="Build/merge data/prices snapshot and summary.",
        description=(
            "Build price snapshot for one date from extracted notices.\n"
            "If target data/prices/{year}/{date}.json exists, merge new provinces into it.\n"
            "Also updates:\n"
            "  - data/prices/{year}/{date}.summary.json\n"
            "  - data/prices/latest.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    build_prices_cmd.add_argument("adjustment_date", help="Adjustment date (YYYY-MM-DD).")
    build_prices_cmd.add_argument(
        "--index",
        help="Explicit index path. If omitted, derive from adjustment_date.",
    )
    build_prices_cmd.set_defaults(func=command_build_prices)

    validate = subparsers.add_parser(
        "validate-json",
        help="Validate JSON syntax.",
        description=(
            "Validate JSON syntax for selected files.\n"
            "If no path is provided, scan all *.json under repository."
        ),
    )
    validate.add_argument("paths", nargs="*", help="Optional JSON file paths.")
    validate.set_defaults(func=command_validate_json)

    lookup = subparsers.add_parser(
        "lookup-price",
        help="Lookup price by area/province/date.",
        description="Resolve an area to zone and query the matching price snapshot.",
    )
    lookup.add_argument("area", help="Area/city/county name.")
    lookup.add_argument("--province", default="sichuan", help="Province slug. Default: %(default)s")
    lookup.add_argument("--parent", help="Optional parent region name for disambiguation.")
    lookup.add_argument(
        "--adjustment-date",
        default="2026-04-21",
        help="Adjustment date (YYYY-MM-DD). Default: %(default)s",
    )
    lookup.add_argument(
        "--product",
        choices=["89", "92", "95", "0"],
        help="Optional product code filter.",
    )
    lookup.set_defaults(func=command_lookup_price)

    run_pipeline = subparsers.add_parser(
        "pipeline",
        help="Run full pipeline in one command.",
        description=(
            "Run discover -> fetch -> extract -> price sequentially for one date.\n\n"
            "Equivalent to:\n"
            "  python -m oilprice.cli discover <date>\n"
            "  python -m oilprice.cli fetch <date>\n"
            "  python -m oilprice.cli extract <date>\n"
            "  python -m oilprice.cli price <date>\n\n"
            "Debug mode (ignore summary skip):\n"
            "  python -m oilprice.cli pipeline <date> --force"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    run_pipeline.add_argument("adjustment_date", help="Adjustment date (YYYY-MM-DD).")
    run_pipeline.add_argument(
        "--sources",
        default="data/sources/provinces.json",
        help="Path to source registry JSON. Default: %(default)s",
    )
    run_pipeline.add_argument(
        "--index",
        help="Custom index path shared by discover/fetch/extract.",
    )
    run_pipeline.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout in seconds for discover/fetch. Default: %(default)s",
    )
    run_pipeline.add_argument(
        "--force",
        action="store_true",
        help="Pass through to discover: ignore summary incremental skip.",
    )
    run_pipeline.set_defaults(func=command_run_pipeline)

    return parser


def _slug_from_notice(notice: dict[str, object]) -> str:
    notice_id = str(notice["notice_id"])
    digest = hashlib.sha1(str(notice["province_code"]).encode("utf-8")).hexdigest()[:8]
    return notice_id.split("-", 1)[0] or digest


def _notice_index_path(args: argparse.Namespace) -> Path:
    explicit_index = getattr(args, "index", None)
    if explicit_index:
        return ROOT / explicit_index

    explicit_output = getattr(args, "output", None)
    if explicit_output:
        return ROOT / explicit_output

    adjustment_date = getattr(args, "date", None) or getattr(args, "adjustment_date", None)
    if adjustment_date:
        return ROOT / "tmp/notices" / adjustment_date / "index.json"

    return ROOT / "tmp/notices/index.json"


def _filter_notices_for_adjustment_date(
    notices: list[dict[str, object]],
    adjustment_date: str,
) -> list[dict[str, object]]:
    markers = _date_markers_for_adjustment_window(adjustment_date)
    filtered = []
    for notice in notices:
        haystack = " ".join(
            str(notice.get(key, ""))
            for key in ("title", "source_url", "notice_id", "published_at")
        )
        if any(marker in haystack for marker in markers):
            filtered.append(notice)
    return filtered


def _non_padded_date_path(adjustment_date: str) -> str:
    year, month, day = adjustment_date.split("-")
    return f"{year}/{int(month)}/{int(day)}"


def _date_markers_for_adjustment_window(adjustment_date: str) -> set[str]:
    base_day = date.fromisoformat(adjustment_date)
    markers: set[str] = set()
    for day in (base_day, base_day + timedelta(days=1)):
        iso_text = day.isoformat()
        month = day.month
        day_of_month = day.day
        markers.update(
            {
                iso_text,
                iso_text.replace("-", ""),
                iso_text.replace("-", "/"),
                _non_padded_date_path(iso_text),
                f"{month:02d}/{day_of_month:02d}",
                f"{month}/{day_of_month}",
                f"{month:02d}-{day_of_month:02d}",
                f"{month}-{day_of_month}",
            }
        )
    return markers


def _province_code_for_slug(slug: str) -> str | None:
    source_path = ROOT / "data/sources/provinces.json"
    if not source_path.exists():
        return None
    payload = read_json(source_path)
    for province in payload.get("provinces", []):
        if province.get("slug") == slug:
            return str(province["province_code"])
    return None


def _build_price_summary(snapshot: dict[str, object], price_path: Path) -> dict[str, object]:
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


def _pending_province_codes_from_summary(adjustment_date: str) -> set[str] | None:
    summary_path = ROOT / "data/prices" / adjustment_date[:4] / f"{adjustment_date}.summary.json"
    if not summary_path.exists():
        return None

    summary = read_json(summary_path)
    raw_missing = summary.get("provinces_missing")
    if not isinstance(raw_missing, list):
        return None
    return {str(code).strip() for code in raw_missing if str(code).strip()}


def _merge_price_snapshots(existing: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    merged = dict(existing)

    for key in ("adjustment_date", "effective_from", "timezone", "unit", "currency"):
        if key in incoming:
            merged[key] = incoming[key]

    existing_map: dict[str, dict[str, object]] = {}
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
    merged["products"] = _collect_products_from_provinces(merged_provinces)
    merged["updated_at"] = incoming.get("updated_at", now_china_iso())
    return merged


def _collect_products_from_provinces(provinces: list[dict[str, object]]) -> list[str]:
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


def _pdf_attachment_from_viewer_url(source_url: str) -> dict[str, str] | None:
    parsed = urlparse(source_url)
    if not parsed.path.endswith("/viewer.html"):
        return None
    file_values = parse_qs(parsed.query).get("file")
    if not file_values:
        return None
    raw_file = unquote(file_values[0])
    if not raw_file.lower().endswith(".pdf"):
        return None
    pdf_url = urljoin(source_url, raw_file)
    name = raw_file.rsplit("/", 1)[-1] or "attachment.pdf"
    return {"url": pdf_url, "name": name}


def _notice_request_headers(notice: dict[str, object]) -> dict[str, str] | None:
    cookie = str(notice.get("cookie") or "").strip()
    if not cookie:
        return None
    return {"Cookie": cookie}


def _normalize_parsed_prices(parsed: dict[str, object]) -> dict[str, object]:
    normalized = dict(parsed)

    extracted_prices = parsed.get("extracted_prices")
    if isinstance(extracted_prices, dict):
        rounded_prices: dict[str, float] = {}
        for product, value in extracted_prices.items():
            rounded = _round_price_value(value)
            if rounded is not None:
                rounded_prices[str(product)] = rounded
        normalized["extracted_prices"] = rounded_prices

    zones = parsed.get("extracted_zones")
    if isinstance(zones, list):
        rounded_zones: list[dict[str, object]] = []
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            zone_copy = dict(zone)
            items = zone.get("items")
            if isinstance(items, dict):
                rounded_items: dict[str, float] = {}
                for product, value in items.items():
                    rounded = _round_price_value(value)
                    if rounded is not None:
                        rounded_items[str(product)] = rounded
                zone_copy["items"] = rounded_items
            rounded_zones.append(zone_copy)
        normalized["extracted_zones"] = rounded_zones

    return normalized


def _round_price_value(value: object) -> float | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return float(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _save_notice_html(
    notice: dict[str, object],
    raw_path: Path,
    *,
    timeout: int,
    headers: dict[str, str] | None,
) -> tuple[str, str | None]:
    source_url = str(notice["source_url"])
    if _should_fetch_notice_with_playwright(notice):
        try:
            return _fetch_hubei_notice_with_playwright(source_url, raw_path, timeout=timeout)
        except Exception as exc:
            print(f"[warn] Playwright fetch failed for {source_url}; fallback to direct HTTP: {exc}")
    return save_raw(
        source_url,
        raw_path,
        timeout=timeout,
        headers=headers,
    )


def _should_fetch_notice_with_playwright(notice: dict[str, object]) -> bool:
    if str(notice.get("detail_fetch") or "").strip().lower() != "playwright":
        return False
    source_url = str(notice.get("source_url") or "").strip()
    if not source_url:
        return False
    parsed = urlparse(source_url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _fetch_page_html_with_playwright(
    source_url: str,
    *,
    timeout: int,
) -> str:
    result = fetch_page_html(source_url, timeout_seconds=timeout)
    return result.html


def _fetch_notice_with_playwright(
    source_url: str,
    raw_path: Path,
    *,
    timeout: int,
) -> tuple[str, str | None]:
    html = _fetch_page_html_with_playwright(source_url, timeout=timeout)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(html, encoding="utf-8")

    content = raw_path.read_bytes()
    return hashlib.sha256(content).hexdigest(), "text/html"


def _fetch_hubei_notice_with_playwright(
    source_url: str,
    raw_path: Path,
    *,
    timeout: int,
) -> tuple[str, str | None]:
    return _fetch_notice_with_playwright(source_url, raw_path, timeout=timeout)


def _should_ocr_attachment(
    notice: dict[str, object],
    attachment: dict[str, object],
    attachment_path: Path,
) -> bool:
    if notice.get("adapter") not in {"hebei", "guizhou", "shaanxi", "qinghai", "heilongjiang"}:
        return False
    if attachment.get("type") == "image":
        return True
    return attachment_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
