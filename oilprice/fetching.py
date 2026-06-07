from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .crawl.browser_client import (
    BrowserSession,
    fetch_bytes_with_browser,
    fetch_page_html,
    fetch_text_with_browser,
)
from .errors import AttachmentFetchError
from .payloads import AttachmentPayload, NoticePayload


logger = logging.getLogger(__name__)


def save_attachment_raw(
    url: str,
    path: Path,
    *,
    timeout: int,
    referer: str | None = None,
    browser_session: BrowserSession | None = None,
) -> str | None:
    """Download an attachment with CloakBrowser."""
    try:
        data = fetch_bytes_with_browser(
            url,
            timeout_seconds=timeout,
            referer=referer,
            browser_session=browser_session,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()
    except Exception as exc:
        error = AttachmentFetchError(url, exc)
        logger.warning("[warn] %s", error)
        return None


def pdf_attachment_from_viewer_url(source_url: str) -> dict[str, str] | None:
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


def fetch_rendered_list_html_with_browser(
    source_url: str,
    *,
    timeout: int,
    browser_session: BrowserSession | None = None,
) -> str:
    timeout_ms = max(timeout, 1) * 1000
    if browser_session is None:
        with BrowserSession(headless=True) as session:
            return fetch_fast_rendered_html(
                source_url,
                timeout_ms=timeout_ms,
                browser_session=session,
            )
    return fetch_fast_rendered_html(
        source_url,
        timeout_ms=timeout_ms,
        browser_session=browser_session,
    )


def fetch_fast_rendered_html(
    source_url: str,
    *,
    timeout_ms: int,
    browser_session: BrowserSession,
) -> str:
    page = browser_session.new_page()
    try:
        page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(800)
        return page.content()
    finally:
        try:
            page.close()
        except Exception:
            pass


def fetch_notice_with_browser(
    source_url: str,
    raw_path: Path,
    *,
    timeout: int,
    browser_session: BrowserSession | None = None,
    rendered_fallback: bool = False,
) -> str:
    html = fetch_notice_html_with_browser(
        source_url,
        timeout=timeout,
        browser_session=browser_session,
        rendered_fallback=rendered_fallback,
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(html, encoding="utf-8")

    content = raw_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def fetch_notice_html_with_browser(
    source_url: str,
    *,
    timeout: int,
    browser_session: BrowserSession | None = None,
    rendered_fallback: bool = False,
) -> str:
    if rendered_fallback:
        return fetch_page_html(
            source_url,
            timeout_seconds=timeout,
            browser_session=browser_session,
        ).html
    try:
        return fetch_text_with_browser(
            source_url,
            timeout_seconds=timeout,
            browser_session=browser_session,
        )
    except Exception:
        if not rendered_fallback:
            raise
        timeout_ms = max(timeout, 1) * 1000
        if browser_session is None:
            with BrowserSession(headless=True) as session:
                return fetch_fast_rendered_html(
                    source_url,
                    timeout_ms=timeout_ms,
                    browser_session=session,
                )
        return fetch_fast_rendered_html(
            source_url,
            timeout_ms=timeout_ms,
            browser_session=browser_session,
        )


def should_ocr_attachment(
    notice: NoticePayload,
    attachment: AttachmentPayload,
    attachment_path: Path,
) -> bool:
    if not notice.get("ocr_attachments"):
        return False
    if attachment.get("type") == "image":
        return True
    return attachment_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def should_fetch_attachment(
    notice: NoticePayload,
    attachment: AttachmentPayload,
    attachment_path: Path,
) -> bool:
    if attachment.get("type") != "image":
        return True
    return should_ocr_attachment(notice, attachment, attachment_path)
