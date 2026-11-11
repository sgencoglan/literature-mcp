"""Offline tests for the additional metadata sources and coverage ranking."""

from __future__ import annotations

import asyncio
import math
import os
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from sciencedirect_meta import sources


def _semantic_raw() -> dict:
    return {
        "paperId": "abc123",
        "title": "A randomized controlled trial of teacher training",
        "abstract": (
            "This randomized controlled trial examined teacher training and "
            "student behaviour in secondary schools."
        ),
        "year": 2024,
        "venue": "Journal of Education",
        "journal": {"name": "Journal of Education"},
        "authors": [{"name": "A. Yilmaz"}, {"name": "B. Demo"}],
        "externalIds": {"DOI": "10.1000/xyz.123", "PubMed": "12345"},
        "citationCount": 120,
        "influentialCitationCount": 12,
        "isOpenAccess": True,
        "openAccessPdf": {"url": "https://example.org/paper.pdf"},
        "url": "https://www.semanticscholar.org/paper/abc123",
        "publicationTypes": ["JournalArticle"],
    }


def _write_setup(path: Path, text: str) -> Path:
    """Write a setup.txt that passes the permission hardening."""
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


ARXIV_XML = """<feed xmlns="http://www.w3.org/2005/Atom"
  xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Preprint on language models</title>
    <summary>We study language models and their evaluation.</summary>
    <published>2024-01-02T00:00:00Z</published>
    <updated>2024-02-03T00:00:00Z</updated>
    <author><name>A. Author</name></author>
    <link href="http://arxiv.org/abs/2401.00001v1" rel="alternate"/>
    <link href="http://arxiv.org/pdf/2401.00001v1" title="pdf"
          type="application/pdf"/>
    <arxiv:primary_category term="cs.CL"/>
    <category term="cs.CL"/>
    <category term="cs.AI"/>
  </entry>
</feed>
"""


def _clinicaltrial_raw() -> dict:
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000001",
                "briefTitle": "Trial of an intervention",
            },
            "statusModule": {
                "overallStatus": "Completed",
                "startDateStruct": {"date": "2023-05"},
            },
            "descriptionModule": {"briefSummary": "A randomized trial."},
            "designModule": {
                "studyType": "Interventional",
                "phases": ["PHASE2"],
            },
            "conditionsModule": {"conditions": ["Asthma"]},
            "armsInterventionsModule": {
                "interventions": [{"type": "DRUG", "name": "Drug A"}]
            },
        }
    }


class SemanticScholarParsingTests(unittest.TestCase):
    def test_normalizes_required_fields(self) -> None:
        paper = sources._semantic_scholar_paper(_semantic_raw())
        self.assertEqual(paper["doi"], "10.1000/xyz.123")
        self.assertEqual(paper["pmid"], "12345")
        self.assertEqual(paper["source"], "semantic_scholar")
        self.assertEqual(paper["semantic_scholar_id"], "abc123")
        self.assertEqual(paper["influential_citations"], 12)
        self.assertEqual(paper["cited_by"], 120)
        self.assertTrue(paper["open_access"])
        self.assertEqual(paper["pdf_url"], "https://example.org/paper.pdf")
        self.assertEqual(paper["journal"], "Journal of Education")
        self.assertEqual(paper["authors"], ["A. Yilmaz", "B. Demo"])
        self.assertFalse(paper.get("is_preprint"))
        self.assertIn("semantic_scholar", paper["sources"])

    def test_arxiv_external_id_marks_preprint(self) -> None:
        raw = _semantic_raw()
        raw["externalIds"] = {"ArXiv": "2401.00001", "DOI": ""}
        paper = sources._semantic_scholar_paper(raw)
        self.assertTrue(paper["is_preprint"])
        self.assertEqual(paper["arxiv_id"], "2401.00001")
        self.assertIsNone(paper["doi"])


class ArxivParsingTests(unittest.TestCase):
    def test_parses_entry_fields(self) -> None:
        entry = ET.fromstring(ARXIV_XML).find(
            "{http://www.w3.org/2005/Atom}entry"
        )
        paper = sources._arxiv_paper(entry)
        self.assertEqual(paper["arxiv_id"], "2401.00001v1")
        self.assertEqual(paper["year"], 2024)
        self.assertTrue(paper["is_preprint"])
        self.assertEqual(paper["source"], "arxiv")
        self.assertEqual(paper["primary_category"], "cs.CL")
        self.assertEqual(paper["categories"], ["cs.CL", "cs.AI"])
        self.assertEqual(paper["pdf_url"], "http://arxiv.org/pdf/2401.00001v1")
        self.assertEqual(paper["abs_url"], "http://arxiv.org/abs/2401.00001v1")
        self.assertEqual(paper["published"], "2024-01-02T00:00:00Z")
        self.assertEqual(paper["updated"], "2024-02-03T00:00:00Z")


