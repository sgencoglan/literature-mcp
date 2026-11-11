"""Shared configuration, constants and small text helpers."""


from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import mcp.types as types

from sciencedirect_meta import pipeline
from sciencedirect_meta.server import (
    normalize_doi,
    redact_secrets,
)

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


LIT_PROJECTS_REGISTRY = Path(
    os.environ.get("LIT_PROJECTS_REGISTRY", "~/.literature-mcp/projects.json")
).expanduser()


_PROJECTS_CACHE: Dict[str, Any] = {"mtime": None, "data": {}}


AVAILABLE_SOURCES = pipeline.AVAILABLE_SOURCES


DEFAULT_SOURCES = pipeline.DEFAULT_SOURCES


logger = logging.getLogger("local-research")


def _json_text(payload: Any) -> List[types.TextContent]:
    return [
        types.TextContent(
            type="text",
            text=json.dumps(payload, ensure_ascii=False, indent=2),
        )
    ]


def _error(message: str, code: str = "error", **extra: Any) -> Dict[str, Any]:
    """Error payload with a stable machine-readable ``error_code``.

    Agents should branch on ``error_code`` rather than parsing the human
    message, which is Turkish prose and may change.
    """
    payload: Dict[str, Any] = {
        "error": redact_secrets(message),
        "error_code": code,
    }
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


_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)


def _clean_doi(value: str) -> str:
    doi = (value or "").strip().rstrip(".,;:)]}\"'")
    return normalize_doi(doi)


