from __future__ import annotations

import argparse
import logging

from .adapters.discovery_enhancers import discover_with_enhancer
from .adapters.generic import discover_from_html
from .crawl.browser_client import fetch_page_html
from .fetching import fetch_rendered_list_html_with_browser
from .io import emit_result, now_china_iso, write_json
from .notices import (
    SkipReason,
    filter_notices_for_adjustment_date,
    pending_province_codes_from_summary,
    province_skip_reason,
)
from .options import DiscoverOptions
from .payloads import EnabledSource, NoticePayload, SourceConfig
from .sources import load_enabled_sources


logger = logging.getLogger(__name__)


class DiscoveryError(Exception):
    def __init__(self, url: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.url = url
        self.cause = cause


class EnhancerDiscoveryError(DiscoveryError):
    pass


class BrowserDiscoveryError(DiscoveryError):
    pass


class ParseDiscoveryError(DiscoveryError):
    pass


def command_discover(args: argparse.Namespace) -> None:
    index_path = run_discover(DiscoverOptions.from_args(args))
    emit_result(index_path)


def validate_requested_province_codes(
    enabled_sources: list[EnabledSource],
    requested_codes: set[str] | None,
) -> None:
    if requested_codes is None:
        return

    configured_codes = {str(item["province_code"]) for item in enabled_sources}
    missing_codes = sorted(requested_codes - configured_codes)
    if missing_codes:
        raise ValueError(
            "no enabled source configured for province code(s): " + ", ".join(missing_codes)
        )


def run_discover(options: DiscoverOptions) -> str:
    enabled_sources = load_enabled_sources(options.sources_path)
    validate_requested_province_codes(enabled_sources, options.province_codes)
    pending_codes: set[str] | None = None
    if options.adjustment_date and not options.force:
        pending_codes = pending_province_codes_from_summary(options.adjustment_date)
    notices: list[NoticePayload] = []
    errors: list[dict[str, str]] = []

    for item in enabled_sources:
        province_code = str(item["province_code"])
        skip_reason = province_skip_reason(province_code, options.province_codes, pending_codes)
        if skip_reason == SkipReason.NOT_SELECTED:
            continue
        if skip_reason == SkipReason.NOT_PENDING:
            logger.info(
                f"[skip] {item['province_name']} ({province_code}) is not pending for "
                f"{options.adjustment_date}"
            )
            continue
        source = item["source"]
        keywords = source.get("notice_keywords") or ["成品油", "汽油", "柴油"]
        enhancer = str(source.get("discovery_enhancer") or "")
        rendered_list_fallback = bool(source.get("rendered_list_fallback"))
        for list_url in source["list_urls"]:
            if enhancer:
                try:
                    refs = _discover_with_enhancer(
                        item,
                        source,
                        list_url,
                        enhancer=enhancer,
                        keywords=keywords,
                        options=options,
                    )
                except EnhancerDiscoveryError as exc:
                    logger.warning(
                        f"[skip] {item['province_name']}: enhancer error {exc.cause} for {exc.url}"
                    )
                    errors.append(_discovery_error_payload(item, source, "enhancer", exc))
                    continue
            else:
                try:
                    html = _fetch_list_html(
                        list_url,
                        rendered_list_fallback=rendered_list_fallback,
                        options=options,
                    )
                except BrowserDiscoveryError as exc:
                    logger.warning(
                        f"[skip] {item['province_name']}: browser error {exc.cause} for {exc.url}"
                    )
                    errors.append(_discovery_error_payload(item, source, "browser", exc))
                    continue
                try:
                    refs = _parse_list_html(item, html, list_url, keywords)
                    if not refs and rendered_list_fallback:
                        rendered_html = _fetch_rendered_list_html(list_url, options=options)
                        refs = _parse_list_html(item, rendered_html, list_url, keywords)
                except BrowserDiscoveryError as exc:
                    logger.warning(
                        f"[skip] {item['province_name']}: browser error {exc.cause} for {exc.url}"
                    )
                    errors.append(_discovery_error_payload(item, source, "browser", exc))
                    continue
                except ParseDiscoveryError as exc:
                    logger.warning(
                        f"[skip] {item['province_name']}: parse error {exc.cause} for {exc.url}"
                    )
                    errors.append(_discovery_error_payload(item, source, "parse", exc))
                    continue
            for ref in refs:
                notice: NoticePayload = {
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
                if source.get("rendered_notice_fallback"):
                    notice["rendered_notice_fallback"] = True
                if source.get("ocr_attachments"):
                    notice["ocr_attachments"] = True
                if ref.published_at:
                    notice["published_at"] = ref.published_at
                notices.append(notice)

    if options.adjustment_date:
        notices = filter_notices_for_adjustment_date(notices, options.adjustment_date)

    write_json(
        options.index_path,
        {
            "updated_at": now_china_iso(),
            "notices": notices,
            "errors": errors,
        },
    )
    return str(options.index_path)


def _discovery_error_payload(
    item: EnabledSource,
    source: SourceConfig,
    stage: str,
    error: DiscoveryError,
) -> dict[str, str]:
    return {
        "province_code": str(item["province_code"]),
        "province_name": str(item["province_name"]),
        "source_name": str(source.get("name") or item["province_name"]),
        "stage": stage,
        "url": error.url,
        "error_type": type(error).__name__,
        "cause_type": type(error.cause).__name__,
        "message": str(error.cause),
    }


def _discover_with_enhancer(
    item: EnabledSource,
    source: SourceConfig,
    list_url: str,
    *,
    enhancer: str,
    keywords: list[str],
    options: DiscoverOptions,
):
    try:
        return discover_with_enhancer(
            enhancer,
            source=source,
            list_url=list_url,
            province_code=item["province_code"],
            province_name=item["province_name"],
            province_slug=item["slug"],
            keywords=keywords,
            timeout=options.timeout,
            browser_session=options.browser_session,
        )
    except Exception as exc:
        raise EnhancerDiscoveryError(list_url, exc) from exc


def _fetch_list_html(
    list_url: str,
    *,
    rendered_list_fallback: bool,
    options: DiscoverOptions,
) -> str:
    try:
        return fetch_page_html(
            list_url,
            timeout_seconds=options.timeout,
            browser_session=options.browser_session,
        ).html
    except Exception as exc:
        if not rendered_list_fallback:
            raise BrowserDiscoveryError(list_url, exc) from exc
        try:
            return fetch_rendered_list_html_with_browser(
                list_url,
                timeout=options.timeout,
                browser_session=options.browser_session,
            )
        except Exception as fallback_exc:
            raise BrowserDiscoveryError(list_url, fallback_exc) from fallback_exc


def _fetch_rendered_list_html(list_url: str, *, options: DiscoverOptions) -> str:
    try:
        return fetch_rendered_list_html_with_browser(
            list_url,
            timeout=options.timeout,
            browser_session=options.browser_session,
        )
    except Exception as exc:
        raise BrowserDiscoveryError(list_url, exc) from exc


def _parse_list_html(
    item: EnabledSource,
    html: str,
    list_url: str,
    keywords: list[str],
):
    try:
        return discover_from_html(
            html=html,
            list_url=list_url,
            province_code=item["province_code"],
            province_name=item["province_name"],
            province_slug=item["slug"],
            keywords=keywords,
        )
    except Exception as exc:
        raise ParseDiscoveryError(list_url, exc) from exc
