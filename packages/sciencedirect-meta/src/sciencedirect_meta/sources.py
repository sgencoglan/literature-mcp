"""Additional open metadata sources, coverage reporting and quality ranking.

The functions in this module extend ``sciencedirect_meta.server`` with:

* Semantic Scholar Graph API (optional ``SEMANTIC_SCHOLAR_API_KEY``),
* arXiv Atom API (no key),
* ClinicalTrials.gov API v2 (no key),
* an advanced OpenAlex helper with search.semantic and richer filters,
* a transparent relevance/quality score,
* per-query coverage statistics and an evidence-scarcity signal.

Every network call is best effort: a failing source is logged and returns an
empty list so the other sources in a combined search keep working.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Dict, List, Optional, Sequence, Tuple

from sciencedirect_meta import server as meta_server
from sciencedirect_meta.server import (
    PRIORITY_LABELS,
    PRIORITY_ORDER,
    RateLimitedError,
    _paper,
    _truncate,
    client_for_loop,
    normalize_doi,
    polite_get,
    redact_secrets,
)

logger = logging.getLogger("sciencedirect-meta.sources")

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = (
    "title,abstract,year,venue,publicationDate,publicationTypes,journal,"
    "authors,externalIds,citationCount,influentialCitationCount,"
    "isOpenAccess,openAccessPdf,url,paperId"
)
ARXIV_API = "https://export.arxiv.org/api/query"
# arXiv asks API clients to identify themselves with a contact address and to
# send no more than one request every few seconds. A generic UA gets 429s.
ARXIV_MIN_INTERVAL = 5.0
_ARXIV_LAST_CALL = 0.0
CLINICALTRIALS_API = "https://clinicaltrials.gov/api/v2/studies"

# Semantic Scholar: 1 request/second is cumulative across all endpoints, with
# or without a key. Requests are serialised through a lock so parallel facet
# searches cannot trip the limit.
_S2_MIN_INTERVAL = 2.0
_S2_LOCK: Optional[asyncio.Lock] = None
_S2_LOCK_LOOP: Optional[asyncio.AbstractEventLoop] = None
_S2_LAST_CALL = 0.0

# Anonymous callers share a small pool; a key gets its own quota. After a 429,
# pause the source for a while instead of failing every remaining facet.
_S2_COOLDOWN_UNTIL = 0.0
ANONYMOUS_S2_COOLDOWN_SECONDS = 120.0
KEYED_S2_COOLDOWN_SECONDS = 8.0

# Sources that returned 429 stay disabled for the rest of the run so the
# remaining facets do not keep hitting them.
_SOURCE_COOLDOWN: Dict[str, float] = {}

# Human-readable per-source notes shown in the coverage table. They describe
# how the source was used, not what it returned, so they stay factual even
# when the source returns nothing.
DEFAULT_SOURCE_NOTES: Dict[str, str] = {
    "openalex": "OpenAlex relevance search; yıl/OA filtreleri uygulandı.",
    "semantic_scholar": "Atıf ve influential citation alanları dahil.",
    "pubmed": "NCBI E-utilities; MeSH/eş anlamlı genişletme ajan tarafından sağlandıysa kullanıldı.",
    "europepmc": "Europe PMC REST; OA PDF bağlantıları dahil.",
    "crossref": "Crossref metadata; DOI doğrulama ve PII çözümü.",
    "arxiv": "Preprint kaynağı; tüm kayıtlar is_preprint=true.",
    "clinicaltrials": "Klinik çalışma kayıtları; hakemli makale değildir.",
}


def _s2_in_cooldown() -> bool:
    return time.monotonic() < _S2_COOLDOWN_UNTIL


def _s2_cooldown_seconds() -> float:
    return (
        KEYED_S2_COOLDOWN_SECONDS
        if meta_server.SEMANTIC_SCHOLAR_API_KEY
        else ANONYMOUS_S2_COOLDOWN_SECONDS
    )


async def _s2_wait_turn() -> None:
    """Serialise Semantic Scholar calls to at most one per interval."""
    global _S2_LOCK, _S2_LOCK_LOOP, _S2_LAST_CALL
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _S2_LOCK is None or (loop is not None and _S2_LOCK_LOOP is not loop):
        # A lock is usable from exactly one event loop.
        _S2_LOCK = asyncio.Lock()
        _S2_LOCK_LOOP = loop
    async with _S2_LOCK:
        elapsed = time.monotonic() - _S2_LAST_CALL
        if elapsed < _S2_MIN_INTERVAL:
            await asyncio.sleep(_S2_MIN_INTERVAL - elapsed)
        _S2_LAST_CALL = time.monotonic()


async def run_source(
    name: str,
    awaitable: Awaitable[Sequence[Dict[str, Any]]],
    requested_limit: int,
    note: Optional[str] = None,
    rate_limited_when_empty: bool = False,
) -> Dict[str, Any]:
    """Await one source, timing it and converting failures into metadata.

    The returned ``items`` list is always safe to merge; ``status`` is one of
    ``ok``, ``error`` or ``rate_limited`` so the coverage report can show why a
    source contributed nothing without aborting the other sources. A source
    that already answered 429 is skipped for the rest of the run instead of
    being hit again by every remaining facet.
    """
    now = time.monotonic()
    cooldown_until = _SOURCE_COOLDOWN.get(name, 0.0)
    if cooldown_until > now:
        if hasattr(awaitable, "close"):
            awaitable.close()  # type: ignore[attr-defined]
        return {
            "items": [],
            "status": "rate_limited",
            "error": None,
            "rate_limited": True,
            "requested_limit": requested_limit,
            "duration_ms": 0,
            "retry_after_seconds": max(0.0, cooldown_until - now) if math.isfinite(cooldown_until) else None,
            "retry_at": (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, cooldown_until - now))).isoformat() if math.isfinite(cooldown_until) else None,
            "note": (
                note
                or f"{name}: hız limiti nedeniyle {int(cooldown_until - now)} sn "
                "devre dışı bırakıldı."
            ),
        }

    started = time.monotonic()
    status = "ok"
    error: Optional[str] = None
    retry_delay = 0.0
    try:
        items = list(await awaitable or [])
    except RateLimitedError as exc:
        items = []
        status = "rate_limited"
        error = redact_secrets(exc)
        cooldown = exc.retry_after or meta_server.RATE_LIMIT_COOLDOWN_SECONDS
        retry_delay = cooldown if math.isfinite(cooldown) else 0.0
        _SOURCE_COOLDOWN[name] = time.monotonic() + cooldown
        note = str(exc)
        logger.info("%s rate limited: %s", name, error)
    except Exception as exc:  # noqa: BLE001 - best effort source
        items = []
        status = "error"
        error = redact_secrets(exc)
        logger.info("%s source failed: %s", name, error)
    duration_ms = int((time.monotonic() - started) * 1000)

    rate_limited = status == "rate_limited"
    if not rate_limited and status == "ok" and not items and rate_limited_when_empty and _s2_in_cooldown():
        status = "rate_limited"
        rate_limited = True

    if status == "rate_limited" and not note:
        remaining = _S2_COOLDOWN_UNTIL - time.monotonic()
        retry_delay = max(retry_delay, remaining if math.isfinite(remaining) else 0.0, 0.0)
        note = (
            f"{name}: hız limiti (429); kaynak "
            f"{int(_s2_cooldown_seconds())} sn devre dışı bırakıldı."
        )

    return {
        "items": items,
        "status": status,
        "error": error,
        "rate_limited": rate_limited,
        "requested_limit": requested_limit,
        "duration_ms": duration_ms,
        "note": note or DEFAULT_SOURCE_NOTES.get(name),
        "retry_after_seconds": retry_delay or None,
        "retry_at": (datetime.now(timezone.utc) + timedelta(seconds=retry_delay)).isoformat() if retry_delay else None,
    }

# A result is "high quality" when the score reaches this threshold *and* the
# study design component is at least 0.4 (i.e. not an unknown/preprint type).
HIGH_QUALITY_SCORE = 0.60
HIGH_QUALITY_STUDY_MIN = 0.40
# Combined searches flag evidence scarcity below this many high-quality hits.
EVIDENCE_SCARCITY_MIN = 5
# Controlled penalty for preprints (arXiv and Semantic Scholar arXiv records).
PREPRINT_PENALTY = 0.85

_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "has", "have", "had", "not", "but", "its", "into", "onto", "about", "over",
    "under", "between", "among", "their", "there", "these", "those", "than",
    "then", "when", "where", "which", "while", "who", "whom", "whose", "will",
    "would", "can", "could", "should", "may", "might", "does", "did", "how",
    "what", "why", "also", "such", "more", "most", "some", "any", "all",
    "bir", "ve", "ile", "için", "olan", "olarak", "bu", "şu", "da", "de",
    "üzerine", "gibi", "daha", "çok", "en", "her", "veya", "ya", "ki",
}


# --------------------------------------------------------------------------- #
# Normalization helpers
# --------------------------------------------------------------------------- #

def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _year_from_date(value: Any) -> Optional[int]:
    match = re.search(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def _semantic_scholar_paper(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    external = raw.get("externalIds") or {}
    doi = normalize_doi(external.get("DOI"))
    arxiv_id = str(external.get("ArXiv") or "").strip() or None
    authors = [
        author.get("name")
        for author in (raw.get("authors") or [])
        if author.get("name")
    ]
    journal = ((raw.get("journal") or {}) if isinstance(raw.get("journal"), dict) else {})
    venue = raw.get("venue") or journal.get("name")
    publication_types = raw.get("publicationTypes") or []
    pdf = (raw.get("openAccessPdf") or {}).get("url") if raw.get("openAccessPdf") else None

    paper = _paper(
        title=_clean_text(raw.get("title")),
        authors=authors,
        year=raw.get("year") or _year_from_date(raw.get("publicationDate")),
        journal=venue,
        doi=doi or None,
        pmid=external.get("PubMed"),
        abstract=_truncate(_clean_text(raw.get("abstract"))),
        cited_by=raw.get("citationCount") or 0,
        open_access=raw.get("isOpenAccess"),
        pdf_url=pdf,
        source="semantic_scholar",
        type=(publication_types[0] if publication_types else "article"),
    )
    paper["semantic_scholar_id"] = raw.get("paperId")
    paper["semantic_scholar_url"] = raw.get("url")
    paper["influential_citations"] = raw.get("influentialCitationCount") or 0
    paper["venue"] = venue
    paper["external_ids"] = {
        key: value
        for key, value in external.items()
        if key in {"DOI", "ArXiv", "PubMed", "PubMedCentral", "CorpusId"}
    }
    if arxiv_id:
        paper["arxiv_id"] = arxiv_id
        paper["is_preprint"] = True
    return paper


async def search_semantic_scholar(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    fields_of_study: Optional[Sequence[str]] = None,
    open_access_only: bool = False,
) -> List[Dict[str, Any]]:
    """Search Semantic Scholar; return [] (and log) when the API fails."""
    global _S2_COOLDOWN_UNTIL
    if not query.strip():
        return []
    if time.monotonic() < _S2_COOLDOWN_UNTIL:
        return []
    params: Dict[str, Any] = {
        "query": query,
        "limit": max(1, min(limit, 100)),
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }
    if year_from or year_to:
        params["year"] = f"{year_from or ''}-{year_to or ''}"
    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(str(v).strip() for v in fields_of_study if str(v).strip())
    if open_access_only:
        params["openAccessPdf"] = ""

    headers: Dict[str, str] = {}
    api_key = meta_server.SEMANTIC_SCHOLAR_API_KEY
    if api_key:
        headers["x-api-key"] = api_key

    last_error: Optional[Exception] = None
    attempts = 3 if api_key else 2
    for attempt in range(attempts):
        try:
            await _s2_wait_turn()
            if time.monotonic() < _S2_COOLDOWN_UNTIL:
                return []
            response = await client_for_loop().get(
                SEMANTIC_SCHOLAR_API,
                params=params,
                headers=headers or None,
            )
            if response.status_code == 429:
                delay = meta_server._retry_after_seconds(response, attempt, "api.semanticscholar.org")
                if attempt < attempts - 1 and delay <= meta_server.MAX_INLINE_WAIT:
                    await asyncio.sleep(delay)
                    continue
                cooldown = max(delay, _s2_cooldown_seconds())
                _S2_COOLDOWN_UNTIL = time.monotonic() + cooldown
                logger.info("Semantic Scholar rate limited; cooling down for %.0fs", cooldown)
                return []
            if response.status_code != 200:
                logger.info("Semantic Scholar HTTP %s for %r", response.status_code, query)
                return []
            payload = response.json()
            papers = [_semantic_scholar_paper(raw) for raw in payload.get("data") or []]
            return [paper for paper in papers if paper and paper.get("title")]
        except Exception as exc:  # noqa: BLE001 - best effort source
            last_error = exc
            await asyncio.sleep(0.5 * (attempt + 1))
    if last_error:
        logger.info("Semantic Scholar failed: %s", redact_secrets(last_error))
    return []


# --------------------------------------------------------------------------- #
# arXiv
# --------------------------------------------------------------------------- #

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def _arxiv_paper(entry: ET.Element) -> Optional[Dict[str, Any]]:
    raw_id = (entry.findtext(f"{_ATOM}id") or "").strip()
    if not raw_id:
        return None
    match = re.search(r"abs/([^/]+)$", raw_id)
    arxiv_id = match.group(1) if match else raw_id.rsplit("/", 1)[-1]
    title = _clean_text(entry.findtext(f"{_ATOM}title"))
    if not title:
        return None
    authors = [
        _clean_text(author.findtext(f"{_ATOM}name"))
        for author in entry.findall(f"{_ATOM}author")
    ]
    authors = [author for author in authors if author]
    published = (entry.findtext(f"{_ATOM}published") or "").strip() or None
    updated = (entry.findtext(f"{_ATOM}updated") or "").strip() or None
    categories = [
        category.get("term")
        for category in entry.findall(f"{_ATOM}category")
        if category.get("term")
    ]
    primary_element = entry.find(f"{_ARXIV}primary_category")
    primary_category = primary_element.get("term") if primary_element is not None else (
        categories[0] if categories else None
    )
    doi = normalize_doi(entry.findtext(f"{_ARXIV}doi"))
    journal_ref = _clean_text(entry.findtext(f"{_ARXIV}journal_ref"))

    pdf_url = None
    abs_url = raw_id
    for link in entry.findall(f"{_ATOM}link"):
        href = link.get("href")
        if not href:
            continue
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = href
        elif link.get("rel") == "alternate":
            abs_url = href
    if not pdf_url:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    paper = _paper(
        title=title,
        authors=authors,
        year=_year_from_date(published),
        journal=journal_ref or "arXiv",
        doi=doi or None,
        abstract=_truncate(_clean_text(entry.findtext(f"{_ATOM}summary"))),
        cited_by=0,
        open_access=True,
        pdf_url=pdf_url,
        source="arxiv",
        type="preprint",
    )
    paper.update(
        {
            "arxiv_id": arxiv_id,
            "abs_url": abs_url,
            "categories": categories,
            "primary_category": primary_category,
            "published": published,
            "updated": updated,
            "is_preprint": True,
        }
    )
    return paper


async def _arxiv_wait_turn() -> None:
    """Serialise arXiv requests; the service rejects bursts with 429."""
    global _ARXIV_LAST_CALL
    elapsed = time.monotonic() - _ARXIV_LAST_CALL
    if elapsed < ARXIV_MIN_INTERVAL:
        await asyncio.sleep(ARXIV_MIN_INTERVAL - elapsed)
    _ARXIV_LAST_CALL = time.monotonic()


def _arxiv_headers() -> Dict[str, str]:
    """Identify the client with a contact address, as arXiv requests."""
    return {
        "User-Agent": (
            f"literature-mcp/{meta_server.__version__} (mailto:{meta_server.MAILTO})"
        )
    }


async def search_arxiv(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    categories: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Search arXiv. Year limits are applied to the published year afterwards."""
    if not query.strip():
        return []
    search_query = f"all:{query}"
    if categories:
        category_filter = " OR ".join(f"cat:{str(c).strip()}" for c in categories if str(c).strip())
        if category_filter:
            search_query = f"({search_query}) AND ({category_filter})"
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max(1, min(limit * 2 if (year_from or year_to) else limit, 100)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        await _arxiv_wait_turn()
        response = await polite_get(
            ARXIV_API, params=params, headers=_arxiv_headers(), attempts=2
        )
        if response.status_code != 200:
            logger.info("arXiv HTTP %s for %r", response.status_code, query)
            return []
        root = ET.fromstring(response.text)
    except RateLimitedError:
        raise
    except Exception as exc:  # noqa: BLE001 - best effort source
        logger.info("arXiv failed: %s", redact_secrets(exc))
        return []

    papers: List[Dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM}entry"):
        paper = _arxiv_paper(entry)
        if not paper:
            continue
        year = paper.get("year")
        if year_from and (year is None or year < year_from):
            continue
        if year_to and (year is None or year > year_to):
            continue
        papers.append(paper)
        if len(papers) >= max(1, min(limit, 50)):
            break
    return papers


# --------------------------------------------------------------------------- #
# ClinicalTrials.gov
# --------------------------------------------------------------------------- #

def _clinicaltrial_study(study: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    protocol = (study or {}).get("protocolSection") or {}
    identification = protocol.get("identificationModule") or {}
    status = protocol.get("statusModule") or {}
    description = protocol.get("descriptionModule") or {}
    design = protocol.get("designModule") or {}
    conditions_module = protocol.get("conditionsModule") or {}
    arms = protocol.get("armsInterventionsModule") or {}

    nct_id = str(identification.get("nctId") or "").strip()
    title = _clean_text(identification.get("briefTitle") or identification.get("officialTitle"))
    if not nct_id or not title:
        return None

    start_date = (status.get("startDateStruct") or {}).get("date")
    study_type = design.get("studyType")
    phases = design.get("phases") or []
    conditions = conditions_module.get("conditions") or []
    interventions = [
        entry.get("name")
        for entry in (arms.get("interventions") or [])
        if entry.get("name")
    ]

    paper = _paper(
        title=title,
        authors=[],
        year=_year_from_date(start_date),
        journal="ClinicalTrials.gov",
        doi=None,
        abstract=_truncate(_clean_text(description.get("briefSummary"))),
        cited_by=0,
        open_access=True,
        pdf_url=None,
        source="clinicaltrials",
        type="clinical_trial",
    )
    paper.update(
        {
            "nct_id": nct_id,
            "clinicaltrials_url": f"https://clinicaltrials.gov/study/{nct_id}",
            "status": status.get("overallStatus"),
            "study_type": study_type,
            "phases": phases,
            "conditions": conditions,
            "interventions": interventions,
            "start_date": start_date,
            "is_preprint": False,
        }
    )
    return paper


async def search_clinicaltrials(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    intervention_only: bool = False,
) -> List[Dict[str, Any]]:
    """Search ClinicalTrials.gov API v2. Year filters use the start date."""
    if not query.strip():
        return []
    params: Dict[str, Any] = {
        "query.term": query,
        "pageSize": max(1, min(limit * 3 if (year_from or year_to) else limit, 100)),
        "format": "json",
    }
    if intervention_only:
        params["filter.advanced"] = "AREA[StudyType]INTERVENTIONAL"
    try:
        response = await polite_get(CLINICALTRIALS_API, params=params, attempts=3)
        if response.status_code != 200:
            logger.info("ClinicalTrials.gov HTTP %s for %r", response.status_code, query)
            return []
        payload = response.json()
    except RateLimitedError:
        raise
    except Exception as exc:  # noqa: BLE001 - best effort source
        logger.info("ClinicalTrials.gov failed: %s", redact_secrets(exc))
        return []

    studies: List[Dict[str, Any]] = []
    for raw in payload.get("studies") or []:
        paper = _clinicaltrial_study(raw)
        if not paper:
            continue
        year = paper.get("year")
        if year_from and (year is None or year < year_from):
            continue
        if year_to and (year is None or year > year_to):
            continue
        studies.append(paper)
        if len(studies) >= max(1, min(limit, 50)):
            break
    return studies


# --------------------------------------------------------------------------- #
# Advanced OpenAlex helper
# --------------------------------------------------------------------------- #

async def search_openalex_advanced(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    open_access_only: bool = False,
    priority_publishers_only: bool = False,
    elsevier_only: bool = False,
    work_types: Optional[Sequence[str]] = None,
    min_citations: Optional[int] = None,
    has_abstract: bool = False,
    semantic_search: bool = True,
) -> List[Dict[str, Any]]:
    """Delegate to the single OpenAlex implementation with advanced filters."""
    from sciencedirect_meta.server import search_openalex

    return await search_openalex(
        query=query,
        limit=limit,
        year_from=year_from,
        year_to=year_to,
        open_access_only=open_access_only,
        elsevier_only=elsevier_only,
        priority_publishers_only=priority_publishers_only,
        work_types=work_types,
        min_citations=min_citations,
        has_abstract=has_abstract,
        semantic_search=semantic_search,
    )


# --------------------------------------------------------------------------- #
# Study design, scoring and evidence scarcity
# --------------------------------------------------------------------------- #

_STUDY_PATTERNS: List[Tuple[str, str, float]] = [
    (r"\bsystematic review\b|\bmeta[- ]analys[ie]s\b|\bmeta[- ]analysis\b", "Systematic review / meta-analysis", 1.0),
    (r"\brandomi[sz]ed controlled\b|\brandomi[sz]ed trial\b|\bcluster[- ]randomi[sz]ed\b|\brct\b", "Randomized controlled trial", 1.0),
    (r"\bquasi[- ]experimental\b", "Quasi-experimental study", 0.60),
    (r"\bcohort\b|\blongitudinal\b|\bprospective\b", "Cohort study", 0.60),
    (r"\bcase[- ]control\b", "Case-control study", 0.50),
    (r"\bcross[- ]sectional\b", "Cross-sectional study", 0.40),
    (r"\bsurvey\b", "Survey", 0.30),
    (r"\bqualitative\b|\bfocus group\b|\binterview", "Qualitative study", 0.35),
]

_QUARTILE_SCORES = {"Q1": 1.0, "Q2": 0.70, "Q3": 0.40, "Q4": 0.15}
_QUARTILE_UNKNOWN = 0.30

# Strict quality definition used alongside the composite score:
# Q1/Q2 journal, at least this many citations, and an RCT/review design.
HIGH_QUALITY_STRICT_CITATIONS = 10
STRICT_QUARTILES = {"Q1", "Q2"}
STRICT_DESIGN_LABELS = {
    "Randomized controlled trial",
    "Systematic review / meta-analysis",
}
TREND_WINDOW_YEARS = 3


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", _normalize_text(value))
        if len(token) > 2 and token not in _STOPWORDS
    }


def detect_study_design(item: Dict[str, Any]) -> Tuple[str, float]:
    """Return a heuristic study label and its ranking boost (0..1)."""
    if item.get("is_preprint") or str(item.get("type") or "").lower() == "preprint" or item.get("source") == "arxiv":
        return "Preprint", 0.05
    if item.get("source") == "clinicaltrials":
        if str(item.get("study_type") or "").lower() == "interventional":
            return "Clinical trial (interventional)", 0.80
        return "Clinical trial", 0.50

    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("title", "abstract", "journal")
    )
    for pattern, label, score in _STUDY_PATTERNS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return label, score
    return "Unspecified design", 0.25


