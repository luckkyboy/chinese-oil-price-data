from __future__ import annotations

import hashlib
import ipaddress
import logging
import socket
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .crawl.browser_client import (
    BrowserSession,
    fetch_bytes_with_browser,
    fetch_page_html,
    fetch_text_with_browser,
)
from .errors import AttachmentFetchError, BrowserHTTPError
from .payloads import AttachmentPayload, NoticePayload


logger = logging.getLogger(__name__)
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


def save_attachment_raw(
    url: str,
    path: Path,
    *,
    timeout: int,
    referer: str | None = None,
    browser_session: BrowserSession | None = None,
    max_bytes: int = MAX_ATTACHMENT_BYTES,
) -> str:
    """Download an attachment with CloakBrowser."""
    try:
        validate_attachment_url(url)
        data = fetch_bytes_with_browser(
            url,
            timeout_seconds=timeout,
            referer=referer,
            browser_session=browser_session,
            max_bytes=max_bytes,
            url_validator=validate_attachment_url,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()
    except Exception as exc:
        error = AttachmentFetchError(url, exc)
        logger.warning("[warn] %s", error)
        raise error from exc


def validate_attachment_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        scheme = parsed.scheme or "<missing>"
        raise ValueError(f"unsupported attachment URL scheme: {scheme}")
    if not parsed.netloc:
        raise ValueError(f"attachment URL has no host: {url}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("attachment URL must not contain credentials")
    try:
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid attachment URL: {url}") from exc
    if not hostname:
        raise ValueError(f"attachment URL has no host: {url}")

    normalized_host = hostname.rstrip(".").lower()
    if normalized_host in {"localhost", "localhost.localdomain"} or normalized_host.endswith(
        ".localhost"
    ):
        raise ValueError(f"local attachment host is not allowed: {hostname}")

    address_host = normalized_host.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(address_host)
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.inet_aton(address_host))
        except OSError:
            if normalized_host.isdecimal():
                raise ValueError(
                    f"non-standard numeric attachment host is not allowed: {hostname}"
                )
            _validate_resolved_attachment_host(normalized_host, parsed.port)
            return
    _require_global_attachment_address(address, hostname)


def _validate_resolved_attachment_host(hostname: str, port: int | None) -> None:
    try:
        addresses = socket.getaddrinfo(
            hostname,
            port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError(f"attachment host cannot be resolved safely: {hostname}") from exc
    if not addresses:
        raise ValueError(f"attachment host has no resolved addresses: {hostname}")

    for address_info in addresses:
        socket_address = address_info[4]
        if not socket_address:
            raise ValueError(f"attachment host has an invalid DNS result: {hostname}")
        raw_address = str(socket_address[0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ValueError(
                f"attachment host resolved to an invalid address: {hostname} -> {raw_address}"
            ) from exc
        _require_global_attachment_address(address, f"{hostname} -> {raw_address}")


def _require_global_attachment_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    label: str,
) -> None:
    if not address.is_global:
        raise ValueError(f"non-public attachment IP is not allowed: {label}")


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
        response = page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
        status = response.status if response else None
        if status is not None and status >= 400:
            raise BrowserHTTPError(source_url, status)
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
    try:
        return fetch_text_with_browser(
            source_url,
            timeout_seconds=timeout,
            browser_session=browser_session,
        )
    except Exception:
        if not rendered_fallback:
            raise
        return fetch_page_html(
            source_url,
            browser_session=browser_session,
            timeout_seconds=timeout,
        ).html


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
