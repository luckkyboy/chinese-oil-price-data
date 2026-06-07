from __future__ import annotations

from oilprice.errors import BrowserFetchError

from .browser_session import BrowserFetchResult, BrowserSession


def fetch_page_html(
    source_url: str,
    *,
    timeout_seconds: int,
    browser_session: BrowserSession | None = None,
) -> BrowserFetchResult:
    try:
        if browser_session is not None:
            return browser_session.fetch_page_html(source_url, timeout_seconds=timeout_seconds)
        with BrowserSession(headless=True) as session:
            return session.fetch_page_html(source_url, timeout_seconds=timeout_seconds)
    except BrowserFetchError:
        raise
    except Exception as exc:
        raise BrowserFetchError(source_url, exc) from exc


def fetch_text_with_browser(
    source_url: str,
    *,
    timeout_seconds: int = 30,
    referer: str | None = None,
    browser_session: BrowserSession | None = None,
) -> str:
    try:
        if browser_session is not None:
            return browser_session.fetch_text(
                source_url,
                timeout_seconds=timeout_seconds,
                referer=referer,
            )
        with BrowserSession(headless=True) as session:
            return session.fetch_text(
                source_url,
                timeout_seconds=timeout_seconds,
                referer=referer,
            )
    except BrowserFetchError:
        raise
    except Exception as exc:
        raise BrowserFetchError(source_url, exc) from exc


def fetch_json_with_browser(
    source_url: str,
    *,
    timeout_seconds: int = 30,
    referer: str | None = None,
    browser_session: BrowserSession | None = None,
) -> dict[str, object]:
    try:
        if browser_session is not None:
            return browser_session.fetch_json(
                source_url,
                timeout_seconds=timeout_seconds,
                referer=referer,
            )
        with BrowserSession(headless=True) as session:
            return session.fetch_json(
                source_url,
                timeout_seconds=timeout_seconds,
                referer=referer,
            )
    except BrowserFetchError:
        raise
    except Exception as exc:
        raise BrowserFetchError(source_url, exc) from exc


def fetch_bytes_with_browser(
    source_url: str,
    *,
    timeout_seconds: int = 30,
    referer: str | None = None,
    validate_binary: bool = True,
    browser_session: BrowserSession | None = None,
) -> bytes:
    try:
        if browser_session is not None:
            return browser_session.fetch_bytes(
                source_url,
                timeout_seconds=timeout_seconds,
                referer=referer,
                validate_binary=validate_binary,
            )
        with BrowserSession(headless=True) as session:
            return session.fetch_bytes(
                source_url,
                timeout_seconds=timeout_seconds,
                referer=referer,
                validate_binary=validate_binary,
            )
    except BrowserFetchError:
        raise
    except Exception as exc:
        raise BrowserFetchError(source_url, exc) from exc