class ClinicalTrialsParsingTests(unittest.TestCase):
    def test_parses_study(self) -> None:
        study = sources._clinicaltrial_study(_clinicaltrial_raw())
        self.assertEqual(study["nct_id"], "NCT00000001")
        self.assertEqual(study["year"], 2023)
        self.assertEqual(study["study_type"], "Interventional")
        self.assertEqual(study["conditions"], ["Asthma"])
        self.assertEqual(study["interventions"], ["Drug A"])
        self.assertEqual(study["source"], "clinicaltrials")
        self.assertFalse(study["is_preprint"])
        self.assertIn("NCT00000001", study["clinicaltrials_url"])

    def test_ignores_study_without_id_or_title(self) -> None:
        self.assertIsNone(sources._clinicaltrial_study({"protocolSection": {}}))


class ScoringTests(unittest.TestCase):
    def _item(self, **overrides) -> dict:
        item = {
            "title": "Teacher training and student behaviour",
            "abstract": "A randomized controlled trial of teacher training.",
            "year": 2024,
            "journal": "Journal of Education",
            "cited_by": 120,
            "type": "article",
        }
        item.update(overrides)
        return item

    def test_formula_components_and_high_quality(self) -> None:
        item = sources.score_result(
            self._item(quartile="Q1"),
            "teacher training student behaviour",
            now_year=2026,
        )
        components = item["score_components"]
        expected = (
            0.35 * components["semantic_relevance"]
            + 0.25 * components["citation"]
            + 0.15 * components["recency"]
            + 0.15 * components["journal_quartile"]
            + 0.10 * components["study_type"]
        )
        self.assertAlmostEqual(item["score"], round(expected, 4))
        self.assertEqual(components["journal_quartile"], 1.0)
        self.assertEqual(components["study_type"], 1.0)
        self.assertEqual(item["study_design"], "Randomized controlled trial")
        self.assertTrue(item["high_quality"])

    def test_preprint_penalty_and_flag(self) -> None:
        item = sources.score_result(
            self._item(is_preprint=True, source="arxiv", type="preprint"),
            "teacher training student behaviour",
            now_year=2026,
        )
        self.assertEqual(item["study_design"], "Preprint")
        self.assertFalse(item["high_quality"])
        base = sources.score_result(
            self._item(quartile="Q1"),
            "teacher training student behaviour",
            now_year=2026,
        )
        self.assertLess(item["score"], base["score"])

    def test_unknown_year_and_quartile(self) -> None:
        item = sources.score_result(
            self._item(year=None, quartile=None),
            "teacher training",
            now_year=2026,
        )
        self.assertEqual(item["score_components"]["recency"], 0.15)
        self.assertEqual(item["score_components"]["journal_quartile"], 0.30)

    def test_citation_score_is_log_scaled(self) -> None:
        self.assertAlmostEqual(
            sources._citation_score(0), 0.0
        )
        self.assertAlmostEqual(
            sources._citation_score(9999), round(math.log10(10000) / 4.0, 4)
        )


