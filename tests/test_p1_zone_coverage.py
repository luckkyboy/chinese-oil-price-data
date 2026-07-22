from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import cast

from oilprice.io import write_json
from oilprice.payloads import PriceSnapshotPayload
from oilprice.prices import validate_snapshot_zone_coverage


def _snapshot(zones: list[dict[str, object]]) -> PriceSnapshotPayload:
    return cast(PriceSnapshotPayload, {
        "adjustment_date": "2026-07-03",
        "effective_from": "2026-07-04T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "unit": "CNY/L",
        "currency": "CNY",
        "products": ["92"],
        "provinces": [
            {
                "province_code": "630000",
                "province_name": "青海省",
                "sources": [],
                "zones": zones,
            }
        ],
        "updated_at": "2026-07-03T18:00:00+08:00",
    })


class RuntimeZoneCoverageTests(unittest.TestCase):
    def _region_root(self, root: Path) -> Path:
        region_root = root / "data/regions"
        write_json(
            region_root / "qinghai.json",
            {
                "province_code": "630000",
                "province_name": "青海省",
                "zones": [
                    {"zone_code": "qinghai-1", "zone_name": "一价区"},
                    {"zone_code": "qinghai-2", "zone_name": "二价区"},
                ],
                "updated_at": "2026-07-03T00:00:00+08:00",
            },
        )
        return region_root

    def test_partial_multi_zone_province_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            region_root = self._region_root(Path(temp_dir))
            snapshot = _snapshot(
                [{"zone_code": "qinghai-2", "zone_name": "二价区", "items": {"92": 8.0}}]
            )

            with self.assertRaisesRegex(RuntimeError, r"630000.*missing: qinghai-1"):
                validate_snapshot_zone_coverage(snapshot, region_root)

    def test_complete_zone_set_with_declared_names_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            region_root = self._region_root(Path(temp_dir))
            snapshot = _snapshot(
                [
                    {"zone_code": "qinghai-1", "zone_name": "一价区", "items": {"92": 8.0}},
                    {"zone_code": "qinghai-2", "zone_name": "二价区", "items": {"92": 8.1}},
                ]
            )

            validate_snapshot_zone_coverage(snapshot, region_root)

    def test_zone_name_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            region_root = self._region_root(Path(temp_dir))
            snapshot = _snapshot(
                [
                    {"zone_code": "qinghai-1", "zone_name": "错误价区", "items": {"92": 8.0}},
                    {"zone_code": "qinghai-2", "zone_name": "二价区", "items": {"92": 8.1}},
                ]
            )

            with self.assertRaisesRegex(RuntimeError, r"630000.*qinghai-1"):
                validate_snapshot_zone_coverage(snapshot, region_root)

    def test_duplicate_zone_code_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            region_root = self._region_root(Path(temp_dir))
            snapshot = _snapshot(
                [
                    {"zone_code": "qinghai-1", "zone_name": "duplicate-a", "items": {"92": 8.0}},
                    {"zone_code": "qinghai-1", "zone_name": "duplicate-b", "items": {"92": 8.1}},
                    {"zone_code": "qinghai-2", "zone_name": "other", "items": {"92": 8.2}},
                ]
            )

            with self.assertRaisesRegex(RuntimeError, r"Duplicate price zone qinghai-1"):
                validate_snapshot_zone_coverage(snapshot, region_root)


if __name__ == "__main__":
    unittest.main()
