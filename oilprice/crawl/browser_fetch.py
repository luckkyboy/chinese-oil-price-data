from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from oilprice.errors import (
    BrowserFetchError,
    BrowserHTTPError,
    ResponseTooLargeError,
)

from .browser_runtime import BrowserUnavailableError
from .browser_session import BrowserFetchResult, BrowserSession


DEFAULT_FETCH_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 0.25
_RETRYABLE_HTTP_STATUSES = {408, 425, 429}
_T = TypeVar("_T")


def fetch_page_html(
    source_url: str,
    *,
    timeout_seconds: int,
    browser_session: BrowserSession | None = None,
    max_attempts: int = DEFAULT_FETCH_ATTEMPTS,
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> BrowserFetchResult:
    def operation() -> BrowserFetchResult:
        if browser_session is not None:
            return browser_session.fetch_page_html(
                source_url,
                timeout_seconds=timeout_seconds,
            )
        with BrowserSession(headless=True) as session:
            return session.fetch_page_html(source_url, timeout_seconds=timeout_seconds)

    return _call_with_retry(
        source_url,
        operation,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )


def fetch_text_with_browser(
    source_url: str,
    *,
    timeout_seconds: int = 30,
    referer: str | None = None,
    browser_session: BrowserSession | None = None,
    max_attempts: int = DEFAULT_FETCH_ATTEMPTS,
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> str:
    def operation() -> str:
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

    return _call_with_retry(
        source_url,
        operation,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )


def fetch_json_with_browser(
    source_url: str,
    *,
    timeout_seconds: int = 30,
    referer: str | None = None,
    browser_session: BrowserSession | None = None,
    max_attempts: int = DEFAULT_FETCH_ATTEMPTS,
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> dict[str, object]:
    def operation() -> dict[str, object]:
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

    return _call_with_retry(
        source_url,
        operation,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )


def fetch_bytes_with_browser(
    source_url: str,
    *,
    timeout_seconds: int = 30,
    referer: str | None = None,
    validate_binary: bool = True,
    browser_session: BrowserSession | None = None,
    max_attempts: int = DEFAULT_FETCH_ATTEMPTS,
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    max_bytes: int | None = None,
    url_validator: Callable[[str], None] | None = None,
) -> bytes:
    _validate_max_bytes(max_bytes)

    def operation() -> bytes:
        if browser_session is not None:
            data = browser_session.fetch_bytes(
                source_url,
                timeout_seconds=timeout_seconds,
                referer=referer,
                validate_binary=validate_binary,
                max_bytes=max_bytes,
                url_validator=url_validator,
            )
        else:
            with BrowserSession(headless=True) as session:
                data = session.fetch_bytes(
                    source_url,
                    timeout_seconds=timeout_seconds,
                    referer=referer,
                    validate_binary=validate_binary,
                    max_bytes=max_bytes,
                    url_validator=url_validator,
                )
        if max_bytes is not None and len(data) > max_bytes:
            raise ResponseTooLargeError(source_url, max_bytes, len(data))
        return data

    return _call_with_retry(
        source_url,
        operation,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )


def _call_with_retry(
    source_url: str,
    operation: Callable[[], _T],
    *,
    max_attempts: int,
    backoff_seconds: float,
) -> _T:
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts must be an integer")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if backoff_seconds < 0:
        raise ValueError("backoff_seconds must not be negative")

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, BrowserFetchError)
                else BrowserFetchError(source_url, exc)
            )
            if attempt >= max_attempts or not _is_retryable(error):
                if error is exc:
                    raise
                raise error from exc
            delay = backoff_seconds * (2 ** (attempt - 1))
            if delay > 0:
                time.sleep(delay)

    raise AssertionError("unreachable retry state")


def _is_retryable(error: Exception) -> bool:
    cause = _root_cause(error)
    if isinstance(cause, BrowserHTTPError):
        return cause.status >= 500 or cause.status in _RETRYABLE_HTTP_STATUSES
    if isinstance(
        cause,
        (BrowserUnavailableError, ResponseTooLargeError, TypeError, ValueError),
    ):
        return False
    return True


def _root_cause(error: Exception) -> Exception:
    cause = error
    seen: set[int] = set()
    while isinstance(cause, BrowserFetchError) and id(cause) not in seen:
        seen.add(id(cause))
        cause = cause.cause
    return cause


def _validate_max_bytes(max_bytes: int | None) -> None:
    if max_bytes is None:
        return
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer or None")