class CoverageTests(unittest.TestCase):
    def _items(self, count: int, high: bool = True) -> list:
        return [
            {
                "doi": f"10.1000/item.{index}",
                "title": f"Item {index}",
                "score": 0.8 if high else 0.2,
                "high_quality": high,
            }
            for index in range(count)
        ]

    def test_run_source_success_and_error(self) -> None:
        async def ok():
            return [{"title": "x"}]

        async def boom():
            raise RuntimeError("network down")

        async def main():
            good = await sources.run_source("openalex", ok(), requested_limit=5)
            bad = await sources.run_source("pubmed", boom(), requested_limit=5)
            return good, bad

        good, bad = asyncio.run(main())
        self.assertEqual(good["status"], "ok")
        self.assertEqual(good["requested_limit"], 5)
        self.assertIsInstance(good["duration_ms"], int)
        self.assertEqual(good["note"], sources.DEFAULT_SOURCE_NOTES["openalex"])
        self.assertEqual(bad["status"], "error")
        self.assertIn("network down", bad["error"])
        self.assertEqual(bad["items"], [])

    def test_run_source_marks_rate_limit(self) -> None:
        async def empty():
            return []

        original = sources._S2_COOLDOWN_UNTIL
        sources._S2_COOLDOWN_UNTIL = float("inf")
        try:
            result = asyncio.run(
                sources.run_source(
                    "semantic_scholar",
                    empty(),
                    requested_limit=10,
                    rate_limited_when_empty=True,
                )
            )
        finally:
            sources._S2_COOLDOWN_UNTIL = original
        self.assertEqual(result["status"], "rate_limited")
        self.assertTrue(result["rate_limited"])

    def test_score_results_best_uses_matching_facet_query(self) -> None:
        item = {
            "title": "Teacher classroom management practices: effects on disruptive student behavior",
            "abstract": "Systematic review of teacher classroom management on disruptive behaviour.",
            "journal": "Campbell Systematic Reviews",
            "year": 2011,
            "cited_by": 302,
            "quartile": "Q1",
            "type": "review",
        }
        sources.score_results_best(
            [item],
            [
                "Eğitimciler İçin Rehber: Sınıfta Riskli Davranışları Tanıma ve Yönlendirme",
                "classroom disruptive behaviour teacher identification referral intervention",
            ],
        )
        self.assertEqual(
            item["scored_query"],
            "classroom disruptive behaviour teacher identification referral intervention",
        )
        self.assertGreater(item["score"], sources.HIGH_QUALITY_SCORE)
        self.assertTrue(item["high_quality"])

    def test_score_results_best_does_not_mutate_with_empty_queries(self) -> None:
        item = {"title": "x", "year": 2024}
        result = sources.score_results_best([item], [])
        self.assertNotIn("score", result[0])

    def test_publisher_distribution(self) -> None:
        items = [
            {"publisher_source": "sciencedirect", "open_access": True, "pdf_url": "x"},
            {"publisher_source": "wiley", "open_access": False},
            {"publisher_url": "https://example.org", "open_access": None},
            {"is_preprint": True},
        ]
        dist = sources.build_publisher_distribution(items)
        self.assertEqual(dist["total"], 4)
        self.assertEqual(dist["counts"]["sciencedirect"], 1)
        self.assertEqual(dist["counts"]["wiley"], 1)
        self.assertEqual(dist["counts"]["other"], 1)
        self.assertEqual(dist["counts"]["unknown"], 1)
        self.assertEqual(dist["open_access_total"], 1)
        self.assertAlmostEqual(dist["open_access_ratio"], 0.25)
        self.assertEqual(dist["preprint_total"], 1)
        self.assertEqual(dist["pdf_link_total"], 1)

    def test_evidence_density_trend_direction(self) -> None:
        def item(year):
            return {"title": f"t{year}", "year": year, "study_design": "Cohort study"}

        rising = sources.build_evidence_density(
            [item(2024)] * 2 + [item(2025)] * 4 + [item(2026)] * 6,
            now_year=2026,
        )
        self.assertEqual(rising["trend"]["direction"], "artıyor")
        self.assertEqual(rising["trend"]["counts"]["2026"], 6)
        falling = sources.build_evidence_density(
            [item(2024)] * 6 + [item(2025)] * 3 + [item(2026)] * 1,
            now_year=2026,
        )
        self.assertEqual(falling["trend"]["direction"], "azalıyor")
        flat = sources.build_evidence_density(
            [item(2024)] * 2 + [item(2025)] * 2 + [item(2026)] * 2,
            now_year=2026,
        )
        self.assertEqual(flat["trend"]["direction"], "sabit")
        empty = sources.build_evidence_density([], now_year=2026)
        self.assertEqual(empty["trend"]["direction"], "belirsiz")

    def test_evidence_density_strict_high_quality(self) -> None:
        items = [
            {
                "title": "Q1 RCT cited",
                "year": 2025,
                "quartile": "Q1",
                "cited_by": 40,
                "study_design": "Randomized controlled trial",
            },
            {
                "title": "Q1 RCT low citations",
                "year": 2025,
                "quartile": "Q1",
                "cited_by": 2,
                "study_design": "Randomized controlled trial",
            },
            {
                "title": "Q3 review",
                "year": 2025,
                "quartile": "Q3",
                "cited_by": 100,
                "study_design": "Systematic review / meta-analysis",
            },
            {
                "title": "Q2 cohort",
                "year": 2025,
                "quartile": "Q2",
                "cited_by": 50,
                "study_design": "Cohort study",
            },
        ]
        density = sources.build_evidence_density(items, now_year=2026)
        self.assertEqual(density["high_quality_strict_total"], 1)
        self.assertAlmostEqual(density["high_quality_strict_ratio"], 0.25)
        self.assertIn("Q1/Q2", density["high_quality_strict_rule"])

    def test_merge_coverage_marks_partial_when_some_facets_fail(self) -> None:
        left = sources.build_coverage(
            {"openalex": self._items(2)}, self._items(2)
        )
        right = sources.build_coverage({"openalex": []}, [])
        right["per_source"]["openalex"]["status"] = "error"
        right["per_source"]["openalex"]["error"] = "429"
        merged = sources.merge_coverage([left, right], self._items(2))
        stats = merged["per_source"]["openalex"]
        self.assertEqual(stats["status"], "partial")
        self.assertEqual(stats["returned"], 2)
        self.assertTrue(
            any("bazı sorgularda" in value for value in merged["warnings"])
        )

    def test_source_warnings(self) -> None:
        warnings = sources.source_warnings(
            {
                "pubmed": {"status": "error", "error": "boom"},
                "semantic_scholar": {"status": "rate_limited"},
                "openalex": {"status": "ok"},
            },
            [{"source": "arxiv", "reason": "include_arxiv=false"}],
        )
        self.assertTrue(any("pubmed" in value and "hata" in value for value in warnings))
        self.assertTrue(any("semantic_scholar" in value and "hız limiti" in value for value in warnings))
        self.assertTrue(any("arxiv" in value and "sorgulanmadı" in value for value in warnings))
        self.assertFalse(any("openalex" in value for value in warnings))

    def test_per_source_counts_and_scarcity(self) -> None:
        high = self._items(3)
        low = self._items(2, high=False)
        low[0]["doi"] = None
        low[1]["doi"] = "10.1000/item.9"
        coverage = sources.build_coverage(
            {"openalex": high, "arxiv": low},
            high + low,
            query_variants=["q1", "q2"],
            timestamp="2026-11-08T00:00:00+00:00",
        )
        self.assertEqual(coverage["sources_queried"], ["openalex", "arxiv"])
        self.assertEqual(coverage["per_source"]["openalex"]["returned"], 3)
        self.assertEqual(coverage["per_source"]["openalex"]["unique_dois"], 3)
        self.assertEqual(coverage["per_source"]["openalex"]["high_quality"], 3)
        self.assertEqual(coverage["per_source"]["arxiv"]["unique_dois"], 1)
        self.assertEqual(coverage["total_unique_dois"], 4)
        self.assertEqual(coverage["high_quality_total"], 3)
        self.assertTrue(coverage["evidence_scarcity"])
        self.assertIn("yüksek kaliteli kanıt sınırlı", coverage["evidence_scarcity_message"])
        self.assertEqual(coverage["query_variants"], ["q1", "q2"])
        self.assertEqual(coverage["timestamp"], "2026-11-08T00:00:00+00:00")

    def test_no_scarcity_when_enough_high_quality(self) -> None:
        items = self._items(5)
        coverage = sources.build_coverage({"openalex": items}, items)
        self.assertFalse(coverage["evidence_scarcity"])
        self.assertIsNone(coverage["evidence_scarcity_message"])

    def test_merge_coverage_sums_counts(self) -> None:
        first = sources.build_coverage(
            {"openalex": self._items(2)}, self._items(2)
        )
        second = sources.build_coverage(
            {"openalex": self._items(1)}, self._items(1)
        )
        merged = sources.merge_coverage(
            [first, second], self._items(3), query_variants=["facet"]
        )
        self.assertEqual(merged["per_source"]["openalex"]["returned"], 3)
        self.assertEqual(merged["per_source"]["openalex"]["unique_dois"], 3)
        self.assertEqual(merged["high_quality_total"], 3)

    def test_query_expansion_from_variants(self) -> None:
        expansion = sources.normalize_query_expansion(
            "ADHD okul performansı müdahale",
            ["ADHD school performance intervention", "ADHD academic achievement"],
        )
        self.assertEqual(expansion["original"], "ADHD okul performansı müdahale")
        self.assertEqual(
            expansion["expanded"],
            ["ADHD school performance intervention", "ADHD academic achievement"],
        )
        self.assertEqual(expansion["transformations"], ["synonym"])
        self.assertTrue(expansion["notes"])

    def test_query_expansion_explicit_record(self) -> None:
        expansion = sources.normalize_query_expansion(
            "ADHD okul performansı müdahale",
            expansion={
                "expanded": ["ADHD school performance intervention"],
                "mesh": ["Attention Deficit Disorder with Hyperactivity[Mesh]"],
                "languages": ["Türkçe → İngilizce"],
                "transformations": ["synonym", "MeSH", "language"],
                "notes": ["MeSH PubMed için kullanıldı."],
            },
        )
        self.assertEqual(expansion["mesh"], ["Attention Deficit Disorder with Hyperactivity[Mesh]"])
        self.assertEqual(expansion["languages"], ["Türkçe → İngilizce"])
        self.assertEqual(expansion["transformations"], ["synonym", "MeSH", "language"])
        self.assertEqual(expansion["notes"], ["MeSH PubMed için kullanıldı."])

    def test_evidence_density_counts(self) -> None:
        items = [
            {
                "title": "RCT",
                "year": 2025,
                "quartile": "Q1",
                "study_design": "Randomized controlled trial",
                "high_quality": True,
            },
            {
                "title": "Review",
                "year": 2019,
                "quartile": "Q2",
                "study_design": "Systematic review / meta-analysis",
                "high_quality": True,
            },
            {
                "title": "Preprint",
                "year": 2024,
                "quartile": None,
                "study_design": "Preprint",
                "high_quality": False,
            },
        ]
        density = sources.build_evidence_density(items, now_year=2026)
        self.assertEqual(density["total_results"], 3)
        self.assertEqual(density["high_quality_total"], 2)
        self.assertEqual(density["q1_total"], 1)
        self.assertAlmostEqual(density["q1_ratio"], round(1 / 3, 4))
        self.assertEqual(density["recent_window_start"], 2022)
        self.assertEqual(density["recent_total"], 2)
        self.assertAlmostEqual(density["recent_ratio"], round(2 / 3, 4))
        self.assertEqual(density["randomized_controlled_trial_total"], 1)
        self.assertEqual(density["systematic_review_or_meta_analysis_total"], 1)
        self.assertEqual(density["preprint_total"], 1)

    def test_scarcity_message_lists_five_closest_studies(self) -> None:
        items = self._items(6, high=False)
        for index, item in enumerate(items):
            item["year"] = 2020 + index
            item["study_design"] = "Cross-sectional study"
        coverage = sources.build_coverage(
            {"openalex": items},
            items,
            original_query="örnek",
            query_variants=["örnek"],
        )
        self.assertTrue(coverage["evidence_scarcity"])
        self.assertEqual(len(coverage["closest_studies"]), 5)
        self.assertIn("Araştırma boşluğu olasılığı yüksektir", coverage["evidence_scarcity_message"])
        self.assertIn("En yakın 5 çalışma", coverage["evidence_scarcity_message"])
        self.assertIn("query_expansion", coverage)
        self.assertIn("evidence_density", coverage)


