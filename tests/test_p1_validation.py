from __future__ import annotations

import argparse
import builtins
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oilprice.io import read_json, write_json
from oilprice.pipeline import command_validate_json
from oilprice.validation import ValidationIssue, ValidationResult, validate_json_project


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _create_valid_project(root: Path) -> None:
    shutil.copytree(PROJECT_ROOT / "schema", root / "schema")

    write_json(
        root / "data/sources/provinces.json",
        {
            "updated_at": "2026-01-01T00:00:00+08:00",
            "provinces": [
                {
                    "province_code": "110000",
                    "province_name": "北京市",
                    "slug": "beijing",
                    "sources": [
                        {
                            "name": "北京市发展和改革委员会",
                            "base_url": "https://example.com/",
                            "list_urls": ["https://example.com/notices"],
                            "enabled": True,
                        }
                    ],
                }
            ],
        },
    )
    write_json(
        root / "data/regions/regions.json",
        {
            "generated_at": "2026-01-01T00:00:00+08:00",
            "count": 1,
            "items": [
                {
                    "region": "北京",
                    "province_code": "110000",
                    "zone_code": "default",
                }
            ],
        },
    )
    write_json(
        root / "data/calendar/2026.json",
        {
            "year": 2026,
            "timezone": "Asia/Shanghai",
            "rule": "test rule",
            "generated_at": "2026-01-01T00:00:00+08:00",
            "anchor_previous_adjustment_date": "2025-12-22",
            "adjustment_dates": [{"date": "2026-01-06", "round": 1}],
            "sources": [{"name": "test", "url": "https://example.com/calendar"}],
        },
    )
    write_json(
        root / "data/calendar/latest.json",
        {
            "year": 2026,
            "path": "/data/calendar/2026.json",
            "updated_at": "2026-01-01T00:00:00+08:00",
        },
    )
    write_json(
        root / "data/prices/2026/2026-01-06.json",
        {
            "adjustment_date": "2026-01-06",
            "effective_from": "2026-01-07T00:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "unit": "CNY/L",
            "currency": "CNY",
            "products": ["92"],
            "provinces": [
                {
                    "province_code": "110000",
                    "province_name": "北京市",
                    "sources": [{"name": "test", "url": "https://example.com/notice"}],
                    "zones": [
                        {
                            "zone_code": "default",
                            "zone_name": "默认价区",
                            "items": {"92": 7.0},
                            "missing_products": ["89", "95", "0"],
                        }
                    ],
                }
            ],
            "updated_at": "2026-01-06T18:00:00+08:00",
        },
    )
    write_json(
        root / "data/prices/2026/2026-01-06.summary.json",
        {
            "adjustment_date": "2026-01-06",
            "price_file": "/data/prices/2026/2026-01-06.json",
            "status": "complete",
            "provinces_total": 1,
            "provinces_success": 1,
            "provinces_missing": [],
        },
    )
    write_json(
        root / "data/prices/latest.json",
        {
            "latest": "2026/2026-01-06.json",
            "latest_summary": "2026/2026-01-06.summary.json",
            "adjustment_date": "2026-01-06",
            "status": "complete",
            "updated_at": "2026-01-06T18:00:00+08:00",
        },
    )


class ProjectValidationTests(unittest.TestCase):
    def test_valid_project_ignores_local_virtual_environment_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            bad_local_json = root / ".venv/lib/package/config.json"
            bad_local_json.parent.mkdir(parents=True)
            bad_local_json.write_text('{"first": true}\n{"second": true}\n', encoding="utf-8")

            result = validate_json_project(root=root)

            self.assertTrue(result.ok, result.format_errors())
            self.assertNotIn(str(bad_local_json), result.format_errors())

    def test_schema_error_contains_file_and_json_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            source_path = root / "data/sources/provinces.json"
            payload = read_json(source_path)
            payload["provinces"][0]["province_code"] = "invalid"
            write_json(source_path, payload)

            result = validate_json_project(root=root)

            rendered = result.format_errors()
            self.assertFalse(result.ok)
            self.assertIn("data/sources/provinces.json:/provinces/0/province_code", rendered)
            self.assertIn("does not match", rendered)

    def test_format_checker_rejects_invalid_date_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            source_path = root / "data/sources/provinces.json"
            payload = read_json(source_path)
            payload["updated_at"] = "not-a-date-time"
            write_json(source_path, payload)

            result = validate_json_project(root=root)

            rendered = result.format_errors()
            self.assertIn("data/sources/provinces.json:/updated_at", rendered)
            self.assertIn("date-time", rendered)

    def test_duplicate_province_and_unknown_zone_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            price_path = root / "data/prices/2026/2026-01-06.json"
            payload = read_json(price_path)
            duplicate = dict(payload["provinces"][0])
            duplicate["zones"] = [dict(duplicate["zones"][0])]
            duplicate["zones"][0]["zone_code"] = "missing-zone"
            payload["provinces"].append(duplicate)
            write_json(price_path, payload)

            result = validate_json_project(root=root)

            rendered = result.format_errors()
            self.assertIn("/provinces/1/province_code", rendered)
            self.assertIn("duplicate province_code", rendered)
            self.assertIn("/provinces/1/zones/0/zone_code", rendered)
            self.assertIn("not declared by a province region file", rendered)

    def test_detailed_region_zone_requires_nonempty_areas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            write_json(
                root / "data/regions/beijing.json",
                {
                    "province_code": "110000",
                    "province_name": "北京市",
                    "zones": [{"zone_code": "beijing-1", "zone_name": "一价区"}],
                    "updated_at": "2026-01-01T00:00:00+08:00",
                },
            )

            result = validate_json_project(
                [Path("data/regions/beijing.json")],
                root=root,
            )

            rendered = result.format_errors()
            self.assertIn("data/regions/beijing.json:/zones/0", rendered)
            self.assertIn("'areas' is a required property", rendered)

    def test_cross_contract_failures_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            write_json(
                root / "data/regions/beijing.json",
                {
                    "province_code": "110000",
                    "province_name": "北京市",
                    "zones": [
                        {
                            "zone_code": "beijing-1",
                            "zone_name": "一价区",
                            "areas": [{"level": "city", "name": "北京市"}],
                        },
                        {
                            "zone_code": "beijing-2",
                            "zone_name": "二价区",
                            "areas": [{"level": "city", "name": "测试市"}],
                        },
                    ],
                    "updated_at": "2026-01-01T00:00:00+08:00",
                },
            )

            region_index_path = root / "data/regions/regions.json"
            region_index = read_json(region_index_path)
            region_index["count"] = 2
            region_index["items"][0]["zone_code"] = "beijing-1"
            write_json(region_index_path, region_index)

            price_path = root / "data/prices/2026/2026-01-06.json"
            snapshot = read_json(price_path)
            snapshot["products"] = ["89"]
            zone = snapshot["provinces"][0]["zones"][0]
            zone["zone_code"] = "beijing-1"
            zone["zone_name"] = "一价区"
            zone["missing_products"] = ["89", "92"]
            write_json(price_path, snapshot)

            result = validate_json_project(root=root)

            rendered = result.format_errors()
            self.assertIn("data/regions/regions.json:/count", rendered)
            self.assertIn("data/regions/beijing.json:/zones/1/zone_code", rendered)
            self.assertIn("is not referenced by data/regions/regions.json", rendered)
            self.assertIn("/provinces/0/zones", rendered)
            self.assertIn("zone_code set must exactly match", rendered)
            self.assertIn("/provinces/0/zones/0/missing_products", rendered)
            self.assertIn("items and missing_products overlap", rendered)
            self.assertIn("must cover exactly", rendered)
            self.assertIn("data/prices/2026/2026-01-06.json:/products", rendered)
            self.assertIn("products must equal the canonically ordered union", rendered)

    def test_snapshot_summary_and_latest_mismatches_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            price_path = root / "data/prices/2026/2026-01-06.json"
            price = read_json(price_path)
            price["adjustment_date"] = "2026-01-20"
            write_json(price_path, price)
            summary_path = root / "data/prices/2026/2026-01-06.summary.json"
            summary = read_json(summary_path)
            summary["price_file"] = "/data/prices/2026/other.json"
            write_json(summary_path, summary)

            result = validate_json_project(root=root)

            rendered = result.format_errors()
            self.assertIn("data/prices/2026/2026-01-06.json:/adjustment_date", rendered)
            self.assertIn("data/prices/2026/2026-01-06.summary.json:/price_file", rendered)
            self.assertIn("data/prices/latest.json:/adjustment_date", rendered)

    def test_missing_jsonschema_dependency_fails_explicitly(self) -> None:
        real_import = builtins.__import__

        def reject_jsonschema(name, *args, **kwargs):
            if name == "jsonschema" or name.startswith("jsonschema."):
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=reject_jsonschema):
            with self.assertRaisesRegex(RuntimeError, "jsonschema>=4.23,<5"):
                validate_json_project(root=PROJECT_ROOT)

    def test_cli_contract_failure_is_nonzero_and_aggregated(self) -> None:
        result = ValidationResult(
            files_checked=1,
            issues=(
                ValidationIssue(
                    file="data/example.json",
                    json_path="/value",
                    message="invalid value",
                    category="schema",
                ),
            ),
        )
        with patch("oilprice.pipeline.validate_json_project", return_value=result):
            with self.assertRaises(SystemExit) as raised:
                command_validate_json(argparse.Namespace(paths=[]))

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("data/example.json:/value", str(raised.exception.code))


if __name__ == "__main__":
    unittest.main()
