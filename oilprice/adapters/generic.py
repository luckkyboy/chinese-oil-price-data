from __future__ import annotations

from datetime import date
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

from oilprice.models import NoticeRef


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
ONCLICK_URL_RE = re.compile(r"""['"]((?:https?:)?//[^'"]+|[^'"]+\.html?)['"]""")
DATE_IN_CONTEXT_RE = re.compile(
    r"([12][0-9]{3})\s*(?:-|/|年)\s*([0-9]{1,2})\s*(?:-|/|月)\s*([0-9]{1,2})\s*日?"
)
MONTH_DAY_IN_CONTEXT_RE = re.compile(r"(?<![0-9])([0-9]{1,2})\s*(?:-|/|月)\s*([0-9]{1,2})(?:日)?(?![0-9])")
YEAR_MONTH_IN_PATH_RE = re.compile(r"/([12][0-9]{3})([01][0-9])(?:/|$)")
YEAR_IN_PATH_RE = re.compile(r"/([12][0-9]{3})(?:/|$)")
LI_BLOCK_RE = re.compile(r"<li\b[^>]*>(?P<body>.*?)</li>", flags=re.IGNORECASE | re.DOTALL)
LI_HREF_RE = re.compile(r"<a[^>]*href=[\"'](?P<href>[^\"']+)[\"']", flags=re.IGNORECASE | re.DOTALL)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href") or _url_from_onclick(attr_map.get("onclick"))
        if not href:
            return
        self._current_href = href
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        self.links.append((self._current_href, "".join(self._text_parts)))
        self._current_href = None
        self._text_parts = []


def strip_tags(value: str) -> str:
    text = TAG_RE.sub("", value)
    return SPACE_RE.sub(" ", unescape(text)).strip()


def _url_from_onclick(onclick: str | None) -> str | None:
    if not onclick:
        return None
    match = ONCLICK_URL_RE.search(onclick)
    return match.group(1) if match else None


def discover_from_html(
    html: str,
    list_url: str,
    province_code: str,
    province_name: str,
    province_slug: str,
    keywords: list[str],
) -> list[NoticeRef]:
    refs: list[NoticeRef] = []
    seen: set[str] = set()
    li_dates = _collect_link_dates_from_li(html, list_url)
    parser = LinkParser()
    parser.feed(html)
    list_parsed = urlparse(list_url)
    list_host = list_parsed.netloc.lower()
    list_scheme = list_parsed.scheme.lower()
    for href, raw_title in parser.links:
        title = strip_tags(raw_title)
        if not title or not any(keyword in title for keyword in keywords):
            continue
        source_url = _normalize_notice_url(urljoin(list_url, href), list_host, list_scheme)
        if _is_same_list_page(source_url, list_url):
            continue
        parsed_source_url = urlparse(source_url)
        if parsed_source_url.netloc.lower() != list_host:
            continue
        dedupe_key = _dedupe_key(source_url)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        published_at = li_dates.get(dedupe_key) or _published_date_from_link_context(html, href, list_url)
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


def build_notice_id(province_slug: str, source_url: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", source_url).strip("-").lower()
    if len(stem) > 80:
        stem = stem[-80:]
    return f"{province_slug}-{stem}"


def _normalize_notice_url(source_url: str, list_host: str, list_scheme: str) -> str:
    parsed = urlparse(source_url)
    if (
        parsed.netloc.lower() == list_host
        and parsed.scheme in {"http", "https"}
        and list_scheme in {"http", "https"}
        and parsed.scheme != list_scheme
    ):
        parsed = parsed._replace(scheme=list_scheme)
        return urlunparse(parsed)
    return source_url


def _dedupe_key(source_url: str) -> str:
    parsed = urlparse(source_url)
    return f"{parsed.netloc.lower()}{parsed.path}?{parsed.query}"


def _published_date_from_link_context(html: str, href: str, list_url: str) -> str | None:
    if not href:
        return None
    for marker in (href, href.replace("&amp;", "&")):
        if not marker:
            continue
        pos = html.find(marker)
        if pos < 0:
            continue
        left = max(0, pos - 100)
        right = min(len(html), pos + 180)
        context = html[left:right]
        year_hint = _infer_year_hint(href, list_url, context)
        published_at = _extract_date(context, year_hint=year_hint)
        if published_at:
            return published_at
    return None


def _collect_link_dates_from_li(html: str, list_url: str) -> dict[str, str]:
    dates: dict[str, str] = {}
    for block in LI_BLOCK_RE.finditer(html):
        body = block.group("body")
        href_match = LI_HREF_RE.search(body)
        if not href_match:
            continue
        raw_href = href_match.group("href")
        year_hint = _infer_year_hint(raw_href, list_url, body)
        published_at = _extract_date(body, year_hint=year_hint)
        if not published_at:
            continue
        source_url = urljoin(list_url, raw_href)
        dates[_dedupe_key(source_url)] = published_at
    return dates


def _extract_date(text: str, year_hint: int | None = None) -> str | None:
    compact = re.sub(r"\s+", "", text)
    match = DATE_IN_CONTEXT_RE.search(compact)
    if match:
        year, month, day = (int(value) for value in match.groups())
        return _safe_iso_date(year, month, day)

    match = MONTH_DAY_IN_CONTEXT_RE.search(compact)
    if not match:
        return None
    month, day_of_month = (int(value) for value in match.groups())
    if year_hint:
        iso_text = _safe_iso_date(year_hint, month, day_of_month)
        if iso_text:
            return iso_text
    return f"{month:02d}/{day_of_month:02d}"


def _infer_year_hint(raw_href: str, list_url: str, context: str) -> int | None:
    for value in (raw_href, list_url, context):
        year_match = YEAR_MONTH_IN_PATH_RE.search(value)
        if year_match:
            return int(year_match.group(1))

    for value in (raw_href, list_url, context):
        year_match = YEAR_IN_PATH_RE.search(value)
        if year_match:
            return int(year_match.group(1))

    return None


def _safe_iso_date(year: int, month: int, day_of_month: int) -> str | None:
    try:
        parsed = date(year, month, day_of_month)
    except ValueError:
        return None
    return parsed.isoformat()


def _is_same_list_page(source_url: str, list_url: str) -> bool:
    source = urlparse(source_url)
    list_page = urlparse(list_url)
    return (
        source.netloc.lower() == list_page.netloc.lower()
        and source.path.rstrip("/") == list_page.path.rstrip("/")
        and source.query == list_page.query
    )
