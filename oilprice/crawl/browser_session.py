from __future__ import annotations

import base64
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlparse, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from oilprice.errors import BrowserHTTPError, ResponseTooLargeError

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
            status = response.status if response else None
            # Some government-site bot checks return their executable browser
            # challenge with HTTP 412. Let the page run that challenge and
            # validate the settled HTML at the notice-fetching boundary.
            if status is not None and status >= 400 and status != 412:
                raise BrowserHTTPError(source_url, status)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            content = capture_settled_html(page, timeout_ms=timeout_ms)
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
        max_bytes: int | None = None,
        url_validator: Callable[[str], None] | None = None,
    ) -> bytes:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"invalid source url: {source_url}")

        timeout_ms = max(timeout_seconds, 1) * 1000
        if max_bytes is not None:
            return self._fetch_bytes_bounded(
                source_url,
                timeout_ms=timeout_ms,
                referer=referer,
                validate_binary=validate_binary,
                max_bytes=max_bytes,
                url_validator=url_validator,
            )

        data = _fetch_bytes_with_context_request(
            self.context,
            source_url,
            timeout_ms=timeout_ms,
            referer=referer,
            max_bytes=max_bytes,
            url_validator=url_validator,
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
                        max_bytes=max_bytes,
                        url_validator=url_validator,
                    )
                    if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
                        return data
                except (ResponseTooLargeError, ValueError):
                    raise
                except Exception:
                    pass
            if referer:
                try:
                    page.goto(referer, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(500)
                    data = _fetch_bytes_from_page_context(
                        page,
                        source_url,
                        timeout_ms=timeout_ms,
                        max_bytes=max_bytes,
                        url_validator=url_validator,
                    )
                    if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
                        return data
                    data = _download_link_from_page(
                        page,
                        source_url,
                        timeout_ms=timeout_ms,
                        max_bytes=max_bytes,
                        url_validator=url_validator,
                    )
                    if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
                        return data
                except (ResponseTooLargeError, ValueError):
                    raise
                except Exception:
                    pass
            response = page.goto(source_url, wait_until="commit", timeout=timeout_ms)
            if response is None:
                raise RuntimeError(f"browser did not return a response for {source_url}")
            _validate_response_url(response, source_url, url_validator)
            status = response.status
            if status is not None and status >= 400:
                raise BrowserHTTPError(source_url, status)
            _reject_oversized_response(source_url, response, max_bytes)
            data = response.body()
            _reject_oversized_data(source_url, data, max_bytes)
            if validate_binary and not _looks_like_binary_payload(source_url, data):
                raise RuntimeError(f"browser returned non-binary attachment content for {source_url}")
            return data
        finally:
            close_page(page)

    def _fetch_bytes_bounded(
        self,
        source_url: str,
        *,
        timeout_ms: int,
        referer: str | None,
        validate_binary: bool,
        max_bytes: int,
        url_validator: Callable[[str], None] | None,
    ) -> bytes:
        direct_error: Exception | None = None
        try:
            data = _fetch_bytes_streaming_http(
                self.context,
                source_url,
                timeout_ms=timeout_ms,
                referer=referer,
                max_bytes=max_bytes,
                url_validator=url_validator,
            )
            if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
                return data
        except (ResponseTooLargeError, ValueError):
            raise
        except Exception as exc:
            direct_error = exc

        page = self.new_page()
        try:
            if referer:
                page.goto(referer, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(500)
            data = _fetch_bytes_from_page_context(
                page,
                source_url,
                timeout_ms=timeout_ms,
                max_bytes=max_bytes,
                url_validator=url_validator,
            )
            if data and (not validate_binary or _looks_like_binary_payload(source_url, data)):
                return data
        finally:
            close_page(page)

        if direct_error is not None:
            raise direct_error
        raise RuntimeError(f"bounded browser download failed for {source_url}")


def _download_link_from_page(
    page,
    source_url: str,
    *,
    timeout_ms: int,
    max_bytes: int | None,
    url_validator: Callable[[str], None] | None,
) -> bytes | None:
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
        download_url = getattr(download, "url", None)
        if isinstance(download_url, str):
            _validate_url(download_url, url_validator)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            download.save_as(str(tmp_path))
            actual_bytes = tmp_path.stat().st_size
            if max_bytes is not None and actual_bytes > max_bytes:
                raise ResponseTooLargeError(source_url, max_bytes, actual_bytes)
            return tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)
    except (ResponseTooLargeError, ValueError):
        raise
    except Exception:
        return None


def _fetch_bytes_with_context_request(
    context,
    source_url: str,
    *,
    timeout_ms: int,
    referer: str | None,
    max_bytes: int | None,
    url_validator: Callable[[str], None] | None,
) -> bytes | None:
    if context is None or not hasattr(context, "request"):
        return None
    headers = {"Referer": referer} if referer else None
    try:
        response = context.request.get(source_url, headers=headers, timeout=timeout_ms)
    except Exception:
        return None
    _validate_response_url(response, source_url, url_validator)
    try:
        if not response.ok:
            return None
        _reject_oversized_response(source_url, response, max_bytes)
        data = response.body()
        _reject_oversized_data(source_url, data, max_bytes)
        return data
    except ResponseTooLargeError:
        raise
    except Exception:
        return None


def _fetch_direct_response_body(
    page,
    source_url: str,
    *,
    timeout_ms: int,
    max_bytes: int | None,
    url_validator: Callable[[str], None] | None,
) -> bytes | None:
    response = page.goto(source_url, wait_until="commit", timeout=timeout_ms)
    if response is None:
        return None
    _validate_response_url(response, source_url, url_validator)
    status = response.status
    if status and status >= 400:
        return None
    _reject_oversized_response(source_url, response, max_bytes)
    data = response.body()
    _reject_oversized_data(source_url, data, max_bytes)
    return data


def _fetch_bytes_from_page_context(
    page,
    source_url: str,
    *,
    timeout_ms: int,
    max_bytes: int | None,
    url_validator: Callable[[str], None] | None,
) -> bytes | None:
    try:
        result = page.evaluate(
            """async ({url, maxBytes, timeoutMs}) => {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                try {
                    const resp = await fetch(url, {
                        credentials: "include",
                        cache: "no-store",
                        signal: controller.signal,
                        headers: {
                            "Accept": "application/pdf,application/octet-stream,*/*"
                        }
                    });
                    const declaredLength = Number(resp.headers.get("content-length"));
                    if (maxBytes !== null && Number.isFinite(declaredLength) && declaredLength > maxBytes) {
                        if (resp.body) await resp.body.cancel();
                        return {ok: resp.ok, status: resp.status, finalUrl: resp.url, tooLarge: declaredLength};
                    }
                    if (!resp.body) return null;

                    const reader = resp.body.getReader();
                    const chunks = [];
                    let total = 0;
                    while (true) {
                        const {done, value} = await reader.read();
                        if (done) break;
                        total += value.byteLength;
                        if (maxBytes !== null && total > maxBytes) {
                            await reader.cancel();
                            return {ok: resp.ok, status: resp.status, finalUrl: resp.url, tooLarge: total};
                        }
                        chunks.push(value);
                    }

                    const bytes = new Uint8Array(total);
                    let offset = 0;
                    for (const chunk of chunks) {
                        bytes.set(chunk, offset);
                        offset += chunk.byteLength;
                    }
                    let binary = "";
                    const sliceSize = 0x8000;
                    for (let index = 0; index < bytes.byteLength; index += sliceSize) {
                        binary += String.fromCharCode(...bytes.subarray(index, index + sliceSize));
                    }
                    return {
                        ok: resp.ok,
                        status: resp.status,
                        contentType: resp.headers.get("content-type") || "",
                        finalUrl: resp.url,
                        body: btoa(binary)
                    };
                } finally {
                    clearTimeout(timer);
                }
            }""",
            {"url": source_url, "maxBytes": max_bytes, "timeoutMs": timeout_ms},
        )
    except Exception:
        return None
    if not result:
        return None
    final_url = result.get("finalUrl")
    if isinstance(final_url, str):
        _validate_url(final_url, url_validator)
    if not result.get("ok"):
        return None
    actual_bytes = result.get("tooLarge")
    if max_bytes is not None and isinstance(actual_bytes, (int, float)):
        raise ResponseTooLargeError(source_url, max_bytes, int(actual_bytes))
    try:
        return base64.b64decode(str(result.get("body") or ""))
    except Exception:
        return None


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    def __init__(self, url_validator: Callable[[str], None] | None) -> None:
        super().__init__()
        self.url_validator = url_validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl, self.url_validator)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        source = urlparse(req.full_url)
        target = urlparse(newurl)
        if redirected is not None and (source.scheme, source.netloc) != (
            target.scheme,
            target.netloc,
        ):
            redirected.remove_header("Cookie")
        return redirected


