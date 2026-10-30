"""Local research functions, exposed by the unified MCP.

Workflow
--------
1. Find DOIs and priority publisher links (Ovid LWW, ScienceDirect,
   SpringerLink, Wiley, Taylor & Francis).
2. The user downloads full texts and places the PDFs in PAPER_LIBRARY_DIR.
3. read_paper / compare_studies / evidence_check read those local PDFs.
4. export_review writes a cited Markdown / CSV / JSON report.

No Elsevier API key and no ScienceDirect scraping.  These functions never
download paywalled PDFs; they only read files the user has placed in the
library folder.
"""

from __future__ import annotations

import asyncio
import csv
import difflib
import gzip
import io
import json
import logging
import math
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin

import mcp.types as types
import pymupdf

from sciencedirect_meta.server import (
    DEFAULT_ALLOWED_PUBLISHERS,
    MAILTO,
    MAX_ENRICH,
    PRIORITY_ORDER,
    _build_links,
    _client,
    _dedupe_key,
    _extract_pii,
    _filter_by_publisher,
    _finalize_links,
    _merge,
    _normalized_allowed_publishers,
    _paper,
    _rank,
    _sciencedirect_link,
    _truncate,
    enrich_sciencedirect_links,
    get_article,
    normalize_doi,
    search_europepmc,
    search_openalex,
    search_pubmed,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

PAPER_LIBRARY_DIR = Path(
    os.environ.get("PAPER_LIBRARY_DIR", "~/Documents/papers")
).expanduser().resolve()
REVIEW_OUTPUT_DIR = Path(
    os.environ.get("REVIEW_OUTPUT_DIR", "~/Documents/reviews")
).expanduser().resolve()

PDF_MAX_PAGES = int(os.environ.get("PDF_MAX_PAGES", "40"))
READ_MAX_CHARS = int(os.environ.get("READ_MAX_CHARS", "30000"))

JOURNAL_RANK_PATH = Path(
    os.environ.get(
        "JOURNAL_RANK_CSV",
        str(Path(__file__).resolve().parents[2] / "data" / "scimagojr_2024.csv.gz"),
    )
).expanduser()

ANALYSIS_UPDATES_PATH = Path(
    os.environ.get(
        "ANALYSIS_UPDATES_JSON",
        str(Path(__file__).resolve().parents[2] / "data" / "analysis_updates.json"),
    )
).expanduser()

# Shared project registry with the paperqa-local MCP.  Each project is an
# isolated unit: its own PDF folder, manifest CSV and PaperQA2 index.  Local
# file tools accept project=... so results never mix across projects.
LIT_PROJECTS_REGISTRY = Path(
    os.environ.get("LIT_PROJECTS_REGISTRY", "~/.literature-mcp/projects.json")
).expanduser()

_PROJECTS_CACHE: Dict[str, Any] = {"mtime": None, "data": {}}

AVAILABLE_SOURCES = ["openalex", "pubmed", "europepmc", "crossref"]

_JOURNAL_RANK_CACHE: Optional[Dict[str, Any]] = None

logger = logging.getLogger("local-research")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _json_text(payload: Any) -> List[types.TextContent]:
    return [
        types.TextContent(
            type="text",
            text=json.dumps(payload, ensure_ascii=False, indent=2),
        )
    ]


def _error(message: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"error": message}
    payload.update(extra)
    return payload


def _strip_html(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", text).strip() or None


def _split_sentences(text: Optional[str]) -> List[str]:
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    return [s.strip() for s in sentences if len(s.strip()) >= 20]


def _safe_slug(value: str, fallback: str = "review") -> str:
    slug = re.sub(r"[^a-zA-Z0-9À-ÿ]+", "-", (value or fallback).lower()).strip("-")
    return (slug or fallback)[:80]


def _authors_short(authors: Optional[Sequence[str]], limit: int = 3) -> str:
    authors = [a for a in (authors or []) if a]
    if not authors:
        return "Unknown authors"
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + " et al."


def _escape_md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Crossref: full metadata + search
# --------------------------------------------------------------------------- #

_crossref_cache: Dict[str, Optional[Dict[str, Any]]] = {}
_crossref_sem = asyncio.Semaphore(3)


async def crossref_work(doi: str) -> Optional[Dict[str, Any]]:
    """Return Crossref metadata for one DOI (cached)."""
    key = normalize_doi(doi)
    if not key:
        return None
    if key in _crossref_cache:
        return _crossref_cache[key]

    async with _crossref_sem:
        url = f"https://api.crossref.org/works/{quote(key, safe='')}"
        for attempt in range(3):
            try:
                response = await _client.get(url, params={"mailto": MAILTO})
                if response.status_code == 429:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code == 404:
                    _crossref_cache[key] = None
                    return None
                if response.status_code != 200:
                    logger.info("Crossref %s -> HTTP %s", key, response.status_code)
                    return None
                message = response.json().get("message")
                _crossref_cache[key] = message
                await asyncio.sleep(0.15)
                return message
            except Exception as exc:  # noqa: BLE001
                logger.info("Crossref lookup failed for %s: %s", key, exc)
                return None
    return None


def _crossref_paper(item: Dict[str, Any]) -> Dict[str, Any]:
    doi = normalize_doi(item.get("DOI"))
    title = (item.get("title") or [None])[0]
    authors: List[str] = []
    for author in item.get("author") or []:
        if author.get("family"):
            authors.append(f"{author['family']} {author.get('given', '')}".strip())
        elif author.get("name"):
            authors.append(author["name"])
    year = None
    date_parts = (item.get("issued") or {}).get("date-parts") or []
    if date_parts and date_parts[0]:
        year = date_parts[0][0]
    journal = (item.get("container-title") or [None])[0]
    pii = _extract_pii(item)
    paper = _paper(
        title=title,
        authors=authors,
        year=year,
        journal=journal,
        doi=doi or None,
        abstract=_truncate(_strip_html(item.get("abstract"))),
        cited_by=item.get("is-referenced-by-count") or 0,
        source="crossref",
        crossref_id=doi or None,
        type=item.get("type"),
    )
    paper["publisher"] = item.get("publisher")
    paper["landing_url"] = item.get("URL")
    _finalize_links(paper, pii=pii)
    return paper


async def search_crossref(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "query": query,
        "rows": max(1, min(limit, 50)),
        "select": (
            "DOI,title,author,container-title,issued,abstract,URL,link,type,"
            "publisher,is-referenced-by-count,alternative-id"
        ),
        "mailto": MAILTO,
    }
    filters: List[str] = []
    if year_from:
        filters.append(f"from-pub-date:{int(year_from)}-01-01")
    if year_to:
        filters.append(f"until-pub-date:{int(year_to)}-12-31")
    if filters:
        params["filter"] = ",".join(filters)

    response = await _client.get("https://api.crossref.org/works", params=params)
    if response.status_code == 429:
        await asyncio.sleep(2.0)
        response = await _client.get("https://api.crossref.org/works", params=params)
    if response.status_code == 429:
        raise RuntimeError("Crossref rate limit (HTTP 429); try again shortly")
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])
    return [_crossref_paper(item) for item in items]


async def _metadata_for(identifier: str, id_type: str = "doi") -> Dict[str, Any]:
    """Metadata from OpenAlex/Europe PMC, falling back to Crossref."""
    identifier = (identifier or "").strip()
    id_type = (id_type or "doi").lower()
    if not identifier or id_type == "title":
        return {}
    try:
        item = await get_article(identifier, id_type)
        if "error" not in item:
            return item
    except Exception as exc:  # noqa: BLE001
        logger.info("Metadata lookup failed for %s: %s", identifier, exc)

    if id_type == "doi":
        message = await crossref_work(identifier)
        if message:
            return _crossref_paper(message)
    return {}


# --------------------------------------------------------------------------- #
# Unified DOI / literature search
# --------------------------------------------------------------------------- #

