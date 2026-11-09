"""Kanonik proje klasör düzeni (scripts tarafı).

``packages/sciencedirect-meta/src/sciencedirect_meta/layout.py`` ile aynı
değerleri taşır; ``scripts/tests/test_scripts.py`` üç kopyanın uyumunu denetler.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

WORKFLOW_DIRECTORIES: Dict[str, str] = {
    "1": "01_konu_belirleme",
    "2": "02_yazim_plani",
    "3": "03_kaynak_kesfi",
    "4": "04_taslak",
    "5": "05_analiz",
}

WORKFLOW_LABELS: Dict[str, str] = {
    "1": "Konu belirleme",
    "2": "Yazım planı",
    "3": "Plana göre kaynak keşfi ve fulltext seçimi",
    "4": "Taslak yazma",
    "5": "Taslak analizi",
}

FULLTEXT_SUBDIR = "fulltext"
INTERNAL_DIRECTORY = ".literature-mcp"

GENRES: Dict[str, str] = {
    "kitap_bolumu": "Kitap bölümü",
    "uygulama_rehberi": "Uygulama rehberi",
    "derleme_makale": "Derleme makalesi",
    "ampirik_makale": "Ampirik makale",
}


def workflow_dir(root: Path, workflow: str) -> Path:
    key = str(workflow).strip()
    if key not in WORKFLOW_DIRECTORIES:
        raise ValueError(
            f"Geçersiz akış: {workflow!r}. Seçenekler: {sorted(WORKFLOW_DIRECTORIES)}"
        )
    return Path(root) / WORKFLOW_DIRECTORIES[key]


def fulltext_dir(root: Path, workflow: str) -> Path:
    return workflow_dir(root, workflow) / FULLTEXT_SUBDIR


def detect_workflow(path: Path) -> str:
    """Bir yolun hangi akış klasöründe olduğunu bul; bulunamazsa '1'."""
    parts = Path(path).resolve().parts
    for key, name in WORKFLOW_DIRECTORIES.items():
        if name in parts:
            return key
    return "1"
