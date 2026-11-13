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
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from sciencedirect_meta import __version__, bootstrap
from sciencedirect_meta.rate_limit import (
    COOLDOWN_SECONDS,
    MAX_INLINE_WAIT,
    MAX_RETRY_AFTER_BY_HOST,
    RATE_INTERVALS,
    cooldown_for,
    interval_for,
    retry_after_seconds,
)
from sciencedirect_meta.rate_limit import (
    MAX_RETRY_AFTER as MAX_RETRY_AFTER_SECONDS,
)

# Proje setup.txt dosyasını süreç başında oku; var olan ortam değişkenleri
# her zaman önceliklidir.
bootstrap.load()

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

# Optional API credentials. Both services work without a key, but keys raise
# the rate limits: NCBI allows 10 req/s with a key (3 without), and OpenAlex
# validates its key and grants the authenticated quota.
OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip()
PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY", "").strip()
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
NCBI_TOOL = os.environ.get("NCBI_TOOL", "sciencedirect-meta-mcp").strip() or "sciencedirect-meta-mcp"
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", MAILTO).strip() or MAILTO

HTTP_TIMEOUT = 35.0
MAX_ABSTRACT_CHARS = 6000
MAX_ENRICH = 15          # max Crossref PII lookups per tool call
CROSSREF_CONCURRENCY = 3

USER_AGENT = f"sciencedirect-meta-mcp/0.1 (mailto:{MAILTO})"


def refresh_credentials() -> None:
    """Re-read API keys from the environment after a setup.txt reload."""
    global MAILTO, OPENALEX_API_KEY, PUBMED_API_KEY, SEMANTIC_SCHOLAR_API_KEY
    global NCBI_EMAIL, USER_AGENT

    MAILTO = (
        os.environ.get("CROSSREF_MAILTO", DEFAULT_MAILTO).strip() or DEFAULT_MAILTO
    )
    OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "").strip()
    PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY", "").strip()
    SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    NCBI_EMAIL = os.environ.get("NCBI_EMAIL", MAILTO).strip() or MAILTO
    USER_AGENT = f"sciencedirect-meta-mcp/0.1 (mailto:{MAILTO})"
    _client.headers["User-Agent"] = USER_AGENT


def active_setup_path() -> Optional[str]:
    """Path of the setup.txt currently in effect (for diagnostics)."""
    path = bootstrap.STATUS.get("path")
    return str(path) if path else None

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("sciencedirect-meta")


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


_client = _new_client()
_client_loop: Optional[asyncio.AbstractEventLoop] = None
# Multiprocess-safe (per-process) semaphore; created lazily so importing the
# module outside an event loop cannot bind it to the wrong loop.
_crossref_sem: Optional[asyncio.Semaphore] = None


def client_for_loop() -> httpx.AsyncClient:
    """Return an AsyncClient bound to the running event loop.

    An ``httpx.AsyncClient`` keeps a connection pool tied to the loop it first
    used. Tests and library callers create a fresh loop per ``asyncio.run``, so
    reusing one client raised "Event loop is closed" and leaked transports.
    The client is recreated whenever the loop changes.
    """
    global _client, _client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return _client
    if _client_loop is not loop:
        _client = _new_client()
        _client_loop = loop
    return _client


def crossref_semaphore() -> asyncio.Semaphore:
    global _crossref_sem
    if _crossref_sem is None:
        _crossref_sem = asyncio.Semaphore(CROSSREF_CONCURRENCY)
    return _crossref_sem


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


