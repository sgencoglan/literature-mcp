from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import build_fulltext_list as fl  # noqa: E402
import build_search_coverage as cov  # noqa: E402
import download_open_access as oa  # noqa: E402
import output_naming  # noqa: E402
import promote_fulltext as pf  # noqa: E402


def sample_candidate(doi: str = "10.1000/xyz.123") -> dict:
    return {
        "doi": doi,
        "title": "Örnek makale",
        "authors": "Yilmaz, A.",
        "year": 2024,
        "journal": "Örnek Dergi",
        "publisher": "Diğer",
        "priority": "A",
        "rationale": "Örnek gerekçe.",
        "project_relevance": "Örnek katkı.",
        "supports": ["Örnek destek."],
        "does_not_support": ["Örnek sınır."],
        "limits": ["Örnek sınırlılık."],
        "assessment_basis": "metadata",
        "open_access": True,
        "oa_pdf_url": "https://example.org/paper.pdf",
        "publisher_url": "https://example.org/article",
    }


class PromoteFilenameTests(unittest.TestCase):
    def test_doi_anywhere_in_filename(self) -> None:
        self.assertEqual(
            pf._dois_from_filename("Yilmaz_2024_10.1000_xyz.123.pdf")[0],
            "10.1000/xyz.123",
        )
        self.assertEqual(
            pf._dois_from_filename("10.4073csr.2011.4.pdf")[0],
            "10.4073/csr.2011.4",
        )
        self.assertEqual(
            pf._dois_from_filename("10.1007s12310-018-09303-z.PDF")[0],
            "10.1007/s12310-018-09303-z",
        )
        self.assertEqual(pf._dois_from_filename("makale.pdf"), [])


class OutputNamingTests(unittest.TestCase):
    def test_timestamp_suffix_format(self) -> None:
        moment = datetime(2026, 11, 8, 13, 45, 6)
        self.assertEqual(
            output_naming.timestamp_suffix(moment),
            "20261108-134506",
        )

    def test_add_timestamp_is_idempotent(self) -> None:
        moment = datetime(2026, 11, 8, 13, 45, 6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "liste.html"
            stamped = output_naming.add_timestamp(path, moment)
            self.assertEqual(stamped.name, "liste_20261108-134506.html")
            self.assertEqual(output_naming.add_timestamp(stamped, moment), stamped)

    def test_collision_gets_numeric_suffix(self) -> None:
        moment = datetime(2026, 11, 8, 13, 45, 6)
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "liste_20261108-134506.html"
            first.write_text("x", encoding="utf-8")
            second = output_naming.add_timestamp(Path(tmp) / "liste.html", moment)
            self.assertEqual(second.name, "liste_20261108-134506-01.html")

    def test_canonical_text_ignores_volatile_timestamps(self) -> None:
        first = '{"generated_at": "2026-11-09T10:00:00", "value": 1}'
        second = '{"generated_at": "2026-11-10T11:00:00", "value": 1}'
        self.assertEqual(
            output_naming.canonical_text(first, ".json"),
            output_naming.canonical_text(second, ".json"),
        )
        self.assertNotEqual(
            output_naming.canonical_text('{"value": 1}', ".json"),
            output_naming.canonical_text('{"value": 2}', ".json"),
        )

    def test_write_versioned_skips_identical_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "rapor.json"
            payload = '{"generated_at": "2026-11-09T10:00:00", "x": 1}'
            first = output_naming.write_versioned(base, payload)
            self.assertEqual(first["status"], "written")
            second = output_naming.write_versioned(
                base, '{"generated_at": "2026-11-10T10:00:00", "x": 1}'
            )
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(first["path"], second["path"])
            self.assertEqual(len(output_naming.versions_of(base)), 1)

    def test_write_versioned_archives_old_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "rapor.json"
            first = output_naming.write_versioned(base, '{"x": 1}')
            second = output_naming.write_versioned(base, '{"x": 2}')
            self.assertEqual(second["status"], "written")
            self.assertTrue(second["archived"])
            self.assertEqual(len(output_naming.versions_of(base)), 1)
            archive = Path(tmp) / "arsiv"
            self.assertTrue(archive.is_dir())
            self.assertEqual(
                sorted(p.name for p in archive.iterdir()), [first["path"].name]
            )

    def test_write_versioned_pair_keeps_json_and_html_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "matris.json"
            first = output_naming.write_versioned_pair(
                base, {".json": '{"x": 1}', ".html": "<p>1</p>"}
            )
            self.assertEqual(first["status"], "written")
            self.assertTrue(first["path"].with_suffix(".html").exists())
            second = output_naming.write_versioned_pair(
                base, {".json": '{"x": 1}', ".html": "<p>1</p>"}
            )
            self.assertEqual(second["status"], "unchanged")
            third = output_naming.write_versioned_pair(
                base, {".json": '{"x": 2}', ".html": "<p>2</p>"}
            )
            self.assertEqual(third["status"], "written")
            archived = sorted(p.suffix for p in (Path(tmp) / "arsiv").iterdir())
            self.assertEqual(archived, [".html", ".json"])


class FulltextListTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "project": "ornek-proje",
            "title": "Örnek Bölüm",
            "query": "örnek sorgu",
            "generated_at": "2026-11-08",
            "target_count": 2,
            "candidates": [
                sample_candidate("10.1016/j.appdev.2020.101199"),
                sample_candidate("10.1000/xyz.123"),
            ],
        }

    def _write_input(self, root: Path, payload: dict) -> Path:
        source_dir = root / "03_kaynak_kesfi"
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / "01_fulltext_listesi_20261108-120000.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_detects_downloaded_doi_from_filename_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self._payload()
            input_path = self._write_input(root, payload)
            fulltext = root / "04_taslak" / "fulltext"
            fulltext.mkdir(parents=True)
            (fulltext / "10.1016j.appdev.2020.101199.pdf").write_bytes(b"%PDF-1.4")
            found = fl.detect_downloaded_dois(payload, input_path)
            self.assertIn("10.1016/j.appdev.2020.101199", found)
            self.assertNotIn("10.1000/xyz.123", found)

    def test_detects_downloaded_doi_from_source_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self._payload()
            input_path = self._write_input(root, payload)
            fulltext = root / "03_kaynak_kesfi" / "fulltext"
            fulltext.mkdir(parents=True)
            (fulltext / "Yilmaz_2024_10.1000_xyz.123.pdf").write_bytes(b"%PDF-1.4")
            found = fl.detect_downloaded_dois(payload, input_path)
            self.assertIn("10.1000/xyz.123", found)
            self.assertNotIn("10.1016/j.appdev.2020.101199", found)

    def test_oa_fields_mark_candidate_downloaded(self) -> None:
        payload = self._payload()
        payload["candidates"][0]["oa_downloaded"] = True
        payload["candidates"][0]["oa_local_file"] = "paper.pdf"
        with tempfile.TemporaryDirectory() as tmp:
            input_path = self._write_input(Path(tmp), payload)
            found = fl.detect_downloaded_dois(payload, input_path)
            self.assertEqual(found, {"10.1016/j.appdev.2020.101199"})

    def test_html_checks_downloaded_and_shows_plain_doi(self) -> None:
        html_text = fl.build_html(
            self._payload(), {"10.1016/j.appdev.2020.101199"}
        )
        self.assertEqual(html_text.count('data-downloaded="1"'), 1)
        self.assertEqual(html_text.count(" checked"), 1)
        self.assertIn("PDF indirildi", html_text)
        self.assertIn('<span class="link-label">doi</span>', html_text)
        self.assertIn(
            '<span class="plain-url">10.1016/j.appdev.2020.101199</span>',
            html_text,
        )
        self.assertNotIn("https://doi.org/10.1016/j.appdev.2020.101199</span>", html_text)
        self.assertNotIn("DOI kopyala", html_text)
        self.assertIn('class="btn doi"', html_text)
        self.assertIn(
            '<a class="btn pub" href="https://example.org/article" '
            'target="_blank" rel="noopener">Diğer</a>',
            html_text,
        )

    def test_database_link_derived_from_doi_prefix(self) -> None:
        payload = {
            "project": "p",
            "title": "T",
            "query": "q",
            "generated_at": "2026-11-09",
            "candidates": [
                {
                    **sample_candidate("10.1007/s10864-022-09491-4"),
                    "publisher": "Diğer",
                    "publisher_url": None,
                    "oa_pdf_url": None,
                }
            ],
        }
        html_text = fl.build_html(payload, set())
        self.assertIn(
            'href="https://link.springer.com/article/10.1007/s10864-022-09491-4"',
            html_text,
        )
        self.assertIn('rel="noopener">SpringerLink</a>', html_text)

    def test_html_stat_counts_downloaded(self) -> None:
        html_text = fl.build_html(
            self._payload(), {"10.1016/j.appdev.2020.101199"}
        )
        self.assertIn('<span class="num" id="stat-done">1</span>', html_text)
        self.assertIn('<span class="num" id="stat-left">1</span>', html_text)


class SearchCoverageTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "project": "ornek-proje",
            "query": "örnek sorgu",
            "coverage": {
                "sources_queried": ["openalex", "semantic_scholar"],
                "per_source": {
                    "openalex": {"returned": 3, "unique_dois": 2, "high_quality": 1},
                    "semantic_scholar": {"returned": 2, "unique_dois": 2, "high_quality": 1},
                },
                "total_unique_dois": 3,
                "high_quality_total": 2,
                "high_quality_threshold": 0.6,
                "evidence_scarcity": True,
                "evidence_scarcity_message": "Bu konuda yüksek kaliteli kanıt sınırlı görünüyor. Araştırma boşluğu olasılığı yüksektir.",
                "query_variants": ["örnek sorgu"],
                "timestamp": "2026-11-08T00:00:00+00:00",
            },
            "results": [
                {
                    "title": "Örnek çalışma",
                    "year": 2024,
                    "journal": "Örnek Dergi",
                    "study_design": "Cohort study",
                    "score": 0.7,
                    "cited_by": 12,
                    "doi": "10.1000/xyz.123",
                }
            ],
        }

    def test_validates_payload(self) -> None:
        self.assertEqual(cov.validate(self._payload()), [])

    def test_rejects_missing_coverage(self) -> None:
        errors = cov.validate({"project": "x"})
        self.assertTrue(errors)

    def test_rejects_negative_counts(self) -> None:
        payload = self._payload()
        payload["coverage"]["per_source"]["openalex"]["returned"] = -1
        self.assertTrue(cov.validate(payload))

    def test_render_contains_summary_and_scarcity(self) -> None:
        html_text = cov.render(self._payload())
        self.assertIn("Arama kapsam raporu", html_text)
        self.assertIn("Semantic Scholar", html_text)
        self.assertIn("Kanıt sınırlılığı", html_text)
        self.assertIn("Bu konuda yüksek kaliteli kanıt sınırlı görünüyor.", html_text)
        self.assertIn("Örnek çalışma", html_text)
        self.assertNotIn("<script", html_text)

    def test_render_query_expansion_and_evidence_density(self) -> None:
        payload = self._payload()
        payload["coverage"]["query_expansion"] = {
            "original": "ADHD okul performansı müdahale",
            "expanded": ["ADHD school performance intervention"],
            "mesh": ["Attention Deficit Disorder with Hyperactivity[Mesh]"],
            "languages": ["Türkçe → İngilizce"],
            "transformations": ["synonym", "MeSH", "language"],
            "notes": ["MeSH PubMed için kullanıldı."],
        }
        payload["coverage"]["evidence_density"] = {
            "total_results": 3,
            "high_quality_total": 2,
            "q1_total": 1,
            "q1_ratio": 0.3333,
            "recent_window_years": 5,
            "recent_window_start": 2022,
            "recent_total": 2,
            "recent_ratio": 0.6667,
            "randomized_controlled_trial_total": 1,
            "systematic_review_or_meta_analysis_total": 1,
            "clinical_trial_total": 0,
            "preprint_total": 0,
            "study_designs": {"Randomized controlled trial": 1},
        }
        payload["coverage"]["closest_studies"] = [
            {
                "title": "Örnek çalışma",
                "year": 2024,
                "doi": "10.1000/xyz.123",
                "score": 0.7,
                "study_design": "Cohort study",
            }
        ]
        html_text = cov.render(payload)
        self.assertIn("Sorgu ve genişletme", html_text)
        self.assertIn("ADHD school performance intervention", html_text)
        self.assertIn("Attention Deficit Disorder with Hyperactivity[Mesh]", html_text)
        self.assertIn("Türkçe → İngilizce", html_text)
        self.assertIn("Kanıt yoğunluğu", html_text)
        self.assertIn("Son 5 yıl oranı", html_text)
        self.assertIn("RCT", html_text)
        self.assertIn("Sistematik derleme / meta-analiz", html_text)
        self.assertIn("En yakın çalışma", html_text)
        self.assertIn("Araştırma boşluğu olasılığı yüksektir", html_text)

    def test_render_source_status_and_publisher_distribution(self) -> None:
        payload = self._payload()
        payload["coverage"]["per_source"]["openalex"].update(
            {
                "status": "ok",
                "note": "OpenAlex relevance search",
                "requested_limit": 10,
                "duration_ms": 320,
                "rate_limited": False,
            }
        )
        payload["coverage"]["per_source"]["semantic_scholar"].update(
            {
                "status": "rate_limited",
                "note": "429 cooldown",
                "requested_limit": 10,
                "duration_ms": 90,
                "rate_limited": True,
            }
        )
        payload["coverage"]["skipped_sources"] = [
            {"source": "arxiv", "reason": "include_arxiv=false"}
        ]
        payload["coverage"]["warnings"] = [
            "semantic_scholar bu koşuda hız limiti (429) nedeniyle devre dışı bırakıldı.",
            "arxiv bu koşuda sorgulanmadı: include_arxiv=false.",
        ]
        payload["coverage"]["publisher_distribution"] = {
            "total": 3,
            "counts": {"sciencedirect": 1, "wiley": 1, "other": 0, "unknown": 1},
            "labels": {
                "sciencedirect": "ScienceDirect",
                "wiley": "Wiley",
                "other": "Diğer yayıncı",
                "unknown": "Yayıncı bilinmiyor",
            },
            "ratios": {"sciencedirect": 0.3333, "wiley": 0.3333, "other": 0.0, "unknown": 0.3334},
            "open_access_total": 1,
            "open_access_ratio": 0.3333,
            "preprint_total": 0,
            "preprint_ratio": 0.0,
            "pdf_link_total": 2,
            "pdf_link_ratio": 0.6667,
        }
        html_text = cov.render(payload)
        self.assertIn("Kaynak uyarıları", html_text)
        self.assertIn("Hız limiti", html_text)
        self.assertIn("Sorgulanmadı", html_text)
        self.assertIn("İstenen limit", html_text)
        self.assertIn("320 ms", html_text)
        self.assertIn("Toplam (tekilleştirilmiş)", html_text)
        self.assertIn("Publisher ve fulltext erişim dağılımı", html_text)
        self.assertIn("ScienceDirect", html_text)
        self.assertIn("Açık erişim", html_text)

    def test_validate_rejects_bad_source_status(self) -> None:
        payload = self._payload()
        payload["coverage"]["per_source"]["openalex"]["status"] = "unknown"
        self.assertTrue(cov.validate(payload))
        payload["coverage"]["per_source"]["openalex"]["status"] = "ok"
        self.assertEqual(cov.validate(payload), [])

    def test_validate_rejects_bad_publisher_counts(self) -> None:
        payload = self._payload()
        payload["coverage"]["publisher_distribution"] = {"counts": {"wiley": -1}}
        self.assertTrue(cov.validate(payload))
        payload["coverage"]["publisher_distribution"] = {"counts": {"wiley": 1}}
        self.assertEqual(cov.validate(payload), [])

    def test_render_markdown_contains_sections(self) -> None:
        payload = self._payload()
        payload["coverage"]["evidence_density"] = {
            "total_results": 3,
            "high_quality_total": 2,
            "high_quality_strict_total": 1,
            "high_quality_strict_ratio": 0.3333,
            "high_quality_strict_rule": "Q1/Q2 + en az 10 atıf + RCT",
            "q1_total": 1,
            "q1_ratio": 0.3333,
            "recent_window_years": 5,
            "recent_window_start": 2022,
            "recent_total": 2,
            "recent_ratio": 0.6667,
            "randomized_controlled_trial_total": 1,
            "systematic_review_or_meta_analysis_total": 1,
            "clinical_trial_total": 0,
            "preprint_total": 0,
            "trend": {
                "window_years": 3,
                "years": [2024, 2025, 2026],
                "counts": {"2024": 1, "2025": 2, "2026": 3},
                "slope": 1.0,
                "direction": "artıyor",
                "change_ratio": 2.0,
                "undated_total": 0,
            },
            "study_designs": {"Randomized controlled trial": 1},
        }
        markdown = cov.render_markdown(payload)
        self.assertIn("# Arama Kapsam Raporu", markdown)
        self.assertIn("## Sorgu ve genişletme", markdown)
        self.assertIn("## Kanıt yoğunluğu", markdown)
        self.assertIn("Katı yüksek kalite", markdown)
        self.assertIn("artıyor", markdown)
        self.assertIn("## Kaynak bazında kapsam", markdown)
        self.assertIn("| OpenAlex |", markdown)
        self.assertIn("## Yöntem ve tanımlar", markdown)

    def test_compare_coverage_and_render(self) -> None:
        left = self._payload()
        right = self._payload()
        right["coverage"]["total_unique_dois"] = 9
        right["coverage"]["high_quality_total"] = 4
        right["coverage"]["per_source"]["openalex"]["unique_dois"] = 7
        right["results"] = right["results"][:1]
        comparison = cov.compare_coverage(left, right, "A", "B")
        self.assertEqual(comparison["delta_total_unique_dois"], 6)
        self.assertEqual(comparison["delta_high_quality_total"], 2)
        self.assertEqual(comparison["doi_overlap"], 1)
        self.assertEqual(comparison["doi_only_left_total"], 0)
        self.assertIn("per_source", comparison)
        html_text = cov.render_comparison(comparison)
        self.assertIn("Arama kapsamı karşılaştırması", html_text)
        self.assertIn("Tekil DOI farkı", html_text)
        self.assertNotIn("<script", html_text)

    def test_main_writes_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "arama.json"
            source.write_text(
                json.dumps(self._payload(), ensure_ascii=False), encoding="utf-8"
            )
            code = cov.main([str(source), "--no-timestamp"])
            self.assertEqual(code, 0)
            self.assertTrue((root / "01_arama_kapsam_raporu.md").is_file())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "arama.json"
            source.write_text(
                json.dumps(self._payload(), ensure_ascii=False), encoding="utf-8"
            )
            code = cov.main([str(source), "--no-timestamp", "--no-markdown"])
            self.assertEqual(code, 0)
            self.assertFalse((root / "01_arama_kapsam_raporu.md").exists())

    def test_main_compare_writes_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "a.json"
            right = root / "b.json"
            payload = self._payload()
            left.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            other = json.loads(json.dumps(payload))
            other["coverage"]["total_unique_dois"] = 10
            right.write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
            code = cov.main(
                [
                    str(left),
                    "--no-timestamp",
                    "--compare",
                    str(right),
                    "--compare-label",
                    "B",
                    "--auto-report",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((root / "01_arama_kapsam_raporu_karsilastirma.json").is_file())
            self.assertTrue((root / "01_arama_kapsam_raporu_karsilastirma.html").is_file())

    def test_validate_rejects_bad_trend(self) -> None:
        payload = self._payload()
        payload["coverage"]["evidence_density"] = {
            "trend": {"direction": "uydurma"}
        }
        self.assertTrue(cov.validate(payload))
        payload["coverage"]["evidence_density"] = {
            "trend": {"direction": "artıyor", "counts": {"2026": 2}}
        }
        self.assertEqual(cov.validate(payload), [])

    def test_load_selected_flags_downloaded_and_rejects_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fulltext = root / "fulltext"
            fulltext.mkdir()
            (fulltext / "Sahin_2015_10.7827_turkishstudies.7838.pdf").write_bytes(b"%PDF-1.4")
            listing = root / "liste.json"
            listing.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "doi": "10.7827/turkishstudies.7838",
                                "title": "T",
                                "year": 2015,
                                "priority": "C",
                                "rationale": "gerekçe",
                            },
                            {
                                "doi": "10.1000/x",
                                "title": "U",
                                "year": 2024,
                                "priority": "A",
                                "rationale": "başka",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            selected = cov.load_selected(listing, [fulltext])
            self.assertEqual(len(selected), 2)
            self.assertIn("PDF indirildi", selected[0]["transfer_note"])
            self.assertIn("PDF bekliyor", selected[1]["transfer_note"])

            bad = root / "bad.json"
            bad.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                cov.load_selected(bad, [fulltext])

    def test_merge_selected_adds_missing_selected_items(self) -> None:
        results = [{"doi": "10.1/a", "title": "A", "score": 0.9}]
        selected = [
            {"doi": "10.1/a", "title": "A", "score": 0.9},
            {"doi": "10.1/b", "title": "B", "score": 0.5, "citations": 3},
            {"doi": "", "title": "no doi"},
        ]
        merged = cov._merge_selected_into_results(results, selected)
        dois = [str(item.get("doi") or "") for item in merged]
        self.assertEqual(dois, ["10.1/a", "10.1/b"])
        self.assertEqual(merged[1]["cited_by"], 3)

    def test_render_marks_selected_results_with_badge(self) -> None:
        payload = self._payload()
        payload["selected"] = [
            {
                "doi": "10.1000/xyz.123",
                "title": "Örnek seçilmiş",
                "year": 2024,
                "rationale": "Bu yüzden seçildi.",
                "transfer_note": "Fulltext HTML'e aktarıldı; PDF indirildi",
            }
        ]
        html_text = cov.render(payload)
        self.assertIn('class="badge selected">seçildi', html_text)
        self.assertNotIn("Seçilen makaleler ve fulltext listesine aktarım", html_text)
        self.assertNotIn("Bu yüzden seçildi.", html_text)
        markdown = cov.render_markdown(payload)
        self.assertNotIn("Seçilen makaleler ve fulltext listesine aktarım", markdown)

    def test_render_no_badge_when_nothing_selected(self) -> None:
        html_text = cov.render(self._payload())
        self.assertNotIn('class="badge selected"', html_text)

    def test_validate_rejects_bad_density(self) -> None:
        payload = self._payload()
        payload["coverage"]["evidence_density"] = {"total_results": -1}
        self.assertTrue(cov.validate(payload))
        payload["coverage"]["evidence_density"] = {"total_results": 1}
        self.assertEqual(cov.validate(payload), [])

    def test_render_escapes_untrusted_text(self) -> None:
        payload = self._payload()
        payload["results"][0]["title"] = '<img src=x onerror="alert(1)">'
        payload["coverage"]["evidence_density"] = {
            "high_quality_total": 1,
            "high_quality_strict_total": 0,
            "q1_total": 0,
            "q1_ratio": 0.0,
            "recent_window_years": 5,
            "recent_window_start": 2022,
            "recent_total": 0,
            "recent_ratio": 0.0,
            "randomized_controlled_trial_total": 0,
            "systematic_review_or_meta_analysis_total": 0,
            "clinical_trial_total": 0,
            "preprint_total": 0,
            "study_designs": {},
            "trend": {"window_years": 3, "years": [2024, 2025, 2026],
                      "counts": {"2024": 0, "2025": 0, "2026": 0},
                      "slope": 0.0, "direction": "belirsiz",
                      "change_ratio": None, "undated_total": 0},
        }
        html_text = cov.render(payload)
        self.assertNotIn("<img src=x", html_text)
        self.assertIn("&lt;img src=x", html_text)
        markdown = cov.render_markdown(payload)
        self.assertNotIn("<img src=x", markdown)

    def test_main_writes_json_and_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "arama.json"
            source.write_text(
                json.dumps(self._payload(), ensure_ascii=False), encoding="utf-8"
            )
            code = cov.main([str(source), "--no-timestamp"])
            self.assertEqual(code, 0)
            self.assertTrue((root / "01_arama_kapsam_raporu.json").is_file())
            self.assertTrue((root / "01_arama_kapsam_raporu.html").is_file())
            report = json.loads(
                (root / "01_arama_kapsam_raporu.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["schema"], cov.SCHEMA_ID)
            self.assertTrue(report["coverage"]["evidence_scarcity"])


class DownloaderTests(unittest.TestCase):
    def test_ascii_url_encodes_turkish_and_idn(self) -> None:
        self.assertEqual(
            oa._ascii_url("https://example.org/Şahin makale.pdf"),
            "https://example.org/%C5%9Eahin%20makale.pdf",
        )
        self.assertEqual(
            oa._ascii_url("https://example.org/a%20b.pdf"),
            "https://example.org/a%20b.pdf",
        )
        self.assertEqual(
            oa._ascii_url("https://example.org/ö?q=ğ&r=%C3%BC#bölüm"),
            "https://example.org/%C3%B6?q=%C4%9F&r=%C3%BC#b%C3%B6l%C3%BCm",
        )
        self.assertTrue(
            oa._ascii_url("https://örnek.net/x.pdf").startswith("https://xn--")
        )

    def test_forbidden_copy_falls_back_to_next_candidate(self) -> None:
        import urllib.error as urlerror

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "03_kaynak_kesfi"
            source_dir.mkdir()
            payload = {
                "project": "ornek-proje",
                "title": "Örnek",
                "query": "q",
                "candidates": [sample_candidate()],
            }
            input_path = source_dir / "01_fulltext_listesi.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            found = [
                {
                    "url": "https://publisher.example/blocked.pdf",
                    "kind": "pdf", "source": "unpaywall",
                    "license": None, "host_type": "publisher",
                },
                {
                    "url": "https://repo.example/ok.pdf",
                    "kind": "pdf", "source": "unpaywall",
                    "license": "cc-by", "host_type": "repository",
                },
            ]
            calls = []

            def fake_download(url, destination, timeout, max_bytes) -> None:
                calls.append(url)
                if "blocked" in url:
                    raise urlerror.HTTPError(url, 403, "Forbidden", {}, None)
                destination.write_bytes(b"%PDF-1.4")

            with mock.patch.object(oa, "_find_oa_candidates", return_value=(found, [])), \
                 mock.patch.object(oa, "_download_pdf", side_effect=fake_download):
                code = oa.main([
                    str(input_path), "--email", "test@example.org",
                    "--no-timestamp", "--update-json",
                ])

            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 2)
            updated = json.loads(input_path.read_text(encoding="utf-8"))
            candidate = updated["candidates"][0]
            self.assertTrue(candidate["oa_downloaded"])
            self.assertEqual(candidate["oa_pdf_url"], "https://repo.example/ok.pdf")

    def test_filename_is_doi_based_without_special_chars(self) -> None:
        self.assertEqual(
            oa._filename_for({"doi": "10.1000/xyz.123", "authors": "Yilmaz, A."}),
            "10.1000xyz.123.pdf",
        )
        self.assertEqual(
            oa._filename_for({"doi": "10.4073/csr.2011.4"}),
            "10.4073csr.2011.4.pdf",
        )
        self.assertEqual(
            oa._filename_for({"doi": "10.1080/13632752.2019.1582742"}),
            "10.108013632752.2019.1582742.pdf",
        )
        name = oa._filename_for({"doi": "10.1000/xyz.123"})
        for char in ("/", ":", "?", "*", " "):
            self.assertNotIn(char, name)

    def test_filename_falls_back_without_doi(self) -> None:
        self.assertEqual(
            oa._filename_for({"authors": "Yilmaz, A.; Demo, B.", "year": 2024}),
            "Yilmaz_2024.pdf",
        )

    def test_safe_url_rejects_private_and_non_http_hosts(self) -> None:
        self.assertIsNone(oa._safe_url("http://127.0.0.1/x.pdf"))
        self.assertIsNone(oa._safe_url("http://localhost/x.pdf"))
        self.assertIsNone(oa._safe_url("ftp://example.org/x.pdf"))
        self.assertEqual(
            oa._safe_url("https://example.org/x.pdf"),
            "https://example.org/x.pdf",
        )

    def test_email_is_read_from_project_setup_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "setup.txt").write_text(
                "email=test@example.org\n", encoding="utf-8"
            )
            args = argparse.Namespace(email=None, from_file=None, project=None)
            empty_env = {
                "UNPAYWALL_EMAIL": "",
                "CROSSREF_MAILTO": "",
                "NCBI_EMAIL": "",
            }
            with mock.patch.dict(os.environ, empty_env):
                self.assertEqual(
                    oa._resolve_email(args, root),
                    "test@example.org",
                )

    def test_project_root_and_default_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "03_kaynak_kesfi"
            source_dir.mkdir()
            input_path = source_dir / "01_fulltext_listesi.json"
            self.assertEqual(oa._project_root(input_path, None), root)
            self.assertEqual(
                oa._default_output_dir(input_path, root, None),
                root / "03_kaynak_kesfi" / "fulltext",
            )
            self.assertEqual(
                oa._default_output_dir(input_path, root, "3"),
                root / "03_kaynak_kesfi" / "fulltext",
            )
            self.assertEqual(
                oa._default_output_dir(input_path, root, "4"),
                root / "04_taslak" / "fulltext",
            )
            self.assertEqual(
                oa._default_output_dir(input_path, root, "5"),
                root / "05_analiz" / "fulltext",
            )

    def test_default_output_dir_follows_input_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_input = root / "04_taslak" / "adaylar.json"
            analysis_input = root / "05_analiz" / "adaylar.json"
            self.assertEqual(
                oa._default_output_dir(draft_input, root, None),
                root / "04_taslak" / "fulltext",
            )
            self.assertEqual(
                oa._default_output_dir(analysis_input, root, None),
                root / "05_analiz" / "fulltext",
            )

    def test_default_report_paths_follow_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                oa._default_report_path(
                    root / "03_kaynak_kesfi" / "fulltext", "20261108-120000"
                ),
                root / "03_kaynak_kesfi"
                / "oa_indirme_raporu_20261108-120000.json",
            )
            self.assertEqual(
                oa._default_report_path(
                    root / "04_taslak" / "fulltext", "20261108-120000"
                ),
                root / "04_taslak"
                / "oa_indirme_raporu_20261108-120000.json",
            )
            self.assertEqual(
                oa._default_report_path(
                    root / "05_analiz" / "fulltext", "20261108-120000"
                ),
                root / "05_analiz"
                / "oa_indirme_raporu_20261108-120000.json",
            )

    def test_mark_downloaded_sets_oa_fields(self) -> None:
        candidate = sample_candidate()
        oa._mark_downloaded(
            candidate, Path("Yilmaz_2024_10.1000_xyz.123.pdf")
        )
        self.assertTrue(candidate["oa_downloaded"])
        self.assertEqual(
            candidate["oa_local_file"], "Yilmaz_2024_10.1000_xyz.123.pdf"
        )
        oa._mark_not_downloaded(candidate)
        self.assertFalse(candidate["oa_downloaded"])
        self.assertNotIn("oa_local_file", candidate)

    def test_main_downloads_to_workflow_one_and_updates_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "03_kaynak_kesfi"
            source_dir.mkdir()
            payload = {
                "project": "ornek-proje",
                "title": "Örnek Bölüm",
                "query": "örnek sorgu",
                "candidates": [sample_candidate()],
            }
            input_path = source_dir / "01_fulltext_listesi.json"
            input_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            found = [
                {
                    "url": "https://example.org/paper.pdf",
                    "kind": "pdf",
                    "source": "unpaywall",
                    "license": "cc-by",
                    "host_type": "publisher",
                }
            ]

            def fake_download(url, destination, timeout, max_bytes) -> None:
                destination.write_bytes(b"%PDF-1.4")

            with mock.patch.object(
                oa, "_find_oa_candidates", return_value=(found, [])
            ), mock.patch.object(oa, "_download_pdf", side_effect=fake_download):
                code = oa.main(
                    [
                        str(input_path),
                        "--email",
                        "test@example.org",
                        "--no-timestamp",
                        "--update-json",
                    ]
                )

            self.assertEqual(code, 0)
            destination = (
                source_dir
                / "fulltext"
                / oa._filename_for(payload["candidates"][0])
            )
            self.assertTrue(destination.is_file())
            reports = list(source_dir.glob("oa_indirme_raporu_*.json"))
            self.assertEqual(len(reports), 1)
            self.assertFalse(
                (source_dir / "taslak").exists(),
                "İndirme raporu doğrudan akış klasöründe olmalı.",
            )
            updated = json.loads(input_path.read_text(encoding="utf-8"))
            candidate = updated["candidates"][0]
            self.assertTrue(candidate["oa_downloaded"])
            self.assertEqual(candidate["oa_local_file"], destination.name)

    def test_open_access_candidates_prefer_pdf_links(self) -> None:
        candidates = [
            {"url": "https://example.org/landing", "kind": "landing"},
            {"url": "https://example.org/paper.pdf", "kind": "pdf"},
        ]
        ordered = oa._sort_candidates(candidates)
        self.assertEqual(ordered[0]["url"], "https://example.org/paper.pdf")

    def test_pdf_link_is_extracted_from_landing_html(self) -> None:
        page = (
            '<html><head>'
            '<meta name="citation_pdf_url" content="/files/paper.pdf">'
            "</head></html>"
        )
        self.assertEqual(
            oa._extract_pdf_link(page, "https://example.org/article/1"),
            "https://example.org/files/paper.pdf",
        )


