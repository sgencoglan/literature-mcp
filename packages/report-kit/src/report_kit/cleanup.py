"""Manifest-based cleanup for generated report artifacts.

Only files explicitly recorded in a report manifest can be deleted. The
manifest lives beside the generated report, and every path must resolve inside
that directory. PDFs, indexes, registries and unrelated files are never
touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MANIFEST_SCHEMA = 1


class CleanupError(RuntimeError):
    pass


@dataclass
class CleanupEntry:
    path: Path
    kind: str
    sha256: str | None
    size: int | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_to_root(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root.resolve()))
    except ValueError as exc:
        raise CleanupError(f"Dosya manifest klasörünün dışında: {path}") from exc


def write_manifest(
    manifest_path: str | Path,
    project: str,
    files: Iterable[tuple[str | Path, str]],
) -> Path:
    """Write a manifest for generated files.

    ``files`` is an iterable of ``(path, kind)`` pairs. ``kind`` is one of
    ``html``, ``intermediate`` or ``manifest``-like auxiliary values. Paths are
    stored relative to the manifest directory.
    """
    manifest = Path(manifest_path)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    root = manifest.parent
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path, kind in files:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise CleanupError(f"Manifeste eklenecek dosya yok: {path}")
        if not path.is_file():
            raise CleanupError(f"Manifeste yalnızca dosya eklenebilir: {path}")
        relative = _relative_to_root(path, root)
        if relative in seen:
            continue
        seen.add(relative)
        entries.append(
            {
                "path": relative,
                "kind": kind,
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    payload = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": project,
        "files": entries,
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.is_file():
        raise CleanupError(f"Manifest bulunamadı: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CleanupError(f"Manifest geçersiz JSON: {path}: {exc}") from exc
    if data.get("schema") != MANIFEST_SCHEMA:
        raise CleanupError(f"Desteklenmeyen manifest şeması: {data.get('schema')!r}")
    if not isinstance(data.get("files"), list):
        raise CleanupError("Manifestte 'files' dizisi yok")
    return data


def _entry_from_dict(raw: Any, root: Path) -> CleanupEntry:
    if not isinstance(raw, dict):
        raise CleanupError("Manifest dosya kaydı nesne değil")
    relative = str(raw.get("path") or "").strip()
    if not relative:
        raise CleanupError("Manifest dosya kaydında 'path' boş")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise CleanupError(f"Manifestte mutlak yol yasak: {relative}")
    if ".." in candidate.parts:
        raise CleanupError(f"Manifestte '..' yasak: {relative}")
    target = (root / candidate).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise CleanupError(f"Manifest yolu klasör dışına çıkıyor: {relative}") from exc
    return CleanupEntry(
        path=target,
        kind=str(raw.get("kind") or "intermediate"),
        sha256=raw.get("sha256"),
        size=raw.get("bytes"),
    )


def cleanup_manifest(
    manifest_path: str | Path,
    scope: str = "intermediate",
    *,
    dry_run: bool = False,
    yes: bool = False,
    force: bool = False,
    delete_manifest: bool = False,
) -> list[Path]:
    """Delete generated files listed in a manifest.

    ``scope='intermediate'`` keeps HTML and Markdown deliverables; ``scope='all'``
    also removes them. The manifest itself is kept by default.
    """
    if scope not in {"intermediate", "all"}:
        raise CleanupError("scope 'intermediate' veya 'all' olmalı")
    manifest = Path(manifest_path).resolve()
    root = manifest.parent
    data = load_manifest(manifest)
    entries = [_entry_from_dict(raw, root) for raw in data["files"]]

    selected: list[tuple[CleanupEntry, str]] = []
    for entry in entries:
        if entry.path == manifest:
            continue
        if entry.kind == "manifest":
            continue
        if scope == "intermediate" and entry.kind in {"html", "markdown"}:
            continue
        if not entry.path.exists():
            print(f"UYARI: manifestteki dosya zaten yok, atlandı: {entry.path}")
            continue
        if not entry.path.is_file():
            raise CleanupError(f"Manifest kaydı dosya değil: {entry.path}")
        if entry.sha256 and not force:
            actual = _sha256(entry.path)
            if actual != entry.sha256:
                raise CleanupError(
                    f"Dosya manifestten sonra değişmiş: {entry.path} "
                    "(yine de silmek için --force kullanın)"
                )
        selected.append(
            (
                entry,
                "HTML" if entry.kind == "html" else "Markdown" if entry.kind == "markdown" else "ara dosya",
            )
        )

    if not selected:
        print("Silinecek dosya yok.")
        return []

    print("Silinecek dosyalar:")
    for entry, kind in selected:
        print(f"  - [{kind}] {entry.path}")
    if delete_manifest and scope == "all":
        print(f"  - [manifest] {manifest}")

    if dry_run:
        print("Dry-run: hiçbir dosya silinmedi.")
        return []

    if not yes:
        if not sys.stdin.isatty():
            print("Onay için terminal yok; hiçbir dosya silinmedi. --yes kullanın.")
            return []
        answer = input("Devam etmek için 'y' yazın: ").strip().lower()
        if answer not in {"y", "yes", "e", "evet"}:
            print("İptal edildi; hiçbir dosya silinmedi.")
            return []

    deleted: list[Path] = []
    for entry, _kind in selected:
        entry.path.unlink()
        deleted.append(entry.path)
    if delete_manifest and scope == "all" and manifest.exists():
        manifest.unlink()
        deleted.append(manifest)
    print(f"{len(deleted)} dosya silindi.")
    return deleted
