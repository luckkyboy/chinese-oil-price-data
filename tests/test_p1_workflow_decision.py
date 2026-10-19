from __future__ import annotations

import unittest
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from oilprice.io import read_json, write_json
from oilprice.ndrc import NdrcNotice
from oilprice.workflow_decision import decide_fetch, decide_fetch_for_repository


def _calendar(*entries: tuple[str, str | None]) -> dict[str, object]:
    return {
        "adjustment_dates": [
            {
                "date": adjustment_date,
                **({"result": result} if result is not None else {}),
            }
            for adjustment_date, result in entries
        ]
    }


def _summary(status: str, missing: list[str] | None = None) -> dict[str, object]:
    return {
        "status": status,
        "provinces_missing": [] if missing is None else missing,
    }


class WorkflowDecisionTests(unittest.TestCase):
    calendar = _calendar(
        ("2026-07-03", None),
        ("2026-07-17", None),
        ("2026-07-31", None),
    )

    def test_cross_day_run_retries_latest_partial_window(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {
                "2026-07-03": _summary("complete"),
                "2026-07-17": _summary("partial", ["210000", "510000"]),
            },
            through_date=date(2026, 7, 19),
        )

        self.assertEqual(decision.target_date, "2026-07-17")
        self.assertEqual(decision.mode, "missing")
        self.assertEqual(decision.provinces_missing, ("210000", "510000"))

    def test_missing_window_stops_after_five_complete_days(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {"2026-07-17": _summary("partial", ["510000"])},
            through_date=date(2026, 7, 22),
        )

        self.assertEqual(decision.mode, "skip")
        self.assertEqual(decision.reason, "retry_window_expired")
        self.assertEqual(decision.provinces_missing, ("510000",))

    def test_missing_window_retries_until_five_complete_days_have_elapsed(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {"2026-07-17": _summary("partial", ["510000"])},
            through_date=date(2026, 7, 21),
        )

        self.assertEqual(decision.mode, "missing")
        self.assertEqual(decision.reason, "summary_has_missing_provinces")

    def test_explicit_date_can_retry_expired_window(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {"2026-07-17": _summary("partial", ["510000"])},
            through_date=date(2026, 7, 19),
            requested_date="2026-07-17",
        )

        self.assertEqual(decision.mode, "missing")
        self.assertEqual(decision.provinces_missing, ("510000",))

    def test_latest_complete_window_skips_old_partial_window(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {
                "2026-07-03": _summary("partial", ["630000"]),
                "2026-07-17": _summary("complete"),
            },
            through_date=date(2026, 7, 20),
        )

        self.assertEqual(decision.target_date, "2026-07-17")
        self.assertEqual(decision.mode, "skip")
        self.assertEqual(decision.reason, "already_complete")

    def test_latest_unresolved_window_wins_over_older_unresolved_window(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {
                "2026-07-03": _summary("partial", ["630000"]),
                "2026-07-17": _summary("partial", ["510000"]),
            },
            through_date=date(2026, 7, 20),
        )

        self.assertEqual(decision.target_date, "2026-07-17")
        self.assertEqual(decision.provinces_missing, ("510000",))

    def test_missing_summary_for_due_window_forces_full_run(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {"2026-07-03": _summary("complete")},
            through_date=date(2026, 7, 20),
        )

        self.assertEqual(decision.target_date, "2026-07-17")
        self.assertEqual(decision.mode, "force")
        self.assertEqual(decision.reason, "summary_missing")

    def test_complete_status_with_missing_provinces_is_not_resolved(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {"2026-07-17": _summary("complete", ["330000"])},
            through_date=date(2026, 7, 19),
        )

        self.assertEqual(decision.mode, "missing")
        self.assertEqual(decision.provinces_missing, ("330000",))

    def test_partial_status_without_missing_codes_forces_contract_recovery(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {"2026-07-17": _summary("partial")},
            through_date=date(2026, 7, 20),
        )

        self.assertEqual(decision.mode, "force")
        self.assertEqual(decision.reason, "summary_invalid")

    def test_explicit_noncanonical_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical YYYY-MM-DD"):
            decide_fetch(
                self.calendar,
                {},
                through_date=date(2026, 7, 20),
                requested_date="2026-7-17",
            )

    def test_explicit_valid_date_keeps_single_window_behavior(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {"2026-07-03": _summary("partial", ["630000"])},
            through_date=date(2026, 7, 20),
            requested_date="2026-07-17",
        )

        self.assertEqual(decision.target_date, "2026-07-17")
        self.assertEqual(decision.mode, "force")

    def test_calendar_no_change_is_resolved_without_a_summary(self) -> None:
        calendar = _calendar(
            ("2026-07-03", None),
            ("2026-07-17", "no_change"),
        )
        decision = decide_fetch(
            calendar,
            {"2026-07-03": _summary("complete")},
            through_date=date(2026, 7, 20),
        )

        self.assertEqual(decision.target_date, "2026-07-17")
        self.assertEqual(decision.mode, "skip")
        self.assertEqual(decision.reason, "calendar_no_change")

    def test_latest_due_window_without_summary_forces_full_run(self) -> None:
        decision = decide_fetch(
            self.calendar,
            {},
            through_date=date(2026, 7, 20),
        )

        self.assertEqual(decision.target_date, "2026-07-17")
        self.assertEqual(decision.mode, "force")

    def test_workflow_delegates_business_logic_to_python_module(self) -> None:
        workflow = Path(".github/workflows/daily-fetch.yml").read_text(encoding="utf-8")

        self.assertIn("decide_fetch_for_repository", workflow)
        self.assertNotIn("adjustment_dates =", workflow)
        self.assertNotIn("summary.get(", workflow)

    def test_skip_takes_precedence_over_missing_summary_and_manual_dispatch(self) -> None:
        calendar = _calendar(("2026-10-15", None), ("2026-10-29", None))
        calendar["adjustment_dates"][0]["skip"] = True
        for requested_date in ("", "2026-10-15"):
            with self.subTest(requested_date=requested_date):
                decision = decide_fetch(
                    calendar, {}, through_date=date(2026, 10, 16),
                    requested_date=requested_date,
                )
                self.assertEqual(decision.target_date, "2026-10-15")
                self.assertEqual(decision.mode, "skip")
                self.assertEqual(decision.reason, "ndrc_no_price_adjustment")

    def test_skip_false_retains_fetch_behavior(self) -> None:
        calendar = _calendar(("2026-10-15", None))
        calendar["adjustment_dates"][0]["skip"] = False
        decision = decide_fetch(calendar, {}, through_date=date(2026, 10, 16))
        self.assertEqual(decision.mode, "force")

    def test_skip_does_not_select_older_partial_or_block_next_window(self) -> None:
        calendar = _calendar(("2026-10-15", None), ("2026-10-29", None))
        calendar["adjustment_dates"][0]["skip"] = True
        decision = decide_fetch(calendar, {}, through_date=date(2026, 10, 30))
        self.assertEqual(decision.target_date, "2026-10-29")
        self.assertEqual(decision.mode, "force")

    def test_skip_must_be_boolean(self) -> None:
        for value in ("true", "false", 1, None):
            with self.subTest(value=value):
                calendar = _calendar(("2026-10-15", None))
                calendar["adjustment_dates"][0]["skip"] = value
                with self.assertRaisesRegex(ValueError, "skip.*boolean"):
                    decide_fetch(calendar, {}, through_date=date(2026, 10, 16))


class RepositoryDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calendar_path = self.root / "data/calendar/2026.json"
        self.calendar = _calendar(("2026-10-15", None), ("2026-10-29", None))
        write_json(self.calendar_path, self.calendar)
        write_json(self.root / "data/calendar/latest.json", {"path": "/data/calendar/2026.json"})

    def decide(self, **kwargs):
        return decide_fetch_for_repository(
            self.root, today_shanghai=date(2026, 10, 17), **kwargs,
        )

    def test_no_change_is_persisted_and_later_runs_do_not_contact_ndrc(self) -> None:
        notice = NdrcNotice(
            "2026年10月15日国内成品油价格不作调整",
            "https://www.ndrc.gov.cn/xwdt/xwfb/202610/t20261015_1408170.html",
        )
        with patch("oilprice.workflow_decision.find_ndrc_notice", return_value=notice) as lookup:
            decision = self.decide()
            lookup.assert_called_once_with(date(2026, 10, 15))
        self.assertEqual(decision.mode, "skip")
        self.assertEqual(decision.reason, "ndrc_no_price_adjustment")
        saved = read_json(self.calendar_path)
        self.assertIs(saved["adjustment_dates"][0]["skip"], True)
        self.assertEqual(
            saved["adjustment_dates"][0]["ndrc_notice"],
            {"title": notice.title, "url": notice.url},
        )
        self.assertEqual(saved["adjustment_dates"][1], self.calendar["adjustment_dates"][1])
        with patch("oilprice.workflow_decision.find_ndrc_notice") as lookup:
            self.assertEqual(self.decide(), decision)
            self.assertEqual(self.decide(requested_date="2026-10-15"), decision)
            lookup.assert_not_called()
        self.assertFalse((self.root / "data/prices").exists())

    def test_adjustment_is_cached_once_for_force_and_missing_runs(self) -> None:
        notice = NdrcNotice("2026年10月15日国内成品油价格调整", "https://www.ndrc.gov.cn/")
        with patch("oilprice.workflow_decision.find_ndrc_notice", return_value=notice) as lookup:
            self.assertEqual(self.decide().mode, "force")
            saved = read_json(self.calendar_path)
            self.assertIs(saved["adjustment_dates"][0]["skip"], False)
            self.assertEqual(
                saved["adjustment_dates"][0]["ndrc_notice"],
                {"title": notice.title, "url": notice.url},
            )
            self.assertEqual(saved["adjustment_dates"][1], self.calendar["adjustment_dates"][1])
            before = self.calendar_path.read_bytes()
            self.assertEqual(self.decide().mode, "force")
            write_json(
                self.root / "data/prices/2026/2026-10-15.summary.json",
                _summary("partial", ["510000"]),
            )
            decision = self.decide()
            self.assertEqual(decision.mode, "missing")
            self.assertEqual(decision.provinces_missing, ("510000",))
            self.assertEqual(self.decide(requested_date="2026-10-15"), decision)
            lookup.assert_called_once_with(date(2026, 10, 15))
        self.assertEqual(self.calendar_path.read_bytes(), before)

    def test_existing_false_allows_fetch_without_querying_ndrc(self) -> None:
        self.calendar["adjustment_dates"][0]["skip"] = False
        write_json(self.calendar_path, self.calendar)
        with patch("oilprice.workflow_decision.find_ndrc_notice", side_effect=TimeoutError) as lookup:
            self.assertEqual(self.decide().mode, "force")
            self.assertEqual(self.decide(requested_date="2026-10-15").mode, "force")
            lookup.assert_not_called()

    def test_next_window_still_requires_its_own_announcement(self) -> None:
        self.calendar["adjustment_dates"][0]["skip"] = False
        write_json(self.calendar_path, self.calendar)
        with patch("oilprice.workflow_decision.find_ndrc_notice", return_value=None) as lookup:
            decision = decide_fetch_for_repository(
                self.root, today_shanghai=date(2026, 10, 30),
            )
            lookup.assert_called_once_with(date(2026, 10, 29))
        self.assertEqual(decision.target_date, "2026-10-29")
        self.assertEqual(decision.reason, "ndrc_notice_not_found")
        self.assertNotIn("skip", read_json(self.calendar_path)["adjustment_dates"][1])

    def test_cache_write_failure_does_not_allow_fetch(self) -> None:
        notice = NdrcNotice("2026年10月15日国内成品油价格调整", "https://www.ndrc.gov.cn/")
        before = self.calendar_path.read_bytes()
        with (
            patch("oilprice.workflow_decision.find_ndrc_notice", return_value=notice),
            patch("oilprice.workflow_decision.write_json", side_effect=OSError("write failed")),
        ):
            with self.assertRaisesRegex(OSError, "write failed"):
                self.decide()
        self.assertEqual(self.calendar_path.read_bytes(), before)

    def test_absent_notice_is_pending_without_persisting_skip(self) -> None:
        before = self.calendar_path.read_bytes()
        with patch("oilprice.workflow_decision.find_ndrc_notice", return_value=None) as lookup:
            for _ in range(2):
                decision = self.decide()
                self.assertEqual(decision.mode, "skip")
                self.assertEqual(decision.reason, "ndrc_notice_not_found")
            self.assertEqual(lookup.call_count, 2)
        self.assertEqual(self.calendar_path.read_bytes(), before)

    def test_failed_lookup_does_not_allow_fetch_or_write_skip(self) -> None:
        before = self.calendar_path.read_bytes()
        with patch("oilprice.workflow_decision.find_ndrc_notice", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.decide()
        self.assertEqual(self.calendar_path.read_bytes(), before)

    def test_completed_or_nonadjustment_windows_need_no_network(self) -> None:
        write_json(
            self.root / "data/prices/2026/2026-10-15.summary.json", _summary("complete"),
        )
        with patch("oilprice.workflow_decision.find_ndrc_notice") as lookup:
            self.assertEqual(self.decide().reason, "already_complete")
            self.assertEqual(self.decide(requested_date="2026-10-16").reason, "not_adjustment_date")
            lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
