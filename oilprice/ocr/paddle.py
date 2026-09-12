from __future__ import annotations

import os
import sys
import tempfile
import logging
from threading import Lock
from pathlib import Path
from typing import Any


class OcrUnavailableError(RuntimeError):
    pass


_OCR_INSTANCE: Any | None = None
_OCR_ERROR: OcrUnavailableError | None = None
_OCR_LOCK = Lock()
_DEFAULT_PADDLEX_CACHE_HOME = Path(sys.prefix) / ".paddlex"
_OCR_CPU_THREADS = 1


def image_to_text(path: Path) -> str:
    ocr = _get_ocr()
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


def initialize_ocr() -> None:
    """Eagerly initialize the process-wide OCR engine for the current CLI run."""

    root_logger = logging.getLogger()
    root_level = root_logger.level
    try:
        _get_ocr()
    finally:
        # PaddleOCR 3.x currently changes the application root logger to WARNING
        # while constructing the pipeline. Restore the CLI's logging contract so
        # per-province timing records remain visible after OCR warm-up.
        root_logger.setLevel(root_level)


def _get_ocr() -> Any:
    global _OCR_INSTANCE, _OCR_ERROR

    if _OCR_INSTANCE is not None:
        return _OCR_INSTANCE
    if _OCR_ERROR is not None:
        raise _OCR_ERROR

    with _OCR_LOCK:
        if _OCR_INSTANCE is not None:
            return _OCR_INSTANCE
        if _OCR_ERROR is not None:
            raise _OCR_ERROR

        # PaddleX uses the PADDLE_PDX_* name. Keep the legacy variable too because
        # older PaddleOCR/PaddleX combinations still read it.
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
        # PP-OCRv5 + Windows/Linux CPU oneDNN/PIR has known native crashes and
        # hangs in the first predict() call. The safe CPU path is intentional.
        os.environ.setdefault("FLAGS_enable_pir_api", "0")
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_DEFAULT_PADDLEX_CACHE_HOME))
        _DEFAULT_PADDLEX_CACHE_HOME.mkdir(parents=True, exist_ok=True)
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            _OCR_ERROR = OcrUnavailableError("paddleocr is not installed")
            raise _OCR_ERROR from exc

        try:
            _OCR_INSTANCE = _build_ocr(PaddleOCR)
        except Exception as exc:
            _OCR_ERROR = OcrUnavailableError(f"paddleocr initialization failed: {exc}")
            raise _OCR_ERROR from exc
        return _OCR_INSTANCE


def _build_ocr(paddle_ocr_class: Any) -> Any:
    try:
        return paddle_ocr_class(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
            device="cpu",
            enable_mkldnn=False,
            cpu_threads=_OCR_CPU_THREADS,
            # Small table labels such as "一价区" can merge with a table's
            # horizontal rule at the source resolution.  `min` upscales the
            # short edge before detection; this preserves the one-stroke
            # character "一" for PP-OCRv5_mobile_det without changing the
            # recognition threshold or filtering valid OCR results.
            text_det_limit_type="min",
            text_det_limit_side_len=960,
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
