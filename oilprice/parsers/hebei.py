from __future__ import annotations

import re

from oilprice.parsers.table import parse_table_notice
from oilprice.payloads import ParsedNoticePayload


PRODUCT_LINE_PATTERNS = {
    "89": re.compile(r"^\s*89(?![0-9.])\s*[#﹟号]?", re.IGNORECASE),
    "92": re.compile(r"^\s*92(?![0-9.])\s*[#﹟号]?", re.IGNORECASE),
    "95": re.compile(r"^\s*95(?![0-9.])\s*[#﹟号]?", re.IGNORECASE),
    "0": re.compile(r"^\s*0(?![0-9.])\s*[#﹟号]?", re.IGNORECASE),
}


def parse_notice(text: str) -> ParsedNoticePayload:
    return parse_table_notice(text, PRODUCT_LINE_PATTERNS, scan_lines=4)
