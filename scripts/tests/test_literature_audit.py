import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from build_literature_audit import load_records, main, parse_ris
from concept_framework import build_framework
from literature_audit import build_audit, normalize_doi, render_audit


def framework():
    return build_framework(
        [
            {
                "id": "C1",
                "term": "Örnek kavram",
                "english_terms": ["example construct"],
                "synonyms": ["alternative construct"],
                "role": "anchor",
            }
        ]
    )


def audit(baseline=None, additional=None, known=None, searches=None):
    return build_audit(baseline or [], additional or [], known or [], framework(), searches)


class AuditTests(unittest.TestCase):
    def test_doi_normalization_handles_url_case_and_encoding(self):
        self.assertEqual(normalize_doi("HTTPS://DOI.ORG/10.1000%2FFixture"), "10.1000/fixture")
        self.assertEqual(normalize_doi("doi: 10.1000/Fixture"), "10.1000/fixture")
        self.assertEqual(normalize_doi("not-a-doi"), "")

    def test_new_known_and_duplicate_records_are_separate(self):
        result = audit(
            [{"doi": "10.1000/old", "title": "Old"}],
            [{"doi": "https://doi.org/10.1000/OLD"}, {"doi": "10.1000/new", "title": "New"}],
            [{"doi": "10.1000/new"}],
        )
        self.assertEqual(result["summary"]["new_candidates"], 1)
        self.assertEqual(result["summary"]["already_present"], 1)
        self.assertEqual(result["summary"]["known_confirmed"], 1)
        self.assertEqual(result["known_items"][0]["baseline_match"]["status"], "not_found")

    def test_title_only_match_is_review_not_confirmed_recovery(self):
        result = audit(
            [{"title": "A study: of behavior", "doi": "10.1000/first", "year": 2020}],
            [{"title": "A Study of Behavior", "doi": "10.1000/second", "year": 2024}],
            [{"title": "A Study of Behavior"}],
        )
        self.assertEqual(result["comparison"][0]["classification"], "possible_duplicate")
        self.assertEqual(result["summary"]["known_confirmed"], 0)
        self.assertEqual(result["known_items"][0]["combined_match"]["status"], "title_candidate")

    def test_identifier_conflicts_are_not_silently_merged(self):
        result = audit(
            [{"doi": "10.1000/first", "pmid": "123"}],
            [{"doi": "10.1000/second", "pmid": "123"}],
        )
        self.assertEqual(result["comparison"][0]["classification"], "identifier_conflict")
        self.assertEqual(result["summary"]["review_required"], 1)

    def test_new_identifiers_in_duplicate_record_are_retained(self):
        result = audit(
            [{"pmid": "123"}],
            [{"doi": "10.1000/new-id", "pmid": "123"}],
            [{"doi": "10.1000/new-id"}],
        )
        self.assertEqual(result["summary"]["known_confirmed"], 1)
        self.assertEqual(result["summary"]["new_candidates"], 0)

    def test_duplicate_additions_are_not_counted_as_multiple_new_candidates(self):
        result = audit(additional=[{"doi": "10.1000/new"}, {"doi": "10.1000/new"}])
        self.assertEqual(result["summary"]["new_candidates"], 1)

    def test_no_benchmarks_does_not_become_perfect_recovery(self):
        result = audit()
        self.assertIsNone(result["summary"]["known_item_recovery"])
        self.assertEqual(result["completeness"], "not_established")

    def test_source_tags_and_generated_links_do_not_mark_database_searched(self):
        result = audit(additional=[{"title": "Fixture", "source": "psycinfo"}])
        self.assertTrue(all(r["status"] == "not_run" for r in result["source_priorities"]))
        self.assertFalse(result["search_log"])

    def test_failed_query_is_not_hidden_by_success_for_same_source(self):
        result = audit(
            searches=[
                {"source": "pubmed", "query": "a", "status": "error"},
                {"source": "pubmed", "query": "b", "status": "ok", "searched_at": "2026-01-01"},
            ]
        )
        source = next(r for r in result["source_priorities"] if r["source"] == "pubmed")
        self.assertEqual(source["status"], "partial")
        self.assertEqual(len(result["search_log"]), 2)

    def test_success_requires_query_and_time(self):
        with self.assertRaises(ValueError):
            audit(searches=[{"source": "scholar", "status": "ok"}])

    def test_concept_checks_english_terms_and_synonyms_as_lexical_matches(self):
        result = audit(additional=[{"title": "Alternative construct research"}])
        coverage = result["concept_coverage"][0]
        self.assertEqual(coverage["additional_ids"], ["additional-1"])
        self.assertEqual(coverage["evidence_status"], "not_assessed")

    def test_purpose_changes_source_priorities(self):
        result = build_audit([], [], [], framework(), domain="medical", purpose="intervention")
        self.assertEqual(result["source_priorities"][0]["source"], "central")
        self.assertIn("clinicaltrials", [r["source"] for r in result["source_priorities"]])

    def test_gap_candidates_are_prioritized_without_claiming_quality(self):
        result = audit(additional=[{"title": "Example construct", "doi": "10.1000/fixture"}])
        triage = result["comparison"][0]["triage"]
        self.assertEqual(triage["priority"], 1)
        self.assertEqual(triage["quality_status"], "not_assessed")

    def test_marked_retraction_is_flagged_even_if_known_item(self):
        record = {"doi": "10.1000/fixture", "is_retracted": True}
        result = audit(additional=[record], known=[record])
        self.assertEqual(result["comparison"][0]["triage"]["priority"], 3)

    def test_audit_matches_schema(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(
            (
                Path(__file__).resolve().parents[2] / "schemas/literature-audit.schema.json"
            ).read_text()
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(audit(additional=[{"doi": "10.1000/fixture"}]))

    def test_broad_scholar_search_exists_alongside_publisher_queries(self):
        queries = framework()["search_plan"]
        broad = [
            q for q in queries if q["database"] == "scholar" and q.get("priority") == "primary"
        ]
        self.assertTrue(broad)
        self.assertNotIn("site:", broad[0]["query"])
        self.assertIn("alternative construct", broad[0]["query"])

    def test_untrusted_html_is_escaped(self):
        result = audit(additional=[{"title": "<script>alert(1)</script>"}])
        page = render_audit(result)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_ris_multiple_records_and_continuation_lines(self):
        text = "\ufeffTY  - JOUR\nTI  - First title\nDO  - 10.1000/one\nAB  - First line\n   second line\nPY  - 2024/01/01\nER  -\nTY  - CHAP\nT1  - Book chapter\nER  -"
        records = parse_ris(text)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["abstract"], "First line second line")
        self.assertEqual(records[0]["year"], "2024")
        self.assertEqual(records[1]["publication_type"], "CHAP")

    def test_empty_ris_and_bad_csv_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_ris("not ris")
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "bad.csv"
            file.write_text("other\nvalue\n")
            with self.assertRaises(ValueError):
                load_records(file)

    def test_cli_imports_ris_and_preserves_previous_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "framework.json").write_text(json.dumps(framework()))
            (root / "baseline.json").write_text('{"records": []}')
            (root / "new.ris").write_text(
                "TY  - JOUR\nTI  - Example construct\nDO  - 10.1000/fixture\nER  -\n"
            )
            args = [
                "--framework",
                str(root / "framework.json"),
                "--baseline",
                str(root / "baseline.json"),
                "--additional",
                str(root / "new.ris"),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 0)
            reports = list(root.glob("02_kaynak_kapsam_denetimi_*.json"))
            self.assertEqual(len(reports), 2)
            self.assertTrue(all(p.with_suffix(".html").exists() for p in reports))
            result = json.loads(reports[0].read_text())
            self.assertEqual(result["summary"]["new_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
