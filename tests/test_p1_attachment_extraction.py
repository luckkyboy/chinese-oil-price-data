from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from oilprice import extraction_pipeline
from oilprice.errors import TextExtractionError
from oilprice.extract.doc import doc_to_text
from oilprice.io import read_json, write_json
from oilprice.options import ExtractFilesOptions


class AttachmentExtractionObservabilityTests(unittest.TestCase):
    def test_legacy_doc_extractor_returns_normalized_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "notice.doc"
            payload = b"\xd0\xcf\x11\xe0legacy-word"
            path.write_bytes(payload)

            with patch(
                "legacy_doc.extract_text",
                return_value=SimpleNamespace(text="  extracted table  \n"),
            ) as extract_text:
                result = doc_to_text(path)

        self.assertEqual(result, "extracted table")
        extract_text.assert_called_once_with(payload)

    def test_unsupported_document_suffixes_are_recorded_in_both_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = self._write_index(
                root,
                [
                    ("legacy.rtf", "document"),
                    ("workbook.xlsx", "document"),
                ],
            )

            with (
                patch.object(extraction_pipeline, "ROOT", root),
                patch.object(extraction_pipeline, "html_to_text", return_value="notice body"),
                patch.object(
                    extraction_pipeline,
                    "parse_notice",
                    return_value={"confidence": "manual_required"},
                ),
                self.assertLogs("oilprice.extraction_pipeline", level="WARNING") as logs,
            ):
                extraction_pipeline.run_extract_files(self._options(index_path))

            index = read_json(index_path)
            indexed_attachments = index["notices"][0]["attachments"]
            extracted_path = root / index["notices"][0]["extracted_path"].lstrip("/")
            extracted_attachments = read_json(extracted_path)["attachments"]

            for suffix, position in ((".rtf", 0), (".xlsx", 1)):
                with self.subTest(suffix=suffix):
                    indexed_error = indexed_attachments[position]["extraction_error"]
                    self.assertIn(suffix, indexed_error)
                    self.assertEqual(
                        extracted_attachments[position]["extraction_error"],
                        indexed_error,
                    )

            warning_output = "\n".join(logs.output)
            self.assertIn("suffix=.rtf", warning_output)
            self.assertIn("suffix=.xlsx", warning_output)

    def test_all_supported_document_suffixes_still_dispatch_to_extractors(self) -> None:
        calls: list[tuple[str, str]] = []

        def extractor(label: str):
            def extract(path: Path) -> str:
                calls.append((label, path.name))
                return f"text from {label}"

            return extract

        extractors = {
            ".doc": extractor("doc"),
            ".docx": extractor("docx"),
            ".pdf": extractor("pdf"),
            ".xls": extractor("xls"),
        }
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(extraction_pipeline.DOCUMENT_TEXT_EXTRACTORS, extractors, clear=True),
        ):
            root = Path(temp_dir)
            results = []
            for suffix in extractors:
                path = root / f"notice{suffix}"
                path.write_bytes(b"test")
                results.append(extraction_pipeline.extract_attachment_text(path))

        self.assertEqual(results, ["text from doc", "text from docx", "text from pdf", "text from xls"])
        self.assertEqual(
            calls,
            [
                ("doc", "notice.doc"),
                ("docx", "notice.docx"),
                ("pdf", "notice.pdf"),
                ("xls", "notice.xls"),
            ],
        )

    def test_supported_extractor_failures_are_not_silenced(self) -> None:
        failure = RuntimeError("corrupt PDF")
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(
                extraction_pipeline.DOCUMENT_TEXT_EXTRACTORS,
                {".pdf": MagicMock(side_effect=failure)},
                clear=True,
            ),
        ):
            path = Path(temp_dir) / "notice.pdf"
            path.write_bytes(b"invalid")
            with self.assertRaises(TextExtractionError) as raised:
                extraction_pipeline.extract_attachment_text(path)

        self.assertIs(raised.exception.cause, failure)

    def test_image_attachment_still_uses_ocr_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = self._write_index(root, [("table.jpg", "image")])
            parse_notice = MagicMock(return_value={"confidence": "manual_required"})

            with (
                patch.object(extraction_pipeline, "ROOT", root),
                patch.object(extraction_pipeline, "html_to_text", return_value="notice body"),
                patch.object(extraction_pipeline, "should_ocr_attachment", return_value=True),
                patch.object(extraction_pipeline, "image_to_text", return_value="ocr table"),
                patch.object(extraction_pipeline, "parse_notice", parse_notice),
            ):
                extraction_pipeline.run_extract_files(self._options(index_path))

            index = read_json(index_path)
            attachment = index["notices"][0]["attachments"][0]
            self.assertIn("ocr_text_path", attachment)
            self.assertNotIn("extraction_error", attachment)
            self.assertIn("ocr table", parse_notice.call_args.args[1])

    @staticmethod
    def _options(index_path: Path) -> ExtractFilesOptions:
        return ExtractFilesOptions(
            index_path=index_path,
            adjustment_date=None,
            force=True,
        )

    @staticmethod
    def _write_index(
        root: Path,
        attachment_specs: list[tuple[str, str]],
    ) -> Path:
        notice_root = root / "tmp" / "notices" / "2026-07-20"
        raw_root = notice_root / "raw" / "sichuan"
        raw_root.mkdir(parents=True, exist_ok=True)
        raw_path = raw_root / "notice.html"
        raw_path.write_text("<html>notice</html>", encoding="utf-8")

        attachments = []
        for filename, attachment_type in attachment_specs:
            path = raw_root / filename
            path.write_bytes(b"attachment")
            attachments.append(
                {
                    "url": f"https://example.gov.cn/{filename}",
                    "name": filename,
                    "type": attachment_type,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": f"sha-{filename}",
                }
            )

        index_path = notice_root / "index.json"
        write_json(
            index_path,
            {
                "notices": [
                    {
                        "notice_id": "sichuan-notice",
                        "province_code": "510000",
                        "province_name": "四川",
                        "title": "成品油价格调整公告",
                        "source_url": "https://example.gov.cn/notice",
                        "raw_path": raw_path.relative_to(root).as_posix(),
                        "attachments": attachments,
                    }
                ]
            },
        )
        return index_path


if __name__ == "__main__":
    unittest.main()
