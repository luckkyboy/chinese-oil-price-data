from __future__ import annotations

from typing import Any, TypedDict


class AttachmentPayload(TypedDict, total=False):
    url: str
    name: str
    type: str
    path: str
    sha256: str
    ocr_error: str
    ocr_text_path: str


class NoticePayload(TypedDict, total=False):
    notice_id: str
    province_code: str
    province_name: str
    source_name: str
    adapter: str
    title: str
    source_url: str
    published_at: str
    cookie: str
    rendered_notice_fallback: bool
    ocr_attachments: bool
    raw_path: str
    sha256: str
    attachments: list[AttachmentPayload]
    extracted_path: str
    content_text: str
    extracted_prices: dict[str, float]
    extracted_zones: list["ZonePayload"]
    confidence: str
    extracted_at: str


class SourceConfig(TypedDict, total=False):
    name: str
    base_url: str
    list_urls: list[str]
    notice_keywords: list[str]
    adapter: str
    enabled: bool
    cookie: str
    discovery_enhancer: str
    rendered_list_fallback: bool
    rendered_notice_fallback: bool
    ocr_attachments: bool
    website_code: str
    channel_id: str
    channel_root_code: str
    channel_path: list[str]
    search_page_size: int
    search_page_limit: int


class EnabledSource(TypedDict):
    province_code: str
    province_name: str
    slug: str
    source: SourceConfig


class ZonePayload(TypedDict, total=False):
    zone_code: str
    zone_name: str
    items: dict[str, float]
    missing_products: list[str]


class ParsedNoticePayload(TypedDict, total=False):
    adjustment_date: str
    extracted_prices: dict[str, float]
    extracted_zones: list[ZonePayload]
    confidence: str


class PriceSourcePayload(TypedDict, total=False):
    notice_id: str
    title: str
    name: str
    url: str


class PriceProvincePayload(TypedDict):
    province_code: str
    province_name: str
    sources: list[PriceSourcePayload]
    zones: list[ZonePayload]


class PriceSnapshotPayload(TypedDict):
    adjustment_date: str
    effective_from: str
    timezone: str
    unit: str
    currency: str
    products: list[str]
    provinces: list[PriceProvincePayload]
    updated_at: str
