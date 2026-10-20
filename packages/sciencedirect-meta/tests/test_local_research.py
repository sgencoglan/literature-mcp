"""Offline tests for the local-library parts of local_research."""

from __future__ import annotations

import asyncio
import csv
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sciencedirect_meta import local_research


def _write_pdf(path: Path, text: str) -> None:
    """Create a tiny valid PDF without external dependencies."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 12 Tf 72 720 Td (" + safe + ") Tj ET").encode()
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream
        + b"\nendstream"
    )

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    path.write_bytes(pdf)


class LocalResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.original_library = local_research.PAPER_LIBRARY_DIR
        self.original_reviews = local_research.REVIEW_OUTPUT_DIR
        self.original_rank_path = local_research.JOURNAL_RANK_PATH
        self.original_analysis = local_research.ANALYSIS_UPDATES_PATH
        local_research.PAPER_LIBRARY_DIR = self.root / "library"
        local_research.REVIEW_OUTPUT_DIR = self.root / "reviews"
        local_research.ANALYSIS_UPDATES_PATH = (
            Path(__file__).resolve().parent / "fixtures" / "audit_fixture.json"
        )
        local_research.PAPER_LIBRARY_DIR.mkdir()
        local_research._LIBRARY_CACHE.clear()
        local_research._JOURNAL_RANK_CACHE = None

        self.doi = "10.5555/example.2026.001"
        self.pdf_path = local_research.PAPER_LIBRARY_DIR / "10.5555_example.2026.001.pdf"
        _write_pdf(
            self.pdf_path,
            "Example workplace wellbeing study. DOI: 10.5555/example.2026.001. "
            "Employees reported improved wellbeing after the programme.",
        )

    def tearDown(self) -> None:
        local_research.PAPER_LIBRARY_DIR = self.original_library
        local_research.REVIEW_OUTPUT_DIR = self.original_reviews
        local_research.JOURNAL_RANK_PATH = self.original_rank_path
        local_research.ANALYSIS_UPDATES_PATH = self.original_analysis
        local_research._LIBRARY_CACHE.clear()
        local_research._JOURNAL_RANK_CACHE = None
        self.tempdir.cleanup()

    def test_library_status_and_doi_match(self) -> None:
        status = local_research.library_status()
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["files"][0]["detected_doi"], self.doi)

        result = asyncio.run(local_research.read_paper(identifier=self.doi))
        self.assertEqual(result["match"], "doi_in_filename")
        self.assertEqual(result["path"], str(self.pdf_path))
        self.assertIn("Example workplace wellbeing study", result["text"])

    def test_title_match_without_network(self) -> None:
        result = asyncio.run(
            local_research.read_paper(
                identifier="Example workplace wellbeing study",
                id_type="title",
            )
        )
        self.assertEqual(result["match"], "title_similarity")
        self.assertEqual(result["path"], str(self.pdf_path))

    def test_pdf_page_range_and_extraction(self) -> None:
        page_count, pages = local_research._extract_pdf_pages(
            self.pdf_path,
            page_start=1,
            page_end=1,
        )
        self.assertEqual(page_count, 1)
        self.assertEqual([page["page"] for page in pages], [1])
        self.assertIn("Example workplace wellbeing study", pages[0]["text"])

    def test_evidence_check_uses_supplied_text(self) -> None:
        result = asyncio.run(
            local_research.evidence_check(
                claims=[
                    "Employees reported improved wellbeing after the programme.",
                    "The moon is made of cheese.",
                ],
                text=(
                    "Employees reported improved wellbeing after the programme. "
                    "The programme was delivered in two organizations."
                ),
            )
        )
        first, second = result["claims"]
        self.assertEqual(first["verdict"], "strong")
        self.assertEqual(second["verdict"], "not_found")
        self.assertTrue(first["evidence"])

    def test_export_review_markdown(self) -> None:
        result = asyncio.run(
            local_research.export_review(
                title="Test Review",
                content="A short review body.",
                format="markdown",
                filename="test-review.md",
            )
        )
        path = Path(result["path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "test-review.md")
        self.assertIn("# Test Review", path.read_text(encoding="utf-8"))

    def test_publisher_allowlist(self) -> None:
        from sciencedirect_meta.server import _paper, _publisher_allowed

        allowed_dois = [
            "10.1097/jan.0000000000000380",  # Ovid LWW
            "10.1016/j.adolescence.2010.05.018",  # ScienceDirect
            "10.1007/s10964-006-9092-z",  # SpringerLink
            "10.1111/josh.13316",  # Wiley
            "10.1080/03069885.2016.1164297",  # Taylor & Francis
        ]
        for doi in allowed_dois:
            item = _paper(title="Example", doi=doi)
            self.assertTrue(item["publisher_allowed"], doi)

        # Oxford and BMC do not have a link from the allowed publisher set.
        for doi in ["10.1093/cs/cdy018", "10.1186/s13034-018-0233-4"]:
            item = _paper(title="Example", doi=doi)
            self.assertFalse(item["publisher_allowed"], doi)
            self.assertFalse(_publisher_allowed(item), doi)

    def test_link_keys_are_limited_to_supported_platforms(self) -> None:
        from sciencedirect_meta.server import _build_links

        allowed = {
            "ovid_lww",
            "sciencedirect",
            "springerlink",
            "wiley",
            "taylor_francis",
            "doi",
        }
        samples = [
            "10.1097/jan.0000000000000380",
            "10.1016/j.adolescence.2010.05.018",
            "10.1007/s10964-006-9092-z",
            "10.1111/josh.13316",
            "10.1080/03069885.2016.1164297",
            "10.1093/cs/cdy018",
        ]
        for doi in samples:
            self.assertLessEqual(set(_build_links(doi)), allowed, doi)

    def test_journal_rank_lookup(self) -> None:
        path = self.root / "scimago.csv.gz"
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(
                [
                    "Rank",
                    "Title",
                    "SJR",
                    "SJR Best Quartile",
                    "H index",
                    "Publisher",
                    "Issn",
                    "Coverage",
                    "Categories",
                    "Areas",
                ]
            )
            writer.writerow(
                [
                    "1",
                    "Journal of Example Work",
                    "0,922",
                    "Q1",
                    "100",
                    "Wiley-Blackwell",
                    "00224391, 17461561",
                    "1950-2025",
                    "Education (Q1); Public Health (Q2)",
                    "Medicine",
                ]
            )
            writer.writerow(
                [
                    "2",
                    "Ethics and Behavior",
                    "0,500",
                    "Q2",
                    "50",
                    "Routledge",
                    "10508422",
                    "1990-2025",
                    "Ethics (Q2)",
                    "Social Sciences",
                ]
            )

        local_research.JOURNAL_RANK_PATH = path
        local_research._JOURNAL_RANK_CACHE = None
        result = asyncio.run(
            local_research.journal_rank(
                ["Journal of Example Work", "Ethics & Behavior", "No Such Journal"]
            )
        )
        self.assertEqual(result["source_year"], 2024)
        self.assertEqual(result["results"][0]["quartile"], "Q1")
        self.assertEqual(result["results"][0]["quartile_rank"], 1)
        self.assertEqual(result["results"][0]["match"], "exact")
        self.assertEqual(result["results"][1]["quartile"], "Q2")
        self.assertEqual(result["results"][1]["match"], "exact")
        self.assertFalse(result["results"][2]["found"])

    def test_merge_preserves_all_sources_and_ids(self) -> None:
        from sciencedirect_meta.server import _merge, _paper

        merged = _paper(
            title="Example",
            doi=self.doi,
            source="openalex",
            openalex_id="https://openalex.org/W1",
        )
        _merge(
            merged,
            _paper(
                title="Example",
                doi=self.doi,
                source="europepmc",
                europepmc_id="12345",
                pmcid="PMC12345",
            ),
        )
        self.assertEqual(merged["sources"], ["europepmc", "openalex"])
        self.assertEqual(merged["openalex_id"], "https://openalex.org/W1")
        self.assertEqual(merged["europepmc_id"], "12345")
        self.assertEqual(merged["pmcid"], "PMC12345")

    def test_analysis_updates_reads_saved_audit(self) -> None:
        result = local_research.analysis_updates(doi=self.doi)
        self.assertEqual(result["revision"], "test-audit-v1")
        self.assertEqual(result["entry_count"], 1)
        self.assertEqual(result["entries"][0]["id"], 1)
        self.assertIn("s. 4", result["entries"][0]["citation"])
        self.assertTrue(result["entries"][0]["full_text_evidence"])
        self.assertEqual(
            set(result["entries"][0]["full_text_evidence"][0]),
            {"original", "turkish"},
        )
        self.assertTrue(result["corrections"])

    def test_analysis_updates_includes_evidence_matrices(self) -> None:
        result = local_research.analysis_updates()
        self.assertEqual(result["claim_count"], 1)
        self.assertEqual(result["risk_of_bias_count"], 1)
        self.assertEqual(result["source_budget_count"], 1)
        self.assertEqual(len(result["claim_matrix"]), 1)
        self.assertEqual(len(result["risk_of_bias"]), 1)
        self.assertTrue(result["gap_analysis"]["chapter_improvements"])

        claim = next(c for c in result["claim_matrix"] if c["id"] == 1)
        self.assertEqual(claim["doi"], self.doi)
        self.assertEqual(claim["strength"], "Orta")
        self.assertIn("wellbeing", claim["key_evidence"])

        rob = next(r for r in result["risk_of_bias"] if r["doi"] == self.doi)
        self.assertEqual(rob["overall"], "Orta")
        self.assertIn("genellenemez", rob["chapter_implication"])

        budget = next(b for b in result["source_budget"] if b["level"].startswith("Giriş"))
        self.assertEqual(budget["ideal_sources"], "2-3")
        self.assertEqual(budget["max_sources"], "4")

    def test_analysis_updates_filters_matrices_by_doi(self) -> None:
        result = local_research.analysis_updates(doi=self.doi)
        self.assertEqual(len(result["claim_matrix"]), 1)
        self.assertEqual(result["claim_matrix"][0]["id"], 1)
        self.assertEqual(len(result["risk_of_bias"]), 1)
        self.assertEqual(result["risk_of_bias"][0]["doi"], self.doi)
        self.assertEqual(result["source_budget_count"], 1)

    def test_analysis_updates_query_searches_matrices(self) -> None:
        result = local_research.analysis_updates(query="wellbeing")
        self.assertTrue(
            any(c["id"] == 1 for c in result["claim_matrix"]),
            result["claim_matrix"],
        )
        self.assertEqual(result["entry_count"], 1)
        self.assertEqual(result["entries"][0]["id"], 1)

        rob_result = local_research.analysis_updates(query="genellenemez")
        self.assertEqual(len(rob_result["risk_of_bias"]), 1)
        self.assertEqual(
            {r["doi"] for r in rob_result["risk_of_bias"]},
            {"10.5555/example.2026.001"},
        )

    def test_project_isolation(self) -> None:
        import json as jsonlib

        original_registry = local_research.LIT_PROJECTS_REGISTRY
        registry_path = self.root / "projects.json"
        dir_a = self.root / "project-a"
        dir_b = self.root / "project-b"
        dir_a.mkdir()
        dir_b.mkdir()
        _write_pdf(
            dir_a / "10.5555_example.2026.001.pdf",
            "Project A investigates remote work arrangements. DOI: 10.5555/example.2026.001.",
        )
        _write_pdf(
            dir_b / "10.1002_example.2020.pdf",
            "Project B investigates hybrid schedules in organizations. "
            "DOI: 10.1002/example.2020.",
        )
        registry_path.write_text(
            jsonlib.dumps(
                {
                    "schema": 1,
                    "projects": {
                        "alpha": {
                            "title": "Project Alpha",
                            "paper_directory": str(dir_a),
                            "include_subdirectories": False,
                            "manifest": str(dir_a / "manifest.csv"),
                            "index_directory": str(self.root / "indexes"),
                            "index_name": "alpha",
                        },
                        "beta": {
                            "title": "Project Beta",
                            "paper_directory": str(dir_b),
                            "include_subdirectories": False,
                            "manifest": str(dir_b / "manifest.csv"),
                            "index_directory": str(self.root / "indexes"),
                            "index_name": "beta",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        local_research.LIT_PROJECTS_REGISTRY = registry_path
        local_research._PROJECTS_CACHE.update({"mtime": None, "data": {}})
        try:
            listing = local_research.list_projects()
            self.assertEqual(listing["count"], 2)

            status_a = local_research.library_status("alpha")
            self.assertEqual(status_a["count"], 1)
            self.assertEqual(status_a["files"][0]["detected_doi"], "10.5555/example.2026.001")

            # Cross-project matching must fail, same-project matching must work.
            self.assertIsNone(
                local_research._match_local_pdf("10.1002/example.2020", "", dir_a, False)
            )
            match_b = local_research._match_local_pdf(
                "10.1002/example.2020", "", dir_b, False
            )
            self.assertIsNotNone(match_b)
            self.assertEqual(match_b["match"], "doi_in_filename")

            blocked = asyncio.run(
                local_research.read_paper(
                    identifier="Project B investigates hybrid schedules",
                    id_type="title",
                    project="alpha",
                )
            )
            self.assertIn("error", blocked)
            found = asyncio.run(
                local_research.read_paper(
                    identifier="Project B investigates hybrid schedules",
                    id_type="title",
                    project="beta",
                )
            )
            self.assertEqual(found["path"], str(dir_b / "10.1002_example.2020.pdf"))

            unknown = local_research.library_status("nope")
            self.assertIn("error", unknown)
        finally:
            local_research.LIT_PROJECTS_REGISTRY = original_registry
            local_research._PROJECTS_CACHE.update({"mtime": None, "data": {}})

    def test_single_mcp_exposes_all_tools(self) -> None:
        from sciencedirect_meta import unified

        tools = asyncio.run(unified.handle_list_tools())
        names = {tool.name for tool in tools}
        self.assertEqual(len(names), 19)
        self.assertIn("get_links", names)
        self.assertIn("search_literature", names)
        self.assertIn("doi_provenance", names)
        self.assertIn("journal_rank", names)
        self.assertIn("read_paper", names)
        self.assertIn("analysis_updates", names)
        self.assertIn("library_status", names)
        self.assertIn("list_projects", names)
        self.assertIn("project_audit", names)


if __name__ == "__main__":
    unittest.main()
