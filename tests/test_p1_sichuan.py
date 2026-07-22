from __future__ import annotations

import unittest

from oilprice.parsers.sichuan import parse_notice


class SichuanParserTests(unittest.TestCase):
    def test_parses_three_zone_rows_from_legacy_word_text(self) -> None:
        text = """
        四川省汽、柴油最高批发零售价格表（2026年7月17日）
        品名 一价区 二价区 三价区 最高批发价格 最高零售价格
        元/吨 元/吨 元/升 元/吨 元/吨 元/升 元/吨 元/吨 元/升
        89﹟汽油（国Ⅵ） 9125 9425 6.98 9225 9525 7.05 9325 9625 7.12
        92﹟汽油（国Ⅵ） 9691 9991 7.52 9791 10091 7.59 9891 10191 7.67
        95﹟汽油（国Ⅵ） 10256 10556 8.03 10356 10656 8.11 10456 10756 8.19
        0﹟车用柴油（国Ⅵ） 8125 8425 7.13 8225 8525 7.21 8325 8625 7.30
        ﹣10﹟车用柴油（国Ⅵ） 8631 8931 7.56 8731 9031 7.64 8831 9131 7.72
        """

        parsed = parse_notice(text)

        self.assertEqual(parsed["confidence"], "high")
        self.assertEqual(
            [zone["items"] for zone in parsed["extracted_zones"]],
            [
                {"89": 6.98, "92": 7.52, "95": 8.03, "0": 7.13},
                {"89": 7.05, "92": 7.59, "95": 8.11, "0": 7.21},
                {"89": 7.12, "92": 7.67, "95": 8.19, "0": 7.30},
            ],
        )


if __name__ == "__main__":
    unittest.main()
