"""Shared multi-source search pipeline.

Both ``server.search_all`` and ``local_research.search_literature`` used to
carry their own copy of the same 150-line pipeline (build tasks, gather,
deduplicate, filter, rank, build coverage). Keeping two copies meant a fix in
one tool silently left the other broken — exactly what happened when Crossref
was missing from ``search_all``.

This module owns the single implementation. The two tools stay thin wrappers
that add their own response shape (``sources_status`` vs ``sources``) and their
own extras (``local_pdf`` annotations, project scoping).

Nothing here imports ``local_research`` at module level: ``search_crossref``
lives there and is imported lazily inside the task builder, so the existing
``server -> pipeline -> server`` import direction stays acyclic.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, Sequence

from sciencedirect_meta import bootstrap
from sciencedirect_meta import sources as extra_sources
from sciencedirect_meta.rate_limit import MAX_PARALLEL_SOURCES
from sciencedirect_meta.server import (
    MAX_ENRICH,
    _dedupe_key,
    _filter_by_publisher,
    _finalize_links,
    _merge,
    _normalized_allowed_publishers,
    _rank,
    enrich_sciencedirect_links,
    refresh_credentials,
    search_europepmc,
    search_openalex,
    search_pubmed,
)

# Every source the MCP can query. The order is also the order used in coverage
# output, so keep it stable.
AVAILABLE_SOURCES: List[str] = [
    "openalex",
    "semantic_scholar",
    "pubmed",
    "europepmc",
    "crossref",
    "arxiv",
    "clinicaltrials",
]

# All available sources are searched by default. Narrowing the set is an
# explicit choice (`sources=[...]`), never an implicit default.
DEFAULT_SOURCES: List[str] = list(AVAILABLE_SOURCES)

# The one source that answers 429 with an empty body instead of an error; it
# needs the cooldown heuristic to be reported as rate_limited rather than "ok".
RATE_LIMITED_WHEN_EMPTY = frozenset({"semantic_scholar"})


def resolve_sources(
    sources: Optional[Sequence[str]] = None,
    include_semantic_scholar: bool = True,
    include_arxiv: bool = True,
    include_clinicaltrials: bool = True,
) -> List[str]:
    """Return the sources to query, validated against ``AVAILABLE_SOURCES``."""
    if sources:
        requested = [name for name in sources if name in AVAILABLE_SOURCES]
        if requested:
            return requested
    requested = list(DEFAULT_SOURCES)
    if not include_semantic_scholar:
        requested = [name for name in requested if name != "semantic_scholar"]
    if not include_arxiv:
        requested = [name for name in requested if name != "arxiv"]
    if not include_clinicaltrials:
        requested = [name for name in requested if name != "clinicaltrials"]
    return requested or list(DEFAULT_SOURCES)


def apply_project_setup(
    project_directory: Optional[str] = None,
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Load API keys for the project being worked on.

    Resolution order: explicit ``project_directory``, then ``LIT_PROJECT_ROOT``,
    then an already-registered project's ``output_directory``. Explicit
    process-environment values still win, and another project's ``setup.txt``
    never overrides the current project's keys.
    """
    root = (
        (project_directory or "").strip()
        or (project_root or "").strip()
        or os.environ.get("LIT_PROJECT_ROOT", "").strip()
        or None
    )
    if not root:
        return {"path": None, "loaded": [], "skipped": []}
    if not os.path.isdir(root):
        # A mistyped path must not silently fall back to another project's keys.
        return {
            "path": None,
            "loaded": [],
            "skipped": [],
            "error": f"project_directory bulunamadı: {root}",
        }
    status = bootstrap.load_for_project(root)
    if status.get("path"):
        refresh_credentials()
    return status


