from __future__ import annotations

import hashlib
from datetime import date, timedelta
from enum import Enum
from pathlib import Path

from .io import now_china_iso, read_json, write_json
from .payloads import NoticePayload
from .paths import ROOT


class SkipReason(Enum):
    NOT_SELECTED = "not_selected"
    NOT_PENDING = "not_pending"


def slug_from_notice(notice: NoticePayload) -> str:
    notice_id = str(notice["notice_id"])
    digest = hashlib.sha1(str(notice["province_code"]).encode("utf-8")).hexdigest()[:8]
    return notice_id.split("-", 1)[0] or digest


def province_skip_reason(
    province_code: str,
    selected_codes: set[str] | None,
    pending_codes: set[str] | None,
) -> SkipReason | None:
    if selected_codes is not None and province_code not in selected_codes:
        return SkipReason.NOT_SELECTED
    if pending_codes is not None and province_code not in pending_codes:
        return SkipReason.NOT_PENDING
    return None


def read_notice_map(index_path: Path) -> dict[str, NoticePayload]:
    if not index_path.exists():
        return {}
    index = read_json(index_path)
    notices = index.get("notices", [])
    if not isinstance(notices, list):
        return {}
    return {
        str(notice.get("notice_id")): notice
        for notice in notices
        if isinstance(notice, dict) and notice.get("notice_id")
    }


def write_notice_index(index_path: Path, notices_by_id: dict[str, NoticePayload]) -> None:
    write_json(index_path, notice_index_payload(notices_by_id))


def notice_index_payload(notices_by_id: dict[str, NoticePayload]) -> dict[str, object]:
    return {
        "updated_at": now_china_iso(),
        "notices": list(notices_by_id.values()),
    }


def cli_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def filter_notices_for_adjustment_date(
    notices: list[NoticePayload],
    adjustment_date: str,
) -> list[NoticePayload]:
    markers = date_markers_for_adjustment_window(adjustment_date)
    exact_dates = {
        adjustment_date,
        (date.fromisoformat(adjustment_date) + timedelta(days=1)).isoformat(),
    }
    filtered = []
    for notice in notices:
        explicit_adjustment_date = str(notice.get("adjustment_date") or "").strip()
        if is_iso_date(explicit_adjustment_date):
            if explicit_adjustment_date == adjustment_date:
                filtered.append(notice)
            continue

        published_at = str(notice.get("published_at") or "").strip()
        if is_iso_date(published_at):
            if published_at in exact_dates:
                filtered.append(notice)
                continue
        haystack = " ".join(
            str(notice.get(key, ""))
            for key in (
                "title",
                "source_url",
                "notice_id",
                "published_at",
                "adjustment_date",
            )
        )
        if any(marker in haystack for marker in markers):
            filtered.append(notice)
    return filtered


def is_iso_date(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def non_padded_date_path(adjustment_date: str) -> str:
    year, month, day = adjustment_date.split("-")
    return f"{year}/{int(month)}/{int(day)}"


def date_markers_for_adjustment_window(adjustment_date: str) -> set[str]:
    base_day = date.fromisoformat(adjustment_date)
    markers: set[str] = set()
    for day in (base_day, base_day + timedelta(days=1)):
        iso_text = day.isoformat()
        month = day.month
        day_of_month = day.day
        markers.update(
            {
                iso_text,
                iso_text.replace("-", ""),
                iso_text.replace("-", "/"),
                non_padded_date_path(iso_text),
                f"{month:02d}/{day_of_month:02d}",
                f"{month}/{day_of_month}",
                f"{month:02d}-{day_of_month:02d}",
                f"{month}-{day_of_month}",
                f"{day.year}年{month}月{day_of_month}日",
            }
        )
    return markers


def province_code_for_slug(slug: str) -> str | None:
    source_path = ROOT / "data/sources/provinces.json"
    if not source_path.exists():
        return None
    payload = read_json(source_path)
    for province in payload.get("provinces", []):
        if province.get("slug") == slug:
            return str(province["province_code"])
    return None


def pending_province_codes_from_summary(adjustment_date: str) -> set[str] | None:
    summary_path = ROOT / "data/prices" / adjustment_date[:4] / f"{adjustment_date}.summary.json"
    if not summary_path.exists():
        return None

    summary = read_json(summary_path)
    raw_missing = summary.get("provinces_missing")
    if not isinstance(raw_missing, list):
        return None
    return {str(code).strip() for code in raw_missing if str(code).strip()}
