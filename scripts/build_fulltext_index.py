#!/usr/bin/env python3
"""Build a landing page for one or more workflow-1 source lists."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

try:  # scripts/ içinden çalışırken
    from output_naming import add_timestamp, add_timestamp_argument
except ImportError:  # python -m scripts.build_fulltext_index
    from scripts.output_naming import add_timestamp, add_timestamp_argument

LIST_RE = re.compile(
    r"^(?P<base>.+_fulltext_listesi)(?:_(?P<stamp>\d{8}-\d{6}))?$"
)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _json_for(directory: Path, base: str, stamp: str | None) -> Path | None:
    candidates: list[Path] = []
    if stamp:
        candidates.append(directory / f"{base}_{stamp}.json")
    candidates.append(directory / f"{base}.json")
    for path in candidates:
        if path.is_file():
            return path
    return None


def discover(directory: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for html_path in sorted(directory.glob("*_fulltext_listesi*.html")):
        match = LIST_RE.match(html_path.stem)
        if not match:
            continue
        base = match.group("base")
        stamp = match.group("stamp")
        json_path = _json_for(directory, base, stamp)
        if json_path is None:
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
            "title": data.get("title") or base,
            "project": data.get("project") or "",
            "count": len(candidates),
            "open_access": open_access,
            "stamp": stamp or "",
            "mtime": html_path.stat().st_mtime,
        })
    reports.sort(key=lambda report: (report.get("stamp") or "", report.get("mtime") or 0), reverse=True)
    return reports


def render(reports: list[dict[str, Any]], directory_name: str) -> str:
    if reports:
        cards = "".join(
            "<li class='card'><h2>" + esc(report["title"]) + "</h2>"
            + ("<p class='muted'>" + esc(report["project"]) + "</p>" if report["project"] else "")
            + ("<p class='muted'>Sürüm: " + esc(report["stamp"]) + "</p>" if report.get("stamp") else "")
            + f"<p>{report['count']} aday kaynak · {report['open_access']} açık erişim</p>"
            + "<p><a class='button' href='" + esc(report["html"])
            + "'>HTML kaynak listesi</a> <a href='" + esc(report["json"])
            + "'>JSON</a></p></li>"
            for report in reports
        )
        summary = (
            f"{len(reports)} kaynak listesi sürümü bulundu. "
            "Önceki sürümler silinmez; her çalıştırma yeni bir zaman damgalı dosya üretir."
        )
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
<h1>Akış 3 — kaynak listeleri</h1>
<p class="muted">Klasör: {esc(directory_name)}</p><p>{esc(summary)}</p>
<ul>{cards}</ul>
<p class="muted">Her araştırmanın HTML raporu ve JSON kaydı aynı klasördedir.</p>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aynı 03_kaynak_kesfi klasöründeki kaynak listeleri için giriş HTML'i üretir."
    )
    parser.add_argument("directory", type=Path, help="03_kaynak_kesfi klasörü")
    parser.add_argument("-o", "--output", type=Path, help="Giriş HTML yolu")
    parser.add_argument("--check", action="store_true", help="Yazmadan eşleşen listeleri say")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Aynı ada sahip giriş sayfasının üzerine yaz (varsayılan: yazma).",
    )
    add_timestamp_argument(parser)
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
    output = add_timestamp(output, enabled=args.timestamp)
    if output.exists() and not args.force:
        print(
            f"Hata: çıktı zaten var: {output}\n"
            "Üzerine yazmak için --force kullanın. Zaman soneki varsayılan "
            "olduğu için önceki giriş sayfaları silinmez.",
            file=sys.stderr,
        )
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(reports, directory.name), encoding="utf-8")
    print(f"Yazıldı: {output} ({len(reports)} kaynak listesi)")
    print("Not: önceki listeler ve giriş sayfaları korunur; hiçbir dosya silinmedi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
