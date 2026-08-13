from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from oilprice import fetch_pipeline, fetching
from oilprice.adapters.enhancers import hubei
from oilprice.crawl import browser_fetch, browser_session as browser_session_module
from oilprice.crawl.browser_session import BrowserFetchResult, BrowserSession
from oilprice.errors import (
    AttachmentFetchError,
    BrowserFetchError,
    BrowserHTTPError,
    ResponseTooLargeError,
)
from oilprice.io import read_json, write_json
from oilprice.options import FetchOptions


URL = "https://www.example.gov.cn/notices/1"


class NoticeRenderedFallbackTests(unittest.TestCase):
    def test_text_fetch_is_attempted_before_rendered_fallback(self) -> None:
        events: list[str] = []
        rendered = BrowserFetchResult(
            html="<html>rendered</html>",
            status=200,
            final_url=URL,
            title="notice",
            bytes=21,
        )

        def fail_text(*args: object, **kwargs: object) -> str:
            events.append("text")
            raise BrowserFetchError(URL, TimeoutError("timed out"))

        def render_page(*args: object, **kwargs: object) -> BrowserFetchResult:
            events.append("render")
            return rendered

        with (
            patch.object(fetching, "fetch_text_with_browser", side_effect=fail_text),
            patch.object(fetching, "fetch_page_html", side_effect=render_page),
        ):
            html = fetching.fetch_notice_html_with_browser(
                URL,
                timeout=10,
                rendered_fallback=True,
            )

        self.assertEqual(html, rendered.html)
        self.assertEqual(events, ["text", "render"])

    def test_successful_text_fetch_does_not_render(self) -> None:
        with (
            patch.object(
                fetching,
                "fetch_text_with_browser",
                return_value="<html>direct</html>",
            ),
            patch.object(fetching, "fetch_page_html") as render_page,
        ):
            html = fetching.fetch_notice_html_with_browser(
                URL,
                timeout=10,
                rendered_fallback=True,
            )

        self.assertEqual(html, "<html>direct</html>")
        render_page.assert_not_called()

    def test_browser_challenge_uses_rendered_fallback(self) -> None:
        challenge = """<html><head><script r='m'>
        $_ss=window['$_ss'];
        </script></head><body></body></html>"""
        rendered = BrowserFetchResult(
            html="<html>notice content</html>",
            status=200,
            final_url=URL,
            title="notice",
            bytes=27,
        )

        with (
            patch.object(fetching, "fetch_text_with_browser", return_value=challenge),
            patch.object(fetching, "fetch_page_html", return_value=rendered) as render_page,
        ):
            html = fetching.fetch_notice_html_with_browser(
                URL,
                timeout=10,
                rendered_fallback=True,
            )

        self.assertEqual(html, rendered.html)
        render_page.assert_called_once()

    def test_unresolved_browser_challenge_is_rejected(self) -> None:
        challenge = """<html><head><script r='m'>
        $_ss=window['$_ss'];
        </script></head><body></body></html>"""
        unresolved = BrowserFetchResult(
            html=challenge,
            status=200,
            final_url=URL,
            title="",
            bytes=len(challenge.encode("utf-8")),
        )

        with (
            patch.object(fetching, "fetch_text_with_browser", return_value=challenge),
            patch.object(fetching, "fetch_page_html", return_value=unresolved),
        ):
            with self.assertRaisesRegex(RuntimeError, "challenge was not resolved"):
                fetching.fetch_notice_html_with_browser(
                    URL,
                    timeout=10,
                    rendered_fallback=True,
                )


