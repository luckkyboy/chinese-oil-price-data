from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oilprice import extraction_pipeline
from oilprice.io import read_json, write_json
from oilprice.normalize import price_snapshot
from oilprice.notices import filter_notices_for_adjustment_date
from oilprice.options import ExtractFilesOptions
from oilprice.parsers import parser_version


class NoticeDateSemanticsTests(unittest.TestCase):
    def test_extraction_keeps_publication_and_adjustment_dates_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "tmp" / "notices" / "index.json"
            raw_path = root / "tmp" / "notices" / "raw.html"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text("raw notice", encoding="utf-8")
            raw_sha256 = "a" * 64
            write_json(
                index_path,
                {
                    "notices": [
                        {
                            "notice_id": "notice-1",
                            "province_code": "110000",
                            "province_name": "Beijing",
                            "source_name": "Official source",
                            "adapter": "beijing",
                            "title": "Price notice",
                            "published_at": "2026-07-21",
                            "source_url": "https://example.test/notice-1",
                            "raw_path": "/tmp/notices/raw.html",
                            "sha256": raw_sha256,
                            "attachments": [],
                        }
                    ]
                },
            )
            options = ExtractFilesOptions(
                index_path=index_path,
                adjustment_date="2026-07-20",
                force=True,
            )

            with (
                patch.object(extraction_pipeline, "ROOT", root),
                patch.object(extraction_pipeline, "html_to_text", return_value="notice text"),
                patch.object(
                    extraction_pipeline,
                    "parse_notice",
                    return_value={
                        "adjustment_date": "2026-07-20",
                        "extracted_prices": {"92": 8.0},
                        "confidence": "high",
                    },
                ),
            ):
                extraction_pipeline.run_extract_files(options)

            updated_index = read_json(index_path)
            extracted_path = root / updated_index["notices"][0]["extracted_path"].lstrip("/")
            extracted = read_json(extracted_path)
            self.assertEqual(extracted["published_at"], "2026-07-21")
            self.assertEqual(extracted["adjustment_date"], "2026-07-20")
            self.assertEqual(extracted["raw_sha256"], raw_sha256)
            self.assertEqual(extracted["sha256"], raw_sha256)
            self.assertEqual(extracted["adapter"], "beijing")
            self.assertEqual(extracted["parser_version"], parser_version("beijing"))

    def test_parser_versions_are_adapter_specific_and_follow_fallbacks(self) -> None:
        self.assertEqual(parser_version("beijing"), "beijing-v1")
        self.assertEqual(parser_version("shaanxi"), "shaanxi-v2")
        self.assertEqual(parser_version("unknown-adapter"), "generic-v1")

    def test_filter_prefers_explicit_adjustment_date_and_keeps_legacy_fallback(self) -> None:
        notices = [
            {
                "notice_id": "explicit-match",
                "adjustment_date": "2026-07-20",
                "published_at": "2026-01-01",
            },
            {
                "notice_id": "explicit-mismatch",
                "adjustment_date": "2026-06-18",
                "published_at": "2026-07-20",
            },
            {
                "notice_id": "legacy-published-date",
                "published_at": "2026-07-21",
            },
        ]

        selected = filter_notices_for_adjustment_date(notices, "2026-07-20")

        self.assertEqual(
            [notice["notice_id"] for notice in selected],
            ["explicit-match", "legacy-published-date"],
        )


class PriceSnapshotSemanticsTests(unittest.TestCase):
    def _write_notice(
        self,
        root: Path,
        notice_id: str,
        price: float,
        raw_sha256: str,
        province_name: str = "Beijing",
    ) -> Path:
        path = root / f"{notice_id}.json"
        write_json(
            path,
            {
                "notice_id": notice_id,
                "province_code": "110000",
                "province_name": province_name,
                "source_name": "Official source",
                "title": f"Notice {notice_id}",
                "source_url": f"https://example.test/{notice_id}",
                "raw_sha256": raw_sha256,
                "adapter": "beijing",
                "parser_version": "1",
                "extracted_at": "2026-07-21T01:00:00+08:00",
                "published_at": "2026-07-21",
                "adjustment_date": "2026-07-20",
                "confidence": "high",
                "extracted_zones": [
                    {
                        "zone_code": "default",
                        "zone_name": "Default",
                        "items": {"92": price},
                    }
                ],
            },
        )
        return path

    def test_identical_province_results_merge_provenance_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notice_a = self._write_notice(root, "notice-a", 8.0, "a" * 64)
            notice_b = self._write_notice(root, "notice-b", 8.0, "b" * 64)

            with patch.object(
                price_snapshot,
                "now_china_iso",
                return_value="2026-07-21T02:00:00+08:00",
            ):
                forward = price_snapshot.build_snapshot(
                    "2026-07-20",
                    [notice_a, notice_b],
                )
                reverse = price_snapshot.build_snapshot(
                    "2026-07-20",
                    [notice_b, notice_a],
                )

            self.assertEqual(forward, reverse)
            sources = forward["provinces"][0]["sources"]
            self.assertEqual(
                [source["notice_id"] for source in sources],
                ["notice-a", "notice-b"],
            )
            self.assertEqual(sources[0]["raw_sha256"], "a" * 64)
            self.assertEqual(sources[0]["url"], "https://example.test/notice-a")
            self.assertEqual(sources[0]["adapter"], "beijing")
            self.assertEqual(sources[0]["parser_version"], "1")
            self.assertEqual(sources[0]["extracted_at"], "2026-07-21T01:00:00+08:00")
            self.assertEqual(sources[0]["published_at"], "2026-07-21")
            self.assertEqual(sources[0]["adjustment_date"], "2026-07-20")
            self.assertEqual(sources[0]["confidence"], "high")

    def test_conflicting_province_results_raise_with_notice_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notice_a = self._write_notice(root, "notice-a", 8.0, "a" * 64)
            notice_b = self._write_notice(root, "notice-b", 8.1, "b" * 64)

            with self.assertRaisesRegex(
                RuntimeError,
                r"110000.*notice-a.*notice-b",
            ):
                price_snapshot.build_snapshot(
                    "2026-07-20",
                    [notice_b, notice_a],
                )

    def test_conflicting_province_names_are_not_silently_merged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notice_a = self._write_notice(root, "notice-a", 8.0, "a" * 64)
            notice_b = self._write_notice(
                root,
                "notice-b",
                8.0,
                "b" * 64,
                province_name="Different name",
            )

            with self.assertRaisesRegex(
                RuntimeError,
                r"Conflicting province names.*110000.*notice-a.*notice-b",
            ):
                price_snapshot.build_snapshot(
                    "2026-07-20",
                    [notice_a, notice_b],
                )


if __name__ == "__main__":
    unittest.main()
