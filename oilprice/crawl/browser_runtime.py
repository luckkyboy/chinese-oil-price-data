from __future__ import annotations

import time


class BrowserUnavailableError(RuntimeError):
    """Raised when CloakBrowser is not installed or its browser binary is unavailable."""


def launch_browser(*, headless: bool):
    try:
        from cloakbrowser import launch
    except Exception as exc:
        raise BrowserUnavailableError(
            "CloakBrowser is unavailable. Install with `pip install cloakbrowser`."
        ) from exc

    try:
        return launch(headless=headless)
    except TypeError:
        return launch()


def new_context(browser):
    if hasattr(browser, "new_context"):
        return browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
        )
    return None


def block_heavy_resources(context) -> None:
    if context is None or not hasattr(context, "route"):
        return

    def handle_route(route):
        try:
            request = route.request
            resource_type = getattr(request, "resource_type", "")
            if resource_type in {"image", "media", "font", "stylesheet"}:
                route.abort()
                return
        except Exception:
            pass
        try:
            route.continue_()
        except Exception:
            pass

    try:
        context.route("**/*", handle_route)
    except Exception:
        pass


def close_browser(browser) -> None:
    try:
        browser.close()
    except Exception:
        pass


def close_page(page) -> None:
    try:
        page.close()
    except Exception:
        pass


def capture_settled_html(page, *, timeout_ms: int) -> str:
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
