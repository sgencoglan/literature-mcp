#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fulltext PDF'lerini sonraki iş akışına taşır ve DOI adına göre yeniden adlandırır.

İş akışı 3'te ``03_kaynak_kesfi/fulltext/`` altına indirilen açık erişimli
PDF'ler, iş akışı 4 (``04_taslak/fulltext/``) veya iş akışı 5
(``05_analiz/fulltext/``) için gereklidir. Bu betik:

* kaynak klasördeki her PDF'i hedef klasöre **kopyalar** (varsayılan) veya
  ``--move`` ile taşır,
* dosyayı DOI tabanlı ada çevirir (``10.4073csr.2011.4.pdf``); DOI'yi önce
  dosya adından, sonra PDF'in ilk iki sayfasından, sonra kaynak listesindeki
  başlık eşleşmesinden bulur,
* hiçbir dosyayı silmez; hedefte aynı DOI varsa atlar,
* ``--dry-run`` ile yalnızca planı gösterir.

Kullanım:
    python3 scripts/promote_fulltext.py <proje-kökü> --to 4
    python3 scripts/promote_fulltext.py <proje-kökü> --to 4 --move
    python3 scripts/promote_fulltext.py <proje-kökü> --to 4 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from project_layout import WORKFLOW_DIRECTORIES as WORKFLOWS
except ImportError:
    from scripts.project_layout import WORKFLOW_DIRECTORIES as WORKFLOWS
PDF_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
DOI_FILENAME_RE = re.compile(r"^(10\.\d{4,9})(.+)$")
DOI_IN_NAME_RE = re.compile(r"(10\.\d{4,9})(.+)$")


def doi_filename(doi: str) -> str:
    """DOI'yi dosya adına çevir; özel karakterleri at (indiriciyle aynı kural)."""
    text = unicodedata.normalize("NFKD", str(doi or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9.\-]+", "", text).strip(".-")
    return (text or "doi-yok")[:150]


def _normalize_tokens(value: str) -> set[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return {
        token
        for token in re.split(r"[^a-z0-9]+", text)
        if len(token) > 3
    }


def _pdf_probe_text(path: Path) -> str:
    try:
        import pymupdf
    except ImportError:
        return ""
    try:
        with pymupdf.open(str(path)) as document:
            chunks = []
            for page_index in range(min(2, document.page_count)):
                try:
                    chunks.append(document.load_page(page_index).get_text("text") or "")
                except Exception:  # noqa: BLE001
                    continue
            return re.sub(r"\s+", " ", "\n".join(chunks))
    except Exception:  # noqa: BLE001
        return ""


def _doi_from_text(text: str) -> str:
    match = PDF_DOI_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}\"'").lower()


def _dois_from_filename(name: str) -> List[str]:
    """Dosya adından DOI adayları üret (özel karakterler atılmış olabilir).

    DOI dosya adının başında olmak zorunda değildir; ``Yilmaz_2024_10.1000_xyz.123.pdf``
    gibi kullanıcı adlandırmaları da çözülür.
    """
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    match = DOI_IN_NAME_RE.search(stem)
    if not match:
        return []
    prefix, tail = match.group(1), match.group(2)
    run = prefix.split(".", 1)[1]
    candidates: List[str] = []
    # 10.1007s12310-018-09303-z  -> 10.1007/s12310-018-09303-z
    for length in range(4, min(9, len(run) + 1)):
        registry = run[:length]
        rest = (run[length:] + tail).strip(" ._-")
        if not rest:
            continue
        candidates.append(f"10.{registry}/{rest}".lower())
    return candidates


def _title_match_score(filename: str, title: str) -> float:
    name_tokens = _normalize_tokens(filename)
    title_tokens = _normalize_tokens(title)
    if not name_tokens or not title_tokens:
        return 0.0
    return len(name_tokens & title_tokens) / len(name_tokens)


