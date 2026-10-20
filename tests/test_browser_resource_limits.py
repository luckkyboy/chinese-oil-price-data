from __future__ import annotations

import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock

from oilprice.crawl import browser_session
from oilprice.errors import BrowserHTTPError, ResponseTooLargeError


URL = "https://example.gov.cn/attachment.pdf"


class APIResponseDisposalTests(unittest.TestCase):
    def fetch(self, response, *, validator=None, max_bytes=4):
        context = MagicMock()
        context.request.get.return_value = response
        return browser_session._fetch_bytes_with_context_request(
            context,
            URL,
            timeout_ms=1000,
            referer=None,
            max_bytes=max_bytes,
            url_validator=validator,
        )

    def response(self):
        response = MagicMock(ok=True, url=URL)
        response.headers = {}
        response.body.return_value = b"data"
        return response

    def test_success_http_failure_and_body_failure_all_dispose(self):
        for outcome in ("success", "http_failure", "body_failure"):
            with self.subTest(outcome=outcome):
                response = self.response()
                if outcome == "http_failure":
                    response.ok = False
                elif outcome == "body_failure":
                    response.body.side_effect = OSError("read failed")
                self.assertEqual(self.fetch(response), b"data" if outcome == "success" else None)
                response.dispose.assert_called_once_with()

    def test_oversized_header_and_body_dispose_and_preserve_error(self):
        for declared in (True, False):
            with self.subTest(declared=declared):
                response = self.response()
                if declared:
                    response.headers = {"content-length": "5"}
                else:
                    response.body.return_value = b"12345"
                response.dispose.side_effect = OSError("cleanup failed")
                with self.assertRaises(ResponseTooLargeError):
                    self.fetch(response)
                response.dispose.assert_called_once_with()
                if declared:
                    response.body.assert_not_called()

    def test_rejected_response_url_disposes_and_preserves_validation_error(self):
        response = self.response()
        response.dispose.side_effect = OSError("cleanup failed")
        validator = MagicMock(side_effect=ValueError("unsafe redirect"))
        with self.assertRaisesRegex(ValueError, "unsafe redirect"):
            self.fetch(response, validator=validator)
        response.body.assert_not_called()
        response.dispose.assert_called_once_with()

    def test_cleanup_failure_does_not_discard_success(self):
        response = self.response()
        response.dispose.side_effect = OSError("cleanup failed")
        self.assertEqual(self.fetch(response), b"data")


@contextmanager
def attachment_server():
    stopped = threading.Event()
    interrupted = threading.Event()
    requests: list[tuple[str, str | None, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.path, self.headers.get("Cookie"), self.headers.get("Referer")))
            try:
                if self.path.startswith("/redirect-chain/"):
                    count = int(self.path.rsplit("/", 1)[-1])
                    if stopped.wait(0.1):
                        return
                    self.send_response(302)
                    self.send_header("Location", f"/redirect-chain/{count - 1}" if count > 1 else "/ok")
                    self.end_headers()
                    return
                if self.path == "/redirect":
                    if stopped.wait(0.08):
                        return
                    self.send_response(302)
                    self.send_header("Location", "/slow-body")
                    self.end_headers()
                    return
                if self.path == "/slow-headers":
                    payload = b"HTTP/1.0 200 OK\r\nContent-Length: 4\r\n\r\ndata"
                elif self.path == "/slow-chunk-size":
                    self.send_response(200)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    payload = b"0" * 100
                elif self.path == "/slow-body":
                    self.send_response(200)
                    self.end_headers()
                    payload = b"x" * 100
                elif self.path == "/missing":
                    self.send_error(404)
                    return
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"data")
                    return
                for byte in payload:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    if stopped.wait(0.03):
                        break
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                interrupted.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, interrupted
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class StreamingDeadlineTests(unittest.TestCase):
    def fetch(self, url, *, timeout_ms=250, max_bytes=1024, context=None, validator=None):
        return browser_session._fetch_bytes_streaming_http(
            context,
            url,
            timeout_ms=timeout_ms,
            referer="https://example.gov.cn/notice",
            max_bytes=max_bytes,
            url_validator=validator,
        )

    def test_continuous_body_headers_and_chunk_sizes_cannot_extend_deadline(self):
        # Each byte arrives well inside the socket inactivity timeout. A body
        # size check or a per-read timeout alone cannot enforce this deadline.
        for path in ("/slow-body", "/slow-headers", "/slow-chunk-size", "/redirect"):
            with self.subTest(path=path), attachment_server() as (base, _, interrupted):
                start = time.monotonic()
                with self.assertRaisesRegex(TimeoutError, "total timeout"):
                    self.fetch(base + path)
                self.assertLess(time.monotonic() - start, 0.8)
                self.assertTrue(interrupted.wait(0.5), "deadline must close the active response socket")

    def test_success_keeps_browser_cookies_referer_and_url_validation(self):
        context = MagicMock()
        context.cookies.return_value = [{"name": "session", "value": "verified"}]
        validator = MagicMock()
        with attachment_server() as (base, requests, _):
            url = base + "/ok"
            self.assertEqual(self.fetch(url, context=context, validator=validator), b"data")
        context.cookies.assert_called_once_with([url])
        self.assertEqual(requests, [("/ok", "session=verified", "https://example.gov.cn/notice")])
        self.assertEqual([args.args[0] for args in validator.call_args_list], [url, url])

    def test_redirect_chain_shares_one_deadline(self):
        with attachment_server() as (base, requests, _):
            start = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, "total timeout"):
                self.fetch(base + "/redirect-chain/5")
            self.assertLess(time.monotonic() - start, 0.8)
        self.assertNotIn("/ok", [request[0] for request in requests])

    def test_redirect_is_validated_before_following(self):
        def validate(url):
            if url.endswith("/slow-body"):
                raise ValueError("redirect forbidden")

        with attachment_server() as (base, requests, _):
            with self.assertRaisesRegex(ValueError, "redirect forbidden"):
                self.fetch(base + "/redirect", validator=validate)
        self.assertEqual([request[0] for request in requests], ["/redirect"])

    def test_rejected_redirect_closes_response_without_hiding_validation_error(self):
        response = MagicMock()
        response.close.side_effect = OSError("cleanup failed")
        handler = browser_session._ValidatingRedirectHandler(
            MagicMock(side_effect=ValueError("unsafe redirect"))
        )
        with self.assertRaisesRegex(ValueError, "unsafe redirect"):
            handler.redirect_request(None, response, 302, "Found", {}, URL)
        response.close.assert_called_once_with()

    def test_real_stream_still_enforces_size_limit(self):
        with attachment_server() as (base, _, _):
            with self.assertRaises(ResponseTooLargeError) as raised:
                self.fetch(base + "/ok", max_bytes=3)
        self.assertEqual(raised.exception.actual_bytes, 4)

    def test_http_errors_remain_browser_http_errors(self):
        with attachment_server() as (base, _, _):
            with self.assertRaises(BrowserHTTPError) as raised:
                self.fetch(base + "/missing")
        self.assertEqual(raised.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
