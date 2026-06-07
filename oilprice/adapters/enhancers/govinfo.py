from __future__ import annotations

import re
from urllib.parse import urlencode, urljoin, urlparse

from oilprice.adapters.generic import build_notice_id
from oilprice.crawl.browser_client import BrowserSession
from oilprice.models import NoticeRef
from oilprice.payloads import SourceConfig

from .common import extract_published_date, fetch_json


def discover_from_govinfo_channel_search(
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
    parsed = urlparse(list_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    website_code = str(source.get("website_code") or _website_code_from_path(parsed.path) or "")
    if not website_code:
        return []
    referer = list_url

    channel_id = str(source.get("channel_id") or "")
    if not channel_id:
        root_code = str(source.get("channel_root_code") or _channel_code_from_path(parsed.path) or "")
        if not root_code:
            return []
        channel_path = source.get("channel_path") or []
        if not isinstance(channel_path, list):
            return []
        channel_id = _resolve_channel_id(
            origin=origin,
            website_code=website_code,
            root_code=root_code,
            channel_path=[str(item) for item in channel_path],
            timeout=timeout,
            referer=referer,
            browser_session=browser_session,
        )
    if not channel_id:
        return []

    page_size = int(source.get("search_page_size", 30))
    page_limit = int(source.get("search_page_limit", 2))
    refs: list[NoticeRef] = []
    seen: set[str] = set()
    for page in range(1, page_limit + 1):
        search_url = _search_url(origin=origin, channel_id=channel_id, page_size=page_size, page=page)
        payload = fetch_json(
            search_url,
            timeout=timeout,
            referer=referer,
            browser_session=browser_session,
        )
        for item in payload.get("data", {}).get("results", []):
            title = str(item.get("title") or "").strip()
            if not title or not any(keyword in title for keyword in keywords):
                continue
            source_url = urljoin(list_url, str(item.get("url") or ""))
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
                    published_at=extract_published_date(str(item.get("publishedTimeStr") or "")),
                )
            )
    return refs


def _resolve_channel_id(
    *,
    origin: str,
    website_code: str,
    root_code: str,
    channel_path: list[str],
    timeout: int,
    referer: str,
    browser_session: BrowserSession | None = None,
) -> str:
    current_code = root_code
    current_node = _fetch_channel_list(
        origin=origin,
        website_code=website_code,
        channel_code=current_code,
        timeout=timeout,
        referer=referer,
        browser_session=browser_session,
    )

    for segment in channel_path:
        children = current_node.get("results", {}).get("children", [])
        next_item = _match_child(children, segment)
        if not next_item:
            return ""
        current_code = str(next_item.get("channelCode") or "")
        if not current_code:
            return ""
        current_node = _fetch_channel_list(
            origin=origin,
            website_code=website_code,
            channel_code=current_code,
            timeout=timeout,
            referer=referer,
            browser_session=browser_session,
        )

    return str(current_node.get("results", {}).get("channelId") or "")


def _match_child(children: list[dict[str, object]], segment: str) -> dict[str, object] | None:
    expected = segment.strip()
    for child in children:
        if str(child.get("channelName") or "").strip() == expected:
            return child
    for child in children:
        name = str(child.get("channelName") or "").strip()
        if expected in name:
            return child
    return None


def _fetch_channel_list(
    *,
    origin: str,
    website_code: str,
    channel_code: str,
    timeout: int,
    referer: str,
    browser_session: BrowserSession | None = None,
) -> dict[str, object]:
    params = urlencode({"channelCode": channel_code, "websiteCodeName": website_code})
    return fetch_json(
        f"{origin}/common/getChannelList?{params}",
        timeout=timeout,
        referer=referer,
        browser_session=browser_session,
    )


def _search_url(*, origin: str, channel_id: str, page_size: int, page: int) -> str:
    params = urlencode(
        {
            "_isAgg": "true",
            "_isJson": "true",
            "_pageSize": str(page_size),
            "_template": "index",
            "_rangeTimeGte": "",
            "_channelName": "",
            "page": str(page),
        }
    )
    return f"{origin}/common/search/{channel_id}?{params}"


def _website_code_from_path(path: str) -> str | None:
    parts = [item for item in path.split("/") if item]
    if parts:
        return parts[0]
    return None


def _channel_code_from_path(path: str) -> str | None:
    match = re.search(r"/(c[0-9]{6})/", path)
    if match:
        return match.group(1)
    return None
