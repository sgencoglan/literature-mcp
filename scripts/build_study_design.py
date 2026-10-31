#!/usr/bin/env python3
"""Render a selected topic proposal's study-design JSON as portable HTML."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def bullets(items: list[Any]) -> str:
    return "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


def validate(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["Kök JSON nesne olmalı."]
    required = ("project", "title", "generated_at", "selected_proposal", "design_status", "assumptions", "research_questions", "aim", "objectives", "design_rationale", "design", "population", "sampling", "sample_size", "variables", "measures", "procedure", "analysis", "ethics", "feasibility", "limitations", "decisions_for_user")
    errors = [f"{key}: zorunlu." for key in required if key not in data]
    for key in ("project", "title", "generated_at", "aim", "design_rationale"):
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            errors.append(f"{key}: boş olmayan metin olmalı.")
    if data.get("design_status") not in {"proposed", "user_review", "approved"}:
        errors.append("design_status: proposed/user_review/approved olmalı.")
    for key in ("assumptions", "research_questions", "objectives", "variables", "measures", "procedure", "ethics", "feasibility", "limitations", "decisions_for_user"):
        if key in data and not isinstance(data[key], list):
            errors.append(f"{key}: dizi olmalı.")
    object_fields = {
        "selected_proposal": ("rank", "proposed_title"),
        "design": ("approach", "design_type", "setting", "timeframe"),
        "population": ("target", "inclusion", "exclusion"),
        "sampling": ("strategy", "recruitment"),
        "sample_size": ("target", "rationale"),
        "analysis": ("quantitative", "qualitative", "integration"),
    }
    for key, fields in object_fields.items():
        if key in data and not isinstance(data[key], dict):
            errors.append(f"{key}: nesne olmalı.")
        elif isinstance(data.get(key), dict):
            errors.extend(f"{key}.{field}: zorunlu." for field in fields if field not in data[key])
    item_fields = {
        "variables": ("name", "role", "operationalization"),
        "measures": ("construct", "instrument_or_method", "caveat"),
        "procedure": ("stage", "description"),
    }
    for key, fields in item_fields.items():
        items = data.get(key, [])
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{key}[{index}]: nesne olmalı.")
            else:
                errors.extend(f"{key}[{index}].{field}: zorunlu." for field in fields if field not in item)
    return errors


def web_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def render(data: dict[str, Any]) -> str:
    design = data["design"]
    population = data["population"]
    sampling = data["sampling"]
    sample_size = data["sample_size"]
    analysis = data["analysis"]
    variables = "".join(
        f"<tr><td>{esc(item['name'])}</td><td>{esc(item['role'])}</td><td>{esc(item['operationalization'])}</td></tr>"
        for item in data["variables"]
    )
    measures = "".join(
        "<article class='card'><h3>" + esc(item["construct"]) + "</h3><p><strong>Ölçüm:</strong> "
        + esc(item["instrument_or_method"]) + "</p><p class='muted'><strong>Sınır:</strong> "
        + esc(item["caveat"]) + "</p>"
        + (f"<p><a href='{esc(item['source_url'])}'>Kaynak</a></p>" if web_url(item.get("source_url")) else "")
        + "</article>"
        for item in data["measures"]
    )
    procedure = "".join(f"<li><strong>{esc(item['stage'])}:</strong> {esc(item['description'])}</li>" for item in data["procedure"])
    references = "".join(
        f"<li><a href='{esc(item['url'])}'>{esc(item['title'])}</a> — {esc(item['relevance'])}</li>"
        for item in data.get("references", []) if web_url(item.get("url"))
    )
    decisions = bullets(data["decisions_for_user"]) if data["decisions_for_user"] else "<p>Ek karar gerekmiyor.</p>"
    status = {"proposed": "Öneri", "user_review": "Kullanıcı incelemesinde", "approved": "Onaylandı"}[data["design_status"]]
    return f"""<!doctype html><html lang='tr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{esc(data['title'])} — Yöntem tasarımı</title><style>
