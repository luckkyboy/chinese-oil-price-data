from __future__ import annotations

import unittest

from oilprice.adapters.generic import discover_from_html


class GenericDiscoveryDateTests(unittest.TestCase):
    def test_compact_date_in_notice_url_wins_over_ambiguous_context(self) -> None:
        html = """
        <ul>
          <li>
            <a href="/fgdt/jggl/202607/t20260731_552187.html">
              西藏自治区成品油销售价格调整通知
            </a>
            <span>26/07</span>
          </li>
        </ul>
        """

        refs = discover_from_html(
            html=html,
            list_url="https://drc.xizang.gov.cn/fgdt/jggl/index.html",
            province_code="540000",
            province_name="西藏自治区",
            province_slug="xizang",
            keywords=["成品油"],
        )

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].published_at, "2026-07-31")

    def test_month_day_without_year_is_not_emitted_as_schema_date(self) -> None:
        html = """
        <li>
          <a href="notice.html">成品油价格调整通知</a>
          <span>07/31</span>
        </li>
        """

        refs = discover_from_html(
            html=html,
            list_url="https://example.gov.cn/notices/index.html",
            province_code="000000",
            province_name="测试省",
            province_slug="test",
            keywords=["成品油"],
        )

        self.assertEqual(len(refs), 1)
        self.assertIsNone(refs[0].published_at)


if __name__ == "__main__":
    unittest.main()
