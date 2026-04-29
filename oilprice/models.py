from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NoticeRef:
    notice_id: str
    province_code: str
    province_name: str
    province_slug: str
    title: str
    source_url: str
    published_at: str | None = None


@dataclass(frozen=True)
class RawNotice:
    ref: NoticeRef
    path: Path
    sha256: str
    content_type: str | None = None
