from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


WORD_TEXT = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def docx_to_text(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            content = archive.read("word/document.xml")
    except (BadZipFile, KeyError):
        return ""

    root = ElementTree.fromstring(content)
    parts = [node.text or "" for node in root.iter(WORD_TEXT)]
    return "\n".join(part for part in parts if part.strip())
