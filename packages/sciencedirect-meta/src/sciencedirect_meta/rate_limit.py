"""Rate-limit policy shared by the MCP server and the helper scripts.

Every outbound request in this repository is paced from this one table, so the
MCP server and ``scripts/download_open_access.py`` cannot drift apart on how
politely they treat a service. Values are deliberately below the published
limits: a multi-facet search fires several requests per source and a burst is
what triggers a 429.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

# host -> (interval without a key, interval with a key), in seconds.
RATE_INTERVALS: Dict[str, Tuple[float, float]] = {
    "api.openalex.org": (0.5, 0.1),
    "eutils.ncbi.nlm.nih.gov": (0.35, 0.11),
    "www.ebi.ac.uk": (0.2, 0.2),
    "api.crossref.org": (0.2, 0.12),
    "export.arxiv.org": (5.0, 5.0),
    "clinicaltrials.gov": (0.5, 0.5),
    "api.unpaywall.org": (0.2, 0.2),
    "doi.org": (0.5, 0.5),
}

# How long a host stays disabled after it keeps answering 429.
COOLDOWN_SECONDS = 20.0
# Nothing waits longer than this, even if the service asks for more.
MAX_RETRY_AFTER = 20.0
# arXiv returns 429 aggressively; a long wait would stall the whole run.
MAX_RETRY_AFTER_BY_HOST: Dict[str, float] = {"export.arxiv.org": 5.0}

# Used when a host is not listed above.
DEFAULT_INTERVAL = 0.5


def interval_for(host: str, has_key: bool = False) -> float:
    """Seconds to leave between two requests to ``host``."""
    anonymous, keyed = RATE_INTERVALS.get(host.lower(), (DEFAULT_INTERVAL, DEFAULT_INTERVAL))
    return keyed if has_key else anonymous


def retry_after_seconds(
    retry_after_header: Optional[str],
    attempt: int,
    host: str = "",
) -> float:
    """Delay before retrying, honouring ``Retry-After`` within a safe ceiling."""
    ceiling = min(
        MAX_RETRY_AFTER,
        MAX_RETRY_AFTER_BY_HOST.get(host.lower(), MAX_RETRY_AFTER),
    )
    value = (retry_after_header or "").strip()
    if value.isdigit():
        return min(float(value), ceiling)
    return min(2.0 * (attempt + 1), ceiling)


def cooldown_for(host: str = "") -> float:
    """Seconds a host stays disabled after a persistent 429."""
    return min(
        COOLDOWN_SECONDS,
        MAX_RETRY_AFTER_BY_HOST.get(host.lower(), COOLDOWN_SECONDS),
    )
