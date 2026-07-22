from __future__ import annotations

import unittest

from oilprice.parsers import parse_notice


COMPLETE_TABLE_TEXT = """
自 2026 年 7 月 3 日 24 时起
汽油
价区 89号 92号 95号
中北部价区 7.41 7.90 8.47
陕南价区 7.51 8.00 8.57
柴油
价区 0号 -10号 -20号 -35号
西安市区 7.20 7.63 8.01 8.26
其他价区 7.30 7.73 8.11 8.36
"""


class ShaanxiParserTests(unittest.TestCase):
    def test_expands_gasoline_and_diesel_rows_into_three_location_zones(self) -> None:
        result = parse_notice("shaanxi", COMPLETE_TABLE_TEXT)

        self.assertEqual(result["adjustment_date"], "2026-07-03")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(
            result["extracted_zones"],
            [
                {
                    "zone_code": "shaanxi-1",
                    "zone_name": "中北部价区（西安市区）",
                    "items": {"89": 7.41, "92": 7.90, "95": 8.47, "0": 7.20},
                    "note": "汽油对应：中北部价区；柴油对应：西安市区",
                },
                {
                    "zone_code": "shaanxi-2",
                    "zone_name": "陕南价区",
                    "items": {"89": 7.51, "92": 8.00, "95": 8.57, "0": 7.30},
                    "note": "汽油对应：陕南价区；柴油对应：其他价区",
                },
                {
                    "zone_code": "shaanxi-3",
                    "zone_name": "中北部价区（西安市区外）",
                    "items": {"89": 7.41, "92": 7.90, "95": 8.47, "0": 7.30},
                    "note": "汽油对应：中北部价区；柴油对应：其他价区",
                },
            ],
        )
        self.assertEqual(
            result["extracted_prices"],
            {"89": 7.41, "92": 7.90, "95": 8.47, "0": 7.20},
        )

    def test_incomplete_table_uses_generic_fallback_and_keeps_adjustment_date(self) -> None:
        incomplete_text = """
        自2026年7月3日24时起
        汽油
        中北部价区 7.41 7.90 8.47
        柴油
        西安市区 7.20 7.63 8.01 8.26
        92号汽油调整为每升8.12元
        """

        result = parse_notice("shaanxi", incomplete_text)

        self.assertEqual(
            result,
            {
                "adjustment_date": "2026-07-03",
                "extracted_prices": {"92": 8.12},
                "extracted_zones": [
                    {
                        "zone_code": "default",
                        "zone_name": "默认价区",
                        "items": {"92": 8.12},
                    }
                ],
                "confidence": "medium",
            },
        )


if __name__ == "__main__":
    unittest.main()
