from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo


FetchMode = Literal["force", "missing", "skip"]
_PROVINCE_CODE_PATTERN = re.compile(r"^[0-9]{6}$")


@dataclass(frozen=True)
class FetchDecision:
    target_date: str
    mode: FetchMode
    reason: str
    summary_path: str = ""
    provinces_missing: tuple[str, ...] = ()

    def as_outputs(self) -> dict[str, str]:
        return {
            "target_date": self.target_date,
            "mode": self.mode,
            "reason": self.reason,
            "summary_path": self.summary_path,
            "provinces_missing": ",".join(self.provinces_missing),
        }


@dataclass(frozen=True)
class _AdjustmentWindow:
    value: date
    result: str | None

    @property
    def text(self) -> str:
        return self.value.isoformat()


def decide_fetch(
    calendar: Mapping[str, object],
    summaries: Mapping[str, Mapping[str, object]],
    snapshot_dates: Iterable[str],
    *,
    through_date: date,
    requested_date: str = "",
) -> FetchDecision:
    """Choose one adjustment window without reading or writing external state.

    Scheduled runs track windows starting at the earliest existing price snapshot.
    When there are no snapshots, only the newest window due by ``through_date`` is
    considered. Explicit dates retain the single-date workflow behavior.
    """

    windows = _parse_windows(calendar)
    windows_by_date = {window.value: window for window in windows}

    if requested_date.strip():
        target = _parse_canonical_date(
            requested_date,
            label="workflow_dispatch date",
        )
        window = windows_by_date.get(target)
        if window is None:
            return FetchDecision(
                target_date=target.isoformat(),
                mode="skip",
                reason="not_adjustment_date",
            )
        return _classify_window(window, summaries.get(window.text))

    due_windows = [window for window in windows if window.value <= through_date]
    if not due_windows:
        return FetchDecision(
            target_date=through_date.isoformat(),
            mode="skip",
            reason="no_due_adjustment_date",
        )

    parsed_snapshot_dates = [
        _parse_canonical_date(value, label="snapshot date")
        for value in snapshot_dates
    ]
    if parsed_snapshot_dates:
        tracking_start = min(parsed_snapshot_dates)
        tracked_windows = [
            window for window in due_windows if window.value >= tracking_start
        ]
        # A future-only snapshot set is inconsistent but must not make a due
        # adjustment disappear from the scheduler.
        if not tracked_windows:
            tracked_windows = [due_windows[-1]]
    else:
        tracked_windows = [due_windows[-1]]

    decisions = [
        _classify_window(window, summaries.get(window.text))
        for window in tracked_windows
    ]
    unresolved = [decision for decision in decisions if decision.mode != "skip"]
    if unresolved:
        return unresolved[-1]
    return decisions[-1]


def decide_fetch_for_repository(
    root: Path,
    *,
    requested_date: str = "",
    today_shanghai: date | None = None,
) -> FetchDecision:
    """Load repository state and delegate the actual choice to ``decide_fetch``."""

    root = root.resolve()
    calendar_latest = _read_json(root / "data" / "calendar" / "latest.json")
    calendar_path_value = calendar_latest.get("path")
    if not isinstance(calendar_path_value, str) or not calendar_path_value.strip():
        raise ValueError("calendar latest path must be a non-empty string")
    calendar_path = _resolve_repo_path(root, calendar_path_value)
    calendar = _read_json(calendar_path)

    prices_root = root / "data" / "prices"
    snapshot_dates = [
        path.stem
        for path in prices_root.glob("[0-9][0-9][0-9][0-9]/*.json")
        if not path.name.endswith(".summary.json")
    ]

    summaries: dict[str, Mapping[str, object]] = {}
    for window in _parse_windows(calendar):
        adjustment_date = window.text
        summary_path = (
            prices_root
            / adjustment_date[:4]
            / f"{adjustment_date}.summary.json"
        )
        if summary_path.exists():
            summaries[adjustment_date] = _read_json(summary_path)

    if today_shanghai is None:
        today_shanghai = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    through_date = today_shanghai - timedelta(days=1)
    return decide_fetch(
        calendar,
        summaries,
        snapshot_dates,
        through_date=through_date,
        requested_date=requested_date,
    )


def _parse_windows(calendar: Mapping[str, object]) -> Sequence[_AdjustmentWindow]:
    raw_windows = calendar.get("adjustment_dates")
    if not isinstance(raw_windows, list):
        raise ValueError("calendar adjustment_dates must be a list")

    windows: list[_AdjustmentWindow] = []
    seen: set[date] = set()
    for raw_window in raw_windows:
        if not isinstance(raw_window, Mapping):
            raise ValueError("calendar adjustment date entries must be objects")
        raw_date = raw_window.get("date")
        if not isinstance(raw_date, str):
            raise ValueError("calendar adjustment date entries must contain date")
        parsed_date = _parse_canonical_date(raw_date, label="calendar date")
        if parsed_date in seen:
            raise ValueError(f"duplicate calendar adjustment date: {raw_date}")
        seen.add(parsed_date)
        result = raw_window.get("result")
        if result is not None and not isinstance(result, str):
            raise ValueError(f"calendar result for {raw_date} must be a string")
        windows.append(_AdjustmentWindow(parsed_date, result))

    return sorted(windows, key=lambda window: window.value)


def _classify_window(
    window: _AdjustmentWindow,
    summary: Mapping[str, object] | None,
) -> FetchDecision:
    if window.result == "no_change":
        return FetchDecision(
            target_date=window.text,
            mode="skip",
            reason="calendar_no_change",
        )

    if summary is None:
        return FetchDecision(
            target_date=window.text,
            mode="force",
            reason="summary_missing",
        )

    summary_path = f"data/prices/{window.text[:4]}/{window.text}.summary.json"
    summary_date = summary.get("adjustment_date")
    if summary_date is not None and summary_date != window.text:
        return FetchDecision(
            target_date=window.text,
            mode="force",
            reason="summary_invalid",
            summary_path=summary_path,
        )
    missing = summary.get("provinces_missing")
    if not isinstance(missing, list) or any(
        not isinstance(code, str) or _PROVINCE_CODE_PATTERN.fullmatch(code) is None
        for code in missing
    ):
        return FetchDecision(
            target_date=window.text,
            mode="force",
            reason="summary_invalid",
            summary_path=summary_path,
        )

    missing_codes = tuple(missing)
    status = summary.get("status")
    if missing_codes:
        return FetchDecision(
            target_date=window.text,
            mode="missing",
            reason="summary_has_missing_provinces",
            summary_path=summary_path,
            provinces_missing=missing_codes,
        )
    if status == "partial":
        return FetchDecision(
            target_date=window.text,
            mode="force",
            reason="summary_invalid",
            summary_path=summary_path,
        )
    if status == "complete":
        return FetchDecision(
            target_date=window.text,
            mode="skip",
            reason="already_complete",
            summary_path=summary_path,
        )
    return FetchDecision(
        target_date=window.text,
        mode="force",
        reason="summary_invalid",
        summary_path=summary_path,
    )


def _parse_canonical_date(value: str, *, label: str) -> date:
    if not value or value != value.strip():
        raise ValueError(f"{label} must use canonical YYYY-MM-DD format")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{label} must use canonical YYYY-MM-DD format"
        ) from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must use canonical YYYY-MM-DD format")
    return parsed


def _resolve_repo_path(root: Path, raw_path: str) -> Path:
    candidate = (root / raw_path.lstrip("/\\")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"calendar path escapes repository root: {raw_path}") from exc
    return candidate


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload
