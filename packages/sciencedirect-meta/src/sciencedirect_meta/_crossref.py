"""Crossref metadata lookup and search."""


from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from sciencedirect_meta import server as meta_server
from sciencedirect_meta._common import _error, _strip_html, logger
from sciencedirect_meta.server import (
    RateLimitedError,
    _extract_pii,
    _finalize_links,
    _openalex_params,
    _paper,
    _truncate,
    get_article,
    normalize_doi,
    polite_get,
    redact_secrets,
    search_europepmc,
    search_pubmed,
)

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
        try:
            response = await polite_get(
                url, params={"mailto": meta_server.MAILTO}, attempts=3
            )
        except RateLimitedError as exc:
            logger.info("Crossref rate limited for %s: %s", key, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.info("Crossref lookup failed for %s: %s", key, exc)
            return None
        if response.status_code == 404:
            _crossref_cache[key] = None
            return None
        if response.status_code != 200:
            logger.info("Crossref %s -> HTTP %s", key, response.status_code)
            return None
        message = response.json().get("message")
        _crossref_cache[key] = message
        return message


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
        "mailto": meta_server.MAILTO,
    }
    filters: List[str] = []
    if year_from:
        filters.append(f"from-pub-date:{int(year_from)}-01-01")
    if year_to:
        filters.append(f"until-pub-date:{int(year_to)}-12-31")
    if filters:
        params["filter"] = ",".join(filters)

    response = await polite_get(
        "https://api.crossref.org/works", params=params, attempts=3
    )
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
        response = await polite_get(
            f"https://api.openalex.org/works/doi:{quote(doi, safe='')}",
            params=_openalex_params(),
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
            "error": redact_secrets(exc),
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
            "error": redact_secrets(exc),
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
            "error": redact_secrets(exc),
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
    from sciencedirect_meta._library import _match_local_pdf
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


