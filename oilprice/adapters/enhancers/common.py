from __future__ import annotations

import re

from oilprice.crawl.browser_client import (
    BrowserSession,
    fetch_json_with_browser,
    fetch_text_with_browser,
)


def fetch_json(
    url: str,
    *,
    timeout: int,
    referer: str,
    browser_session: BrowserSession | None = None,
) -> dict[str, object]:
    return fetch_json_with_browser(
        url,
        timeout_seconds=timeout,
        referer=referer,
        browser_session=browser_session,
    )


def fetch_text(
    url: str,
    *,
    timeout: int,
    referer: str,
    browser_session: BrowserSession | None = None,
) -> str:
    return fetch_text_with_browser(
        url,
        timeout_seconds=timeout,
        referer=referer,
        browser_session=browser_session,
    )


def extract_published_date(raw: str) -> str | None:
    match = re.search(r"([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})", raw)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
