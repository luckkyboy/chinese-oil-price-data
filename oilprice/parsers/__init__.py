from __future__ import annotations

import re

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


DATE_PATTERNS = [
    re.compile(r"自\s*([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日\s*24时起"),
    re.compile(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日\s*24时起执行"),
    re.compile(r"([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日\s*起执行"),
    re.compile(r"发布日期]\s*([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})"),
    re.compile(r"发布时间[:：]\s*([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})"),
]


def parse_notice(adapter: str, text: str) -> dict[str, object]:
    if adapter == "anhui":
        result = parse_anhui_notice(text)
    elif adapter == "sichuan":
        result = parse_sichuan_notice(text)
    elif adapter == "beijing":
        result = parse_beijing_notice(text)
    elif adapter == "hebei":
        result = parse_hebei_notice(text)
    elif adapter == "heilongjiang":
        result = parse_heilongjiang_notice(text)
    elif adapter == "henan":
        result = parse_henan_notice(text)
    elif adapter == "fujian":
        result = parse_fujian_notice(text)
    elif adapter == "guizhou":
        result = parse_guizhou_notice(text)
    elif adapter == "guangxi":
        result = parse_guangxi_notice(text)
    elif adapter == "jiangsu":
        result = parse_jiangsu_notice(text)
    elif adapter == "jiangxi":
        result = parse_jiangxi_notice(text)
    elif adapter == "liaoning":
        result = parse_liaoning_notice(text)
    elif adapter == "neimenggu":
        result = parse_neimenggu_notice(text)
    elif adapter == "ningxia":
        result = parse_ningxia_notice(text)
    elif adapter == "qinghai":
        result = parse_qinghai_notice(text)
    elif adapter == "shaanxi":
        result = parse_shaanxi_notice(text)
    elif adapter == "shandong":
        result = parse_shandong_notice(text)
    elif adapter == "shanxi":
        result = parse_shanxi_notice(text)
    elif adapter == "xinjiang":
        result = parse_xinjiang_notice(text)
    elif adapter == "xizang":
        result = parse_xizang_notice(text)
    elif adapter == "yunnan":
        result = parse_yunnan_notice(text)
    elif adapter == "zhejiang":
        result = parse_zhejiang_notice(text)
    else:
        result = parse_generic_notice(text)

    if "adjustment_date" not in result:
        adjustment_date = extract_adjustment_date(text)
        if adjustment_date:
            result["adjustment_date"] = adjustment_date
    return result


def extract_adjustment_date(text: str) -> str | None:
    compact_text = re.sub(r"\s+", "", text)
    for pattern in DATE_PATTERNS:
        match = pattern.search(compact_text)
        if not match:
            continue
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return None
