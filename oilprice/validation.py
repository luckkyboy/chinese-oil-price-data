from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .paths import ROOT


SCHEMA_FILES = {
    "calendar": "calendar.schema.json",
    "calendar_latest": "calendar-latest.schema.json",
    "price_latest": "price-latest.schema.json",
    "price_summary": "price-summary.schema.json",
    "prices": "prices.schema.json",
    "region_index": "region-index.schema.json",
    "region_zones": "region-zones.schema.json",
    "source_sites": "source-sites.schema.json",
}

PRICE_PATH_RE = re.compile(
    r"^data/prices/(?P<year>[0-9]{4})/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\.json$"
)
PRICE_SUMMARY_PATH_RE = re.compile(
    r"^data/prices/(?P<year>[0-9]{4})/"
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\.summary\.json$"
)
CALENDAR_PATH_RE = re.compile(r"^data/calendar/(?P<year>[0-9]{4})\.json$")
REGION_ZONE_PATH_RE = re.compile(r"^data/regions/(?P<slug>[^/]+)\.json$")
PRODUCT_ORDER = ("89", "92", "95", "0")
PRODUCT_CODES = frozenset(PRODUCT_ORDER)


@dataclass(frozen=True)
class ValidationIssue:
    file: str
    json_path: str
    message: str
    category: str

    def render(self) -> str:
        return f"{self.file}:{self.json_path}: [{self.category}] {self.message}"


@dataclass(frozen=True)
class ValidationResult:
    files_checked: int
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def format_errors(self) -> str:
        return "\n".join(issue.render() for issue in self.issues)


def validate_json_project(
    paths: Sequence[Path] | None = None,
    *,
    root: Path = ROOT,
) -> ValidationResult:
    """Validate controlled project JSON with schemas and semantic invariants.

    With no explicit paths, only committed-style static inputs under ``data/`` and
    ``schema/`` are considered. Local environments and crawler working data are not
    scanned. Explicit files/directories are supported for focused validation.
    """

    Draft202012Validator, FormatChecker, SchemaError = _jsonschema_api()
    root = root.resolve()
    selected_paths, selection_issues = _selected_json_paths(root, paths)
    selected_labels = {_path_label(path, root) for path in selected_paths}
    issues: list[ValidationIssue] = list(selection_issues)
    payloads: dict[str, Any] = {}

    for path in selected_paths:
        label = _path_label(path, root)
        payload = _read_json(path, label, issues)
        if payload is not _INVALID:
            payloads[label] = payload

    schemas: dict[str, Any] = {}
    for schema_kind, filename in SCHEMA_FILES.items():
        schema_path = root / "schema" / filename
        label = _path_label(schema_path, root)
        payload = payloads.get(label, _MISSING)
        if payload is _MISSING:
            payload = _read_json(schema_path, label, issues)
        if payload is _INVALID:
            continue
        try:
            Draft202012Validator.check_schema(payload)
        except SchemaError as exc:
            issues.append(
                ValidationIssue(
                    file=label,
                    json_path=_json_pointer(getattr(exc, "absolute_path", ())),
                    message=str(getattr(exc, "message", exc)),
                    category="schema-definition",
                )
            )
            continue
        schemas[schema_kind] = payload

    known_schema_labels = {
        f"schema/{filename}" for filename in SCHEMA_FILES.values()
    }
    for label, payload in payloads.items():
        if label.startswith("schema/"):
            if label not in known_schema_labels:
                issues.append(
                    ValidationIssue(
                        file=label,
                        json_path="/",
                        message="no validator mapping for this controlled JSON Schema file",
                        category="schema-mapping",
                    )
                )
            continue
        schema_kind = _schema_kind_for_path(label)
        if schema_kind is None:
            issues.append(
                ValidationIssue(
                    file=label,
                    json_path="/",
                    message="no JSON Schema mapping for this controlled JSON file",
                    category="schema-mapping",
                )
            )
            continue
        schema = schemas.get(schema_kind)
        if schema is None:
            continue
        validator = Draft202012Validator(
            schema,
            format_checker=_format_checker(FormatChecker),
        )
        errors = sorted(
            validator.iter_errors(payload),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                error.message,
            ),
        )
        for error in errors:
            issues.append(
                ValidationIssue(
                    file=label,
                    json_path=_json_pointer(error.absolute_path),
                    message=error.message,
                    category="schema",
                )
            )

    context_payloads = dict(payloads)
    for path in _default_json_paths(root):
        label = _path_label(path, root)
        if label in context_payloads:
            continue
        try:
            context_payloads[label] = _strict_json_loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            # A focused validation should not report unrelated context failures.
            # Default validation already parsed every controlled file above.
            continue

    _validate_semantics(
        context_payloads,
        issues,
        report_files=selected_labels,
    )
    issues.sort(key=lambda issue: (issue.file, issue.json_path, issue.category, issue.message))
    return ValidationResult(files_checked=len(selected_paths), issues=tuple(issues))


