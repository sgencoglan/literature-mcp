"""ScienceDirect Metadata MCP server.

API-key-free literature search built on open metadata sources:

* OpenAlex  -> works from all publishers (optional priority publisher filter)
* PubMed    -> E-utilities (abstracts + DOIs + PMIDs)
* Europe PMC-> REST API (abstracts + DOIs + full-text links)
* Crossref  -> only used to resolve Elsevier PII for exact ScienceDirect URLs

Links are ordered by priority: Ovid LWW, ScienceDirect,
SpringerLink, Wiley, Taylor & Francis.

This server never requests www.sciencedirect.com, so it is not affected by
ScienceDirect's Cloudflare bot protection.  It returns metadata and links; it
does not download paywalled PDFs and does not bypass access controls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

ELSEVIER_OPENALEX_ID = "P4310320990"  # OpenAlex publisher id for Elsevier BV

# OpenAlex publisher IDs for the platforms the user wants to prioritise.
PRIORITY_PUBLISHER_IDS = [
    "P4310315671",  # Lippincott Williams & Wilkins (Ovid LWW)
    "P4310318547",  # Wolters Kluwer
    "P4310315860",  # Wolters Kluwer Health
    "P4310320990",  # Elsevier (ScienceDirect)
    "P4310319965",  # Springer Nature
    "P4310320108",  # Springer Nature (Netherlands)
    "P4310320595",  # Wiley
    "P4310320547",  # Taylor & Francis
    "P4310319847",  # Routledge (Taylor & Francis)
]

# Lower index = higher priority. This is the order requested by the user.
PRIORITY_ORDER = [
    "ovid_lww",
    "sciencedirect",
    "springerlink",
    "wiley",
    "taylor_francis",
]
PRIORITY_LABELS = {
    "ovid_lww": "Ovid LWW",
    "sciencedirect": "ScienceDirect",
    "springerlink": "SpringerLink",
    "wiley": "Wiley",
    "taylor_francis": "Taylor & Francis",
}

# The default allowlist requires a real publisher link from one of the five
# supported academic publishers.
DEFAULT_ALLOWED_PUBLISHERS = (
    "ovid_lww",
    "sciencedirect",
    "springerlink",
    "wiley",
    "taylor_francis",
)

DEFAULT_MAILTO = "research@example.org"
MAILTO = os.environ.get("CROSSREF_MAILTO", DEFAULT_MAILTO).strip() or DEFAULT_MAILTO

HTTP_TIMEOUT = 35.0
MAX_ABSTRACT_CHARS = 6000
MAX_ENRICH = 15          # max Crossref PII lookups per tool call
CROSSREF_CONCURRENCY = 3

USER_AGENT = f"sciencedirect-meta-mcp/0.1 (mailto:{MAILTO})"

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("sciencedirect-meta")

_client = httpx.AsyncClient(
    timeout=HTTP_TIMEOUT,
    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    follow_redirects=True,
)

_crossref_sem = asyncio.Semaphore(CROSSREF_CONCURRENCY)
_pii_cache: Dict[str, Optional[str]] = {}

_PII_IN_URL = re.compile(r"PII:([A-Z0-9]+)")
_PII_RE = re.compile(r"S[0-9A-Z]{10,}")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def normalize_doi(value: Optional[str]) -> str:
    if not value:
        return ""
    doi = str(value).strip()
    for prefix in ("https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip().strip(".").lower()


def _truncate(text: Optional[str], limit: int = MAX_ABSTRACT_CHARS) -> Optional[str]:
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _is_pii(value: Optional[str]) -> bool:
    return bool(value) and bool(_PII_RE.fullmatch(value.strip()))


def _extract_pii(message: Dict[str, Any]) -> Optional[str]:
    for alt in message.get("alternative-id") or []:
        if _is_pii(str(alt)):
            return str(alt).strip()
    for link in message.get("link") or []:
        match = _PII_IN_URL.search(str(link.get("URL", "")))
        if match and _is_pii(match.group(1)):
            return match.group(1)
    return None


def _sciencedirect_link(doi: str, pii: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if pii:
        return (
            f"https://www.sciencedirect.com/science/article/pii/{pii}",
            "pii",
        )
    if doi.startswith("10.1016/"):
        # Elsevier DOI; resolves to ScienceDirect (or the current publisher
        # landing page if the journal moved).
        return (f"https://doi.org/{doi}", "doi_redirect")
    return (None, None)


def _pii_from_url(url: Optional[str]) -> Optional[str]:
    match = re.search(r"/pii/([A-Z0-9]+)", url or "")
    return match.group(1) if match else None


def _springerlink_url(doi: str, work_type: Optional[str]) -> str:
    kind = (work_type or "").lower()
    if kind in ("book-chapter", "chapter"):
        return f"https://link.springer.com/chapter/{doi}"
    if kind in ("book", "monograph"):
        return f"https://link.springer.com/book/{doi}"
    if kind in ("article", "journal-article", "review", "letter", "editorial"):
        return f"https://link.springer.com/article/{doi}"
    return f"https://link.springer.com/{doi}"


def _build_links(
    doi: str,
    pii: Optional[str] = None,
    work_type: Optional[str] = None,
) -> Dict[str, str]:
    """Build publisher links in the requested priority order."""
    links: Dict[str, str] = {}
    if not doi:
        return links

    if doi.startswith("10.1097/"):
        # DOI resolves to journals.lww.com (Ovid LWW).
        links["ovid_lww"] = f"https://doi.org/{doi}"
    if doi.startswith("10.1016/"):
        url, _ = _sciencedirect_link(doi, pii)
        if url:
            links["sciencedirect"] = url

    if doi.startswith("10.1007/"):
        links["springerlink"] = _springerlink_url(doi, work_type)
    if doi.startswith(("10.1111/", "10.1002/")):
        links["wiley"] = f"https://onlinelibrary.wiley.com/doi/{doi}"
    if doi.startswith("10.1080/"):
        links["taylor_francis"] = f"https://www.tandfonline.com/doi/full/{doi}"

    links["doi"] = f"https://doi.org/{doi}"
    return links


def _preferred_link(links: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    for key in PRIORITY_ORDER:
        if links.get(key):
            return links[key], key
    if links.get("doi"):
        return links["doi"], "doi"
    return None, None


def _normalized_allowed_publishers(
    allowed: Optional[Sequence[str]] = None,
) -> List[str]:
    requested = [
        source
        for source in (allowed or DEFAULT_ALLOWED_PUBLISHERS)
        if source in PRIORITY_ORDER
    ]
    return requested or list(DEFAULT_ALLOWED_PUBLISHERS)


def _publisher_allowed(
    item: Dict[str, Any],
    allowed: Optional[Sequence[str]] = None,
) -> bool:
    """Whether an item has a real link from the caller's allowed publisher set."""
    allowed_set = set(_normalized_allowed_publishers(allowed))
    return item.get("publisher_source") in allowed_set