def _fetch_bytes_streaming_http(
    context,
    source_url: str,
    *,
    timeout_ms: int,
    referer: str | None,
    max_bytes: int,
    url_validator: Callable[[str], None] | None,
) -> bytes:
    _validate_url(source_url, url_validator)
    headers = {
        "Accept": "application/pdf,application/octet-stream,*/*",
        "User-Agent": "Mozilla/5.0 (compatible; chinese-oil-price-data/1.0)",
    }
    if referer:
        headers["Referer"] = _ascii_http_url(referer)
    cookie_header = _browser_cookie_header(context, source_url)
    if cookie_header:
        headers["Cookie"] = cookie_header

    request = Request(_ascii_http_url(source_url), headers=headers)
    opener = build_opener(_ValidatingRedirectHandler(url_validator))
    try:
        response = opener.open(request, timeout=max(timeout_ms / 1000, 1))
    except HTTPError as exc:
        raise BrowserHTTPError(source_url, exc.code) from exc

    with response:
        final_url = response.geturl()
        _validate_url(final_url, url_validator)
        status = getattr(response, "status", None)
        if status is not None and status >= 400:
            raise BrowserHTTPError(final_url, status)

        raw_length = response.headers.get("content-length")
        try:
            declared_length = int(raw_length)
        except (TypeError, ValueError):
            declared_length = None
        if declared_length is not None and declared_length > max_bytes:
            raise ResponseTooLargeError(source_url, max_bytes, declared_length)

        data = bytearray()
        while len(data) <= max_bytes:
            remaining = max_bytes + 1 - len(data)
            chunk = response.read(min(64 * 1024, remaining))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        raise ResponseTooLargeError(source_url, max_bytes, len(data))


