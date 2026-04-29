from __future__ import annotations

import hashlib
from pathlib import Path
import ssl
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

LEGACY_TLS_HOSTS = {"drc.jiangxi.gov.cn"}


def fetch_bytes(
    url: str,
    timeout: int = 20,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str | None]:
    request_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = Request(normalize_url(url), headers=request_headers)
    with urlopen(request, timeout=timeout, context=_ssl_context_for_url(url)) as response:
        return response.read(), response.headers.get("Content-Type")


def fetch_bytes_with_headers(
    url: str,
    *,
    timeout: int = 20,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str | None]:
    request_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = Request(normalize_url(url), headers=request_headers)
    with urlopen(request, timeout=timeout, context=_ssl_context_for_url(url)) as response:
        return response.read(), response.headers.get("Content-Type")


def save_raw(
    url: str,
    path: Path,
    timeout: int = 20,
    headers: dict[str, str] | None = None,
) -> tuple[str, str | None]:
    content, content_type = fetch_bytes(url, timeout=timeout, headers=headers)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest(), content_type


def build_discovery_headers(
    base_url: str,
    list_url: str,
    cookie: str | None = None,
) -> dict[str, str]:
    host = _host_from_url(base_url) or _host_from_url(list_url)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": list_url,
        "Upgrade-Insecure-Requests": "1",
    }
    if host:
        headers["Host"] = host
    if cookie:
        headers["Cookie"] = cookie
    return headers


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    path = quote(parts.path, safe="/%")
    query = quote(parts.query, safe="=&?/%")
    return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def _ssl_context_for_url(url: str) -> ssl.SSLContext | None:
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        return None
    host = parts.hostname.lower() if parts.hostname else ""
    if host not in LEGACY_TLS_HOSTS:
        return None
    context = ssl.create_default_context()
    if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
        context.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return context


def _host_from_url(url: str) -> str:
    parts = urlsplit(url)
    return parts.netloc.strip()