class HubeiDiscoveryTests(unittest.TestCase):
    def test_official_http_notice_url_is_not_rewritten_to_blocked_https(self) -> None:
        source_url = "http://fgw.hubei.gov.cn/fbjd/zc/zcwj/gg/202607/notice.shtml"
        payload = {
            "data": [
                {
                    "FILENAME": "湖北成品油价格调整",
                    "URL": source_url,
                    "PUBDATE": "2026-07-31",
                }
            ]
        }
        source = {
            "name": "湖北省发展和改革委员会",
            "adapter": "generic",
            "base_url": "https://fgw.hubei.gov.cn/",
            "list_urls": ["https://fgw.hubei.gov.cn/fbjd/zc/zcwj/qtgk.json"],
        }

        with patch.object(hubei, "fetch_json", return_value=payload):
            refs = hubei.discover_from_hubei_qtgk_json(
                source=source,
                list_url=source["list_urls"][0],
                province_code="420000",
                province_name="湖北",
                province_slug="hubei",
                keywords=["成品油"],
                timeout=10,
            )

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].source_url, source_url)


class BrowserStatusTests(unittest.TestCase):
    def test_page_html_rejects_404_even_when_the_page_has_content(self) -> None:
        response = MagicMock(status=404)
        page = MagicMock()
        page.goto.return_value = response
        page.url = URL
        session = BrowserSession()
        session.new_page = MagicMock(return_value=page)

        with (
            patch(
                "oilprice.crawl.browser_session.capture_settled_html",
                return_value="<html>not found</html>",
            ) as capture_html,
            patch("oilprice.crawl.browser_session.close_page"),
        ):
            with self.assertRaises(BrowserHTTPError) as raised:
                session.fetch_page_html(URL, timeout_seconds=5)

        self.assertEqual(raised.exception.status, 404)
        capture_html.assert_not_called()

    def test_text_mode_rejects_500_body(self) -> None:
        response = MagicMock(status=500)
        response.body.return_value = b"server error"
        page = MagicMock()
        page.goto.return_value = response
        session = BrowserSession()
        session.new_page = MagicMock(return_value=page)

        with patch("oilprice.crawl.browser_session.close_page"):
            with self.assertRaises(BrowserHTTPError) as raised:
                session.fetch_bytes(
                    URL,
                    timeout_seconds=5,
                    validate_binary=False,
                )

        self.assertEqual(raised.exception.status, 500)
        response.body.assert_not_called()

    def test_fast_rendered_fetch_rejects_http_error_content(self) -> None:
        response = MagicMock(status=403)
        page = MagicMock()
        page.goto.return_value = response
        page.content.return_value = "<html>forbidden</html>"
        session = MagicMock()
        session.new_page.return_value = page

        with self.assertRaises(BrowserHTTPError):
            fetching.fetch_fast_rendered_html(
                URL,
                timeout_ms=5000,
                browser_session=session,
            )

        page.content.assert_not_called()
        page.close.assert_called_once()


