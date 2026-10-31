#!/usr/bin/env python3
"""Render topic/title/aim discovery JSON as a portable HTML report."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
DATABASE_LABELS = {
    "openalex": "OpenAlex",
    "pubmed": "PubMed",
    "europepmc": "Europe PMC",
    "crossref": "Crossref",
    "other": "Diğer",
}
STATUS_LABELS = {"ok": "Arandı", "error": "Hata", "not_searched": "Aranmadı"}
NOVELTY_LABELS = {"weak": "Sınırlı boşluk sinyali", "moderate": "Orta düzey boşluk sinyali", "strong": "Belirgin boşluk sinyali"}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def doi_link(doi: Any, title: Any) -> str:
    raw = str(doi or "").strip()
    text = esc(title)
    if DOI_RE.match(raw):
        return f'<a href="https://doi.org/{esc(raw)}">{text}</a>'
    return text


def validate(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Kök JSON nesne olmalı."]
    for key in ("project", "title", "topic", "generated_at"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key}: boş olmayan metin olmalı.")
    databases = data.get("database_searches")
    if not isinstance(databases, list) or not databases:
        errors.append("database_searches: en az bir veritabanı sorgusu olmalı.")
    else:
        for i, item in enumerate(databases):
            path = f"database_searches[{i}]"
            if not isinstance(item, dict):
                errors.append(f"{path}: nesne olmalı.")
                continue
            if item.get("database") not in DATABASE_LABELS:
                errors.append(f"{path}.database: desteklenmeyen veritabanı.")
            if not str(item.get("query") or "").strip():
                errors.append(f"{path}.query: boş olamaz.")
            if item.get("status") not in STATUS_LABELS:
                errors.append(f"{path}.status: ok/error/not_searched olmalı.")
            if not isinstance(item.get("result_count"), int) or item["result_count"] < 0:
                errors.append(f"{path}.result_count: sıfır veya daha büyük tam sayı olmalı.")

    proposals = data.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        errors.append("proposals: en az bir öneri olmalı.")
    else:
        required = ("rank", "proposed_title", "research_question", "aim", "objectives", "population_context", "suggested_design", "gap_type", "novelty_opportunity", "novelty_signal", "closest_studies", "feasibility_notes", "ranking_rationale")
        for i, item in enumerate(proposals):
            path = f"proposals[{i}]"
            if not isinstance(item, dict):
                errors.append(f"{path}: nesne olmalı.")
                continue
            for key in required:
                if key not in item:
                    errors.append(f"{path}.{key}: zorunlu.")
            if not isinstance(item.get("rank"), int) or item.get("rank", 0) < 1:
                errors.append(f"{path}.rank: pozitif tam sayı olmalı.")
            for key in ("proposed_title", "research_question", "aim", "population_context", "suggested_design", "novelty_opportunity", "feasibility_notes", "ranking_rationale"):
                if not str(item.get(key) or "").strip():
                    errors.append(f"{path}.{key}: boş olamaz.")
            if not isinstance(item.get("objectives"), list) or not item["objectives"]:
                errors.append(f"{path}.objectives: en az bir amaç olmalı.")
            if not isinstance(item.get("closest_studies"), list):
                errors.append(f"{path}.closest_studies: dizi olmalı.")
        ranks = [item.get("rank") for item in proposals if isinstance(item, dict)]
        if len(ranks) != len(set(ranks)):
            errors.append("proposals.rank: sıra numaraları benzersiz olmalı.")
    if not isinstance(data.get("limitations"), list) or not data["limitations"]:
        errors.append("limitations: en az bir sınırlılık açıklanmalı.")
    return errors


def render(data: dict[str, Any]) -> str:
    rows: list[str] = []
    for item in data["database_searches"]:
        database = item.get("database_label") or DATABASE_LABELS[item["database"]]
        status = item["status"]
        rows.append(
            "<tr>"
            f"<td>{esc(database)}</td><td>{esc(item['query'])}</td>"
            f'<td class="status {esc(status)}">{esc(STATUS_LABELS[status])}</td>'
            f"<td>{esc(item['result_count'])}</td>"
            f"<td>{esc(item.get('note') or '—')}</td></tr>"
        )

    cards: list[str] = []
    for item in sorted(data["proposals"], key=lambda proposal: proposal["rank"]):
        studies: list[str] = []
        for study in item.get("closest_studies") or []:
            relevance = f'<p>{esc(study["relevance"])}</p>'
            limitation = f'<p class="muted"><strong>Çalışma sınırı:</strong> {esc(study["limitation"])}</p>' if study.get("limitation") else ""
            source = f'<span class="muted">{esc(study["database"])}</span> · ' if study.get("database") else ""
            studies.append(
                "<li>" + source + doi_link(study.get("doi"), study["title"])
                + relevance + limitation + "</li>"
            )
        study_html = "<ul>" + "".join(studies) + "</ul>" if studies else "<p>Arama çıktılarında yakın çalışma kaydı bulunamadı.</p>"
        objectives = "<ul>" + "".join(f"<li>{esc(value)}</li>" for value in item["objectives"]) + "</ul>"
        cards.append(f"""
