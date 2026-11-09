"""Load project credentials from ``setup.txt`` at process start.

The MCP servers and the open-access downloader are normally launched by the
editor, not from the project folder, so ``setup.txt`` is not on the path by
default. This module finds it once at import time and fills ``os.environ``
without ever overriding a value that was already supplied.

Resolution order for ``setup.txt``:

1. ``LIT_SETUP_FILE`` (explicit path)
2. ``LIT_PROJECT_ROOT`` / ``setup.txt``
3. ``setup.txt`` next to each registered project in ``projects.json``
4. ``setup.txt`` in the current directory or one of its parents
5. ``setup.txt`` in the repository root

Only the four known keys are imported; unknown keys are ignored so a stray
value cannot inject arbitrary environment variables.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("sciencedirect-meta.bootstrap")

SETUP_FILENAME = "setup.txt"
MAX_PARENT_DEPTH = 5

# key in setup.txt -> environment variable it fills
KEY_TARGETS: Dict[str, str] = {
    "openalex": "OPENALEX_API_KEY",
    "openalex_key": "OPENALEX_API_KEY",
    "openalex_api_key": "OPENALEX_API_KEY",
    "pubmed": "PUBMED_API_KEY",
    "pubmed_key": "PUBMED_API_KEY",
    "pubmed_api_key": "PUBMED_API_KEY",
    "ncbi": "PUBMED_API_KEY",
    "ncbi_key": "PUBMED_API_KEY",
    "ncbi_api_key": "PUBMED_API_KEY",
    "semantic_scholar": "SEMANTIC_SCHOLAR_API_KEY",
    "semantic_scholar_key": "SEMANTIC_SCHOLAR_API_KEY",
    "semantic_scholar_api_key": "SEMANTIC_SCHOLAR_API_KEY",
    "s2": "SEMANTIC_SCHOLAR_API_KEY",
    "s2_key": "SEMANTIC_SCHOLAR_API_KEY",
}

EMAIL_KEYS = {
    "email",
    "e_posta",
    "eposta",
    "mail",
    "contact",
    "contact_email",
    "crossref_mailto",
    "ncbi_email",
    "unpaywall_email",
}

# Filled by load(); tests and callers can inspect what happened.
STATUS: Dict[str, object] = {"path": None, "loaded": [], "skipped": []}


def parse_setup_file(path: Path) -> Dict[str, str]:
    """Return the recognised ``key=value`` pairs from one setup.txt."""
    values: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("setup.txt okunamadı (%s): %s", path, exc)
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        key = re.sub(r"[\s\-]+", "_", key.strip().lower())
        value = value.strip().strip('"').strip("'").strip()
        if not value:
            continue
        if key in EMAIL_KEYS:
            values["email"] = value
        elif key in KEY_TARGETS:
            values[KEY_TARGETS[key]] = value
    return values


def _registry_path() -> Optional[Path]:
    registry = os.environ.get("LIT_PROJECTS_REGISTRY", "").strip()
    if registry:
        return Path(registry).expanduser()
    return Path("~/.literature-mcp/projects.json").expanduser()


def _registry_setup_candidates() -> List[Path]:
    """setup.txt next to each registered project (output or PDF folder)."""
    registry = _registry_path()
    candidates: List[Path] = []
    if not registry or not registry.is_file():
        return candidates
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return candidates
    projects = payload.get("projects") if isinstance(payload, dict) else None
    if isinstance(projects, dict):
        entries = list(projects.values())
    elif isinstance(projects, list):
        entries = projects
    else:
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for field in ("output_directory", "paper_directory"):
            value = str(entry.get(field) or "").strip()
            if not value:
                continue
            base = Path(value).expanduser()
            # paper_directory is usually <root>/<workflow>/fulltext
            candidates.append(base / SETUP_FILENAME)
            candidates.append(base.parent / SETUP_FILENAME)
            candidates.append(base.parent.parent / SETUP_FILENAME)
    return candidates


def _walk_up(start: Path) -> List[Path]:
    candidates: List[Path] = []
    current = start
    for _ in range(MAX_PARENT_DEPTH + 1):
        candidates.append(current / SETUP_FILENAME)
        if current.parent == current:
            break
        current = current.parent
    return candidates


def candidate_paths() -> List[Path]:
    """Ordered, de-duplicated places where setup.txt may live."""
    candidates: List[Path] = []

    explicit = os.environ.get("LIT_SETUP_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    project_root = os.environ.get("LIT_PROJECT_ROOT", "").strip()
    if project_root:
        candidates.append(Path(project_root).expanduser() / SETUP_FILENAME)

    candidates.extend(_registry_setup_candidates())
    candidates.extend(_walk_up(Path.cwd().resolve()))
    candidates.append(Path(__file__).resolve().parents[3] / SETUP_FILENAME)

    seen: set[str] = set()
    ordered: List[Path] = []
    for path in candidates:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def find_setup_file() -> Optional[Path]:
    for path in candidate_paths():
        if path.is_file():
            return path
    return None


def load(path: Optional[Path] = None) -> Dict[str, object]:
    """Populate ``os.environ`` from setup.txt; existing values win."""
    setup_path = path or find_setup_file()
    STATUS["path"] = str(setup_path) if setup_path else None
    STATUS["loaded"] = []
    STATUS["skipped"] = []
    if setup_path is None:
        logger.info("setup.txt bulunamadı; yalnızca ortam değişkenleri kullanılacak")
        return STATUS

    values = parse_setup_file(setup_path)
    email = values.pop("email", "")
    if email:
        for name in ("CROSSREF_MAILTO", "NCBI_EMAIL", "UNPAYWALL_EMAIL"):
            if not os.environ.get(name, "").strip():
                os.environ[name] = email
                STATUS["loaded"].append(name)

    for name, value in values.items():
        if os.environ.get(name, "").strip():
            STATUS["skipped"].append(name)
            continue
        os.environ[name] = value
        STATUS["loaded"].append(name)

    try:
        mode = setup_path.stat().st_mode
        if mode & 0o077:
            logger.warning(
                "%s diğer kullanıcılar tarafından okunabilir; `chmod 600` önerilir",
                setup_path,
            )
    except OSError:
        pass

    logger.info(
        "setup.txt: %s (%d değişken yüklendi, %d zaten tanımlıydı)",
        setup_path,
        len(STATUS["loaded"]),
        len(STATUS["skipped"]),
    )
    return STATUS
