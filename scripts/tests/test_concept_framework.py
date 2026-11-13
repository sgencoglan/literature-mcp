"""Kavramların ve ilişkilerin kaynak var diye yanlış doğrulanmasını önle."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import build_concept_map as cm
from concept_framework import build_framework, render_framework


def corpus():
    return [
        {
            "id": f"fixture-{i}",
            "title": f"Response inhibition experiment {i}",
            "abstract": "Response inhibition varies. Environmental cues modify response inhibition.",
        }
        for i in range(6)
    ]


class FrameworkTests(unittest.TestCase):
    def test_single_word_terms_are_kept_without_cross_sentence_phrases(self):
        terms = cm._candidate_grams("Inhibition varies. Environmental cues differ.")
        self.assertIn("inhibition", terms)
        self.assertNotIn("varies environmental", terms)

    def test_occurrence_has_identity_and_passage_but_is_not_a_definition(self):
        mined = cm.mine_candidates("fixture", corpus=corpus())
        row = next(r for r in mined["candidates"] if r["term"] == "response inhibition")
        self.assertIsNone(row["specificity"])
        self.assertEqual(row["validation_status"], "proposed")
        self.assertEqual(row["evidence"][0]["source_id"], "fixture-0")
        concepts = cm.concepts_from_seed(
            {"concepts": [{"term": row["term"], "evidence": row["evidence"]}]}
        )
        node = build_framework(concepts)["nodes"][0]
        self.assertTrue(node["observed_in_sources"])
        self.assertEqual(node["status"], "proposed")
        self.assertEqual(node["proposed_definition"]["status"], "missing")

    def test_duplicate_records_do_not_inflate_support(self):
        works = corpus()
        mined = cm.mine_candidates("fixture", corpus=works + works)
        self.assertEqual(mined["sample_size"], 6)
        self.assertEqual(mined["candidates"][0]["documents"], 6)

    def test_error_is_distinct_from_zero_results(self):
        with patch.object(cm, "_fetch_corpus", side_effect=RuntimeError("fixture")):
            failed = cm.mine_candidates("fixture")
        with patch.object(cm, "_fetch_corpus", return_value=[]):
            empty = cm.mine_candidates("fixture")
        self.assertEqual(failed["coverage"]["target"]["status"], "error")
        self.assertEqual(empty["coverage"]["target"]["status"], "ok")
        self.assertTrue(failed["errors"])

    def test_related_mesh_is_not_used_as_synonym_or_query_expansion(self):
        concept = cm.concepts_from_seed({"concepts": ["response inhibition"]})[0]
        original = concept["english_terms"][:]
        cm.attach_mesh(
            [concept],
            {
                "response inhibition": {
                    "found": True,
                    "mesh_terms": [{"term": "Unrelated descriptor", "count": 8, "pmids": ["1"]}],
                }
            },
        )
        self.assertEqual(concept["english_terms"], original)
        self.assertEqual(concept["mesh"], [])
        self.assertEqual(concept["related_mesh"][0]["relation"], "co_occurrence")
        self.assertNotIn(
            "Unrelated descriptor", json.dumps(build_framework([concept])["search_plan"])
        )

    def test_mesh_requires_exact_match_and_preserves_scope(self):
        concept = cm.concepts_from_seed({"concepts": ["fixture"]})[0]
        cm.attach_vocabulary(concept, {"entries": [{"term": "wrong", "match_type": "contains"}]})
        self.assertFalse(concept["mesh"])
        cm.attach_vocabulary(
            concept,
            {
                "entries": [
                    {
                        "term": "Fixture",
                        "match_type": "exact_label",
                        "scope_note": "Vocabulary definition.",
                        "uri": "https://id.nlm.nih.gov/mesh/D000000",
                    }
                ]
            },
        )
        framework = build_framework([concept])
        self.assertEqual(
            framework["nodes"][0]["vocabulary_definitions"][0]["text"], "Vocabulary definition."
        )
        self.assertIn('"Fixture"[MeSH Terms]', framework["search_plan"][0]["query"])
        self.assertEqual(framework["nodes"][0]["status"], "proposed")

    def test_relations_and_external_definitions_are_never_auto_approved(self):
        concepts = cm.concepts_from_seed(
            {
                "concepts": [
                    {
                        "term": "alpha",
                        "definition": {"text": "A definition", "status": "verified"},
                        "relations": [{"target": "C2", "type": "causes", "status": "verified"}],
                    },
                    "beta",
                ]
            }
        )
        framework = build_framework(concepts)
        self.assertEqual(framework["relations"][0]["status"], "proposed")
        self.assertEqual(framework["nodes"][0]["proposed_definition"]["status"], "proposed")

    def test_search_urls_round_trip_and_each_domain_has_site_operator(self):
        framework = build_framework(cm.concepts_from_seed({"concepts": ["alpha & beta"]}))
        for query in framework["search_plan"]:
            parameters = parse_qs(urlparse(query["url"]).query)
            self.assertEqual(parameters.get("q", parameters.get("term"))[0], query["query"])
            self.assertEqual(query["status"], "not_run")
            if query["database"] == "scholar":
                if query.get("priority") == "supplementary":
                    self.assertTrue(query["query"].startswith("site:"))
                else:
                    self.assertNotIn("site:", query["query"])

    def test_scope_does_not_invent_concepts_or_relations(self):
        framework = build_framework([], {"context": "fixture setting"})
        self.assertFalse(framework["nodes"])
        self.assertFalse(framework["relations"])
        self.assertNotIn("Ortam ve bağlam", framework["missing_dimensions"])

    def test_framework_matches_schema(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(
            (
                Path(__file__).resolve().parents[2] / "schemas/concept-framework.schema.json"
            ).read_text()
        )
        Draft202012Validator.check_schema(schema)
        framework = build_framework(cm.concepts_from_seed({"concepts": ["fixture"]}))
        Draft202012Validator(schema).validate(framework)

    def test_html_escapes_external_passages_and_links(self):
        concept = cm.concepts_from_seed(
            {
                "concepts": [
                    {
                        "term": "<script>bad</script>",
                        "evidence": [
                            {
                                "source_id": "javascript:bad",
                                "title": "<img src=x>",
                                "passage": "<script>bad</script>",
                            }
                        ],
                    }
                ]
            }
        )
        rendered = render_framework(build_framework(concept))
        self.assertNotIn("<script>", rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_explicit_seed_replaces_previous_and_phase_two_retains_framework(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.json"
            seed.write_text(
                json.dumps(
                    {"domain": "medical", "scope": {"context": "fixture"}, "concepts": ["alpha"]}
                )
            )
            args = [str(root), "--concept-seed", str(seed)]
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                cm.main(args)
                seed.write_text(json.dumps({"domain": "medical", "concepts": ["beta"]}))
                cm.main(args)
                cm.main([str(root), "--phase", "2"])
            reports = list((root / "01_konu_belirleme").glob("02_kavram_haritasi_*.json"))
            latest = next(
                r for r in (json.loads(p.read_text()) for p in reports) if r["phase"] == 2
            )
            self.assertEqual(latest["concepts"][0]["term"], "beta")
            self.assertEqual(latest["domain"], "medical")
            self.assertEqual(latest["phase"], 2)
            self.assertEqual(latest["framework"]["scope"], {})
            self.assertGreaterEqual(len(reports), 3)

    def test_offline_corpus_never_fetches_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.json"
            path.write_text(json.dumps({"records": corpus()}))
            with (
                patch.object(cm, "_fetch_corpus", side_effect=AssertionError("network")),
                patch.object(cm, "_fetch_pubmed_corpus", side_effect=AssertionError("network")),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    cm.main([tmp, "--title", "fixture", "--corpus", str(path), "--check"]), 0
                )


if __name__ == "__main__":
    unittest.main()
