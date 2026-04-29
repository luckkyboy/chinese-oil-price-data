from __future__ import annotations

import re
from html import unescape
from urllib.parse import unquote, urljoin, urlparse


ATTACHMENT_EXTENSIONS = (".doc", ".docx", ".pdf", ".xls", ".xlsx")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
HREF_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
SRC_RE = re.compile(r"\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE | re.DOTALL)
DATA_SRC_RE = re.compile(r"\bdata-src=[\"']([^\"']+)[\"']", re.IGNORECASE | re.DOTALL)
ALT_RE = re.compile(r"\balt=[\"']([^\"']*)[\"']", re.IGNORECASE | re.DOTALL)
CLASS_RE = re.compile(r"\bclass=[\"']([^\"']*)[\"']", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
MAIN_CONTENT_START_RE = re.compile(
    r"""<(?:div|article|section)\b[^>]*(?:id=["'](?:zoomcon|vsb_content|artibody|trs_editor)["']|class=["'][^"']*(?:article_content|rich_media_content|wp_articlecontent|trs_editor)[^"']*["'])[^>]*>""",
    re.IGNORECASE | re.DOTALL,
)
MAIN_CONTENT_END_RE = re.compile(
    r"""<!--\s*正文\s*end\s*-->|<div\b[^>]*class=["'][^"']*(?:zrbj|article_attachments|article_documents)[^"']*["']""",
    re.IGNORECASE | re.DOTALL,
)


def find_attachment_links(html: str, base_url: str) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()

    for href, raw_name in HREF_RE.findall(html):
        url = urljoin(base_url, href)
        path = unquote(urlparse(url).path).lower()
        if not path.endswith(ATTACHMENT_EXTENSIONS):
            continue
        if url in seen:
            continue
        seen.add(url)
        name = _clean_text(raw_name) or unquote(path.rsplit("/", 1)[-1])
        attachments.append({"url": url, "name": name, "type": "document"})

    for item in _collect_body_images(html, base_url):
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        attachments.append(item)

    for raw_tag in IMG_RE.findall(html):
        src = _img_src(raw_tag)
        if not src:
            continue
        url = urljoin(base_url, src)
        path = unquote(urlparse(url).path).lower()
        if not _looks_like_image_url(url):
            continue
        if not _is_content_image(path, raw_tag):
            continue
        if url in seen:
            continue
        seen.add(url)
        alt_match = ALT_RE.search(raw_tag)
        name = _clean_text(alt_match.group(1)) if alt_match else ""
        attachments.append(
            {
                "url": url,
                "name": name or unquote(path.rsplit("/", 1)[-1]),
                "type": "image",
            }
        )

    return attachments


def attachment_suffix(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    suffix = path.rsplit(".", 1)[-1] if "." in path else _image_format_from_query(parsed.query) or "bin"
    suffix = re.sub(r"[^a-zA-Z0-9]+", "", suffix).lower()
    return f".{suffix or 'bin'}"


def _clean_text(value: str) -> str:
    text = TAG_RE.sub("", value)
    return SPACE_RE.sub(" ", unescape(text)).strip()


def _img_src(raw_tag: str) -> str | None:
    match = SRC_RE.search(raw_tag) or DATA_SRC_RE.search(raw_tag)
    if not match:
        return None
    return unescape(match.group(1)).strip()


def _looks_like_image_url(url: str) -> bool:
    parsed = urlparse(url)
    path = unquote(parsed.path).lower()
    if path.endswith(IMAGE_EXTENSIONS):
        return True
    return _image_format_from_query(parsed.query) is not None


def _image_format_from_query(query: str) -> str | None:
    match = re.search(r"(?:^|[&?])wx_fmt=(png|jpg|jpeg|webp)(?:&|$)", query, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower()


def _is_content_image(path: str, raw_tag: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name.startswith("w0"):
        return True

    class_match = CLASS_RE.search(raw_tag)
    classes = class_match.group(1).lower() if class_match else ""
    if "rich_pages" in classes or "wxw-img" in classes:
        return True

    return False


def _collect_body_images(html: str, base_url: str) -> list[dict[str, str]]:
    matches = list(MAIN_CONTENT_START_RE.finditer(html))
    if not matches:
        return []

    images: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in matches:
        start = match.end()
        end_match = MAIN_CONTENT_END_RE.search(html, start)
        end = end_match.start() if end_match else len(html)
        segment = html[start:end]
        for raw_tag in IMG_RE.findall(segment):
            src = _img_src(raw_tag)
            if not src:
                continue
            url = urljoin(base_url, src)
            if not _looks_like_image_url(url) or url in seen:
                continue
            seen.add(url)
            path = unquote(urlparse(url).path)
            alt_match = ALT_RE.search(raw_tag)
            name = _clean_text(alt_match.group(1)) if alt_match else ""
            images.append(
                {
                    "url": url,
                    "name": name or unquote(path.rsplit("/", 1)[-1]),
                    "type": "image",
                }
            )
    return images