class NoDeletionTests(unittest.TestCase):
    """Üretilen dosyalar bir sonraki çalıştırmada silinmemeli."""

    def test_second_coverage_run_keeps_first_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "arama.json"
            source.write_text(
                json.dumps(
                    {
                        "project": "p",
                        "query": "q",
                        "coverage": {
                            "sources_queried": ["openalex"],
                            "per_source": {
                                "openalex": {
                                    "returned": 1,
                                    "unique_dois": 1,
                                    "high_quality": 1,
                                }
                            },
                            "total_unique_dois": 1,
                            "high_quality_total": 1,
                            "evidence_scarcity": False,
                            "query_variants": ["q"],
                            "timestamp": "2026-11-09T00:00:00+00:00",
                        },
                        "results": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertEqual(cov.main([str(source)]), 0)
            first = sorted(root.glob("01_arama_kapsam_raporu_*.json"))
            self.assertEqual(len(first), 1)
            first_bytes = first[0].read_bytes()

            # Aynı içerikle tekrar çalıştırma yeni sürüm üretmez.
            self.assertEqual(cov.main([str(source)]), 0)
            unchanged = sorted(root.glob("01_arama_kapsam_raporu_*.json"))
            self.assertEqual(
                len(unchanged), 1, "değişmeyen çıktı yeni sürüm üretmemeli"
            )
            self.assertEqual(unchanged[0].read_bytes(), first_bytes)

            # İçerik değişince yeni sürüm yazılır, eskisi arşive taşınır.
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["coverage"]["total_unique_dois"] = 99
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(cov.main([str(source)]), 0)
            after = sorted(root.glob("01_arama_kapsam_raporu_*.json"))
            self.assertEqual(len(after), 1, "klasörde tek güncel sürüm kalmalı")
            archived = sorted((root / "arsiv").glob("01_arama_kapsam_raporu_*"))
            self.assertTrue(archived, "eski sürüm arşivlenmeli")
            self.assertEqual(
                [p for p in archived if p.suffix == ".json"][0].read_bytes(),
                first_bytes,
                "arşivlenen ilk sürümün içeriği değişmemeli",
            )

    def test_second_fulltext_list_run_keeps_first_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "adaylar.json"
            source.write_text(
                json.dumps(
                    {
                        "project": "p",
                        "title": "T",
                        "query": "q",
                        "generated_at": "2026-11-09",
                        "candidates": [sample_candidate()],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            out = root / "liste.html"
            self.assertEqual(
                fl.main([str(source), "-o", str(out), "--no-timestamp"]), 0
            )

            # Aynı içerikle ikinci çalıştırma yeni sürüm üretmez.
            self.assertEqual(
                fl.main([str(source), "-o", str(out), "--no-timestamp"]), 0
            )
            self.assertEqual(len(list(root.glob("liste*.html"))), 1)
            self.assertFalse((root / "arsiv").exists())

            # İçerik değişince sabit ad --force olmadan ezilmez.
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["title"] = "T2"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(
                fl.main([str(source), "-o", str(out), "--no-timestamp"]), 2
            )
            self.assertEqual(len(list(root.glob("liste*.html"))), 1)

            # --force ile aynı ad yeniden yazılır (arşiv gerekmez).
            self.assertEqual(
                fl.main([str(source), "-o", str(out), "--no-timestamp", "--force"]), 0
            )
            self.assertIn("T2", out.read_text(encoding="utf-8"))
            self.assertEqual(len(list(root.glob("liste*.html"))), 1)

            # Zaman sonekli modda içerik değişince yeni sürüm yazılır, eskisi arşivlenir.
            source.write_text(
                json.dumps(
                    {
                        "project": "p",
                        "title": "T3",
                        "query": "q",
                        "generated_at": "2026-11-09",
                        "candidates": [sample_candidate()],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertEqual(fl.main([str(source), "-o", str(out)]), 0)
            self.assertTrue(list((root / "arsiv").glob("liste*.html")))
            self.assertEqual(len(list(root.glob("liste*.html"))), 1)

    def test_index_refuses_overwrite_without_force(self) -> None:
        import build_fulltext_index as idx

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            listing = root / "01_fulltext_listesi_20260101-000000.json"
            listing.write_text(
                json.dumps(
                    {
                        "title": "T",
                        "project": "p",
                        "candidates": [sample_candidate()],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "01_fulltext_listesi_20260101-000000.html").write_text(
                "<html></html>", encoding="utf-8"
            )
            target = root / "00_kaynak_listeleri.html"
            target.write_text("eski", encoding="utf-8")
            with mock.patch("sys.argv", ["idx", str(root), "--no-timestamp"]):
                self.assertEqual(idx.main(), 2)
            self.assertEqual(target.read_text(encoding="utf-8"), "eski")

    def test_index_second_run_adds_new_file(self) -> None:
        import build_fulltext_index as idx

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "01_fulltext_listesi_20260101-000000.json").write_text(
                json.dumps(
                    {"title": "T", "project": "p", "candidates": [sample_candidate()]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "01_fulltext_listesi_20260101-000000.html").write_text(
                "<html></html>", encoding="utf-8"
            )
            with mock.patch("sys.argv", ["idx", str(root)]):
                self.assertEqual(idx.main(), 0)
            first = sorted(root.glob("00_kaynak_listeleri_*.html"))
            self.assertEqual(len(first), 1)
            old_bytes = first[0].read_bytes()
            with mock.patch("sys.argv", ["idx", str(root)]):
                self.assertEqual(idx.main(), 0)
            after = sorted(root.glob("00_kaynak_listeleri_*.html"))
            self.assertEqual(len(after), 2)
            self.assertEqual(first[0].read_bytes(), old_bytes)


class LayoutTests(unittest.TestCase):
    """Üç kopya klasör düzeni aynı olmalı (drift koruması)."""

    def test_layout_matches_all_copies(self) -> None:
        import project_layout

        self.assertEqual(
            project_layout.WORKFLOW_DIRECTORIES,
            {
                "1": "01_konu_belirleme",
                "2": "02_yazim_plani",
                "3": "03_kaynak_kesfi",
                "4": "04_taslak",
                "5": "05_analiz",
            },
        )

        import sys
        from pathlib import Path as _Path

        repo = _Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo / "packages" / "sciencedirect-meta" / "src"))
        sys.path.insert(0, str(repo / "packages" / "paperqa-local"))
        import paperqa_mcp  # noqa: E402
        from sciencedirect_meta import layout as meta_layout  # noqa: E402

        self.assertEqual(
            meta_layout.WORKFLOW_DIRECTORIES, project_layout.WORKFLOW_DIRECTORIES
        )
        self.assertEqual(
            paperqa_mcp.WORKFLOW_DIRS, project_layout.WORKFLOW_DIRECTORIES
        )
        self.assertEqual(
            meta_layout.FULLTEXT_SUBDIR, project_layout.FULLTEXT_SUBDIR
        )

    def test_genre_list_has_no_default(self) -> None:
        import project_layout

        self.assertIn("kitap_bolumu", project_layout.GENRES)
        self.assertIn("derleme_makale", project_layout.GENRES)
        self.assertGreaterEqual(len(project_layout.GENRES), 4)


class WritingPlanTests(unittest.TestCase):
    def _plan(self) -> dict:
        return {
            "schema": "writing-plan/1",
            "project": "p",
            "title": "T",
            "genre": "uygulama_rehberi",
            "target_total_words": 1000,
            "sections": [
                {
                    "id": "S1",
                    "heading": "Disruptive behaviour prevalence",
                    "purpose": "Show how common disruptive behaviour is in classrooms.",
                    "target_words": 400,
                    "evidence_needs": [
                        {"design": "systematic_review", "min_count": 1}
                    ],
                    "assigned_dois": [],
                    "status": "planned",
                },
                {
                    "id": "S2",
                    "heading": "Teacher recognition of internalizing problems",
                    "purpose": "Explain why internalizing behaviour goes unnoticed.",
                    "target_words": 400,
                    "evidence_needs": [
                        {"design": "cross_sectional", "min_count": 1}
                    ],
                    "assigned_dois": [],
                    "status": "planned",
                },
                {
                    "id": "S3",
                    "heading": "Referral workflow",
                    "purpose": "Describe referral thresholds and handover.",
                    "target_words": 200,
                    "evidence_needs": [{"design": "any", "min_count": 1}],
                    "assigned_dois": [],
                    "status": "planned",
                },
            ],
        }

    def test_writing_plan_validates_and_renders(self) -> None:
        import build_writing_plan as wp

        plan = self._plan()
        self.assertEqual(wp.validate(plan), [])
        html_text = wp.render(plan)
        self.assertIn("S1", html_text)
        self.assertIn("Sistematik derleme", html_text)
        self.assertNotIn("<script", html_text)
        budget = wp.word_budget(plan)
        self.assertEqual(budget["planned_section_words"], 1000)
        self.assertEqual(budget["target_total_words"], 1000)

    def test_writing_plan_rejects_missing_genre(self) -> None:
        import build_writing_plan as wp

        plan = self._plan()
        plan.pop("genre")
        self.assertTrue(wp.validate(plan))

    def test_writing_plan_enforces_word_budget_tolerance(self) -> None:
        import build_writing_plan as wp

        plan = self._plan()
        # %10 tolerance: target 1000, allowed planned is 900-1100.
        # Planned is 1000, target 1050 (+5%): passes
        plan["target_total_words"] = 1050
        self.assertEqual(wp.validate(plan), [])

        # Target 1200 (planned is 1000, -16.7%): fails
        plan["target_total_words"] = 1200
        errors = wp.validate(plan)
        self.assertTrue(any("Kelime bütçesi dengesiz" in e for e in errors))

    def test_writing_plan_validates_section_id_format(self) -> None:
        import build_writing_plan as wp

        plan = self._plan()
        plan["sections"][0]["id"] = "Giris"
        errors = wp.validate(plan)
        self.assertTrue(any("geçersiz kimlik" in e for e in errors))

    def test_writing_plan_validates_plan_status(self) -> None:
        import build_writing_plan as wp

        plan = self._plan()
        plan["plan_status"] = "invalid_status"
        errors = wp.validate(plan)
        self.assertTrue(any("plan_status" in e for e in errors))

        plan["plan_status"] = "draft"
        self.assertEqual(wp.validate(plan), [])
        plan["plan_status"] = "approved"
        self.assertEqual(wp.validate(plan), [])

    def test_assignment_matches_designs(self) -> None:
        import build_assignment_matrix as am

        pool = [
            {
                "doi": "10.1000/sr.1",
                "title": "Systematic review of disruptive behaviour prevalence in classrooms",
                "abstract": "Disruptive behaviour prevalence and classroom management.",
                "quartile": "Q1",
                "citations": 100,
            },
            {
                "doi": "10.1000/cs.2",
                "title": "Teacher recognition of internalizing problems in students",
                "abstract": "Cross-sectional survey of teacher recognition of internalizing behaviour.",
                "quartile": "Q2",
                "citations": 20,
            },
            {
                "doi": "10.1000/other.3",
                "title": "Unrelated topic about school buildings",
                "abstract": "Architecture and ventilation.",
                "quartile": "Q4",
                "citations": 1,
            },
        ]
        matrix = am.assign(self._plan(), pool)
        by_id = {s["section_id"]: s for s in matrix["sections"]}
        self.assertIn("10.1000/sr.1", [e["doi"] for e in by_id["S1"]["assigned"]])
        self.assertIn("10.1000/cs.2", [e["doi"] for e in by_id["S2"]["assigned"]])
        self.assertNotIn(
            "10.1000/other.3",
            [e["doi"] for s in matrix["sections"] for e in s["assigned"]],
        )
        self.assertIn("10.1000/sr.1", matrix["assigned_dois"])

    def test_compliance_detects_missing_and_extra(self) -> None:
        import check_plan_compliance as cp

        draft = {
            "intro": {
                "paragraphs": [
                    "**Disruptive behaviour prevalence**",
                    "Disruptive behaviour is common. " * 40,
                    "**Unplanned section**",
                    "Something else entirely. " * 10,
                ]
            }
        }
        report = cp.compare(self._plan(), draft)
        self.assertEqual(report["plan_sections"], 3)
        self.assertEqual(len(report["missing_sections"]), 2)
        self.assertIn("Unplanned section", report["extra_sections"])
        self.assertEqual(report["written_sections"], 1)

    def test_compliance_matches_numbered_headings(self) -> None:
        import check_plan_compliance as cp

        plan = self._plan()
        plan["sections"][0]["heading"] = "1. Disruptive behaviour prevalence"
        draft = {
            "intro": {
                "paragraphs": [
                    "**1. Disruptive behaviour prevalence**",
                    "Text. " * 90,
                ]
            }
        }
        report = cp.compare(plan, draft)
        self.assertTrue(report["sections"][0]["written"])


if __name__ == "__main__":
    unittest.main()
