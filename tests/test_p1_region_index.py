from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from oilprice.io import write_json
from oilprice.validation import validate_json_project


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_fixture(root: Path, items: list[dict[str, str]]) -> None:
    shutil.copytree(PROJECT_ROOT / "schema", root / "schema")
    write_json(
        root / "data/sources/provinces.json",
        {
            "updated_at": "2026-01-01T00:00:00+08:00",
            "provinces": [
                {
                    "province_code": code,
                    "province_name": name,
                    "slug": slug,
                    "sources": [
                        {
                            "name": "test",
                            "base_url": "https://example.com/",
                            "list_urls": ["https://example.com/notices"],
                            "enabled": True,
                        }
                    ],
                }
                for code, name, slug in (
                    ("110000", "Province A", "province-a"),
                    ("120000", "Province B", "province-b"),
                )
            ],
        },
    )
    write_json(
        root / "data/regions/regions.json",
        {
            "generated_at": "2026-01-01T00:00:00+08:00",
            "count": len(items),
            "items": items,
        },
    )


class RegionIndexValidationTests(unittest.TestCase):
    def test_empty_index_is_rejected_by_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_fixture(root, [])

            result = validate_json_project(root=root)

            self.assertFalse(result.ok)
            self.assertIn("data/regions/regions.json:/items", result.format_errors())
            self.assertIn("should be non-empty", result.format_errors())

    def test_duplicate_and_conflicting_query_keys_are_aggregated(self) -> None:
        first = {
            "region": "Shared Region",
            "province_code": "110000",
            "zone_code": "default",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_fixture(
                root,
                [
                    first,
                    dict(first),
                    {
                        "region": "Shared Region",
                        "province_code": "120000",
                        "zone_code": "default",
                    },
                ],
            )

            result = validate_json_project(root=root)

            rendered = result.format_errors()
            self.assertFalse(result.ok)
            self.assertIn("non-unique", rendered)
            self.assertIn("/items/1/region", rendered)
            self.assertIn("duplicate region lookup key", rendered)
            self.assertIn("/items/2/region", rendered)
            self.assertIn("conflicting region lookup key", rendered)


if __name__ == "__main__":
    unittest.main()
