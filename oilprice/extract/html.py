from __future__ import annotations

import re
from html import unescape


SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")
BLANK_LINE_RE = re.compile(r"\n{3,}")


def html_to_text(content: bytes) -> str:
    raw = content.decode("utf-8", errors="replace")
    raw = SCRIPT_STYLE_RE.sub("", raw)
    raw = re.sub(r"</(p|div|br|li|tr|h[1-6])\s*>", "\n", raw, flags=re.IGNORECASE)
    text = TAG_RE.sub("", raw)
    text = unescape(text)
    text = SPACE_RE.sub(" ", text)
    text = BLANK_LINE_RE.sub("\n\n", text)
    return text.strip()
