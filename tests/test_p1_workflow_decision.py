from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from oilprice.workflow_decision import decide_fetch


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
            through_date=date(2026, 7, 20),
        )

        self.assertEqual(decision.target_date, "2026-07-17")
        self.assertEqual(decision.mode, "missing")
        self.assertEqual(decision.provinces_missing, ("210000", "510000"))

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
            through_date=date(2026, 7, 20),
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


if __name__ == "__main__":
    unittest.main()
