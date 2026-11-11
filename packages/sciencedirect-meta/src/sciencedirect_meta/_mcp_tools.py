"""MCP tool schemas and dispatch for the local research tools."""


from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import mcp.types as types

from sciencedirect_meta import _common, bootstrap
from sciencedirect_meta import server as meta_server
from sciencedirect_meta._common import AVAILABLE_SOURCES, _error, _json_text, logger
from sciencedirect_meta._crossref import doi_provenance
from sciencedirect_meta._evidence import compare_studies, evidence_check, export_review
from sciencedirect_meta._journals import journal_rank
from sciencedirect_meta._library import (
    analysis_updates,
    library_status,
    list_projects,
    project_audit,
    read_paper,
)
from sciencedirect_meta._search import deep_research, search_literature, verify_doi_and_publisher
from sciencedirect_meta.server import (
    PRIORITY_ORDER,
    RateLimitedError,
    redact_secrets,
)


async def handle_list_tools() -> List[types.Tool]:
    source_schema = {
        "type": "array",
        "items": {"type": "string", "enum": AVAILABLE_SOURCES},
        "description": "Metadata sources to query. Default: all available sources.",
    }
    publisher_schema = {
        "type": "array",
        "items": {"type": "string", "enum": list(PRIORITY_ORDER)},
        "description": (
            "Publisher/source allowlist. Default: Ovid LWW, ScienceDirect, "
            "SpringerLink, Wiley, Taylor & Francis."
        ),
    }
    project_schema = {
        "type": "string",
        "description": (
            "Registered project name (see list_projects). Scopes local PDF "
            "lookups to that project's folder only; projects never mix."
        ),
    }
    project_directory_schema = {
        "type": "string",
        "description": (
            "Project root path. Its setup.txt supplies the API keys "
            "(OpenAlex, PubMed/NCBI, Semantic Scholar) and contact e-mail."
        ),
    }
    return [
        types.Tool(
            name="list_projects",
            description=(
                "List registered literature projects (shared registry with the "
                "paperqa-local MCP). Each project is isolated: own PDF folder, "
                "manifest CSV and PaperQA2 index. Shows per-project PDF counts, "
                "detected DOIs, manifest status, and files not yet in the manifest."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="project_audit",
            description=(
                "Audit one registered project's PDFs without mixing projects: per "
                "unique DOI returns metadata (OpenAlex/Europe PMC, Crossref fallback), "
                "database provenance (found_in), Crossref vs OpenAlex citation counts, "
                "SCImago quartile, and OpenAlex retraction flags. This is the "
                "project-scoped version of the Ek C style metrics table."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": project_schema,
                    "include_quartiles": {"type": "boolean", "default": True},
                    "check_retractions": {"type": "boolean", "default": True},
                    "max_dois": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                },
                "required": ["project"],
            },
        ),
        types.Tool(
            name="search_literature",
            description=(
                "Find DOIs and metadata across every available source; narrow the set with "
                "sources. Returns a quality score per result, a per-source coverage block "
                "and an evidence_scarcity signal. Every available source is queried by default "
                "(OpenAlex, Semantic Scholar, PubMed, Europe PMC, Crossref, arXiv, "
                "ClinicalTrials.gov); all publishers are returned. Adds local_pdf when a "
                "matching PDF is already available; pass project=... to check only that "
                "project's folder and to use its setup.txt API keys."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "sources": source_schema,
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer"},
                    "priority_only": {"type": "boolean", "default": False},
                    "allowed_publishers": publisher_schema,
                    "include_local_pdf": {"type": "boolean", "default": True},
                    "project": project_schema,
                    "project_directory": project_directory_schema,
                    "query_expansion": {
                        "type": "object",
                        "description": (
                            "Explicit query-expansion record for the coverage report. "
                            "Fields: original, expanded/queries, mesh, languages, "
                            "transformations, notes."
                        ),
                        "properties": {
                            "original": {"type": "string"},
                            "expanded": {"type": "array", "items": {"type": "string"}},
                            "queries": {"type": "array", "items": {"type": "string"}},
                            "mesh": {"type": "array", "items": {"type": "string"}},
                            "languages": {"type": "array", "items": {"type": "string"}},
                            "transformations": {"type": "array", "items": {"type": "string"}},
                            "notes": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="deep_research",
            description=(
                "Decompose a research question into facets (overview, reviews, prevalence, "
                "risk factors, interventions, qualitative) and run multi-source DOI searches. "
                "Searches every available source and returns all publishers by default; set "
                "priority_only=true to keep only the priority publisher set. Returns a "
                "quality score per result and a combined coverage block with an "
                "evidence_scarcity signal. Pass subtopics to control the decomposition explicitly."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "subtopics": {"type": "array", "items": {"type": "string"}},
                    "max_subtopics": {"type": "integer", "default": 5, "minimum": 1, "maximum": 8},
                    "results_per_topic": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer"},
                    "sources": source_schema,
                    "priority_only": {"type": "boolean", "default": False},
                    "allowed_publishers": publisher_schema,
                    "project": project_schema,
                    "project_directory": project_directory_schema,
                    "query_expansion": {
                        "type": "object",
                        "description": (
                            "Explicit query-expansion record for the coverage report. "
                            "Fields: original, expanded/queries, mesh, languages, "
                            "transformations, notes."
                        ),
                        "properties": {
                            "original": {"type": "string"},
                            "expanded": {"type": "array", "items": {"type": "string"}},
                            "queries": {"type": "array", "items": {"type": "string"}},
                            "mesh": {"type": "array", "items": {"type": "string"}},
                            "languages": {"type": "array", "items": {"type": "string"}},
                            "transformations": {"type": "array", "items": {"type": "string"}},
                            "notes": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["question"],
            },
        ),
        types.Tool(
            name="verify_doi_and_publisher",
            description=(
                "Verify a DOI in Crossref and via doi.org, identify the publisher, resolve "
                "the Elsevier PII when present, and return the ScienceDirect and priority links."
            ),
            inputSchema={
                "type": "object",
                "properties": {"doi": {"type": "string"}},
                "required": ["doi"],
            },
        ),
        types.Tool(
            name="doi_provenance",
            description=(
                "Report which metadata databases index a DOI (Crossref, OpenAlex, "
                "Europe PMC, PubMed), including each database's record ID and title. "
                "Use this to audit where a selected DOI came from."
            ),
            inputSchema={
                "type": "object",
                "properties": {"doi": {"type": "string"}},
                "required": ["doi"],
            },
        ),
        types.Tool(
            name="read_paper",
            description=(
                "Read a full-text PDF from the local library (matched by DOI or title) or "
                "from an explicit pdf_path. With no arguments, lists the local library. "
                "Pass project=... to search only that project's folder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "DOI, PMID, or title (with id_type=title)."},
                    "id_type": {"type": "string", "enum": ["doi", "pmid", "title"], "default": "doi"},
                    "pdf_path": {"type": "string"},
                    "max_chars": {"type": "integer", "default": _common.READ_MAX_CHARS, "minimum": 1000},
                    "max_pages": {"type": "integer", "default": _common.PDF_MAX_PAGES, "minimum": 1},
                    "page_start": {"type": "integer", "minimum": 1},
                    "page_end": {"type": "integer", "minimum": 1},
                    "project": project_schema,
                },
            },
        ),
        types.Tool(
            name="compare_studies",
            description=(
                "Build a methods/sample/results/limitations table for DOIs, PMIDs, or a query. "
                "Uses local full-text PDFs when available, otherwise abstracts. "
                "Pass project=... so full texts are only taken from that project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifiers": {"type": "array", "items": {"type": "string"}},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 6, "minimum": 1, "maximum": 12},
                    "sources": source_schema,
                    "project": project_schema,
                },
            },
        ),
        types.Tool(
            name="evidence_check",
            description=(
                "Match claims against sentences in a local full-text PDF or abstract. "
                "Returns strong/moderate/weak/not_found verdicts and the best matching sentences. "
                "Pass project=... to restrict local PDF lookups to that project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "claims": {"type": "array", "items": {"type": "string"}},
                    "identifier": {"type": "string"},
                    "id_type": {"type": "string", "enum": ["doi", "pmid", "title"], "default": "doi"},
                    "pdf_path": {"type": "string"},
                    "text": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
                    "project": project_schema,
                },
                "required": ["claims"],
            },
        ),
        types.Tool(
            name="export_review",
            description=(
                "Save a cited review as Markdown, CSV, or JSON. With project, "
                "the file is written inside that project's output_directory "
                "(defaults to the project folder); otherwise inside REVIEW_OUTPUT_DIR. "
                "Accepts sections, references, and evidence-check claims."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "project": project_schema,
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "body": {"type": "string"},
                            },
                        },
                    },
                    "content": {"type": "string"},
                    "references": {"type": "array", "items": {"type": "object"}},
                    "claims": {"type": "array", "items": {"type": "object"}},
                    "format": {"type": "string", "enum": ["markdown", "md", "csv", "json"], "default": "markdown"},
                    "filename": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["title"],
            },
        ),
        types.Tool(
            name="journal_rank",
            description=(
                "Look up SCImago Journal Rank 2024 Q1-Q4 quartiles for journal titles. "
                "Reads a local CSV; does not call external services at runtime."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "journals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Journal titles, e.g. ['Journal of Example Work'].",
                    },
                    "include_categories": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include SCImago subject categories and areas.",
                    },
                },
                "required": ["journals"],
            },
        ),
        types.Tool(
            name="analysis_updates",
            description=(
                "Return the saved full-text citation audit for the active project. "
                "Includes page-level full-text quotes, translations, constructed sentences, "
                "abstract-vs-full-text corrections, document-level citation metrics, the claim "
                "evidence matrix, the risk-of-bias assessment, the source budget, and an optional "
                "gap analysis. Filter by DOI, entry_id, or query."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {
                        "type": "string",
                        "description": "Optional DOI filter, e.g. 10.1111/bjep.12553.",
                    },
                    "entry_id": {
                        "type": "integer",
                        "description": "Optional audit entry number (1-13).",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional case-insensitive search in headings, quotes, translations, notes, corrections, claim matrix, risk-of-bias records, source budget, and gap analysis.",
                    },
                    "include_entries": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include matching audit entries.",
                    },
                    "include_corrections": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include matching abstract-vs-full-text corrections.",
                    },
                    "include_matrices": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include claim_matrix, risk_of_bias, and source_budget.",
                    },
                    "include_gap_analysis": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include the optional gap analysis.",
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Registered project name; reads that project's own "
                            "analysis_json file instead of the global audit."
                        ),
                    },
                },
            },
        ),
        types.Tool(
            name="library_status",
            description=(
                "List PDFs in the local library with detected DOIs and titles. "
                "Pass project=... to scan only that registered project's folder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": project_schema,
                },
            },
        ),
    ]


