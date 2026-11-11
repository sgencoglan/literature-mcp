#!/usr/bin/env python3
"""Plan uyumu denetimi — akış 5.

Taslak metni ile yazım planını karşılaştırır:

* Planlanan her alt başlık taslakta var mı?
* Bölüm kelime sayısı hedefe yakın mı? (±%25 tolerans)
* Planda olmayan alt başlık eklendi mi? (kapsam kayması)
* Atanan kaynakların kaçı taslakta geçiyor?
* Hangi alt başlık kanıt boşluğu olarak kalmış?

Bu denetim **iddia–kanıt denetiminin yerine geçmez**; onu tamamlar.
Kanıt doğrulaması hâlâ `chapter-report` kalite kapısı ve Ek 2 ile yapılır.

Kullanım:
    python3 scripts/check_plan_compliance.py plan.json taslak.json
    python3 scripts/check_plan_compliance.py plan.json taslak.json --check
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from project_layout import workflow_dir
except ImportError:
    from scripts.project_layout import workflow_dir

TOLERANCE = 0.25


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def draft_paragraphs(draft: Dict[str, Any]) -> List[str]:
    intro = draft.get("intro") if isinstance(draft, dict) else None
    raw = (intro or {}).get("paragraphs") or []
    out: List[str] = []
    for paragraph in raw:
        if isinstance(paragraph, str):
            out.append(paragraph)
        elif isinstance(paragraph, dict):
            if paragraph.get("text"):
                out.append(str(paragraph["text"]))
            elif paragraph.get("segments"):
                out.append(
                    "".join(
                        str(seg.get("text", "")) if isinstance(seg, dict) else str(seg)
                        for seg in paragraph["segments"]
                    )
                )
    return out


def split_sections(paragraphs: List[str]) -> List[Dict[str, Any]]:
    """Metni ``**Başlık**`` biçimindeki kalın satırlardan bölümlere ayır."""
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for paragraph in paragraphs:
        heading_match = re.fullmatch(r"\*\*(.+?)\*\*", paragraph.strip())
        if heading_match:
            current = {"heading": heading_match.group(1).strip(), "words": 0}
            sections.append(current)
            continue
        if current is None:
            current = {"heading": "(giriş)", "words": 0}
            sections.append(current)
        current["words"] += len(paragraph.split())
    return sections


def compare(plan: Dict[str, Any], draft: Dict[str, Any]) -> Dict[str, Any]:
    planned = [
        section
        for section in (plan.get("sections") or [])
        if isinstance(section, dict)
    ]
    actual = split_sections(draft_paragraphs(draft))
    actual_by_norm = {_normalize(item["heading"]): item for item in actual}
    draft_text = _normalize(" ".join(draft_paragraphs(draft)))

    results: List[Dict[str, Any]] = []
    matched_headings: set[str] = set()
    for section in planned:
        heading = str(section.get("heading") or "")
        key = _normalize(heading)
        hit = actual_by_norm.get(key)
        if hit is None:
            # Başlık numarası taşıyorsa ("3. Tanıma") son parçasıyla eşleştir.
            stripped = re.sub(r"^\s*\d+[.)]\s*", "", key)
            hit = next(
                (
                    value
                    for name, value in actual_by_norm.items()
                    if re.sub(r"^\s*\d+[.)]\s*", "", name) == stripped
                ),
                None,
            )
        if hit:
            matched_headings.add(_normalize(hit["heading"]))
        target = int(section.get("target_words") or 0)
        written = int(hit["words"]) if hit else 0
        if target:
            deviation = round((written - target) / target, 3)
            within = abs(deviation) <= TOLERANCE
        else:
            deviation, within = 0.0, True
        assigned = [str(doi).lower() for doi in (section.get("assigned_dois") or [])]
        used = [doi for doi in assigned if doi in draft_text]
        results.append(
            {
                "section_id": section.get("id"),
                "heading": heading,
                "written": hit is not None,
                "target_words": target,
                "written_words": written,
                "deviation": deviation,
                "within_tolerance": within,
                "assigned_sources": len(assigned),
                "used_sources": len(used),
                "unused_sources": [
                    doi for doi in assigned if doi not in draft_text
                ],
            }
        )

    extra = [
        item["heading"]
        for item in actual
        if _normalize(item["heading"]) not in matched_headings
        and _normalize(item["heading"]) != "(giriş)"
    ]
    missing = [entry for entry in results if not entry["written"]]
    off_budget = [entry for entry in results if not entry["within_tolerance"]]
    unused_total = sum(len(entry["unused_sources"]) for entry in results)
    assigned_total = sum(entry["assigned_sources"] for entry in results)

    return {
        "schema": "plan-compliance/1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project": plan.get("project"),
        "title": plan.get("title"),
        "genre": plan.get("genre"),
        "plan_sections": len(planned),
        "draft_sections": len(actual),
        "written_sections": len(planned) - len(missing),
        "missing_sections": missing,
        "extra_sections": extra,
        "off_budget": off_budget,
        "assigned_sources_total": assigned_total,
        "unused_sources_total": unused_total,
        "target_total_words": int(plan.get("target_total_words") or 0),
        "written_total_words": sum(int(item["words"]) for item in actual),
        "sections": results,
        "notes": [
            "Bu denetim plan uyumunu ölçer; kanıt doğrulaması değildir.",
            "Kanıt için chapter-report kalite kapısı ve Ek 2 iddia–kanıt matrisi esastır.",
        ],
    }


def render_html(report: Dict[str, Any]) -> str:
    rows = []
    muted_ok = '<span class="muted">uyumlu</span>'
    for section in report["sections"]:
        flags = []
        if not section["written"]:
            flags.append('<span class="badge bad">Yazılmadı</span>')
        if not section["within_tolerance"] and section["written"]:
            flags.append(
                f'<span class="badge warn">Kelime sapması {section["deviation"]:+.0%}</span>'
            )
        if section["unused_sources"]:
            flags.append(
                f'<span class="badge warn">{len(section["unused_sources"])} atanan kaynak kullanılmadı</span>'
            )
        rows.append(
            "<tr>"
            f'<td class="sid">{esc(section["section_id"])}</td>'
            f'<td>{esc(section["heading"])}</td>'
            f'<td class="num">{esc(section["target_words"])}</td>'
            f'<td class="num">{esc(section["written_words"])}</td>'
            f'<td class="num">{esc(section["used_sources"])}/{esc(section["assigned_sources"])}</td>'
            f'<td>{" ".join(flags) or muted_ok}</td>'
            "</tr>"
        )
    extra_html = (
        "<ul>"
        + "".join(f"<li>{esc(heading)}</li>" for heading in report["extra_sections"])
        + "</ul>"
        if report["extra_sections"]
        else '<p class="muted">Planda olmayan bölüm yok.</p>'
    )
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Plan uyumu — {esc(report.get("title"))}</title>
<style>
body {{ margin:0; background:#f5f7f9; color:#16212b; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
header.hero {{ background:#0b2540; color:#fff; padding:24px 22px; }}
main {{ max-width:1040px; margin:0 auto; padding:20px 22px 40px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:16px 0; }}
.stat {{ background:#fff; border:1px solid #dce3ea; border-radius:10px; padding:12px 14px; }}
.stat .num {{ font-size:22px; font-weight:700; display:block; }}
.card {{ background:#fff; border:1px solid #dce3ea; border-radius:10px; padding:16px; margin:16px 0; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; font-size:12px; text-transform:uppercase; color:#5b6b7b; border-bottom:1px solid #dce3ea; padding:8px 10px; }}
td {{ border-bottom:1px solid #dce3ea; padding:9px 10px; vertical-align:top; }}
td.num {{ text-align:right; white-space:nowrap; }}
.sid {{ font-family:ui-monospace,monospace; font-size:12px; color:#5b6b7b; }}
.badge {{ border-radius:999px; padding:2px 9px; font-size:11.5px; font-weight:700; margin-right:4px; }}
.badge.bad {{ background:#fde8e6; color:#b3261e; }}
.badge.warn {{ background:#fff4d6; color:#8a5a00; }}
.muted {{ color:#5b6b7b; }}
footer {{ max-width:1040px; margin:0 auto; padding:0 22px 36px; color:#5b6b7b; font-size:12.5px; }}
@media print {{ body {{ background:#fff; }} header.hero {{ background:#fff; color:#000; border-bottom:2px solid #000; }} }}
</style></head><body>
<header class="hero"><div style="text-transform:uppercase;letter-spacing:.08em;font-size:12px;opacity:.8">Plan uyumu denetimi · Akış 5</div>
<h1>{esc(report.get("title"))}</h1><p>{esc(report.get("genre") or "")}</p></header>
<main>
<section class="stats">
  <div class="stat"><span class="num">{report["written_sections"]}/{report["plan_sections"]}</span><small>Yazılan alt başlık</small></div>
  <div class="stat"><span class="num">{report["written_total_words"]}</span><small>Yazılan kelime</small></div>
  <div class="stat"><span class="num">{report["target_total_words"]}</span><small>Hedef kelime</small></div>
  <div class="stat"><span class="num">{report["unused_sources_total"]}</span><small>Kullanılmayan atama</small></div>
</section>
<section class="card">
  <h2>Alt başlık uyumu</h2>
  <table><thead><tr><th>ID</th><th>Başlık</th><th>Hedef</th><th>Yazılan</th><th>Kaynak</th><th>Durum</th></tr></thead>
  <tbody>{"".join(rows)}</tbody></table>
</section>
<section class="card">
  <h2>Planda olmayan bölümler (kapsam kayması)</h2>
  {extra_html}
</section>
</main>
<footer>Bu rapor plan uyumunu ölçer; kanıt doğrulaması chapter-report kalite kapısı ve Ek 2 ile yapılır.</footer>
</body></html>"""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Plan uyumu denetimi (akış 5).")
    parser.add_argument("plan", type=Path, help="Yazım planı JSON")
    parser.add_argument("draft", type=Path, help="Taslak JSON (chapter-report girdisi)")
    parser.add_argument("-o", "--output-dir", type=Path, help="Çıktı klasörü")
    parser.add_argument("--check", action="store_true", help="Yalnızca özet, dosya yazma")
    parser.add_argument("--strict", action="store_true", help="Uyumsuzlukta çıkış kodu 1")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--no-timestamp", dest="timestamp", action="store_false",
        help="Sabit dosya adı kullan.",
    )
    args = parser.parse_args(argv)

    from output_naming import add_timestamp

    for path in (args.plan, args.draft):
        if not path.is_file():
            print(f"Hata: dosya bulunamadı: {path}", file=sys.stderr)
            return 2
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        draft = json.loads(args.draft.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Hata: JSON çözümlenemedi: {exc}", file=sys.stderr)
        return 2

    report = compare(plan, draft)
    print(
        f"Alt başlık: {report['written_sections']}/{report['plan_sections']} yazıldı | "
        f"kelime: {report['written_total_words']}/{report['target_total_words']} | "
        f"kullanılmayan atama: {report['unused_sources_total']}"
    )
    for entry in report["missing_sections"]:
        print(f"  EKSİK: {entry['section_id']} {entry['heading']}")
    for entry in report["off_budget"]:
        print(
            f"  SAPMA: {entry['section_id']} {entry['heading']} "
            f"({entry['written_words']}/{entry['target_words']}, {entry['deviation']:+.0%})"
        )
    for heading in report["extra_sections"]:
        print(f"  PLANSIZ BÖLÜM: {heading}")

    if args.check:
        problems = (
            report["missing_sections"]
            or report["off_budget"]
            or report["extra_sections"]
        )
        return 1 if (args.strict and problems) else 0

    output_dir = (
        args.output_dir or workflow_dir(args.plan.parent.parent, "5")
    ).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = add_timestamp(output_dir / "05_plan_uyumu.json", enabled=args.timestamp)
    stem = stem.with_suffix("")
    json_path = stem.with_suffix(".json")
    html_path = stem.with_suffix(".html")
    if not args.force:
        for path in (json_path, html_path):
            if path.exists():
                print(f"Hata: çıktı zaten var: {path}", file=sys.stderr)
                return 2
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    html_path.write_text(render_html(report), encoding="utf-8")
    print(f"Yazıldı: {json_path}")
    print(f"Yazıldı: {html_path}")
    problems = (
        report["missing_sections"] or report["off_budget"] or report["extra_sections"]
    )
    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())