class ServerCoverageTests(unittest.TestCase):
    """End-to-end shape of search_all coverage with mocked sources."""

    def _paper(self, source: str, doi: str, title: str) -> dict:
        from sciencedirect_meta import server

        return server._paper(
            title=title,
            authors=["A"],
            year=2024,
            journal="J",
            doi=doi,
            abstract="randomized controlled trial",
            cited_by=20,
            source=source,
            type="article",
        )

    def test_search_all_reports_status_skipped_and_warnings(self) -> None:
        from unittest import mock

        from sciencedirect_meta import local_research, pipeline, server

        async def ok_openalex(*args, **kwargs):
            return [self._paper("openalex", "10.1/a", "A")]

        async def failing_pubmed(*args, **kwargs):
            raise RuntimeError("pubmed down")

        async def empty(*args, **kwargs):
            return []

        async def main():
            with mock.patch.object(pipeline, "search_openalex", ok_openalex), \
                 mock.patch.object(pipeline, "search_pubmed", failing_pubmed), \
                 mock.patch.object(pipeline, "search_europepmc", empty), \
                 mock.patch.object(sources, "search_semantic_scholar", empty), \
                 mock.patch.object(sources, "search_arxiv", empty), \
                 mock.patch.object(sources, "search_clinicaltrials", empty), \
                 mock.patch.object(local_research, "search_crossref", empty), \
                 mock.patch.object(pipeline, "enrich_sciencedirect_links", mock.AsyncMock()), \
                 mock.patch.object(pipeline, "_attach_quartiles_best_effort", lambda items: None):
                full = await server.search_all("q", limit=5)
                narrow = await server.search_all("q", limit=5, sources=["openalex"])
                return full, narrow

        payload, narrow = asyncio.run(main())
        coverage = payload["coverage"]
        self.assertEqual(payload["sources"]["pubmed"], "error")
        self.assertEqual(coverage["per_source"]["pubmed"]["status"], "error")
        self.assertIn("pubmed down", coverage["per_source"]["pubmed"]["error"])
        self.assertEqual(coverage["per_source"]["openalex"]["status"], "ok")
        self.assertEqual(coverage["per_source"]["openalex"]["requested_limit"], 5)
        # Defaults query every available source, including Crossref.
        self.assertEqual(
            set(payload["sources_requested"]),
            {"openalex", "semantic_scholar", "pubmed", "europepmc", "crossref",
             "arxiv", "clinicaltrials"},
        )
        self.assertEqual(payload["coverage"]["skipped_sources"], [])
        skipped = {entry["source"] for entry in narrow["coverage"]["skipped_sources"]}
        self.assertIn("arxiv", skipped)
        self.assertIn("clinicaltrials", skipped)
        self.assertIn("crossref", skipped)
        self.assertTrue(any("pubmed" in value for value in coverage["warnings"]))
        self.assertIn("publisher_distribution", coverage)
        self.assertIn("trend", coverage["evidence_density"])

    def test_search_all_marks_rate_limited_semantic_scholar(self) -> None:
        from unittest import mock

        from sciencedirect_meta import local_research, pipeline, server

        async def ok(*args, **kwargs):
            return [self._paper("openalex", "10.1/a", "A")]

        async def empty(*args, **kwargs):
            return []

        original = sources._S2_COOLDOWN_UNTIL
        sources._S2_COOLDOWN_UNTIL = float("inf")
        try:
            async def main():
                with mock.patch.object(pipeline, "search_openalex", ok), \
                     mock.patch.object(pipeline, "search_pubmed", empty), \
                     mock.patch.object(pipeline, "search_europepmc", empty), \
                     mock.patch.object(sources, "search_semantic_scholar", empty), \
                     mock.patch.object(sources, "search_arxiv", empty), \
                     mock.patch.object(sources, "search_clinicaltrials", empty), \
                     mock.patch.object(local_research, "search_crossref", empty), \
                     mock.patch.object(pipeline, "enrich_sciencedirect_links", mock.AsyncMock()), \
                 mock.patch.object(pipeline, "_attach_quartiles_best_effort", lambda items: None):
                    return await server.search_all("q", limit=5)
            payload = asyncio.run(main())
        finally:
            sources._S2_COOLDOWN_UNTIL = original
        stats = payload["coverage"]["per_source"]["semantic_scholar"]
        self.assertEqual(stats["status"], "rate_limited")
        self.assertTrue(stats["rate_limited"])
        self.assertTrue(
            any("semantic_scholar" in value and "hız limiti" in value
                for value in payload["coverage"]["warnings"])
        )


    def test_redacts_semantic_scholar_key(self) -> None:
        from sciencedirect_meta import server

        original = server.SEMANTIC_SCHOLAR_API_KEY
        server.SEMANTIC_SCHOLAR_API_KEY = "test-s2-key"
        try:
            text = server.redact_secrets("failed with key=test-s2-key")
        finally:
            server.SEMANTIC_SCHOLAR_API_KEY = original
        self.assertNotIn("test-s2-key", text)
        self.assertIn("<redacted>", text)