def load_candidates(project_root: Path) -> List[Dict[str, Any]]:
    """Akış 3'teki fulltext listelerinden DOI + başlık eşlemesi topla."""
    merged: Dict[str, Dict[str, Any]] = {}
    for path in sorted((project_root / WORKFLOWS["3"]).glob("*fulltext_listesi*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("candidates") or []:
            if not isinstance(item, dict):
                continue
            doi = str(item.get("doi") or "").strip().lower()
            if not doi:
                continue
            entry = merged.setdefault(doi, {"doi": doi, "titles": []})
            title = str(item.get("title") or "").strip()
            if title and title not in entry["titles"]:
                entry["titles"].append(title)
    return list(merged.values())


def resolve_doi(
    path: Path,
    candidates: List[Dict[str, Any]],
    probe_text: str,
) -> Tuple[str, str]:
    """(doi, kaynak) döndürür. Kaynak: filename | pdf | title | ''."""
    from_name = _dois_from_filename(path.name)
    if from_name:
        return from_name[0], "filename"

    from_pdf = _doi_from_text(probe_text)
    if from_pdf:
        return from_pdf, "pdf"

    best_doi, best_score = "", 0.0
    for entry in candidates:
        for title in entry["titles"]:
            score = _title_match_score(path.name, title)
            if score > best_score:
                best_doi, best_score = entry["doi"], score
    if best_score >= 0.5:
        return best_doi, "title"
    return "", ""


def _pdf_files(directory: Path) -> List[Path]:
    """Klasördeki PDF'ler; uzantı büyük/küçük harfe duyarsız (.PDF dahil)."""
    if not directory.is_dir():
        return []
    return sorted(
        (path for path in directory.iterdir()
         if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: path.name.lower(),
    )


def promote(
    project_root: Path,
    target_workflow: str,
    sources: List[Path],
    *,
    move: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    target_dir = project_root / WORKFLOWS[target_workflow] / "fulltext"
    candidates = load_candidates(project_root)
    existing: Dict[str, str] = {}
    if target_dir.is_dir():
        for pdf in _pdf_files(target_dir):
            stem = pdf.stem.lower()
            existing[stem] = pdf.name

    report: Dict[str, Any] = {
        "target_directory": str(target_dir),
        "moved": 0,
        "copied": 0,
        "already_present": 0,
        "renamed_only": 0,
        "unresolved": [],
        "items": [],
    }

    seen_names: set[str] = set()
    for source_dir in sources:
        if not source_dir.is_dir():
            continue
        for pdf in _pdf_files(source_dir):
            probe_text = ""
            doi, how = resolve_doi(pdf, candidates, probe_text)
            if not doi:
                probe_text = _pdf_probe_text(pdf)
                doi, how = resolve_doi(pdf, candidates, probe_text)

            if not doi:
                report["unresolved"].append(pdf.name)
                report["items"].append(
                    {"source": str(pdf), "doi": None, "status": "unresolved"}
                )
                continue

            stem = doi_filename(doi)
            destination = target_dir / f"{stem}.pdf"
            if destination.name in existing.values() or stem in existing:
                report["already_present"] += 1
                report["items"].append(
                    {
                        "source": str(pdf),
                        "doi": doi,
                        "status": "already_present",
                        "destination": destination.name,
                    }
                )
                # Kaynak zaten hedefteyse ve adı farklıysa yalnızca raporla.
                continue

            if stem in seen_names:
                continue
            seen_names.add(stem)

            if dry_run:
                report["items"].append(
                    {
                        "source": str(pdf),
                        "doi": doi,
                        "status": "planned",
                        "destination": destination.name,
                        "resolved_by": how,
                    }
                )
                continue

            target_dir.mkdir(parents=True, exist_ok=True)
            if move:
                shutil.move(str(pdf), str(destination))
                report["moved"] += 1
            else:
                shutil.copy2(str(pdf), str(destination))
                report["copied"] += 1
            report["items"].append(
                {
                    "source": str(pdf),
                    "doi": doi,
                    "status": "moved" if move else "copied",
                    "destination": destination.name,
                    "resolved_by": how,
                }
            )

    # Kaynak klasörde ve hedef klasörde DOI adlı olmayan dosyaları yerinde
    # yeniden adlandır (kullanıcının kendi indirdiği dosyalar hedefte olabilir).
    for source_dir in [*sources, target_dir]:
        if not source_dir.is_dir():
            continue
        for pdf in _pdf_files(source_dir):
            if DOI_FILENAME_RE.match(pdf.stem):
                continue
            probe_text = _pdf_probe_text(pdf)
            doi, how = resolve_doi(pdf, candidates, probe_text)
            if not doi:
                continue
            destination = source_dir / f"{doi_filename(doi)}.pdf"
            if destination.exists():
                continue
            if dry_run:
                report["items"].append(
                    {
                        "source": str(pdf),
                        "doi": doi,
                        "status": "rename_planned",
                        "destination": destination.name,
                        "resolved_by": how,
                    }
                )
                continue
            pdf.rename(destination)
            report["renamed_only"] += 1
            report["items"].append(
                {
                    "source": str(pdf),
                    "doi": doi,
                    "status": "renamed",
                    "destination": destination.name,
                    "resolved_by": how,
                }
            )

    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="PDF'leri sonraki iş akışına taşı ve DOI adına göre yeniden adlandır."
    )
    parser.add_argument("project_root", type=Path, help="Proje kök klasörü")
    parser.add_argument(
        "--to",
        dest="target",
        choices=["4", "5"],
        default="4",
        help="Hedef iş akışı: 4 (04_taslak) veya 5 (05_analiz).",
    )
    parser.add_argument(
        "--from-workflow",
        action="append",
        choices=sorted(WORKFLOWS),
        help="Kaynak iş akışı; birden çok kez verilebilir (varsayılan: 3).",
    )
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        help="Ek kaynak klasör (ör. kullanıcının indirdiği PDF'ler).",
    )
    parser.add_argument("--move", action="store_true", help="Kopyalamak yerine taşı.")
    parser.add_argument("--dry-run", action="store_true", help="Yalnızca planı göster.")
    parser.add_argument(
        "--report",
        type=Path,
        help="JSON rapor yolu (varsayılan: hedef klasörün üstünde).",
    )
    parser.add_argument(
        "--no-timestamp",
        dest="timestamp",
        action="store_false",
        help="Rapor adına zaman soneki ekleme.",
    )
    args = parser.parse_args(argv)

    from output_naming import add_timestamp, timestamp_suffix

    project_root = args.project_root.expanduser().resolve()
    if not project_root.is_dir():
        print(f"Hata: proje kökü bulunamadı: {project_root}", file=sys.stderr)
        return 2

    source_workflows = args.from_workflow or ["3"]
    sources: List[Path] = []
    for workflow in source_workflows:
        if workflow == args.target:
            continue
        sources.append(project_root / WORKFLOWS[workflow] / "fulltext")
    for extra in args.source or []:
        sources.append(extra.expanduser().resolve())

    if not any(path.is_dir() for path in sources):
        print("Uyarı: kaynak fulltext klasörü bulunamadı.", file=sys.stderr)

    report = promote(
        project_root,
        args.target,
        sources,
        move=args.move,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        report_path = args.report or (
            project_root / WORKFLOWS[args.target] / "fulltext_aktarim.json"
        )
        if args.timestamp:
            report_path = add_timestamp(
                report_path,
                moment=None,
                enabled=True,
            ) if not report_path.stem.endswith(timestamp_suffix()) else report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report["generated_at"] = timestamp_suffix()
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report["report_path"] = str(report_path)

    print(f"Hedef: {report['target_directory']}")
    print(
        f"Kopyalanan: {report['copied']} | Taşınan: {report['moved']} | "
        f"Zaten var: {report['already_present']} | Yerinde yeniden adlandırılan: "
        f"{report['renamed_only']} | Çözülemeyen: {len(report['unresolved'])}"
    )
    for item in report["items"]:
        if item.get("status") in {"copied", "moved", "renamed", "planned", "rename_planned"}:
            print(f"  {item['status']:14} -> {item.get('destination')}")
    if report["unresolved"]:
        print("Çözülemeyen dosyalar (DOI bulunamadı):")
        for name in report["unresolved"]:
            print(f"  - {name}")
    if report.get("report_path"):
        print(f"Rapor: {report['report_path']}")
    if args.dry_run:
        print("(dry-run: hiçbir dosya değiştirilmedi)")
    else:
        print("Not: hiçbir dosya silinmedi.")
    return 0 if not report["unresolved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
