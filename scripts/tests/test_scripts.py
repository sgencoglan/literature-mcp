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
        # "Diğer" yerine gerçek yayıncı/platform adı yazılır; düğmede ek
        # nitelikler (title, priority-platform) bulunabilir.
        self.assertNotIn(">Diğer</a>", html_text)
        self.assertIn("Bilinmiyor", html_text)
        self.assertIn('class="btn pub', html_text)
        self.assertIn('href="https://example.org/article"', html_text)

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
        self.assertIn(">SpringerLink</a>", html_text)
        # Yayıncı adı düz yazı olarak tekrarlanmaz; düğme yeterlidir.
        self.assertNotIn("yayıncı: Springer Nature", html_text)

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
            meta_layout.DRAFT_SUBDIR, project_layout.DRAFT_SUBDIR
        )
        self.assertEqual(
            meta_layout.DRAFT_WORKFLOWS, project_layout.DRAFT_WORKFLOWS
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


class PublisherLookupTests(unittest.TestCase):
    """Yayıncı adı "Diğer" değil gerçek kaynak olarak gösterilmeli."""

    def test_doi_prefix_resolves_sage(self) -> None:
        from publisher_lookup import resolve

        self.assertEqual(resolve("10.1177/0198742916688656")[0], "SAGE")
        # AERA bir dernektir; makaleleri SAGE üzerinde yayımlanır.
        self.assertEqual(resolve("10.3102/00346543211051428")[0], "AERA")

    def test_button_shows_database_not_society(self) -> None:
        from publisher_lookup import display_label, publisher_note

        # Düğme veritabanını göstermeli: AERA değil SAGE.
        self.assertEqual(display_label("10.3102/00346543211051428"), "SAGE")
        self.assertEqual(publisher_note("10.3102/00346543211051428"), "AERA")
        self.assertEqual(display_label("10.1037/edu0000641"), "APA PsycNet")
        self.assertEqual(publisher_note("10.1037/edu0000641"), "APA")

    def test_platform_covers_non_priority_publishers(self) -> None:
        from publisher_lookup import platform_for

        self.assertEqual(platform_for("10.1353/etc.2019.0021"), "Project MUSE")
        self.assertEqual(platform_for("10.1093/x"), "Oxford Academic")
        self.assertIsNone(platform_for("10.99999/x"))

    def test_taylor_francis_is_resolved(self) -> None:
        from publisher_lookup import resolve

        self.assertEqual(resolve("10.1080/10409289.2019.1594531")[0], "Taylor & Francis")
        self.assertEqual(
            resolve("10.1080/10409289.2019.1594531")[2], "Taylor & Francis"
        )

    def test_priority_platform_only_for_the_five(self) -> None:
        from publisher_lookup import resolve

        self.assertEqual(resolve("10.1016/j.jsp.2022.04.002")[2], "ScienceDirect")
        self.assertEqual(resolve("10.1007/s10639-021-10795-7")[2], "SpringerLink")
        self.assertIsNone(resolve("10.1177/0198742916688656")[2])
        self.assertIsNone(resolve("10.1037/edu0000641")[2])

    def test_metadata_name_wins_over_prefix(self) -> None:
        from publisher_lookup import resolve

        name, _url, priority = resolve("10.9999/x", "SAGE Publications")
        self.assertEqual(name, "SAGE")
        self.assertIsNone(priority)

    def test_unknown_does_not_say_diger(self) -> None:
        from publisher_lookup import resolve

        name, _url, _priority = resolve("10.99999/none", None)
        self.assertEqual(name, "Bilinmiyor")
        self.assertNotEqual(name, "Diğer")

    def test_html_button_shows_real_publisher(self) -> None:
        import build_fulltext_list as fl

        rows = fl.render_rows(
            [
                {
                    "doi": "10.1177/0198742916688656",
                    "title": "T",
                    "authors": "A",
                    "year": 2024,
                    "journal": "J",
                    "publisher": "Diğer",  # eski/eksik değer
                    "priority": "A",
                    "rationale": "R",
                    "project_relevance": "P",
                    "supports": ["s"],
                    "does_not_support": ["n"],
                    "limits": ["l"],
                    "assessment_basis": "abstract",
                }
            ]
        )
        self.assertIn("SAGE", rows)
        self.assertNotIn(">Diğer<", rows)


class DoiNamingTests(unittest.TestCase):
    """HTML'de gösterilen PDF adı, indiricinin ürettiği adla birebir aynı olmalı."""

    def test_strips_special_characters(self) -> None:
        from doi_naming import doi_filename

        self.assertEqual(doi_filename("10.4073/csr.2011.4"), "10.4073csr.2011.4")
        self.assertEqual(doi_filename("10.1007/s10639-021-10795-7"), "10.1007s10639-021-10795-7")
        self.assertNotIn("/", doi_filename("10.1016/j.jsp.2022.04.002"))

    def test_pdf_suffix_and_fallback(self) -> None:
        from doi_naming import doi_filename, doi_pdf_filename

        self.assertTrue(doi_pdf_filename("10.1177/0198742916688656").endswith(".pdf"))
        self.assertEqual(doi_filename(""), "doi-yok")

    def test_downloader_uses_the_shared_rule(self) -> None:
        import download_open_access as oa
        from doi_naming import doi_pdf_filename

        for doi in ("10.4073/csr.2011.4", "10.3102/00346543211051428", "10.1016/j.tate.2021.103349"):
            self.assertEqual(oa._filename_for({"doi": doi}), doi_pdf_filename(doi))

    def test_html_has_filename_copy_button(self) -> None:
        import build_fulltext_list as fl

        rows = fl.render_rows(
            [
                {
                    "doi": "10.1007/s10639-021-10795-7",
                    "title": "T",
                    "authors": "A",
                    "year": 2024,
                    "journal": "J",
                    "publisher": "SpringerLink",
                    "priority": "A",
                    "rationale": "R",
                    "project_relevance": "P",
                    "supports": ["s"],
                    "does_not_support": ["n"],
                    "limits": ["l"],
                    "assessment_basis": "abstract",
                }
            ]
        )
        # Değer görünmez, düğme veri olarak taşır.
        self.assertIn('class="btn file"', rows)
        self.assertIn('data-filename="10.1007s10639-021-10795-7"', rows)
        self.assertNotIn(">10.1007s10639-021-10795-7<", rows)
        self.assertNotIn("10.1007s10639-021-10795-7.pdf", rows)

    def test_detection_finds_the_downloader_filename(self) -> None:
        import build_fulltext_list as fl

        keys = fl.doi_filename_keys("10.1007/s10639-021-10795-7")
        self.assertIn("10.1007s10639-021-10795-7", keys)


class EvidenceGapRequestTests(unittest.TestCase):
    """Kanıt eksikliği ile plan değişikliği ayrımı korunmalı."""

    def _plan(self, **section_overrides):
        section = {
            "id": "S1",
            "heading": "Kriz Öncesi",
            "target_words": 1000,
            "evidence_needs": [{"design": "cross_sectional", "min_count": 1}],
            "assigned_dois": ["10.1/a", "10.1/b"],
            "search_terms": ["screening", "referral", "teacher"],
        }
        section.update(section_overrides)
        return {"project": "p", "title": "T", "plan_status": "approved",
                "target_total_words": 1000, "sections": [section]}

    def test_evidence_shortfall_does_not_require_user_decision(self) -> None:
        from build_evidence_gap_request import preflight

        report = preflight(self._plan(), fulltext_list={"candidates": []},
                           available_pdfs={"10.1a", "10.1b"})
        gap = report["gaps"][0]
        self.assertEqual(gap["status"], "evidence_shortfall")
        self.assertFalse(gap["needs_user_decision"])
        self.assertTrue(gap["suggested_queries"])

    def test_no_assignment_is_plan_change(self) -> None:
        from build_evidence_gap_request import preflight

        report = preflight(self._plan(assigned_dois=[]), fulltext_list={"candidates": []})
        self.assertEqual(report["gaps"][0]["status"], "plan_change_required")
        self.assertTrue(report["gaps"][0]["needs_user_decision"])

    def test_single_source_for_long_section_is_plan_change(self) -> None:
        from build_evidence_gap_request import preflight

        plan = self._plan(target_words=1500, assigned_dois=["10.1/a"])
        report = preflight(plan, fulltext_list={"candidates": []},
                           available_pdfs={"10.1a"})
        self.assertEqual(report["gaps"][0]["status"], "plan_change_required")

    def test_missing_pdf_is_flagged(self) -> None:
        from build_evidence_gap_request import preflight

        report = preflight(self._plan(), fulltext_list={"candidates": []},
                           available_pdfs=set())
        gap = report["gaps"][0]
        self.assertEqual(gap["missing_pdf_count"], 2)
        self.assertEqual(gap["status"], "evidence_shortfall")

    def test_well_supported_section_produces_no_gap(self) -> None:
        from build_evidence_gap_request import preflight

        dois = [f"10.1234/study.{i}" for i in range(4)]
        plan = self._plan(
            target_words=600,
            assigned_dois=dois,
            evidence_needs=[{"design": "any", "min_count": 1}],
        )
        from build_evidence_gap_request import _pdf_stem

        report = preflight(
            plan,
            fulltext_list={"candidates": [
                {"doi": doi, "title": "randomized trial", "abstract": ""}
                for doi in dois
            ]},
            available_pdfs={_pdf_stem(doi) for doi in dois},
        )
        self.assertEqual(report["gaps"], [])

    def test_summary_counts_both_categories(self) -> None:
        from build_evidence_gap_request import preflight

        plan = self._plan()
        plan["sections"].append(
            {
                "id": "S2",
                "heading": "Kriz Sonrası",
                "target_words": 900,
                "evidence_needs": [{"design": "any", "min_count": 1}],
                "assigned_dois": [],
                "search_terms": ["reentry"],
            }
        )
        report = preflight(plan, fulltext_list={"candidates": []},
                           available_pdfs={"10.1a", "10.1b"})
        self.assertEqual(report["summary"]["gap_sections"], 2)
        self.assertEqual(report["summary"]["plan_change_required"], 1)
        self.assertEqual(report["summary"]["evidence_shortfall"], 1)
        self.assertEqual(report["mode"], "preflight")


class EvidenceBankTests(unittest.TestCase):
    def test_pdf_filename_matches_downloader_rule(self) -> None:
        from build_evidence_bank import pdf_filename
        from doi_naming import doi_pdf_filename

        for doi in ("10.1007/s10639-021-10795-7", "10.3102/00346543211051428"):
            self.assertEqual(pdf_filename(doi), doi_pdf_filename(doi))

    def test_section_terms_prefers_explicit_search_terms(self) -> None:
        from build_evidence_bank import section_terms

        self.assertEqual(
            section_terms({"heading": "Kriz Öncesi", "search_terms": ["screening", "referral"]}),
            ["screening", "referral"],
        )

    def test_section_terms_falls_back_to_heading_keywords(self) -> None:
        from build_evidence_bank import section_terms

        terms = section_terms({"heading": "Kriz Sonrası: İzleme"})
        self.assertIn("reintegration", terms)

    def test_design_detection(self) -> None:
        from build_evidence_bank import detect_design

        self.assertEqual(detect_design("A meta-analysis of X", ""), "meta_analysis")
        self.assertEqual(detect_design("A randomized trial", ""), "rct")
        self.assertEqual(detect_design("Qualitative interviews", ""), "qualitative")
        self.assertEqual(detect_design("Something else", ""), "any")

    def test_sentence_filtering_skips_short_and_long(self) -> None:
        from build_evidence_bank import split_sentences

        long_sentence = "This is far too long. " * 40 + "End."
        text = (
            "Short one. "
            "This sentence is long enough to be a candidate because it carries "
            "context about screening and referral practices in schools. "
            + long_sentence
        )
        picked = split_sentences(text)
        self.assertTrue(all(60 <= len(s) <= 420 for s in picked))
        self.assertTrue(any("screening" in s for s in picked))


class ConceptCoverageTests(unittest.TestCase):
    """Anchor terim zinciri: sözlük -> külliyat -> seçim."""

    def _plan(self, anchors=None, terms=None):
        return {
            "project": "p",
            "title": "T",
            "anchor_terms": anchors if anchors is not None else ["de-escalation"],
            "sections": [
                {
                    "id": "S1",
                    "heading": "Kriz Anı",
                    "search_terms": terms if terms is not None else ["de-escalation", "crisis"],
                }
            ],
        }

    def test_missing_anchor_terms_fails(self) -> None:
        from check_concept_coverage import analyse

        report = analyse(self._plan(anchors=[]))
        self.assertFalse(report["ok"])
        self.assertTrue(any("anchor_terms" in f for f in report["failures"]))

    def test_anchor_not_in_search_terms_fails(self) -> None:
        from check_concept_coverage import analyse

        report = analyse(self._plan(terms=["classroom management", "screening"]))
        self.assertFalse(report["ok"])
        self.assertEqual(report["dictionary"]["missing_from_search_terms"], ["de-escalation"])

    def test_anchor_in_search_terms_passes_dictionary(self) -> None:
        from check_concept_coverage import analyse

        report = analyse(self._plan())
        self.assertTrue(report["dictionary"]["ok"])

    def test_spelling_variants_are_matched(self) -> None:
        from check_concept_coverage import _variant_pattern

        for text in ("de-escalation", "deescalation", "de escalation", "De-Escalation"):
            self.assertTrue(_variant_pattern("de-escalation").search(text), text)

    def test_pool_record_with_anchor_must_be_assigned_or_rejected(self) -> None:
        from check_concept_coverage import analyse

        pool = {
            "records": [
                {"doi": "10.1/loaded", "title": "Loaded moments toward escalation or de-escalation"},
                {"doi": "10.1/other", "title": "Something unrelated"},
            ]
        }
        report = analyse(self._plan(), pool=pool, assigned={"10.1/loaded"})
        self.assertTrue(report["selection"]["ok"])
        self.assertEqual(len(report["selection"]["matches"]), 1)

        report2 = analyse(self._plan(), pool=pool, assigned=set())
        self.assertFalse(report2["selection"]["ok"])
        dropped = report2["selection"]["dropped_without_reason"]
        self.assertEqual([row["doi"] for row in dropped], ["10.1/loaded"])

    def test_rejection_reason_clears_selection_gap(self) -> None:
        from check_concept_coverage import analyse

        pool = {"records": [{"doi": "10.1/loaded", "title": "de-escalation in schools"}]}
        report = analyse(
            self._plan(), pool=pool, assigned=set(),
            rejections={"10.1/loaded": "örneklem uygun değil"},
        )
        self.assertTrue(report["selection"]["ok"])

    def test_corpus_check_is_skipped_without_pdfs(self) -> None:
        from check_concept_coverage import analyse

        report = analyse(self._plan())
        self.assertIsNone(report["corpus"]["ok"])

    def test_cli_exit_code_reflects_failure(self) -> None:
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        plugin = Path("scripts/check_concept_coverage.py").resolve()
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(
                '{"project":"p","title":"T","anchor_terms":["de-escalation"],'
                '"sections":[{"id":"S1","heading":"H","search_terms":["disruptive behavior"]}]}',
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(plugin), str(plan), "--check"],
                capture_output=True, text=True,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("KALDI", proc.stdout)


if __name__ == "__main__":
    unittest.main()