class BootstrapTests(unittest.TestCase):
    def test_parse_setup_file_maps_known_keys(self) -> None:
        from sciencedirect_meta import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.txt"
            _write_setup(
                path,
                "# yorum\n"
                "email=a@example.org\n"
                "openalex_key=oa\n"
                "pubmed_key=pm\n"
                "semantic_scholar_key=s2k-test\n"
                "random_key=ignored\n",
            )
            values = bootstrap.parse_setup_file(path)
        self.assertEqual(values["email"], "a@example.org")
        self.assertEqual(values["OPENALEX_API_KEY"], "oa")
        self.assertEqual(values["PUBMED_API_KEY"], "pm")
        self.assertEqual(values["SEMANTIC_SCHOLAR_API_KEY"], "s2k-test")
        self.assertNotIn("ignored", values)

    def test_load_does_not_override_existing_env(self) -> None:
        from sciencedirect_meta import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.txt"
            _write_setup(
                path, "semantic_scholar_key=from-file\nopenalex_key=oa-file\n"
            )
            with mock.patch.dict(
                os.environ,
                {"SEMANTIC_SCHOLAR_API_KEY": "from-env", "OPENALEX_API_KEY": ""},
                clear=False,
            ):
                status = bootstrap.load(path)
                self.assertEqual(os.environ["SEMANTIC_SCHOLAR_API_KEY"], "from-env")
                self.assertEqual(os.environ["OPENALEX_API_KEY"], "oa-file")
        self.assertIn("SEMANTIC_SCHOLAR_API_KEY", status["skipped"])

    def test_load_for_project_overrides_previous_setup_values(self) -> None:
        from sciencedirect_meta import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a"
            first.mkdir()
            _write_setup(
                first / "setup.txt",
                "openalex_key=first\nemail=first@example.org\n",
            )
            second = root / "b"
            second.mkdir()
            _write_setup(
                second / "setup.txt", "openalex_key=second\npubmed_key=pm-second\n"
            )
            with mock.patch.dict(
                os.environ,
                {"OPENALEX_API_KEY": "", "PUBMED_API_KEY": "", "CROSSREF_MAILTO": ""},
                clear=False,
            ):
                bootstrap.load(first / "setup.txt")
                self.assertEqual(os.environ["OPENALEX_API_KEY"], "first")
                status = bootstrap.load_for_project(second)
                self.assertEqual(os.environ["OPENALEX_API_KEY"], "second")
                self.assertEqual(os.environ["PUBMED_API_KEY"], "pm-second")
                self.assertIn(str(second / "setup.txt"), status["path"])

    def test_load_for_project_keeps_explicit_environment(self) -> None:
        from sciencedirect_meta import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_setup(root / "setup.txt", "openalex_key=from-file\n")
            with mock.patch.dict(
                os.environ, {"OPENALEX_API_KEY": "explicit-env"}, clear=False
            ):
                bootstrap.BOOTSTRAP_KEYS.discard("OPENALEX_API_KEY")
                bootstrap.load_for_project(root)
                self.assertEqual(os.environ["OPENALEX_API_KEY"], "explicit-env")

    def test_load_for_project_drops_keys_missing_from_new_file(self) -> None:
        from sciencedirect_meta import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "a"
            first.mkdir()
            _write_setup(
                first / "setup.txt", "openalex_key=oa-first\npubmed_key=pm-first\n"
            )
            second = root / "b"
            second.mkdir()
            _write_setup(second / "setup.txt", "openalex_key=oa-second\n")
            with mock.patch.dict(
                os.environ, {"OPENALEX_API_KEY": "", "PUBMED_API_KEY": ""}, clear=False
            ):
                bootstrap.load(first / "setup.txt")
                self.assertEqual(os.environ["PUBMED_API_KEY"], "pm-first")
                bootstrap.load_for_project(second)
                self.assertEqual(os.environ["OPENALEX_API_KEY"], "oa-second")
                self.assertNotIn("PUBMED_API_KEY", os.environ)

    def test_insecure_setup_is_not_loaded(self) -> None:
        from sciencedirect_meta import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.txt"
            path.write_text("openalex_key=leaky\n", encoding="utf-8")
            path.chmod(0o644)
            with mock.patch.dict(
                os.environ, {"OPENALEX_API_KEY": ""}, clear=False
            ), mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(bootstrap.ALLOW_INSECURE_ENV, None)
                status = bootstrap.load(path)
                self.assertTrue(status["insecure"])
                self.assertEqual(os.environ["OPENALEX_API_KEY"], "")
                self.assertEqual(status["loaded"], [])

    def test_insecure_setup_can_be_allowed_explicitly(self) -> None:
        from sciencedirect_meta import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.txt"
            path.write_text("openalex_key=leaky\n", encoding="utf-8")
            path.chmod(0o644)
            with mock.patch.dict(
                os.environ,
                {"OPENALEX_API_KEY": "", bootstrap.ALLOW_INSECURE_ENV: "1"},
                clear=False,
            ):
                status = bootstrap.load(path)
                self.assertTrue(status["insecure"])
                self.assertEqual(os.environ["OPENALEX_API_KEY"], "leaky")

    def test_candidate_paths_prefers_explicit_file(self) -> None:
        from sciencedirect_meta import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            explicit = Path(tmp) / "custom.txt"
            _write_setup(explicit, "email=a@example.org\n")
            with mock.patch.dict(
                os.environ, {"LIT_SETUP_FILE": str(explicit)}, clear=False
            ):
                self.assertEqual(bootstrap.find_setup_file(), explicit)

    def test_semantic_scholar_calls_are_serialised(self) -> None:
        async def main():
            sources._S2_LAST_CALL = 0.0
            started = time.monotonic()
            await asyncio.gather(
                sources._s2_wait_turn(),
                sources._s2_wait_turn(),
                sources._s2_wait_turn(),
            )
            return time.monotonic() - started

        elapsed = asyncio.run(main())
        self.assertGreaterEqual(elapsed, sources._S2_MIN_INTERVAL * 2)