def _jsonschema_api():
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError
    except ImportError as exc:
        raise RuntimeError(
            "JSON Schema validation requires jsonschema>=4.23,<5; "
            "install the project validation dependency"
        ) from exc
    return Draft202012Validator, FormatChecker, SchemaError


def _format_checker(format_checker_type):
    """Return a checker that works even without jsonschema's optional extras."""

    checker = format_checker_type()
    if "date-time" not in checker.checkers:
        checker.checks("date-time")(_is_rfc3339_datetime)
    checker.checks("http-uri")(_is_http_uri)
    return checker


def _is_rfc3339_datetime(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})",
        value,
    ):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _is_http_uri(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or any(character.isspace() or ord(character) < 32 for character in value)
        or "\\" in value
    ):
        return False
    try:
        parsed = urlsplit(value)
        # Accessing these properties performs bracket and port validation.
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if not parsed.netloc or not hostname:
        return False
    return parsed.username is None and parsed.password is None


def _default_json_paths(root: Path) -> list[Path]:
    schema_root = (root / "schema").resolve()
    paths = [
        path.resolve()
        for path in root.joinpath("schema").glob("*.schema.json")
        if _is_relative_to(path.resolve(), schema_root)
    ]
    data_root = root / "data"
    if data_root.exists():
        resolved_data_root = data_root.resolve()
        paths.extend(
            path.resolve()
            for path in data_root.rglob("*.json")
            if _is_relative_to(path.resolve(), resolved_data_root)
        )
    return sorted(set(paths), key=lambda path: _path_label(path, root))


