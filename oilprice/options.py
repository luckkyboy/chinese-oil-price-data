from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import ROOT


def parse_province_codes(raw_value: object) -> set[str] | None:
    if raw_value is None:
        return None
    values: list[str]
    if isinstance(raw_value, (list, tuple, set)):
        values = [str(item) for item in raw_value]
    else:
        values = str(raw_value).split(",")
    selected = {value.strip() for value in values if value and value.strip()}
    return selected or None


def notice_index_path(
    *,
    index: str | None = None,
    output: str | None = None,
    adjustment_date: str | None = None,
) -> Path:
    if index:
        return ROOT / index
    if output:
        return ROOT / output
    if adjustment_date:
        return ROOT / "tmp/notices" / adjustment_date / "index.json"
    return ROOT / "tmp/notices/index.json"


@dataclass(frozen=True)
class DiscoverOptions:
    sources_path: Path
    index_path: Path
    adjustment_date: str | None
    timeout: int
    force: bool
    province_codes: set[str] | None = None
    browser_session: Any = None

    @classmethod
    def from_args(cls, args: object) -> "DiscoverOptions":
        adjustment_date = getattr(args, "date", None) or getattr(args, "adjustment_date", None)
        return cls(
            sources_path=ROOT / getattr(args, "sources"),
            index_path=notice_index_path(
                output=getattr(args, "output", None),
                adjustment_date=adjustment_date,
            ),
            adjustment_date=adjustment_date,
            timeout=int(getattr(args, "timeout")),
            force=bool(getattr(args, "force", False)),
            province_codes=parse_province_codes(getattr(args, "province_code", None)),
            browser_session=getattr(args, "browser_session", None),
        )


@dataclass(frozen=True)
class FetchOptions:
    index_path: Path
    adjustment_date: str | None
    timeout: int
    force: bool
    province_codes: set[str] | None = None
    browser_session: Any = None

    @classmethod
    def from_args(cls, args: object) -> "FetchOptions":
        adjustment_date = getattr(args, "date", None) or getattr(args, "adjustment_date", None)
        return cls(
            index_path=notice_index_path(
                index=getattr(args, "index", None),
                adjustment_date=adjustment_date,
            ),
            adjustment_date=adjustment_date,
            timeout=int(getattr(args, "timeout")),
            force=bool(getattr(args, "force", False)),
            province_codes=parse_province_codes(getattr(args, "province_code", None)),
            browser_session=getattr(args, "browser_session", None),
        )


@dataclass(frozen=True)
class ExtractFilesOptions:
    index_path: Path
    adjustment_date: str | None
    force: bool
    province_codes: set[str] | None = None

    @classmethod
    def from_args(cls, args: object) -> "ExtractFilesOptions":
        adjustment_date = getattr(args, "date", None) or getattr(args, "adjustment_date", None)
        return cls(
            index_path=notice_index_path(
                index=getattr(args, "index", None),
                adjustment_date=adjustment_date,
            ),
            adjustment_date=adjustment_date,
            force=bool(getattr(args, "force", False)),
            province_codes=parse_province_codes(getattr(args, "province_code", None)),
        )


@dataclass(frozen=True)
class ExtractOptions:
    sources_path: Path
    index_path: Path
    adjustment_date: str
    timeout: int
    force: bool
    province_codes: set[str] | None = None

    @classmethod
    def from_args(cls, args: object) -> "ExtractOptions":
        adjustment_date = getattr(args, "date", None) or getattr(args, "adjustment_date", None)
        if not adjustment_date:
            raise SystemExit("extract requires an adjustment date")
        return cls(
            sources_path=ROOT / getattr(args, "sources"),
            index_path=notice_index_path(
                index=getattr(args, "index", None),
                adjustment_date=adjustment_date,
            ),
            adjustment_date=adjustment_date,
            timeout=int(getattr(args, "timeout")),
            force=bool(getattr(args, "force", False)),
            province_codes=parse_province_codes(getattr(args, "province_code", None)),
        )


@dataclass(frozen=True)
class PriceOptions:
    index_path: Path
    adjustment_date: str
    province_codes: set[str] | None = None

    @classmethod
    def from_args(cls, args: object) -> "PriceOptions":
        adjustment_date = getattr(args, "adjustment_date")
        return cls(
            index_path=notice_index_path(
                index=getattr(args, "index", None),
                adjustment_date=adjustment_date,
            ),
            adjustment_date=adjustment_date,
            province_codes=parse_province_codes(getattr(args, "province_code", None)),
        )