class PipelineTests(unittest.TestCase):
    """search_all and search_literature must stay behaviourally identical."""

    def _paper(self, source: str, doi: str | None, title: str, year: int = 2024) -> dict:
        from sciencedirect_meta import server

        return server._paper(
            title=title,
            authors=["Ada Lovelace"],
            year=year,
            journal="J",
            doi=doi,
            abstract="randomized controlled trial",
            cited_by=10,
            source=source,
            type="article",
        )

    def test_both_search_tools_query_the_same_sources(self) -> None:
        from sciencedirect_meta import local_research, pipeline, server

        async def fake(*args, **kwargs):
            return [self._paper("openalex", "10.1/x", "Same title")]

        async def main():
            with mock.patch.object(pipeline, "search_openalex", fake), \
                 mock.patch.object(pipeline, "search_pubmed", fake), \
                 mock.patch.object(pipeline, "search_europepmc", fake), \
                 mock.patch.object(pipeline.extra_sources, "search_semantic_scholar", fake), \
                 mock.patch.object(pipeline.extra_sources, "search_arxiv", fake), \
                 mock.patch.object(pipeline.extra_sources, "search_clinicaltrials", fake), \
                 mock.patch.object(local_research, "search_crossref", fake), \
                 mock.patch.object(pipeline, "enrich_sciencedirect_links", mock.AsyncMock()), \
                 mock.patch.object(pipeline, "_attach_quartiles_best_effort", lambda items: None):
                return (
                    await server.search_all("q", limit=5),
                    await local_research.search_literature("q", limit=5),
                )

        all_payload, lit_payload = asyncio.run(main())
        self.assertEqual(all_payload["sources_requested"], lit_payload["sources_requested"])
        self.assertEqual(all_payload["sources_status"], lit_payload["sources_status"])
        self.assertEqual(all_payload["count"], lit_payload["count"])
        self.assertEqual(
            [(item["doi"], item["title"]) for item in all_payload["results"]],
            [(item["doi"], item["title"]) for item in lit_payload["results"]],
        )
        self.assertEqual(set(all_payload["sources_status"]), set(pipeline.AVAILABLE_SOURCES))

    def test_dedupe_key_separates_same_title_different_year(self) -> None:
        from sciencedirect_meta import server

        first = self._paper("openalex", None, "Editorial note", year=2019)
        second = self._paper("pubmed", None, "Editorial note", year=2024)
        self.assertNotEqual(server._dedupe_key(first), server._dedupe_key(second))

    def test_dedupe_key_skips_untitled_records(self) -> None:
        from sciencedirect_meta import server

        self.assertEqual(server._dedupe_key(server._paper(title=None)), "")

    def test_first_author_token_handles_both_name_orders(self) -> None:
        from sciencedirect_meta import server

        comma = server._paper(title="T", authors=["Lovelace, Ada"])
        plain = server._paper(title="T", authors=["Ada Lovelace"])
        self.assertEqual(server._first_author_token(comma), "lovelace")
        self.assertEqual(server._first_author_token(plain), "lovelace")

    def test_merge_keeps_richer_year_and_journal(self) -> None:
        from sciencedirect_meta import server

        target = server._paper(title="T", doi="10.1/a", year=None, journal=None)
        server._merge(target, server._paper(title="T", doi="10.1/a", year=2021, journal="J2"))
        self.assertEqual(target["year"], 2021)
        self.assertEqual(target["journal"], "J2")


