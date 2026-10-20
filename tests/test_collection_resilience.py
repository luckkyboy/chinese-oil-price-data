from __future__ import annotations

import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from oilprice import pipeline, prices
from oilprice.io import read_json, write_json
from oilprice.options import ExtractOptions, PriceOptions
from tests.test_p1_validation import _create_valid_project
from oilprice.validation import validate_json_project


DATE = "2026-01-06"


class CollectionResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        _create_valid_project(self.root)
        self.price_path = self.root / f"data/prices/2026/{DATE}.json"
        self.index = self.root / "tmp/notices" / DATE / "index.json"
        # Start with no collected prices, retaining real schemas and region fixtures.
        for name in (f"2026/{DATE}.json", f"2026/{DATE}.summary.json", "latest.json"):
            (self.root / "data/prices" / name).unlink()
        registry = read_json(self.root / "data/sources/provinces.json")
        registry["provinces"].append({
            "province_code": "630000", "province_name": "青海省", "slug": "qinghai",
            "sources": [{"name": "青海省发展和改革委员会", "base_url": "https://example.com/",
                         "list_urls": ["https://example.com/qinghai"], "enabled": True}],
        })
        write_json(self.root / "data/sources/provinces.json", registry)
        write_json(self.root / "data/regions/qinghai.json", {
            "province_code": "630000", "province_name": "青海省",
            "updated_at": "2026-01-01T00:00:00+08:00",
            "zones": [
                {"zone_code": "qinghai-1", "zone_name": "一价区", "areas": [{"level": "city", "name": "西宁市"}]},
                {"zone_code": "qinghai-2", "zone_name": "二价区", "areas": [{"level": "city", "name": "海东市"}]},
            ],
        })
        region_index = read_json(self.root / "data/regions/regions.json")
        region_index["items"].extend([
            {"region": "西宁市", "province_code": "630000", "zone_code": "qinghai-1"},
            {"region": "海东市", "province_code": "630000", "zone_code": "qinghai-2"},
        ])
        region_index["count"] = len(region_index["items"])
        write_json(self.root / "data/regions/regions.json", region_index)
        self.extracted: dict[str, dict] = {
            "110000": {"extracted_prices": {"92": 7.0, "95": 7.5, "0": 6.8}},
            "630000": {"extracted_zones": [
                {"zone_code": "qinghai-1", "zone_name": "一价区", "items": {"92": 7.0}},
            ]},
        }
        self.discovery_errors: dict[str, list] = {}

    def discover(self, options):
        code = next(iter(options.province_codes))
        payload_path = self.root / "tmp" / f"{code}.json"
        write_json(payload_path, {
            "notice_id": "notice-" + code, "province_code": code,
            "province_name": "北京市" if code == "110000" else "青海省",
            "source_name": "Official", "source_url": "https://example.com/" + code,
            "adjustment_date": DATE, "confidence": "high", **self.extracted[code],
        })
        write_json(options.index_path, {
            "notices": [{"notice_id": "notice-" + code, "province_code": code,
                         "extracted_path": "/tmp/" + code + ".json"}],
            "errors": self.discovery_errors.get(code, []),
        })

    def run_pipeline(self, codes=None):
        with ExitStack() as stack:
            for module in (pipeline, prices):
                stack.enter_context(patch.object(module, "ROOT", self.root))
            stack.enter_context(patch.object(pipeline, "BrowserSession", MagicMock()))
            stack.enter_context(patch.object(pipeline, "run_discover", side_effect=self.discover))
            stack.enter_context(patch.object(pipeline, "run_fetch"))
            stack.enter_context(patch.object(pipeline, "run_extract_files"))
            return pipeline.run_extract(ExtractOptions(
                self.root / "data/sources/provinces.json", self.index, DATE, 1, True, codes,
            ))

    def test_one_invalid_province_does_not_block_valid_prices_or_index(self) -> None:
        self.run_pipeline()
        snapshot = read_json(self.price_path)
        self.assertEqual([p["province_code"] for p in snapshot["provinces"]], ["110000"])
        summary = read_json(self.price_path.with_suffix(".summary.json"))
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["provinces_missing"], ["630000"])
        index = read_json(self.index)
        self.assertEqual([n["province_code"] for n in index["notices"]], ["110000"])
        self.assertEqual(index["errors"][0]["stage"], "price")
        self.assertEqual(index["errors"][0]["province_code"], "630000")
        self.assertEqual(index["status"], "partial")
        result = validate_json_project(root=self.root)
        self.assertTrue(result.ok, result.format_errors())

    def test_valid_notice_survives_failure_of_a_backup_listing(self) -> None:
        self.discovery_errors["110000"] = [{"stage": "browser", "message": "backup timed out"}]
        self.run_pipeline({"110000"})
        self.assertEqual(read_json(self.price_path)["provinces"][0]["province_code"], "110000")

    def test_degraded_recollection_preserves_price_provenance_and_index(self) -> None:
        self.run_pipeline({"110000"})
        protected = [self.index, self.price_path, self.price_path.with_suffix(".summary.json"),
                     self.root / "data/prices/latest.json"]
        before = {path: path.read_bytes() for path in protected}
        self.extracted["110000"] = {"extracted_prices": {"92": 7.2}}
        with self.assertRaisesRegex(RuntimeError, "No provinces successfully collected"):
            self.run_pipeline({"110000"})
        self.assertEqual({path: path.read_bytes() for path in protected}, before)

    def test_all_failure_creates_no_price_and_reports_failure(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "No provinces successfully collected"):
            self.run_pipeline({"630000"})
        self.assertFalse(self.price_path.exists())
        self.assertFalse(self.index.exists())
        self.assertFalse((self.root / "data/prices/latest.json").exists())

    def test_direct_price_rebuild_cannot_drop_existing_products(self) -> None:
        self.run_pipeline({"110000"})
        before = self.price_path.read_bytes()
        extracted = self.root / "tmp/110000.json"
        payload = read_json(extracted)
        payload["extracted_prices"] = {"92": 7.2}
        write_json(extracted, payload)
        with patch.object(prices, "ROOT", self.root):
            with self.assertRaisesRegex(RuntimeError, "Price regression.*110000"):
                prices.run_build_prices(PriceOptions(self.index, DATE, {"110000"}))
        self.assertEqual(self.price_path.read_bytes(), before)

    def test_real_guizhou_result_cannot_lose_diesel_on_same_date(self) -> None:
        project = Path(__file__).resolve().parents[1]
        existing = read_json(project / "data/prices/2026/2026-09-24.json")
        incoming = copy.deepcopy(existing)
        incoming["provinces"] = [p for p in incoming["provinces"] if p["province_code"] == "520000"]
        for zone in incoming["provinces"][0]["zones"]:
            zone["items"].pop("0")
        with self.assertRaisesRegex(RuntimeError, "Price regression.*520000"):
            prices.merge_price_snapshots(existing, incoming)

    def test_real_unsold_grade_does_not_become_mandatory(self) -> None:
        self.run_pipeline({"110000"})
        before = read_json(self.price_path)
        self.assertNotIn("89", before["provinces"][0]["zones"][0]["items"])
        self.extracted["110000"]["extracted_prices"]["92"] = 7.2
        self.run_pipeline({"110000"})
        self.assertEqual(read_json(self.price_path)["provinces"][0]["zones"][0]["items"]["92"], 7.2)


if __name__ == "__main__":
    unittest.main()
