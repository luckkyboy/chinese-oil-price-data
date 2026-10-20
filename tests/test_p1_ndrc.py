from __future__ import annotations

import io
import unittest
from datetime import date
from unittest.mock import patch

from oilprice.ndrc import NEWS_RELEASE_URL, find_ndrc_notice


def _link(title: str, stamp: str = "20261015", *, title_attribute: bool = True) -> str:
    attribute = f' title="{title}"' if title_attribute else ""
    return (
        f'<li><a href="./{stamp[:6]}/t{stamp}_1408170.html"{attribute}>'
        f'<span>{title}</span></a><span>{stamp[:4]}/{stamp[4:6]}/{stamp[6:]}</span></li>'
    )


class NdrcNoticeTests(unittest.TestCase):
    def lookup(self, html: str):
        with patch("oilprice.ndrc.urlopen", return_value=io.BytesIO(html.encode("utf-8"))):
            return find_ndrc_notice(date(2026, 10, 15))

    def test_official_no_change_title(self) -> None:
        notice = self.lookup(_link("2026年10月15日国内成品油价格不作调整"))
        self.assertIsNotNone(notice)
        self.assertTrue(notice.no_change)
        self.assertEqual(
            notice.url,
            "https://www.ndrc.gov.cn/xwdt/xwfb/202610/t20261015_1408170.html",
        )

    def test_adjustment_titles_and_text_without_title_attribute(self) -> None:
        for title in (
            "2026年10月15日国内成品油价格调整",
            "2026年10月15日国家继续实施调控，成品油价格适当调整",
            "2026年10月15日国家对成品油价格实施调控",
            "国内成品油价格按机制上调",
        ):
            with self.subTest(title=title):
                notice = self.lookup(_link(title, title_attribute=False))
                self.assertIsNotNone(notice)
                self.assertFalse(notice.no_change)

    def test_other_windows_and_unrelated_titles_cannot_mark_skip(self) -> None:
        html = "".join((
            _link("2026年9月24日国内成品油价格不作调整", "20260924"),
            _link("2026年9月24日国内成品油价格不作调整"),
            _link("2026年10月15日其他商品价格不作调整"),
            _link("2026年10月15日国内成品油价格政策解读"),
            _link("2026年10月15日国内成品油价格不作调整").replace(
                'href="./', 'href="https://example.com/xwdt/xwfb/',
            ),
        ))
        self.assertIsNone(self.lookup(html))

    def test_title_with_padded_date_matches(self) -> None:
        html = _link("2026年09月24日国内成品油价格不作调整", "20260924")
        with patch("oilprice.ndrc.urlopen", return_value=io.BytesIO(html.encode("utf-8"))):
            notice = find_ndrc_notice(date(2026, 9, 24))
        self.assertTrue(notice.no_change)

    def test_older_manual_window_follows_official_pagination(self) -> None:
        pages = [
            _link("国家发展改革委新闻", "20261016") + 'createPageHTML(40, 0, "index", "html");',
            _link("2026年10月15日国内成品油价格不作调整")
            + _link("国家发展改革委新闻", "20261014"),
        ]
        with patch(
            "oilprice.ndrc.urlopen",
            side_effect=[io.BytesIO(page.encode("utf-8")) for page in pages],
        ) as fetch:
            notice = find_ndrc_notice(date(2026, 10, 15))
        self.assertTrue(notice.no_change)
        self.assertEqual(
            [call.args[0].full_url for call in fetch.call_args_list],
            [NEWS_RELEASE_URL, NEWS_RELEASE_URL + "index_1.html"],
        )

    def test_target_day_without_notice_on_first_page_continues_same_day(self) -> None:
        pages = [
            _link("国家发展改革委新闻") + 'createPageHTML(3, 0, "index", "html");',
            _link("2026年10月15日国内成品油价格不作调整"),
            _link("国家发展改革委新闻", "20261014"),
        ]
        with patch(
            "oilprice.ndrc.urlopen",
            side_effect=[io.BytesIO(page.encode("utf-8")) for page in pages],
        ) as fetch:
            notice = find_ndrc_notice(date(2026, 10, 15))
        self.assertTrue(notice.no_change)
        self.assertEqual(fetch.call_count, 3)

    def test_cross_page_conflicting_announcements_do_not_cache_first_match(self) -> None:
        pages = [
            _link("2026年10月15日国内成品油价格调整")
            + 'createPageHTML(2, 0, "index", "html");',
            _link("2026年10月15日国内成品油价格不作调整").replace("1408170", "1408171"),
        ]
        with patch(
            "oilprice.ndrc.urlopen",
            side_effect=[io.BytesIO(page.encode("utf-8")) for page in pages],
        ):
            with self.assertRaisesRegex(ValueError, "conflicting NDRC"):
                find_ndrc_notice(date(2026, 10, 15))

    def test_repeated_same_announcement_across_pages_is_accepted(self) -> None:
        title = "2026年10月15日国内成品油价格不作调整"
        pages = [
            _link(title) + 'createPageHTML(2, 0, "index", "html");',
            _link(title),
        ]
        with patch(
            "oilprice.ndrc.urlopen",
            side_effect=[io.BytesIO(page.encode("utf-8")) for page in pages],
        ) as fetch:
            notice = find_ndrc_notice(date(2026, 10, 15))
        self.assertTrue(notice.no_change)
        self.assertEqual(fetch.call_count, 2)

    def test_pending_window_stops_before_older_pages(self) -> None:
        html = _link("2026年9月24日国内成品油价格调整", "20260924")
        html += 'createPageHTML(40, 0, "index", "html");'
        with patch("oilprice.ndrc.urlopen", return_value=io.BytesIO(html.encode("utf-8"))) as fetch:
            self.assertIsNone(find_ndrc_notice(date(2026, 10, 15)))
        fetch.assert_called_once()

    def test_conflicting_announcements_fail_instead_of_allowing_fetch(self) -> None:
        html = _link("2026年10月15日国内成品油价格调整")
        html += _link("2026年10月15日国内成品油价格不作调整").replace("1408170", "1408171")
        with self.assertRaisesRegex(ValueError, "conflicting NDRC"):
            self.lookup(html)

    def test_http_failure_is_not_treated_as_a_notice(self) -> None:
        with patch("oilprice.ndrc.urlopen", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                find_ndrc_notice(date(2026, 10, 15))


if __name__ == "__main__":
    unittest.main()
