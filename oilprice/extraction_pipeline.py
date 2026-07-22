from __future__ import annotations

import argparse
import logging
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable

from .extract.doc import doc_to_text
from .extract.docx import docx_to_text
from .extract.html import html_to_text
from .extract.pdf import pdf_to_text
from .extract.xls import xls_to_text
from .errors import OcrError, TextExtractionError
from .fetching import should_ocr_attachment
from .io import emit_result, now_china_iso, read_json, repo_relative, write_json
from .notices import (
    pending_province_codes_from_summary,
    province_skip_reason,
    SkipReason,
    slug_from_notice,
)
from .ocr.paddle import image_to_text
from .options import ExtractFilesOptions
from .payloads import AttachmentPayload, NoticePayload, ParsedNoticePayload, ZonePayload
from .paths import ROOT
from .parsers import parse_notice, parser_version


logger = logging.getLogger(__name__)
DOCUMENT_TEXT_EXTRACTORS: dict[str, Callable[[Path], str]] = {
    ".doc": doc_to_text,
    ".docx": docx_to_text,
    ".pdf": pdf_to_text,
    ".xls": xls_to_text,
}


def command_extract_files(args: argparse.Namespace) -> None:
    index_path = run_extract_files(ExtractFilesOptions.from_args(args))
    emit_result(index_path)


def run_extract_files(options: ExtractFilesOptions) -> str:
    notice_root = options.index_path.parent
    index = read_json(options.index_path)
    updated_notices: list[NoticePayload] = []
    pending_codes: set[str] | None = None
    if options.adjustment_date and not options.force:
        pending_codes = pending_province_codes_from_summary(options.adjustment_date)

    for notice in index.get("notices", []):
        province_code = str(notice.get("province_code", "") or "")
        skip_reason = province_skip_reason(province_code, options.province_codes, pending_codes)
        if skip_reason == SkipReason.NOT_SELECTED:
            updated_notices.append(notice)
            continue
        if skip_reason == SkipReason.NOT_PENDING:
            logger.info(
                f"[skip] {notice.get('province_name', province_code)} ({province_code}) "
                f"is not pending for {options.adjustment_date}"
            )
            updated_notices.append(notice)
            continue

        raw_path = notice.get("raw_path")
        if not raw_path:
            updated_notices.append(notice)
            continue

        absolute_raw_path = ROOT / str(raw_path).lstrip("/")
        if not absolute_raw_path.exists():
            updated_notices.append(notice)
            continue

        notice_extract_start = time.perf_counter()
        logger.info(
            f"[extract-file] {notice.get('province_name', province_code)} ({province_code}) "
            f"html_to_text start path={raw_path}"
        )
        try:
            text = html_to_text(absolute_raw_path.read_bytes())
        except Exception as exc:
            raise TextExtractionError(str(absolute_raw_path), exc) from exc
        logger.info(
            f"[extract-file] {notice.get('province_name', province_code)} ({province_code}) "
            f"html_to_text elapsed={_elapsed(notice_extract_start)} chars={len(text)}"
        )
        province_slug = slug_from_notice(notice)
        attachment_texts = []
        updated_attachments: list[AttachmentPayload] = []
        for attachment in notice.get("attachments", []):
            updated_attachment = dict(attachment)
            updated_attachment.pop("extraction_error", None)
            attachment_path = attachment.get("path")
            if not attachment_path:
                updated_attachments.append(updated_attachment)
                continue
            absolute_attachment_path = ROOT / str(attachment_path).lstrip("/")
            attachment_extract_start = time.perf_counter()
            logger.info(
                f"[extract-file] {notice.get('province_name', province_code)} ({province_code}) "
                f"attachment_text start suffix={absolute_attachment_path.suffix.lower()} "
                f"path={attachment_path}"
            )
            suffix = absolute_attachment_path.suffix.lower()
            if attachment.get("type") == "document" and suffix not in DOCUMENT_TEXT_EXTRACTORS:
                extraction_error = _unsupported_document_extraction_error(suffix)
                updated_attachment["extraction_error"] = extraction_error
                logger.warning(
                    f"[warn] {notice.get('province_name', province_code)} ({province_code}) "
                    f"attachment extraction unsupported suffix={suffix or '<none>'} "
                    f"path={attachment_path}: {extraction_error}"
                )
            elif suffix in DOCUMENT_TEXT_EXTRACTORS:
                attachment_text = extract_attachment_text(absolute_attachment_path)
                if attachment_text:
                    attachment_texts.append(attachment_text)
            elif should_ocr_attachment(notice, attachment, absolute_attachment_path):
                try:
                    attachment_text = image_to_text(absolute_attachment_path)
                except Exception as exc:
                    updated_attachment["ocr_error"] = str(OcrError(str(absolute_attachment_path), exc))
                else:
                    if attachment_text:
                        ocr_text_path = (
                            notice_root
                            / "extracted"
                            / province_slug
                            / f"{notice['notice_id'][:64]}_{absolute_attachment_path.stem}.ocr.txt"
                        )
                        ocr_text_path.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            ocr_text_path.write_text(attachment_text, encoding="utf-8")
                        except OSError:
                            short_name = f"{notice['notice_id'][:32]}_{absolute_attachment_path.stem[-32:]}.ocr.txt"
                            ocr_text_path = ocr_text_path.with_name(short_name)
                            ocr_text_path.write_text(attachment_text, encoding="utf-8")
                        updated_attachment["ocr_text_path"] = repo_relative(ocr_text_path, ROOT)
                        attachment_texts.append(attachment_text)
            logger.info(
                f"[extract-file] {notice.get('province_name', province_code)} ({province_code}) "
                f"attachment_text elapsed={_elapsed(attachment_extract_start)} "
                f"path={attachment_path}"
            )
            updated_attachments.append(updated_attachment)
        combined_text = "\n\n".join([text, *attachment_texts])
        parse_start = time.perf_counter()
        logger.info(
            f"[extract-file] {notice.get('province_name', province_code)} ({province_code}) "
            f"parse_notice start chars={len(combined_text)}"
        )
        adapter = str(notice.get("adapter", "generic"))
        parsed = parse_notice(adapter, combined_text)
        parsed = normalize_parsed_prices(parsed)
        logger.info(
            f"[extract-file] {notice.get('province_name', province_code)} ({province_code}) "
            f"parse_notice elapsed={_elapsed(parse_start)}"
        )
        raw_sha256 = notice.get("raw_sha256") or notice.get("sha256")
        extracted_payload: NoticePayload = {
            "notice_id": notice["notice_id"],
            "province_code": notice["province_code"],
            "province_name": notice["province_name"],
            "source_name": notice.get("source_name", notice["province_name"]),
            "adapter": adapter,
            "parser_version": parser_version(adapter),
            "title": notice["title"],
            "published_at": notice.get("published_at"),
            "adjustment_date": parsed.get("adjustment_date"),
            "source_url": notice["source_url"],
            "raw_path": raw_path,
            "sha256": raw_sha256,
            "raw_sha256": raw_sha256,
            "content_text": combined_text,
            "attachments": updated_attachments,
            "extracted_prices": parsed.get("extracted_prices"),
            "extracted_zones": parsed.get("extracted_zones"),
            "confidence": parsed.get("confidence", "manual_required"),
            "extracted_at": now_china_iso(),
        }
        extracted_payload = {
            key: value for key, value in extracted_payload.items() if value is not None
        }
        extracted_path = notice_root / "extracted" / province_slug / f"{notice['notice_id']}.json"
        write_start = time.perf_counter()
        write_json(extracted_path, extracted_payload)
        logger.info(
            f"[extract-file] {notice.get('province_name', province_code)} ({province_code}) "
            f"write_extracted elapsed={_elapsed(write_start)} path={repo_relative(extracted_path, ROOT)}"
        )

        updated = dict(notice)
        updated["extracted_path"] = repo_relative(extracted_path, ROOT)
        if updated_attachments:
            updated["attachments"] = updated_attachments
        updated_notices.append(updated)

    write_json(options.index_path, {"updated_at": now_china_iso(), "notices": updated_notices})
    return str(options.index_path)


