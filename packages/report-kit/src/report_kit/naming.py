"""Timestamped output paths for the chapter report."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
TIMESTAMP_RE = re.compile(r"_\d{8}-\d{6}(?:-\d{2})?$")


def timestamp_suffix(moment: Optional[datetime] = None) -> str:
    moment = moment or datetime.now().astimezone()
    return moment.strftime(TIMESTAMP_FORMAT)


def has_timestamp(path: str | Path) -> bool:
    return bool(TIMESTAMP_RE.search(Path(path).stem))


def unique_path(path: str | Path) -> Path:
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
    path = Path(path)
    if not enabled or has_timestamp(path):
        return path
    candidate = path.with_name(f"{path.stem}_{timestamp_suffix(moment)}{path.suffix}")
    return unique_path(candidate)
