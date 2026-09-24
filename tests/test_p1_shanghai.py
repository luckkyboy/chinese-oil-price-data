from __future__ import annotations

import unittest

from oilprice.parsers import parse_notice, parser_version


class ShanghaiParserTests(unittest.TestCase):
    def test_parses_liter_prices_from_table_after_narrative_prices(self) -> None:
        text = """
        一、89号汽油和0号柴油最高零售价格每吨分别为10310元和9240元。
        标 号 单 位 最高零售价
        89号汽油 元/吨 10310 元/升 7.70
        92号汽油 元/吨 10929 元/升 8.25
        95号汽油 元/吨 11547 元/升 8.78
        0号柴油 元/吨 9240 元/升 7.95
        -10号柴油 元/吨 9794 元/升 8.43
        """

        parsed = parse_notice("shanghai", text)

        self.assertEqual(parser_version("shanghai"), "shanghai-v2")
        self.assertEqual(
            parsed["extracted_prices"],
            {"89": 7.70, "92": 8.25, "95": 8.78, "0": 7.95},
        )
        self.assertEqual(parsed["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
