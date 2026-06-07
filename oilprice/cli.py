from __future__ import annotations

import argparse
import logging

from .discovery_pipeline import command_discover
from .fetch_pipeline import command_fetch
from .pipeline import (
    command_extract,
    command_lookup_price,
    command_validate_json,
)
from .prices import command_build_prices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Chinese oil price data CLI.\n\n"
            "Typical flow for one adjustment date:\n"
            "  1) discover -> find official notice links\n"
            "  2) fetch    -> download raw notice pages and attachments\n"
            "  3) extract  -> parse structured price info from raw files\n"
            "  4) price    -> build / merge data/prices/{year}/{date}.json + summary\n\n"
            "Run `extract` to execute the full per-province flow in one shared browser session."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser(
        "discover",
        help="Discover notice URLs from source registry.",
        description=(
            "Discover official notice links for a target date and write index JSON.\n\n"
            "Output defaults to:\n"
            "  tmp/notices/{date}/index.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    discover.add_argument(
        "--sources",
        default="data/sources/provinces.json",
        help="Path to source registry JSON. Default: %(default)s",
    )
    discover.add_argument(
        "date",
        help="Adjustment date (YYYY-MM-DD). Used for filtering and default index path.",
    )
    discover.add_argument(
        "--output",
        help="Custom index output path (overrides default tmp/notices/{date}/index.json).",
    )
    add_timeout_arg(discover)
    discover.add_argument(
        "--force",
        action="store_true",
        help="Ignore summary incremental skip and force discover for configured sources.",
    )
    add_province_filter(discover)
    discover.set_defaults(func=command_discover)

    fetch = subparsers.add_parser(
        "fetch",
        help="Fetch raw notice pages/attachments from index.",
        description=(
            "Read discovered notices from index.json and download raw HTML/files.\n\n"
            "Input index defaults to:\n"
            "  tmp/notices/{date}/index.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    fetch.add_argument(
        "date",
        help="Adjustment date (YYYY-MM-DD). Used to resolve default index path.",
    )
    add_index_arg(fetch, derived_from="--date")
    add_timeout_arg(fetch)
    fetch.add_argument(
        "--force",
        action="store_true",
        help="Ignore summary incremental skip and re-fetch all.",
    )
    add_province_filter(fetch)
    fetch.set_defaults(func=command_fetch)

    extract = subparsers.add_parser(
        "extract",
        help="Run discover/fetch/extract/price per province with CloakBrowser.",
        description=(
            "Run the full per-province action with one shared CloakBrowser session.\n"
            "For each province: discover -> fetch -> extract -> price.\n\n"
            "Input index defaults to:\n"
            "  tmp/notices/{date}/index.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    extract.add_argument(
        "--sources",
        default="data/sources/provinces.json",
        help="Path to source registry JSON. Default: %(default)s",
    )
    extract.add_argument(
        "date",
        help="Adjustment date (YYYY-MM-DD). Used to resolve default index path.",
    )
    add_index_arg(extract, derived_from="--date")
    extract.add_argument(
        "--force",
        action="store_true",
        help="Ignore summary incremental skip and run all selected provinces.",
    )
    add_timeout_arg(extract, help_text="Browser timeout in seconds for discover/fetch. Default: %(default)s")
    add_province_filter(extract)
    extract.set_defaults(func=command_extract)

    build_prices_cmd = subparsers.add_parser(
        "price",
        help="Build/merge data/prices snapshot and summary.",
        description=(
            "Build price snapshot for one date from extracted notices.\n"
            "If target data/prices/{year}/{date}.json exists, merge new provinces into it.\n"
            "Also updates:\n"
            "  - data/prices/{year}/{date}.summary.json\n"
            "  - data/prices/latest.json"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    build_prices_cmd.add_argument("adjustment_date", help="Adjustment date (YYYY-MM-DD).")
    add_index_arg(build_prices_cmd, derived_from="adjustment_date")
    add_province_filter(build_prices_cmd)
    build_prices_cmd.set_defaults(func=command_build_prices)

    validate = subparsers.add_parser(
        "validate-json",
        help="Validate JSON syntax.",
        description=(
            "Validate JSON syntax for selected files.\n"
            "If no path is provided, scan all *.json under repository."
        ),
    )
    validate.add_argument("paths", nargs="*", help="Optional JSON file paths.")
    validate.set_defaults(func=command_validate_json)

    lookup = subparsers.add_parser(
        "lookup-price",
        help="Lookup price by area/province/date.",
        description="Resolve an area to zone and query the matching price snapshot.",
    )
    lookup.add_argument("area", help="Area/city/county name.")
    lookup.add_argument("--province", default="sichuan", help="Province slug. Default: %(default)s")
    lookup.add_argument("--parent", help="Optional parent region name for disambiguation.")
    lookup.add_argument(
        "--adjustment-date",
        default="2026-04-21",
        help="Adjustment date (YYYY-MM-DD). Default: %(default)s",
    )
    lookup.add_argument(
        "--product",
        choices=["89", "92", "95", "0"],
        help="Optional product code filter.",
    )
    lookup.set_defaults(func=command_lookup_price)

    return parser


def add_index_arg(parser: argparse.ArgumentParser, *, derived_from: str) -> None:
    parser.add_argument(
        "--index",
        help=f"Explicit index path. If omitted, derive from {derived_from}.",
    )


def add_province_filter(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--province-code",
        "--provinceCode",
        dest="province_code",
        help="Optional province code filter, e.g. 620000. Comma-separated values are allowed.",
    )


def add_timeout_arg(
    parser: argparse.ArgumentParser,
    *,
    help_text: str = "Browser timeout in seconds. Default: %(default)s",
) -> None:
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help=help_text,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