class RatePolicyTests(unittest.TestCase):
    def test_interval_for_prefers_the_keyed_quota(self) -> None:
        from sciencedirect_meta import rate_limit

        self.assertGreater(
            rate_limit.interval_for("api.openalex.org"),
            rate_limit.interval_for("api.openalex.org", has_key=True),
        )
        self.assertEqual(
            rate_limit.interval_for("export.arxiv.org"),
            rate_limit.interval_for("export.arxiv.org", has_key=True),
        )

    def test_unknown_host_falls_back_to_default(self) -> None:
        from sciencedirect_meta import rate_limit

        self.assertEqual(rate_limit.interval_for("example.org"), rate_limit.DEFAULT_INTERVAL)

    def test_retry_after_header_is_honoured_but_capped(self) -> None:
        from sciencedirect_meta import rate_limit

        self.assertEqual(rate_limit.retry_after_seconds("3", 0), 3.0)
        self.assertEqual(rate_limit.retry_after_seconds("999", 0), rate_limit.MAX_RETRY_AFTER)
        self.assertLessEqual(
            rate_limit.retry_after_seconds("999", 0, "export.arxiv.org"), 5.0
        )

    def test_backoff_grows_and_stays_capped(self) -> None:
        from sciencedirect_meta import rate_limit

        first = rate_limit.retry_after_seconds(None, 0)
        second = rate_limit.retry_after_seconds(None, 1)
        self.assertLess(first, second)
        self.assertLessEqual(rate_limit.retry_after_seconds(None, 99), rate_limit.MAX_RETRY_AFTER)

    def test_server_uses_the_shared_table(self) -> None:
        from sciencedirect_meta import rate_limit, server

        self.assertIs(server._RATE_INTERVALS, rate_limit.RATE_INTERVALS)
        self.assertEqual(server.RATE_LIMIT_COOLDOWN_SECONDS, rate_limit.COOLDOWN_SECONDS)