def extract_attachment_text(path: Path) -> str:
    try:
        suffix = path.suffix.lower()
        extractor = DOCUMENT_TEXT_EXTRACTORS.get(suffix)
        if extractor is None:
            raise ValueError(_unsupported_document_extraction_error(suffix))
        return extractor(path)
    except Exception as exc:
        raise TextExtractionError(str(path), exc) from exc


def _unsupported_document_extraction_error(suffix: str) -> str:
    display_suffix = suffix or "<none>"
    supported = ", ".join(sorted(DOCUMENT_TEXT_EXTRACTORS))
    return (
        f"unsupported document attachment suffix {display_suffix!r}; "
        f"supported suffixes: {supported}"
    )


def normalize_parsed_prices(parsed: ParsedNoticePayload) -> ParsedNoticePayload:
    normalized = dict(parsed)

    extracted_prices = parsed.get("extracted_prices")
    if isinstance(extracted_prices, dict):
        rounded_prices: dict[str, float] = {}
        for product, value in extracted_prices.items():
            rounded = round_price_value(value)
            if rounded is not None:
                rounded_prices[str(product)] = rounded
        normalized["extracted_prices"] = rounded_prices

    zones = parsed.get("extracted_zones")
    if isinstance(zones, list):
        rounded_zones: list[ZonePayload] = []
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            zone_copy = dict(zone)
            items = zone.get("items")
            if isinstance(items, dict):
                rounded_items: dict[str, float] = {}
                for product, value in items.items():
                    rounded = round_price_value(value)
                    if rounded is not None:
                        rounded_items[str(product)] = rounded
                zone_copy["items"] = rounded_items
            rounded_zones.append(zone_copy)
        normalized["extracted_zones"] = rounded_zones

    return normalized


def round_price_value(value: object) -> float | None:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return float(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.1f}s"
