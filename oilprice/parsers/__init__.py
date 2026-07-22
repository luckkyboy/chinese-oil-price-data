from __future__ import annotations

import re
from collections.abc import Callable

from .anhui import parse_notice as parse_anhui_notice
from .beijing import parse_notice as parse_beijing_notice
from .fujian import parse_notice as parse_fujian_notice
from .guizhou import parse_notice as parse_guizhou_notice
from .guangxi import parse_notice as parse_guangxi_notice
from .generic import parse_notice as parse_generic_notice
from .hebei import parse_notice as parse_hebei_notice
from .heilongjiang import parse_notice as parse_heilongjiang_notice
from .henan import parse_notice as parse_henan_notice
from .jiangsu import parse_notice as parse_jiangsu_notice
from .jiangxi import parse_notice as parse_jiangxi_notice
from .liaoning import parse_notice as parse_liaoning_notice
from .neimenggu import parse_notice as parse_neimenggu_notice
from .ningxia import parse_notice as parse_ningxia_notice
from .qinghai import parse_notice as parse_qinghai_notice
from .shaanxi import parse_notice as parse_shaanxi_notice
from .shandong import parse_notice as parse_shandong_notice
from .shanxi import parse_notice as parse_shanxi_notice
from .sichuan import parse_notice as parse_sichuan_notice
from .xinjiang import parse_notice as parse_xinjiang_notice
from .xizang import parse_notice as parse_xizang_notice
from .yunnan import parse_notice as parse_yunnan_notice
from .zhejiang import parse_notice as parse_zhejiang_notice
from ..payloads import ParsedNoticePayload


PARSER_FUNCTIONS: dict[str, Callable[[str], ParsedNoticePayload]] = {
    "anhui": parse_anhui_notice,
    "beijing": parse_beijing_notice,
    "fujian": parse_fujian_notice,
    "generic": parse_generic_notice,
    "guangxi": parse_guangxi_notice,
    "guizhou": parse_guizhou_notice,
    "hebei": parse_hebei_notice,
    "heilongjiang": parse_heilongjiang_notice,
    "henan": parse_henan_notice,
    "jiangsu": parse_jiangsu_notice,
    "jiangxi": parse_jiangxi_notice,
    "liaoning": parse_liaoning_notice,
    "neimenggu": parse_neimenggu_notice,
    "ningxia": parse_ningxia_notice,
    "qinghai": parse_qinghai_notice,
    "shaanxi": parse_shaanxi_notice,
    "shandong": parse_shandong_notice,
    "shanxi": parse_shanxi_notice,
    "sichuan": parse_sichuan_notice,
    "xinjiang": parse_xinjiang_notice,
    "xizang": parse_xizang_notice,
    "yunnan": parse_yunnan_notice,
    "zhejiang": parse_zhejiang_notice,
}
PARSER_REVISIONS = {name: 1 for name in PARSER_FUNCTIONS}
PARSER_REVISIONS["shaanxi"] = 2
PARSER_REVISIONS["sichuan"] = 2


DATE_PATTERNS = [
    re.compile(r"自\s*([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日\s*24时起"),
    re.compile(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日\s*24时起执行"),
    re.compile(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日\s*起执行"),
    re.compile(r"发布日期]\s*([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})"),
    re.compile(r"发布时间[:：]\s*([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})"),
]


def parse_notice(adapter: str, text: str) -> ParsedNoticePayload:
    parser = PARSER_FUNCTIONS.get(adapter, parse_generic_notice)
    result = parser(text)

    if "adjustment_date" not in result:
        adjustment_date = extract_adjustment_date(text)
        if adjustment_date:
            result["adjustment_date"] = adjustment_date
    return result


def parser_version(adapter: str) -> str:
    """Return a provenance version for the parser that actually handles an adapter."""

    resolved_adapter = adapter if adapter in PARSER_FUNCTIONS else "generic"
    return f"{resolved_adapter}-v{PARSER_REVISIONS[resolved_adapter]}"


def extract_adjustment_date(text: str) -> str | None:
    compact_text = re.sub(r"\s+", "", text)
    for pattern in DATE_PATTERNS:
        match = pattern.search(compact_text)
        if not match:
            continue
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return None
