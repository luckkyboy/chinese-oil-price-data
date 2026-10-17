from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


NEWS_RELEASE_URL = "https://www.ndrc.gov.cn/xwdt/xwfb/"
_ARTICLE_DATE = re.compile(r"/t(\d{4})(\d{2})(\d{2})_\d+\.html$")
_TITLE_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_PAGE_COUNT = re.compile(r"createPageHTML\(\s*(\d+)")


@dataclass(frozen=True)
class NdrcNotice:
    title: str
    url: str

    @property
    def no_change(self) -> bool:
        return "不作调整" in self.title


class _NewsLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._title = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attributes = dict(attrs)
            self._href = attributes.get("href")
            self._title = attributes.get("title") or ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            title = re.sub(r"\s+", "", self._title or "".join(self._text))
            self.links.append((self._href, title))
            self._href = None


def find_ndrc_notice(target_date: date) -> NdrcNotice | None:
    """Find this window's price announcement in the official news release list.

    Follow the list's static pagination for older manual dispatches. A missing
    notice is pending, never evidence that prices remain unchanged. HTTP and
    parsing errors propagate so the workflow cannot start an unverified fetch.
    """
    page_count = 1
    for page in range(40):
        if page >= page_count:
            break
        page_url = NEWS_RELEASE_URL if page == 0 else urljoin(
            NEWS_RELEASE_URL, f"index_{page}.html"
        )
        request = Request(page_url, headers={"User-Agent": "oilprice-calendar/1.0"})
        with urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8-sig")
        if page == 0:
            count = _PAGE_COUNT.search(html)
            if count:
                page_count = int(count.group(1))
        parser = _NewsLinks()
        parser.feed(html)
        publication_dates: list[date] = []
        matches: dict[str, NdrcNotice] = {}
        for href, title in parser.links:
            url = urljoin(page_url, href)
            parts = urlsplit(url)
            if parts.hostname != "www.ndrc.gov.cn" or not parts.path.startswith("/xwdt/xwfb/"):
                continue
            published = _ARTICLE_DATE.search(parts.path)
            if published is None:
                continue
            published_date = date(*(int(value) for value in published.groups()))
            publication_dates.append(published_date)
            if published_date != target_date or not re.search(r"成品油.*价格", title):
                continue
            title_date = _TITLE_DATE.search(title)
            if title_date and date(*(int(value) for value in title_date.groups())) != target_date:
                continue
            if not any(word in title for word in ("调整", "调控", "上调", "下调")):
                continue
            matches[url] = NdrcNotice(title=title, url=url)
        if matches:
            if len({notice.no_change for notice in matches.values()}) > 1:
                raise ValueError(f"conflicting NDRC price announcements for {target_date}")
            return next(iter(matches.values()))
        if publication_dates and min(publication_dates) <= target_date:
            break
    return None
