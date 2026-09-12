from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from oilprice.ocr import paddle


class OcrLifecycleTests(unittest.TestCase):
    def test_initialize_ocr_builds_one_process_wide_engine(self) -> None:
        engine = object()
        fake_paddleocr = SimpleNamespace(PaddleOCR=object)
        previous_instance = paddle._OCR_INSTANCE
        previous_error = paddle._OCR_ERROR
        try:
            paddle._OCR_INSTANCE = None
            paddle._OCR_ERROR = None
            with (
                patch.dict(sys.modules, {"paddleocr": fake_paddleocr}),
                patch.object(paddle, "_build_ocr", return_value=engine) as build_ocr,
            ):
                paddle.initialize_ocr()
                paddle.initialize_ocr()

            build_ocr.assert_called_once_with(object)
            self.assertIs(paddle._OCR_INSTANCE, engine)
        finally:
            paddle._OCR_INSTANCE = previous_instance
            paddle._OCR_ERROR = previous_error

    def test_image_to_text_reuses_preinitialized_engine(self) -> None:
        engine = object()
        previous_instance = paddle._OCR_INSTANCE
        previous_error = paddle._OCR_ERROR
        try:
            paddle._OCR_INSTANCE = engine
            paddle._OCR_ERROR = None
            with tempfile.TemporaryDirectory() as temp_dir:
                image_path = Path(temp_dir) / "table.jpg"
                image_path.write_bytes(b"image")
                with patch.object(
                    paddle,
                    "_predict",
                    return_value={"rec_texts": ["reused OCR"]},
                ) as predict:
                    result = paddle.image_to_text(image_path)

            self.assertEqual(result, "reused OCR")
            predict.assert_called_once_with(engine, image_path)
        finally:
            paddle._OCR_INSTANCE = previous_instance
            paddle._OCR_ERROR = previous_error


if __name__ == "__main__":
    unittest.main()