def _selected_json_paths(
    root: Path,
    paths: Sequence[Path] | None,
) -> tuple[list[Path], list[ValidationIssue]]:
    if not paths:
        return _default_json_paths(root), []

    selected: set[Path] = set()
    issues: list[ValidationIssue] = []
    controlled_roots = (root / "data", root / "schema")
    for raw_path in paths:
        path = raw_path if raw_path.is_absolute() else root / raw_path
        path = path.resolve()
        if path == root:
            selected.update(_default_json_paths(root))
            continue
        if not any(_is_relative_to(path, controlled_root) for controlled_root in controlled_roots):
            issues.append(
                ValidationIssue(
                    file=_path_label(path, root),
                    json_path="/",
                    message="path is outside controlled data/ and schema/ roots",
                    category="selection",
                )
            )
            continue
        if path.is_dir():
            matches: set[Path] = set()
            for item in path.rglob("*.json"):
                resolved_item = item.resolve()
                if any(
                    _is_relative_to(resolved_item, controlled_root)
                    for controlled_root in controlled_roots
                ):
                    matches.add(resolved_item)
                else:
                    issues.append(
                        ValidationIssue(
                            file=_path_label(resolved_item, root),
                            json_path="/",
                            message="resolved JSON path escapes controlled roots",
                            category="selection",
                        )
                    )
            if not matches:
                issues.append(
                    ValidationIssue(
                        file=_path_label(path, root),
                        json_path="/",
                        message="directory contains no controlled JSON files",
                        category="selection",
                    )
                )
            selected.update(matches)
            continue
        if path.suffix.lower() != ".json":
            issues.append(
                ValidationIssue(
                    file=_path_label(path, root),
                    json_path="/",
                    message="selected path must be a JSON file or directory",
                    category="selection",
                )
            )
            continue
        selected.add(path)
    return (
        sorted(selected, key=lambda path: _path_label(path, root)),
        issues,
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
    except ValueError:
        return False
    return True


_INVALID = object()
_MISSING = object()


def _read_json(path: Path, label: str, issues: list[ValidationIssue]) -> Any:
    if not path.exists():
        issues.append(
            ValidationIssue(
                file=label,
                json_path="/",
                message="file does not exist",
                category="io",
            )
        )
        return _INVALID
    if not path.is_file():
        issues.append(
            ValidationIssue(
                file=label,
                json_path="/",
                message="path is not a file",
                category="io",
            )
        )
        return _INVALID
    try:
        return _strict_json_loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(
            ValidationIssue(
                file=label,
                json_path="/",
                message=f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
                category="syntax",
            )
        )
    except ValueError as exc:
        issues.append(
            ValidationIssue(
                file=label,
                json_path="/",
                message=f"invalid JSON: {exc}",
                category="syntax",
            )
        )
    except (OSError, UnicodeError) as exc:
        issues.append(
            ValidationIssue(
                file=label,
                json_path="/",
                message=str(exc),
                category="io",
            )
        )
    return _INVALID


def _strict_json_loads(raw: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard numeric constant {value!r}")

    return json.loads(raw, parse_constant=reject_constant)


def _schema_kind_for_path(relative_path: str) -> str | None:
    if relative_path == "data/calendar/latest.json":
        return "calendar_latest"
    if CALENDAR_PATH_RE.fullmatch(relative_path):
        return "calendar"
    if relative_path == "data/prices/latest.json":
        return "price_latest"
    if PRICE_SUMMARY_PATH_RE.fullmatch(relative_path):
        return "price_summary"
    if PRICE_PATH_RE.fullmatch(relative_path):
        return "prices"
    if relative_path == "data/regions/regions.json":
        return "region_index"
    if REGION_ZONE_PATH_RE.fullmatch(relative_path):
        return "region_zones"
    if relative_path == "data/sources/provinces.json":
        return "source_sites"
    return None


def _validate_semantics(
    payloads: dict[str, Any],
    issues: list[ValidationIssue],
    *,
    report_files: set[str],
) -> None:
    def report(
        file: str,
        json_path: str,
        message: str,
        *,
        related_files: Iterable[str] = (),
    ) -> None:
        if file not in report_files and report_files.isdisjoint(related_files):
            return
        issues.append(
            ValidationIssue(
                file=file,
                json_path=json_path,
                message=message,
                category="semantic",
            )
        )

    registry_codes = _validate_source_registry(payloads, report)
    declared_zones = _validate_region_data(payloads, registry_codes, report)
    calendars = _validate_calendars(payloads, report)
    _validate_prices(
        payloads,
        registry_codes,
        declared_zones,
        calendars,
        report,
    )


def _validate_source_registry(payloads: dict[str, Any], report) -> set[str]:
    file = "data/sources/provinces.json"
    payload = payloads.get(file)
    if not isinstance(payload, dict) or not isinstance(payload.get("provinces"), list):
        return set()

    seen_codes: dict[str, int] = {}
    codes: set[str] = set()
    for index, province in enumerate(payload["provinces"]):
        if not isinstance(province, dict):
            continue
        code = province.get("province_code")
        if not isinstance(code, str):
            continue
        if code in seen_codes:
            report(
                file,
                f"/provinces/{index}/province_code",
                f"duplicate province_code {code!r}; first declared at /provinces/{seen_codes[code]}",
            )
        else:
            seen_codes[code] = index
        codes.add(code)
    return codes


def _validate_region_data(
    payloads: dict[str, Any],
    registry_codes: set[str],
    report,
) -> dict[str, dict[str, str]]:
    declared_zones: dict[str, dict[str, str]] = {}
    declared_zone_locations: dict[tuple[str, str], tuple[str, int]] = {}
    province_files: dict[str, str] = {}

    for file, payload in sorted(payloads.items()):
        match = REGION_ZONE_PATH_RE.fullmatch(file)
        if not match or file == "data/regions/regions.json" or not isinstance(payload, dict):
            continue
        province_code = payload.get("province_code")
        zones = payload.get("zones")
        if not isinstance(province_code, str) or not isinstance(zones, list):
            continue
        if registry_codes and province_code not in registry_codes:
            report(file, "/province_code", f"unknown province_code {province_code!r}")
        if province_code in province_files:
            report(
                file,
                "/province_code",
                f"province_code {province_code!r} is also declared by {province_files[province_code]}",
            )
        else:
            province_files[province_code] = file

        zone_names: dict[str, str] = {}
        first_zone_index: dict[str, int] = {}
        for zone_index, zone in enumerate(zones):
            if not isinstance(zone, dict) or not isinstance(zone.get("zone_code"), str):
                continue
            zone_code = zone["zone_code"]
            if zone_code in first_zone_index:
                report(
                    file,
                    f"/zones/{zone_index}/zone_code",
                    f"duplicate zone_code {zone_code!r}; first declared at /zones/{first_zone_index[zone_code]}",
                )
            else:
                first_zone_index[zone_code] = zone_index
                zone_name = zone.get("zone_name")
                zone_names[zone_code] = zone_name if isinstance(zone_name, str) else ""
                declared_zone_locations[(province_code, zone_code)] = (file, zone_index)
        declared_zones[province_code] = zone_names

    index_file = "data/regions/regions.json"
    region_index = payloads.get(index_file)
    if isinstance(region_index, dict) and isinstance(region_index.get("items"), list):
        items = region_index["items"]
        if type(region_index.get("count")) is int and region_index["count"] != len(items):
            report(
                index_file,
                "/count",
                f"count should equal len(items) ({len(items)})",
            )
        indexed_zones: set[tuple[str, str]] = set()
        seen_region_keys: dict[str, tuple[int, tuple[object, object]]] = {}
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            region = item.get("region")
            province_code = item.get("province_code")
            zone_code = item.get("zone_code")
            if isinstance(region, str):
                target = (province_code, zone_code)
                first = seen_region_keys.get(region)
                if first is None:
                    seen_region_keys[region] = (item_index, target)
                else:
                    first_index, first_target = first
                    if target == first_target:
                        message = (
                            f"duplicate region lookup key {region!r}; first declared at "
                            f"/items/{first_index}/region"
                        )
                    else:
                        message = (
                            f"conflicting region lookup key {region!r}: maps to {target!r}, "
                            f"but first maps to {first_target!r} at "
                            f"/items/{first_index}/region"
                        )
                    report(index_file, f"/items/{item_index}/region", message)
            if isinstance(province_code, str) and registry_codes and province_code not in registry_codes:
                report(
                    index_file,
                    f"/items/{item_index}/province_code",
                    f"unknown province_code {province_code!r}",
                )
            if isinstance(province_code, str) and isinstance(zone_code, str):
                indexed_zones.add((province_code, zone_code))
            if (
                isinstance(province_code, str)
                and isinstance(zone_code, str)
                and zone_code != "default"
                and zone_code not in declared_zones.get(province_code, {})
            ):
                report(
                    index_file,
                    f"/items/{item_index}/zone_code",
                    f"zone_code {zone_code!r} is not declared by a province region file",
                )

        for key, (detail_file, zone_index) in sorted(declared_zone_locations.items()):
            if key in indexed_zones:
                continue
            province_code, zone_code = key
            report(
                detail_file,
                f"/zones/{zone_index}/zone_code",
                f"zone_code {zone_code!r} for province {province_code!r} "
                "is not referenced by data/regions/regions.json",
            )
    return declared_zones


def _validate_calendars(payloads: dict[str, Any], report) -> dict[int, set[str]]:
    calendars: dict[int, set[str]] = {}
    for file, payload in sorted(payloads.items()):
        match = CALENDAR_PATH_RE.fullmatch(file)
        if not match or not isinstance(payload, dict):
            continue
        path_year = int(match.group("year"))
        payload_year = payload.get("year")
        if payload_year != path_year:
            report(file, "/year", f"year {payload_year!r} does not match path year {path_year}")

        adjustment_dates = payload.get("adjustment_dates")
        if not isinstance(adjustment_dates, list):
            continue
        dates: set[str] = set()
        first_date_index: dict[str, int] = {}
        for item_index, item in enumerate(adjustment_dates):
            if not isinstance(item, dict) or not isinstance(item.get("date"), str):
                continue
            adjustment_date = item["date"]
            if adjustment_date in first_date_index:
                report(
                    file,
                    f"/adjustment_dates/{item_index}/date",
                    f"duplicate adjustment date {adjustment_date!r}; first declared at "
                    f"/adjustment_dates/{first_date_index[adjustment_date]}",
                )
            else:
                first_date_index[adjustment_date] = item_index
            dates.add(adjustment_date)
            expected_round = item_index + 1
            if item.get("round") != expected_round:
                report(
                    file,
                    f"/adjustment_dates/{item_index}/round",
                    f"round {item.get('round')!r} should be {expected_round}",
                )
        calendars[path_year] = dates

    latest_file = "data/calendar/latest.json"
    latest = payloads.get(latest_file)
    if isinstance(latest, dict):
        raw_path = latest.get("path")
        if isinstance(raw_path, str):
            target_file = raw_path.lstrip("/")
            target = payloads.get(target_file)
            if not isinstance(target, dict):
                report(latest_file, "/path", f"calendar target {raw_path!r} does not exist")
            elif latest.get("year") != target.get("year"):
                report(
                    latest_file,
                    "/year",
                    "latest calendar year does not match the target calendar",
                )
    return calendars


def _validate_prices(
    payloads: dict[str, Any],
    registry_codes: set[str],
    declared_zones: dict[str, dict[str, str]],
    calendars: dict[int, set[str]],
    report,
) -> None:
    snapshot_files: dict[str, dict[str, Any]] = {}
    summary_files: dict[str, dict[str, Any]] = {}
    for file, payload in payloads.items():
        if PRICE_PATH_RE.fullmatch(file) and isinstance(payload, dict):
            snapshot_files[file] = payload
        elif PRICE_SUMMARY_PATH_RE.fullmatch(file) and isinstance(payload, dict):
            summary_files[file] = payload

    for file, snapshot in sorted(snapshot_files.items()):
        match = PRICE_PATH_RE.fullmatch(file)
        assert match is not None
        path_year = match.group("year")
        path_date = match.group("date")
        adjustment_date = snapshot.get("adjustment_date")
        if adjustment_date != path_date:
            report(
                file,
                "/adjustment_date",
                f"adjustment_date {adjustment_date!r} does not match path date {path_date!r}",
            )
        if path_date[:4] != path_year:
            report(file, "/", f"snapshot filename year does not match directory {path_year}")
        if isinstance(adjustment_date, str):
            try:
                expected_effective = (
                    date.fromisoformat(adjustment_date) + timedelta(days=1)
                ).isoformat() + "T00:00:00+08:00"
            except ValueError:
                pass
            else:
                if snapshot.get("effective_from") != expected_effective:
                    report(
                        file,
                        "/effective_from",
                        f"effective_from should be {expected_effective!r}",
                    )
            calendar_dates = calendars.get(int(path_year))
            if calendar_dates is not None and adjustment_date not in calendar_dates:
                report(
                    file,
                    "/adjustment_date",
                    f"adjustment_date {adjustment_date!r} is absent from the {path_year} calendar",
                )

        provinces = snapshot.get("provinces")
        province_codes: set[str] = set()
        snapshot_item_codes: set[str] = set()
        first_province_index: dict[str, int] = {}
        if isinstance(provinces, list):
            for province_index, province in enumerate(provinces):
                if not isinstance(province, dict):
                    continue
                province_code = province.get("province_code")
                if not isinstance(province_code, str):
                    continue
                if province_code in first_province_index:
                    report(
                        file,
                        f"/provinces/{province_index}/province_code",
                        f"duplicate province_code {province_code!r}; first declared at "
                        f"/provinces/{first_province_index[province_code]}",
                    )
                else:
                    first_province_index[province_code] = province_index
                province_codes.add(province_code)
                if registry_codes and province_code not in registry_codes:
                    report(
                        file,
                        f"/provinces/{province_index}/province_code",
                        f"unknown province_code {province_code!r}",
                    )

                zones = province.get("zones")
                if not isinstance(zones, list):
                    continue
                declared_province_zones = declared_zones.get(province_code)
                first_zone_index: dict[str, int] = {}
                for zone_index, zone in enumerate(zones):
                    if not isinstance(zone, dict) or not isinstance(zone.get("zone_code"), str):
                        continue
                    zone_code = zone["zone_code"]
                    if zone_code in first_zone_index:
                        report(
                            file,
                            f"/provinces/{province_index}/zones/{zone_index}/zone_code",
                            f"duplicate zone_code {zone_code!r}; first declared at "
                            f"/provinces/{province_index}/zones/{first_zone_index[zone_code]}",
                        )
                    else:
                        first_zone_index[zone_code] = zone_index
                    if (
                        zone_code != "default"
                        and (
                            declared_province_zones is None
                            or zone_code not in declared_province_zones
                        )
                    ):
                        report(
                            file,
                            f"/provinces/{province_index}/zones/{zone_index}/zone_code",
                            f"zone_code {zone_code!r} is not declared by a province region file",
                        )
                    if (
                        declared_province_zones is not None
                        and zone_code in declared_province_zones
                        and zone.get("zone_name") != declared_province_zones[zone_code]
                    ):
                        report(
                            file,
                            f"/provinces/{province_index}/zones/{zone_index}/zone_name",
                            f"zone_name should be {declared_province_zones[zone_code]!r} "
                            f"for zone_code {zone_code!r}",
                        )

                    items = zone.get("items")
                    missing_products = zone.get("missing_products")
                    if not isinstance(items, dict):
                        continue
                    item_codes = set(items)
                    snapshot_item_codes.update(item_codes)
                    if not isinstance(missing_products, list):
                        report(
                            file,
                            f"/provinces/{province_index}/zones/{zone_index}/missing_products",
                            "missing_products must list every product absent from items",
                        )
                        continue
                    missing_codes = {
                        product for product in missing_products if isinstance(product, str)
                    }
                    overlap = sorted(item_codes & missing_codes)
                    if overlap:
                        report(
                            file,
                            f"/provinces/{province_index}/zones/{zone_index}/missing_products",
                            f"items and missing_products overlap: {overlap!r}",
                        )
                    covered_codes = item_codes | missing_codes
                    if covered_codes != PRODUCT_CODES:
                        report(
                            file,
                            f"/provinces/{province_index}/zones/{zone_index}/missing_products",
                            "items and missing_products must cover exactly "
                            f"{sorted(PRODUCT_CODES)!r}; got {sorted(covered_codes)!r}",
                        )

                if declared_province_zones is not None:
                    actual_zone_codes = set(first_zone_index)
                    expected_zone_codes = set(declared_province_zones)
                    if actual_zone_codes != expected_zone_codes:
                        report(
                            file,
                            f"/provinces/{province_index}/zones",
                            "zone_code set must exactly match the province region file; "
                            f"missing={sorted(expected_zone_codes - actual_zone_codes)!r}, "
                            f"extra={sorted(actual_zone_codes - expected_zone_codes)!r}",
                        )

        products = snapshot.get("products")
        if isinstance(products, list):
            expected_products = [
                product for product in PRODUCT_ORDER if product in snapshot_item_codes
            ]
            if products != expected_products:
                report(
                    file,
                    "/products",
                    "products must equal the canonically ordered union of all zone item keys; "
                    f"expected={expected_products!r}, got={products!r}",
                )

        summary_file = f"data/prices/{path_year}/{path_date}.summary.json"
        summary = summary_files.get(summary_file)
        if summary is None:
            report(file, "/", f"paired summary file {summary_file!r} does not exist")
        else:
            _validate_summary_for_snapshot(
                summary_file,
                summary,
                file,
                path_date,
                province_codes,
                registry_codes,
                report,
            )

    for summary_file in sorted(summary_files):
        match = PRICE_SUMMARY_PATH_RE.fullmatch(summary_file)
        assert match is not None
        snapshot_file = (
            f"data/prices/{match.group('year')}/{match.group('date')}.json"
        )
        if snapshot_file not in snapshot_files:
            report(summary_file, "/price_file", f"paired snapshot {snapshot_file!r} does not exist")

    _validate_price_latest(payloads, snapshot_files, summary_files, report)


def _validate_summary_for_snapshot(
    summary_file: str,
    summary: dict[str, Any],
    snapshot_file: str,
    path_date: str,
    province_codes: set[str],
    registry_codes: set[str],
    report,
) -> None:
    def report_summary(json_path: str, message: str) -> None:
        report(
            summary_file,
            json_path,
            message,
            related_files=(snapshot_file,),
        )

    expected_price_file = "/" + snapshot_file
    if summary.get("adjustment_date") != path_date:
        report_summary(
            "/adjustment_date",
            f"adjustment_date should be {path_date!r}",
        )
    if summary.get("price_file") != expected_price_file:
        report_summary("/price_file", f"price_file should be {expected_price_file!r}")
    if summary.get("provinces_success") != len(province_codes):
        report_summary(
            "/provinces_success",
            f"provinces_success should be {len(province_codes)}",
        )
    if registry_codes:
        expected_missing = sorted(registry_codes - province_codes)
        expected_status = "complete" if not expected_missing else "partial"
        if summary.get("status") != expected_status:
            report_summary(
                "/status",
                f"status should be {expected_status!r} for provinces_missing={expected_missing!r}",
            )
        if summary.get("provinces_total") != len(registry_codes):
            report_summary(
                "/provinces_total",
                f"provinces_total should be {len(registry_codes)}",
            )
        if summary.get("provinces_missing") != expected_missing:
            report_summary(
                "/provinces_missing",
                f"provinces_missing should be {expected_missing!r}",
            )


def _validate_price_latest(
    payloads: dict[str, Any],
    snapshot_files: dict[str, dict[str, Any]],
    summary_files: dict[str, dict[str, Any]],
    report,
) -> None:
    file = "data/prices/latest.json"
    latest = payloads.get(file)
    if not isinstance(latest, dict):
        return

    raw_snapshot_path = latest.get("latest")
    raw_summary_path = latest.get("latest_summary")
    snapshot_file = (
        f"data/prices/{raw_snapshot_path}" if isinstance(raw_snapshot_path, str) else ""
    )
    summary_file = (
        f"data/prices/{raw_summary_path}" if isinstance(raw_summary_path, str) else ""
    )
    snapshot = snapshot_files.get(snapshot_file)
    summary = summary_files.get(summary_file)
    if snapshot is None:
        report(file, "/latest", f"snapshot target {raw_snapshot_path!r} does not exist")
    else:
        if latest.get("adjustment_date") != snapshot.get("adjustment_date"):
            report(file, "/adjustment_date", "adjustment_date does not match latest snapshot")
        if latest.get("updated_at") != snapshot.get("updated_at"):
            report(file, "/updated_at", "updated_at does not match latest snapshot")
    if summary is None:
        report(file, "/latest_summary", f"summary target {raw_summary_path!r} does not exist")
    elif latest.get("adjustment_date") != summary.get("adjustment_date"):
        report(file, "/latest_summary", "latest summary date does not match adjustment_date")
    elif latest.get("status") != summary.get("status"):
        report(file, "/status", "status does not match latest summary")

    if snapshot_files:
        newest_snapshot_file = max(
            snapshot_files,
            key=lambda item: PRICE_PATH_RE.fullmatch(item).group("date"),  # type: ignore[union-attr]
        )
        if snapshot_file and snapshot_file != newest_snapshot_file:
            report(
                file,
                "/latest",
                f"latest should point to newest snapshot {newest_snapshot_file!r}",
            )


def _path_label(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _json_pointer(parts: Iterable[object]) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"
