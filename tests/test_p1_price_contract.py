from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from oilprice.io import read_json, write_json
from oilprice.validation import validate_json_project
from tests.test_p1_validation import _create_valid_project


class PriceContractBoundaryTests(unittest.TestCase):
    def test_zero_and_ton_scale_prices_are_rejected(self) -> None:
        for value in (0, 1000):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                _create_valid_project(root)
                price_path = root / "data/prices/2026/2026-01-06.json"
                payload = read_json(price_path)
                payload["provinces"][0]["zones"][0]["items"]["92"] = value
                write_json(price_path, payload)

                result = validate_json_project([price_path], root=root)

                self.assertFalse(result.ok)
                self.assertIn("/zones/0/items/92", result.format_errors())

    def test_missing_products_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            price_path = root / "data/prices/2026/2026-01-06.json"
            payload = read_json(price_path)
            del payload["provinces"][0]["zones"][0]["missing_products"]
            write_json(price_path, payload)

            result = validate_json_project([price_path], root=root)

            self.assertFalse(result.ok)
            self.assertIn("'missing_products' is a required property", result.format_errors())

    def test_products_must_use_canonical_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            price_path = root / "data/prices/2026/2026-01-06.json"
            payload = read_json(price_path)
            zone = payload["provinces"][0]["zones"][0]
            zone["items"] = {"89": 6.8, "92": 7.0}
            zone["missing_products"] = ["95", "0"]
            payload["products"] = ["92", "89"]
            write_json(price_path, payload)

            result = validate_json_project([price_path], root=root)

            self.assertFalse(result.ok)
            self.assertIn("canonically ordered", result.format_errors())

    def test_confidence_uses_declared_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            price_path = root / "data/prices/2026/2026-01-06.json"
            payload = read_json(price_path)
            payload["provinces"][0]["sources"][0]["confidence"] = "potato"
            write_json(price_path, payload)

            result = validate_json_project([price_path], root=root)

            self.assertFalse(result.ok)
            self.assertIn("/sources/0/confidence", result.format_errors())

    def test_summary_status_must_match_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            summary_path = root / "data/prices/2026/2026-01-06.summary.json"
            summary = read_json(summary_path)
            summary["status"] = "partial"
            write_json(summary_path, summary)
            latest_path = root / "data/prices/latest.json"
            latest = read_json(latest_path)
            latest["status"] = "partial"
            write_json(latest_path, latest)

            result = validate_json_project(root=root)

            self.assertFalse(result.ok)
            self.assertIn(
                "data/prices/2026/2026-01-06.summary.json:/status",
                result.format_errors(),
            )


if __name__ == "__main__":
    unittest.main()
