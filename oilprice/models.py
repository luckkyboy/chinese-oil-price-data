from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NoticeRef:
    notice_id: str
    province_code: str
    province_name: str
    province_slug: str
    title: str
    source_url: str
    published_at: str | None = None
