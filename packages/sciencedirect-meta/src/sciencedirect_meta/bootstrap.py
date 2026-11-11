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

A tool call that names a concrete project root (``project_directory``) re-reads
that project's own ``setup.txt`` through :func:`load_for_project`, so the API
keys of the project being worked on always win over keys read from another
registered project at process start. Values supplied explicitly in the process
environment (``opencode.json``) keep precedence unless they were themselves
loaded from an earlier ``setup.txt``.

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
STATUS: Dict[str, object] = {
    "path": None,
    "loaded": [],
    "skipped": [],
    "insecure": False,
}

# A setup.txt readable by other local users is a credential leak. Refuse to
# load its secrets unless the operator explicitly accepts the risk.
ALLOW_INSECURE_ENV = "LIT_ALLOW_INSECURE_SETUP"

# Environment variables that this module wrote itself. A later load() may
# replace them (for example when a different project's setup.txt is used),
# while values that came from the real process environment never change.
BOOTSTRAP_KEYS: set[str] = set()

EMAIL_ENV_NAMES = ("CROSSREF_MAILTO", "NCBI_EMAIL", "UNPAYWALL_EMAIL")


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


def project_setup_candidates(project_root: str | Path) -> List[Path]:
    """``setup.txt`` locations for one project root, nearest first.

    The root itself wins; the two parents are checked because agents are
    often given a workflow folder (``03_kaynak_kesfi``) instead of the root.
    """
    root = Path(project_root).expanduser()
    candidates: List[Path] = []
    current = root
    for _ in range(3):
        candidates.append(current / SETUP_FILENAME)
        if current.parent == current:
            break
        current = current.parent
    return candidates


def find_project_setup_file(project_root: str | Path) -> Optional[Path]:
    for path in project_setup_candidates(project_root):
        if path.is_file():
            return path
    return None


def _apply(values: Dict[str, str], setup_path: Path, override_loaded: bool) -> Dict[str, object]:
    status: Dict[str, object] = {"path": str(setup_path), "loaded": [], "skipped": []}
    email = values.pop("email", "")
    pairs: Dict[str, str] = {}
    if email:
        for name in EMAIL_ENV_NAMES:
            pairs[name] = email
    pairs.update(values)

    if override_loaded:
        # Keys that came from a previous setup.txt but are absent here must not
        # leak from another project into this one.
        for name in list(BOOTSTRAP_KEYS - set(pairs)):
            os.environ.pop(name, None)
            BOOTSTRAP_KEYS.discard(name)

    for name, value in pairs.items():
        current = os.environ.get(name, "").strip()
        replaceable = name in BOOTSTRAP_KEYS
        if current and not (override_loaded and replaceable):
            status["skipped"].append(name)
            continue
        os.environ[name] = value
        BOOTSTRAP_KEYS.add(name)
        status["loaded"].append(name)
    return status


def is_insecure(path: Path) -> bool:
    """True when the file is readable or writable by group/other."""
    try:
        return bool(path.stat().st_mode & 0o077)
    except OSError:
        return False


def load(path: Optional[Path] = None, *, override_loaded: bool = False) -> Dict[str, object]:
    """Populate ``os.environ`` from setup.txt; existing values win.

    ``override_loaded=True`` lets a project-specific file replace values that
    an earlier ``setup.txt`` load wrote; explicit process environment values
    are still never overwritten.

    A file that other local users can read is treated as compromised: its
    secrets are not loaded and ``STATUS["insecure"]`` is set so the
    diagnostics tool can explain why no key is active. Set
    ``LIT_ALLOW_INSECURE_SETUP=1`` to override.
    """
    setup_path = path or find_setup_file()
    if setup_path is None:
        STATUS["path"] = None
        STATUS["loaded"] = []
        STATUS["skipped"] = []
        STATUS["insecure"] = False
        logger.info("setup.txt bulunamadı; yalnızca ortam değişkenleri kullanılacak")
        return STATUS

    STATUS["path"] = str(setup_path)
    STATUS["loaded"] = []
    STATUS["skipped"] = []
    insecure = is_insecure(setup_path)
    STATUS["insecure"] = insecure

    if insecure and os.environ.get(ALLOW_INSECURE_ENV, "").strip() != "1":
        logger.error(
            "%s grup/diğer kullanıcılar tarafından okunabilir; anahtarlar "
            "yüklenmedi. `chmod 600 %s` uygulayın veya bilinçli olarak "
            "%s=1 verin.",
            setup_path,
            setup_path,
            ALLOW_INSECURE_ENV,
        )
        return STATUS
    if insecure:
        logger.warning(
            "%s güvenli olmayan izinlerle yüklendi (%s=1)",
            setup_path,
            ALLOW_INSECURE_ENV,
        )

    values = parse_setup_file(setup_path)
    applied = _apply(values, setup_path, override_loaded)
    STATUS["loaded"] = applied["loaded"]
    STATUS["skipped"] = applied["skipped"]

    logger.info(
        "setup.txt: %s (%d değişken yüklendi, %d zaten tanımlıydı)",
        setup_path,
        len(STATUS["loaded"]),
        len(STATUS["skipped"]),
    )
    return STATUS


def load_for_project(project_root: Optional[str | Path]) -> Dict[str, object]:
    """Apply the ``setup.txt`` of one project root, if it has one.

    Safe to call repeatedly: with no file nothing changes and an empty status
    is returned, so tools keep working with process-environment credentials.
    """
    if not project_root:
        return {"path": None, "loaded": [], "skipped": [], "insecure": False}
    setup_path = find_project_setup_file(project_root)
    if setup_path is None:
        return {"path": None, "loaded": [], "skipped": [], "insecure": False}
    # Re-reading the same file for every facet is pointless; its values are
    # already in os.environ. An insecure file is re-read so that a `chmod 600`
    # applied while the server is running starts working without a restart.
    if (
        str(setup_path) == str(STATUS.get("path") or "")
        and not STATUS.get("insecure")
    ):
        return STATUS
    return load(setup_path, override_loaded=True)
