#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

# Keep the documented direct-script entry point usable without installation.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oilprice.io import write_json
from oilprice.paths import ROOT


BOOTSTRAP_ANCHORS = {
    2026: "2025-12-22",
}


def expand_range(raw_range: list[str]) -> list[date]:
    if len(raw_range) not in {1, 2}:
        raise ValueError("holiday range must contain one or two dates")
    if len(raw_range) == 1:
        return [date.fromisoformat(raw_range[0])]

    start = date.fromisoformat(raw_range[0])
    end = date.fromisoformat(raw_range[1])
    if end < start:
        raise ValueError(f"holiday range ends before it starts: {raw_range}")
    result: list[date] = []
    current = start
    while current <= end:
        result.append(current)
        current += timedelta(days=1)
    return result


def load_holiday_calendar(year: int) -> tuple[set[date], set[date], list[dict[str, str]]]:
    """Read the repository's holiday/workday configuration without network I/O."""
    from jsonschema import Draft202012Validator, FormatChecker

    path = ROOT / "data/holidays" / f"{year}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schema/holidays.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)

    holidays: set[date] = set()
    working_days: set[date] = set()
    for item in payload["holidays"]:
        target_set = working_days if item["type"] == "workingday" else holidays
        target_set.update(expand_range(item["range"]))

    overlap = holidays & working_days
    if overlap:
        raise ValueError(
            "dates declared as both holiday and workingday: "
            + ", ".join(day.isoformat() for day in sorted(overlap))
        )
    return holidays, working_days, payload["sources"]


def is_workday(target_day: date, holidays: set[date], working_days: set[date]) -> bool:
    if target_day in working_days:
        return True
    if target_day in holidays:
        return False
    return target_day.weekday() < 5


def next_adjustment_day(
    current: date,
    holidays: set[date],
    working_days: set[date],
) -> date:
    counted = 0
    target = current
    while counted < 10:
        target += timedelta(days=1)
        if is_workday(target, holidays, working_days):
            counted += 1
    return target


def derive_adjustment_dates(
    target_year: int,
    anchor_previous_adjustment_date: date,
    holidays: set[date],
    working_days: set[date],
) -> list[date]:
    current = anchor_previous_adjustment_date
    adjustment_dates: list[date] = []

    while True:
        current = next_adjustment_day(current, holidays, working_days)
        if current.year > target_year:
            break
        if current.year == target_year:
            adjustment_dates.append(current)

    return adjustment_dates


def resolve_anchor_previous_adjustment_date(year: int, explicit_anchor: str | None) -> str:
    if explicit_anchor:
        return explicit_anchor

    bootstrap_anchor = BOOTSTRAP_ANCHORS.get(year)
    if bootstrap_anchor:
        return bootstrap_anchor

    previous_path = ROOT / "data/calendar" / f"{year - 1}.json"
    if previous_path.exists():
        payload = json.loads(previous_path.read_text(encoding="utf-8"))
        adjustment_dates = payload.get("adjustment_dates", [])
        if adjustment_dates:
            previous_last = adjustment_dates[-1]
            if isinstance(previous_last, str):
                return previous_last
            return previous_last["date"]

    raise ValueError(f"missing bootstrap anchor or previous-year calendar for {year}")


def build_calendar_payload(
    year: int,
    anchor_previous_adjustment_date: str,
    today: date,
) -> dict[str, object]:
    holidays, working_days, holiday_sources = load_holiday_calendar(year)
    adjustment_dates = derive_adjustment_dates(
        target_year=year,
        anchor_previous_adjustment_date=date.fromisoformat(anchor_previous_adjustment_date),
        holidays=holidays,
        working_days=working_days,
    )

    return {
        "year": year,
        "timezone": "Asia/Shanghai",
        "rule": {
            "name": "10-working-day refined oil adjustment window",
            "description": (
                "Domestic refined oil adjustment window dates derived from the "
                "10-working-day NDRC rule and the China holiday/workday calendar."
            ),
        },
        "generated_at": f"{today.isoformat()}T00:00:00+08:00",
        "anchor_previous_adjustment_date": anchor_previous_adjustment_date,
        "adjustment_dates": [
            {
                "date": adjustment_day.isoformat(),
                "round": index,
            }
            for index, adjustment_day in enumerate(adjustment_dates, start=1)
        ],
        "sources": [
            {
                "name": "国家发展改革委关于进一步完善成品油价格形成机制的通知",
                "url": "https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=19805",
            },
            *holiday_sources,
        ],
    }


def preserve_calendar_metadata(
    generated: dict[str, object], existing: dict[str, object],
) -> dict[str, object]:
    """Retain confirmed window metadata while refreshing derived dates/rounds."""
    old_windows = existing.get("adjustment_dates")
    if not isinstance(old_windows, list):
        raise ValueError("existing calendar adjustment_dates must be a list")
    old_by_date: dict[str, dict[str, object]] = {}
    for entry in old_windows:
        if isinstance(entry, str):
            entry = {"date": entry}
        if not isinstance(entry, dict) or not isinstance(entry.get("date"), str):
            raise ValueError("existing calendar adjustment date entries must contain date")
        entry_date = entry["date"]
        if entry_date in old_by_date:
            raise ValueError(f"duplicate existing calendar adjustment date: {entry_date}")
        old_by_date[entry_date] = entry

    generated_dates = {entry["date"] for entry in generated["adjustment_dates"]}
    removed_confirmed = [
        entry_date for entry_date, entry in old_by_date.items()
        if entry_date not in generated_dates and set(entry) - {"date", "round"}
    ]
    if removed_confirmed:
        raise ValueError(
            "regenerated calendar would remove windows with saved metadata: "
            + ", ".join(sorted(removed_confirmed))
        )
    return {
        **generated,
        "adjustment_dates": [
            {**old_by_date.get(entry["date"], {}), **entry}
            for entry in generated["adjustment_dates"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate refined oil adjustment calendar JSON.")
    parser.add_argument("year", type=int, nargs="?", default=date.today().year)
    parser.add_argument("--anchor", help="Previous adjustment date, formatted as YYYY-MM-DD.")
    parser.add_argument("--today", help="Generation date, formatted as YYYY-MM-DD.")
    parser.add_argument("--output-dir", default="data/calendar")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    anchor = resolve_anchor_previous_adjustment_date(args.year, args.anchor)
    payload = build_calendar_payload(args.year, anchor, today)

    output_dir = Path(args.output_dir)
    output_path = output_dir / f"{args.year}.json"
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise ValueError("existing calendar must be a JSON object")
        payload = preserve_calendar_metadata(payload, existing)
    write_json(output_path, payload)
    print(output_path)


if __name__ == "__main__":
    main()
