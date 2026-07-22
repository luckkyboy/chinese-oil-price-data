from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from oilprice.io import read_json, write_json
from oilprice.validation import validate_json_project
from tests.test_p1_validation import _create_valid_project


class ValidationBoundaryTests(unittest.TestCase):
    def test_http_uri_rejects_malformed_and_non_http_values_without_crashing(self) -> None:
        invalid_values = [
            "http://[::1",
            "https://example.com:99999/path",
            "https://example.com:not-a-port/path",
            "ftp://example.com/file",
            "mailto:operator@example.com",
            "https://user:password@example.com/path",
        ]
        for value in invalid_values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                _create_valid_project(root)
                source_path = root / "data/sources/provinces.json"
                payload = read_json(source_path)
                payload["provinces"][0]["sources"][0]["base_url"] = value
                write_json(source_path, payload)

                result = validate_json_project([source_path], root=root)

                self.assertFalse(result.ok)
                self.assertIn("http-uri", result.format_errors())

    def test_http_uri_accepts_public_http_https_and_ipv6_syntax(self) -> None:
        valid_values = [
            "http://example.com/path",
            "https://example.com:8443/path?q=1",
            "https://[2001:db8::1]/path",
        ]
        for value in valid_values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                _create_valid_project(root)
                source_path = root / "data/sources/provinces.json"
                payload = read_json(source_path)
                payload["provinces"][0]["sources"][0]["base_url"] = value
                write_json(source_path, payload)

                result = validate_json_project([source_path], root=root)

                self.assertTrue(result.ok, result.format_errors())

    def test_explicit_project_root_matches_default_controlled_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            ignored = root / ".venv/package/bad.json"
            ignored.parent.mkdir(parents=True)
            ignored.write_text("{not-json", encoding="utf-8")

            default_result = validate_json_project(root=root)
            explicit_result = validate_json_project([Path(".")], root=root)

            self.assertTrue(default_result.ok, default_result.format_errors())
            self.assertTrue(explicit_result.ok, explicit_result.format_errors())
            self.assertEqual(explicit_result.files_checked, default_result.files_checked)

    def test_outside_path_is_rejected_without_being_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            _create_valid_project(root)
            outside = base / "outside.json"
            outside.write_text("{not-json", encoding="utf-8")

            result = validate_json_project([outside], root=root)

            self.assertFalse(result.ok)
            self.assertEqual(result.files_checked, 0)
            self.assertIn("outside controlled", result.format_errors())
            self.assertNotIn("invalid JSON", result.format_errors())

    def test_empty_directory_and_unmapped_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            empty = root / "data/empty"
            empty.mkdir(parents=True)
            empty_result = validate_json_project([empty], root=root)

            unknown = root / "data/unknown.json"
            write_json(unknown, {"value": True})
            unknown_result = validate_json_project([unknown], root=root)

            self.assertIn("contains no controlled JSON", empty_result.format_errors())
            self.assertIn("no JSON Schema mapping", unknown_result.format_errors())

    def test_snapshot_focus_reports_paired_summary_semantic_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _create_valid_project(root)
            summary_path = root / "data/prices/2026/2026-01-06.summary.json"
            summary = read_json(summary_path)
            summary["provinces_total"] = 99
            write_json(summary_path, summary)

            snapshot_path = root / "data/prices/2026/2026-01-06.json"
            result = validate_json_project([snapshot_path], root=root)

            self.assertFalse(result.ok)
            self.assertIn(
                "data/prices/2026/2026-01-06.summary.json:/provinces_total",
                result.format_errors(),
            )


if __name__ == "__main__":
    unittest.main()
