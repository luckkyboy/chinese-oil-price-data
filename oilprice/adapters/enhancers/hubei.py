from __future__ import annotations

from urllib.parse import urljoin

from oilprice.adapters.generic import build_notice_id, strip_tags
from oilprice.crawl.browser_client import BrowserSession
from oilprice.models import NoticeRef
from oilprice.payloads import SourceConfig

from .common import extract_published_date, fetch_json


def discover_from_hubei_qtgk_json(
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

    payload = fetch_json(
        list_url,
        timeout=timeout,
        referer=referer,
        browser_session=browser_session,
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
                published_at=extract_published_date(
                    str(item.get("PUBDATE") or item.get("DOCRELTIME") or "")
                ),
            )
        )
    return refs
