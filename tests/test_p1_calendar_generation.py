from __future__ import annotations

import contextlib
import copy
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oilprice.io import read_json, write_json
from script import generate_calendar


class CalendarGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output_dir = Path(self.temp.name)
        self.output_path = self.output_dir / "2026.json"
        self.generated = {
            "year": 2026,
            "generated_at": "2026-10-20T00:00:00+08:00",
            "adjustment_dates": [
                {"date": "2026-01-06", "round": 1},
                {"date": "2026-01-20", "round": 2},
            ],
        }

    def run_generator(self) -> None:
        argv = [
            "generate_calendar.py", "2026", "--anchor", "2025-12-22",
            "--today", "2026-10-20", "--output-dir", str(self.output_dir),
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(generate_calendar, "build_calendar_payload", return_value=self.generated),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            generate_calendar.main()

    def test_regeneration_preserves_all_saved_metadata_by_date(self) -> None:
        existing = copy.deepcopy(self.generated)
        existing["generated_at"] = "old"
        first, second = existing["adjustment_dates"]
        first.update({
            "round": 99,
            "skip": True,
            "ndrc_notice": {"title": "国内成品油价格不作调整", "url": "https://www.ndrc.gov.cn/a"},
            "result": "no_change",
            "custom_confirmation": {"verified": True},
        })
        second["skip"] = False
        # Matching is by date, independent of the old ordering and round.
        existing["adjustment_dates"].reverse()
        write_json(self.output_path, existing)

        self.run_generator()

        saved = read_json(self.output_path)
        self.assertEqual(saved["generated_at"], self.generated["generated_at"])
        self.assertEqual(saved["adjustment_dates"][0], {**first, "round": 1})
        self.assertEqual(saved["adjustment_dates"][1], second)

    def test_removed_windows_with_any_metadata_abort_without_changing_file(self) -> None:
        for metadata in ({"skip": False}, {"skip": True}, {"ndrc_notice": {}}, {"result": "no_change"}):
            with self.subTest(metadata=metadata):
                existing = copy.deepcopy(self.generated)
                existing["adjustment_dates"].append({
                    "date": "2026-02-03", "round": 3, **metadata,
                })
                write_json(self.output_path, existing)
                before = self.output_path.read_bytes()

                with self.assertRaisesRegex(ValueError, "remove windows with saved metadata.*2026-02-03"):
                    self.run_generator()

                self.assertEqual(self.output_path.read_bytes(), before)

    def test_unconfirmed_removed_windows_and_legacy_string_dates_can_regenerate(self) -> None:
        write_json(self.output_path, {
            "adjustment_dates": ["2026-01-06", {"date": "2026-02-03", "round": 3}],
        })

        self.run_generator()

        self.assertEqual(read_json(self.output_path), self.generated)

    def test_atomic_publication_failure_keeps_original_calendar(self) -> None:
        existing = copy.deepcopy(self.generated)
        existing["adjustment_dates"][0]["skip"] = True
        write_json(self.output_path, existing)
        before = self.output_path.read_bytes()

        with patch("oilprice.io.os.replace", side_effect=OSError("publication failed")):
            with self.assertRaisesRegex(OSError, "publication failed"):
                self.run_generator()

        self.assertEqual(self.output_path.read_bytes(), before)
        self.assertEqual(list(self.output_dir.iterdir()), [self.output_path])

    def test_direct_script_entry_point_imports_package_from_other_directory(self) -> None:
        script_path = Path(generate_calendar.__file__).resolve()
        result = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            cwd=self.output_dir, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Generate refined oil adjustment calendar JSON", result.stdout)


if __name__ == "__main__":
    unittest.main()
