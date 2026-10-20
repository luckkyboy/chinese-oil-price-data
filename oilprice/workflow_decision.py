from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from oilprice.io import write_json
from oilprice.ndrc import find_ndrc_notice


FetchMode = Literal["force", "missing", "skip"]
_PROVINCE_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_MAX_AUTOMATIC_RETRY_DAYS = 5


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
    skip: bool = False

    @property
    def text(self) -> str:
        return self.value.isoformat()


def decide_fetch(
    calendar: Mapping[str, object],
    summaries: Mapping[str, Mapping[str, object]],
    *,
    through_date: date,
    requested_date: str = "",
) -> FetchDecision:
    """Choose one adjustment window without reading or writing external state.

    Scheduled runs evaluate only the newest window due by ``through_date``. On
    a day without a due adjustment this is the latest completed window, so a
    fully collected summary (provinces_total == provinces_success) makes the
    workflow skip instead of re-running stale partial windows from previous
    rounds. Explicit dates retain the single-date workflow behavior.
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

    latest_window = due_windows[-1]
    summary = summaries.get(latest_window.text)
    decision = _classify_window(latest_window, summary)

    # Give an incomplete adjustment window five complete calendar days after
    # the adjustment date for automatic retries. Manual dispatches above keep
    # the existing behavior and can still force a later recovery attempt.
    if (
        decision.mode in {"force", "missing"}
        and through_date >= latest_window.value + timedelta(days=_MAX_AUTOMATIC_RETRY_DAYS)
    ):
        return FetchDecision(
            target_date=decision.target_date,
            mode="skip",
            reason="retry_window_expired",
            summary_path=decision.summary_path,
            provinces_missing=decision.provinces_missing,
        )

    return decision


def decide_fetch_for_repository(
    root: Path,
    *,
    requested_date: str = "",
    today_shanghai: date | None = None,
) -> FetchDecision:
    """Choose a window and cache its confirmed NDRC adjustment decision."""

    root = root.resolve()
    if today_shanghai is None:
        today_shanghai = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    through_date = today_shanghai - timedelta(days=1)
    calendars = _load_repository_calendars(root, through_date, requested_date)
    calendar = {
        "adjustment_dates": [
            entry for _, payload in calendars for entry in payload["adjustment_dates"]
        ],
    }

    prices_root = root / "data" / "prices"
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

    decision = decide_fetch(
        calendar,
        summaries,
        through_date=through_date,
        requested_date=requested_date,
    )
    if decision.mode == "skip":
        return decision

    entry = next(
        entry for entry in calendar["adjustment_dates"]
        if entry["date"] == decision.target_date
    )
    # An explicit false records a confirmed adjustment. Absence means the
    # announcement has not been checked successfully yet.
    if "skip" in entry:
        return decision

    notice = find_ndrc_notice(date.fromisoformat(decision.target_date))
    if notice is None:
        return FetchDecision(
            target_date=decision.target_date,
            mode="skip",
            reason="ndrc_notice_not_found",
        )
    entry["skip"] = notice.no_change
    entry["ndrc_notice"] = {"title": notice.title, "url": notice.url}
    calendar_path, owning_calendar = next(
        (path, payload) for path, payload in calendars
        if any(item is entry for item in payload["adjustment_dates"])
    )
    write_json(calendar_path, owning_calendar)
    return decide_fetch(
        calendar,
        summaries,
        through_date=through_date,
        requested_date=requested_date,
    )


def _load_repository_calendars(
    root: Path, through_date: date, requested_date: str,
) -> list[tuple[Path, dict[str, object]]]:
    calendar_root = root / "data" / "calendar"
    if requested_date.strip():
        target = _parse_canonical_date(requested_date, label="workflow_dispatch date")
        paths = [calendar_root / f"{target.year}.json"]
    else:
        latest = _read_json(calendar_root / "latest.json")
        raw_path = latest.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("calendar latest path must be a non-empty string")
        latest_path = _resolve_repo_path(root, raw_path)
        # The latest pointer may already refer to next year's calendar. Keep
        # the previous year's final window eligible during the year boundary.
        paths = [
            latest_path,
            calendar_root / f"{through_date.year}.json",
            calendar_root / f"{through_date.year - 1}.json",
        ]

    loaded: list[tuple[Path, dict[str, object]]] = []
    seen: set[Path] = set()
    for path in paths:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            # A broken latest pointer is a configuration error; optional
            # adjacent years and absent manual years have no eligible windows.
            if not requested_date.strip() and path == paths[0]:
                raise FileNotFoundError(path)
            continue
        payload = _read_json(path)
        _parse_windows(payload)
        loaded.append((path, payload))
    return loaded


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
        skip = raw_window.get("skip", False)
        if not isinstance(skip, bool):
            raise ValueError(f"calendar skip for {raw_date} must be a boolean")
        windows.append(_AdjustmentWindow(parsed_date, result, skip))

    return sorted(windows, key=lambda window: window.value)


def _classify_window(
    window: _AdjustmentWindow,
    summary: Mapping[str, object] | None,
) -> FetchDecision:
    if window.skip:
        return FetchDecision(
            target_date=window.text,
            mode="skip",
            reason="ndrc_no_price_adjustment",
        )
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
