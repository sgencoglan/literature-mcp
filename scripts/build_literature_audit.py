#!/usr/bin/env python3
"""Kavram çerçevesi ve kaynak havuzundan eksik kaynak denetimi üret."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from literature_audit import build_audit, records_from, render_audit
    from output_naming import add_timestamp, write_versioned_pair
except ImportError:
    from scripts.literature_audit import build_audit, records_from, render_audit
    from scripts.output_naming import add_timestamp, write_versioned_pair


def parse_ris(text: str) -> list[dict[str, Any]]:
    """RIS kayıtlarını oku. Etiketlerin devam satırlarını ve BOM'u destekler."""
    records = []
    current: dict[str, list[str]] = {}
    last_tag = None

    def finish() -> None:
        if not current:
            return

        def first(*tags: str) -> str:
            return next((current[t][0] for t in tags if current.get(t)), "")

        year = re.search(r"\b\d{4}\b", first("PY", "Y1", "DA"))
        records.append(
            {
                "title": first("TI", "T1", "CT"),
                "doi": first("DO"),
                "abstract": "\n".join(current.get("AB", []) or current.get("N2", [])),
                "year": year.group() if year else None,
                "publication_type": first("TY"),
            }
        )

    for line in text.lstrip("\ufeff").splitlines():
        match = re.match(r"^([A-Z0-9]{2})\s{2}-\s?(.*)$", line)
        if match:
            tag, value = match.groups()
            if tag == "TY" and current:
                finish()
                current = {}
            if tag == "ER":
                finish()
                current = {}
                last_tag = None
            else:
                current.setdefault(tag, []).append(value.strip())
                last_tag = tag
        elif line.strip() and last_tag:
            current[last_tag][-1] += " " + line.strip()
    finish()
    if not records:
        raise ValueError("RIS dosyasında kayıt bulunamadı.")
    return records


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".ris":
        return parse_ris(path.read_text(encoding="utf-8-sig"))
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows or not any(k in rows[0] for k in ("doi", "pmid", "title")):
            raise ValueError("CSV başlıkları title/doi/pmid alanlarından en az birini içermeli.")
        return rows
    return records_from(json.loads(path.read_text(encoding="utf-8-sig")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--framework", type=Path, required=True, help="Kavram haritası JSON'u veya framework bloğu"
    )
    parser.add_argument(
        "--baseline", type=Path, required=True, help="Başlangıç havuzu: JSON / CSV / RIS"
    )
    parser.add_argument(
        "--additional",
        type=Path,
        action="append",
        default=[],
        help="Ek sonuçlar; birden çok dosya verilebilir",
    )
    parser.add_argument(
        "--known-items", type=Path, help="Bilinen önemli yayınlar: JSON / CSV / RIS"
    )
    parser.add_argument(
        "--search-log", type=Path, help="source/query/status/searched_at içeren JSON listesi"
    )
    parser.add_argument("--domain", choices=["medical", "psychology", "education"])
    parser.add_argument("--purpose", choices=["overview", "intervention"], default="overview")
    parser.add_argument("-o", "--output-dir", type=Path)
    parser.add_argument("--check", action="store_true", help="Yalnızca denetle ve özet yaz")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.framework.read_text(encoding="utf-8-sig"))
        framework = data.get("framework", data)
        if not isinstance(framework, dict) or framework.get("schema") != "concept-framework/1":
            raise ValueError("Geçerli concept-framework/1 girdisi gerekli.")
        additional = [r for p in args.additional for r in load_records(p)]
        searches = (
            json.loads(args.search_log.read_text(encoding="utf-8-sig")) if args.search_log else []
        )
        if not isinstance(searches, list) or any(not isinstance(s, dict) for s in searches):
            raise ValueError("Arama günlüğü JSON nesnelerinden oluşan liste olmalı.")
        report = build_audit(
            load_records(args.baseline),
            additional,
            load_records(args.known_items) if args.known_items else [],
            framework,
            searches,
            args.domain or data.get("domain") or "psychology",
            args.purpose,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Dosya içeriğini veya hassas kayıt değerlerini hata çıktısına kopyalama.
        print(
            f"Denetim girdisi okunamadı ({type(exc).__name__}). Dosya biçimini ve gerekli alanları kontrol edin.",
            file=sys.stderr,
        )
        return 2
    if args.check:
        print(json.dumps(report["summary"], ensure_ascii=False))
        return 0
    directory = args.output_dir or args.baseline.parent
    target = add_timestamp(directory / "02_kaynak_kapsam_denetimi.json")
    page = (
        '<!doctype html><html lang="tr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Kaynak kapsam denetimi</title><style>"
        "body{font:16px/1.5 system-ui;max-width:1200px;margin:2rem auto;padding:1rem}"
        "table{border-collapse:collapse;width:100%;font-size:.85rem}td,th{border:1px solid #ddd;padding:.5rem;text-align:left;overflow-wrap:anywhere}"
        "@media print{body{margin:0}tr{break-inside:avoid}}"
        "</style></head><body>" + render_audit(report) + "</body></html>"
    )
    result = write_versioned_pair(
        target, {".json": json.dumps(report, ensure_ascii=False, indent=2) + "\n", ".html": page}
    )
    print(f"Yazıldı: {result['path']}")
    print(f"Yazıldı: {result['path'].with_suffix('.html')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
