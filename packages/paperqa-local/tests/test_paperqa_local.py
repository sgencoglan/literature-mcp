"""paperqa-local için ağır bağımlılık gerektirmeyen birim testleri."""

from __future__ import annotations

import asyncio
import csv
import json
import os
import signal
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import paperqa_mcp


class HelperTests(unittest.TestCase):
    def test_model_name_strips_litellm_prefix(self) -> None:
        self.assertEqual(
            paperqa_mcp._model_name("openai/qwen2.5-3b-instruct"),
            "qwen2.5-3b-instruct",
        )
        self.assertEqual(
            paperqa_mcp._model_name("qwen2.5-3b-instruct"),
            "qwen2.5-3b-instruct",
        )

    def test_doi_candidates_from_filename(self) -> None:
        candidates = paperqa_mcp._doi_candidates_from_filename(
            "10.117701430343231202923.pdf"
        )
        self.assertGreater(len(candidates), 1)
        self.assertTrue(all(candidate.startswith("10.") for candidate in candidates))
        self.assertEqual(len(candidates), len(set(candidates)))

    def test_manifest_reader_skips_blank_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.csv"
            with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=paperqa_mcp.MANIFEST_FIELDS
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "file_location": "a.pdf",
                        "doi": "10.1234/a",
                        "title": "A",
                        "journal": "J",
                        "year": "2024",
                        "authors": "[]",
                    }
                )
                writer.writerow({field: "" for field in paperqa_mcp.MANIFEST_FIELDS})
            rows = paperqa_mcp._read_manifest(
                {"manifest": str(manifest), "paper_directory": tmp}
            )
            self.assertEqual([row["file_location"] for row in rows], ["a.pdf"])
            self.assertEqual(rows[0]["doi"], "10.1234/a")

    def _write_manifest(self, tmp: str, locations: list[str]) -> dict[str, str]:
        manifest = Path(tmp) / "manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=paperqa_mcp.MANIFEST_FIELDS
            )
            writer.writeheader()
            for location in locations:
                writer.writerow(
                    {
                        "file_location": location,
                        "doi": "",
                        "title": "",
                        "journal": "",
                        "year": "",
                        "authors": "",
                    }
                )
        return {"manifest": str(manifest), "paper_directory": tmp}

    def test_manifest_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_manifest(tmp, ["../outside.pdf"])
            with self.assertRaisesRegex(ValueError, "proje klasörü dışına"):
                paperqa_mcp._read_manifest(cfg)

    def test_manifest_rejects_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_manifest(tmp, ["/etc/passwd"])
            with self.assertRaisesRegex(ValueError, "mutlak yol"):
                paperqa_mcp._read_manifest(cfg)

    def test_manifest_rejects_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._write_manifest(tmp, ["a.pdf", "a.pdf"])
            with self.assertRaisesRegex(ValueError, "çift kayıt"):
                paperqa_mcp._read_manifest(cfg)

    def test_index_name_rejects_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_name"):
            paperqa_mcp._validate_index_name("../outside")
        self.assertEqual(paperqa_mcp._validate_index_name("proje-1"), "proje-1")

    def test_index_root_rejects_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_name"):
            paperqa_mcp._index_root(
                {"index_directory": "/tmp/indexes", "index_name": "../outside"}
            )
        _, root = paperqa_mcp._index_root(
            {"index_directory": "/tmp/indexes", "index_name": "proje-1"}
        )
        self.assertEqual(root.name, "proje-1")

    def test_backup_index_root_moves_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_root = Path(tmp) / "index"
            index_root.mkdir()
            (index_root / "data.bin").write_text("x", encoding="utf-8")
            backup = paperqa_mcp._backup_index_root(index_root)
            self.assertFalse(index_root.exists())
            self.assertTrue((backup / "data.bin").is_file())
            self.assertIn(".bak-", backup.name)

    def test_invalidate_project_cache_clears_derived_state(self) -> None:
        paperqa_mcp._settings_cache["p1"] = object()
        paperqa_mcp._docs_cache["p1"] = object()
        paperqa_mcp._doc_meta["p1"] = {}
        paperqa_mcp._invalidate_project_cache("p1")
        self.assertNotIn("p1", paperqa_mcp._settings_cache)
        self.assertNotIn("p1", paperqa_mcp._docs_cache)
        self.assertNotIn("p1", paperqa_mcp._doc_meta)


class ProjectRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry = self.root / "projects.json"
        self.patchers = [
            mock.patch.object(paperqa_mcp, "REGISTRY_PATH", self.registry),
            mock.patch.object(
                paperqa_mcp, "DEFAULT_PROJECTS_ROOT", self.root / "projects"
            ),
            mock.patch.object(
                paperqa_mcp, "DEFAULT_INDEX_ROOT", self.root / "indexes"
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
        paperqa_mcp._registry_cache = {"mtime": None, "data": None}

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        paperqa_mcp._registry_cache = {"mtime": None, "data": None}
        self.tmp.cleanup()

    def _register(self, name: str, directory: Path, **kwargs):
        pdf = directory / "10.1234test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        registered = paperqa_mcp._load_registry(force=True).get("projects", {}).get(name, {})
        kwargs.setdefault("output_directory", registered.get("output_directory", str(directory)))

        async def fake_resolve(path, probe):
            return "10.1234/test", True

        with mock.patch.object(
            paperqa_mcp, "_scan_pdfs", return_value=[pdf]
        ), mock.patch.object(
            paperqa_mcp,
            "_pdf_probe",
            return_value={"text": "", "title": "Test", "doi": ""},
        ), mock.patch.object(
            paperqa_mcp, "_resolve_doi_for_pdf", side_effect=fake_resolve
        ):
            return asyncio.run(
                paperqa_mcp.paperqa_register_project(
                    name=name,
                    paper_directory=str(directory),
                    enrich_metadata=False,
                    **kwargs,
                )
            )

    def test_unknown_project_lists_registered_names(self) -> None:
        directory = self.root / "p1"
        directory.mkdir()
        self._register("p1", directory)
        with self.assertRaisesRegex(ValueError, "p1"):
            paperqa_mcp._project_config("missing")

    def test_explicit_project_root_is_stored_as_output_directory(self) -> None:
        directory = self.root / "p1"
        directory.mkdir()
        result = self._register("p1", directory)
        self.assertEqual(
            Path(result["output_directory"]), directory.resolve()
        )
        entry = paperqa_mcp._load_registry(force=True)["projects"]["p1"]
        self.assertEqual(Path(entry["output_directory"]), directory.resolve())

    def test_explicit_output_directory_is_stored(self) -> None:
        directory = self.root / "p1"
        directory.mkdir()
        output = self.root / "reports"
        output.mkdir()
        result = self._register(
            "p1", directory, output_directory=str(output)
        )
        self.assertEqual(Path(result["output_directory"]), output.resolve())

    def test_projects_keep_separate_manifests(self) -> None:
        first = self.root / "p1"
        second = self.root / "p2"
        first.mkdir()
        second.mkdir()
        self._register("p1", first)
        self._register("p2", second)
        registry = paperqa_mcp._load_registry(force=True)
        self.assertEqual(sorted(registry["projects"]), ["p1", "p2"])
        self.assertNotEqual(
            registry["projects"]["p1"]["manifest"],
            registry["projects"]["p2"]["manifest"],
        )

    def test_reusing_name_with_new_folder_requires_refresh(self) -> None:
        first = self.root / "p1"
        second = self.root / "p2"
        first.mkdir()
        second.mkdir()
        self._register("p1", first)
        with self.assertRaisesRegex(ValueError, "refresh_manifest=True"):
            self._register("p1", second)
        result = self._register("p1", second, refresh_manifest=True)
        self.assertTrue(result["manifest_built"])
        self.assertEqual(result["paper_directory"], str(second.resolve()))

    def test_index_name_collision_is_rejected(self) -> None:
        first = self.root / "p1"
        second = self.root / "p2"
        first.mkdir()
        second.mkdir()
        workspace = self.root / "workspace"
        workspace.mkdir()
        self._register("p1", first, output_directory=str(workspace))
        with self.assertRaisesRegex(ValueError, "çakışması"):
            self._register(
                "p2", second, output_directory=str(workspace), index_name="p1"
            )

    def test_nested_index_path_is_rejected(self) -> None:
        first = self.root / "p1"
        second = self.root / "p2"
        first.mkdir()
        second.mkdir()
        workspace = self.root / "workspace"
        workspace.mkdir()
        self._register("p1", first, output_directory=str(workspace))
        nested_dir = workspace / ".literature-mcp" / "indexes" / "p1"
        with self.assertRaisesRegex(ValueError, "iç içe"):
            self._register(
                "p2", second, output_directory=str(workspace),
                index_directory=str(nested_dir), index_name="sub"
            )

    def test_register_rejects_unsafe_index_name(self) -> None:
        directory = self.root / "p1"
        directory.mkdir()
        with self.assertRaisesRegex(ValueError, "index_name"):
            self._register("p1", directory, index_name="../outside")

    def test_duplicate_doi_is_skipped(self) -> None:
        directory = self.root / "p1"
        directory.mkdir()
        first = directory / "a.pdf"
        second = directory / "b.pdf"
        first.write_bytes(b"%PDF-1.4\n")
        second.write_bytes(b"%PDF-1.4\n")

        async def fake_resolve(path, probe):
            return "10.1234/test", True

        with mock.patch.object(
            paperqa_mcp, "_scan_pdfs", return_value=[first, second]
        ), mock.patch.object(
            paperqa_mcp,
            "_pdf_probe",
            return_value={"text": "", "title": "", "doi": ""},
        ), mock.patch.object(
            paperqa_mcp, "_resolve_doi_for_pdf", side_effect=fake_resolve
        ):
            result = asyncio.run(
                paperqa_mcp.paperqa_register_project(
                    name="p1",
                    paper_directory=str(directory),
                    output_directory=str(directory),
                    enrich_metadata=False,
                )
            )
        self.assertEqual(result["manifest_rows"], 1)
        self.assertEqual(len(result["skipped_duplicate_doi"]), 1)
        self.assertEqual(
            result["skipped_duplicate_doi"][0]["kept"], "a.pdf"
        )

    def test_ask_fails_fast_when_server_is_down(self) -> None:
        directory = self.root / "p1"
        directory.mkdir()
        self._register("p1", directory)

        async def fake_ensure():
            return {
                "reachable": False,
                "model_available": False,
                "error": "yetersiz RAM",
            }

        with mock.patch.object(
            paperqa_mcp, "_ensure_llama_server", side_effect=fake_ensure
        ), mock.patch.object(
            paperqa_mcp, "_load_docs", new=mock.AsyncMock()
        ) as load_docs:
            result = asyncio.run(paperqa_mcp.paperqa_ask("p1", "test"))
        self.assertEqual(result["error"], "local llama.cpp server unavailable")
        self.assertIn("start_llamacpp.sh", result["hint"])
        self.assertEqual(result["detail"], "yetersiz RAM")
        load_docs.assert_not_awaited()

    def test_ask_validates_inputs_before_starting_server(self) -> None:
        directory = self.root / "p1"
        directory.mkdir()
        self._register("p1", directory)

        with mock.patch.object(
            paperqa_mcp, "_ensure_llama_server", new=mock.AsyncMock()
        ) as ensure:
            with self.assertRaisesRegex(ValueError, "tam sayı"):
                asyncio.run(
                    paperqa_mcp.paperqa_ask("p1", "test", evidence_k="bad")
                )
        ensure.assert_not_awaited()

    def test_ask_touches_server_after_success(self) -> None:
        directory = self.root / "p1"
        directory.mkdir()
        self._register("p1", directory)

        class FakeDocs:
            async def aquery(self, question, settings=None):
                return SimpleNamespace(answer="taslak", contexts=[])

        class FakeSettings:
            def __init__(self) -> None:
                self.answer = SimpleNamespace()

        async def fake_ensure():
            return {"reachable": True, "model_available": True}

        with mock.patch.object(
            paperqa_mcp, "_ensure_llama_server", side_effect=fake_ensure
        ), mock.patch.object(
            paperqa_mcp, "_load_docs", new=mock.AsyncMock(return_value=FakeDocs())
        ), mock.patch.object(
            paperqa_mcp, "_settings_for", return_value=FakeSettings()
        ), mock.patch.object(
            paperqa_mcp, "_touch_llama"
        ) as touch:
            result = asyncio.run(paperqa_mcp.paperqa_ask("p1", "test"))
        self.assertEqual(result["answer"], "taslak")
        touch.assert_called_once_with()
        self.assertEqual(paperqa_mcp._llama_active_asks, 0)


class LlamaLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {
            "_llama_process": paperqa_mcp._llama_process,
            "_llama_started_by_us": paperqa_mcp._llama_started_by_us,
            "_llama_active_asks": paperqa_mcp._llama_active_asks,
            "_llama_last_used": paperqa_mcp._llama_last_used,
            "_llama_stop_task": paperqa_mcp._llama_stop_task,
        }
        paperqa_mcp._llama_process = None
        paperqa_mcp._llama_started_by_us = False
        paperqa_mcp._llama_active_asks = 0
        paperqa_mcp._llama_last_used = 0.0
        paperqa_mcp._llama_stop_task = None
        self.pidfile = self.root / "llama.pid"
        self.patcher = mock.patch.object(
            paperqa_mcp, "LLAMA_PIDFILE", self.pidfile
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        for key, value in self.saved.items():
            setattr(paperqa_mcp, key, value)
        self.tmp.cleanup()

    def test_pid_is_llama_rejects_unrelated_process(self) -> None:
        self.assertFalse(paperqa_mcp._pid_is_llama(os.getpid()))
        self.assertFalse(paperqa_mcp._pid_alive(-1))

    def test_stop_without_server_is_noop(self) -> None:
        result = asyncio.run(paperqa_mcp._stop_llama_server("test"))
        self.assertFalse(result["stopped"])

    def test_atexit_does_not_stop_unmanaged_server(self) -> None:
        self.pidfile.write_text(
            json.dumps({"pid": os.getpid()}), encoding="utf-8"
        )
        with mock.patch.object(
            paperqa_mcp, "_pid_is_llama", return_value=True
        ), mock.patch.object(paperqa_mcp.os, "kill") as kill:
            paperqa_mcp._atexit_stop_llama()
        kill.assert_not_called()
        self.assertTrue(self.pidfile.exists())

    def test_atexit_stops_managed_server(self) -> None:
        self.pidfile.write_text(
            json.dumps({"pid": os.getpid()}), encoding="utf-8"
        )
        paperqa_mcp._llama_started_by_us = True
        with mock.patch.object(
            paperqa_mcp, "_pid_alive", return_value=True
        ), mock.patch.object(
            paperqa_mcp, "_pid_is_llama", return_value=True
        ), mock.patch.object(paperqa_mcp.os, "kill") as kill:
            paperqa_mcp._atexit_stop_llama()
        kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
        self.assertFalse(self.pidfile.exists())

    def test_idle_stop_skips_when_ask_is_active(self) -> None:
        paperqa_mcp._llama_started_by_us = True
        paperqa_mcp._llama_active_asks = 1
        paperqa_mcp._llama_last_used = 1.0
        with mock.patch.object(
            paperqa_mcp, "_stop_llama_server", new=mock.AsyncMock()
        ) as stop:
            asyncio.run(paperqa_mcp._idle_stop_after(0.01, 1.0))
        stop.assert_not_awaited()

    def test_idle_stop_skips_stale_timer(self) -> None:
        paperqa_mcp._llama_started_by_us = True
        paperqa_mcp._llama_last_used = 2.0
        with mock.patch.object(
            paperqa_mcp, "_stop_llama_server", new=mock.AsyncMock()
        ) as stop:
            asyncio.run(paperqa_mcp._idle_stop_after(0.01, 1.0))
        stop.assert_not_awaited()

    def test_idle_stop_runs_when_idle(self) -> None:
        paperqa_mcp._llama_started_by_us = True
        paperqa_mcp._llama_last_used = 1.0
        with mock.patch.object(
            paperqa_mcp, "_stop_llama_server", new=mock.AsyncMock()
        ) as stop:
            asyncio.run(paperqa_mcp._idle_stop_after(0.01, 1.0))
        stop.assert_awaited_once_with("idle timeout")

    def test_ensure_respects_disabled_auto_start(self) -> None:
        async def fake_status(**kwargs):
            return {"reachable": False, "model_available": False}

        with mock.patch.object(
            paperqa_mcp, "AUTO_START_LLAMA", False
        ), mock.patch.object(
            paperqa_mcp, "paperqa_llm_status", side_effect=fake_status
        ), mock.patch.object(
            paperqa_mcp.asyncio, "create_subprocess_exec", new=mock.AsyncMock()
        ) as spawn:
            result = asyncio.run(paperqa_mcp._ensure_llama_server())
        self.assertFalse(result["reachable"])
        spawn.assert_not_awaited()

    def test_ensure_adopts_already_reachable_server(self) -> None:
        async def fake_status(**kwargs):
            return {"reachable": True, "model_available": True}

        with mock.patch.object(
            paperqa_mcp, "paperqa_llm_status", side_effect=fake_status
        ), mock.patch.object(paperqa_mcp, "_adopt_pidfile") as adopt:
            result = asyncio.run(paperqa_mcp._ensure_llama_server())
        self.assertTrue(result["reachable"])
        adopt.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
