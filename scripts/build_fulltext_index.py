#!/usr/bin/env python3
"""Build a landing page for one or more workflow-1 source lists."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def discover(directory: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for html_path in sorted(directory.glob("*_fulltext_listesi.html")):
        json_path = html_path.with_suffix(".json")
        if not json_path.is_file():
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        candidates = data.get("candidates")
        if not isinstance(candidates, list):
            candidates = []
        open_access = sum(
            1 for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("open_access") is True
        )
        reports.append({
            "html": html_path.name,
            "json": json_path.name,
            "title": data.get("title") or html_path.stem,
            "project": data.get("project") or "",
            "count": len(candidates),
            "open_access": open_access,
        })
    return reports


def render(reports: list[dict[str, Any]], directory_name: str) -> str:
    if reports:
        cards = "".join(
            "<li class='card'><h2>" + esc(report["title"]) + "</h2>"
            + ("<p class='muted'>" + esc(report["project"]) + "</p>" if report["project"] else "")
            + f"<p>{report['count']} aday kaynak · {report['open_access']} açık erişim</p>"
            + "<p><a class='button' href='" + esc(report["html"])
            + "'>HTML kaynak listesi</a> <a href='" + esc(report["json"])
            + "'>JSON</a></p></li>"
            for report in reports
        )
        summary = f"{len(reports)} ayrı araştırma için kaynak listesi bulundu."
    else:
        cards = "<li class='card'>Henüz kaynak listesi oluşturulmadı.</li>"
        summary = "Kaynak listeleri oluşturulduğunda bu sayfada görünecek."
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kaynak listeleri — {esc(directory_name)}</title>
<style>
:root{{--ink:#202833;--muted:#586575;--line:#d9e0e7;--blue:#174f82;--soft:#f4f7fa}}
*{{box-sizing:border-box}}body{{max-width:900px;margin:0 auto;padding:2rem 1.3rem 4rem;color:var(--ink);font:16px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif}}
h1{{line-height:1.25}}.muted{{color:var(--muted);font-size:.9rem}}ul{{padding:0;list-style:none}}.card{{border:1px solid var(--line);border-radius:9px;padding:1rem 1.15rem;margin:1rem 0;background:#fff}}.card h2{{font-size:1.15rem;margin:.1rem 0 .4rem}}a{{color:var(--blue)}}.button{{display:inline-block;background:var(--soft);padding:.4rem .7rem;border-radius:6px;text-decoration:none;font-weight:650}}
@media print{{body{{max-width:none;padding:.4in}}.card{{break-inside:avoid}}}}
</style></head><body>
<h1>İş akışı 1 — kaynak listeleri</h1>
<p class="muted">Klasör: {esc(directory_name)}</p><p>{esc(summary)}</p>
<ul>{cards}</ul>
<p class="muted">Her araştırmanın HTML raporu ve JSON kaydı aynı klasördedir.</p>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aynı 01_kaynak_kesfi klasöründeki kaynak listeleri için giriş HTML'i üretir."
    )
    parser.add_argument("directory", type=Path, help="01_kaynak_kesfi klasörü")
    parser.add_argument("-o", "--output", type=Path, help="Giriş HTML yolu")
    parser.add_argument("--check", action="store_true", help="Yazmadan eşleşen listeleri say")
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        print(f"Kaynak keşfi klasörü bulunamadı: {directory}", file=sys.stderr)
        return 2
    reports = discover(directory)
    if args.check:
        print(f"OK: {directory} içinde {len(reports)} eşleşen kaynak listesi.")
        return 0
    output = args.output or directory / "00_kaynak_listeleri.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(reports, directory.name), encoding="utf-8")
    print(f"Yazıldı: {output} ({len(reports)} kaynak listesi)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
