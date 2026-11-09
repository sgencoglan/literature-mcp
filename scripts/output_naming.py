#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ortak çıktı adlandırma yardımcıları.

Üretilen raporların üzerine yazılmasını önlemek için dosya adına
``_YYYYMMDD-HHMMSS`` biçiminde bir zaman damgası ekler. Aynı saniye içinde
ikinci bir çıktı üretilirse ``-01``, ``-02`` ... soneki kullanılır.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
TIMESTAMP_RE = re.compile(r"_\d{8}-\d{6}(?:-\d{2})?$")


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
