#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Yazım planı (iskelet) HTML üreticisi — akış 2.

Girdi: ``schemas/writing-plan.schema.json`` biçiminde JSON.
Çıktı: tek dosyalık, yazdırılabilir HTML. Her alt başlık bir karttır:
amaç · hedef kelime · gereken kanıt türü · atanmış kaynaklar · boşluk notu.

Kullanım:
    python3 scripts/build_writing_plan.py plan.json \\
        -o <proje-kökü>/02_yazim_plani/01_yazim_plani.html
    python3 scripts/build_writing_plan.py plan.json --check
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from output_naming import add_timestamp_argument
except ImportError:
    from scripts.output_naming import add_timestamp_argument

GENRE_LABELS = {
    "kitap_bolumu": "Kitap bölümü",
    "uygulama_rehberi": "Uygulama rehberi",
    "derleme_makale": "Derleme makalesi",
    "ampirik_makale": "Ampirik makale",
}

DESIGN_LABELS = {
    "systematic_review": "Sistematik derleme",
    "meta_analysis": "Meta-analiz",
    "rct": "Randomize kontrollü çalışma",
    "quasi_experimental": "Yarı deneysel",
    "cohort": "Kohort",
    "cross_sectional": "Kesitsel",
    "qualitative": "Nitel",
    "policy_document": "Mevzuat / politika belgesi",
    "any": "Herhangi bir tasarım",
}