class BoundedRetryTests(unittest.TestCase):
    def test_all_public_fetch_kinds_retry_transient_failures(self) -> None:
        cases = [
            (
                browser_fetch.fetch_page_html,
                "fetch_page_html",
                BrowserFetchResult("ok", 200, URL, "", 2),
                {"timeout_seconds": 5},
            ),
            (
                browser_fetch.fetch_text_with_browser,
                "fetch_text",
                "ok",
                {"timeout_seconds": 5},
            ),
            (
                browser_fetch.fetch_json_with_browser,
                "fetch_json",
                {"ok": True},
                {"timeout_seconds": 5},
            ),
            (
                browser_fetch.fetch_bytes_with_browser,
                "fetch_bytes",
                b"ok",
                {"timeout_seconds": 5, "validate_binary": False},
            ),
        ]

        for fetch_function, method_name, success, extra_kwargs in cases:
            with self.subTest(fetch=fetch_function.__name__):
                session = MagicMock()
                method = getattr(session, method_name)
                method.side_effect = [TimeoutError("temporary"), success]
                with patch("oilprice.crawl.browser_fetch.time.sleep") as sleep:
                    result = fetch_function(
                        URL,
                        browser_session=session,
                        max_attempts=2,
                        backoff_seconds=0.1,
                        **extra_kwargs,
                    )

                self.assertEqual(result, success)
                self.assertEqual(method.call_count, 2)
                sleep.assert_called_once_with(0.1)

    def test_backoff_is_exponential_and_attempts_are_bounded(self) -> None:
        session = MagicMock()
        session.fetch_text.side_effect = [
            TimeoutError("first"),
            TimeoutError("second"),
            "ok",
        ]

        with patch("oilprice.crawl.browser_fetch.time.sleep") as sleep:
            result = browser_fetch.fetch_text_with_browser(
                URL,
                browser_session=session,
                max_attempts=3,
                backoff_seconds=0.25,
            )

        self.assertEqual(result, "ok")
        self.assertEqual(session.fetch_text.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(0.25), call(0.5)])

    def test_retry_stops_after_the_configured_attempt_limit(self) -> None:
        session = MagicMock()
        session.fetch_text.side_effect = TimeoutError("still unavailable")

        with (
            patch("oilprice.crawl.browser_fetch.time.sleep"),
            self.assertRaises(BrowserFetchError),
        ):
            browser_fetch.fetch_text_with_browser(
                URL,
                browser_session=session,
                max_attempts=3,
                backoff_seconds=0,
            )

        self.assertEqual(session.fetch_text.call_count, 3)

    def test_permanent_http_and_input_errors_are_not_retried(self) -> None:
        failures = [
            (
                "fetch_page_html",
                BrowserHTTPError(URL, 404),
                browser_fetch.fetch_page_html,
            ),
            (
                "fetch_json",
                json.JSONDecodeError("bad json", "{", 1),
                browser_fetch.fetch_json_with_browser,
            ),
            (
                "fetch_text",
                ValueError("invalid URL"),
                browser_fetch.fetch_text_with_browser,
            ),
        ]

        for method_name, failure, fetch_function in failures:
            with self.subTest(method=method_name):
                session = MagicMock()
                getattr(session, method_name).side_effect = failure
                with (
                    patch("oilprice.crawl.browser_fetch.time.sleep") as sleep,
                    self.assertRaises(BrowserFetchError),
                ):
                    fetch_function(
                        URL,
                        browser_session=session,
                        timeout_seconds=5,
                        max_attempts=3,
                    )

                self.assertEqual(getattr(session, method_name).call_count, 1)
                sleep.assert_not_called()