def _browser_cookie_header(context, source_url: str) -> str | None:
    if context is None or not hasattr(context, "cookies"):
        return None
    try:
        cookies = context.cookies([source_url])
    except Exception:
        return None
    if not isinstance(cookies, list):
        return None
    pairs = [
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if isinstance(cookie, dict) and cookie.get("name") and cookie.get("value") is not None
    ]
    return "; ".join(pairs) or None


def _ascii_http_url(url: str) -> str:
    """Encode Unicode HTTP URLs without double-encoding existing escapes."""

    parsed = urlsplit(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"URL has no host: {url}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must not contain credentials")

    if ":" in hostname:
        ascii_host = f"[{hostname}]"
    else:
        ascii_host = hostname.encode("idna").decode("ascii")
    netloc = ascii_host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"

    path = quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def _validate_response_url(
    response,
    fallback_url: str,
    url_validator: Callable[[str], None] | None,
) -> None:
    raw_url = getattr(response, "url", None)
    try:
        final_url = raw_url() if callable(raw_url) else raw_url
    except Exception:
        final_url = None
    _validate_url(final_url if isinstance(final_url, str) else fallback_url, url_validator)


def _validate_url(
    url: str,
    url_validator: Callable[[str], None] | None,
) -> None:
    if url_validator is not None:
        url_validator(url)


def _reject_oversized_response(source_url: str, response, max_bytes: int | None) -> None:
    if max_bytes is None:
        return
    raw_headers = getattr(response, "headers", None)
    try:
        headers = raw_headers() if callable(raw_headers) else raw_headers
    except Exception:
        return
    if not isinstance(headers, dict):
        return
    raw_length = headers.get("content-length") or headers.get("Content-Length")
    try:
        actual_bytes = int(raw_length)
    except (TypeError, ValueError):
        return
    if actual_bytes > max_bytes:
        raise ResponseTooLargeError(source_url, max_bytes, actual_bytes)


def _reject_oversized_data(source_url: str, data: bytes, max_bytes: int | None) -> None:
    if max_bytes is not None and len(data) > max_bytes:
        raise ResponseTooLargeError(source_url, max_bytes, len(data))


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