def _openalex_params(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """OpenAlex query params with polite-pool mailto and optional API key."""
    params: Dict[str, Any] = {"mailto": MAILTO}
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    if extra:
        params.update(extra)
    return params


def _pubmed_params(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """NCBI E-utilities params with tool/email and optional API key."""
    params: Dict[str, Any] = {"tool": NCBI_TOOL, "email": NCBI_EMAIL}
    if PUBMED_API_KEY:
        params["api_key"] = PUBMED_API_KEY
    if extra:
        params.update(extra)
    return params


class RateLimitedError(RuntimeError):
    """Raised when a source keeps answering 429 after all polite retries."""

    def __init__(self, message: str, source: str = "", retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.source = source
        self.retry_after = retry_after


# The interval table lives in ``rate_limit`` so the MCP and
# scripts/download_open_access.py cannot drift apart.
_RATE_INTERVALS = RATE_INTERVALS
_HOST_LOCKS: Dict[str, asyncio.Lock] = {}
_HOST_LAST_CALL: Dict[str, float] = {}
_HOST_COOLDOWN_UNTIL: Dict[str, float] = {}
_HOST_LOCKS_LOOP: Optional[asyncio.AbstractEventLoop] = None

# How long a source stays disabled after a 429, so the remaining facets in the
# same run do not hammer it again.
RATE_LIMIT_COOLDOWN_SECONDS = COOLDOWN_SECONDS
MAX_RETRY_AFTER = MAX_RETRY_AFTER_SECONDS
_MAX_RETRY_AFTER_BY_HOST = MAX_RETRY_AFTER_BY_HOST


def _host(url: str) -> str:
    try:
        return (httpx.URL(url).host or "").lower()
    except Exception:  # noqa: BLE001 - never fail a search over URL parsing
        return ""


def _has_key_for(host: str) -> bool:
    if host == "api.openalex.org":
        return bool(OPENALEX_API_KEY)
    if host == "eutils.ncbi.nlm.nih.gov":
        return bool(PUBMED_API_KEY)
    return False


def _rate_interval(host: str) -> float:
    return interval_for(host, _has_key_for(host))


def host_in_cooldown(url: str) -> bool:
    return time.monotonic() < _HOST_COOLDOWN_UNTIL.get(_host(url), 0.0)


def _retry_after_seconds(response: httpx.Response, attempt: int, host: str) -> float:
    return retry_after_seconds(response.headers.get("Retry-After"), attempt, host)


def _host_lock(host: str) -> asyncio.Lock:
    """One lock per host, recreated when the event loop changes."""
    global _HOST_LOCKS_LOOP
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and _HOST_LOCKS_LOOP is not loop:
        _HOST_LOCKS.clear()
        _HOST_LOCKS_LOOP = loop
    return _HOST_LOCKS.setdefault(host, asyncio.Lock())


async def _throttle(url: str) -> None:
    """Space requests to the same host so rate limits are respected."""
    host = _host(url)
    interval = _rate_interval(host)
    if not host or interval <= 0:
        return
    lock = _host_lock(host)
    async with lock:
        elapsed = time.monotonic() - _HOST_LAST_CALL.get(host, 0.0)
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)
        _HOST_LAST_CALL[host] = time.monotonic()


async def polite_get(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    attempts: int = 4,
    follow_redirects: Optional[bool] = None,
) -> httpx.Response:
    """Throttled GET that retries 429/5xx and never returns a 429 silently.

    A source that is still rate limited after ``attempts`` raises
    :class:`RateLimitedError`; callers record it as ``rate_limited`` instead
    of aborting the whole combined search.
    """
    host = _host(url)
    if host_in_cooldown(url):
        raise RateLimitedError(
            f"{host}: hız limiti nedeniyle geçici olarak devre dışı", source=host,
            retry_after=max(0.0, _HOST_COOLDOWN_UNTIL[host] - time.monotonic()),
        )

    last_error: Optional[Exception] = None
    response: Optional[httpx.Response] = None
    request_kwargs: Dict[str, Any] = {}
    if follow_redirects is not None:
        request_kwargs["follow_redirects"] = follow_redirects
    for attempt in range(attempts):
        await _throttle(url)
        # Başka eşzamanlı çağrı beklerken host 429 aldıysa yeniden istek atma.
        if host_in_cooldown(url):
            raise RateLimitedError(f"{host}: bekleme sürüyor", source=host,
                                   retry_after=max(0.0, _HOST_COOLDOWN_UNTIL[host] - time.monotonic()))
        try:
            response = await client_for_loop().get(
                url, params=params, headers=headers, **request_kwargs
            )
        except httpx.RequestError as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            raise

        if response.status_code == 429:
            delay = _retry_after_seconds(response, attempt, host)
            _HOST_COOLDOWN_UNTIL[host] = max(_HOST_COOLDOWN_UNTIL.get(host, 0.0), time.monotonic() + delay)
            if attempt < attempts - 1 and delay <= MAX_INLINE_WAIT:
                await asyncio.sleep(delay)
                continue
            cooldown = max(delay, cooldown_for(host))
            _HOST_COOLDOWN_UNTIL[host] = max(_HOST_COOLDOWN_UNTIL.get(host, 0.0), time.monotonic() + cooldown)
            raise RateLimitedError(
                f"{host}: HTTP 429 (deneme {attempts}); kaynak "
                f"{int(cooldown)} sn devre dışı",
                source=host,
                retry_after=cooldown,
            )
        if response.status_code >= 500 and attempt < attempts - 1:
            delay = _retry_after_seconds(response, attempt, host)
            if delay > MAX_INLINE_WAIT:
                _HOST_COOLDOWN_UNTIL[host] = max(_HOST_COOLDOWN_UNTIL.get(host, 0.0), time.monotonic() + delay)
                raise RateLimitedError(f"{host}: HTTP {response.status_code}; Retry-After bekleniyor", source=host, retry_after=delay)
            await asyncio.sleep(delay)
            continue
        return response

    if response is not None:
        return response
    raise last_error or httpx.ConnectError("istek tamamlanamadı")


async def _get_with_retry(
    url: str,
    params: Dict[str, Any],
    attempts: int = 4,
) -> httpx.Response:
    """Backwards-compatible wrapper around :func:`polite_get`."""
    return await polite_get(url, params=params, attempts=attempts)


def redact_secrets(value: Any) -> str:
    """Remove API keys from error text before it reaches logs or tool output."""
    text = str(value)
    for secret in (OPENALEX_API_KEY, PUBMED_API_KEY, SEMANTIC_SCHOLAR_API_KEY):
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


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


def _first_author_token(item: Dict[str, Any]) -> str:
    """Surname-ish token of the first author, for title-level deduplication."""
    authors = item.get("authors") or []
    if not authors:
        return ""
    first = str(authors[0] or "").strip()
    if not first:
        return ""
    if "," in first:
        # "Lovelace, Ada" -> surname is the part before the comma
        surname = first.split(",", 1)[0]
    else:
        # "Ada Lovelace" -> surname is the last token
        surname = first.split()[-1] if first.split() else ""
    return re.sub(r"[^a-z0-9]+", "", surname.lower())[:24]


def _dedupe_key(item: Dict[str, Any]) -> str:
    """Stable identity for one record.

    DOI wins because it is the only globally unique identifier. Without a DOI
    the title alone is not enough: editorials, errata and same-titled papers
    from different years would collapse into one row. The key therefore also
    carries the publication year and the first author.
    """
    doi = normalize_doi(item.get("doi"))
    if doi:
        return "doi:" + doi
    title = re.sub(r"[^a-z0-9]+", "", (item.get("title") or "").lower())
    if not title:
        return ""
    year = str(item.get("year") or "").strip()
    author = _first_author_token(item)
    return f"title:{title[:140]}|{year}|{author}"


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
    # Prefer the richer record for the fields where "first wins" is wrong.
    if extra.get("year") and not target.get("year"):
        target["year"] = extra["year"]
    if extra.get("journal") and not target.get("journal"):
        target["journal"] = extra["journal"]
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

    async with crossref_semaphore():
        try:
            url = f"https://api.crossref.org/works/{quote(key, safe='')}"
            response = await polite_get(url, params={"mailto": MAILTO}, attempts=3)
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
    work_types: Optional[Sequence[str]] = None,
    min_citations: Optional[int] = None,
    has_abstract: bool = False,
    semantic_search: bool = False,
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
    if work_types:
        types = "|".join(
            str(value).strip() for value in work_types if str(value).strip()
        )
        if types:
            filters.append(f"type:{types}")
    if min_citations is not None:
        filters.append(f"cited_by_count:>{max(0, int(min_citations))}")
    if has_abstract:
        filters.append("has_abstract:true")

    params = _openalex_params({
        "per-page": max(1, min(limit, 50)),
        "select": (
            "id,doi,title,publication_year,publication_date,authorships,"
            "primary_location,abstract_inverted_index,cited_by_count,"
            "open_access,best_oa_location,type,relevance_score"
        ),
    })
    if semantic_search:
        params["search.semantic"] = query
    else:
        params["search"] = query
    if filters:
        params["filter"] = ",".join(filters)
    response = await _get_with_retry("https://api.openalex.org/works", params)
    if response.status_code == 429:
        raise RuntimeError(
            "OpenAlex 429: anonim günlük kota dolu; OPENALEX_API_KEY tanımlayın "
            "veya kısa süre sonra tekrar deneyin"
        )
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
        item = _paper(
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
        if work.get("relevance_score") is not None:
            item["openalex_relevance_score"] = work.get("relevance_score")
        results.append(item)

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


async def search_pubmed(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> List[Dict[str, Any]]:
    term = query
    if year_from or year_to:
        term = f"({query}) AND ({year_from or 1800}:{year_to or 3000}[dp])"
    search = await _get_with_retry(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        _pubmed_params({
            "db": "pubmed",
            "term": term,
            "retmode": "json",
            "retmax": max(1, min(limit, 50)),
            "sort": "relevance",
        }),
    )
    search.raise_for_status()
    ids = search.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    fetch = await _get_with_retry(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        _pubmed_params({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}),
    )
    fetch.raise_for_status()
    return _parse_pubmed_xml(fetch.text)


# --------------------------------------------------------------------------- #
# Europe PMC
# --------------------------------------------------------------------------- #

async def search_europepmc(
    query: str,
    limit: int = 10,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> List[Dict[str, Any]]:
    epmc_query = query
    if year_from or year_to:
        epmc_query = (
            f"({query}) AND FIRST_PDATE:[{year_from or 1800}-01-01 "
            f"TO {year_to or 3000}-12-31]"
        )
    response = await polite_get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={
            "query": epmc_query,
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

AVAILABLE_SOURCES = (
    "openalex",
    "semantic_scholar",
    "pubmed",
    "europepmc",
    "crossref",
    "arxiv",
    "clinicaltrials",
)
DEFAULT_SOURCES = list(AVAILABLE_SOURCES)


def _resolve_sources(
    sources: Optional[Sequence[str]] = None,
    include_semantic_scholar: bool = True,
    include_arxiv: bool = True,
    include_clinicaltrials: bool = True,
) -> List[str]:
    """Every available source by default; ``sources`` narrows the selection."""
    from sciencedirect_meta import pipeline

    return pipeline.resolve_sources(
        sources,
        include_semantic_scholar=include_semantic_scholar,
        include_arxiv=include_arxiv,
        include_clinicaltrials=include_clinicaltrials,
    )


async def search_all(
    query: str,
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
    sources: Optional[Sequence[str]] = None,
    project_directory: Optional[str] = None,
) -> Dict[str, Any]:
    """Combined search over every source; see ``pipeline.run_multi_source_search``.

    The implementation lives in ``sciencedirect_meta.pipeline`` and is shared
    with ``search_literature`` so both tools always behave the same way.
    """
    from sciencedirect_meta import pipeline

    return await pipeline.run_multi_source_search(
        query,
        sources=sources,
        limit=limit,
        year_from=year_from,
        year_to=year_to,
        priority_only=priority_only,
        allowed_publishers=allowed_publishers,
        include_semantic_scholar=include_semantic_scholar,
        include_arxiv=include_arxiv,
        include_clinicaltrials=include_clinicaltrials,
        query_variants=query_variants,
        query_expansion=query_expansion,
        project_directory=project_directory,
    )


def _attach_quartiles_best_effort(items: Sequence[Dict[str, Any]]) -> None:
    """Add SCImago quartiles when the local dataset is available."""
    if not items:
        return
    try:
        from sciencedirect_meta.local_research import _attach_quartiles

        _attach_quartiles(items)
    except Exception as exc:  # noqa: BLE001 - optional local dataset
        logger.info("Quartile enrichment skipped: %s", exc)


async def get_article(identifier: str, id_type: str = "doi") -> Dict[str, Any]:
    id_type = (id_type or "doi").lower()
    doi = normalize_doi(identifier) if id_type == "doi" else ""
    pmid = identifier.strip() if id_type == "pmid" else ""

    items: List[Dict[str, Any]] = []

    if doi:
        try:
            response = await polite_get(
                f"https://api.openalex.org/works/doi:{quote(doi, safe='')}",
                params=_openalex_params(),
            )
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
            logger.info("OpenAlex article lookup failed: %s", redact_secrets(exc))

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
def search_diagnostics(project_directory: Optional[str] = None) -> Dict[str, Any]:
    """Describe the effective search configuration without leaking secrets."""
    from sciencedirect_meta import pipeline

    setup = pipeline.apply_project_setup(project_directory)
    keys = {
        "openalex": bool(OPENALEX_API_KEY),
        "pubmed_ncbi": bool(PUBMED_API_KEY),
        "semantic_scholar": bool(SEMANTIC_SCHOLAR_API_KEY),
    }
    now = time.monotonic()
    cooldowns = {
        host: round(until - now, 1)
        for host, until in sorted(_HOST_COOLDOWN_UNTIL.items())
        if until > now
    }
    source_cooldowns = {}
    try:
        from sciencedirect_meta import sources as extra_sources

        source_cooldowns = {
            name: round(until - now, 1)
            for name, until in extra_sources._SOURCE_COOLDOWN.items()
            if until > now
        }
        if extra_sources._s2_in_cooldown():
            source_cooldowns.setdefault(
                "semantic_scholar", round(extra_sources._S2_COOLDOWN_UNTIL - now, 1)
            )
    except Exception:  # noqa: BLE001 - diagnostics must never fail
        pass

    status = bootstrap.STATUS
    return {
        "version": __version__,
        "setup_file": setup.get("path"),
        "setup_error": setup.get("error"),
        "setup_loaded": list(status.get("loaded") or []),
        "setup_skipped": list(status.get("skipped") or []),
        "setup_insecure": bool(status.get("insecure")),
        "credentials_configured": keys,
        "contact_email_configured": bool(MAILTO and MAILTO != DEFAULT_MAILTO),
        "default_sources": list(pipeline.DEFAULT_SOURCES),
        "available_sources": list(pipeline.AVAILABLE_SOURCES),
        "priority_only_default": False,
        "rate_limit_intervals_seconds": dict(_RATE_INTERVALS),
        "host_cooldowns": cooldowns,
        "source_cooldowns": source_cooldowns,
        "projects_registry": os.environ.get(
            "LIT_PROJECTS_REGISTRY", "~/.literature-mcp/projects.json"
        ),
        "journal_rank_dataset": os.environ.get("JOURNAL_RANK_CSV") or "yok",
        "notes": [
            "Anahtarlar yalnızca var/yok olarak raporlanır; değerleri döndürülmez.",
            "Bir kaynak rate_limited ise diğerleri çalışmaya devam eder.",
            "setup_insecure=true ise anahtarlar yüklenmedi; chmod 600 uygulayın.",
        ],
    }


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
                    "project_directory": {
                        "type": "string",
                        "description": "Project root; its setup.txt supplies the API keys for this call.",
                    },
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
                "Search PubMed via NCBI E-utilities (works without a key; PUBMED_API_KEY "
                "raises the rate limit to 10 req/s). Returns abstracts, DOIs and PMIDs; "
                "Elsevier DOIs get a ScienceDirect DOI link."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_directory": {
                        "type": "string",
                        "description": "Project root; its setup.txt supplies the API keys for this call.",
                    },
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
                    "project_directory": {
                        "type": "string",
                        "description": "Project root; its setup.txt supplies the API keys for this call.",
                    },
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="search_semantic_scholar",
            description=(
                "Search Semantic Scholar's Graph API. Returns title, abstract, year, DOI, "
                "citation/influential-citation counts, open-access PDF, venue, authors, "
                "paperId and URL. Works anonymously; SEMANTIC_SCHOLAR_API_KEY raises the "
                "rate limit. Failures are swallowed so other sources keep working."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_directory": {
                        "type": "string",
                        "description": "Project root; its setup.txt supplies the API keys for this call.",
                    },
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer"},
                    "fields_of_study": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Semantic Scholar fields of study, e.g. ['Medicine'].",
                    },
                    "open_access_only": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="search_arxiv",
            description=(
                "Search arXiv (no API key). Returns title, abstract, authors, published/updated "
                "dates, arXiv id, DOI when present, PDF/abstract URLs, categories and primary "
                "category. Results are marked is_preprint=true and receive a controlled "
                "ranking penalty."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_directory": {
                        "type": "string",
                        "description": "Project root; its setup.txt supplies the API keys for this call.",
                    },
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer"},
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional arXiv categories, e.g. ['cs.CL', 'stat.ML'].",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="search_clinicaltrials",
            description=(
                "Search ClinicalTrials.gov API v2 (no API key). Useful for intervention, RCT "
                "and clinical-study searches. Returns NCT id, status, study type, phase, "
                "conditions, interventions, start year and a study URL."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_directory": {
                        "type": "string",
                        "description": "Project root; its setup.txt supplies the API keys for this call.",
                    },
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer"},
                    "intervention_only": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="search_all",
            description=(
                "Combined search across every metadata source by default: OpenAlex (all "
                "publishers), Semantic Scholar, PubMed, Europe PMC, Crossref, arXiv and "
                "ClinicalTrials.gov. Narrow the set with sources=[...]. Adds a "
                "relevance/quality score, a transparent per-source coverage block and an "
                "evidence-scarcity signal. Deduplicates results and ranks links in this "
                "order: Ovid LWW, ScienceDirect, SpringerLink, Wiley, Taylor & Francis. "
                "Set priority_only=true to restrict results to these publishers; the "
                "default returns every publisher. Pass project_directory to use that "
                "project's setup.txt API keys."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    "year_from": {"type": "integer"},
                    "year_to": {"type": "integer"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(AVAILABLE_SOURCES)},
                        "description": (
                            "Metadata sources to query. Default: all available sources."
                        ),
                    },
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
                    "include_semantic_scholar": {"type": "boolean", "default": True},
                    "include_arxiv": {"type": "boolean", "default": True},
                    "include_clinicaltrials": {"type": "boolean", "default": True},
                    "project_directory": {
                        "type": "string",
                        "description": (
                            "Project root; its setup.txt supplies the API keys and "
                            "contact email for this call."
                        ),
                    },
                    "query_variants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Synonyms/variants used for this query; echoed in coverage.",
                    },
                    "query_expansion": {
                        "type": "object",
                        "description": (
                            "Explicit query-expansion record. Fields: original, expanded/queries, "
                            "mesh, languages, transformations, notes."
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
        types.Tool(
            name="search_diagnostics",
            description=(
                "Explain how a search will behave: which credential file and API keys are "
                "active (values are never returned), which sources are queried by default, "
                "which hosts are currently rate limited, and the effective priority_only "
                "default. Use this when a search returns fewer results than expected. "
                "Pass project_directory to inspect one project's setup.txt."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_directory": {
                        "type": "string",
                        "description": "Project root whose setup.txt should be inspected.",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> List[types.TextContent]:
    args = arguments or {}
    try:
        project_root = (
            str(args.get("project_directory") or "").strip()
            or os.environ.get("LIT_PROJECT_ROOT", "").strip()
        )
        if project_root and bootstrap.load_for_project(project_root).get("path"):
            refresh_credentials()
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

        if name == "search_semantic_scholar":
            query = str(args.get("query", "")).strip()
            if not query:
                return _text({"error": "query is required"})
            from sciencedirect_meta import sources

            results = await sources.search_semantic_scholar(
                query=query,
                limit=int(args.get("limit", 10)),
                year_from=args.get("year_from"),
                year_to=args.get("year_to"),
                fields_of_study=args.get("fields_of_study"),
                open_access_only=bool(args.get("open_access_only", False)),
            )
            sources.score_results(results, query)
            results.sort(key=lambda item: -(item.get("score") or 0.0))
            return _text(
                {
                    "query": query,
                    "count": len(results),
                    "source": "semantic_scholar",
                    "notes": [
                        "Anonymous access unless SEMANTIC_SCHOLAR_API_KEY is set; "
                        "failures return an empty result list."
                    ],
                    "results": results,
                }
            )

        if name == "search_arxiv":
            query = str(args.get("query", "")).strip()
            if not query:
                return _text({"error": "query is required"})
            from sciencedirect_meta import sources

            results = await sources.search_arxiv(
                query=query,
                limit=int(args.get("limit", 10)),
                year_from=args.get("year_from"),
                year_to=args.get("year_to"),
                categories=args.get("categories"),
            )
            sources.score_results(results, query)
            results.sort(key=lambda item: -(item.get("score") or 0.0))
            return _text(
                {
                    "query": query,
                    "count": len(results),
                    "source": "arxiv",
                    "notes": [
                        "All arXiv records are preprints (is_preprint=true) and receive "
                        "a controlled ranking penalty."
                    ],
                    "results": results,
                }
            )

        if name == "search_clinicaltrials":
            query = str(args.get("query", "")).strip()
            if not query:
                return _text({"error": "query is required"})
            from sciencedirect_meta import sources

            results = await sources.search_clinicaltrials(
                query=query,
                limit=int(args.get("limit", 10)),
                year_from=args.get("year_from"),
                year_to=args.get("year_to"),
                intervention_only=bool(args.get("intervention_only", False)),
            )
            sources.score_results(results, query)
            results.sort(key=lambda item: -(item.get("score") or 0.0))
            return _text(
                {
                    "query": query,
                    "count": len(results),
                    "source": "clinicaltrials",
                    "notes": [
                        "ClinicalTrials.gov records are study registrations, not "
                        "peer-reviewed publications."
                    ],
                    "results": results,
                }
            )

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
                include_semantic_scholar=bool(args.get("include_semantic_scholar", True)),
                include_arxiv=bool(args.get("include_arxiv", True)),
                include_clinicaltrials=bool(args.get("include_clinicaltrials", True)),
                query_variants=args.get("query_variants"),
                query_expansion=args.get("query_expansion"),
                sources=args.get("sources"),
                project_directory=args.get("project_directory"),
            )
            return _text(payload)

        if name == "search_diagnostics":
            return _text(
                search_diagnostics(
                    str(args.get("project_directory") or "").strip() or None
                )
            )

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
    except RateLimitedError as exc:
        # A rate-limited source is not a tool failure: report it without an
        # ``error`` field so callers keep the other evidence they already have.
        logger.info("Tool %s rate limited: %s", name, exc)
        return _text(
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
        return _text({"error": redact_secrets(exc), "tool": name})


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
