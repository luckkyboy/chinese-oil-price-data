from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from oilprice.adapters.generic import build_notice_id, strip_tags
from oilprice.crawl.browser_client import BrowserSession
from oilprice.models import NoticeRef
from oilprice.payloads import SourceConfig

from .common import extract_published_date, fetch_text


def discover_from_embedded_article_list(
    *,
    source: SourceConfig,
    list_url: str,
    province_code: str,
    province_name: str,
    province_slug: str,
    keywords: list[str],
    timeout: int,
    browser_session: BrowserSession | None = None,
) -> list[NoticeRef]:
    referer = list_url
    html = fetch_text(
        list_url,
        timeout=timeout,
        referer=referer,
        browser_session=browser_session,
    )
    article_list = _extract_article_list_items(html)
    refs: list[NoticeRef] = []
    seen: set[str] = set()
    for item in article_list:
        title = strip_tags(str(item.get("title") or item.get("showTitle") or ""))
        if not title or not any(keyword in title for keyword in keywords):
            continue
        source_url = _article_pc_url(item, list_url)
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        refs.append(
            NoticeRef(
                notice_id=build_notice_id(province_slug, source_url),
                province_code=province_code,
                province_name=province_name,
                province_slug=province_slug,
                title=title,
                source_url=source_url,
                published_at=extract_published_date(str(item.get("pubDate") or "")),
            )
        )
    return refs


def _extract_article_list_items(html: str) -> list[dict[str, object]]:
    match = re.search(r"articleList\s*:\s*\[", html)
    if not match:
        return []
    start = match.end() - 1
    end = _find_matching_bracket(html, start)
    if end < 0:
        return []
    raw_array = html[start : end + 1]
    try:
        payload = json.loads(raw_array)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _find_matching_bracket(text: str, start_index: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == "\"":
                in_string = False
            continue
        if char == "\"":
            in_string = True
            continue
        if char == "[":
            depth += 1
            continue
        if char == "]":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _article_pc_url(item: dict[str, object], list_url: str) -> str:
    urls = item.get("urls")
    if isinstance(urls, dict):
        pc_path = urls.get("pc")
        if isinstance(pc_path, str) and pc_path:
            return urljoin(list_url, pc_path)
        return ""
    if not isinstance(urls, str):
        return ""
    urls_text = urls.strip()
    if not urls_text:
        return ""
    try:
        parsed = json.loads(urls_text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    pc_path = parsed.get("pc")
    if not isinstance(pc_path, str) or not pc_path:
        return ""
    return urljoin(list_url, pc_path)
