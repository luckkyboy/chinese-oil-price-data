from __future__ import annotations

import argparse
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from oilprice import extraction_pipeline, fetch_pipeline, pipeline, prices
from oilprice.adapters.generic import build_notice_id
from oilprice.extract.price_parser import extract_prices
from oilprice.io import read_json, write_json
from oilprice.normalize import price_snapshot
from oilprice.notices import filter_notices_for_adjustment_date
from oilprice.options import ExtractFilesOptions, ExtractOptions, FetchOptions, PriceOptions
from oilprice.parsers import extract_adjustment_date, parse_notice


class PriceMeaningTests(unittest.TestCase):
    def test_delta_is_not_a_price(self) -> None:
        cases = [
            ('92号汽油每升下调0.15元，最高零售价7.80元', {'92': 7.8}),
            ('92号汽油每升上调0.15元', {}),
            ('92号汽油原价7.80元，调整为每升7.65元', {'92': 7.65}),
            ('92号汽油调整为每升8元', {'92': 8.0}),
            ('92号汽油 10000 7.80', {'92': 7.8}),
            ('92号汽油 7.80 8.30', {}),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(extract_prices(text), expected)

    def test_partial_generic_result_is_completed_from_table(self) -> None:
        # Generic parsing sees 92; the product-only table row supplies 95.
        for adapter in ('hebei', 'shanxi', 'shandong'):
            with self.subTest(adapter=adapter):
                result = parse_notice(adapter, '92号汽油 7.80\n95号\n8.30')
                self.assertEqual(result['extracted_prices'], {'92': 7.8, '95': 8.3})

    def test_fullwidth_product_marker_is_normalized(self) -> None:
        for adapter in ('anhui', 'jiangsu'):
            with self.subTest(adapter=adapter):
                result = parse_notice(adapter, '92号汽油 7.80\n95＃汽油 8.30')
                self.assertEqual(result['extracted_prices'], {'92': 7.8, '95': 8.3})

    def test_table_row_does_not_borrow_next_products_price(self) -> None:
        for adapter in ('anhui', 'jiangsu', 'hebei', 'shanxi', 'jiangxi', 'shandong'):
            with self.subTest(adapter=adapter):
                result = parse_notice(adapter, '92号汽油\n10000\n95号汽油\n8.30')
                self.assertEqual(result['extracted_prices'], {'95': 8.3})

    def test_table_fallback_does_not_restore_a_rejected_delta(self) -> None:
        for adapter in ('anhui', 'jiangsu', 'hebei', 'shanxi', 'jiangxi', 'fujian'):
            with self.subTest(adapter=adapter):
                result = parse_notice(adapter, '92号汽油每升下调0.15元')
                self.assertFalse(result.get('extracted_prices'))

    def test_conflicting_repeated_table_rows_fail_explicitly(self) -> None:
        with self.assertRaisesRegex(ValueError, 'Conflicting parsed prices.*92'):
            parse_notice('anhui', '92号汽油 7.80\n92号汽油 8.30')

    def test_other_fuel_grades_bound_the_current_product(self) -> None:
        self.assertEqual(extract_prices('92号汽油\n98号汽油 9.80'), {})
        self.assertEqual(extract_prices('－10号柴油 7.30'), {})

    def test_product_mention_cannot_capture_browser_version_from_footer(self) -> None:
        self.assertEqual(extract_prices('标准品为0号车用柴油。\n建议使用IE10.0浏览器'), {})


class DateEvidenceTests(unittest.TestCase):
    def test_old_year_cannot_match_yearless_markers(self) -> None:
        for notice in (
            {'published_at': '2025-07-31'},
            {'source_url': 'https://example.test/2025/07/31/notice.html'},
            {'title': '2025年油价通知 07-31'},
        ):
            with self.subTest(notice=notice):
                self.assertEqual(filter_notices_for_adjustment_date([notice], '2026-07-31'), [])

    def test_month_day_only_is_discovery_evidence_not_publication_evidence(self) -> None:
        notices = [{'title': '07-31油价通知'}]
        self.assertEqual(filter_notices_for_adjustment_date(notices, '2026-07-31'), notices)
        self.assertEqual(filter_notices_for_adjustment_date(
            notices, '2026-07-31', allow_month_day=False,
        ), [])

    def test_full_date_fallback_and_year_boundary_remain_supported(self) -> None:
        for title in ('20260731', '2026年7月31日', '2026/7/31'):
            notices = [{'title': title, 'published_at': '2026-08-04'}]
            self.assertEqual(filter_notices_for_adjustment_date(
                notices, '2026-07-31', allow_month_day=False,
            ), notices)
        notices = [{'published_at': '2027-01-01'}]
        self.assertEqual(filter_notices_for_adjustment_date(notices, '2026-12-31'), notices)

    def test_publication_date_is_not_inferred_as_adjustment_date(self) -> None:
        self.assertIsNone(extract_adjustment_date('发布时间：2026-08-01'))
        self.assertIsNone(extract_adjustment_date('自2026年2月30日24时起'))
        self.assertEqual(extract_adjustment_date('自2026年7月31日24时起'), '2026-07-31')

    def test_price_builder_rejects_month_day_only_notice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / 'extracted.json', {
                'province_code': '110000', 'province_name': 'Beijing',
                'title': '07-31油价通知', 'source_url': 'https://example.test/notice',
                'extracted_prices': {'92': 7.8},
            })
            index = root / 'index.json'
            write_json(index, {'notices': [{
                'province_code': '110000', 'extracted_path': '/extracted.json',
            }]})
            with patch.object(prices, 'ROOT', root):
                with self.assertRaisesRegex(RuntimeError, 'missing requested province codes'):
                    prices.run_build_prices(PriceOptions(index, '2026-07-31', {'110000'}))
            self.assertFalse((root / 'data/prices').exists())