def _relevance(item_items: set[str], query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return round(len(item_items & query_tokens) / len(query_tokens), 4)


def _citation_score(citations: Any) -> float:
    try:
        value = max(0, int(citations or 0))
    except (TypeError, ValueError):
        value = 0
    return round(min(1.0, math.log10(value + 1) / 4.0), 4)


def _recency_score(year: Any, now_year: int) -> float:
    try:
        value = int(year)
    except (TypeError, ValueError):
        return 0.15
    age = max(0, now_year - value)
    if age <= 2:
        return 1.0
    if age >= 10:
        return 0.0
    return round(1.0 - (age - 2) / 8.0, 4)


def _quartile_score(quartile: Any) -> float:
    if isinstance(quartile, dict):
        quartile = quartile.get("quartile")
    return _QUARTILE_SCORES.get(str(quartile or "").upper(), _QUARTILE_UNKNOWN)


def _apply_score(
    item: Dict[str, Any],
    query: str,
    now_year: int,
) -> Tuple[float, Dict[str, float], str, float, bool]:
    """Compute (score, components, design label, design value, is_preprint)."""
    query_tokens = _tokens(query)
    text_tokens = _tokens(
        " ".join(
            str(item.get(key) or "")
            for key in ("title", "abstract", "journal")
        )
    )
    semantic = _relevance(text_tokens, query_tokens)
    citations = _citation_score(item.get("cited_by"))
    recency = _recency_score(item.get("year"), now_year)
    quartile_component = _quartile_score(item.get("quartile"))
    design_label, design_component = detect_study_design(item)

    components = {
        "semantic_relevance": semantic,
        "citation": citations,
        "recency": recency,
        "journal_quartile": quartile_component,
        "study_type": design_component,
    }
    score = (
        0.35 * semantic
        + 0.25 * citations
        + 0.15 * recency
        + 0.15 * quartile_component
        + 0.10 * design_component
    )
    is_preprint = bool(item.get("is_preprint"))
    if is_preprint:
        score *= PREPRINT_PENALTY
    return round(score, 4), components, design_label, design_component, is_preprint


def _write_score(
    item: Dict[str, Any],
    score: float,
    components: Dict[str, float],
    design_label: str,
    design_component: float,
    is_preprint: bool,
) -> Dict[str, Any]:
    item["score"] = score
    item["score_components"] = components
    item["study_design"] = design_label
    item["is_preprint"] = is_preprint
    item["high_quality"] = (
        not is_preprint
        and score >= HIGH_QUALITY_SCORE
        and design_component >= HIGH_QUALITY_STUDY_MIN
    )
    return item


def score_result(item: Dict[str, Any], query: str, now_year: Optional[int] = None) -> Dict[str, Any]:
    """Attach ``score``/``score_components`` to one normalized paper."""
    now_year = now_year or datetime.now(timezone.utc).year
    score, components, label, design, preprint = _apply_score(item, query, now_year)
    return _write_score(item, score, components, label, design, preprint)


def score_results(
    items: Sequence[Dict[str, Any]],
    query: str,
    now_year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    now_year = now_year or datetime.now(timezone.utc).year
    for item in items:
        score_result(item, query, now_year)
    return list(items)


def score_results_best(
    items: Sequence[Dict[str, Any]],
    queries: Sequence[str],
    now_year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Score each item against the facet query that fits it best.

    Multi-query searches (``deep_research``) must not score English records
    against a Turkish question: the token overlap would be zero and every
    composite score would collapse. Each item takes its highest-scoring facet
    query, and the winning query is recorded for transparency.
    """
    now_year = now_year or datetime.now(timezone.utc).year
    candidates = [str(query) for query in queries if str(query).strip()]
    if not candidates:
        return list(items)
    for item in items:
        best = None
        for query in candidates:
            score, components, label, design, preprint = _apply_score(item, query, now_year)
            if best is None or score > best[0]:
                best = (score, components, label, design, preprint, query)
        assert best is not None
        score, components, label, design, preprint, query = best
        _write_score(item, score, components, label, design, preprint)
        item["scored_query"] = query
    return list(items)



def _coverage_key(item: Dict[str, Any]) -> str:
    doi = normalize_doi(item.get("doi"))
    if doi:
        return "doi:" + doi
    title = re.sub(r"[^a-z0-9]+", "", _normalize_text(item.get("title")))
    return "title:" + title[:140]


SYNONYM = "synonym"
MESH = "MeSH"
LANGUAGE = "language"
TRANSLATION_METHODS = (SYNONYM, MESH, LANGUAGE)


def normalize_query_expansion(
    original_query: Optional[str],
    query_variants: Optional[Sequence[str]] = None,
    expansion: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the explicit query-expansion record used by the coverage report.

    ``expansion`` may supply ``expanded``/``queries``, ``mesh``, ``languages``,
    ``transformations`` and ``notes``. Missing values are derived from the
    original query and ``query_variants`` so the report is always explicit
    about what was actually sent to the sources.
    """
    expansion = expansion or {}
    original = (
        str(expansion.get("original") or original_query or "").strip()
    )
    expanded: List[str] = []
    for value in (
        expansion.get("expanded")
        or expansion.get("queries")
        or query_variants
        or []
    ):
        text = str(value).strip()
        if text and text != original and text not in expanded:
            expanded.append(text)

    mesh: List[str] = []
    for value in expansion.get("mesh") or []:
        text = str(value).strip()
        if text and text not in mesh:
            mesh.append(text)

    languages: List[str] = []
    for value in expansion.get("languages") or []:
        text = str(value).strip()
        if text and text not in languages:
            languages.append(text)

    transformations: List[str] = []
    for value in expansion.get("transformations") or []:
        text = str(value).strip()
        if text and text not in transformations:
            transformations.append(text)
    if not transformations:
        if expanded:
            transformations.append(SYNONYM)
        if mesh:
            transformations.append(MESH)
        if languages:
            transformations.append(LANGUAGE)
        if not transformations:
            transformations.append("none")

    notes: List[str] = []
    for value in expansion.get("notes") or []:
        text = str(value).strip()
        if text and text not in notes:
            notes.append(text)
    if not notes:
        notes.append(
            "Genişletme kaydı ajan tarafından sağlanmadı; yalnızca orijinal "
            "sorgu ve bilinen varyantlar gösterilir."
        )

    return {
        "original": original,
        "expanded": expanded,
        "mesh": mesh,
        "languages": languages,
        "transformations": transformations,
        "notes": notes,
    }


def _trend_signal(
    items: Sequence[Dict[str, Any]],
    now_year: int,
    window_years: int = TREND_WINDOW_YEARS,
) -> Dict[str, Any]:
    """Describe the publication-count trend over the last few years."""
    years = list(range(now_year - window_years + 1, now_year + 1))
    counts = {year: 0 for year in years}
    undated = 0
    for item in items:
        try:
            year = int(item.get("year"))
        except (TypeError, ValueError):
            undated += 1
            continue
        if year in counts:
            counts[year] += 1

    values = [counts[year] for year in years]
    direction = "belirsiz"
    change_pct: Optional[float] = None
    slope = 0.0
    if sum(values) > 0:
        # Least-squares slope over evenly spaced years.
        n = len(values)
        mean_x = (n - 1) / 2
        mean_y = sum(values) / n
        numerator = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values))
        denominator = sum((index - mean_x) ** 2 for index in range(n))
        slope = numerator / denominator if denominator else 0.0
        first, last = values[0], values[-1]
        if first:
            change_pct = round((last - first) / first, 4)
        if abs(slope) < 0.34:
            direction = "sabit"
        elif slope > 0:
            direction = "artıyor"
        else:
            direction = "azalıyor"

    return {
        "window_years": window_years,
        "years": years,
        "counts": {str(year): counts[year] for year in years},
        "slope": round(slope, 4),
        "direction": direction,
        "change_ratio": change_pct,
        "undated_total": undated,
    }


def build_evidence_density(
    items: Sequence[Dict[str, Any]],
    now_year: Optional[int] = None,
    window_years: int = 5,
) -> Dict[str, Any]:
    """Summarize study-design mix, recency, Q1 share and the recent trend."""
    now_year = now_year or datetime.now(timezone.utc).year
    first_year = now_year - max(1, window_years) + 1
    total = len(items)

    design_counts: Dict[str, int] = {}
    recent = 0
    q1 = 0
    high_quality = 0
    high_quality_strict = 0
    for item in items:
        label = item.get("study_design") or detect_study_design(item)[0]
        design_counts[label] = design_counts.get(label, 0) + 1
        try:
            year = int(item.get("year"))
        except (TypeError, ValueError):
            year = None
        if year is not None and year >= first_year:
            recent += 1
        quartile = str(item.get("quartile") or "").upper()
        if quartile == "Q1":
            q1 += 1
        if item.get("high_quality"):
            high_quality += 1
        try:
            citations = int(item.get("cited_by") or 0)
        except (TypeError, ValueError):
            citations = 0
        if (
            quartile in STRICT_QUARTILES
            and citations >= HIGH_QUALITY_STRICT_CITATIONS
            and label in STRICT_DESIGN_LABELS
        ):
            high_quality_strict += 1

    rct = design_counts.get("Randomized controlled trial", 0)
    review = design_counts.get("Systematic review / meta-analysis", 0)
    clinical_trial = sum(
        count
        for label, count in design_counts.items()
        if label.startswith("Clinical trial")
    )
    preprint = design_counts.get("Preprint", 0)

    return {
        "total_results": total,
        "high_quality_total": high_quality,
        "high_quality_strict_total": high_quality_strict,
        "high_quality_strict_ratio": round(high_quality_strict / total, 4) if total else 0.0,
        "high_quality_strict_rule": (
            f"Q1/Q2 + en az {HIGH_QUALITY_STRICT_CITATIONS} atıf + "
            "RCT veya sistematik derleme/meta-analiz"
        ),
        "q1_total": q1,
        "q1_ratio": round(q1 / total, 4) if total else 0.0,
        "recent_window_years": window_years,
        "recent_window_start": first_year,
        "recent_total": recent,
        "recent_ratio": round(recent / total, 4) if total else 0.0,
        "randomized_controlled_trial_total": rct,
        "systematic_review_or_meta_analysis_total": review,
        "clinical_trial_total": clinical_trial,
        "preprint_total": preprint,
        "trend": _trend_signal(items, now_year),
        "study_designs": dict(sorted(design_counts.items(), key=lambda pair: -pair[1])),
    }


def _closest_studies(
    items: Sequence[Dict[str, Any]], limit: int = 5
) -> List[Dict[str, Any]]:
    ordered = sorted(
        (item for item in items if item.get("title")),
        key=lambda item: item.get("score") or 0.0,
        reverse=True,
    )[:limit]
    return [
        {
            "title": item.get("title"),
            "year": item.get("year"),
            "doi": normalize_doi(item.get("doi")) or None,
            "score": item.get("score"),
            "study_design": item.get("study_design"),
        }
        for item in ordered
    ]


PUBLISHER_KEYS = list(PRIORITY_ORDER) + ["other", "unknown"]
PUBLISHER_LABELS = {
    **PRIORITY_LABELS,
    "other": "Diğer yayıncı",
    "unknown": "Yayıncı bilinmiyor",
}


def build_publisher_distribution(
    items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Publisher/platform mix plus open-access and preprint ratios.

    ``other`` means a publisher link exists but outside the five priority
    platforms; ``unknown`` means no publisher link could be resolved.
    """
    counts: Dict[str, int] = {key: 0 for key in PUBLISHER_KEYS}
    open_access = 0
    preprint = 0
    pdf_link = 0
    for item in items:
        key = str(item.get("publisher_source") or "").strip()
        if key not in PRIORITY_ORDER:
            key = (
                "other"
                if (item.get("publisher") or item.get("publisher_url"))
                else "unknown"
            )
        counts[key] = counts.get(key, 0) + 1
        if item.get("open_access") is True:
            open_access += 1
        if item.get("is_preprint"):
            preprint += 1
        if item.get("pdf_url") or item.get("oa_pdf_url"):
            pdf_link += 1

    total = len(items)
    ratios = {
        key: round(value / total, 4) if total else 0.0
        for key, value in counts.items()
    }
    return {
        "total": total,
        "counts": counts,
        "labels": PUBLISHER_LABELS,
        "ratios": ratios,
        "open_access_total": open_access,
        "open_access_ratio": round(open_access / total, 4) if total else 0.0,
        "preprint_total": preprint,
        "preprint_ratio": round(preprint / total, 4) if total else 0.0,
        "pdf_link_total": pdf_link,
        "pdf_link_ratio": round(pdf_link / total, 4) if total else 0.0,
    }


def source_warnings(
    source_meta: Optional[Dict[str, Dict[str, Any]]],
    skipped_sources: Optional[Sequence[Dict[str, str]]],
) -> List[str]:
    """Return short, user-facing warnings for missing or degraded sources."""
    warnings: List[str] = []
    for name, meta in (source_meta or {}).items():
        status = meta.get("status")
        if status == "error":
            warnings.append(
                f"{name} bu koşuda hata verdi ve atlandı: {meta.get('error') or 'bilinmeyen hata'}"
            )
        elif status == "partial":
            warnings.append(
                f"{name} bazı sorgularda hata/hız limiti verdi; dönen kayıtlar korundu."
            )
        elif status == "rate_limited":
            warnings.append(
                f"{name} bu koşuda hız limiti (429) nedeniyle devre dışı bırakıldı."
            )
    for entry in skipped_sources or []:
        info = dict(entry or {})
        name = info.get("source", "?")
        reason = info.get("reason") or "istekte bulunulmadı"
        warnings.append(f"{name} bu koşuda sorgulanmadı: {reason}.")
    return warnings


def _coverage_payload(
    per_source_stats: Dict[str, Dict[str, int]],
    merged_items: Sequence[Dict[str, Any]],
    query_variants: Optional[Sequence[str]],
    timestamp: Optional[str],
    original_query: Optional[str] = None,
    query_expansion: Optional[Dict[str, Any]] = None,
    now_year: Optional[int] = None,
    source_meta: Optional[Dict[str, Dict[str, Any]]] = None,
    skipped_sources: Optional[Sequence[Dict[str, str]]] = None,
    requested_limit: Optional[int] = None,
) -> Dict[str, Any]:
    total_unique_dois = len(
        {normalize_doi(item.get("doi")) for item in merged_items}
        - {""}
    )
    density = build_evidence_density(merged_items, now_year=now_year)
    high_quality_total = density["high_quality_total"]
    scarcity = high_quality_total < EVIDENCE_SCARCITY_MIN
    closest = _closest_studies(merged_items, limit=5)
    message = None
    if scarcity:
        examples = "; ".join(
            f"{item['title']} ({item.get('year') or 'yıl yok'})"
            + (f", DOI: {item['doi']}" if item.get("doi") else "")
            for item in closest
        )
        message = (
            "Bu konuda yüksek kaliteli kanıt sınırlı görünüyor. "
            f"Yüksek kaliteli sonuç sayısı: {high_quality_total} "
            f"(eşik: {EVIDENCE_SCARCITY_MIN})."
        )
        if examples:
            message += f" En yakın {len(closest)} çalışma: {examples}."
        message += " Araştırma boşluğu olasılığı yüksektir."

    meta = dict(source_meta or {})
    enriched_per_source: Dict[str, Dict[str, Any]] = {}
    for name, stats in per_source_stats.items():
        entry: Dict[str, Any] = dict(stats)
        info = meta.get(name) or {}
        entry.update(
            {
                "status": info.get("status", "ok"),
                "note": info.get("note") or DEFAULT_SOURCE_NOTES.get(name),
                "requested_limit": info.get("requested_limit", requested_limit),
                "duration_ms": info.get("duration_ms"),
                "rate_limited": bool(info.get("rate_limited")),
                "retry_after_seconds": info.get("retry_after_seconds"),
                "retry_at": info.get("retry_at"),
            }
        )
        if info.get("error"):
            entry["error"] = info["error"]
        enriched_per_source[name] = entry

    skipped = [dict(entry or {}) for entry in (skipped_sources or [])]
    warnings = source_warnings(enriched_per_source, skipped)
    publisher = build_publisher_distribution(merged_items)

    return {
        "sources_queried": list(per_source_stats.keys()),
        "per_source": enriched_per_source,
        "skipped_sources": skipped,
        "warnings": warnings,
        "total_unique_dois": total_unique_dois,
        "high_quality_total": high_quality_total,
        "high_quality_threshold": HIGH_QUALITY_SCORE,
        "evidence_scarcity": scarcity,
        "evidence_scarcity_message": message,
        "closest_studies": closest,
        "publisher_distribution": publisher,
        "query_expansion": normalize_query_expansion(
            original_query, query_variants, query_expansion
        ),
        "evidence_density": density,
        "query_variants": list(query_variants or []),
        "timestamp": timestamp
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def build_coverage(
    per_source: Dict[str, Sequence[Dict[str, Any]]],
    merged_items: Sequence[Dict[str, Any]],
    query_variants: Optional[Sequence[str]] = None,
    timestamp: Optional[str] = None,
    original_query: Optional[str] = None,
    query_expansion: Optional[Dict[str, Any]] = None,
    now_year: Optional[int] = None,
    source_meta: Optional[Dict[str, Dict[str, Any]]] = None,
    skipped_sources: Optional[Sequence[Dict[str, str]]] = None,
    requested_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the transparent per-query coverage block."""
    high_quality_keys = {
        _coverage_key(item)
        for item in merged_items
        if item.get("high_quality")
    }

    per_source_stats: Dict[str, Dict[str, int]] = {}
    for name, items in per_source.items():
        items = list(items or [])
        dois = {normalize_doi(item.get("doi")) for item in items}
        dois.discard("")
        per_source_stats[name] = {
            "returned": len(items),
            "unique_dois": len(dois),
            "high_quality": sum(
                1 for item in items if _coverage_key(item) in high_quality_keys
            ),
        }

    return _coverage_payload(
        per_source_stats,
        merged_items,
        query_variants,
        timestamp,
        original_query=original_query,
        query_expansion=query_expansion,
        now_year=now_year,
        source_meta=source_meta,
        skipped_sources=skipped_sources,
        requested_limit=requested_limit,
    )


def merge_coverage(
    blocks: Sequence[Dict[str, Any]],
    merged_items: Sequence[Dict[str, Any]],
    query_variants: Optional[Sequence[str]] = None,
    timestamp: Optional[str] = None,
    original_query: Optional[str] = None,
    query_expansion: Optional[Dict[str, Any]] = None,
    now_year: Optional[int] = None,
    requested_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Combine per-facet coverage blocks (counts are summed over facets)."""
    per_source_stats: Dict[str, Dict[str, int]] = {}
    source_meta: Dict[str, Dict[str, Any]] = {}
    skipped: List[Dict[str, str]] = []
    for block in blocks:
        for name, stats in (block.get("per_source") or {}).items():
            target = per_source_stats.setdefault(
                name, {"returned": 0, "unique_dois": 0, "high_quality": 0}
            )
            for key in ("returned", "unique_dois", "high_quality"):
                target[key] += int(stats.get(key) or 0)
            meta = source_meta.setdefault(
                name,
                {
                    "status": "ok",
                    "note": stats.get("note"),
                    "requested_limit": 0,
                    "duration_ms": 0,
                    "rate_limited": False,
                },
            )
            if stats.get("status") == "error":
                meta["status"] = "error"
                meta["error"] = stats.get("error")
            elif stats.get("status") == "rate_limited" and meta["status"] == "ok":
                meta["status"] = "rate_limited"
                meta["rate_limited"] = True
            elif stats.get("status") == "partial" and meta["status"] == "ok":
                meta["status"] = "partial"
                if stats.get("error"):
                    meta["error"] = stats["error"]
            meta["requested_limit"] = int(meta.get("requested_limit") or 0) + int(
                stats.get("requested_limit") or 0
            )
            meta["duration_ms"] = int(meta.get("duration_ms") or 0) + int(
                stats.get("duration_ms") or 0
            )
            if float(stats.get("retry_after_seconds") or 0) > float(meta.get("retry_after_seconds") or 0):
                meta["retry_after_seconds"] = stats["retry_after_seconds"]
                meta["retry_at"] = stats.get("retry_at")
        for entry in block.get("skipped_sources") or []:
            if entry not in skipped:
                skipped.append(dict(entry))

    # A source that returned records in some facets but failed in others is
    # "partial", not "error": calling it an error would hide real coverage.
    for name, stats in per_source_stats.items():
        meta = source_meta.setdefault(name, {})
        if meta.get("status") == "error" and int(stats.get("returned") or 0) > 0:
            meta["status"] = "partial"
        if meta.get("status") == "rate_limited" and int(stats.get("returned") or 0) > 0:
            meta["status"] = "partial"
            meta["rate_limited"] = True

    return _coverage_payload(
        per_source_stats,
        merged_items,
        query_variants,
        timestamp,
        original_query=original_query,
        query_expansion=query_expansion,
        now_year=now_year,
        source_meta=source_meta,
        skipped_sources=skipped,
        requested_limit=requested_limit,
    )
