from __future__ import annotations

import argparse
import logging
import time

from .extract.attachments import attachment_suffix, find_attachment_links
from .fetching import (
    fetch_notice_with_browser,
    pdf_attachment_from_viewer_url,
    save_attachment_raw,
    should_fetch_attachment,
)
from .io import emit_result, now_china_iso, read_json, repo_relative, write_json
from .notices import (
    SkipReason,
    pending_province_codes_from_summary,
    province_skip_reason,
    slug_from_notice,
)
from .options import FetchOptions
from .payloads import AttachmentPayload, NoticePayload
from .paths import ROOT


logger = logging.getLogger(__name__)


def command_fetch(args: argparse.Namespace) -> None:
    index_path = run_fetch(FetchOptions.from_args(args))
    emit_result(index_path)


def run_fetch(options: FetchOptions) -> str:
    notice_root = options.index_path.parent
    index = read_json(options.index_path)
    fetched: list[NoticePayload] = []
    pending_codes: set[str] | None = None
    if options.adjustment_date and not options.force:
        pending_codes = pending_province_codes_from_summary(options.adjustment_date)

    for notice in index.get("notices", []):
        province_code = str(notice.get("province_code", "") or "")
        skip_reason = province_skip_reason(province_code, options.province_codes, pending_codes)
        if skip_reason == SkipReason.NOT_SELECTED:
            fetched.append(notice)
            continue
        if skip_reason == SkipReason.NOT_PENDING:
            logger.info(
                f"[skip] {notice.get('province_name', province_code)} ({province_code}) "
                f"is not pending for {options.adjustment_date}"
            )
            fetched.append(notice)
            continue

        province_slug = slug_from_notice(notice)
        notice_id = notice["notice_id"]
        raw_path = notice_root / "raw" / province_slug / f"{notice_id}.html"
        notice_start = time.perf_counter()
        sha256 = fetch_notice_with_browser(
            str(notice["source_url"]),
            raw_path=raw_path,
            timeout=options.timeout,
            browser_session=options.browser_session,
            rendered_fallback=bool(notice.get("rendered_notice_fallback")),
        )
        logger.info(
            f"[fetch] {notice.get('province_name', province_code)} ({province_code}) "
            f"notice_html elapsed={_elapsed(notice_start)} url={notice.get('source_url')}"
        )
        raw_html = raw_path.read_text(encoding="utf-8", errors="replace")
        attachments: list[AttachmentPayload] = []
        embedded_pdf = pdf_attachment_from_viewer_url(str(notice["source_url"]))
        if embedded_pdf:
            url = embedded_pdf["url"]
            attachment_path = (
                notice_root
                / "raw"
                / province_slug
                / f"{notice_id}_attachment_1{attachment_suffix(url)}"
            )
            result = save_attachment_raw(
                url,
                attachment_path,
                timeout=options.timeout,
                referer=str(notice["source_url"]),
                browser_session=options.browser_session,
            )
            if result:
                attachments.append(
                    {
                        "url": url,
                        "name": embedded_pdf.get("name"),
                        "type": "document",
                        "path": repo_relative(attachment_path, ROOT),
                        "sha256": result,
                    }
                )
        discovered_attachments = find_attachment_links(raw_html, notice["source_url"])
        skipped_attachments = 0
        logger.info(
            f"[fetch] {notice.get('province_name', province_code)} ({province_code}) "
            f"attachments discovered={len(discovered_attachments)}"
        )
        for index_number, attachment in enumerate(
            discovered_attachments,
            start=len(attachments) + 1,
        ):
            suffix = attachment_suffix(attachment["url"])
            attachment_path = (
                notice_root
                / "raw"
                / province_slug
                / f"{notice_id}_attachment_{index_number}{suffix}"
            )
            if not should_fetch_attachment(notice, attachment, attachment_path):
                skipped_attachments += 1
                continue
            attachment_start = time.perf_counter()
            result = save_attachment_raw(
                attachment["url"],
                attachment_path,
                timeout=options.timeout,
                referer=str(notice["source_url"]),
                browser_session=options.browser_session,
            )
            if not result:
                continue
            logger.info(
                f"[fetch] {notice.get('province_name', province_code)} ({province_code}) "
                f"attachment elapsed={_elapsed(attachment_start)} url={attachment['url']}"
            )
            attachment_payload: AttachmentPayload = {
                "url": attachment["url"],
                "name": attachment.get("name"),
                "type": attachment.get("type"),
                "path": repo_relative(attachment_path, ROOT),
                "sha256": result,
            }
            attachments.append(
                {key: value for key, value in attachment_payload.items() if value is not None}
            )
        updated = dict(notice)
        updated["raw_path"] = repo_relative(raw_path, ROOT)
        updated["sha256"] = sha256
        if attachments:
            updated["attachments"] = attachments
        if skipped_attachments:
            logger.info(
                f"[fetch] {notice.get('province_name', province_code)} ({province_code}) "
                f"attachments skipped={skipped_attachments}"
            )
        fetched.append(updated)

    write_json(options.index_path, {"updated_at": now_china_iso(), "notices": fetched})
    return str(options.index_path)


def _elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.1f}s"
