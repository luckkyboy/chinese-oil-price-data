from __future__ import annotations

from collections.abc import Callable

from oilprice.adapters.enhancers.embedded_article_list import discover_from_embedded_article_list
from oilprice.adapters.enhancers.govinfo import discover_from_govinfo_channel_search
from oilprice.adapters.enhancers.hubei import discover_from_hubei_qtgk_json
from oilprice.adapters.enhancers.jpage import discover_from_jpage_xml
from oilprice.crawl.browser_client import BrowserSession
from oilprice.models import NoticeRef
from oilprice.payloads import SourceConfig


Enhancer = Callable[..., list[NoticeRef]]

ENHANCERS: dict[str, Enhancer] = {
    "govinfo_channel_search": discover_from_govinfo_channel_search,
    "jpage_xml": discover_from_jpage_xml,
    "embedded_article_list": discover_from_embedded_article_list,
    "hubei_qtgk_json": discover_from_hubei_qtgk_json,
}


def discover_with_enhancer(
    enhancer: str,
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
    handler = ENHANCERS.get(enhancer)
    if handler is None:
        return []
    return handler(
        source=source,
        list_url=list_url,
        province_code=province_code,
        province_name=province_name,
        province_slug=province_slug,
        keywords=keywords,
        timeout=timeout,
        browser_session=browser_session,
    )
