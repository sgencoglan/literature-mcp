"""SCImago journal quartile lookup from the local CSV."""


from __future__ import annotations

import csv
import difflib
import gzip
import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sciencedirect_meta import _common
from sciencedirect_meta._common import _error, logger

_JOURNAL_RANK_CACHE: Optional[Dict[str, Any]] = None


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
    """Load SCImago data once per dataset; no network request is made."""
    global _JOURNAL_RANK_CACHE

    path = _common.JOURNAL_RANK_PATH
    # Cache by resolved path so pointing JOURNAL_RANK_PATH at another file (a
    # test fixture, a newer SCImago dump) does not return the previous data.
    cache_key = str(path)
    if _JOURNAL_RANK_CACHE is not None and _JOURNAL_RANK_CACHE.get("path") == cache_key:
        return _JOURNAL_RANK_CACHE

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
        "path": cache_key,
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


def _attach_quartiles(items: Sequence[Dict[str, Any]]) -> None:
    """Attach SCImago quartiles from the local dataset when available."""
    if not items:
        return
    try:
        data = _load_journal_rank_data()
    except Exception as exc:  # noqa: BLE001 - optional local dataset
        logger.info("Quartile dataset unavailable: %s", exc)
        return
    for item in items:
        if item.get("quartile"):
            continue
        journal = item.get("journal")
        if not journal:
            continue
        entry, _match = _find_journal_rank(str(journal), data)
        if entry and entry.get("quartile"):
            item["quartile"] = entry["quartile"]


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
        "dataset": str(_common.JOURNAL_RANK_PATH),
        "count": len(results),
        "results": results,
        "notes": [
            "Quartile is the SCImago 'SJR Best Quartile' field.",
            "Q1 is the highest quartile; Q4 is the lowest.",
            "Quartile is bibliometric context, not a measure of article quality.",
        ],
    }