class LookupAndIdentityTests(unittest.TestCase):
    def test_unknown_province_fails_before_loading_prices(self) -> None:
        args = argparse.Namespace(province='hubeii', area='武汉市',
                                  adjustment_date='2026-07-31', parent=None, product=None)
        with patch.object(pipeline, 'province_code_for_slug', return_value=None), \
             patch.object(pipeline, 'read_json') as read:
            with self.assertRaisesRegex(SystemExit, 'unknown province: hubeii'):
                pipeline.command_lookup_price(args)
            read.assert_not_called()

    def test_missing_province_has_a_useful_error(self) -> None:
        args = argparse.Namespace(province='hubei', area='武汉市',
                                  adjustment_date='2026-07-31', parent=None, product=None)
        with patch.object(pipeline, 'province_code_for_slug', return_value='420000'), \
             patch.object(pipeline, 'read_json', return_value={'provinces': []}):
            with self.assertRaisesRegex(SystemExit, 'province not found'):
                pipeline.command_lookup_price(args)

    def test_notice_ids_preserve_url_identity(self) -> None:
        urls = [
            'https://example.test/a-b.html', 'https://example.test/a/b.html',
            'https://example.test/A/b.html', 'https://example.test/a/b.html?q=1',
            'https://other.test/' + 'x' * 100 + '/same.html',
            'https://example.test/' + 'x' * 100 + '/same.html',
        ]
        self.assertEqual(len({build_notice_id('anhui', url) for url in urls}), len(urls))
        self.assertEqual(build_notice_id('anhui', 'HTTPS://EXAMPLE.TEST/a#one'),
                         build_notice_id('anhui', 'https://example.test/a#two'))