class AttachmentBoundaryTests(unittest.TestCase):
    def test_public_cross_origin_cdn_urls_remain_allowed(self) -> None:
        with patch.object(
            fetching.socket,
            "getaddrinfo",
            return_value=[
                (fetching.socket.AF_INET, fetching.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
            ],
        ):
            fetching.validate_attachment_url("https://cdn.example.gov.cn/files/notice.pdf")

    def test_domain_resolving_to_private_address_is_rejected(self) -> None:
        with (
            patch.object(
                fetching.socket,
                "getaddrinfo",
                return_value=[
                    (fetching.socket.AF_INET, fetching.socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))
                ],
            ),
            self.assertRaisesRegex(ValueError, "non-public attachment IP"),
        ):
            fetching.validate_attachment_url("https://cdn.example.gov.cn/files/notice.pdf")

    def test_unsafe_attachment_urls_are_rejected(self) -> None:
        unsafe_urls = [
            "file:///etc/passwd",
            "ftp://files.example.gov.cn/notice.pdf",
            "http://localhost/notice.pdf",
            "http://api.localhost/notice.pdf",
            "http://127.0.0.1/notice.pdf",
            "http://127.1/notice.pdf",
            "http://2130706433/notice.pdf",
            "http://10.0.0.8/notice.pdf",
            "http://169.254.1.1/notice.pdf",
            "http://[::1]/notice.pdf",
            "https://user:password@example.gov.cn/notice.pdf",
        ]

        for url in unsafe_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetching.validate_attachment_url(url)

    def test_oversized_bytes_fail_once_without_writing_a_file(self) -> None:
        session = MagicMock()
        session.fetch_bytes.return_value = b"12345"

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attachment.pdf"
            with (
                patch.object(
                    fetching.socket,
                    "getaddrinfo",
                    return_value=[
                        (
                            fetching.socket.AF_INET,
                            fetching.socket.SOCK_STREAM,
                            6,
                            "",
                            ("93.184.216.34", 443),
                        )
                    ],
                ),
                self.assertRaises(AttachmentFetchError) as raised,
            ):
                fetching.save_attachment_raw(
                    "https://cdn.example.gov.cn/attachment.pdf",
                    path,
                    timeout=5,
                    browser_session=session,
                    max_bytes=4,
                )

            self.assertFalse(path.exists())

        self.assertEqual(session.fetch_bytes.call_count, 1)
        browser_error = raised.exception.cause
        self.assertIsInstance(browser_error, BrowserFetchError)
        self.assertIsInstance(browser_error.cause, ResponseTooLargeError)

    def test_declared_oversized_response_is_rejected_before_body_buffering(self) -> None:
        response = MagicMock(status=200)
        response.headers = {"content-length": "5"}
        response.geturl.return_value = URL
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        session = BrowserSession()
        session.context = MagicMock()
        session.context.cookies.return_value = []

        with (
            patch.object(browser_session_module, "build_opener", return_value=opener),
            self.assertRaises(ResponseTooLargeError),
        ):
                session.fetch_bytes(
                    URL,
                    timeout_seconds=5,
                    validate_binary=False,
                    max_bytes=4,
                )

        response.read.assert_not_called()

    def test_missing_content_length_is_read_only_to_the_hard_limit(self) -> None:
        response = MagicMock(status=200)
        response.headers = {}
        response.geturl.return_value = URL
        response.__enter__.return_value = response
        response.read.side_effect = [b"1234", b"5"]
        opener = MagicMock()
        opener.open.return_value = response
        session = BrowserSession()
        session.context = MagicMock()
        session.context.cookies.return_value = []

        with (
            patch.object(browser_session_module, "build_opener", return_value=opener),
            self.assertRaises(ResponseTooLargeError) as raised,
        ):
            session.fetch_bytes(
                URL,
                timeout_seconds=5,
                validate_binary=False,
                max_bytes=4,
            )

        self.assertEqual(raised.exception.actual_bytes, 5)
        self.assertEqual(response.read.call_args_list, [call(5), call(1)])

    def test_unicode_attachment_url_is_percent_encoded_for_streaming_http(self) -> None:
        unicode_url = "https://cdn.example.gov.cn/files/四川省价格表.doc"
        response = MagicMock(status=200)
        response.headers = {}
        response.geturl.return_value = unicode_url
        response.__enter__.return_value = response
        response.read.side_effect = [b"\xd0\xcf\x11\xe0payload", b""]
        opener = MagicMock()
        opener.open.return_value = response
        session = BrowserSession()
        session.context = MagicMock()
        session.context.cookies.return_value = []

        with patch.object(browser_session_module, "build_opener", return_value=opener):
            data = session.fetch_bytes(
                unicode_url,
                timeout_seconds=5,
                max_bytes=1024,
            )

        request = opener.open.call_args.args[0]
        self.assertNotIn("四川省价格表", request.full_url)
        self.assertIn("%E5%9B%9B%E5%B7%9D%E7%9C%81", request.full_url)
        self.assertEqual(data, b"\xd0\xcf\x11\xe0payload")

    def test_redirect_to_private_address_is_rejected_before_body_use(self) -> None:
        response = MagicMock(status=200)
        response.headers = {}
        response.geturl.return_value = "http://127.0.0.1/internal"
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        session = BrowserSession()
        session.context = MagicMock()
        session.context.cookies.return_value = []

        with (
            patch.object(browser_session_module, "build_opener", return_value=opener),
            patch.object(
                fetching.socket,
                "getaddrinfo",
                return_value=[
                    (fetching.socket.AF_INET, fetching.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
                ],
            ),
            self.assertRaisesRegex(ValueError, "non-public attachment IP"),
        ):
            session.fetch_bytes(
                URL,
                timeout_seconds=5,
                validate_binary=False,
                max_bytes=4,
                url_validator=fetching.validate_attachment_url,
            )

        response.read.assert_not_called()

    def test_cross_origin_redirect_does_not_forward_browser_cookies(self) -> None:
        handler = browser_session_module._ValidatingRedirectHandler(None)
        request = browser_session_module.Request(
            URL,
            headers={"Cookie": "session=secret"},
        )

        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://cdn.example.gov.cn/notice.pdf",
        )

        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Cookie"))

    def test_page_context_reader_reports_oversize_without_returning_a_body(self) -> None:
        page = MagicMock()
        page.evaluate.return_value = {
            "ok": True,
            "status": 200,
            "finalUrl": URL,
            "tooLarge": 5,
        }

        with self.assertRaises(ResponseTooLargeError):
            browser_session_module._fetch_bytes_from_page_context(
                page,
                URL,
                timeout_ms=5000,
                max_bytes=4,
                url_validator=None,
            )

        arguments = page.evaluate.call_args.args[1]
        self.assertEqual(arguments["timeoutMs"], 5000)
        self.assertEqual(arguments["maxBytes"], 4)

    def test_max_bytes_is_forwarded_to_a_shared_browser_session(self) -> None:
        session = MagicMock()
        session.fetch_bytes.return_value = b"1234"

        result = browser_fetch.fetch_bytes_with_browser(
            URL,
            browser_session=session,
            timeout_seconds=5,
            validate_binary=False,
            max_bytes=4,
        )

        self.assertEqual(result, b"1234")
        session.fetch_bytes.assert_called_once_with(
            URL,
            timeout_seconds=5,
            referer=None,
            validate_binary=False,
            max_bytes=4,
            url_validator=None,
        )

    def test_invalid_url_is_rejected_before_browser_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attachment.pdf"
            with (
                patch.object(fetching, "fetch_bytes_with_browser") as fetch_bytes,
                self.assertRaises(AttachmentFetchError),
            ):
                fetching.save_attachment_raw(
                    "http://127.0.0.1/attachment.pdf",
                    path,
                    timeout=5,
                )

            fetch_bytes.assert_not_called()
            self.assertFalse(path.exists())