def _build_tasks(
    requested: Sequence[str],
    query: str,
    limit: int,
    year_from: Optional[int],
    year_to: Optional[int],
    priority_only: bool,
) -> Dict[str, Any]:
    """Create one coroutine per requested source (never awaited here)."""
    tasks: Dict[str, Any] = {}
    if "openalex" in requested:
        tasks["openalex"] = search_openalex(
            query,
            limit,
            year_from,
            year_to,
            elsevier_only=False,
            priority_publishers_only=priority_only,
        )
    if "semantic_scholar" in requested:
        tasks["semantic_scholar"] = extra_sources.search_semantic_scholar(
            query, limit, year_from, year_to
        )
    if "pubmed" in requested:
        tasks["pubmed"] = search_pubmed(query, limit, year_from, year_to)
    if "europepmc" in requested:
        tasks["europepmc"] = search_europepmc(query, limit, year_from, year_to)
    if "crossref" in requested:
        from sciencedirect_meta.local_research import search_crossref

        tasks["crossref"] = search_crossref(query, limit, year_from, year_to)
    if "arxiv" in requested:
        tasks["arxiv"] = extra_sources.search_arxiv(query, limit, year_from, year_to)
    if "clinicaltrials" in requested:
        tasks["clinicaltrials"] = extra_sources.search_clinicaltrials(
            query, limit, year_from, year_to
        )
    return tasks


async def collect_source_results(
    requested: Sequence[str],
    query: str,
    limit: int,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    priority_only: bool = False,
) -> Dict[str, Any]:
    """Query the sources in parallel and merge them into one ranked pool.

    Returns the raw pieces (``per_source``, ``source_meta``, ``notes``,
    ``skipped``) so callers can build their own response and coverage block.
    A failing or rate-limited source never aborts the others.
    """
    tasks = _build_tasks(requested, query, limit, year_from, year_to, priority_only)

    source_slots = asyncio.Semaphore(MAX_PARALLEL_SOURCES)

    async def run_bounded(name: str, coro: Any) -> Dict[str, Any]:
        async with source_slots:
            return await extra_sources.run_source(
                name,
                coro,
                requested_limit=limit,
                rate_limited_when_empty=name in RATE_LIMITED_WHEN_EMPTY,
            )

    gathered = await asyncio.gather(*(run_bounded(name, coro) for name, coro in tasks.items()))

    merged: Dict[str, Dict[str, Any]] = {}
    notes: List[str] = []
    status: Dict[str, str] = {}
    per_source: Dict[str, List[Dict[str, Any]]] = {}
    source_meta: Dict[str, Dict[str, Any]] = {}

    for name, result in zip(tasks.keys(), gathered):
        meta = {key: value for key, value in result.items() if key != "items"}
        source_meta[name] = meta
        status[name] = str(meta.get("status") or "ok")
        per_source[name] = result["items"]
        if meta.get("status") == "error":
            notes.append(f"{name}: {meta.get('error')}")
        elif meta.get("status") == "rate_limited":
            notes.append(f"{name}: {meta.get('note')}")
        for item in result["items"]:
            key = _dedupe_key(item)
            # An empty title cannot be merged safely; skipping it is better
            # than collapsing every untitled record into one row.
            if not key:
                continue
            if key in merged:
                _merge(merged[key], item)
            else:
                merged[key] = item

    skipped: List[Dict[str, str]] = [
        {"source": name, "reason": "kullanıcı seçmedi (sources listesinde yok)"}
        for name in AVAILABLE_SOURCES
        if name not in requested
    ]

    return {
        "requested": list(requested),
        "merged": merged,
        "per_source": per_source,
        "source_meta": source_meta,
        "status": status,
        "notes": notes,
        "skipped": skipped,
    }