<article class="proposal">
  <div class="proposal-head"><span class="rank">#{esc(item['rank'])}</span><span class="novelty {esc(item['novelty_signal'])}">{esc(NOVELTY_LABELS.get(item['novelty_signal'], item['novelty_signal']))}</span></div>
  <h2>{esc(item['proposed_title'])}</h2>
  <p><strong>Araştırma sorusu:</strong> {esc(item['research_question'])}</p>
  <p><strong>Çalışmanın amacı:</strong> {esc(item['aim'])}</p>
  <h3>Özel amaçlar</h3>{objectives}
  <dl><dt>Hedef grup / bağlam</dt><dd>{esc(item['population_context'])}</dd>
  <dt>Önerilen desen</dt><dd>{esc(item['suggested_design'])}</dd>
  <dt>Olası boşluk türü</dt><dd>{esc(item['gap_type'])}</dd>
  <dt>Özgünlük fırsatı</dt><dd>{esc(item['novelty_opportunity'])}</dd>
  <dt>Yapılabilirlik</dt><dd>{esc(item['feasibility_notes'])}</dd>
  <dt>Sıralama gerekçesi</dt><dd>{esc(item['ranking_rationale'])}</dd></dl>
  <h3>En yakın bulunan çalışmalar</h3>{study_html}
</article>""")

    limitations = "<ul>" + "".join(f"<li>{esc(value)}</li>" for value in data["limitations"]) + "</ul>"
    scope = f'<p><strong>Tarama kapsamı:</strong> {esc(data["scope"])}</p>' if data.get("scope") else ""
    next_step = f'<p class="next"><strong>Sonraki adım:</strong> {esc(data["next_step"])}</p>' if data.get("next_step") else ""
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(data['title'])} — {esc(data['project'])}</title>
<style>
:root{{--ink:#202833;--muted:#586575;--line:#d9e0e7;--blue:#174f82;--soft:#f4f7fa;--green:#e1f3e9;--amber:#fff1d2;--gray:#edf0f3}}
*{{box-sizing:border-box}}body{{max-width:1050px;margin:0 auto;padding:2rem 1.4rem 4rem;color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
h1,h2,h3{{line-height:1.25}}h1{{margin:0 0 .5rem;font-size:2rem}}h2{{font-size:1.35rem}}h3{{font-size:1rem;margin-bottom:.4rem}}p{{margin:.5rem 0}}a{{color:var(--blue)}}.meta,.muted{{color:var(--muted);font-size:.88rem}}
.callout{{background:#fff9e9;border-left:4px solid #bd8121;padding:.8rem 1rem;margin:1.3rem 0}}.scope{{background:var(--soft);padding:.7rem 1rem;border-radius:7px}}
.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px}}table{{border-collapse:collapse;width:100%;min-width:700px}}th,td{{text-align:left;vertical-align:top;padding:.65rem;border-bottom:1px solid var(--line)}}th{{background:var(--soft);font-size:.82rem}}.status{{font-weight:700}}.status.ok{{color:#17663a}}.status.error{{color:#9b2d28}}.status.not_searched{{color:#7a5d23}}
.proposal{{border:1px solid var(--line);border-radius:10px;padding:1.1rem 1.25rem;margin:1.2rem 0;break-inside:avoid}}.proposal-head{{display:flex;align-items:center;gap:.65rem}}.rank{{font-weight:800;font-size:1.1rem;color:var(--blue)}}.novelty{{border-radius:99px;padding:.18rem .65rem;font-size:.78rem;font-weight:700}}.novelty.strong{{background:var(--green);color:#17663a}}.novelty.moderate{{background:var(--amber);color:#765000}}.novelty.weak{{background:var(--gray);color:#4f5b66}}dl{{display:grid;grid-template-columns:minmax(145px, .3fr) 1fr;gap:.35rem .8rem}}dt{{font-weight:700}}dd{{margin:0}}li{{margin:.25rem 0}}.next{{background:var(--soft);padding:.8rem 1rem}}footer{{margin-top:2rem;border-top:1px solid var(--line);padding-top:.7rem;color:var(--muted);font-size:.8rem}}
@media print{{body{{padding:.4in;max-width:none}}.proposal{{break-inside:avoid}}a{{color:inherit;text-decoration:none}}}}
</style></head><body>
<h1>{esc(data['title'])}</h1><p class="meta">Proje: <strong>{esc(data['project'])}</strong> · Üretim: {esc(data['generated_at'])}</p>
<p class="scope"><strong>Konu:</strong> {esc(data['topic'])}</p>{scope}
<aside class="callout"><strong>Özgünlük notu:</strong> Bu rapor, seçilen veri tabanlarında bulunan kayıtlar üzerinden olası araştırma boşluklarını gösterir. “Özgünlük fırsatı” kesin yenilik kanıtı değildir; kapsamlı sistematik tarama, atıf zinciri ve alan uzmanı doğrulaması gerekir.</aside>
<h2>Veri tabanı tarama kaydı</h2><div class="table-wrap"><table><thead><tr><th>Veri tabanı</th><th>Sorgu</th><th>Durum</th><th>Kayıt</th><th>Not</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Sıralı çalışma önerileri</h2>{''.join(cards)}
<h2>Taramanın sınırları</h2>{limitations}{next_step}
<footer>Öneriler karar desteğidir; kullanıcı onayı olmadan araştırma başlığı veya çalışma tasarımı kesinleştirilmez.</footer>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Konu keşfi JSON'unu çevrimdışı HTML'e çevirir.")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Girdi okunamadı: {exc}", file=sys.stderr)
        return 2
    errors = validate(data)
    if errors:
        print("Girdi doğrulama hataları:\n" + "\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    if args.check:
        print(f"OK: {args.input} geçerli ({len(data['proposals'])} öneri).")
        return 0
    if not args.output:
        parser.error("--check kullanılmadığında -o/--output zorunludur")
    if args.output.exists() and not args.force:
        print(f"Çıktı zaten var: {args.output}; üzerine yazmak için --force kullanın.", file=sys.stderr)
        return 2
    output = render(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(f"Yazıldı: {args.output} ({len(output):,} bayt)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
