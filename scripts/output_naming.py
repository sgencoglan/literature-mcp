#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ortak çıktı adlandırma yardımcıları.

Üretilen raporların üzerine yazılmasını önlemek için dosya adına
``_YYYYMMDD-HHMMSS`` biçiminde bir zaman damgası ekler. Aynı saniye içinde
ikinci bir çıktı üretilirse ``-01``, ``-02`` ... soneki kullanılır.

``write_versioned`` tekrar çalıştırmaları disipline eder: içerik değişmediyse
yeni sürüm yazmaz; değiştiyse yeni sürümü yazar ve eski sürümleri ``arsiv/``
altına taşır. Böylece klasörde her zaman tek bir güncel çıktı kalır, geçmiş
kaybolmaz.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
TIMESTAMP_RE = re.compile(r"_\d{8}-\d{6}(?:-\d{2})?$")

# Üretim zamanı her koşuda değişen alanlar; içerik karşılaştırmasında yok sayılır.
VOLATILE_KEYS = {
    "generated_at",
    "timestamp",
    "created_at",
    "updated_at",
    "searched_at",
    "oa_checked_at",
    "approved_at",
}
ARCHIVE_DIRNAME = "arsiv"


def timestamp_suffix(moment: Optional[datetime] = None) -> str:
    """Return a filesystem-safe local timestamp."""
    moment = moment or datetime.now().astimezone()
    return moment.strftime(TIMESTAMP_FORMAT)


def has_timestamp(path: str | Path) -> bool:
    """Return True when the file stem already ends with a timestamp."""
    return bool(TIMESTAMP_RE.search(Path(path).stem))


def unique_path(path: str | Path) -> Path:
    """Return ``path`` or a ``-01``/``-02`` variant that does not exist."""
    path = Path(path)
    if not path.exists():
        return path
    for index in range(1, 100):
        candidate = path.with_name(f"{path.stem}-{index:02d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Boş bir çıktı adı bulunamadı: {path}")


def add_timestamp(
    path: str | Path,
    moment: Optional[datetime] = None,
    enabled: bool = True,
) -> Path:
    """Append a timestamp to ``path`` unless it already has one."""
    path = Path(path)
    if not enabled or has_timestamp(path):
        return path
    candidate = path.with_name(f"{path.stem}_{timestamp_suffix(moment)}{path.suffix}")
    return unique_path(candidate)


def add_timestamp_argument(
    parser: argparse.ArgumentParser,
    default: bool = True,
) -> None:
    """Add ``--timestamp/--no-timestamp`` to a parser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--timestamp",
        dest="timestamp",
        action="store_true",
        default=default,
        help="Çıktı adına tarih-saat ekle (varsayılan: açık).",
    )
    group.add_argument(
        "--no-timestamp",
        dest="timestamp",
        action="store_false",
        help="Sabit dosya adı kullan; tarih-saat ekleme.",
    )


def _strip_volatile(value: Any) -> Any:
    """Recursively drop keys that change on every run."""
    if isinstance(value, dict):
        return {
            key: _strip_volatile(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def canonical_text(text: str, suffix: str) -> str:
    """Return a stable representation for change detection.

    JSON files are re-serialised without volatile timestamp fields so that
    re-running an unchanged pipeline does not look like a content change.
    Other formats are compared verbatim.
    """
    if suffix.lower() != ".json":
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(
        _strip_volatile(data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def versions_of(path: str | Path) -> List[Path]:
    """List all timestamped (and base-name) versions of one output path."""
    path = Path(path)
    if not path.parent.exists():
        return []
    found = [
        candidate
        for candidate in path.parent.glob(f"{path.stem}*{path.suffix}")
        if candidate.is_file()
        and (candidate.stem == path.stem or TIMESTAMP_RE.search(candidate.stem))
    ]
    return sorted(found, key=lambda item: item.stat().st_mtime)


def _archive_target(path: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    candidate = archive_dir / path.name
    if not candidate.exists():
        return candidate
    for index in range(1, 100):
        variant = archive_dir / f"{path.stem}-{index:02d}{path.suffix}"
        if not variant.exists():
            return variant
    raise FileExistsError(f"Arşivde boş ad bulunamadı: {path.name}")


def archive_older_versions(
    base: str | Path,
    keep: str | Path,
    archive_dir: Optional[str | Path] = None,
) -> List[Path]:
    """Move every version of ``base`` except ``keep`` into the archive folder."""
    base = Path(base)
    keep = Path(keep)
    target_dir = Path(archive_dir) if archive_dir else base.parent / ARCHIVE_DIRNAME
    moved: List[Path] = []
    for version in versions_of(base):
        if version == keep or not version.exists():
            continue
        destination = _archive_target(version, target_dir)
        shutil.move(str(version), str(destination))
        moved.append(destination)
    return moved


def write_versioned(
    base: str | Path,
    text: str,
    *,
    enabled: bool = True,
    force: bool = False,
    archive_old: bool = True,
    archive_dir: Optional[str | Path] = None,
    moment: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Write a generated output without piling up duplicate versions.

    - Same content as the newest existing version: nothing is written.
    - Changed content: a new timestamped version is written; older versions are
      moved to ``arsiv/`` (never deleted).
    - ``force`` rewrites even when the content matches.

    Raises ``FileExistsError`` when a fixed name (``enabled=False``) would be
    overwritten with different content without ``force``.
    """
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    existing = versions_of(base)
    latest = existing[-1] if existing else None

    if latest is not None and not force:
        try:
            previous = latest.read_text(encoding="utf-8")
        except OSError:
            previous = None
        if previous is not None and canonical_text(
            previous, base.suffix
        ) == canonical_text(text, base.suffix):
            archived = (
                archive_older_versions(base, keep=latest, archive_dir=archive_dir)
                if archive_old
                else []
            )
            return {
                "status": "unchanged",
                "path": latest,
                "archived": archived,
            }

    target = add_timestamp(base, moment=moment, enabled=enabled)
    if target.exists() and not force:
        try:
            same = canonical_text(
                target.read_text(encoding="utf-8"), base.suffix
            ) == canonical_text(text, base.suffix)
        except OSError:
            same = False
        if not same:
            raise FileExistsError(f"Çıktı zaten var: {target}")
        return {"status": "unchanged", "path": target, "archived": []}

    target.write_text(text, encoding="utf-8")
    archived = (
        archive_older_versions(base, keep=target, archive_dir=archive_dir)
        if archive_old
        else []
    )
    return {"status": "written", "path": target, "archived": archived}