async def handle_call_tool(
    name: str,
    arguments: Optional[Dict[str, Any]],
) -> List[types.TextContent]:
    args = arguments or {}
    try:
        project_root = (
            str(args.get("project_directory") or "").strip()
            or os.environ.get("LIT_PROJECT_ROOT", "").strip()
        )
        if project_root and bootstrap.load_for_project(project_root).get("path"):
            meta_server.refresh_credentials()

        if name == "list_projects":
            return _json_text(list_projects())

        if name == "project_audit":
            project = str(args.get("project", "")).strip()
            if not project:
                return _json_text(_error("project is required"))
            return _json_text(
                await project_audit(
                    project=project,
                    include_quartiles=bool(args.get("include_quartiles", True)),
                    check_retractions=bool(args.get("check_retractions", True)),
                    max_dois=int(args.get("max_dois", 50)),
                )
            )

        if name == "search_literature":
            query = str(args.get("query", "")).strip()
            if not query:
                return _json_text(_error("query is required"))
            return _json_text(
                await search_literature(
                    query=query,
                    sources=args.get("sources"),
                    limit=int(args.get("limit", 10)),
                    year_from=args.get("year_from"),
                    year_to=args.get("year_to"),
                    priority_only=bool(args.get("priority_only", False)),
                    allowed_publishers=args.get("allowed_publishers"),
                    include_local_pdf=bool(args.get("include_local_pdf", True)),
                    project=args.get("project"),
                    project_directory=args.get("project_directory"),
                    query_expansion=args.get("query_expansion"),
                )
            )

        if name == "deep_research":
            return _json_text(
                await deep_research(
                    question=str(args.get("question", "")),
                    subtopics=args.get("subtopics"),
                    max_subtopics=int(args.get("max_subtopics", 5)),
                    results_per_topic=int(args.get("results_per_topic", 5)),
                    year_from=args.get("year_from"),
                    year_to=args.get("year_to"),
                    sources=args.get("sources"),
                    priority_only=bool(args.get("priority_only", False)),
                    allowed_publishers=args.get("allowed_publishers"),
                    query_expansion=args.get("query_expansion"),
                    project=args.get("project"),
                    project_directory=args.get("project_directory"),
                )
            )

        if name == "verify_doi_and_publisher":
            doi = str(args.get("doi", "")).strip()
            if not doi:
                return _json_text(_error("doi is required"))
            return _json_text(await verify_doi_and_publisher(doi))

        if name == "doi_provenance":
            doi = str(args.get("doi", "")).strip()
            if not doi:
                return _json_text(_error("doi is required"))
            return _json_text(await doi_provenance(doi))

        if name == "journal_rank":
            journals = args.get("journals")
            if isinstance(journals, str):
                journals = [journals]
            return _json_text(
                await journal_rank(
                    journals=journals or [],
                    include_categories=bool(args.get("include_categories", True)),
                )
            )

        if name == "read_paper":
            return _json_text(
                await read_paper(
                    identifier=args.get("identifier"),
                    id_type=str(args.get("id_type", "doi")),
                    pdf_path=args.get("pdf_path"),
                    max_chars=int(args.get("max_chars", _common.READ_MAX_CHARS)),
                    max_pages=int(args.get("max_pages", _common.PDF_MAX_PAGES)),
                    page_start=args.get("page_start"),
                    page_end=args.get("page_end"),
                    project=args.get("project"),
                )
            )

        if name == "compare_studies":
            return _json_text(
                await compare_studies(
                    identifiers=args.get("identifiers"),
                    query=args.get("query"),
                    limit=int(args.get("limit", 6)),
                    sources=args.get("sources"),
                    project=args.get("project"),
                )
            )

        if name == "evidence_check":
            claims = args.get("claims")
            if isinstance(claims, str):
                claims = [claims]
            return _json_text(
                await evidence_check(
                    claims=claims or [],
                    identifier=args.get("identifier"),
                    id_type=str(args.get("id_type", "doi")),
                    pdf_path=args.get("pdf_path"),
                    text=args.get("text"),
                    top_k=int(args.get("top_k", 3)),
                    project=args.get("project"),
                )
            )

        if name == "export_review":
            return _json_text(
                await export_review(
                    title=str(args.get("title", "")),
                    sections=args.get("sections"),
                    content=args.get("content"),
                    references=args.get("references"),
                    claims=args.get("claims"),
                    format=str(args.get("format", "markdown")),
                    filename=args.get("filename"),
                    output_path=args.get("output_path"),
                    project=args.get("project"),
                )
            )

        if name == "analysis_updates":
            return _json_text(
                analysis_updates(
                    doi=args.get("doi"),
                    entry_id=args.get("entry_id"),
                    query=args.get("query"),
                    include_entries=bool(args.get("include_entries", True)),
                    include_corrections=bool(args.get("include_corrections", True)),
                    include_matrices=bool(args.get("include_matrices", True)),
                    include_gap_analysis=bool(args.get("include_gap_analysis", True)),
                    project=args.get("project"),
                )
            )

        if name == "library_status":
            return _json_text(library_status(args.get("project")))

        return _json_text(_error(f"unknown tool: {name}"))
    except RateLimitedError as exc:
        logger.info("Tool %s rate limited: %s", name, exc)
        return _json_text(
            {
                "tool": name,
                "rate_limited": True,
                "error_code": "rate_limited",
                "note": redact_secrets(exc),
                "results": [],
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool %s failed", name)
        return _json_text(_error(str(exc), tool=name))


