"""Multi-source literature search, DOI verification and deep research."""


from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote, urljoin

from sciencedirect_meta import pipeline
from sciencedirect_meta import sources as extra_sources
from sciencedirect_meta._common import _error
from sciencedirect_meta._crossref import crossref_work
from sciencedirect_meta._journals import _attach_quartiles
from sciencedirect_meta._library import _annotate_local_pdfs, _match_local_pdf
from sciencedirect_meta._projects import _apply_project_setup, _project_scope, _project_setup_root
from sciencedirect_meta.server import (
    DEFAULT_ALLOWED_PUBLISHERS,
    MAX_ENRICH,
    PRIORITY_ORDER,
    _build_links,
    _dedupe_key,
    _extract_pii,
    _finalize_links,
    _merge,
    _normalized_allowed_publishers,
    _rank,
    _sciencedirect_link,
    enrich_sciencedirect_links,
    normalize_doi,
    polite_get,
)


async def search_literature(
    query: str,
    sources: Optional[Sequence[str]] = None,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    priority_only: bool = False,
    allowed_publishers: Optional[Sequence[str]] = None,
    include_local_pdf: bool = True,
    project: Optional[str] = None,
    query_expansion: Optional[Dict[str, Any]] = None,
    project_directory: Optional[str] = None,
) -> Dict[str, Any]:
    """Search every metadata source by default; ``project`` scopes local PDFs.

    The search pipeline itself lives in ``sciencedirect_meta.pipeline`` and is
    shared with ``search_all``. This wrapper adds the two things only this tool
    has: project-scoped local PDF annotations and the ``project``/``setup_file``
    response fields.

    When ``project`` or ``project_directory`` is given, that project's
    ``setup.txt`` supplies the API keys (OpenAlex, PubMed/NCBI, Semantic
    Scholar) and the contact e-mail used for the polite pools.
    """
    try:
        scope_dir, scope_recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))

    payload = await pipeline.run_multi_source_search(
        query,
        sources=sources,
        limit=limit,
        year_from=year_from,
        year_to=year_to,
        priority_only=priority_only,
        allowed_publishers=allowed_publishers,
        query_expansion=query_expansion,
        project_directory=project_directory,
        project_root=_project_setup_root(project),
    )

    if include_local_pdf:
        _annotate_local_pdfs(payload["results"], scope_dir, scope_recurse)

    payload["project"] = project or None
    return payload


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
        response = await polite_get(
            f"https://doi.org/{quote(doi, safe='/')}",
            follow_redirects=False,
            headers={"Accept": "text/html"},
            attempts=2,
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


def _research_plan(
    question: str,
    subtopics: Optional[Sequence[str]],
    max_subtopics: int,
) -> List[Dict[str, str]]:
    if subtopics:
        plan: List[Dict[str, str]] = []
        seen: set[str] = set()
        for topic in subtopics:
            query = str(topic).strip()
            key = query.lower()
            # Duplicate facets would issue the identical search twice.
            if not query or key in seen:
                continue
            seen.add(key)
            plan.append({"facet": "custom", "query": query})
        return plan[: max(1, min(max_subtopics, 8))]

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
    priority_only: bool = False,
    allowed_publishers: Optional[Sequence[str]] = None,
    query_expansion: Optional[Dict[str, Any]] = None,
    project: Optional[str] = None,
    project_directory: Optional[str] = None,
) -> Dict[str, Any]:
    if not question.strip():
        return _error("question is required")

    setup = _apply_project_setup(project, project_directory)
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
                project=project,
                project_directory=project_directory,
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
            if not key:
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
    _attach_quartiles(items)
    extra_sources.score_results_best(items, [entry["query"] for entry in plan])
    _annotate_local_pdfs(items)
    items.sort(key=lambda item: (-(item.get("score") or 0.0), _rank(item)))

    coverage_blocks = [
        batch.get("coverage")
        for batch in batches
        if not isinstance(batch, Exception) and batch.get("coverage")
    ]
    coverage = extra_sources.merge_coverage(
        coverage_blocks,
        items,
        query_variants=[entry["query"] for entry in plan],
        original_query=question,
        query_expansion=query_expansion or {
            "original": question,
            "expanded": [entry["query"] for entry in plan],
            "transformations": ["heuristic facet decomposition"],
            "notes": [
                "Sorgu genişletmesi sezgisel facet ayrıştırmasıyla üretildi; "
                "MeSH terimleri ve dil dönüşümü ayrıca sağlanmadı."
            ],
        },
        requested_limit=results_per_topic,
    )

    return {
        "question": question,
        "plan": plan,
        "count": len(items[:50]),
        "total_found": len(items),
        "priority_only": priority_only,
        "allowed_publishers": _normalized_allowed_publishers(allowed_publishers),
        "setup_file": setup.get("path"),
        "coverage": coverage,
        "evidence_scarcity": coverage["evidence_scarcity"],
        "evidence_scarcity_message": coverage["evidence_scarcity_message"],
        "notes": sorted(set(notes)) + [
            "Heuristic query decomposition; pass explicit subtopics for full control.",
            "local_pdf shows which results already have a full text in the library.",
            "Coverage per-source counts are summed across facets; unique_dois is a sum, not a global distinct count.",
        ],
        "results": items[:50],
    }


