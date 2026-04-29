#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlopen


HOLIDAY_DATA_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/bastengao/chinese-holidays-data/master/data/{year}.json"
)

BOOTSTRAP_ANCHORS = {
    2026: "2025-12-22",
}


def expand_range(raw_range: list[str]) -> list[date]:
    if len(raw_range) == 1:
        return [date.fromisoformat(raw_range[0])]

    start = date.fromisoformat(raw_range[0])
    end = date.fromisoformat(raw_range[1])
    result: list[date] = []
    current = start
    while current <= end:
        result.append(current)
        current += timedelta(days=1)
    return result


def fetch_holiday_calendar(year: int) -> tuple[set[date], set[date], str]:
    url = HOLIDAY_DATA_URL_TEMPLATE.format(year=year)
    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    holidays: set[date] = set()
    working_days: set[date] = set()
    for item in payload:
        target_set = working_days if item["type"] == "workingday" else holidays
        target_set.update(expand_range(item["range"]))

    return holidays, working_days, url


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

    previous_path = Path("data/calendar") / f"{year - 1}.json"
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
    holidays, working_days, holiday_source_url = fetch_holiday_calendar(year)
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
            {
                "name": f"{year} holiday and working-day data",
                "url": holiday_source_url,
            },
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
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.year}.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
