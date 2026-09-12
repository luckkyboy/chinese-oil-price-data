from __future__ import annotations

import unittest

from oilprice.parsers.guizhou import parse_notice


CURRENT_OCR_FORMAT = """
贵州省各价区汽油销售价格表
(2026年9月11日24时起）
价区
89#汽油（VIB)
92#汽油（VIB)
95#汽油（VIB)
市场最高批发价最高零售价
一价区 贵阳市（云岩、南明、花溪、乌当、白云、观山湖等六区）
10175 7.95 10804 8.42 11432 8.90
二价区 安顺、黔南、贵阳市所属修文县、开阳县、息烽县、清镇市
10215 7.98 10845 8.46 11476 8.93
三价区 遵义、六盘水、铜仁、黔东南、黔西南、毕节
10254 8.01 10887 8.49 11521 8.97
附表2:
贵州省各价区柴油（国VI）销售价格表
0#车用柴油
价区 市场最高批发价最高零售价
一价区 贵阳市 9130 8.07
二价区 安顺、黔南 9165 8.10
三价区 遵义、六盘水 9200 8.13
说明：执行区域按行政区划分。
"""


class GuizhouParserTests(unittest.TestCase):
    def test_uses_actual_tables_when_html_has_early_attachment_labels(self) -> None:
        text = (
            "网页附件：附表1 贵州省各价区汽油销售价格表；附表2 贵州省各价区柴油销售价格表\n"
            + CURRENT_OCR_FORMAT
        )
        result = parse_notice(text)

        self.assertEqual(
            result["extracted_prices"],
            {"89": 7.95, "92": 8.42, "95": 8.90, "0": 8.07},
        )
        self.assertEqual(
            [zone["zone_code"] for zone in result["extracted_zones"]],
            ["guizhou-1", "guizhou-2", "guizhou-3"],
        )

    def test_detects_tables_from_product_headers_without_attachment_one(self) -> None:
        result = parse_notice(CURRENT_OCR_FORMAT)

        self.assertEqual(
            [zone["zone_code"] for zone in result["extracted_zones"]],
            ["guizhou-1", "guizhou-2", "guizhou-3"],
        )
        self.assertEqual(result["extracted_prices"], {"89": 7.95, "92": 8.42, "95": 8.90, "0": 8.07})

    def test_keeps_legacy_attachment_markers_compatible(self) -> None:
        text = CURRENT_OCR_FORMAT.replace(
            "贵州省各价区汽油销售价格表",
            "附表1 贵州省各价区汽油销售价格表",
        )
        result = parse_notice(text)

        self.assertEqual(len(result["extracted_zones"]), 3)


if __name__ == "__main__":
    unittest.main()