:root{{--ink:#202833;--muted:#586575;--line:#d9e0e7;--blue:#174f82;--soft:#f4f7fa;--amber:#fff1d2}}*{{box-sizing:border-box}}body{{max-width:1000px;margin:auto;padding:2rem 1.4rem 4rem;color:var(--ink);font:16px/1.58 system-ui,-apple-system,'Segoe UI',sans-serif}}h1,h2,h3{{line-height:1.25}}h1{{font-size:2rem}}h2{{margin-top:2rem;border-bottom:1px solid var(--line);padding-bottom:.4rem}}h3{{font-size:1.05rem;margin:.2rem 0 .5rem}}p{{margin:.55rem 0}}li{{margin:.35rem 0}}a{{color:var(--blue)}}.meta,.muted{{color:var(--muted);font-size:.9rem}}.banner{{background:var(--amber);padding:1rem;border-left:4px solid #bd8121;border-radius:5px}}.card{{border:1px solid var(--line);padding:1rem;border-radius:8px;margin:.8rem 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:.7rem}}.grid .card{{margin:0}}table{{width:100%;border-collapse:collapse;margin:1rem 0}}th,td{{text-align:left;vertical-align:top;border:1px solid var(--line);padding:.6rem}}th{{background:var(--soft)}}
@media print{{body{{max-width:none;padding:.4in}}tr,.card{{break-inside:avoid}}}}</style></head><body>
<h1>Araştırma yöntemi ve tasarım önerisi</h1><p class='meta'>Proje: <strong>{esc(data['project'])}</strong> · Durum: {esc(status)} · Tarih: {esc(data['generated_at'])}</p>
<div class='banner'><strong>Seçilen başlık (#{esc(data['selected_proposal']['rank'])}):</strong> {esc(data['selected_proposal']['proposed_title'])}<br><strong>Tasarımın durumu:</strong> Bu, kullanıcı ve araştırma ekibi incelemesine sunulan yöntem önerisidir.</div>
<h2>Varsayımlar ve kapsam</h2>{bullets(data['assumptions'])}
<h2>Amaç ve araştırma soruları</h2><p><strong>Amaç:</strong> {esc(data['aim'])}</p>{bullets(data['research_questions'])}<h3>Özel amaçlar</h3>{bullets(data['objectives'])}
<h2>Önerilen desen</h2><div class='grid'><div class='card'><strong>Yaklaşım</strong><p>{esc(design['approach'])}</p></div><div class='card'><strong>Desen</strong><p>{esc(design['design_type'])}</p></div><div class='card'><strong>Ortam</strong><p>{esc(design['setting'])}</p></div><div class='card'><strong>Zaman çerçevesi</strong><p>{esc(design['timeframe'])}</p></div></div><p>{esc(data['design_rationale'])}</p>
<h2>Evren ve örneklem</h2><p><strong>Hedef grup:</strong> {esc(population['target'])}</p><h3>Dahil edilme ölçütleri</h3>{bullets(population['inclusion'])}<h3>Dışlama/ayrı değerlendirme ölçütleri</h3>{bullets(population['exclusion'])}<p><strong>Örnekleme:</strong> {esc(sampling['strategy'])}</p><p><strong>Katılımcıya ulaşma:</strong> {esc(sampling['recruitment'])}</p><p><strong>Hedef büyüklük:</strong> {esc(sample_size['target'])}</p><p>{esc(sample_size['rationale'])}</p>
<h2>Değişkenler</h2><div style='overflow-x:auto'><table><thead><tr><th>Değişken</th><th>Rol</th><th>Tanım/işlemselleştirme</th></tr></thead><tbody>{variables}</tbody></table></div>
<h2>Ölçüm araçları ve sınırları</h2>{measures}
<h2>Veri toplama adımları</h2><ol>{procedure}</ol>
<h2>Analiz ve veri bütünleştirme</h2><h3>Nicel</h3>{bullets(analysis['quantitative'])}<h3>Nitel</h3>{bullets(analysis['qualitative'])}<h3>Bütünleştirme</h3><p>{esc(analysis['integration'])}</p>
<h2>Etik, uygulanabilirlik ve sınırlılıklar</h2><h3>Etik</h3>{bullets(data['ethics'])}<h3>Uygulanabilirlik</h3>{bullets(data['feasibility'])}<h3>Sınırlılıklar</h3>{bullets(data['limitations'])}
<h2>Kullanıcı/araştırma ekibiyle netleştirilecekler</h2>{decisions}
{('<h2>Yöntem dayanakları</h2><ul>'+references+'</ul>') if references else ''}
<p class='meta'>Özgünlük, ölçme geçerliği veya etik uygunluk hakkında kesin hüküm değildir. Örneklem hesabı, ölçme aracı izinleri ve etik kurul koşulları araştırma ekibi tarafından doğrulanmalıdır.</p></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Seçilen başlık için yöntem tasarımı JSON'unu çevrimdışı HTML'e çevirir.")
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
        print(f"OK: {args.input} geçerli yöntem tasarımı.")
        return 0
    if not args.output:
        parser.error("--check kullanılmadığında -o/--output zorunludur")
    if args.output.exists() and not args.force:
        print(f"Çıktı zaten var: {args.output}; üzerine yazmak için --force kullanın.", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = render(data)
    args.output.write_text(output, encoding="utf-8")
    print(f"Yazıldı: {args.output} ({len(output):,} bayt)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