class AttachmentFailureRecordingTests(unittest.TestCase):
    def test_attachment_failure_is_recorded_on_notice_in_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "tmp" / "notices" / "2026-07-20" / "index.json"
            write_json(
                index_path,
                {
                    "errors": [],
                    "notices": [
                        {
                            "notice_id": "notice-1",
                            "province_code": "110000",
                            "province_name": "Beijing",
                            "source_url": URL,
                        }
                    ],
                },
            )
            options = FetchOptions(
                index_path=index_path,
                adjustment_date=None,
                timeout=5,
                force=True,
            )

            def fetch_notice(source_url: str, raw_path: Path, **kwargs: object) -> str:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text("<html>notice</html>", encoding="utf-8")
                return "notice-sha"

            attachment_url = "https://cdn.example.gov.cn/files/notice.pdf"
            attachment_error = AttachmentFetchError(
                attachment_url,
                ResponseTooLargeError(attachment_url, 4, 5),
            )
            with (
                patch.object(fetch_pipeline, "ROOT", root),
                patch.object(
                    fetch_pipeline,
                    "fetch_notice_with_browser",
                    side_effect=fetch_notice,
                ),
                patch.object(
                    fetch_pipeline,
                    "find_attachment_links",
                    return_value=[
                        {
                            "url": attachment_url,
                            "name": "notice.pdf",
                            "type": "document",
                        }
                    ],
                ),
                patch.object(
                    fetch_pipeline,
                    "save_attachment_raw",
                    side_effect=attachment_error,
                ),
            ):
                fetch_pipeline.run_fetch(options)

            payload = read_json(index_path)
            self.assertEqual(payload["errors"], [])
            notice = payload["notices"][0]
            self.assertNotIn("attachments", notice)
            self.assertEqual(
                notice["attachment_errors"],
                [
                    {
                        "url": attachment_url,
                        "name": "notice.pdf",
                        "type": "document",
                        "message": (
                            f"response for {attachment_url} exceeds 4 bytes "
                            "(received 5 bytes)"
                        ),
                        "cause_type": "ResponseTooLargeError",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
