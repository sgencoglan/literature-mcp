import json
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz
from build_evidence_gap_request import preflight
from fulltext_reading import apply_reviews, prepare_reading, reading_advice, reading_gate
from search_progress import progress_rows, render_search_progress


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdfs = self.root / "fulltext"
        self.pdfs.mkdir()
        pdf = fitz.open()
        pdf.new_page().insert_text((40, 40), "Synthetic novel construct on page one.")
        page = pdf.new_page()
        page.insert_text((40, 40), "Synthetic second page with a figure.")
        page.draw_rect(fitz.Rect(50, 60, 100, 100))
        pdf.save(self.pdfs / "fixture.pdf")
        pdf.close()
        self.manifest = prepare_reading(self.pdfs, self.root / "pages", "4")

    def reviews(self):
        doc = self.manifest["documents"][0]
        return [
            {
                "document_id": doc["document_id"],
                "page": p["page"],
                "mode": "text_and_visual",
                "text_sha256": p["text_sha256"],
                "image_sha256": p["image_sha256"],
                "summary": f"Synthetic page {p['page']} reviewed.",
                "terms": ["novel construct"],
                "sections": ["S1"],
            }
            for p in doc["pages"]
        ]

    def test_every_page_is_extracted_with_images_but_not_called_read(self):
        pages = self.manifest["documents"][0]["pages"]
        self.assertEqual(len(pages), 2)
        self.assertTrue(all((self.root / "pages" / p["image_file"]).exists() for p in pages))
        self.assertFalse(reading_gate(self.manifest, self.pdfs, "4")["complete"])
        self.assertTrue(pages[1]["requires_visual"])

    def test_all_page_reviews_are_required_and_wrong_stage_is_blocked(self):
        partial = apply_reviews(self.manifest, self.reviews()[:1])
        self.assertFalse(reading_gate(partial, self.pdfs, "4")["complete"])
        complete = apply_reviews(partial, self.reviews()[1:])
        self.assertTrue(reading_gate(complete, self.pdfs, "4")["complete"])
        self.assertFalse(reading_gate(complete, self.pdfs, "5")["complete"])
        self.assertFalse(reading_gate(complete)["complete"])

    def test_stale_page_hash_and_text_only_figure_review_are_rejected(self):
        reviews = self.reviews()
        reviews[0]["text_sha256"] = "stale"
        with self.assertRaises(ValueError):
            apply_reviews(self.manifest, reviews)
        reviews = self.reviews()[1:]
        reviews[0]["mode"] = "text"
        with self.assertRaises(ValueError):
            apply_reviews(self.manifest, reviews)

    def test_adding_or_changing_pdf_invalidates_gate(self):
        complete = apply_reviews(self.manifest, self.reviews())
        (self.pdfs / "another.pdf").write_bytes((self.pdfs / "fixture.pdf").read_bytes())
        self.assertFalse(reading_gate(complete, self.pdfs, "4")["complete"])

    def test_changed_pdf_content_invalidates_existing_reviews(self):
        complete = apply_reviews(self.manifest, self.reviews())
        pdf = fitz.open()
        pdf.new_page().insert_text((40, 40), "Changed document contents.")
        pdf.save(self.pdfs / "fixture.pdf")
        pdf.close()
        self.assertFalse(reading_gate(complete, self.pdfs, "4")["complete"])

    def test_generated_reading_reports_match_schema(self):
        from jsonschema import Draft202012Validator

        schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/fulltext-reading.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.manifest)
        Draft202012Validator(schema).validate(apply_reviews(self.manifest, self.reviews()))

    def test_duplicate_file_contents_share_review_without_losing_pages(self):
        (self.pdfs / "duplicate.pdf").write_bytes((self.pdfs / "fixture.pdf").read_bytes())
        self.manifest = prepare_reading(self.pdfs, self.root / "pages", "4")
        complete = apply_reviews(self.manifest, self.reviews())
        gate = reading_gate(complete, self.pdfs, "4")
        self.assertTrue(gate["complete"])
        self.assertEqual(gate["reviewed_pages"], 4)

    def test_corrupt_pdf_is_reported_and_never_skipped_as_complete(self):
        (self.pdfs / "broken.pdf").write_bytes(b"not a pdf")
        manifest = prepare_reading(self.pdfs, self.root / "pages", "4")
        self.assertTrue(any(d["status"] == "error" for d in manifest["documents"]))
        self.assertFalse(reading_gate(manifest, self.pdfs, "4")["complete"])

    def test_terms_have_page_provenance_and_article_needs_do_not_invent_titles(self):
        manifest = apply_reviews(self.manifest, self.reviews())
        plan = {
            "sections": [
                {
                    "id": "S1",
                    "heading": "Fixture",
                    "search_terms": ["old term"],
                    "evidence_needs": [{"design": "any", "min_count": 2}],
                }
            ]
        }
        advice = reading_advice(manifest, plan)
        self.assertEqual(advice["new_term_candidates"][0]["term"], "novel construct")
        self.assertEqual(len(advice["new_term_candidates"][0]["source_pages"]), 2)
        self.assertEqual(len(advice["new_article_needs"]), 1)
        self.assertEqual(advice["actual_new_publications"], [])

    def test_preflight_blocks_without_reading_even_if_plan_has_no_capacity_gap(self):
        plan = {"plan_status": "approved", "sections": []}
        self.assertFalse(preflight(plan)["transition_allowed"])
        manifest = apply_reviews(self.manifest, self.reviews())
        result = preflight(plan, reading_manifest=manifest, fulltext_root=self.pdfs, workflow="4")
        self.assertTrue(result["transition_allowed"])


class ProgressTests(unittest.TestCase):
    def test_missing_report_is_not_marked_success(self):
        self.assertIn("eklenmedi", render_search_progress({}))

    def test_zero_results_error_and_not_run_are_distinct(self):
        data = {
            "search_reports": [
                {
                    "kind": "coverage",
                    "payload": {
                        "per_source": {
                            "pubmed": {"status": "ok", "returned": 0},
                            "crossref": {"status": "error", "error": "HTTP 500 api_key=secret"},
                            "embase": {"status": "not_run"},
                            "openalex": {"status": "rate_limited", "retry_after_seconds": 120},
                        }
                    },
                }
            ]
        }
        page = render_search_progress(data)
        for text in ("Sorgu başarılı", "Henüz aranmadı", "Hız sınırı", "120 saniye", "HTTP 500"):
            self.assertIn(text, page)
        self.assertNotIn("secret", page)
        self.assertIn("eş anlamlıları", page)

    def test_shared_panel_is_rendered_in_workflows_one_two_three(self):
        from build_fulltext_list import build_html
        from build_topic_discovery import render as render_topic
        from build_writing_plan import render as render_plan

        root = Path(__file__).resolve().parents[2] / "examples"
        for filename, render in (
            ("fulltext-list.example.json", build_html),
            ("topic-discovery.example.json", render_topic),
            ("writing-plan.example.json", render_plan),
        ):
            data = json.loads((root / filename).read_text())
            data["search_reports"] = [
                {
                    "kind": "coverage",
                    "payload": {
                        "per_source": {
                            "fixture-source": {"status": "error", "error": "Fixture failure"}
                        }
                    },
                }
            ]
            page = render(data)
            self.assertIn("fixture-source", page)
            self.assertIn("Fixture failure", page)


if __name__ == "__main__":
    unittest.main()
