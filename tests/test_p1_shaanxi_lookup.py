from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from oilprice.pipeline import command_lookup_price


class ShaanxiLookupIntegrationTests(unittest.TestCase):
    def _lookup(self, area: str, product: str) -> dict[str, object]:
        args = argparse.Namespace(
            area=area,
            province="shaanxi",
            parent=None,
            adjustment_date="2026-07-03",
            product=product,
        )
        with patch("oilprice.pipeline.emit_result") as emit_result:
            command_lookup_price(args)
        return emit_result.call_args.args[0]

    def test_combined_gasoline_and_diesel_zones_route_by_area(self) -> None:
        xian_diesel = self._lookup("西安", "0")
        xianyang_diesel = self._lookup("咸阳", "0")
        hanzhong_gasoline = self._lookup("汉中", "92")

        self.assertEqual(xian_diesel["zone_code"], "shaanxi-1")
        self.assertEqual(xian_diesel["price"], 6.72)
        self.assertEqual(xianyang_diesel["zone_code"], "shaanxi-3")
        self.assertEqual(xianyang_diesel["price"], 6.89)
        self.assertEqual(hanzhong_gasoline["zone_code"], "shaanxi-2")
        self.assertEqual(hanzhong_gasoline["price"], 7.15)


if __name__ == "__main__":
    unittest.main()
