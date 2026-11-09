"""Kanonik proje klasör düzeni — beş iş akışı.

Tek doğruluk kaynağı. ``scripts/project_layout.py`` ve
``packages/paperqa-local/paperqa_mcp.py`` aynı değerleri taşır; bir test üçünün
uyumunu denetler.

Klasörler:

1. ``01_konu_belirleme``   — konu, başlık, tür, kapsam, (opsiyonel) yöntem
2. ``02_yazim_plani``      — iskelet: alt başlıklar + kanıt ihtiyacı
3. ``03_kaynak_kesfi``     — plana göre arama, atama matrisi, PDF indirme
4. ``04_taslak``           — sayfa doğrulamalı taslak metin
5. ``05_analiz``           — iddia–kanıt + plan uyumu denetimi

Kural: her akış klasörü kendi çıktısını doğrudan içinde tutar; yalnızca PDF'ler
``fulltext/`` alt klasöründedir. Önceki sürümdeki ``taslak/`` alt klasörü
kaldırıldı.
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

# Ürün türleri. Varsayılan YOKTUR; akış 1'de kullanıcıya sorulur.
GENRES: Dict[str, str] = {
    "kitap_bolumu": "Kitap bölümü",
    "uygulama_rehberi": "Uygulama rehberi",
    "derleme_makale": "Derleme makalesi",
    "ampirik_makale": "Ampirik makale",
}

GENRE_REQUIRED_FIELDS = (
    "Tür seçilmeden akış 2 başlamaz; iskeletin yapısı türe bağlıdır."
)

ALL_DIRECTORY_NAMES = set(WORKFLOW_DIRECTORIES.values()) | {
    INTERNAL_DIRECTORY,
}


def workflow_dir(root: Path, workflow: str) -> Path:
    """Bir akışın kök klasörü."""
    key = str(workflow).strip()
    if key not in WORKFLOW_DIRECTORIES:
        raise ValueError(
            f"Geçersiz akış: {workflow!r}. Seçenekler: {sorted(WORKFLOW_DIRECTORIES)}"
        )
    return Path(root) / WORKFLOW_DIRECTORIES[key]


def fulltext_dir(root: Path, workflow: str) -> Path:
    """Bir akışın PDF klasörü."""
    return workflow_dir(root, workflow) / FULLTEXT_SUBDIR


def all_paths(root: Path) -> Dict[str, Path]:
    """Tüm akış ve iç klasörlerin yolları."""
    root = Path(root)
    paths: Dict[str, Path] = {}
    for key, name in WORKFLOW_DIRECTORIES.items():
        paths[f"w{key}"] = root / name
    for key, name in WORKFLOW_DIRECTORIES.items():
        paths[f"w{key}_fulltext"] = root / name / FULLTEXT_SUBDIR
    paths["internal"] = root / INTERNAL_DIRECTORY
    paths["indexes"] = root / INTERNAL_DIRECTORY / "indexes"
    paths["manifests"] = root / INTERNAL_DIRECTORY / "projects"
    return paths


def detect_workflow(path: Path) -> str:
    """Bir yolun hangi akış klasöründe olduğunu bul; bulunamazsa '1'."""
    parts = Path(path).resolve().parts
    for key, name in WORKFLOW_DIRECTORIES.items():
        if name in parts:
            return key
    return "1"