async def search_literature(
    query: str,
    sources: Optional[Sequence[str]] = None,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    priority_only: bool = True,
    allowed_publishers: Optional[Sequence[str]] = None,
    include_local_pdf: bool = True,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Search metadata sources; ``project`` scopes the local_pdf annotations.

    When ``project`` is given, the "already have the PDF?" flag is computed
    against that project's folder only, so hits from other projects are not
    mixed in.
    """
    try:
        scope_dir, scope_recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    requested = [s for s in (sources or AVAILABLE_SOURCES) if s in AVAILABLE_SOURCES]
    if not requested:
        requested = list(AVAILABLE_SOURCES)

    tasks: Dict[str, Any] = {}
    if "openalex" in requested:
        tasks["openalex"] = search_openalex(
            query, limit, year_from, year_to,
            elsevier_only=False,
            priority_publishers_only=priority_only,
        )
    if "pubmed" in requested:
        tasks["pubmed"] = search_pubmed(query, limit)
    if "europepmc" in requested:
        tasks["europepmc"] = search_europepmc(query, limit)
    if "crossref" in requested:
        tasks["crossref"] = search_crossref(query, limit, year_from, year_to)

    gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)

    merged: Dict[str, Dict[str, Any]] = {}
    notes: List[str] = []
    status: Dict[str, str] = {}
    for name, result in zip(tasks.keys(), gathered):
        if isinstance(result, Exception):
            status[name] = "error"
            notes.append(f"{name}: {result}")
            continue
        status[name] = "ok"
        for item in result:
            key = _dedupe_key(item)
            if not key or key == "title:":
                continue
            if key in merged:
                _merge(merged[key], item)
            else:
                merged[key] = item

    items = list(merged.values())
    for item in items:
        _finalize_links(item)

    # Resolve ScienceDirect PII links before applying the allowlist.  A
    # 10.1016 DOI can otherwise look like a DOI-only record until Crossref
    # enrichment supplies its publisher link.
    await enrich_sciencedirect_links(items, limit=min(10, MAX_ENRICH))
    if priority_only:
        items = _filter_by_publisher(items, allowed_publishers)

    items.sort(key=_rank)
    returned = items[: max(1, min(limit, 50))]

    if include_local_pdf:
        _annotate_local_pdfs(returned, scope_dir, scope_recurse)

    return {
        "query": query,
        "project": project or None,
        "count": len(returned),
        "total_found": len(items),
        "sources_requested": requested,
        "sources_status": status,
        "priority_only": priority_only,
        "priority_order": PRIORITY_ORDER,
        "allowed_publishers": _normalized_allowed_publishers(allowed_publishers),
        "notes": notes,
        "results": returned,
    }


# --------------------------------------------------------------------------- #
# DOI / publisher verification
# --------------------------------------------------------------------------- #

async def verify_doi_and_publisher(doi: str) -> Dict[str, Any]:
    doi = normalize_doi(doi)
    if not doi:
        return _error("A valid DOI is required")

    message = await crossref_work(doi)
    pii = _extract_pii(message or {})
    sd_url, sd_type = _sciencedirect_link(doi, pii)

    resolution_status: Optional[int] = None
    resolved_url: Optional[str] = None
    resolution_error: Optional[str] = None
    try:
        response = await _client.get(
            f"https://doi.org/{quote(doi, safe='/')}",
            follow_redirects=False,
            headers={"Accept": "text/html"},
        )
        resolution_status = response.status_code
        location = response.headers.get("location")
        if location:
            resolved_url = urljoin(f"https://doi.org/{doi}", location)
    except Exception as exc:  # noqa: BLE001
        resolution_error = str(exc)

    publisher = message.get("publisher") if message else None
    is_elsevier = (
        bool(pii)
        or doi.startswith("10.1016/")
        or "elsevier" in (publisher or "").lower()
    )
    links = _build_links(doi, pii=pii, work_type=(message or {}).get("type"))

    warnings: List[str] = []
    if not message:
        warnings.append("DOI was not found in Crossref.")
    if doi.startswith("10.1016/") and not pii:
        warnings.append(
            "PII not found in Crossref; ScienceDirect URL falls back to the DOI resolver."
        )
    if resolution_status in (401, 403):
        warnings.append(
            "Publisher page blocked an automated request; the link may still work in a browser."
        )
    if resolution_error:
        warnings.append(f"DOI resolution check failed: {resolution_error}")

    year = None
    title = None
    if message:
        date_parts = (message.get("issued") or {}).get("date-parts") or []
        if date_parts and date_parts[0]:
            year = date_parts[0][0]
        title = (message.get("title") or [None])[0]

    valid = bool(message) or resolution_status in (200, 301, 302, 303, 307, 308)
    local_pdf = _match_local_pdf(doi, title) if title else _match_local_pdf(doi)
    preferred_source = next((key for key in PRIORITY_ORDER if links.get(key)), None)
    publisher_source = preferred_source
    return {
        "doi": doi,
        "valid": valid,
        "title": title,
        "year": year,
        "publisher": publisher,
        "is_elsevier": is_elsevier,
        "pii": pii,
        "sciencedirect_url": sd_url,
        "sciencedirect_url_type": sd_type,
        "resolved_url": resolved_url,
        "resolution_status": resolution_status,
        "links": links,
        "preferred_url": links.get(preferred_source) if preferred_source else links.get("doi"),
        "preferred_source": preferred_source,
        "publisher_url": links.get(publisher_source) if publisher_source else None,
        "publisher_source": publisher_source,
        "publisher_allowed": publisher_source in DEFAULT_ALLOWED_PUBLISHERS,
        "allowed_publishers": list(DEFAULT_ALLOWED_PUBLISHERS),
        "local_pdf": local_pdf,
        "warnings": warnings,
    }


async def doi_provenance(doi: str) -> Dict[str, Any]:
    """Report every metadata database in which a DOI is indexed.

    This is deliberately separate from search ranking: it answers
    "where did this DOI come from?" rather than "which result is best?".
    """
    doi = normalize_doi(doi)
    if not doi:
        return _error("A valid DOI is required")

    checks: Dict[str, Dict[str, Any]] = {}

    # Crossref
    crossref = await crossref_work(doi)
    if crossref:
        checks["crossref"] = {
            "found": True,
            "checked": True,
            "id": crossref.get("DOI") or doi,
            "title": (crossref.get("title") or [None])[0],
            "publisher": crossref.get("publisher"),
            "type": crossref.get("type"),
            "cited_by": crossref.get("is-referenced-by-count") or 0,
            "url": crossref.get("URL"),
        }
    else:
        # crossref_work() intentionally swallows transport errors, so this is
        # reported as "not confirmed" rather than a hard "not indexed".
        checks["crossref"] = {"found": False, "checked": False}

    # OpenAlex
    try:
        response = await _client.get(
            f"https://api.openalex.org/works/doi:{quote(doi, safe='')}"
        )
        if response.status_code == 200:
            work = response.json()
            checks["openalex"] = {
                "found": True,
                "checked": True,
                "id": work.get("id"),
                "title": work.get("title"),
                "type": work.get("type"),
                "cited_by": work.get("cited_by_count") or 0,
            }
        elif response.status_code == 404:
            checks["openalex"] = {"found": False, "checked": True}
        else:
            checks["openalex"] = {
                "found": False,
                "checked": False,
                "status": response.status_code,
            }
    except Exception as exc:  # noqa: BLE001
        checks["openalex"] = {
            "found": False,
            "checked": False,
            "error": str(exc),
        }

    # Europe PMC
    try:
        epmc_items = await search_europepmc(f"DOI:{doi}", limit=1)
        epmc = next(
            (
                item
                for item in epmc_items
                if normalize_doi(item.get("doi")) == doi
            ),
            None,
        )
        if epmc:
            checks["europepmc"] = {
                "found": True,
                "checked": True,
                "id": epmc.get("europepmc_id"),
                "pmid": epmc.get("pmid"),
                "pmcid": epmc.get("pmcid"),
                "title": epmc.get("title"),
            }
        else:
            checks["europepmc"] = {"found": False, "checked": True}
    except Exception as exc:  # noqa: BLE001
        checks["europepmc"] = {
            "found": False,
            "checked": False,
            "error": str(exc),
        }

    # PubMed
    try:
        pubmed_items = await search_pubmed(f"{doi}[DOI]", limit=1)
        pubmed = next(
            (
                item
                for item in pubmed_items
                if normalize_doi(item.get("doi")) == doi
            ),
            None,
        )
        if pubmed:
            checks["pubmed"] = {
                "found": True,
                "checked": True,
                "id": pubmed.get("pmid"),
                "title": pubmed.get("title"),
            }
        else:
            checks["pubmed"] = {"found": False, "checked": True}
    except Exception as exc:  # noqa: BLE001
        checks["pubmed"] = {
            "found": False,
            "checked": False,
            "error": str(exc),
        }

    found_in = [name for name, check in checks.items() if check.get("found")]
    not_found_in = [
        name
        for name, check in checks.items()
        if check.get("checked") and not check.get("found")
    ]
    unchecked = [
        name
        for name, check in checks.items()
        if not check.get("checked")
    ]
    title = next(
        (
            checks[name].get("title")
            for name in ("crossref", "openalex", "europepmc", "pubmed")
            if checks.get(name, {}).get("title")
        ),
        None,
    )
    local_pdf = _match_local_pdf(doi, title or "")

    return {
        "doi": doi,
        "title": title,
        "found_in": found_in,
        "not_found_in": not_found_in,
        "unchecked": unchecked,
        "source_count": len(found_in),
        "checks": checks,
        "local_pdf": local_pdf,
        "notes": [
            "found_in lists metadata indexes, not open-access full-text availability.",
            "Source IDs are reported per database; a DOI can be indexed in several databases.",
            "unchecked means the database could not be queried (for example HTTP 429); it is not evidence of absence.",
        ],
    }


# --------------------------------------------------------------------------- #
# Journal quartiles (SCImago Journal Rank, local CSV)
# --------------------------------------------------------------------------- #

JOURNAL_RANK_YEAR = 2024


def _normalize_journal_title(value: str) -> str:
    text = (value or "").replace("&amp;", "&")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_scimago_number(value: Optional[str]) -> Optional[float]:
    text = (value or "").strip()
    if not text or text == "-":
        return None
    try:
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        return float(text)
    except ValueError:
        return None


def _parse_scimago_categories(value: Optional[str]) -> List[Dict[str, Any]]:
    categories: List[Dict[str, Any]] = []
    for part in (value or "").split(";"):
        part = part.strip()
        if not part:
            continue
        match = re.match(r"^(.*?)\s*\((Q[1-4])\)\s*$", part, re.IGNORECASE)
        if match:
            categories.append(
                {"name": match.group(1).strip(), "quartile": match.group(2).upper()}
            )
        else:
            categories.append({"name": part, "quartile": None})
    return categories


def _load_journal_rank_data() -> Dict[str, Any]:
    """Load SCImago data once; no network request is made at runtime."""
    global _JOURNAL_RANK_CACHE
    if _JOURNAL_RANK_CACHE is not None:
        return _JOURNAL_RANK_CACHE

    path = JOURNAL_RANK_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Journal rank CSV not found: {path}. Set JOURNAL_RANK_CSV."
        )

    opener = gzip.open if path.suffix.lower() == ".gz" else open
    rows: List[Dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            title = (row.get("Title") or "").strip()
            if not title:
                continue
            normalized = _normalize_journal_title(title)
            if not normalized:
                continue
            quartile = (row.get("SJR Best Quartile") or "").strip().upper() or None
            h_index = (row.get("H index") or "").strip()
            rank = (row.get("Rank") or "").strip()
            rows.append(
                {
                    "title": title,
                    "normalized_title": normalized,
                    "quartile": quartile if quartile in {"Q1", "Q2", "Q3", "Q4"} else None,
                    "sjr": _parse_scimago_number(row.get("SJR")),
                    "h_index": int(h_index) if h_index.isdigit() else None,
                    "scimago_rank": int(rank) if rank.isdigit() else None,
                    "publisher": (row.get("Publisher") or "").strip() or None,
                    "issn": [
                        value.strip()
                        for value in (row.get("Issn") or "").split(",")
                        if value.strip()
                    ],
                    "coverage": (row.get("Coverage") or "").strip() or None,
                    "categories": _parse_scimago_categories(row.get("Categories")),
                    "areas": [
                        value.strip()
                        for value in (row.get("Areas") or "").split(";")
                        if value.strip()
                    ],
                }
            )

    index: Dict[str, Dict[str, Any]] = {}
    for entry in rows:
        index.setdefault(entry["normalized_title"], entry)
    _JOURNAL_RANK_CACHE = {
        "rows": rows,
        "index": index,
        "titles": list(index),
    }
    return _JOURNAL_RANK_CACHE


def _find_journal_rank(
    query: str, data: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], str]:
    normalized = _normalize_journal_title(query)
    if not normalized:
        return None, "empty"

    exact = data["index"].get(normalized)
    if exact:
        return exact, "exact"

    contained = [
        entry
        for entry in data["rows"]
        if normalized in entry["normalized_title"]
        or entry["normalized_title"] in normalized
    ]
    if contained:
        contained.sort(key=lambda entry: abs(len(entry["normalized_title"]) - len(normalized)))
        return contained[0], "contains"

    close = difflib.get_close_matches(
        normalized, data["titles"], n=1, cutoff=0.88
    )
    if close:
        return data["index"][close[0]], "fuzzy"
    return None, "not_found"


async def journal_rank(
    journals: Sequence[str],
    include_categories: bool = True,
) -> Dict[str, Any]:
    """Look up SCImago Q1-Q4 quartiles for one or more journal titles."""
    queries = [str(value).strip() for value in journals if str(value).strip()]
    if not queries:
        return _error("At least one journal title is required")

    try:
        data = _load_journal_rank_data()
    except FileNotFoundError as exc:
        return _error(str(exc))

    results: List[Dict[str, Any]] = []
    for query in queries:
        entry, match_type = _find_journal_rank(query, data)
        if not entry:
            results.append(
                {
                    "query": query,
                    "found": False,
                    "quartile": None,
                    "match": match_type,
                    "note": "Journal not found in the local SCImago 2024 dataset.",
                }
            )
            continue

        quartile = entry["quartile"]
        item: Dict[str, Any] = {
            "query": query,
            "found": True,
            "title": entry["title"],
            "quartile": quartile,
            "quartile_rank": int(quartile[1]) if quartile else None,
            "sjr": entry["sjr"],
            "h_index": entry["h_index"],
            "scimago_rank": entry["scimago_rank"],
            "publisher": entry["publisher"],
            "issn": entry["issn"],
            "coverage": entry["coverage"],
            "match": match_type,
        }
        if include_categories:
            item["categories"] = entry["categories"]
            item["areas"] = entry["areas"]
        results.append(item)

    return {
        "source": f"SCImago Journal Rank {JOURNAL_RANK_YEAR}",
        "source_year": JOURNAL_RANK_YEAR,
        "dataset": str(JOURNAL_RANK_PATH),
        "count": len(results),
        "results": results,
        "notes": [
            "Quartile is the SCImago 'SJR Best Quartile' field.",
            "Q1 is the highest quartile; Q4 is the lowest.",
            "Quartile is bibliometric context, not a measure of article quality.",
        ],
    }


# --------------------------------------------------------------------------- #
# Local paper library (user-provided PDFs)
# --------------------------------------------------------------------------- #

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
_LIBRARY_CACHE: Dict[str, Dict[str, Any]] = {}

_TITLE_STOPWORDS = set(
    """
    a an the and or of to in on for with by from as at is are was were be been
    this that these those using based study studies research paper article
    ve bir bu da de için ile olan olarak gibi
    """.split()
)


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _title_tokens(value: str) -> set:
    return {
        token
        for token in re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", (value or "").lower())
        if token not in _TITLE_STOPWORDS
    }


def _clean_doi(value: str) -> str:
    doi = (value or "").strip().rstrip(".,;:)]}\"'")
    return normalize_doi(doi)


def _first_page_metadata(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    cached = _LIBRARY_CACHE.get(str(path))
    if cached and cached.get("mtime") == stat.st_mtime and cached.get("size") == stat.st_size:
        return cached

    doi = ""
    title_guess = ""
    first_text = ""
    try:
        with pymupdf.open(str(path)) as document:
            chunks: List[str] = []
            for page_index in range(min(2, document.page_count)):
                try:
                    chunks.append(document.load_page(page_index).get_text("text") or "")
                except Exception:  # noqa: BLE001
                    continue
            first_text = re.sub(r"\s+", " ", "\n".join(chunks)).strip()
            match = _DOI_RE.search(first_text)
            if match:
                doi = _clean_doi(match.group(0))
            if not title_guess:
                try:
                    metadata = document.metadata or {}
                    title_guess = metadata.get("title") or metadata.get("/Title") or ""
                except Exception:  # noqa: BLE001
                    title_guess = ""
            if not title_guess and first_text:
                for line in re.split(r"(?<=[.!?])\s+|\n", first_text):
                    line = line.strip()
                    if 20 <= len(line) <= 300 and not line.lower().startswith(("doi", "http")):
                        title_guess = line
                        break
    except Exception as exc:  # noqa: BLE001
        logger.info("PDF metadata extraction failed for %s: %s", path, exc)

    record = {
        "path": str(path),
        "filename": path.name,
        "doi": doi,
        "title_guess": title_guess,
        "first_text": first_text[:4000],
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }
    _LIBRARY_CACHE[str(path)] = record
    return record


def _library_scan(
    directory: Optional[Path] = None,
    recurse: bool = True,
) -> List[Dict[str, Any]]:
    root = Path(directory).expanduser() if directory else PAPER_LIBRARY_DIR
    if not root.exists():
        return []
    iterator = root.rglob("*") if recurse else root.iterdir()
    paths = sorted(
        (
            path
            for path in iterator
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:300]
    return [_first_page_metadata(path) for path in paths if path.is_file()]


def _title_similarity(left: str, right: str) -> float:
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _match_local_pdf(
    doi: str = "",
    title: str = "",
    directory: Optional[Path] = None,
    recurse: bool = True,
) -> Optional[Dict[str, Any]]:
    records = _library_scan(directory, recurse)
    if not records:
        return None

    doi = normalize_doi(doi)
    doi_token = _normalize_token(doi)
    best: Optional[Dict[str, Any]] = None

    if doi_token:
        for record in records:
            if doi_token in _normalize_token(record["filename"]):
                return {
                    "path": record["path"],
                    "filename": record["filename"],
                    "match": "doi_in_filename",
                    "score": 1.0,
                    "detected_doi": record["doi"] or doi,
                    "title_guess": record["title_guess"],
                }
        for record in records:
            if doi and normalize_doi(record["doi"]) == doi:
                return {
                    "path": record["path"],
                    "filename": record["filename"],
                    "match": "doi_in_pdf_text",
                    "score": 1.0,
                    "detected_doi": record["doi"],
                    "title_guess": record["title_guess"],
                }
        for record in records:
            if doi_token and doi_token in _normalize_token(record["first_text"]):
                return {
                    "path": record["path"],
                    "filename": record["filename"],
                    "match": "doi_in_pdf_text",
                    "score": 0.95,
                    "detected_doi": record["doi"] or doi,
                    "title_guess": record["title_guess"],
                }

    if title:
        for record in records:
            score = max(
                _title_similarity(title, record["title_guess"]),
                _title_similarity(title, record["filename"].replace("_", " ")),
            )
            if score >= 0.55 and (best is None or score > best["score"]):
                best = {
                    "path": record["path"],
                    "filename": record["filename"],
                    "match": "title_similarity",
                    "score": round(score, 3),
                    "detected_doi": record["doi"] or None,
                    "title_guess": record["title_guess"],
                }

    return best


def _annotate_local_pdfs(
    items: Sequence[Dict[str, Any]],
    directory: Optional[Path] = None,
    recurse: bool = True,
) -> None:
    root = Path(directory).expanduser() if directory else PAPER_LIBRARY_DIR
    if not root.exists():
        return
    for item in list(items)[:25]:
        try:
            match = _match_local_pdf(
                item.get("doi") or "", item.get("title") or "", root, recurse
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Local PDF matching failed: %s", exc)
            match = None
        item["local_pdf"] = match["path"] if match else None
        item["local_pdf_match"] = match["match"] if match else None
        item["local_pdf_score"] = match["score"] if match else None


# --------------------------------------------------------------------------- #
# Project registry (shared with the paperqa-local MCP)
# --------------------------------------------------------------------------- #

def _projects_registry() -> Dict[str, Any]:
    """Read the shared projects.json (cached by mtime)."""
    path = LIT_PROJECTS_REGISTRY
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _PROJECTS_CACHE.update({"mtime": None, "data": {}})
        return {}
    if _PROJECTS_CACHE.get("mtime") == mtime and _PROJECTS_CACHE.get("data"):
        return _PROJECTS_CACHE["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.info("Project registry could not be read: %s", exc)
        data = {}
    _PROJECTS_CACHE.update({"mtime": mtime, "data": data})
    return data


def _project_config(name: str) -> Dict[str, Any]:
    registry = _projects_registry()
    projects = registry.get("projects") or {}
    name = (name or "").strip()
    if name not in projects:
        available = ", ".join(sorted(projects)) or "(kayıtlı proje yok)"
        raise KeyError(f"Bilinmeyen proje: {name!r}. Kayıtlı projeler: {available}")
    return projects[name]


def _project_scope(project: Optional[str]) -> Tuple[Optional[Path], bool]:
    """(directory, recurse) — project None means the legacy library folder.

    Projects are isolated: when a project name is given, only that project's
    own PDF folder is scanned, so results never mix across projects.
    """
    if not project:
        return None, True
    config = _project_config(project)
    directory = Path(config["paper_directory"]).expanduser()
    return directory, bool(config.get("include_subdirectories", False))


def _project_analysis_path(config: Dict[str, Any]) -> Optional[Path]:
    """Where a project's analysis_updates JSON lives.

    ``analysis_json`` wins when configured; otherwise the project's own
    ``output_directory/analysis_updates.json`` is used, so every registered
    project can produce and read its audit without extra registry edits.
    """
    configured = config.get("analysis_json")
    if configured:
        return Path(configured).expanduser()
    output = config.get("output_directory") or config.get("paper_directory")
    if output:
        return Path(output).expanduser() / "analysis_updates.json"
    return None


def _citation_band(total: Optional[int]) -> Optional[str]:
    """Rough citation band used in the audit's documents table."""
    if total is None:
        return None
    if total <= 0:
        return "Yok"
    if total <= 10:
        return "Düşük"
    if total <= 50:
        return "Orta"
    if total <= 200:
        return "Yüksek"
    return "Çok yüksek"


def _doi_candidates_from_filename(name: str) -> List[str]:
    """Possible DOIs from a filename (registrant length is ambiguous).

    ``10.117701430343231202923.pdf`` may be ``10.1177/01430343231202923``;
    candidates are generated for 4..9 digit registrant lengths.
    """
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    match = re.match(r"^(10\.)(\d{4,9})(.*)$", stem)
    if not match:
        return []
    run, tail = match.group(2), match.group(3)
    candidates: List[str] = []
    for length in range(4, min(9, len(run)) + 1):
        rest = (run[length:] + tail).strip(" ._-")
        if not rest:
            continue
        doi = f"10.{run[:length]}/{rest}".rstrip(".,;:)]}\"'").lower()
        if doi not in candidates:
            candidates.append(doi)
    return candidates


async def _resolve_filename_doi(record: Dict[str, Any]) -> str:
    """DOI for a library record: first-page text first, then filename candidates.

    Ambiguous filename candidates are validated against Crossref so that
    ``10.1177...`` style SAGE files resolve correctly.
    """
    text_doi = _clean_doi(record.get("doi") or "")
    if text_doi:
        return text_doi
    candidates = _doi_candidates_from_filename(record.get("filename") or "")
    if len(candidates) > 1:
        for candidate in candidates:
            message = await crossref_work(candidate)
            if message:
                return candidate
    return candidates[0] if candidates else ""


_openalex_flags_cache: Dict[str, Dict[str, Any]] = {}


async def _openalex_flags(doi: str) -> Dict[str, Any]:
    """Retraction flag + per-year citation counts from OpenAlex (cached)."""
    key = normalize_doi(doi)
    if not key:
        return {}
    if key in _openalex_flags_cache:
        return _openalex_flags_cache[key]
    payload: Dict[str, Any] = {}
    try:
        response = await _client.get(
            f"https://api.openalex.org/works/doi:{quote(key, safe='')}",
            params={
                "select": "id,doi,is_retracted,cited_by_count,counts_by_year",
                "mailto": MAILTO,
            },
        )
        if response.status_code == 200:
            data = response.json()
            payload = {
                "is_retracted": data.get("is_retracted"),
                "openalex_cited_by": data.get("cited_by_count"),
                "counts_by_year": [
                    {"year": entry.get("year"), "count": entry.get("cited_by_count")}
                    for entry in (data.get("counts_by_year") or [])
                ],
            }
    except Exception as exc:  # noqa: BLE001
        logger.info("OpenAlex flags failed for %s: %s", key, exc)
    _openalex_flags_cache[key] = payload
    return payload


def list_projects() -> Dict[str, Any]:
    """List registered projects with per-project PDF inventory and manifest status.

    Projects come from the shared registry (``~/.literature-mcp/projects.json``); each
    project is isolated (own folder + manifest + PaperQA2 index).  Callers
    should then pass ``project=...`` to read_paper / evidence_check /
    library_status so that lookups stay inside one project.
    """
    registry = _projects_registry()
    projects = registry.get("projects") or {}
    entries: List[Dict[str, Any]] = []
    for name, config in sorted(projects.items()):
        directory = Path(config["paper_directory"]).expanduser()
        recurse = bool(config.get("include_subdirectories", False))
        records = _library_scan(directory, recurse) if directory.exists() else []
        manifest_path = (
            Path(config["manifest"]).expanduser() if config.get("manifest") else None
        )
        manifest_files: List[str] = []
        if manifest_path and manifest_path.exists():
            try:
                with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
                    manifest_files = [
                        row.get("file_location") or ""
                        for row in csv.DictReader(handle)
                    ]
            except Exception as exc:  # noqa: BLE001
                logger.info("Manifest could not be read (%s): %s", manifest_path, exc)
        manifest_set = {value for value in manifest_files if value}
        filenames = {record["filename"] for record in records}
        entries.append(
            {
                "project": name,
                "title": config.get("title"),
                "description": config.get("description"),
                "paper_directory": str(directory),
                "directory_exists": directory.exists(),
                "include_subdirectories": recurse,
                "pdf_files": len(records),
                "files_with_detected_doi": sum(1 for r in records if r["doi"]),
                "manifest": str(manifest_path) if manifest_path else None,
                "manifest_rows": len(manifest_set),
                "files_not_in_manifest": sorted(filenames - manifest_set),
                "index_name": config.get("index_name"),
                "index_directory": config.get("index_directory"),
                "output_directory": config.get("output_directory"),
                "analysis_json": config.get("analysis_json"),
            }
        )
    return {
        "registry": str(LIT_PROJECTS_REGISTRY),
        "registry_exists": LIT_PROJECTS_REGISTRY.exists(),
        "count": len(entries),
        "projects": entries,
        "notes": [
            "Projeler izole kayıtlardır: paper_directory + manifest + PaperQA indeksi.",
            "Yerel metin araçlarına project=... verin; böylece yalnızca o projenin PDF'leri taranır.",
            "project verilmezse eski PAPER_LIBRARY_DIR davranışı korunur.",
        ],
    }


async def project_audit(
    project: str,
    include_quartiles: bool = True,
    check_retractions: bool = True,
    max_dois: int = 50,
) -> Dict[str, Any]:
    """Audit one project's PDFs: DOI detection + metadata + citations + quartiles.

    Per unique DOI it reports: metadata (OpenAlex/Europe PMC, Crossref fallback),
    in which databases the DOI is indexed, Crossref vs OpenAlex citation counts,
    SCImago journal quartile, and (optionally) OpenAlex retraction flags.
    Only this project's folder is scanned; nothing mixes across projects.
    """
    try:
        config = _project_config(project)
    except KeyError as exc:
        return _error(str(exc))
    directory = Path(config["paper_directory"]).expanduser()
    recurse = bool(config.get("include_subdirectories", False))
    if not directory.exists():
        return _error("Proje klasörü bulunamadı", paper_directory=str(directory))

    records = _library_scan(directory, recurse)
    if not records:
        return _error("Proje klasöründe PDF yok", paper_directory=str(directory))

    files: List[Dict[str, Any]] = []
    doi_to_files: Dict[str, List[str]] = {}
    for record in records:
        doi = await _resolve_filename_doi(record)
        files.append(
            {
                "file": record["filename"],
                "path": record["path"],
                "detected_doi": doi or None,
                "title_guess": record["title_guess"] or None,
                "size_mb": round(record["size"] / (1024 * 1024), 2),
            }
        )
        if doi:
            doi_to_files.setdefault(doi, []).append(record["filename"])

    dois = list(doi_to_files)[: max(1, min(int(max_dois), 200))]
    semaphore = asyncio.Semaphore(3)

    async def audit_one(doi: str, number: int) -> Dict[str, Any]:
        async with semaphore:
            row: Dict[str, Any] = {
                "no": number,
                "doi": doi,
                "local_files": doi_to_files.get(doi, []),
            }
            try:
                meta = await _metadata_for(doi)
            except Exception as exc:  # noqa: BLE001
                meta = {}
                row["metadata_error"] = str(exc)
            row.update(
                {
                    "title": meta.get("title"),
                    "authors_short": _authors_short(meta.get("authors")),
                    "year": meta.get("year"),
                    "journal": meta.get("journal"),
                    "publisher": meta.get("publisher_label") or meta.get("publisher"),
                    "pmid": meta.get("pmid"),
                    "open_access": meta.get("open_access") if "open_access" in meta else meta.get("is_oa"),
                }
            )
            try:
                provenance = await doi_provenance(doi)
                checks = provenance.get("checks") or {}
            except Exception as exc:  # noqa: BLE001
                checks = {}
                row["provenance_error"] = str(exc)
            for source_name in ("crossref", "openalex", "europepmc", "pubmed"):
                check = checks.get(source_name) or {}
                row[f"{source_name}_found"] = bool(check.get("found"))
            crossref_citations = (checks.get("crossref") or {}).get("cited_by")
            openalex_citations = (checks.get("openalex") or {}).get("cited_by")
            row["crossref_citations"] = crossref_citations
            row["openalex_citations"] = openalex_citations
            if crossref_citations is not None and openalex_citations is not None:
                row["citations_difference"] = openalex_citations - crossref_citations
            row["found_in"] = provenance.get("found_in")
            if include_quartiles and row.get("journal"):
                try:
                    quartiles = await journal_rank(
                        [str(row["journal"])], include_categories=False
                    )
                    results = quartiles.get("results") or []
                    if results and results[0].get("found"):
                        row["scimago_quartile"] = results[0].get("quartile")
                except Exception as exc:  # noqa: BLE001
                    logger.info("Quartile lookup failed for %s: %s", doi, exc)
            if check_retractions:
                flags = await _openalex_flags(doi)
                row["is_retracted"] = flags.get("is_retracted")
                row["counts_by_year"] = flags.get("counts_by_year")
            return row

    audits = await asyncio.gather(
        *(audit_one(doi, number) for number, doi in enumerate(dois, start=1))
    )

    no_doi_files = [f["file"] for f in files if not f["detected_doi"]]
    return {
        "project": project,
        "title": config.get("title"),
        "paper_directory": str(directory),
        "files": files,
        "no_doi_files": no_doi_files,
        "dois": audits,
        "summary": {
            "pdf_files": len(files),
            "files_with_doi": len(files) - len(no_doi_files),
            "unique_dois": len(dois),
            "missing_metadata": sum(1 for a in audits if not a.get("title")),
            "retracted": sum(1 for a in audits if a.get("is_retracted")),
        },
        "notes": [
            "Metadata: OpenAlex + Europe PMC (yedek: Crossref); atıf sayıları Crossref ve OpenAlex'ten.",
            "is_retracted OpenAlex kaydından gelir; null = bilinmiyor.",
            "Bu denetim yalnızca bu projenin klasörünü tarar; diğer projelere dokunmaz.",
        ],
    }


def _extract_pdf_pages(
    path: Path,
    max_pages: int = PDF_MAX_PAGES,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> Tuple[int, List[Dict[str, Any]]]:
    with pymupdf.open(str(path)) as document:
        page_count = document.page_count

        if page_start or page_end:
            start = max(1, int(page_start or 1))
            end = min(page_count, int(page_end or page_count))
            indexes = list(range(start - 1, max(start - 1, end)))
        else:
            indexes = list(range(min(page_count, max(1, max_pages))))

        pages: List[Dict[str, Any]] = []
        for index in indexes:
            try:
                text = document.load_page(index).get_text("text") or ""
            except Exception as exc:  # noqa: BLE001
                text = ""
                logger.info("PDF page %s extraction failed in %s: %s", index + 1, path, exc)
            pages.append(
                {
                    "page": index + 1,
                    "text": re.sub(r"[ \t]+", " ", text).strip(),
                }
            )
        return page_count, pages


def analysis_updates(
    doi: Optional[str] = None,
    entry_id: Optional[int] = None,
    query: Optional[str] = None,
    include_entries: bool = True,
    include_corrections: bool = True,
    include_matrices: bool = True,
    include_gap_analysis: bool = True,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the saved full-text citation audit and its evidence matrices.

    The audit is a local, versioned JSON record.  It is not a literature
    search: it documents how abstract-level claims were checked against the
    page-level full text and which sentences were used in the draft.  The
    same file also stores the claim-evidence matrix, the methodological
    quality/risk-of-bias assessment, the source budget, and an optional gap
    analysis so they remain queryable from the MCP server.

    Pass ``project`` to read that project's own ``analysis_json`` file from the
    shared registry; without it the legacy global audit file is used.
    """
    path = ANALYSIS_UPDATES_PATH
    if project:
        try:
            config = _project_config(project)
        except KeyError as exc:
            return _error(str(exc))
        resolved = _project_analysis_path(config)
        if not resolved:
            return _error(
                "Bu proje için analiz dosyası yolu tanımlı değil",
                project=project,
                hint=(
                    "Proje kaydına analysis_json ya da output_directory ekleyin; "
                    "ardından proje için analysis_updates dosyasını oluşturun."
                ),
            )
        path = resolved
    if not path.exists():
        hint = (
            "Bu proje için analysis_updates dosyasını oluşturun."
            if project
            else "Set ANALYSIS_UPDATES_JSON or add analysis_json to the project registry."
        )
        return _error("analysis updates file not found", path=str(path), hint=hint)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return _error("analysis updates file could not be read", path=str(path), detail=str(exc))

    entries = list(data.get("entries") or [])
    documents = list(data.get("documents") or [])
    corrections = list(data.get("corrections") or [])
    claim_matrix = list(data.get("claim_matrix") or [])
    risk_of_bias = list(data.get("risk_of_bias") or [])
    source_budget = list(data.get("source_budget") or [])
    gap_analysis = dict(data.get("gap_analysis") or {})

    normalized_doi = normalize_doi(doi) if doi else ""
    if normalized_doi:
        entries = [e for e in entries if normalize_doi(e.get("doi")) == normalized_doi]
        documents = [d for d in documents if normalize_doi(d.get("doi")) == normalized_doi]
        corrections = [c for c in corrections if normalize_doi(c.get("doi")) == normalized_doi]
        claim_matrix = [c for c in claim_matrix if normalize_doi(c.get("doi")) == normalized_doi]
        risk_of_bias = [r for r in risk_of_bias if normalize_doi(r.get("doi")) == normalized_doi]

    if entry_id is not None:
        try:
            wanted = int(entry_id)
        except (TypeError, ValueError):
            return _error("entry_id must be an integer")
        entries = [e for e in entries if int(e.get("id", -1)) == wanted]
        claim_matrix = [c for c in claim_matrix if int(c.get("id", -1)) == wanted]

    if query:
        needle = query.strip().casefold()
        if needle:
            def _haystack(item: Dict[str, Any]) -> str:
                parts: List[str] = [
                    str(item.get("citation") or item.get("heading") or ""),
                    str(item.get("constructed_sentence") or ""),
                    str(item.get("notes") or ""),
                ]
                for evidence in item.get("full_text_evidence") or []:
                    parts.append(str(evidence.get("original") or ""))
                    parts.append(str(evidence.get("turkish") or ""))
                parts.extend(str(s) for s in (item.get("original_sentences") or []))
                return " ".join(parts).casefold()

            entries = [e for e in entries if needle in _haystack(e)]
            documents = [
                d for d in documents
                if needle in " ".join(
                    str(d.get(k) or "") for k in ("authors", "journal", "doi", "quartile")
                ).casefold()
            ]
            corrections = [
                c for c in corrections
                if needle in " ".join(
                    str(c.get(k) or "") for k in ("author_year", "abstract_claim", "full_text_finding", "action", "doi")
                ).casefold()
            ]
            claim_matrix = [
                c for c in claim_matrix
                if needle in " ".join(
                    str(c.get(k) or "") for k in (
                        "id", "paragraph", "doi", "citation", "claim", "key_evidence",
                        "evidence_type", "support", "strength", "decision",
                    )
                ).casefold()
            ]
            risk_of_bias = [
                r for r in risk_of_bias
                if needle in " ".join(
                    str(r.get(k) or "") for k in (
                        "doi", "study", "design", "strengths", "limitations",
                        "overall", "chapter_implication",
                    )
                ).casefold()
            ]
            source_budget = [
                b for b in source_budget
                if needle in " ".join(
                    str(b.get(k) or "") for k in (
                        "level", "words", "ideal_sources", "max_sources", "note",
                    )
                ).casefold()
            ]
            if gap_analysis:
                gap_analysis["comparison"] = [
                    row for row in (gap_analysis.get("comparison") or [])
                    if needle in " ".join(
                        str(row.get(k) or "") for k in (
                            "capability", "reference", "local", "gap", "chapter_relevance",
                        )
                    ).casefold()
                ]
                gap_analysis["chapter_improvements"] = [
                    row for row in (gap_analysis.get("chapter_improvements") or [])
                    if needle in " ".join(
                        str(row.get(k) or "") for k in (
                            "priority", "improvement", "status", "detail",
                        )
                    ).casefold()
                ]

    result: Dict[str, Any] = {
        "revision": data.get("revision"),
        "schema": data.get("schema"),
        "matrix_revision": data.get("matrix_revision"),
        "entry_format": data.get("entry_format"),
        "topic": data.get("topic"),
        "generated_at": data.get("generated_at"),
        "source_policy": data.get("source_policy"),
        "path": str(path),
        "entry_count": len(entries),
        "evidence_count": sum(len(e.get("full_text_evidence") or []) for e in entries),
        "document_count": len(documents),
        "correction_count": len(corrections),
        "claim_count": len(claim_matrix),
        "risk_of_bias_count": len(risk_of_bias),
        "source_budget_count": len(source_budget),
        "documents": documents,
    }
    if include_entries:
        result["entries"] = entries
    if include_corrections:
        result["corrections"] = corrections
    if include_matrices:
        result["claim_matrix"] = claim_matrix
        result["risk_of_bias"] = risk_of_bias
        result["source_budget"] = source_budget
    if include_gap_analysis:
        result["gap_analysis"] = gap_analysis
    for key in ("report_title", "corrected_text", "limitations", "next_steps"):
        if key in data:
            result[key] = data.get(key)
    return result


def library_status(project: Optional[str] = None) -> Dict[str, Any]:
    """List local PDFs, optionally scoped to a single registered project.

    With ``project`` given, only that project's folder is scanned, so the
    inventory never mixes files from other projects.  Without it, the legacy
    PAPER_LIBRARY_DIR folder is scanned (recursively).
    """
    try:
        directory, recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    root = directory or PAPER_LIBRARY_DIR
    records = _library_scan(directory, recurse)
    files = [
        {
            "path": record["path"],
            "filename": record["filename"],
            "detected_doi": record["doi"] or None,
            "title_guess": record["title_guess"] or None,
            "size_mb": round(record["size"] / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(record["mtime"], tz=timezone.utc).isoformat(),
        }
        for record in records
    ]
    notes = [
        "Place PDFs in the library folder; filenames containing the DOI work best.",
        "The DOI is also detected from the first two pages of each PDF.",
    ]
    if project:
        notes.append(
            f"Yalnızca {project!r} projesinin klasörü tarandı; diğer projeler dışarıda bırakıldı."
        )
    return {
        "project": project or None,
        "library_dir": str(root),
        "exists": root.exists(),
        "recurse_subdirectories": recurse,
        "count": len(files),
        "with_detected_doi": sum(1 for f in files if f["detected_doi"]),
        "files": files,
        "notes": notes,
    }


async def read_paper(
    identifier: Optional[str] = None,
    id_type: str = "doi",
    pdf_path: Optional[str] = None,
    max_chars: int = READ_MAX_CHARS,
    max_pages: int = PDF_MAX_PAGES,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Read one local PDF, optionally scoped to a single registered project.

    With ``project`` given, DOI/title matching only searches that project's
    folder and an explicit ``pdf_path`` outside the project folder is rejected,
    so lookups never leak across projects.
    """
    try:
        scope_dir, scope_recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    if not identifier and not pdf_path:
        return library_status(project)

    identifier = (identifier or "").strip()
    id_type = (id_type or "doi").lower()
    meta: Dict[str, Any] = {}
    doi = ""
    title = ""

    if identifier:
        if id_type == "doi":
            doi = normalize_doi(identifier)
        elif id_type == "title":
            title = identifier
        elif id_type != "pmid":
            return _error("id_type must be doi, pmid, or title")
        if id_type != "title":
            maybe_meta = await _metadata_for(identifier, id_type)
            if maybe_meta:
                meta = maybe_meta
                doi = doi or normalize_doi(meta.get("doi"))
                title = title or (meta.get("title") or "")

    if pdf_path:
        path = Path(pdf_path).expanduser().resolve()
        if not path.exists():
            return _error("PDF file not found", pdf_path=str(path))
        if scope_dir is not None:
            try:
                path.relative_to(scope_dir.resolve())
            except ValueError:
                return _error(
                    "Bu PDF seçilen projenin klasöründe değil",
                    project=project,
                    pdf_path=str(path),
                    project_dir=str(scope_dir),
                )
        match = {
            "path": str(path),
            "filename": path.name,
            "match": "explicit_path",
            "score": 1.0,
            "detected_doi": doi or None,
            "title_guess": title or None,
        }
    else:
        match = _match_local_pdf(doi, title, scope_dir, scope_recurse)
        if not match:
            return _error(
                "No matching PDF found in the local library",
                identifier=identifier,
                doi=doi or None,
                title=title or None,
                project=project or None,
                library_dir=str(scope_dir or PAPER_LIBRARY_DIR),
                notes=[
                    "Place the full-text PDF in the library folder.",
                    "Using filenames that contain the DOI gives the most reliable match.",
                    "Call library_status to inspect the folder.",
                ],
            )
        path = Path(match["path"])

    if path.suffix.lower() != ".pdf":
        return _error("Selected file is not a PDF", path=str(path))
    try:
        page_count, pages = _extract_pdf_pages(
            path,
            max_pages=max_pages,
            page_start=page_start,
            page_end=page_end,
        )
    except Exception as exc:  # noqa: BLE001
        return _error("PDF parsing failed", path=str(path), detail=str(exc))

    full_text = "\n\n".join(page["text"] for page in pages if page["text"])
    truncated = len(full_text) > max_chars
    notes: List[str] = ["Text was read from the local library; nothing was downloaded."]
    if not full_text.strip():
        notes.append("No extractable text found; the PDF may be scanned or image-only.")

    return {
        "identifier": identifier or None,
        "doi": doi or meta.get("doi") or match.get("detected_doi"),
        "pmid": meta.get("pmid"),
        "title": meta.get("title") or match.get("title_guess"),
        "authors": meta.get("authors"),
        "year": meta.get("year"),
        "journal": meta.get("journal"),
        "path": str(path),
        "filename": path.name,
        "match": match.get("match"),
        "match_score": match.get("score"),
        "detected_doi": match.get("detected_doi"),
        "page_count": page_count,
        "pages_read": len(pages),
        "page_range": [pages[0]["page"], pages[-1]["page"]] if pages else [],
        "truncated": truncated,
        "text": full_text[:max_chars],
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# Deep research (heuristic multi-facet DOI discovery)
# --------------------------------------------------------------------------- #

def _research_plan(
    question: str,
    subtopics: Optional[Sequence[str]],
    max_subtopics: int,
) -> List[Dict[str, str]]:
    if subtopics:
        return [
            {"facet": "custom", "query": str(topic).strip()}
            for topic in subtopics
            if str(topic).strip()
        ][: max(1, min(max_subtopics, 8))]

    base = question.strip()
    facets = [
        ("overview", base),
        ("reviews", f"{base} systematic review"),
        ("prevalence", f"{base} prevalence"),
        ("risk_factors", f"{base} risk factors"),
        ("interventions", f"{base} intervention"),
        ("qualitative", f"{base} qualitative"),
    ]
    return [
        {"facet": name, "query": query}
        for name, query in facets[: max(1, min(max_subtopics, len(facets)))]
    ]


async def deep_research(
    question: str,
    subtopics: Optional[Sequence[str]] = None,
    max_subtopics: int = 5,
    results_per_topic: int = 5,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    sources: Optional[Sequence[str]] = None,
    priority_only: bool = True,
    allowed_publishers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    if not question.strip():
        return _error("question is required")

    plan = _research_plan(question, subtopics, max_subtopics)
    semaphore = asyncio.Semaphore(3)

    async def run(entry: Dict[str, str]) -> Dict[str, Any]:
        async with semaphore:
            payload = await search_literature(
                entry["query"],
                sources=sources,
                limit=results_per_topic,
                year_from=year_from,
                year_to=year_to,
                priority_only=priority_only,
                allowed_publishers=allowed_publishers,
            )
            payload["facet"] = entry["facet"]
            return payload

    batches = await asyncio.gather(*(run(entry) for entry in plan), return_exceptions=True)

    merged: Dict[str, Dict[str, Any]] = {}
    notes: List[str] = []
    for entry, batch in zip(plan, batches):
        if isinstance(batch, Exception):
            notes.append(f"{entry['facet']}: {batch}")
            continue
        notes.extend(batch.get("notes") or [])
        for item in batch.get("results") or []:
            key = _dedupe_key(item)
            if not key or key == "title:":
                continue
            if key in merged:
                existing = merged[key]
                _merge(existing, item)
                if entry["facet"] not in existing["matched_subtopics"]:
                    existing["matched_subtopics"].append(entry["facet"])
            else:
                item["matched_subtopics"] = [entry["facet"]]
                merged[key] = item

    items = list(merged.values())
    for item in items:
        _finalize_links(item)
    await enrich_sciencedirect_links(items, limit=min(10, MAX_ENRICH))
    _annotate_local_pdfs(items)
    items.sort(key=_rank)

    return {
        "question": question,
        "plan": plan,
        "count": len(items[:50]),
        "total_found": len(items),
        "priority_only": priority_only,
        "allowed_publishers": _normalized_allowed_publishers(allowed_publishers),
        "notes": sorted(set(notes)) + [
            "Heuristic query decomposition; pass explicit subtopics for full control.",
            "local_pdf shows which results already have a full text in the library.",
        ],
        "results": items[:50],
    }


# --------------------------------------------------------------------------- #
# Study comparison (heuristic extraction)
# --------------------------------------------------------------------------- #

_DESIGN_PATTERNS = [
    (r"\bsystematic review\b", "Systematic review"),
    (r"\bmeta-analys[ie]s\b", "Meta-analysis"),
    (r"\brandomi[sz]ed controlled trial\b|\bRCT\b", "Randomized controlled trial"),
    (r"\bcluster[- ]randomi[sz]ed\b", "Cluster-randomized trial"),
    (r"\bquasi[- ]experimental\b", "Quasi-experimental study"),
    (r"\bcohort\b", "Cohort study"),
    (r"\blongitudinal\b", "Longitudinal study"),
    (r"\bcross[- ]sectional\b", "Cross-sectional study"),
    (r"\bcase[- ]control\b", "Case-control study"),
    (r"\bmixed[- ]methods\b", "Mixed-methods study"),
    (r"\bqualitative\b", "Qualitative study"),
    (r"\bsurvey\b", "Survey"),
]

_RESULT_KEYWORDS = [
    "result", "finding", "showed", "found", "associated", "significant",
    "effect", "improved", "increased", "decreased", "higher", "lower",
]
_LIMITATION_KEYWORDS = [
    "limitation", "limited", "generaliz", "caution", "bias", "small sample",
    "cannot", "cross-sectional", "self-report",
]


def _extract_design(text: str) -> str:
    found: List[str] = []
    for pattern, label in _DESIGN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE) and label not in found:
            found.append(label)
    return "; ".join(found) if found else "Not extracted"


def _extract_sample(text: str) -> str:
    patterns = [
        r"(?:N|n)\s*=\s*[\d,]+",
        r"[\d,]+\s+(?:participants|students|teachers|adolescents|children|patients|respondents|caregivers|parents)",
        r"sample of\s+[\d,]+",
        r"[\d,]+\s+(?:high school|middle school|primary school|university|college)\s+students",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            sentence = next(
                (s for s in _split_sentences(text) if match.group(0).lower() in s.lower()),
                match.group(0),
            )
            return sentence[:500]
    return "Not extracted"


def _best_sentences(text: str, keywords: Sequence[str], max_n: int = 2) -> List[str]:
    sentences = _split_sentences(text)
    scored: List[Tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        low = sentence.lower()
        score = sum(1 for keyword in keywords if keyword in low)
        if score:
            scored.append((score, -index, sentence))
    scored.sort(reverse=True)
    selected: List[str] = []
    for _, _, sentence in scored:
        if sentence not in selected:
            selected.append(sentence[:700])
        if len(selected) >= max_n:
            break
    return selected


async def _study_text(
    study: Dict[str, Any],
    directory: Optional[Path] = None,
    recurse: bool = True,
) -> Tuple[str, str, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (text, source, pages, local_match)."""
    doi = study.get("doi") or ""
    title = study.get("title") or ""
    match = _match_local_pdf(doi, title, directory, recurse)
    if match:
        try:
            _, pages = _extract_pdf_pages(Path(match["path"]), max_pages=PDF_MAX_PAGES)
            text = "\n\n".join(page["text"] for page in pages if page["text"])
            if text.strip():
                return text, "local_pdf", pages, match
        except Exception as exc:  # noqa: BLE001
            logger.info("Local PDF read failed for %s: %s", doi, exc)
    abstract = study.get("abstract") or ""
    pages = [{"page": None, "text": abstract}] if abstract else []
    return abstract, "abstract", pages, None


def _compare_one(study: Dict[str, Any], text: str, text_source: str, match: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "doi": study.get("doi"),
        "pmid": study.get("pmid"),
        "title": study.get("title"),
        "authors": study.get("authors"),
        "year": study.get("year"),
        "journal": study.get("journal"),
        "design": _extract_design(text),
        "sample": _extract_sample(text),
        "results": _best_sentences(text, _RESULT_KEYWORDS, max_n=2),
        "limitations": _best_sentences(text, _LIMITATION_KEYWORDS, max_n=2),
        "text_source": text_source,
        "local_pdf": match["path"] if match else None,
        "links": study.get("links"),
        "source": study.get("source"),
    }


async def compare_studies(
    identifiers: Optional[Sequence[str]] = None,
    query: Optional[str] = None,
    limit: int = 6,
    sources: Optional[Sequence[str]] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare studies; local full texts are looked up inside one project only.

    ``project`` scopes the PDF matching to that project's folder so studies
    from different projects are never mixed.
    """
    try:
        scope_dir, scope_recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    limit = max(1, min(limit, 12))
    studies: List[Dict[str, Any]] = []
    notes: List[str] = []

    if identifiers:
        for identifier in identifiers[:limit]:
            identifier = str(identifier).strip()
            if not identifier:
                continue
            id_type = "pmid" if identifier.isdigit() else "doi"
            item = await _metadata_for(identifier, id_type)
            if not item:
                item = {
                    "doi": normalize_doi(identifier) if id_type == "doi" else None,
                    "pmid": identifier if id_type == "pmid" else None,
                    "title": None,
                    "authors": [],
                    "year": None,
                    "journal": None,
                    "abstract": None,
                    "source": "local_library",
                }
                match = _match_local_pdf(
                    item.get("doi") or "", "", scope_dir, scope_recurse
                )
                if not match:
                    notes.append(f"Metadata and local PDF not found for {identifier}")
                    continue
                item["local_pdf"] = match["path"]
                item["title"] = match.get("title_guess")
                notes.append(f"Using local PDF only for {identifier}")
            studies.append(item)
    elif query:
        payload = await search_literature(
            query, sources=sources, limit=limit, project=project
        )
        studies = payload.get("results") or []
        notes.extend(payload.get("notes") or [])
    else:
        return _error("Provide identifiers or query")

    if not studies:
        return _error("No studies found", identifiers=list(identifiers or []), query=query)

    rows: List[Dict[str, Any]] = []
    notes.append(
        "Design/sample/results/limitations are extracted heuristically; verify against the PDF."
    )
    for study in studies[:limit]:
        text, text_source, _, match = await _study_text(study, scope_dir, scope_recurse)
        rows.append(_compare_one(study, text, text_source, match))

    header = "| Study | Design | Sample | Key findings | Limitations |"
    separator = "|---|---|---|---|---|"
    table_lines = [header, separator]
    for row in rows:
        study_label = f"{_authors_short(row.get('authors'))} ({row.get('year') or 'n.d.'})"
        results = " ".join(row.get("results") or []) or "Not extracted"
        limitations = " ".join(row.get("limitations") or []) or "Not extracted"
        table_lines.append(
            "| "
            + " | ".join(
                _escape_md(value)[:320]
                for value in (
                    study_label,
                    row.get("design"),
                    row.get("sample"),
                    results,
                    limitations,
                )
            )
            + " |"
        )

    return {
        "count": len(rows),
        "table_markdown": "\n".join(table_lines),
        "studies": rows,
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# Evidence check (lexical TF-IDF matching)
# --------------------------------------------------------------------------- #

_STOPWORDS = set(
    """
    a an the and or but if then than that this these those of to in on for with by from as at is are was were be been being
    it its their they we you he she his her our not no can could may might will would should do does did have has had
    this that there here also into about more most other such only own same so than too very just
    ve bir bu da de için ile olan olarak gibi daha çok az en veya ama fakat ancak ise her hem ya
    """.split()
)


def _tokens(text: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", (text or "").lower())
        if token not in _STOPWORDS and not token.isdigit()
    ]


def _vectorize_sentences(
    sentences: Sequence[str],
) -> Tuple[List[Dict[str, float]], Dict[str, float]]:
    tokenized = [_tokens(sentence) for sentence in sentences]
    document_frequency: Counter = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    total = max(1, len(sentences))
    idf = {
        term: math.log((1 + total) / (1 + frequency)) + 1.0
        for term, frequency in document_frequency.items()
    }
    vectors: List[Dict[str, float]] = []
    for tokens in tokenized:
        counts = Counter(tokens)
        if not counts:
            vectors.append({})
            continue
        length = sum(counts.values())
        vectors.append(
            {
                term: (count / length) * idf.get(term, 1.0)
                for term, count in counts.items()
            }
        )
    return vectors, idf


def _cosine(left: Dict[str, float], right: Dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[term] * right[term] for term in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _verdict(score: float, coverage: float) -> str:
    """Conservative lexical verdict; coverage penalises missing claim terms."""
    if score >= 0.40 and coverage >= 0.65:
        return "strong"
    if score >= 0.25 and coverage >= 0.45:
        return "moderate"
    if score >= 0.12 or coverage >= 0.25:
        return "weak"
    return "not_found"


async def evidence_check(
    claims: Sequence[str],
    identifier: Optional[str] = None,
    id_type: str = "doi",
    pdf_path: Optional[str] = None,
    text: Optional[str] = None,
    top_k: int = 3,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Score claims against one paper's sentences (lexical TF-IDF).

    ``project`` scopes the local PDF lookup to that project's folder and
    rejects explicit pdf_path values outside it, so evidence never comes from
    a different project by accident.
    """
    try:
        scope_dir, scope_recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    claims = [str(claim).strip() for claim in claims if str(claim).strip()]
    if not claims:
        return _error("At least one claim is required")

    paper: Dict[str, Any] = {}
    pages: List[Dict[str, Any]] = []
    text_source = "provided_text"

    if text:
        pages = [{"page": None, "text": text}]
    elif pdf_path:
        path = Path(pdf_path).expanduser().resolve()
        if not path.exists():
            return _error("PDF file not found", pdf_path=str(path))
        if scope_dir is not None:
            try:
                path.relative_to(scope_dir.resolve())
            except ValueError:
                return _error(
                    "Bu PDF seçilen projenin klasöründe değil",
                    project=project,
                    pdf_path=str(path),
                    project_dir=str(scope_dir),
                )
        try:
            _, pages = _extract_pdf_pages(path, max_pages=PDF_MAX_PAGES)
        except Exception as exc:  # noqa: BLE001
            return _error("PDF parsing failed", detail=str(exc))
        text_source = "explicit_pdf"
    else:
        if not identifier:
            return _error("Provide text, identifier, or pdf_path")
        paper = await _metadata_for(identifier, id_type)
        study = paper if paper else {"doi": identifier if id_type == "doi" else None, "title": identifier if id_type == "title" else None}
        _, text_source, pages, match = await _study_text(study, scope_dir, scope_recurse)
        if match:
            paper["local_pdf"] = match["path"]

    sentences: List[Dict[str, Any]] = []
    for page in pages:
        for sentence in _split_sentences(page.get("text")):
            sentences.append({"text": sentence, "page": page.get("page")})
    if not sentences:
        return _error(
            "No extractable sentences found",
            identifier=identifier,
            local_pdf=paper.get("local_pdf"),
        )

    sentence_texts = [sentence["text"] for sentence in sentences]
    sentence_vectors, idf = _vectorize_sentences(sentence_texts)
    sentence_token_sets = [set(_tokens(text)) for text in sentence_texts]

    results: List[Dict[str, Any]] = []
    for claim in claims:
        claim_tokens = _tokens(claim)
        claim_token_set = set(claim_tokens)
        claim_counts = Counter(claim_tokens)
        if claim_counts:
            length = sum(claim_counts.values())
            claim_vector = {
                term: (count / length) * idf.get(term, 1.0)
                for term, count in claim_counts.items()
            }
        else:
            claim_vector = {}

        scored = []
        for index, vector in enumerate(sentence_vectors):
            cosine = _cosine(claim_vector, vector)
            coverage = (
                len(claim_token_set & sentence_token_sets[index]) / len(claim_token_set)
                if claim_token_set
                else 0.0
            )
            combined = 0.6 * cosine + 0.4 * coverage
            scored.append((index, cosine, coverage, combined))
        scored.sort(key=lambda row: row[3], reverse=True)
        top = [
            {
                "text": sentences[index]["text"],
                "page": sentences[index]["page"],
                "score": round(cosine, 4),
                "coverage": round(coverage, 4),
                "combined": round(combined, 4),
            }
            for index, cosine, coverage, combined in scored[: max(1, min(top_k, 10))]
            if combined > 0
        ]
        best = top[0]["combined"] if top else 0.0
        best_coverage = top[0]["coverage"] if top else 0.0
        results.append(
            {
                "claim": claim,
                "verdict": _verdict(best, best_coverage),
                "best_score": best,
                "best_coverage": best_coverage,
                "evidence": top,
            }
        )

    return {
        "identifier": identifier,
        "doi": paper.get("doi"),
        "pmid": paper.get("pmid"),
        "title": paper.get("title"),
        "local_pdf": paper.get("local_pdf"),
        "text_source": text_source,
        "claims": results,
        "notes": [
            "Lexical TF-IDF overlap only; this is not a semantic entailment or fact-checking model.",
            "A high score means the paper contains similar wording, not that the claim is true.",
        ],
    }


# --------------------------------------------------------------------------- #
# Review export
# --------------------------------------------------------------------------- #

def _review_markdown(review: Dict[str, Any]) -> str:
    lines = [
        f"# {review['title']}",
        "",
        f"_Generated: {review['generated_at']}_",
        "",
    ]
    for section in review.get("sections") or []:
        heading = section.get("heading") or "Section"
        body = section.get("body") or ""
        lines.extend([f"## {heading}", "", str(body).strip(), ""])

    references = review.get("references") or []
    if references:
        lines.extend(["## References", ""])
        for index, ref in enumerate(references, 1):
            authors = ", ".join(ref.get("authors") or []) or "Unknown authors"
            year = ref.get("year") or "n.d."
            title = ref.get("title") or ""
            journal = ref.get("journal") or ""
            doi = normalize_doi(ref.get("doi"))
            url = ref.get("url") or (f"https://doi.org/{doi}" if doi else "")
            line = f"{index}. **{authors}** ({year}). *{title}*. {journal}."
            if url:
                line += f" [Link]({url})"
            lines.append(line)
        lines.append("")

    claims = review.get("claims") or []
    if claims:
        lines.extend(
            [
                "## Evidence map",
                "",
                "| Claim | Verdict | Score | Evidence | Source |",
                "|---|---|---|---|---|",
            ]
        )
        for claim in claims:
            evidence = claim.get("evidence") or []
            first = evidence[0] if evidence else {}
            source = claim.get("doi") or claim.get("identifier") or ""
            lines.append(
                "| "
                + " | ".join(
                    _escape_md(value)[:320]
                    for value in (
                        claim.get("claim"),
                        claim.get("verdict"),
                        claim.get("best_score"),
                        first.get("text"),
                        source,
                    )
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _review_csv(review: Dict[str, Any]) -> str:
    buffer = io.StringIO()
    claims = review.get("claims") or []
    references = review.get("references") or []

    if claims:
        fieldnames = [
            "claim", "verdict", "score", "evidence", "page",
            "doi", "title", "year", "journal", "url",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for claim in claims:
            evidence = claim.get("evidence") or []
            first = evidence[0] if evidence else {}
            doi = normalize_doi(claim.get("doi") or "")
            writer.writerow(
                {
                    "claim": claim.get("claim"),
                    "verdict": claim.get("verdict"),
                    "score": claim.get("best_score"),
                    "evidence": first.get("text"),
                    "page": first.get("page"),
                    "doi": doi,
                    "title": claim.get("title"),
                    "year": claim.get("year"),
                    "journal": claim.get("journal"),
                    "url": f"https://doi.org/{doi}" if doi else "",
                }
            )
    else:
        fieldnames = ["authors", "year", "title", "journal", "doi", "url"]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for ref in references:
            doi = normalize_doi(ref.get("doi"))
            writer.writerow(
                {
                    "authors": "; ".join(ref.get("authors") or []),
                    "year": ref.get("year"),
                    "title": ref.get("title"),
                    "journal": ref.get("journal"),
                    "doi": doi,
                    "url": ref.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                }
            )
    return buffer.getvalue()


async def export_review(
    title: str,
    sections: Optional[Sequence[Dict[str, Any]]] = None,
    content: Optional[str] = None,
    references: Optional[Sequence[Dict[str, Any]]] = None,
    claims: Optional[Sequence[Dict[str, Any]]] = None,
    format: str = "markdown",
    filename: Optional[str] = None,
    output_path: Optional[str] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    if not title.strip():
        return _error("title is required")

    fmt = (format or "markdown").lower()
    if fmt in ("md", "markdown"):
        fmt = "markdown"
        extension = ".md"
        encoding = "utf-8"
    elif fmt == "csv":
        extension = ".csv"
        encoding = "utf-8-sig"
    elif fmt == "json":
        extension = ".json"
        encoding = "utf-8"
    else:
        return _error("format must be markdown, csv, or json")

    review: Dict[str, Any] = {
        "title": title.strip(),
        "generated_at": _iso_now(),
        "sections": list(sections or []),
        "references": list(references or []),
        "claims": list(claims or []),
    }
    if content and not review["sections"]:
        review["sections"] = [{"heading": "Review", "body": content}]

    if fmt == "markdown":
        payload = _review_markdown(review)
    elif fmt == "csv":
        payload = _review_csv(review)
    else:
        payload = json.dumps(review, ensure_ascii=False, indent=2) + "\n"

    if project:
        config = _project_config(project)
        base_dir = Path(
            config.get("output_directory") or config["paper_directory"]
        ).expanduser().resolve()
    else:
        base_dir = REVIEW_OUTPUT_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    def _stem(value: str) -> str:
        value = value.strip()
        return value[: -len(extension)] if value.lower().endswith(extension) else value

    if output_path:
        path = Path(output_path).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        path = path.resolve()
        if path.is_dir():
            path = path / (_safe_slug(_stem(filename or title)) + extension)
        try:
            path.relative_to(base_dir)
        except ValueError:
            return _error(
                (
                    "output_path must be inside the project output directory"
                    if project
                    else "output_path must be inside REVIEW_OUTPUT_DIR"
                ),
                output_dir=str(base_dir),
                output_path=str(path),
            )
    elif filename:
        name = _safe_slug(_stem(filename)) + extension
        path = base_dir / name
    else:
        path = base_dir / f"{_safe_slug(title)}-{timestamp}{extension}"

    if path.suffix.lower() != extension:
        path = path.with_suffix(extension)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding=encoding)

    result = {
        "path": str(path),
        "format": fmt,
        "bytes": len(payload.encode(encoding)),
        "references_count": len(review["references"]),
        "claims_count": len(review["claims"]),
        "title": review["title"],
    }
    if project:
        result["project"] = project
        result["output_directory"] = str(base_dir)
    return result


# --------------------------------------------------------------------------- #
# Tool schemas and handlers (registered by unified.py)
# --------------------------------------------------------------------------- #

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
                "Find DOIs and metadata across OpenAlex, PubMed, Europe PMC and Crossref. "
                "By default only records with a real publisher link from the allowed set "
                "are returned (Ovid LWW, ScienceDirect, SpringerLink, Wiley, Taylor & Francis). "
                "Adds local_pdf when a matching PDF is already available; pass project=... "
                "to check only that project's folder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "sources": source_schema,
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer"},
                    "priority_only": {"type": "boolean", "default": True},
                    "allowed_publishers": publisher_schema,
                    "include_local_pdf": {"type": "boolean", "default": True},
                    "project": project_schema,
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="deep_research",
            description=(
                "Decompose a research question into facets (overview, reviews, prevalence, "
                "risk factors, interventions, qualitative) and run multi-source DOI searches. "
                "By default only allowed publisher records are returned. Pass subtopics to "
                "control the decomposition explicitly."
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
                    "priority_only": {"type": "boolean", "default": True},
                    "allowed_publishers": publisher_schema,
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
                    "max_chars": {"type": "integer", "default": READ_MAX_CHARS, "minimum": 1000},
                    "max_pages": {"type": "integer", "default": PDF_MAX_PAGES, "minimum": 1},
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
                    priority_only=bool(args.get("priority_only", True)),
                    allowed_publishers=args.get("allowed_publishers"),
                    include_local_pdf=bool(args.get("include_local_pdf", True)),
                    project=args.get("project"),
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
                    priority_only=bool(args.get("priority_only", True)),
                    allowed_publishers=args.get("allowed_publishers"),
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
                    max_chars=int(args.get("max_chars", READ_MAX_CHARS)),
                    max_pages=int(args.get("max_pages", PDF_MAX_PAGES)),
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool %s failed", name)
        return _json_text(_error(str(exc), tool=name))
