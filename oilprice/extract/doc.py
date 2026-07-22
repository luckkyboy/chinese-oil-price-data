from __future__ import annotations

from pathlib import Path


def doc_to_text(path: Path) -> str:
    """Extract text from a bounded, legacy Word 97-2003 OLE document."""

    try:
        from legacy_doc import extract_text
    except ImportError as exc:
        raise RuntimeError(
            "legacy .doc extraction requires legacy-doc==0.2.1"
        ) from exc

    result = extract_text(path.read_bytes())
    return result.text.strip()
