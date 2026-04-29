from __future__ import annotations

import subprocess
from pathlib import Path


def pdf_to_text(path: Path) -> str:
    text = _pdf_to_text_pdftotext(path)
    if text:
        return text
    return _pdf_to_text_pypdfium(path)


def _pdf_to_text_pdftotext(path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def _pdf_to_text_pypdfium(path: Path) -> str:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return ""

    lines: list[str] = []
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception:
        return ""

    try:
        for page in document:
            text_page = page.get_textpage()
            try:
                content = text_page.get_text_range()
            finally:
                text_page.close()
                page.close()
            if content:
                lines.append(content.strip())
    finally:
        document.close()

    return "\n".join(line for line in lines if line).strip()