def write_versioned_pair(
    base: str | Path,
    texts: Dict[str, str],
    *,
    enabled: bool = True,
    force: bool = False,
    archive_dir: Optional[str | Path] = None,
    moment: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Write a multi-file output (for example JSON + HTML) as one version.

    Change detection uses the JSON member when one is present, so a re-run that
    only refreshes ``generated_at`` does not create a new version. Older
    versions of every member are moved to ``arsiv/`` together.
    """
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    primary_suffix = ".json" if ".json" in texts else next(iter(texts))
    existing = versions_of(base)
    latest = existing[-1] if existing else None

    if latest is not None and not force:
        try:
            previous = latest.read_text(encoding="utf-8")
        except OSError:
            previous = None
        current = texts[primary_suffix]
        if previous is not None and canonical_text(
            previous, primary_suffix
        ) == canonical_text(current, primary_suffix):
            archived: List[Path] = []
            for suffix in texts:
                archived.extend(
                    archive_older_versions(
                        base.with_suffix(suffix),
                        keep=latest.with_suffix(suffix),
                        archive_dir=Path(archive_dir) if archive_dir else base.parent / ARCHIVE_DIRNAME,
                    )
                )
            return {"status": "unchanged", "path": latest, "archived": archived}

    target = add_timestamp(base, moment=moment, enabled=enabled)
    if target.exists() and not force:
        try:
            same = canonical_text(
                target.read_text(encoding="utf-8"), primary_suffix
            ) == canonical_text(texts[primary_suffix], primary_suffix)
        except OSError:
            same = False
        if not same:
            raise FileExistsError(f"Çıktı zaten var: {target}")
        return {"status": "unchanged", "path": target, "archived": []}

    for suffix, text in texts.items():
        target.with_suffix(suffix).write_text(text, encoding="utf-8")

    archived: List[Path] = []
    for suffix in texts:
        archived.extend(
            archive_older_versions(
                base.with_suffix(suffix),
                keep=target.with_suffix(suffix),
                archive_dir=Path(archive_dir) if archive_dir else base.parent / ARCHIVE_DIRNAME,
            )
        )
    return {"status": "written", "path": target, "archived": archived}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bir dosya adına tarih-saat soneki ekler."
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--no-timestamp", dest="timestamp", action="store_false")
    args = parser.parse_args(argv)
    print(add_timestamp(args.path, enabled=args.timestamp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
