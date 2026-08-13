from __future__ import annotations

import unittest

from oilprice.parsers.qinghai import parse_notice


class QinghaiParserTests(unittest.TestCase):
    def test_recovers_first_zone_when_table_omits_its_number(self) -> None:
        text = """
        汽油(国VIB) 柴油(国VI)
        89号 92号 95号 0号 -10 -20 -35
        价区
        9855 7.44 7.93 8.50 8890 7.56 8.01 8.39 8.69
        二价区
        9965 7.52 8.01 8.59 9000 7.65 8.11 8.49 8.80
        三价区
        10095 7.62 8.12 8.70 9130 7.76 8.23 8.61 8.92
        """

        result = parse_notice(text)

        zones = result["extracted_zones"]
        self.assertEqual(
            [zone["zone_code"] for zone in zones],
            ["qinghai-1", "qinghai-2", "qinghai-3"],
        )
        self.assertEqual(
            zones[0]["items"],
            {"89": 7.44, "92": 7.93, "95": 8.5, "0": 7.56},
        )


if __name__ == "__main__":
    unittest.main()
