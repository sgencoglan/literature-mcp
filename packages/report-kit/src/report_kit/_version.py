"""Single place where the repository version is defined and checked.

The version lives in the root ``VERSION`` file and is mirrored into the two
package metadata files and the two ``__version__`` attributes. Keeping five
copies in sync by hand is how a release ends up half-versioned, so
``scripts/check_version.py`` (run by ``validate_all.sh`` and CI) fails the
build when they disagree.

This module only *reads* the version: it prefers the installed package
metadata (so ``pip`` installs report the real distribution version) and falls
back to files on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def _from_metadata(distribution: str) -> Optional[str]:
    try:
        from importlib.metadata import version

        return version(distribution)
    except Exception:  # noqa: BLE001 - metadata is optional at runtime
        return None


def _from_version_file() -> Optional[str]:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "VERSION"
        if candidate.is_file():
            try:
                value = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            return value or None
    return None


def resolve(distribution: str, fallback: str) -> str:
    """Repository ``VERSION`` first, installed metadata second.

    During development the editable install metadata goes stale until the next
    ``pip install -e``; the checked-in VERSION file is always current. In an
    installed wheel the file is absent and distribution metadata wins.
    """
    return _from_version_file() or _from_metadata(distribution) or fallback
