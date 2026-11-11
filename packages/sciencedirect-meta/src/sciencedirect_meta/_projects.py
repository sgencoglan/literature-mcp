"""Project registry (shared with the paperqa-local MCP) and scoping."""


from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from sciencedirect_meta import _common, pipeline
from sciencedirect_meta._common import _PROJECTS_CACHE, _clean_doi, logger
from sciencedirect_meta._crossref import crossref_work
from sciencedirect_meta.server import (
    _openalex_params,
    normalize_doi,
    polite_get,
    redact_secrets,
)


def _projects_registry() -> Dict[str, Any]:
    """Read the shared projects.json (cached by mtime)."""
    path = _common.LIT_PROJECTS_REGISTRY
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


def _project_setup_root(project: Optional[str]) -> Optional[str]:
    """``output_directory`` (or PDF folder) of a registered project."""
    if not project:
        return None
    try:
        config = _project_config(project)
    except KeyError:
        return None
    return (
        str(config.get("output_directory") or config.get("paper_directory") or "").strip()
        or None
    )


def _apply_project_setup(
    project: Optional[str] = None,
    project_directory: Optional[str] = None,
) -> Dict[str, Any]:
    """Load the API keys of the project being worked on.

    Delegates to :func:`sciencedirect_meta.pipeline.apply_project_setup`, which
    prefers ``project_directory``, then ``LIT_PROJECT_ROOT``, then the
    registered project's ``output_directory``.
    """
    return pipeline.apply_project_setup(project_directory, _project_setup_root(project))


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
        response = await polite_get(
            f"https://api.openalex.org/works/doi:{quote(key, safe='')}",
            params=_openalex_params({
                "select": "id,doi,is_retracted,cited_by_count,counts_by_year",
            }),
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
        logger.info("OpenAlex flags failed for %s: %s", key, redact_secrets(exc))
    _openalex_flags_cache[key] = payload
    return payload