class RateLimitTests(unittest.TestCase):
    def tearDown(self) -> None:
        from sciencedirect_meta import server

        server._HOST_COOLDOWN_UNTIL.clear()
        sources._SOURCE_COOLDOWN.clear()

    def test_polite_get_raises_rate_limited_after_retries(self) -> None:
        from sciencedirect_meta import server

        response = mock.Mock(status_code=429, headers={"Retry-After": "0"})
        fake_get = mock.AsyncMock(return_value=response)
        fake_client = mock.Mock()
        fake_client.get = fake_get
        with mock.patch.object(server, "client_for_loop", lambda: fake_client):
            with self.assertRaises(server.RateLimitedError):
                asyncio.run(
                    server.polite_get("https://api.openalex.org/works", attempts=2)
                )
        self.assertEqual(fake_get.await_count, 2)

    def test_host_throttle_spaces_requests(self) -> None:
        from sciencedirect_meta import server

        response = mock.Mock(status_code=200, headers={})
        fake_get = mock.AsyncMock(return_value=response)
        fake_client = mock.Mock()
        fake_client.get = fake_get
        with mock.patch.dict(
            server._RATE_INTERVALS, {"api.crossref.org": (0.2, 0.2)}, clear=False
        ), mock.patch.object(server, "client_for_loop", lambda: fake_client):
            server._HOST_LAST_CALL.pop("api.crossref.org", None)

            async def main() -> float:
                started = time.monotonic()
                await server.polite_get("https://api.crossref.org/works")
                await server.polite_get("https://api.crossref.org/works")
                return time.monotonic() - started

            self.assertGreaterEqual(asyncio.run(main()), 0.19)

    def test_run_source_marks_rate_limited_and_skips_remaining_facets(self) -> None:
        from sciencedirect_meta import server

        async def limited():
            raise server.RateLimitedError("429", source="openalex", retry_after=5.0)

        first = asyncio.run(sources.run_source("openalex", limited(), 10))
        self.assertEqual(first["status"], "rate_limited")
        self.assertTrue(first["rate_limited"])
        self.assertIn("429", first["note"])

        async def never():
            raise AssertionError("cooldown should skip the request")

        second = asyncio.run(sources.run_source("openalex", never(), 10))
        self.assertEqual(second["status"], "rate_limited")
        self.assertEqual(second["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
