from __future__ import annotations

import base64
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .browser_runtime import (
    block_heavy_resources,
    capture_settled_html,
    close_browser,
    close_page,
    launch_browser,
    new_context,
)


@dataclass(frozen=True)
class BrowserFetchResult:
    html: str
    status: int | None
    final_url: str
    title: str
    bytes: int


class BrowserSession:
    def __init__(self, *, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.context = None

    def __enter__(self) -> "BrowserSession":
        self.browser = launch_browser(headless=self.headless)
        self.context = new_context(self.browser)
        block_heavy_resources(self.context)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None
        if self.browser is not None:
            close_browser(self.browser)
            self.browser = None

    def new_page(self):
        if self.browser is None:
            raise RuntimeError("BrowserSession is not open")
        if self.context is not None:
            return self.context.new_page()
        return self.browser.new_page()

    def fetch_page_html(
        self,
        source_url: str,
        *,
        timeout_seconds: int,
    ) -> BrowserFetchResult:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"invalid source url: {source_url}")

        timeout_ms = max(timeout_seconds, 1) * 1000
        page = self.new_page()
        try:
            response = page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            content = capture_settled_html(page, timeout_ms=timeout_ms)
            status = response.status if response else None
            final_url = page.url
            title = ""
            try:
                title = page.title()
            except Exception:
                title = ""
            if not content.strip():
                raise RuntimeError(
                    f"browser fetched empty content (status={status}, final_url={final_url})"
                )
            return BrowserFetchResult(
                html=content,
                status=status,
                final_url=final_url,
                title=title,
                bytes=len(content.encode("utf-8")),
            )
        finally:
            close_page(page)

    def fetch_text(
        self,
        source_url: str,
        *,
        timeout_seconds: int = 30,
        referer: str | None = None,
    ) -> str:
        data = self.fetch_bytes(
            source_url,
            timeout_seconds=timeout_seconds,
            referer=referer,
            validate_binary=False,
        )
        return data.decode("utf-8", errors="replace")

    def fetch_json(
        self,
        source_url: str,
        *,
        timeout_seconds: int = 30,
        referer: str | None = None,
    ) -> dict[str, object]:
        return json.loads(
            self.fetch_text(
                source_url,
                timeout_seconds=timeout_seconds,
                referer=referer,
            )
        )

    def fetch_bytes(
        self,
        source_url: str,
        *,
        timeout_seconds: int = 30,
        referer: str | None = None,
        validate_binary: bool = True,
    ) -> bytes:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"invalid source url: {source_url}")

        timeout_ms = max(timeout_seconds, 1) * 1000
        data = _fetch_bytes_with_context_request(
            self.context,
            source_url,
            timeout_ms=timeout_ms,
            referer=referer,
        )
        if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
            return data

        page = self.new_page()
        try:
            if referer:
                try:
                    data = _fetch_direct_response_body(
                        page,
                        source_url,
                        timeout_ms=timeout_ms,
                    )
                    if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
                        return data
                except Exception:
                    pass
            if referer:
                try:
                    page.goto(referer, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(500)
                    data = _fetch_bytes_from_page_context(page, source_url)
                    if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
                        return data
                    data = _download_link_from_page(page, source_url, timeout_ms=timeout_ms)
                    if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
                        return data
                except Exception:
                    pass
            response = page.goto(source_url, wait_until="commit", timeout=timeout_ms)
            if response is None:
                raise RuntimeError(f"browser did not return a response for {source_url}")
            status = response.status
            if status and status >= 400:
                if not validate_binary:
                    data = response.body()
                    if data:
                        return data
                raise RuntimeError(f"browser fetch failed with HTTP {status} for {source_url}")
            data = response.body()
            if validate_binary and not _looks_like_binary_payload(source_url, data):
                raise RuntimeError(f"browser returned non-binary attachment content for {source_url}")
            return data
        finally:
            close_page(page)


def _download_link_from_page(page, source_url: str, *, timeout_ms: int) -> bytes | None:
    filename = unquote_path_name(source_url)
    selector = f'a[href*="{filename}"]'
    link = page.locator(selector).first
    try:
        if link.count() < 1:
            return None
    except Exception:
        return None

    try:
        link.evaluate("(node) => node.removeAttribute('target')")
    except Exception:
        pass

    try:
        with page.expect_download(timeout=timeout_ms) as download_info:
            link.click(timeout=timeout_ms)
        download = download_info.value
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            download.save_as(str(tmp_path))
            return tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception:
        return None


def _fetch_bytes_with_context_request(
    context,
    source_url: str,
    *,
    timeout_ms: int,
    referer: str | None,
) -> bytes | None:
    if context is None or not hasattr(context, "request"):
        return None
    headers = {"Referer": referer} if referer else None
    try:
        response = context.request.get(source_url, headers=headers, timeout=timeout_ms)
    except Exception:
        return None
    try:
        if not response.ok:
            return None
        return response.body()
    except Exception:
        return None


def _fetch_direct_response_body(page, source_url: str, *, timeout_ms: int) -> bytes | None:
    response = page.goto(source_url, wait_until="commit", timeout=timeout_ms)
    if response is None:
        return None
    status = response.status
    if status and status >= 400:
        return None
    return response.body()


def _fetch_bytes_from_page_context(page, source_url: str) -> bytes | None:
    try:
        result = page.evaluate(
            """async (url) => {
                const resp = await fetch(url, {
                    credentials: "include",
                    cache: "no-store",
                    headers: {
                        "Accept": "application/pdf,application/octet-stream,*/*"
                    }
                });
                const buffer = await resp.arrayBuffer();
                let binary = "";
                const bytes = new Uint8Array(buffer);
                for (let i = 0; i < bytes.byteLength; i += 1) {
                    binary += String.fromCharCode(bytes[i]);
                }
                return {
                    ok: resp.ok,
                    status: resp.status,
                    contentType: resp.headers.get("content-type") || "",
                    body: btoa(binary)
                };
            }""",
            source_url,
        )
    except Exception:
        return None
    if not result or not result.get("ok"):
        return None
    try:
        return base64.b64decode(str(result.get("body") or ""))
    except Exception:
        return None


def _looks_like_binary_payload(source_url: str, data: bytes | None) -> bool:
    if not data:
        return False
    suffix = urlparse(source_url).path.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        return data.startswith(b"%PDF")
    if suffix in {"xls", "doc"}:
        return data.startswith(b"\xd0\xcf\x11\xe0")
    if suffix in {"xlsx", "docx"}:
        return data.startswith(b"PK\x03\x04")
    if suffix in {"png"}:
        return data.startswith(b"\x89PNG")
    if suffix in {"jpg", "jpeg"}:
        return data.startswith(b"\xff\xd8")
    if suffix in {"gif"}:
        return data.startswith((b"GIF87a", b"GIF89a"))
    return not data.lstrip()[:20].lower().startswith((b"<!doctype", b"<html"))


def unquote_path_name(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])
