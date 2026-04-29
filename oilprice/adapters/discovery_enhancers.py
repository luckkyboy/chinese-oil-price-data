from __future__ import annotations

import json
import re
from urllib.parse import urlencode, urljoin, urlparse

from oilprice.adapters.generic import LinkParser, build_notice_id, strip_tags
from oilprice.crawl.http import build_discovery_headers, fetch_bytes_with_headers
from oilprice.models import NoticeRef


def discover_with_enhancer(
    enhancer: str,
    *,
    source: dict[str, object],
    list_url: str,
    province_code: str,
    province_name: str,
    province_slug: str,
    keywords: list[str],
    timeout: int,
) -> list[NoticeRef]:
    if enhancer == "govinfo_channel_search":
        return discover_from_govinfo_channel_search(
            source=source,
            list_url=list_url,
            province_code=province_code,
            province_name=province_name,
            province_slug=province_slug,
            keywords=keywords,
            timeout=timeout,
        )
    if enhancer == "jpage_xml":
        return discover_from_jpage_xml(
            source=source,
            list_url=list_url,
            province_code=province_code,
            province_name=province_name,
            province_slug=province_slug,
            keywords=keywords,
            timeout=timeout,
        )
    if enhancer == "embedded_article_list":
        return discover_from_embedded_article_list(
            source=source,
            list_url=list_url,
            province_code=province_code,
            province_name=province_name,
            province_slug=province_slug,
            keywords=keywords,
            timeout=timeout,
        )
    if enhancer == "hubei_qtgk_json":
        return discover_from_hubei_qtgk_json(
            source=source,
            list_url=list_url,
            province_code=province_code,
            province_name=province_name,
            province_slug=province_slug,
            keywords=keywords,
            timeout=timeout,
        )
    return []


def discover_from_govinfo_channel_search(
    *,
    source: dict[str, object],
    list_url: str,
    province_code: str,
    province_name: str,
    province_slug: str,
    keywords: list[str],
    timeout: int,
) -> list[NoticeRef]:
    parsed = urlparse(list_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    website_code = str(source.get("website_code") or _website_code_from_path(parsed.path) or "")
    if not website_code:
        return []
    headers = build_discovery_headers(
        str(source.get("base_url") or ""),
        list_url,
        str(source.get("cookie") or "") or None,
    )
    referer = headers["Referer"]
    host = headers.get("Host", "")
    if not host:
        host = urlparse(list_url).netloc

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
                user_agent=headers["User-Agent"],
                host=host,
            )
    if not channel_id:
        return []

    page_size = int(source.get("search_page_size", 30))
    page_limit = int(source.get("search_page_limit", 2))
    refs: list[NoticeRef] = []
    seen: set[str] = set()
    for page in range(1, page_limit + 1):
        search_url = _search_url(origin=origin, channel_id=channel_id, page_size=page_size, page=page)
        payload = _fetch_json(
            search_url,
            timeout=timeout,
            referer=referer,
            user_agent=headers["User-Agent"],
            host=host,
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
                    published_at=_extract_published_date(str(item.get("publishedTimeStr") or "")),
                )
            )
    return refs


def discover_from_jpage_xml(
    *,
    source: dict[str, object],
    list_url: str,
    province_code: str,
    province_name: str,
    province_slug: str,
    keywords: list[str],
    timeout: int,
) -> list[NoticeRef]:
    headers = build_discovery_headers(
        str(source.get("base_url") or ""),
        list_url,
        str(source.get("cookie") or "") or None,
    )
    referer = headers["Referer"]
    host = headers.get("Host", "")
    if not host:
        host = urlparse(list_url).netloc
    html = _fetch_text(
        list_url,
        timeout=timeout,
        referer=referer,
        user_agent=headers["User-Agent"],
        host=host,
    )

    refs: list[NoticeRef] = []
    seen: set[str] = set()
    for script_block in re.findall(
        r"<script[^>]*type=[\"']text/xml[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        for record_html in re.findall(
            r"<record>\s*<!\[CDATA\[(.*?)\]\]>\s*</record>",
            script_block,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            parser = LinkParser()
            parser.feed(record_html)
            published_at = _extract_published_date(record_html)
            for href, raw_title in parser.links:
                title = strip_tags(raw_title)
                if not title or not any(keyword in title for keyword in keywords):
                    continue
                source_url = urljoin(list_url, href)
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
                        published_at=published_at,
                    )
                )
    return refs


