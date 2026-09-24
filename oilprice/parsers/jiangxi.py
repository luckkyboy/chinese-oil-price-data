from __future__ import annotations

import re

from oilprice.parsers.table import parse_table_notice
from oilprice.payloads import ParsedNoticePayload


PRODUCT_LINE_PATTERNS = {
    "89": re.compile(r"^\s*(?:国[A-Z0-9ⅥB]+)?\s*89\s*[#﹟号]?\s*.*汽油", re.IGNORECASE),
    "92": re.compile(r"^\s*(?:国[A-Z0-9ⅥB]+)?\s*92\s*[#﹟号]?\s*.*汽油", re.IGNORECASE),
    "95": re.compile(r"^\s*(?:国[A-Z0-9ⅥB]+)?\s*95\s*[#﹟号]?\s*.*汽油", re.IGNORECASE),
    "0": re.compile(r"^\s*(?:国[A-Z0-9ⅥB]+)?\s*0\s*[#﹟号]?\s*.*柴油", re.IGNORECASE),
}


def parse_notice(text: str) -> ParsedNoticePayload:
    return parse_table_notice(text, PRODUCT_LINE_PATTERNS, scan_lines=8)