STATUS_LABELS = {
    "planned": "Planlandı",
    "covered": "Kanıt atandı",
    "gap": "Kanıt boşluğu",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def validate(data: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["Kök nesne bir JSON nesnesi olmalı."]
    for key in ("project", "title", "genre", "target_total_words", "sections"):
        if key not in data:
            errors.append(f"'{key}' alanı zorunlu.")
    if data.get("genre") not in GENRE_LABELS:
        errors.append(
            "genre şu değerlerden biri olmalı: " + ", ".join(GENRE_LABELS)
        )
    total = data.get("target_total_words")
    if not isinstance(total, int) or isinstance(total, bool) or total < 300:
        errors.append("target_total_words en az 300 olan tam sayı olmalı.")
    sections = data.get("sections")
    if not isinstance(sections, list) or len(sections) < 3:
        errors.append("sections en az 3 alt başlık içermeli.")
        return errors

    planned = 0
    seen: set[str] = set()
    for index, section in enumerate(sections, start=1):
        path = f"sections[{index}]"
        if not isinstance(section, dict):
            errors.append(f"{path}: nesne olmalı.")
            continue
        sid = str(section.get("id") or "")
        if not sid:
            errors.append(f"{path}.id: zorunlu.")
        elif sid in seen:
            errors.append(f"{path}.id: yinelenen kimlik {sid!r}.")
        else:
            seen.add(sid)
        for key in ("heading", "purpose"):
            value = section.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{path}.{key}: boş olmayan metin olmalı.")
        words = section.get("target_words")
        if not isinstance(words, int) or isinstance(words, bool) or words < 50:
            errors.append(f"{path}.target_words: en az 50 olan tam sayı olmalı.")
        else:
            planned += words
        needs = section.get("evidence_needs")
        if not isinstance(needs, list) or not needs:
            errors.append(f"{path}.evidence_needs: boş olmayan liste olmalı.")
        else:
            for need_index, need in enumerate(needs, start=1):
                if not isinstance(need, dict) or not need.get("design"):
                    errors.append(
                        f"{path}.evidence_needs[{need_index}].design: zorunlu."
                    )
                elif need["design"] not in DESIGN_LABELS:
                    errors.append(
                        f"{path}.evidence_needs[{need_index}].design: bilinmeyen tür."
                    )
    return errors


def word_budget(data: Dict[str, Any]) -> Dict[str, int]:
    sections = data.get("sections") or []
    planned = sum(
        int(section.get("target_words") or 0)
        for section in sections
        if isinstance(section, dict)
    )
    target = int(data.get("target_total_words") or 0)
    return {
        "sections_total": len(sections),
        "target_total_words": target,
        "planned_section_words": planned,
        "difference": planned - target,
    }


def _section_card(section: Dict[str, Any], index: int) -> str:
    sid = str(section.get("id") or f"S{index}")
    status = str(section.get("status") or "planned")
    needs = "".join(
        f'<span class="chip">{esc(DESIGN_LABELS.get(str(need.get("design")), need.get("design")))}'
        f'{" ×" + esc(need.get("min_count")) if need.get("min_count") else ""}</span>'
        for need in (section.get("evidence_needs") or [])
        if isinstance(need, dict)
    )
    dois = section.get("assigned_dois") or []
    doi_html = (
        "".join(
            f'<a class="doi" href="https://doi.org/{esc(doi)}" target="_blank" '
            f'rel="noopener">{esc(doi)}</a>'
            for doi in dois
        )
        if dois
        else '<span class="muted">Akış 3 henüz kaynak atamadı.</span>'
    )
    gap = ""
    if status == "gap" or section.get("gap_note"):
        gap = (
            '<p class="gap"><strong>Boşluk:</strong> '
            f'{esc(section.get("gap_note") or "Bu alt başlık için yeterli kanıt bulunamadı.")}</p>'
        )
    return f"""
    <article class="section">
      <header>
        <span class="sid">{esc(sid)}</span>
        <h3>{esc(section.get("heading"))}</h3>
        <span class="badge {esc(status)}">{esc(STATUS_LABELS.get(status, status))}</span>
        <span class="words">{esc(section.get("target_words"))} kelime</span>
      </header>
      <p><strong>Amaç:</strong> {esc(section.get("purpose"))}</p>
      <p><strong>Gereken kanıt:</strong> {needs or '<span class="muted">belirtilmedi</span>'}</p>
      <p><strong>Atanmış kaynaklar ({len(dois)}):</strong><br>{doi_html}</p>
      {gap}
    </article>"""


def render(data: Dict[str, Any]) -> str:
    sections = [s for s in (data.get("sections") or []) if isinstance(s, dict)]
    budget = word_budget(data)
    genre = str(data.get("genre") or "")
    gaps = [s for s in sections if (s.get("status") == "gap" or s.get("gap_note"))]
    diff = budget["difference"]
    diff_text = (
        f"{diff:+d} kelime"
        if diff
        else "hedefle uyumlu"
    )
    scope_in = "".join(
        f"<li>{esc(value)}</li>" for value in (data.get("scope_in") or [])
    ) or "<li class='muted'>Belirtilmedi.</li>"
    scope_out = "".join(
        f"<li>{esc(value)}</li>" for value in (data.get("scope_out") or [])
    ) or "<li class='muted'>Belirtilmedi.</li>"
    cards = "".join(
        _section_card(section, index) for index, section in enumerate(sections, 1)
    )
    generated = data.get("generated_at") or datetime.now(timezone.utc).date().isoformat()
    plan_status = str(data.get("plan_status") or "draft")

    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yazım planı — {esc(data.get("title"))}</title>
<style>
:root {{ --bg:#f5f7f9; --card:#fff; --ink:#16212b; --muted:#5b6b7b; --line:#dce3ea; --blue:#0b5cad; --green:#1e7d4f; --red:#b3261e; --amber:#8a5a00; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
header.hero {{ background:#0b2540; color:#fff; padding:26px 22px; }}
header.hero h1 {{ margin:6px 0; font-size:24px; }}
header.hero p {{ margin:0; opacity:.9; }}
main {{ max-width:1080px; margin:0 auto; padding:20px 22px 40px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:16px 0; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
.stat .num {{ font-size:22px; font-weight:700; display:block; }}
.stat small {{ color:var(--muted); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:16px 0; }}
h2 {{ font-size:18px; margin:4px 0 10px; }}
.section {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin:12px 0; }}
.section header {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-bottom:6px; }}
.section h3 {{ font-size:16px; margin:0; }}
.sid {{ font-family:ui-monospace,monospace; font-size:12px; color:var(--muted); }}
.words {{ margin-left:auto; font-size:12px; color:var(--muted); }}
.badge {{ border-radius:999px; padding:2px 10px; font-size:11.5px; font-weight:700; }}
.badge.planned {{ background:#e7f0fa; color:var(--blue); }}
.badge.covered {{ background:#e2f4ea; color:var(--green); }}
.badge.gap {{ background:#fde8e6; color:var(--red); }}
.chip {{ display:inline-block; background:#f0f4f8; border-radius:999px; padding:2px 9px; margin:2px 5px 2px 0; font-size:12px; }}
.doi {{ display:block; font-size:12px; word-break:break-all; }}
.muted {{ color:var(--muted); }}
.gap {{ background:#fff4f2; border-left:3px solid var(--red); padding:8px 10px; border-radius:4px; margin:8px 0 0; }}
ul {{ margin:6px 0; padding-left:20px; }}
footer {{ max-width:1080px; margin:0 auto; padding:0 22px 36px; color:var(--muted); font-size:12.5px; }}
@media print {{ body {{ background:#fff; }} header.hero {{ background:#fff; color:#000; border-bottom:2px solid #000; }} .section,.card {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<header class="hero">
  <div style="text-transform:uppercase;letter-spacing:.08em;font-size:12px;opacity:.8">Yazım planı · Akış 2</div>
  <h1>{esc(data.get("title"))}</h1>
  <p>{esc(GENRE_LABELS.get(genre, genre))} · Hedef {esc(budget["target_total_words"])} kelime · Plan durumu: {esc(plan_status)}</p>
</header>
<main>
  <section class="stats">
    <div class="stat"><span class="num">{budget["sections_total"]}</span><small>Alt başlık</small></div>
    <div class="stat"><span class="num">{esc(budget["planned_section_words"])}</span><small>Planlanan kelime</small></div>
    <div class="stat"><span class="num">{esc(diff_text)}</span><small>Hedefle fark</small></div>
    <div class="stat"><span class="num">{len(gaps)}</span><small>Kanıt boşluğu</small></div>
  </section>

  <section class="card">
    <h2>Kapsam</h2>
    <p><strong>Hedef kitle:</strong> {esc(data.get("audience") or "belirtilmedi")}</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px">
      <div><strong>Kapsam içi</strong><ul>{scope_in}</ul></div>
      <div><strong>Kapsam dışı</strong><ul>{scope_out}</ul></div>
    </div>
    {f'<p class="muted"><strong>Tür notu:</strong> {esc(data.get("genre_note"))}</p>' if data.get("genre_note") else ""}
  </section>

  <section>
    <h2 style="margin-left:2px">Alt başlıklar</h2>
    {cards}
  </section>
</main>
<footer>
  Bu plan akış 3'ün arama ve kaynak atama tabanıdır. “Kanıt boşluğu” işaretli alt başlıklar için ya
  kapsam daraltılmalı ya da boşluk gerekçesiyle kabul edilmelidir. Plan onaylanmadan kaynak indirilmez.
</footer>
</body>
</html>
"""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Yazım planı HTML üreticisi.")
    parser.add_argument("input", type=Path, help="Yazım planı JSON dosyası")
    parser.add_argument("-o", "--output", type=Path, help="Çıktı HTML dosyası")
    parser.add_argument("--check", action="store_true", help="Yalnızca doğrula")
    parser.add_argument("--force", action="store_true", help="Var olan çıktının üzerine yaz")
    add_timestamp_argument(parser)
    args = parser.parse_args(argv)

    from output_naming import add_timestamp

    if not args.input.is_file():
        print(f"Hata: girdi bulunamadı: {args.input}", file=sys.stderr)
        return 2
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Hata: JSON çözümlenemedi: {exc}", file=sys.stderr)
        return 2

    errors = validate(data)
    if errors:
        print("Girdi doğrulama hataları:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    if args.check:
        budget = word_budget(data)
        print(
            f"OK: {args.input} geçerli yazım planı "
            f"({budget['sections_total']} alt başlık, hedef {budget['target_total_words']} kelime)."
        )
        return 0

    if not args.output:
        print("Hata: --check verilmediyse -o/--output zorunludur.", file=sys.stderr)
        return 2
    output = add_timestamp(args.output, enabled=args.timestamp)
    if output.exists() and not args.force:
        print(
            f"Hata: çıktı zaten var: {output}\nÜzerine yazmak için --force kullanın.",
            file=sys.stderr,
        )
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    html_text = render(data)
    output.write_text(html_text, encoding="utf-8")
    print(f"Yazıldı: {output} ({len(html_text):,} bayt)")
    print("Not: önceki planlar silinmedi; her çalıştırma yeni sürüm ekler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