async def finalize_items(
    merged: Dict[str, Dict[str, Any]],
    query: str,
    limit: int,
    priority_only: bool = False,
    allowed_publishers: Optional[Sequence[str]] = None,
    attach_quartiles: bool = True,
) -> List[Dict[str, Any]]:
    """Link, enrich, filter, score and rank the merged pool.

    PII enrichment runs *before* the publisher filter: a 10.1016 DOI without a
    Crossref PII yet looks like a DOI-only record and would otherwise be
    dropped by ``priority_only``.
    """
    items = list(merged.values())
    for item in items:
        _finalize_links(item)

    await enrich_sciencedirect_links(items, limit=min(10, MAX_ENRICH))
    if priority_only:
        items = _filter_by_publisher(items, allowed_publishers)

    if attach_quartiles:
        _attach_quartiles_best_effort(items)
    extra_sources.score_results(items, query)
    items.sort(key=lambda item: (-(item.get("score") or 0.0), _rank(item)))
    return items


def _attach_quartiles_best_effort(items: Sequence[Dict[str, Any]]) -> None:
    """Add SCImago quartiles when the local dataset is available."""
    if not items:
        return
    try:
        from sciencedirect_meta.local_research import _attach_quartiles

        _attach_quartiles(items)
    except Exception:  # noqa: BLE001 - optional local dataset
        return


def build_payload(
    *,
    query: str,
    collected: Dict[str, Any],
    items: Sequence[Dict[str, Any]],
    limit: int,
    priority_only: bool,
    allowed_publishers: Optional[Sequence[str]],
    query_variants: Optional[Sequence[str]] = None,
    query_expansion: Optional[Dict[str, Any]] = None,
    setup_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble the coverage block and the shared part of the response."""
    returned = list(items)[: max(1, min(limit, 50))]
    coverage = extra_sources.build_coverage(
        collected["per_source"],
        items,
        query_variants=list(query_variants or [query]),
        original_query=query,
        query_expansion=query_expansion,
        source_meta=collected["source_meta"],
        skipped_sources=collected["skipped"],
        requested_limit=limit,
    )
    return {
        "query": query,
        "count": len(returned),
        "total_found": len(items),
        "sources_requested": collected["requested"],
        "sources_status": collected["status"],
        # Kept for callers that used the older ``sources`` mapping.
        "sources": collected["status"],
        "priority_only": priority_only,
        "priority_order": list(extra_sources.PRIORITY_ORDER),
        "allowed_publishers": _normalized_allowed_publishers(allowed_publishers),
        "setup_file": setup_file,
        "coverage": coverage,
        "evidence_scarcity": coverage["evidence_scarcity"],
        "evidence_scarcity_message": coverage["evidence_scarcity_message"],
        "notes": collected["notes"],
        "results": returned,
    }


async def run_multi_source_search(
    query: str,
    *,
    sources: Optional[Sequence[str]] = None,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    priority_only: bool = False,
    allowed_publishers: Optional[Sequence[str]] = None,
    include_semantic_scholar: bool = True,
    include_arxiv: bool = True,
    include_clinicaltrials: bool = True,
    query_variants: Optional[Sequence[str]] = None,
    query_expansion: Optional[Dict[str, Any]] = None,
    project_directory: Optional[str] = None,
    project_root: Optional[str] = None,
    attach_quartiles: bool = True,
) -> Dict[str, Any]:
    """One-call convenience wrapper used by both search tools."""
    setup = apply_project_setup(project_directory, project_root)
    requested = resolve_sources(
        sources,
        include_semantic_scholar=include_semantic_scholar,
        include_arxiv=include_arxiv,
        include_clinicaltrials=include_clinicaltrials,
    )
    collected = await collect_source_results(
        requested, query, limit, year_from, year_to, priority_only
    )
    items = await finalize_items(
        collected["merged"],
        query,
        limit,
        priority_only=priority_only,
        allowed_publishers=allowed_publishers,
        attach_quartiles=attach_quartiles,
    )
    payload = build_payload(
        query=query,
        collected=collected,
        items=items,
        limit=limit,
        priority_only=priority_only,
        allowed_publishers=allowed_publishers,
        query_variants=query_variants,
        query_expansion=query_expansion,
        setup_file=setup.get("path"),
    )
    if setup.get("error"):
        payload["setup_error"] = setup["error"]
    return payload
