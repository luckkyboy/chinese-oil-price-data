from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from oilprice.io import read_json, write_json, write_json_batch_atomic
from oilprice.options import DiscoverOptions, ExtractOptions, PriceOptions
from oilprice import discovery_pipeline, pipeline, prices


def _snapshot(adjustment_date: str, province_codes: set[str]) -> dict[str, object]:
    return {
        "adjustment_date": adjustment_date,
        "effective_from": f"{adjustment_date}T00:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "unit": "CNY/L",
        "currency": "CNY",
        "products": ["92"],
        "provinces": [
            {
                "province_code": code,
                "province_name": code,
                "sources": [],
                "zones": [
                    {
                        "zone_code": "default",
                        "zone_name": "default",
                        "items": {"92": 8.0},
                        "missing_products": [],
                    }
                ],
            }
            for code in sorted(province_codes)
        ],
        "updated_at": "2026-07-20T00:00:00+08:00",
    }


class AtomicJsonWriteTests(unittest.TestCase):
    def test_write_json_replaces_the_target_with_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "payload.json"
            path.write_text('{"old": true}\n', encoding="utf-8")

            write_json(path, {"new": True})

            self.assertEqual(read_json(path), {"new": True})
            self.assertEqual([item for item in path.parent.iterdir() if item != path], [])

    def test_write_json_preserves_the_old_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "payload.json"
            original = '{"old": true}\n'
            path.write_text(original, encoding="utf-8")

            with patch("oilprice.io.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    write_json(path, {"new": True})

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual([item for item in path.parent.iterdir() if item != path], [])

    def test_batch_failure_restores_every_target_and_removes_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.json"
            second = root / "second.json"
            third = root / "third.json"
            first.write_text('{"old": 1}\n', encoding="utf-8")
            second.write_text('{"old": 2}\n', encoding="utf-8")
            real_replace = os.replace

            def fail_second_promotion(source: object, target: object) -> None:
                if Path(target) == second and Path(source).suffix == ".tmp":
                    raise OSError("second promotion failed")
                real_replace(source, target)

            with patch("oilprice.io.os.replace", side_effect=fail_second_promotion):
                with self.assertRaisesRegex(OSError, "second promotion failed"):
                    write_json_batch_atomic(
                        {
                            first: {"new": 1},
                            second: {"new": 2},
                            third: {"new": 3},
                        }
                    )

            self.assertEqual(read_json(first), {"old": 1})
            self.assertEqual(read_json(second), {"old": 2})
            self.assertFalse(third.exists())
            self.assertEqual(set(root.iterdir()), {first, second})


class PricePublicationGuardTests(unittest.TestCase):
    def _run_build(
        self,
        root: Path,
        adjustment_date: str,
        required_codes: set[str],
        incoming_codes: set[str],
        additional_payloads: dict[Path, object] | None = None,
    ) -> None:
        index_path = root / "tmp" / "index.json"
        write_json(index_path, {"notices": []})
        options = PriceOptions(
            index_path=index_path,
            adjustment_date=adjustment_date,
            province_codes=required_codes,
        )
        summary = {
            "adjustment_date": adjustment_date,
            "price_file": f"/data/prices/{adjustment_date[:4]}/{adjustment_date}.json",
            "status": "complete",
            "provinces_total": len(incoming_codes),
            "provinces_success": len(incoming_codes),
            "provinces_missing": [],
        }
        with (
            patch.object(prices, "ROOT", root),
            patch.object(
                prices,
                "build_snapshot",
                return_value=_snapshot(adjustment_date, incoming_codes),
            ),
            patch.object(prices, "build_price_summary", return_value=summary),
        ):
            prices.run_build_prices(options, additional_payloads=additional_payloads)

    def test_price_publication_rolls_back_when_notice_index_promotion_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            global_index = root / "tmp" / "global-index.json"
            write_json(global_index, {"notices": ["old"]})
            real_replace = os.replace

            def fail_global_index(source: object, target: object) -> None:
                if Path(target) == global_index and Path(source).suffix == ".tmp":
                    raise OSError("global index promotion failed")
                real_replace(source, target)

            with (
                patch("oilprice.io.os.replace", side_effect=fail_global_index),
                self.assertRaisesRegex(OSError, "global index promotion failed"),
            ):
                self._run_build(
                    root,
                    "2026-07-20",
                    {"110000"},
                    {"110000"},
                    additional_payloads={global_index: {"notices": ["new"]}},
                )

            self.assertEqual(read_json(global_index), {"notices": ["old"]})
            self.assertFalse(root.joinpath("data/prices/2026/2026-07-20.json").exists())
            self.assertFalse(root.joinpath("data/prices/2026/2026-07-20.summary.json").exists())
            self.assertFalse(root.joinpath("data/prices/latest.json").exists())

    def test_missing_required_province_fails_before_writing_prices(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(RuntimeError, "110000"):
                self._run_build(root, "2026-07-20", {"110000"}, set())

            self.assertFalse(root.joinpath("data/prices/2026/2026-07-20.json").exists())
            self.assertFalse(root.joinpath("data/prices/latest.json").exists())

    def test_historical_backfill_does_not_move_latest_backwards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest_path = root / "data" / "prices" / "latest.json"
            existing_latest = {
                "latest": "2026/2026-07-20.json",
                "latest_summary": "2026/2026-07-20.summary.json",
                "adjustment_date": "2026-07-20",
                "updated_at": "2026-07-20T00:00:00+08:00",
            }
            write_json(latest_path, existing_latest)

            self._run_build(root, "2026-07-03", {"110000"}, {"110000"})

            self.assertEqual(read_json(latest_path), existing_latest)
            self.assertTrue(root.joinpath("data/prices/2026/2026-07-03.json").exists())

    def test_same_or_newer_adjustment_date_updates_latest(self) -> None:
        for target_date in ("2026-07-20", "2026-08-01"):
            with self.subTest(target_date=target_date), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                latest_path = root / "data" / "prices" / "latest.json"
                write_json(
                    latest_path,
                    {
                        "latest": "2026/2026-07-20.json",
                        "latest_summary": "2026/2026-07-20.summary.json",
                        "adjustment_date": "2026-07-20",
                        "updated_at": "old",
                    },
                )

                self._run_build(root, target_date, {"110000"}, {"110000"})

                latest = read_json(latest_path)
                self.assertEqual(latest["adjustment_date"], target_date)
                self.assertEqual(latest["updated_at"], "2026-07-20T00:00:00+08:00")

    def test_invalid_existing_latest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest_path = root / "data" / "prices" / "latest.json"
            write_json(latest_path, {"adjustment_date": "not-a-date"})

            with self.assertRaises((RuntimeError, ValueError)):
                self._run_build(root, "2026-07-20", {"110000"}, {"110000"})

            self.assertEqual(read_json(latest_path), {"adjustment_date": "not-a-date"})
            self.assertFalse(root.joinpath("data/prices/2026/2026-07-20.json").exists())


class ExtractionOrchestrationGuardTests(unittest.TestCase):
    @staticmethod
    def _options(root: Path) -> ExtractOptions:
        return ExtractOptions(
            sources_path=root / "data" / "sources" / "provinces.json",
            index_path=root / "tmp" / "notices" / "2026-07-20" / "index.json",
            adjustment_date="2026-07-20",
            timeout=30,
            force=True,
            province_codes=None,
        )

    @staticmethod
    def _source(province_code: str, province_name: str) -> dict[str, object]:
        return {
            "province_code": province_code,
            "province_name": province_name,
            "slug": province_code,
            "source": {
                "name": province_name,
                "list_urls": [f"https://example.invalid/{province_code}"],
            },
        }

    def test_unknown_explicit_province_is_rejected_before_browser_start(self) -> None:
        enabled_sources = [self._source("110000", "Beijing")]

        with self.assertRaisesRegex(ValueError, "999999"):
            pipeline.validate_requested_province_codes(enabled_sources, {"999999"})

    def test_discovery_error_preserves_the_existing_global_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            options = self._options(root)
            existing_notice = {
                "notice_id": "old-notice",
                "province_code": "110000",
                "province_name": "Beijing",
                "source_url": "https://example.invalid/old",
            }
            write_json(options.index_path, {"notices": [existing_notice]})

            def fail_discovery(discover_options: object) -> str:
                province_index = discover_options.index_path
                write_json(
                    province_index,
                    {
                        "notices": [],
                        "errors": [
                            {
                                "province_code": "110000",
                                "stage": "browser",
                                "url": "https://example.invalid/110000",
                                "message": "timeout",
                            }
                        ],
                    },
                )
                return str(province_index)

            browser_factory = MagicMock()
            browser_factory.return_value.__enter__.return_value = object()
            with (
                patch.object(pipeline, "ROOT", root),
                patch.object(
                    pipeline,
                    "load_enabled_sources",
                    return_value=[self._source("110000", "Beijing")],
                ),
                patch.object(pipeline, "BrowserSession", browser_factory),
                patch.object(pipeline, "run_discover", side_effect=fail_discovery),
                patch.object(pipeline, "run_fetch") as run_fetch,
                patch.object(pipeline, "run_extract_files") as run_extract_files,
                patch.object(pipeline, "run_build_prices") as run_build_prices,
            ):
                with self.assertRaisesRegex(RuntimeError, "discovery failed"):
                    pipeline.run_extract(options)

            self.assertEqual(read_json(options.index_path)["notices"], [existing_notice])
            run_fetch.assert_not_called()
            run_extract_files.assert_not_called()
            run_build_prices.assert_not_called()

    def test_empty_discovery_preserves_the_existing_global_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            options = self._options(root)
            existing_notice = {
                "notice_id": "old-notice",
                "province_code": "110000",
                "province_name": "Beijing",
                "source_url": "https://example.invalid/old",
            }
            write_json(options.index_path, {"notices": [existing_notice]})

            def empty_discovery(discover_options: object) -> str:
                province_index = discover_options.index_path
                write_json(province_index, {"notices": [], "errors": []})
                return str(province_index)

            browser_factory = MagicMock()
            browser_factory.return_value.__enter__.return_value = object()
            with (
                patch.object(pipeline, "ROOT", root),
                patch.object(
                    pipeline,
                    "load_enabled_sources",
                    return_value=[self._source("110000", "Beijing")],
                ),
                patch.object(pipeline, "BrowserSession", browser_factory),
                patch.object(pipeline, "run_discover", side_effect=empty_discovery),
                patch.object(pipeline, "run_fetch") as run_fetch,
                patch.object(pipeline, "run_extract_files") as run_extract_files,
                patch.object(pipeline, "run_build_prices") as run_build_prices,
            ):
                with self.assertRaisesRegex(RuntimeError, "no notices found"):
                    pipeline.run_extract(options)

            self.assertEqual(read_json(options.index_path)["notices"], [existing_notice])
            run_fetch.assert_not_called()
            run_extract_files.assert_not_called()
            run_build_prices.assert_not_called()

    def test_fetch_failure_does_not_replace_the_existing_global_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            options = self._options(root)
            existing_notice = {
                "notice_id": "old-notice",
                "province_code": "110000",
                "province_name": "Beijing",
                "source_url": "https://example.invalid/old",
            }
            write_json(options.index_path, {"notices": [existing_notice]})

            def discover(discover_options: object) -> str:
                province_index = discover_options.index_path
                write_json(
                    province_index,
                    {
                        "notices": [
                            {
                                "notice_id": "new-notice",
                                "province_code": "110000",
                                "province_name": "Beijing",
                                "source_url": "https://example.invalid/new",
                            }
                        ],
                        "errors": [],
                    },
                )
                return str(province_index)

            browser_factory = MagicMock()
            browser_factory.return_value.__enter__.return_value = object()
            with (
                patch.object(pipeline, "ROOT", root),
                patch.object(
                    pipeline,
                    "load_enabled_sources",
                    return_value=[self._source("110000", "Beijing")],
                ),
                patch.object(pipeline, "BrowserSession", browser_factory),
                patch.object(pipeline, "run_discover", side_effect=discover),
                patch.object(pipeline, "run_fetch", side_effect=RuntimeError("fetch failed")),
                patch.object(pipeline, "run_extract_files") as run_extract_files,
                patch.object(pipeline, "run_build_prices") as run_build_prices,
            ):
                with self.assertRaisesRegex(RuntimeError, "fetch failed"):
                    pipeline.run_extract(options)

            self.assertEqual(read_json(options.index_path)["notices"], [existing_notice])
            run_extract_files.assert_not_called()
            run_build_prices.assert_not_called()

    def test_price_quality_failure_does_not_replace_the_existing_global_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            options = self._options(root)
            existing_notice = {
                "notice_id": "old-notice",
                "province_code": "110000",
                "province_name": "Beijing",
                "source_url": "https://example.invalid/old",
            }
            write_json(options.index_path, {"notices": [existing_notice]})

            def discover(discover_options: object) -> str:
                province_index = discover_options.index_path
                write_json(
                    province_index,
                    {
                        "notices": [
                            {
                                "notice_id": "new-notice",
                                "province_code": "110000",
                                "province_name": "Beijing",
                                "source_url": "https://example.invalid/new",
                            }
                        ],
                        "errors": [],
                    },
                )
                return str(province_index)

            browser_factory = MagicMock()
            browser_factory.return_value.__enter__.return_value = object()
            with (
                patch.object(pipeline, "ROOT", root),
                patch.object(
                    pipeline,
                    "load_enabled_sources",
                    return_value=[self._source("110000", "Beijing")],
                ),
                patch.object(pipeline, "BrowserSession", browser_factory),
                patch.object(pipeline, "run_discover", side_effect=discover),
                patch.object(pipeline, "run_fetch"),
                patch.object(pipeline, "run_extract_files"),
                patch.object(
                    pipeline,
                    "run_build_prices",
                    side_effect=RuntimeError("price completeness failed"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "price completeness failed"):
                    pipeline.run_extract(options)

            self.assertEqual(read_json(options.index_path)["notices"], [existing_notice])
            self.assertEqual(
                list(options.index_path.parent.glob("*.candidate")),
                [],
            )

    def test_successful_provinces_use_staging_and_build_prices_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            options = self._options(root)
            write_json(options.index_path, {"notices": []})
            enabled_sources = [
                self._source("110000", "Beijing"),
                self._source("110000", "Beijing backup"),
                self._source("120000", "Tianjin"),
            ]
            discovered_paths: list[Path] = []

            def discover(discover_options: object) -> str:
                province_code = next(iter(discover_options.province_codes))
                province_index = discover_options.index_path
                discovered_paths.append(province_index)
                write_json(
                    province_index,
                    {
                        "notices": [
                            {
                                "notice_id": f"notice-{province_code}",
                                "province_code": province_code,
                                "province_name": province_code,
                                "source_url": f"https://example.invalid/{province_code}",
                            }
                        ],
                        "errors": [],
                    },
                )
                return str(province_index)

            browser_factory = MagicMock()
            browser_factory.return_value.__enter__.return_value = object()
            with (
                patch.object(pipeline, "ROOT", root),
                patch.object(pipeline, "load_enabled_sources", return_value=enabled_sources),
                patch.object(pipeline, "BrowserSession", browser_factory),
                patch.object(pipeline, "run_discover", side_effect=discover) as run_discover,
                patch.object(pipeline, "run_fetch") as run_fetch,
                patch.object(pipeline, "run_extract_files") as run_extract_files,
                patch.object(pipeline, "run_build_prices") as run_build_prices,
            ):
                pipeline.run_extract(options)

            self.assertEqual(run_discover.call_count, 2)
            self.assertEqual(run_fetch.call_count, 2)
            self.assertEqual(run_extract_files.call_count, 2)
            self.assertTrue(all(path != options.index_path for path in discovered_paths))
            self.assertTrue(
                all(call.args[0].index_path != options.index_path for call in run_fetch.call_args_list)
            )
            run_build_prices.assert_called_once()
            price_options = run_build_prices.call_args.args[0]
            self.assertNotEqual(price_options.index_path, options.index_path)
            self.assertEqual(price_options.index_path.parent, options.index_path.parent)
            self.assertEqual(price_options.province_codes, {"110000", "120000"})
            self.assertFalse(price_options.index_path.exists())
            additional_payloads = run_build_prices.call_args.kwargs["additional_payloads"]
            self.assertEqual(
                {
                    notice["province_code"]
                    for notice in additional_payloads[options.index_path]["notices"]
                },
                {"110000", "120000"},
            )


class DiscoveryErrorReportingTests(unittest.TestCase):
    def test_browser_failure_is_written_as_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "discover.json"
            list_url = "https://example.invalid/notices"
            enabled_source = ExtractionOrchestrationGuardTests._source("110000", "Beijing")
            options = DiscoverOptions(
                sources_path=root / "sources.json",
                index_path=output_path,
                adjustment_date="2026-07-20",
                timeout=30,
                force=True,
                province_codes={"110000"},
            )
            error = discovery_pipeline.BrowserDiscoveryError(
                list_url,
                TimeoutError("request timed out"),
            )

            with (
                patch.object(
                    discovery_pipeline,
                    "load_enabled_sources",
                    return_value=[enabled_source],
                ),
                patch.object(discovery_pipeline, "_fetch_list_html", side_effect=error),
            ):
                discovery_pipeline.run_discover(options)

            payload = read_json(output_path)
            self.assertEqual(payload["notices"], [])
            self.assertEqual(len(payload["errors"]), 1)
            self.assertEqual(payload["errors"][0]["province_code"], "110000")
            self.assertEqual(payload["errors"][0]["stage"], "browser")
            self.assertEqual(payload["errors"][0]["url"], list_url)
            self.assertEqual(payload["errors"][0]["cause_type"], "TimeoutError")


class WorkflowInjectionGuardTests(unittest.TestCase):
    def test_step_outputs_are_not_interpolated_directly_into_bash(self) -> None:
        workflow = Path(".github/workflows/daily-fetch.yml").read_text(encoding="utf-8")

        self.assertIn("date.fromisoformat", workflow)
        self.assertNotIn(
            'git commit -m "actions:oilprice:update ${{ steps.decide.outputs.target_date }} prices"',
            workflow,
        )
        self.assertNotIn(
            'echo "- target_date: ${{ steps.decide.outputs.target_date',
            workflow,
        )

    def test_generated_data_is_validated_before_automatic_commit(self) -> None:
        workflow = Path(".github/workflows/daily-fetch.yml").read_text(encoding="utf-8")

        validation_position = workflow.index("python -m oilprice.cli validate-json")
        commit_position = workflow.index("git commit -m")
        self.assertLess(validation_position, commit_position)

    def test_runtime_and_quality_ci_share_the_validation_requirement(self) -> None:
        runtime_requirements = Path("requirements.txt").read_text(encoding="utf-8")
        quality_workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

        self.assertIn("-r requirements-core.txt", runtime_requirements)
        self.assertIn("pip install -r requirements-core.txt", quality_workflow)
        self.assertNotIn("jsonschema>=", quality_workflow)


if __name__ == "__main__":
    unittest.main()
