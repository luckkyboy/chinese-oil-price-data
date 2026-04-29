from __future__ import annotations

from dataclasses import dataclass
import time
from urllib.parse import urlparse


class PlaywrightUnavailableError(RuntimeError):
    """Raised when Python Playwright is not installed or browser binaries are missing."""


@dataclass(frozen=True)
class PlaywrightFetchResult:
    html: str
    status: int | None
    final_url: str
    title: str
    bytes: int


def fetch_page_html(
    source_url: str,
    *,
    timeout_seconds: int,
) -> PlaywrightFetchResult:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid source url: {source_url}")

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise PlaywrightUnavailableError(
            "Python Playwright is unavailable. Install with `pip install playwright` "
            "and run `python -m playwright install chromium`."
        ) from exc

    timeout_ms = max(timeout_seconds, 1) * 1000

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                channel="chromium",
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                ignore_https_errors=True,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/147.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            response = page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                # Some pages keep background requests alive. DOM content is enough for extraction.
                pass
            content = _capture_settled_html(page, timeout_ms=timeout_ms)
            status = response.status if response else None
            final_url = page.url
            title = ""
            try:
                title = page.title()
            except Exception:
                title = ""
            context.close()
            browser.close()
            if not content.strip():
                raise RuntimeError(
                    f"playwright fetched empty content (status={status}, final_url={final_url})"
                )
            return PlaywrightFetchResult(
                html=content,
                status=status,
                final_url=final_url,
                title=title,
                bytes=len(content.encode("utf-8")),
            )
    except PlaywrightError as exc:
        raise RuntimeError(str(exc)) from exc


def _capture_settled_html(page, *, timeout_ms: int) -> str:
    deadline = time.monotonic() + max(timeout_ms, 1000) / 1000.0
    best = ""
    while time.monotonic() < deadline:
        try:
            content = page.content()
        except Exception:
            page.wait_for_timeout(300)
            continue
        best = content
        compact = content.replace(" ", "").replace("\n", "").lower()
        if len(content) > 1000 and "<body></body>" not in compact:
            return content
        page.wait_for_timeout(500)
    return best