def discover_from_embedded_article_list(
    *,
    source: dict[str, object],
    list_url: str,
    province_code: str,
    province_name: str,
    province_slug: str,
    keywords: list[str],
    timeout: int,
) -> list[NoticeRef]:
    headers = build_discovery_headers(
        str(source.get("base_url") or ""),
        list_url,
        str(source.get("cookie") or "") or None,
    )
    referer = headers["Referer"]
    host = headers.get("Host", "")
    if not host:
        host = urlparse(list_url).netloc
    html = _fetch_text(
        list_url,
        timeout=timeout,
        referer=referer,
        user_agent=headers["User-Agent"],
        host=host,
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
                published_at=_extract_published_date(str(item.get("pubDate") or "")),
            )
        )
    return refs


def discover_from_hubei_qtgk_json(
    *,
    source: dict[str, object],
    list_url: str,
    province_code: str,
    province_name: str,
    province_slug: str,
    keywords: list[str],
    timeout: int,
) -> list[NoticeRef]:
    headers = build_discovery_headers(
        str(source.get("base_url") or ""),
        list_url,
        str(source.get("cookie") or "") or None,
    )
    referer = headers["Referer"]
    host = headers.get("Host", "")
    if not host:
        host = urlparse(list_url).netloc

    payload = _fetch_json(
        list_url,
        timeout=timeout,
        referer=referer,
        user_agent=headers["User-Agent"],
        host=host,
    )
    refs: list[NoticeRef] = []
    seen: set[str] = set()
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        title = strip_tags(str(item.get("FILENAME") or "")).strip()
        if not title or not any(keyword in title for keyword in keywords):
            continue
        raw_url = str(item.get("URL") or "").strip()
        if not raw_url:
            continue
        source_url = urljoin(list_url, raw_url)
        if source_url.startswith("http://"):
            source_url = "https://" + source_url[len("http://") :]
        if source_url in seen:
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
                published_at=_extract_published_date(
                    str(item.get("PUBDATE") or item.get("DOCRELTIME") or "")
                ),
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
    user_agent: str,
    host: str,
) -> str:
    current_code = root_code
    current_node = _fetch_channel_list(
        origin=origin,
        website_code=website_code,
        channel_code=current_code,
        timeout=timeout,
        referer=referer,
        user_agent=user_agent,
        host=host,
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
            user_agent=user_agent,
            host=host,
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
    user_agent: str,
    host: str,
) -> dict[str, object]:
    params = urlencode({"channelCode": channel_code, "websiteCodeName": website_code})
    return _fetch_json(
        f"{origin}/common/getChannelList?{params}",
        timeout=timeout,
        referer=referer,
        user_agent=user_agent,
        host=host,
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


def _fetch_json(
    url: str,
    *,
    timeout: int,
    referer: str,
    user_agent: str,
    host: str,
) -> dict[str, object]:
    headers = {"Referer": referer, "User-Agent": user_agent or DEFAULT_USER_AGENT}
    if host:
        headers["Host"] = host
    content, _ = fetch_bytes_with_headers(url, timeout=timeout, headers=headers)
    return json.loads(content.decode("utf-8", errors="replace"))


def _fetch_text(
    url: str,
    *,
    timeout: int,
    referer: str,
    user_agent: str,
    host: str,
) -> str:
    headers = {"Referer": referer, "User-Agent": user_agent or DEFAULT_USER_AGENT}
    if host:
        headers["Host"] = host
    content, _ = fetch_bytes_with_headers(url, timeout=timeout, headers=headers)
    return content.decode("utf-8", errors="replace")


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


def _extract_published_date(raw: str) -> str | None:
    match = re.search(r"([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})", raw)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _host_from_base_url(base_url: str) -> str:
    if not base_url:
        return ""
    return urlparse(base_url).netloc


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
