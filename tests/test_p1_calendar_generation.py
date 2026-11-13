from __future__ import annotations

import contextlib
import copy
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
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

    def test_generation_updates_latest_pointer_in_output_directory(self) -> None:
        latest_path = self.output_dir / "latest.json"
        write_json(latest_path, {"year": 2025, "path": "/data/calendar/2025.json",
                                 "updated_at": "2025-01-01T00:00:00+08:00"})
        self.run_generator()
        self.assertEqual(read_json(latest_path), {
            "year": 2026, "path": "/data/calendar/2026.json",
            "updated_at": self.generated["generated_at"],
        })
        self.assertEqual(read_json(self.output_path), self.generated)

    def test_latest_failure_rolls_back_calendar_and_pointer(self) -> None:
        latest_path = self.output_dir / "latest.json"
        write_json(self.output_path, {**self.generated, "generated_at": "old"})
        write_json(latest_path, {"year": 2025, "path": "/data/calendar/2025.json",
                                 "updated_at": "2025-01-01T00:00:00+08:00"})
        before = {path: path.read_bytes() for path in (self.output_path, latest_path)}
        replace = os.replace

        def fail_latest(source, target):
            if Path(target) == latest_path:
                raise OSError("latest publication failed")
            return replace(source, target)

        with patch("oilprice.io.os.replace", side_effect=fail_latest):
            with self.assertRaisesRegex(OSError, "latest publication failed"):
                self.run_generator()
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual(set(self.output_dir.iterdir()), set(before))

    def test_latest_failure_removes_new_calendar(self) -> None:
        replace = os.replace

        def fail_latest(source, target):
            if Path(target).name == "latest.json":
                raise OSError("latest publication failed")
            return replace(source, target)

        with patch("oilprice.io.os.replace", side_effect=fail_latest):
            with self.assertRaisesRegex(OSError, "latest publication failed"):
                self.run_generator()
        self.assertEqual(list(self.output_dir.iterdir()), [])

    def test_direct_script_entry_point_imports_package_from_other_directory(self) -> None:
        script_path = Path(generate_calendar.__file__).resolve()
        result = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            cwd=self.output_dir, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Generate refined oil adjustment calendar JSON", result.stdout)


class LocalHolidayCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        schema_path = self.root / "schema/holidays.schema.json"
        schema_path.parent.mkdir(parents=True)
        schema_path.write_bytes((generate_calendar.ROOT / "schema/holidays.schema.json").read_bytes())
        self.path = self.root / "data/holidays/2027.json"
        self.payload = {
            "holidays": [
                {"name": "元旦", "range": ["2027-01-01", "2027-01-03"], "type": "holiday"},
                {"name": "春节", "range": ["2027-01-31"], "type": "workingday"},
            ],
            "sources": [{"name": "本地维护的来源", "url": "https://example.gov.cn/2027"}],
        }

    def load(self):
        write_json(self.path, self.payload)
        with patch.object(generate_calendar, "ROOT", self.root):
            return generate_calendar.load_holiday_calendar(2027)

    def test_local_ranges_working_sunday_and_source_metadata(self) -> None:
        holidays, working_days, sources = self.load()
        self.assertEqual(holidays, {date(2027, 1, day) for day in (1, 2, 3)})
        self.assertEqual(working_days, {date(2027, 1, 31)})
        self.assertFalse(generate_calendar.is_workday(date(2027, 1, 1), holidays, working_days))
        self.assertTrue(generate_calendar.is_workday(date(2027, 1, 31), holidays, working_days))
        self.assertEqual(sources, self.payload["sources"])

    def test_invalid_format_or_types_are_rejected_by_schema(self) -> None:
        from jsonschema import ValidationError
        original = copy.deepcopy(self.payload)
        for bad in (
            original["holidays"],
            {**original, "holidays": [{"name": "bad", "range": ["2027-02-30"], "type": "holiday"}]},
            {**original, "holidays": [{"name": "bad", "range": ["2027-01-30", "2027-01-31"], "type": "workingday"}]},
            {**original, "holidays": [{"name": "bad", "range": ["2027-01-31"], "type": "unknown"}]},
        ):
            with self.subTest(payload=bad):
                self.payload = bad
                with self.assertRaises(ValidationError):
                    self.load()

    def test_reversed_ranges_and_conflicting_days_are_rejected(self) -> None:
        self.payload["holidays"][0]["range"] = ["2027-01-03", "2027-01-01"]
        with self.assertRaisesRegex(ValueError, "ends before it starts"):
            self.load()
        self.payload["holidays"][0]["range"] = ["2027-01-31"]
        with self.assertRaisesRegex(ValueError, "both holiday and workingday.*2027-01-31"):
            self.load()

    def test_missing_local_file_fails_without_remote_fallback(self) -> None:
        with patch.object(generate_calendar, "ROOT", self.root):
            with self.assertRaises(FileNotFoundError):
                generate_calendar.load_holiday_calendar(2027)

    def test_real_2027_generation_uses_previous_calendar_and_local_sources(self) -> None:
        anchor = generate_calendar.resolve_anchor_previous_adjustment_date(2027, None)
        self.assertEqual(anchor, "2026-12-24")
        result = generate_calendar.build_calendar_payload(2027, anchor, date(2026, 11, 13))
        dates = [entry["date"] for entry in result["adjustment_dates"]]
        self.assertEqual(dates[:4], ["2027-01-08", "2027-01-22", "2027-02-04", "2027-02-25"])
        self.assertEqual(dates[-1], "2027-12-28")
        self.assertEqual(len(dates), 25)
        local = read_json(generate_calendar.ROOT / "data/holidays/2027.json")
        self.assertEqual(result["sources"][1:], local["sources"])


if __name__ == "__main__":
    unittest.main()
