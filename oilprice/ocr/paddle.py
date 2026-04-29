from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


class OcrUnavailableError(RuntimeError):
    pass


def image_to_text(path: Path) -> str:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise OcrUnavailableError("paddleocr is not installed") from exc

    ocr = _build_ocr(PaddleOCR)
    prepared_path = path
    cleanup_path: Path | None = None
    try:
        prepared_path = _prepare_image_for_ocr(path)
        if prepared_path != path:
            cleanup_path = prepared_path
        result = _predict(ocr, prepared_path)
        return "\n".join(_extract_text_lines(result))
    finally:
        if cleanup_path:
            cleanup_path.unlink(missing_ok=True)


def _build_ocr(paddle_ocr_class: Any) -> Any:
    try:
        return paddle_ocr_class(
            lang="ch",
            ocr_version="PP-OCRv5",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except (TypeError, ValueError):
        return paddle_ocr_class(lang="ch", use_angle_cls=False)


def _predict(ocr: Any, path: Path) -> Any:
    if hasattr(ocr, "predict"):
        return ocr.predict(str(path))
    return ocr.ocr(str(path), cls=False)


def _prepare_image_for_ocr(path: Path) -> Path:
    if path.suffix.lower() != ".png":
        return path

    try:
        from PIL import Image
    except ImportError:
        return path

    try:
        image = Image.open(path)
    except OSError:
        return path

    if "A" not in image.getbands():
        return path

    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.split()[3])

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        background.save(tmp_path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        return path
    return tmp_path


def _extract_text_lines(value: Any) -> list[str]:
    lines: list[str] = []
    _collect_text(value, lines)
    return [line for line in lines if line]


def _collect_text(value: Any, lines: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            lines.append(text)
        return
    if isinstance(value, dict):
        for key in ("rec_texts", "texts"):
            items = value.get(key)
            if isinstance(items, list):
                for item in items:
                    _collect_text(item, lines)
        for key in ("json", "res", "result"):
            if key in value:
                _collect_text(value[key], lines)
        return
    if isinstance(value, (list, tuple)):
        if _looks_like_legacy_ocr_item(value):
            _collect_text(value[1][0], lines)
            return
        for item in value:
            _collect_text(item, lines)
        return
    json_value = getattr(value, "json", None)
    if json_value is not None:
        _collect_text(json_value, lines)


def _looks_like_legacy_ocr_item(value: list[Any] | tuple[Any, ...]) -> bool:
    if len(value) != 2:
        return False
    text_part = value[1]
    return (
        isinstance(text_part, (list, tuple))
        and len(text_part) >= 1
        and isinstance(text_part[0], str)
    )
