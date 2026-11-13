"""Regressions observed in the 2026-11-12 official notices."""
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from oilprice import discovery_pipeline
from oilprice.crawl.browser_runtime import capture_settled_html
from oilprice.extract.html import html_to_text
from oilprice.options import DiscoverOptions
from oilprice.parsers import parse_notice


class NovemberCollectionTests(unittest.TestCase):
    def test_minified_ningxia_table_preserves_ton_and_liter_boundaries(self):
        # Same adjacent-cell layout and numbers as the official November notice.
        rows = [("89", "汽油", "10395", "7.80"),
                ("92", "汽油", "11019", "8.26"),
                ("95", "汽油", "11642", "8.73"),
                ("0", "柴油", "9330", "7.93"),
                ("-10", "柴油", "9890", "8.41")]
        html = "自2026年11月12日24时起执行<table>" + "".join(
            f"<tr><td>{grade}号车用{fuel}（100%）</td><td>{ton}</td><td>{liter}</td></tr>"
            for grade, fuel, ton, liter in rows
        ) + "</table>"
        result = parse_notice("ningxia", html_to_text(html.encode()))
        self.assertEqual(result["extracted_prices"], {"89": 7.8, "92": 8.26, "95": 8.73, "0": 7.93})
        self.assertEqual(result["adjustment_date"], "2026-11-12")

    def test_head_only_challenge_is_not_a_settled_article(self):
        page = MagicMock()
        head = "<html><head>" + "x" * 1500 + "</head></html>"
        article = "<html><body>" + "正文" * 600 + "</body></html>"
        page.content.side_effect = [head, article]
        self.assertEqual(capture_settled_html(page, timeout_ms=1000), article)
        page.wait_for_timeout.assert_called_once()

    def static_refs(self, html):
        session = MagicMock()
        session.fetch_static_text.return_value = html
        options = DiscoverOptions(Path("unused"), Path("unused"), "2026-11-12", 90, True,
                                  browser_session=session)
        item = {"province_code": "640000", "province_name": "宁夏", "slug": "ningxia"}
        refs = discovery_pipeline._discover_static_list_refs(
            item, "https://fzggw.nx.gov.cn/tzgg/", ["成品油"], options,
        )
        session.fetch_static_text.assert_called_once_with(
            "https://fzggw.nx.gov.cn/tzgg/", timeout_seconds=8,
        )
        return refs

    def test_static_list_finds_target_and_next_day_publications(self):
        for day in ("12", "13"):
            with self.subTest(day=day):
                refs = self.static_refs(f'<a href="202611/t202611{day}_1.html">成品油价格调整公告</a>')
                self.assertEqual(len(refs), 1)

    def test_stale_or_challenge_static_list_requests_browser_fallback(self):
        for html in ('<a href="202610/t20261029_1.html">成品油价格</a>',
                     '<html><script>challenge()</script></html>', ""):
            with self.subTest(html=html):
                self.assertEqual(self.static_refs(html), [])

    def test_static_request_exception_requests_browser_fallback(self):
        with patch.object(discovery_pipeline, "_parse_list_html", side_effect=ValueError("bad HTML")):
            self.assertEqual(self.static_refs("bad HTML"), [])