class ArtifactIsolationTests(unittest.TestCase):
    @staticmethod
    def notice() -> dict:
        # Existing IDs remain valid inputs; no eager historical migration.
        return {'notice_id': 'legacy-notice', 'province_code': '110000',
                'province_name': 'Beijing', 'source_name': 'Official',
                'source_url': 'https://example.test/notice', 'adapter': 'generic',
                'title': '2026年7月31日油价'}

    @staticmethod
    def download(url, *, raw_path, **kwargs):
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        content = '<p>自2026年7月31日24时起，92号汽油 7.80</p>'.encode()
        raw_path.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def test_refetch_keeps_old_raw_file_and_invalidates_old_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_raw = root / 'old.html'
            old_raw.write_text('old', encoding='utf-8')
            notice = self.notice() | {'raw_path': '/old.html', 'extracted_path': '/old.json',
                                      'raw_sha256': 'old-hash'}
            index = root / 'index.json'
            write_json(index, {'notices': [notice]})
            with patch.object(fetch_pipeline, 'ROOT', root), \
                 patch.object(fetch_pipeline, 'fetch_notice_with_browser', side_effect=self.download):
                fetch_pipeline.run_fetch(FetchOptions(index, '2026-07-31', 1, True))
            updated = read_json(index)['notices'][0]
            self.assertEqual(old_raw.read_text(), 'old')
            self.assertNotEqual(updated['raw_path'], '/old.html')
            self.assertNotIn('extracted_path', updated)
            self.assertEqual(updated['raw_sha256'], updated['sha256'])

    def test_reextraction_keeps_old_payload_and_index_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'raw.html'
            self.download('', raw_path=raw)
            index = root / 'index.json'
            write_json(index, {'notices': [self.notice() | {'raw_path': '/raw.html'}],
                               'errors': [{'message': 'upstream error'}]})
            with patch.object(extraction_pipeline, 'ROOT', root):
                options = ExtractFilesOptions(index, '2026-07-31', True)
                extraction_pipeline.run_extract_files(options)
                old_path = root / read_json(index)['notices'][0]['extracted_path'].lstrip('/')
                old_bytes = old_path.read_bytes()
                raw.write_text('<p>92号汽油 8.30</p>', encoding='utf-8')
                extraction_pipeline.run_extract_files(options)
            updated = read_json(index)
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertNotEqual(root / updated['notices'][0]['extracted_path'].lstrip('/'), old_path)
            self.assertEqual(updated['errors'], [{'message': 'upstream error'}])

    def test_failed_publication_preserves_index_and_every_referenced_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / 'data/sources/provinces.json'
            write_json(registry, {'provinces': [{'province_code': '110000', 'province_name': 'Beijing'}]})
            index = root / 'tmp/index.json'
            source = {'province_code': '110000', 'province_name': 'Beijing', 'slug': 'legacy', 'source': {}}

            def discover(options):
                write_json(options.index_path, {'notices': [self.notice()], 'errors': []})

            with patch.object(pipeline, 'ROOT', root), \
                 patch.object(fetch_pipeline, 'ROOT', root), \
                 patch.object(extraction_pipeline, 'ROOT', root), \
                 patch.object(prices, 'ROOT', root), \
                 patch.object(price_snapshot, 'ROOT', root), \
                 patch.object(pipeline, 'BrowserSession', MagicMock()), \
                 patch.object(pipeline, 'load_enabled_sources', return_value=[source]), \
                 patch.object(pipeline, 'run_discover', side_effect=discover), \
                 patch.object(fetch_pipeline, 'fetch_notice_with_browser', side_effect=self.download):
                options = ExtractOptions(registry, index, '2026-07-31', 1, True)
                pipeline.run_extract(options)
                notice = read_json(index)['notices'][0]
                protected = [index, root / notice['raw_path'].lstrip('/'),
                             root / notice['extracted_path'].lstrip('/'),
                             *root.joinpath('data/prices').rglob('*.json')]
                before = {path: path.read_bytes() for path in protected}
                with patch.object(prices, 'write_json_batch_atomic', side_effect=OSError('publication failed')):
                    with self.assertRaisesRegex(OSError, 'publication failed'):
                        pipeline.run_extract(options)
                self.assertEqual({path: path.read_bytes() for path in protected}, before)
                pipeline.run_extract(options)
                self.assertNotEqual(read_json(index)['notices'][0]['raw_path'], notice['raw_path'])
                for path in protected[1:3]:
                    self.assertEqual(path.read_bytes(), before[path])

    def test_ocr_retry_clears_old_error_without_overwriting_previous_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.download('', raw_path=root / 'raw.html')
            (root / 'old.ocr.txt').write_text('old OCR', encoding='utf-8')
            (root / 'table.png').write_bytes(b'image mocked in this test')
            index = root / 'index.json'
            write_json(index, {'notices': [self.notice() | {
                'raw_path': '/raw.html', 'ocr_attachments': True,
                'attachments': [{'path': '/table.png', 'type': 'image',
                                 'ocr_error': 'old failure', 'ocr_text_path': '/old.ocr.txt'}],
            }]})
            with patch.object(extraction_pipeline, 'ROOT', root), \
                 patch.object(extraction_pipeline, 'should_ocr_attachment', return_value=True), \
                 patch.object(extraction_pipeline, 'image_to_text', return_value='OCR succeeded'):
                extraction_pipeline.run_extract_files(ExtractFilesOptions(index, '2026-07-31', True))
            attachment = read_json(index)['notices'][0]['attachments'][0]
            self.assertNotIn('ocr_error', attachment)
            self.assertNotEqual(attachment['ocr_text_path'], '/old.ocr.txt')
            self.assertEqual((root / 'old.ocr.txt').read_text(), 'old OCR')
            self.assertEqual((root / attachment['ocr_text_path'].lstrip('/')).read_text(), 'OCR succeeded')


if __name__ == '__main__':
    unittest.main()