def _filter_by_publisher(
    items: Iterable[Dict[str, Any]],
    allowed: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    return [item for item in items if _publisher_allowed(item, allowed)]


def _finalize_links(item: Dict[str, Any], pii: Optional[str] = None) -> Dict[str, Any]:
    """(Re)build all link fields after metadata enrichment or merging."""
    doi = normalize_doi(item.get("doi"))
    if pii is None:
        pii = item.get("_pii") or _pii_from_url(item.get("sciencedirect_url"))
    if pii:
        item["_pii"] = pii

    links = _build_links(doi, pii=pii, work_type=item.get("type"))
    item["links"] = links

    preferred_url, preferred_source = _preferred_link(links)
    item["preferred_url"] = preferred_url
    item["preferred_source"] = preferred_source
    item["preferred_label"] = PRIORITY_LABELS.get(preferred_source or "", preferred_source)
    item["link_priority"] = (
        PRIORITY_ORDER.index(preferred_source) + 1
        if preferred_source in PRIORITY_ORDER
        else 99
    )

    publisher_source = next(
        (key for key in PRIORITY_ORDER if links.get(key)),
        None,
    )
    item["publisher_source"] = publisher_source
    item["publisher_label"] = PRIORITY_LABELS.get(publisher_source or "", publisher_source)
    item["publisher_url"] = links.get(publisher_source) if publisher_source else None
    item["publisher_allowed"] = publisher_source in DEFAULT_ALLOWED_PUBLISHERS
    item["allowed_publishers"] = list(DEFAULT_ALLOWED_PUBLISHERS)

    # Backwards-compatible ScienceDirect fields.
    item["sciencedirect_url"] = links.get("sciencedirect")
    if item["sciencedirect_url"]:
        item["sciencedirect_url_type"] = (
            "pii" if "/pii/" in item["sciencedirect_url"] else "doi_redirect"
        )
    else:
        item["sciencedirect_url_type"] = None

    return item


def _reconstruct_abstract(inverted: Optional[Dict[str, List[int]]]) -> Optional[str]:
    if not inverted:
        return None
    positions: List[Tuple[int, str]] = []
    for word, indexes in inverted.items():
        for index in indexes:
            positions.append((index, word))
    positions.sort(key=lambda pair: pair[0])
    return _truncate(" ".join(word for _, word in positions))


def _dedupe_key(item: Dict[str, Any]) -> str:
    doi = normalize_doi(item.get("doi"))
    if doi:
        return "doi:" + doi
    title = re.sub(r"[^a-z0-9]+", "", (item.get("title") or "").lower())
    return "title:" + title[:140]


def _rank(item: Dict[str, Any]) -> Tuple[int, int, int]:
    """Lower link_priority first (LWW=1 ... T&F=6), then PII, then citations."""
    priority = int(item.get("link_priority") or 99)
    sd_bonus = 0 if item.get("sciencedirect_url_type") == "pii" else 1
    return (priority, sd_bonus, -int(item.get("cited_by") or 0))


def _paper(**kwargs: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "title": None,
        "authors": [],
        "year": None,
        "journal": None,
        "doi": None,
        "pmid": None,
        "abstract": None,
        "cited_by": 0,
        "open_access": None,
        "pdf_url": None,
        "doi_url": None,
        "sciencedirect_url": None,
        "sciencedirect_url_type": None,
        "source": None,
        "sources": [],
        "openalex_id": None,
        "europepmc_id": None,
        "pmcid": None,
        "crossref_id": None,
        "type": None,
    }
    item.update(kwargs)
    source = item.get("source")
    if source:
        item["sources"] = sorted(set(item.get("sources") or []) | {source})
    doi = normalize_doi(item.get("doi"))
    if doi:
        item["doi"] = doi
        item["doi_url"] = f"https://doi.org/{doi}"
    return _finalize_links(item)


def _merge(target: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in extra.items():
        if key == "sources":
            continue
        if value not in (None, "", [], 0, False) and not target.get(key):
            target[key] = value
    merged_sources = set(target.get("sources") or [])
    if target.get("source"):
        merged_sources.add(target["source"])
    if extra.get("source"):
        merged_sources.add(extra["source"])
    merged_sources.update(extra.get("sources") or [])
    if merged_sources:
        target["sources"] = sorted(merged_sources)
    if extra.get("abstract") and len(extra["abstract"]) > len(target.get("abstract") or ""):
        target["abstract"] = extra["abstract"]
    target["cited_by"] = max(int(target.get("cited_by") or 0), int(extra.get("cited_by") or 0))
    if not target.get("sciencedirect_url") and extra.get("sciencedirect_url"):
        target["sciencedirect_url"] = extra["sciencedirect_url"]
        target["sciencedirect_url_type"] = extra["sciencedirect_url_type"]
    if not target.get("_pii") and extra.get("_pii"):
        target["_pii"] = extra["_pii"]
    return target


def _text(payload: Any) -> List[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]


# --------------------------------------------------------------------------- #
# Crossref PII resolution
# --------------------------------------------------------------------------- #

async def crossref_pii(doi: str) -> Optional[str]:
    """Return the Elsevier PII for a DOI, using Crossref (cached)."""
    key = normalize_doi(doi)
    if not key:
        return None
    if key in _pii_cache:
        return _pii_cache[key]

    async with _crossref_sem:
        try:
            url = f"https://api.crossref.org/works/{quote(key, safe='')}"
            response = await _client.get(url, params={"mailto": MAILTO})
            if response.status_code == 429:
                await asyncio.sleep(1.5)
                response = await _client.get(url, params={"mailto": MAILTO})
            if response.status_code != 200:
                logger.info("Crossref %s -> HTTP %s", key, response.status_code)
                _pii_cache[key] = None
                return None
            pii = _extract_pii(response.json().get("message", {}))
            _pii_cache[key] = pii
            await asyncio.sleep(0.15)
            return pii
        except Exception as exc:  # noqa: BLE001 - best effort enrichment
            logger.info("Crossref lookup failed for %s: %s", key, exc)
            _pii_cache[key] = None
            return None


async def enrich_sciencedirect_links(items: List[Dict[str, Any]], limit: int = MAX_ENRICH) -> None:
    """Attach exact ScienceDirect URLs where a PII can be resolved."""
    candidates = [
        item for item in items
        if item.get("doi") and normalize_doi(item["doi"]).startswith("10.1016/")
        and item.get("sciencedirect_url_type") != "pii"
    ][:limit]

    async def attach(item: Dict[str, Any]) -> None:
        doi = normalize_doi(item["doi"])
        pii = await crossref_pii(doi)
        if pii:
            item["_pii"] = pii
        _finalize_links(item, pii=pii)

    await asyncio.gather(*(attach(item) for item in candidates), return_exceptions=True)


# --------------------------------------------------------------------------- #
# OpenAlex (publisher filters)
# --------------------------------------------------------------------------- #

async def search_openalex(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    open_access_only: bool = False,
    elsevier_only: bool = True,
    priority_publishers_only: bool = False,
) -> List[Dict[str, Any]]:
    filters: List[str] = []
    if elsevier_only:
        filters.append(f"primary_location.source.host_organization:{ELSEVIER_OPENALEX_ID}")
    elif priority_publishers_only:
        publishers = "|".join(PRIORITY_PUBLISHER_IDS)
        filters.append(f"primary_location.source.host_organization:{publishers}")
    if year_from or year_to:
        filters.append(f"publication_year:{year_from or 1900}-{year_to or 2100}")
    if open_access_only:
        filters.append("is_oa:true")

    params: Dict[str, Any] = {
        "search": query,
        "per-page": max(1, min(limit, 50)),
        "select": (
            "id,doi,title,publication_year,publication_date,authorships,"
            "primary_location,abstract_inverted_index,cited_by_count,"
            "open_access,best_oa_location,type"
        ),
    }
    if filters:
        params["filter"] = ",".join(filters)
    response = await _client.get("https://api.openalex.org/works", params=params)
    response.raise_for_status()
    payload = response.json()

    results: List[Dict[str, Any]] = []
    for work in payload.get("results", []):
        doi = normalize_doi(work.get("doi"))
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        best_oa = work.get("best_oa_location") or {}
        oa = work.get("open_access") or {}
        authors = [
            authorship.get("author", {}).get("display_name")
            for authorship in work.get("authorships", [])
            if authorship.get("author", {}).get("display_name")
        ]
        url, link_type = _sciencedirect_link(doi, None)
        results.append(
            _paper(
                title=work.get("title"),
                authors=authors,
                year=work.get("publication_year"),
                journal=source.get("display_name"),
                doi=doi or None,
                abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
                cited_by=work.get("cited_by_count") or 0,
                open_access=oa.get("is_oa"),
                pdf_url=best_oa.get("pdf_url"),
                sciencedirect_url=url,
                sciencedirect_url_type=link_type,
                source="openalex",
                openalex_id=work.get("id"),
                type=work.get("type"),
            )
        )

    await enrich_sciencedirect_links(results)
    return results


# --------------------------------------------------------------------------- #
# PubMed
# --------------------------------------------------------------------------- #

def _parse_pubmed_xml(xml_text: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    results: List[Dict[str, Any]] = []

    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//MedlineCitation/PMID")
        title = article.findtext(".//Article/ArticleTitle")
        if not title:
            title_el = article.find(".//Article/ArticleTitle")
            title = "".join(title_el.itertext()).strip() if title_el is not None else None

        abstract_parts: List[str] = []
        for element in article.findall(".//Article/Abstract/AbstractText"):
            text = "".join(element.itertext()).strip()
            label = element.get("Label")
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = _truncate(" ".join(abstract_parts))

        authors: List[str] = []
        for author in article.findall(".//AuthorList/Author"):
            last = author.findtext("LastName")
            first = author.findtext("ForeName")
            collective = author.findtext("CollectiveName")
            if last:
                authors.append(f"{last} {first or ''}".strip())
            elif collective:
                authors.append(collective)

        journal = article.findtext(".//Journal/Title")
        year = (
            article.findtext(".//Journal/JournalIssue/PubDate/Year")
            or article.findtext(".//Journal/JournalIssue/PubDate/MedlineDate")
            or article.findtext(".//Article/ArticleDate/Year")
        )
        doi = article.findtext(".//PubmedData/ArticleIdList/ArticleId[@IdType='doi']")
        doi = normalize_doi(doi)
        url, link_type = _sciencedirect_link(doi, None)

        results.append(
            _paper(
                title=title,
                authors=authors,
                year=year,
                journal=journal,
                doi=doi or None,
                pmid=pmid,
                abstract=abstract,
                sciencedirect_url=url,
                sciencedirect_url_type=link_type,
                source="pubmed",
                type="article",
            )
        )
    return results


async def search_pubmed(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    search = await _client.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": max(1, min(limit, 50)),
            "sort": "relevance",
        },
    )
    search.raise_for_status()
    ids = search.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    fetch = await _client.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
    )
    fetch.raise_for_status()
    return _parse_pubmed_xml(fetch.text)


# --------------------------------------------------------------------------- #
# Europe PMC
# --------------------------------------------------------------------------- #

async def search_europepmc(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    response = await _client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={
            "query": query,
            "format": "json",
            "pageSize": max(1, min(limit, 50)),
            "resultType": "core",
        },
    )
    response.raise_for_status()
    payload = response.json()

    results: List[Dict[str, Any]] = []
    for record in payload.get("resultList", {}).get("result", []):
        doi = normalize_doi(record.get("doi"))
        url, link_type = _sciencedirect_link(doi, None)
        full_texts = (record.get("fullTextUrlList") or {}).get("fullTextUrl") or []
        pdf_url = next(
            (
                entry.get("url")
                for entry in full_texts
                if str(entry.get("documentStyle", "")).lower() == "pdf"
            ),
            None,
        )
        results.append(
            _paper(
                title=record.get("title"),
                authors=[a.strip() for a in (record.get("authorString") or "").split(",") if a.strip()],
                year=record.get("pubYear"),
                journal=record.get("journalTitle"),
                doi=doi or None,
                pmid=record.get("pmid"),
                abstract=_truncate(record.get("abstractText")),
                cited_by=record.get("citedByCount") or 0,
                open_access=record.get("isOpenAccess") == "Y",
                pdf_url=pdf_url,
                sciencedirect_url=url,
                sciencedirect_url_type=link_type,
                source="europepmc",
                europepmc_id=record.get("id"),
                pmcid=record.get("pmcid"),
                type="article",
            )
        )
    return results


# --------------------------------------------------------------------------- #
# Combined search / lookup
# --------------------------------------------------------------------------- #

async def search_all(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    priority_only: bool = False,
    allowed_publishers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    sources = await asyncio.gather(
        search_openalex(
            query,
            limit,
            year_from,
            year_to,
            elsevier_only=False,
            priority_publishers_only=priority_only,
        ),
        search_pubmed(query, limit),
        search_europepmc(query, limit),
        return_exceptions=True,
    )

    merged: Dict[str, Dict[str, Any]] = {}
    notes: List[str] = []
    for name, result in zip(("openalex", "pubmed", "europepmc"), sources):
        if isinstance(result, Exception):
            notes.append(f"{name}: {result}")
            continue
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

    # Enrich before filtering so a ScienceDirect DOI without an initial PII
    # still gets a chance to qualify.
    await enrich_sciencedirect_links(items, limit=min(10, MAX_ENRICH))
    if priority_only:
        # Keep only records with a real publisher link in the allowlist.
        items = _filter_by_publisher(items, allowed_publishers)

    items.sort(key=_rank)
    returned = items[: max(1, min(limit, 50))]

    return {
        "query": query,
        "count": len(returned),
        "total_found": len(items),
        "priority_only": priority_only,
        "priority_order": PRIORITY_ORDER,
        "allowed_publishers": _normalized_allowed_publishers(allowed_publishers),
        "sources": {
            "openalex": "ok" if not isinstance(sources[0], Exception) else "error",
            "pubmed": "ok" if not isinstance(sources[1], Exception) else "error",
            "europepmc": "ok" if not isinstance(sources[2], Exception) else "error",
        },
        "notes": notes,
        "results": returned,
    }


async def get_article(identifier: str, id_type: str = "doi") -> Dict[str, Any]:
    id_type = (id_type or "doi").lower()
    doi = normalize_doi(identifier) if id_type == "doi" else ""
    pmid = identifier.strip() if id_type == "pmid" else ""

    items: List[Dict[str, Any]] = []

    if doi:
        try:
            response = await _client.get(f"https://api.openalex.org/works/doi:{quote(doi, safe='')}")
            if response.status_code == 200:
                work = response.json()
                location = work.get("primary_location") or {}
                source = location.get("source") or {}
                best_oa = work.get("best_oa_location") or {}
                oa = work.get("open_access") or {}
                url, link_type = _sciencedirect_link(doi, None)
                items.append(
                    _paper(
                        title=work.get("title"),
                        authors=[
                            a.get("author", {}).get("display_name")
                            for a in work.get("authorships", [])
                            if a.get("author", {}).get("display_name")
                        ],
                        year=work.get("publication_year"),
                        journal=source.get("display_name"),
                        doi=doi,
                        abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
                        cited_by=work.get("cited_by_count") or 0,
                        open_access=oa.get("is_oa"),
                        pdf_url=best_oa.get("pdf_url"),
                        sciencedirect_url=url,
                        sciencedirect_url_type=link_type,
                        source="openalex",
                        openalex_id=work.get("id"),
                        type=work.get("type"),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.info("OpenAlex article lookup failed: %s", exc)

    query = f"DOI:{doi}" if doi else f"EXT_ID:{pmid}"
    try:
        epmc = await search_europepmc(query, limit=1)
        items.extend(epmc)
    except Exception as exc:  # noqa: BLE001
        logger.info("Europe PMC article lookup failed: %s", exc)

    if not items and pmid:
        try:
            items.extend(await search_pubmed(pmid, limit=1))
        except Exception as exc:  # noqa: BLE001
            logger.info("PubMed article lookup failed: %s", exc)

    if not items:
        return {"error": "Article not found", "identifier": identifier, "id_type": id_type}

    merged = items[0]
    for item in items[1:]:
        _merge(merged, item)
    _finalize_links(merged)
    await enrich_sciencedirect_links([merged], limit=1)
    return merged


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #

server = Server("sciencedirect-meta")


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name="search_sciencedirect",
            description=(
                "Search Elsevier/ScienceDirect-indexed articles without an Elsevier API key. "
                "Uses OpenAlex (Elsevier publisher filter) and resolves exact ScienceDirect "
                "PII links via Crossref when possible. Results also include priority-ordered "
                "links for Ovid LWW, ScienceDirect, SpringerLink, Wiley and Taylor & Francis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic, title or keyword query."},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    "year_from": {"type": "integer", "description": "Earliest publication year."},
                    "year_to": {"type": "integer", "description": "Latest publication year."},
                    "open_access_only": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="search_pubmed",
            description=(
                "Search PubMed via NCBI E-utilities (no API key required). Returns abstracts, "
                "DOIs and PMIDs; Elsevier DOIs get a ScienceDirect DOI link."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="search_europepmc",
            description=(
                "Search Europe PMC (no API key required). Returns abstracts, DOIs, PMIDs, "
                "citation counts and open-access PDF links."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="search_all",
            description=(
                "Combined search across OpenAlex (all publishers), PubMed and Europe PMC. "
                "Deduplicates results and ranks links in this order: Ovid LWW, ScienceDirect, "
                "SpringerLink, Wiley, Taylor & Francis. Set priority_only=true to "
                "restrict results to these publishers."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer"},
                    "priority_only": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Only return records that have a real publisher link in the "
                            "allowed_publishers set."
                        ),
                    },
                    "allowed_publishers": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(PRIORITY_ORDER),
                        },
                        "description": (
                            "Publisher/source allowlist. Default: Ovid LWW, ScienceDirect, "
                            "SpringerLink, Wiley, Taylor & Francis."
                        ),
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_article",
            description=(
                "Look up one article by DOI or PMID across OpenAlex and Europe PMC; returns "
                "metadata, abstract, citation count and priority-ordered publisher links."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "DOI or PMID value."},
                    "id_type": {
                        "type": "string",
                        "enum": ["doi", "pmid"],
                        "default": "doi",
                    },
                },
                "required": ["identifier"],
            },
        ),
        types.Tool(
            name="get_links",
            description=(
                "Return priority-ordered links for one DOI or PMID: Ovid LWW, ScienceDirect, "
                "SpringerLink, Wiley, Taylor & Francis, then the DOI resolver. "
                "Also returns preferred_url and publisher_url."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "DOI or PMID value."},
                    "id_type": {
                        "type": "string",
                        "enum": ["doi", "pmid"],
                        "default": "doi",
                    },
                },
                "required": ["identifier"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> List[types.TextContent]:
    args = arguments or {}
    try:
        if name == "search_sciencedirect":
            query = str(args.get("query", "")).strip()
            if not query:
                return _text({"error": "query is required"})
            results = await search_openalex(
                query=query,
                limit=int(args.get("limit", 10)),
                year_from=args.get("year_from"),
                year_to=args.get("year_to"),
                open_access_only=bool(args.get("open_access_only", False)),
            )
            results.sort(key=_rank)
            return _text({"query": query, "count": len(results), "results": results})

        if name == "search_pubmed":
            query = str(args.get("query", "")).strip()
            if not query:
                return _text({"error": "query is required"})
            results = await search_pubmed(query, limit=int(args.get("limit", 10)))
            await enrich_sciencedirect_links(results, limit=min(10, MAX_ENRICH))
            results.sort(key=_rank)
            return _text({"query": query, "count": len(results), "results": results})

        if name == "search_europepmc":
            query = str(args.get("query", "")).strip()
            if not query:
                return _text({"error": "query is required"})
            results = await search_europepmc(query, limit=int(args.get("limit", 10)))
            await enrich_sciencedirect_links(results, limit=min(10, MAX_ENRICH))
            results.sort(key=_rank)
            return _text({"query": query, "count": len(results), "results": results})

        if name == "search_all":
            query = str(args.get("query", "")).strip()
            if not query:
                return _text({"error": "query is required"})
            payload = await search_all(
                query=query,
                limit=int(args.get("limit", 10)),
                year_from=args.get("year_from"),
                year_to=args.get("year_to"),
                priority_only=bool(args.get("priority_only", False)),
                allowed_publishers=args.get("allowed_publishers"),
            )
            return _text(payload)

        if name == "get_article":
            identifier = str(args.get("identifier", "")).strip()
            if not identifier:
                return _text({"error": "identifier is required"})
            payload = await get_article(identifier, str(args.get("id_type", "doi")))
            return _text(payload)

        if name == "get_links":
            identifier = str(args.get("identifier", "")).strip()
            if not identifier:
                return _text({"error": "identifier is required"})
            payload = await get_article(identifier, str(args.get("id_type", "doi")))
            if "error" in payload:
                return _text(payload)
            return _text(
                {
                    "identifier": identifier,
                    "title": payload.get("title"),
                    "doi": payload.get("doi"),
                    "pmid": payload.get("pmid"),
                    "links": payload.get("links"),
                    "preferred_url": payload.get("preferred_url"),
                    "preferred_source": payload.get("preferred_source"),
                    "preferred_label": payload.get("preferred_label"),
                    "publisher_url": payload.get("publisher_url"),
                    "publisher_source": payload.get("publisher_source"),
                    "publisher_label": payload.get("publisher_label"),
                    "publisher_allowed": payload.get("publisher_allowed"),
                    "allowed_publishers": payload.get("allowed_publishers"),
                    "link_priority": payload.get("link_priority"),
                }
            )

        return _text({"error": f"unknown tool: {name}"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool %s failed", name)
        return _text({"error": str(exc), "tool": name})


async def _run() -> None:
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await _client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
