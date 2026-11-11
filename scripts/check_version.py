#!/usr/bin/env python3
"""Fail when the version is not identical everywhere it is written.

Five files carry the version: ``VERSION``, the two ``pyproject.toml`` files,
the two ``__version__`` attributes, plus the README/AGENTS banner. A release is
exactly when one of them gets forgotten, so this check runs in
``validate_all.sh`` and CI.

Kullanım:
    python3 scripts/check_version.py
    python3 scripts/check_version.py --set 2.9.0   # write the new version
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PYPROJECTS = [
    ROOT / "packages/sciencedirect-meta/pyproject.toml",
    ROOT / "packages/report-kit/pyproject.toml",
]
BANNERS = [ROOT / "README.md", ROOT / "AGENTS.md"]
_PYPROJECT_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
_BANNER_VERSION = re.compile(r"(?:Sürüm:\**|Depo sürümü)\s*v?(\d+\.\d+\.\d+)")


def read_version() -> str:
    value = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise SystemExit(f"VERSION geçersiz: {value!r} (beklenen X.Y.Z)")
    return value


def collect() -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = [("VERSION", read_version())]
    for path in PYPROJECTS:
        match = _PYPROJECT_VERSION.search(path.read_text(encoding="utf-8"))
        found.append((str(path.relative_to(ROOT)), match.group(1) if match else None))
    for path in BANNERS:
        text = path.read_text(encoding="utf-8")
        match = _BANNER_VERSION.search(text)
        found.append((str(path.relative_to(ROOT)), match.group(1) if match else None))
    return found


def check() -> int:
    expected = read_version()
    problems = 0
    for name, value in collect():
        if value is None:
            print(f"HATA: {name} içinde sürüm bulunamadı", file=sys.stderr)
            problems += 1
        elif value != expected:
            print(f"HATA: {name} = {value}, VERSION = {expected}", file=sys.stderr)
            problems += 1
    if problems:
        print(
            "Sürümler uyuşmuyor. `python3 scripts/check_version.py --set X.Y.Z` "
            "ile hepsini birlikte güncelleyin.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: tüm sürüm alanları {expected}")
    return 0


def set_version(new_version: str) -> int:
    if not re.fullmatch(r"\d+\.\d+\.\d+", new_version):
        print("Sürüm X.Y.Z biçiminde olmalı", file=sys.stderr)
        return 2
    (ROOT / "VERSION").write_text(new_version + "\n", encoding="utf-8")
    for path in PYPROJECTS:
        text = path.read_text(encoding="utf-8")
        text = _PYPROJECT_VERSION.sub(f'version = "{new_version}"', text, count=1)
        path.write_text(text, encoding="utf-8")
    for path in BANNERS:
        text = path.read_text(encoding="utf-8")
        def _replace(match: re.Match[str]) -> str:
            prefix = match.group(0)[: match.start(1) - match.start(0)]
            return f"{prefix}{new_version}"

        text = _BANNER_VERSION.sub(_replace, text, count=1)
        path.write_text(text, encoding="utf-8")
    print(f"Güncellendi: {new_version}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="new_version", help="Sürümü tüm dosyalarda güncelle")
    args = parser.parse_args()
    if args.new_version:
        return set_version(args.new_version)
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
