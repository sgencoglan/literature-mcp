from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "report-kit" / "src"))

from report_kit.cleanup import CleanupError, cleanup_manifest, write_manifest  # noqa: E402
from report_kit.markdown import render_markdown  # noqa: E402
from report_kit.render import render_report  # noqa: E402
from report_kit.validate import validate_data, validate_html  # noqa: E402


def example_data() -> dict:
    return json.loads((ROOT / "examples" / "chapter-report.example.json").read_text(encoding="utf-8"))


class RenderTests(unittest.TestCase):
    def test_example_renders_golden_sections(self) -> None:
        html = render_report(example_data())
        self.assertIn('<span class="mark">', html)
        self.assertIn("Ek 1 — Değişikliklerin Kaynak Cümleleriyle Karşılaştırması", html)
        self.assertIn("Ek 2 — Kaynak Denetimi ve İddia–Kanıt Matrisi", html)
        self.assertIn("https://doi.org/10.5555/ornek.2024.001", html)
        self.assertIn("Örnek İş ve Örgüt Psikolojisi Dergisi (2024)", html)
        self.assertIn("✅ Destekli", html)
        self.assertNotIn("file://", html)
        self.assertNotIn("/home/", html)

    def test_html_is_balanced(self) -> None:
        result = validate_html(render_report(example_data()))
        self.assertTrue(result.ok, result.errors)

    def test_invalid_doi_does_not_become_a_link(self) -> None:
        data = example_data()
        data["change_cards"][0]["sources"][0]["doi"] = "not-a-doi"
        html = render_report(data)
        self.assertNotIn('href="https://doi.org/not-a-doi"', html)

    def test_text_is_escaped(self) -> None:
        data = example_data()
        data["title"] = '<script>alert(1)</script>'
        html = render_report(data)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_markdown_has_same_sections(self) -> None:
        markdown = render_markdown(example_data())
        self.assertIn("# 1. Giriş", markdown)
        self.assertIn("## Ek 1 — Değişikliklerin Kaynak Cümleleriyle Karşılaştırması", markdown)
        self.assertIn("## Ek 2 — Kaynak Denetimi ve İddia–Kanıt Matrisi", markdown)
        self.assertIn("| # | Kaynak | DOI |", markdown)
        self.assertIn("https://doi.org/10.5555/ornek.2024.001", markdown)
        self.assertNotIn("file://", markdown)
        self.assertNotIn("/home/", markdown)


class ValidationTests(unittest.TestCase):
    def test_example_passes_quality_gate(self) -> None:
        result = validate_data(example_data())
        self.assertTrue(result.ok, result.errors)

    def test_missing_source_quote_fails(self) -> None:
        data = copy.deepcopy(example_data())
        del data["change_cards"][0]["sources"][0]["quote"]
        result = validate_data(data)
        self.assertFalse(result.ok)
        self.assertTrue(any("quote" in error for error in result.errors))

    def test_missing_page_evidence_fails(self) -> None:
        data = copy.deepcopy(example_data())
        data["claim_matrix"][0]["evidence"] = "Genel olarak destekleniyor."
        result = validate_data(data)
        self.assertFalse(result.ok)
        self.assertTrue(any("sayfa" in error for error in result.errors))

    def test_local_path_fails(self) -> None:
        data = copy.deepcopy(example_data())
        data["title"] = "/home/kullanici/gizli.pdf"
        result = validate_data(data)
        self.assertFalse(result.ok)
        self.assertTrue(any("yerel yol" in error for error in result.errors))

    def test_summary_mismatch_fails(self) -> None:
        data = copy.deepcopy(example_data())
        data["summary"]["claims"] = 99
        result = validate_data(data)
        self.assertFalse(result.ok)
        self.assertTrue(any("summary.claims" in error for error in result.errors))


class CleanupTests(unittest.TestCase):
    def test_intermediate_cleanup_keeps_html_and_unrelated_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = root / "05_bolum_raporu.html"
            csv = root / "03_iddia_kanit_matrisi.csv"
            unrelated = root / "onemli_not.txt"
            html.write_text("<html></html>", encoding="utf-8")
            csv.write_text("a,b\n1,2\n", encoding="utf-8")
            unrelated.write_text("silme", encoding="utf-8")
            manifest = root / "05_bolum_raporu.manifest.json"
            write_manifest(manifest, "test", [(html, "html"), (csv, "intermediate")])
            with redirect_stdout(io.StringIO()):
                deleted = cleanup_manifest(manifest, scope="intermediate", yes=True)
            self.assertEqual(deleted, [csv])
            self.assertTrue(html.exists())
            self.assertTrue(unrelated.exists())
            self.assertFalse(csv.exists())

    def test_intermediate_cleanup_keeps_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = root / "05_bolum_raporu.html"
            md = root / "05_bolum_raporu.md"
            csv = root / "ara.csv"
            html.write_text("<html></html>", encoding="utf-8")
            md.write_text("# rapor", encoding="utf-8")
            csv.write_text("x", encoding="utf-8")
            manifest = root / "manifest.json"
            write_manifest(manifest, "test", [(html, "html"), (md, "markdown"), (csv, "intermediate")])
            with redirect_stdout(io.StringIO()):
                cleanup_manifest(manifest, scope="intermediate", yes=True)
            self.assertTrue(html.exists())
            self.assertTrue(md.exists())
            self.assertFalse(csv.exists())

    def test_all_cleanup_removes_html_but_keeps_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = root / "05_bolum_raporu.html"
            html.write_text("<html></html>", encoding="utf-8")
            manifest = root / "05_bolum_raporu.manifest.json"
            write_manifest(manifest, "test", [(html, "html")])
            with redirect_stdout(io.StringIO()):
                cleanup_manifest(manifest, scope="all", yes=True)
            self.assertFalse(html.exists())
            self.assertTrue(manifest.exists())

    def test_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / "disarida.txt"
            outside.write_text("x", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "generated_at": "2026-10-22",
                        "project": "test",
                        "files": [
                            {
                                "path": "../disarida.txt",
                                "kind": "intermediate",
                                "sha256": None,
                                "bytes": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(CleanupError):
                cleanup_manifest(manifest, scope="intermediate", yes=True)
            self.assertTrue(outside.exists())

    def test_missing_manifest_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv = root / "ara.csv"
            csv.write_text("x", encoding="utf-8")
            manifest = root / "manifest.json"
            write_manifest(manifest, "test", [(csv, "intermediate")])
            csv.unlink()
            with redirect_stdout(io.StringIO()):
                deleted = cleanup_manifest(manifest, scope="intermediate", yes=True)
            self.assertEqual(deleted, [])

    def test_dry_run_does_not_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv = root / "ara.csv"
            csv.write_text("x", encoding="utf-8")
            manifest = root / "manifest.json"
            write_manifest(manifest, "test", [(csv, "intermediate")])
            with redirect_stdout(io.StringIO()):
                deleted = cleanup_manifest(manifest, scope="intermediate", dry_run=True)
            self.assertEqual(deleted, [])
            self.assertTrue(csv.exists())


if __name__ == "__main__":
    unittest.main()
