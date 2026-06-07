from __future__ import annotations

import re
from urllib.parse import urljoin

from oilprice.adapters.generic import LinkParser, build_notice_id, strip_tags
from oilprice.crawl.browser_client import BrowserSession
from oilprice.models import NoticeRef
from oilprice.payloads import SourceConfig

from .common import extract_published_date, fetch_text


def discover_from_jpage_xml(
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
            published_at = extract_published_date(record_html)
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
