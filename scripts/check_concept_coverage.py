#!/usr/bin/env python3
"""Kavram kapsama denetimi — "anchor term" zincirini doğrular.

Neden gerekli
-------------
Bir bölümün kavramsal çekirdeği literatürde tek bir terimle anılır:
*de-escalation*, *scaffolding*, *self-regulated learning* ... Kullanıcının
ifadesi bu kavramın Türkçe karşılığı olabilir ("kriz öncesi/anı/sonrası" =
escalation cycle). Plan bu terimi ``search_terms`` içine almazsa zincirin
tamamı kör kalır:

    kavram -> sözlük -> toplama -> seçme -> yazma

Ölçülen bir vakada plan 31 kaynağı taradı ama "de-escalation" hiçbir sorguda
geçmediği için alanın çekirdek makalesi (Q1, 2023, "Loaded Moments") havuza
girse bile atanmadı; 31 PDF'in yalnızca 1'inde kelime geçti.

Bu betik üç halkayı denetler:

1. **Sözlük** — her anchor terim planın ``search_terms`` alanında geçiyor mu?
2. **Külliyat** — indirilen PDF'lerde anchor terim geçiyor mu, kaçında?
3. **Seçim** — havuzda başlığında/özetinde anchor terim geçen kayıtlar
   atanmış mı, atanmadıysa gerekçesi var mı?

Kullanım:
    python3 scripts/check_concept_coverage.py <proje-kökü> --workflow 2
    python3 scripts/check_concept_coverage.py plan.json --fulltext-dir ... \\
        --pool 00_doi_havuzu.json --assignments 00_atamalar.json
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
    from output_naming import add_timestamp, add_timestamp_argument, write_versioned_pair
except ImportError:
    from scripts.output_naming import (
        add_timestamp,
        add_timestamp_argument,
        write_versioned_pair,
    )

try:
    from project_layout import fulltext_dir, workflow_dir
except ImportError:
    from scripts.project_layout import fulltext_dir, workflow_dir

SCHEMA_ID = "concept-coverage/1"
OUTPUT_STEM = "03_kavram_kapsami"
MIN_CORPUS_RATIO = 0.15  # PDF'lerin en az %15'inde anchor terim geçmeli


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _norm(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in lowered if not unicodedata.combining(ch)).lower()


def _variant_pattern(term: str) -> re.Pattern[str]:
    """Terimin yazım varyantlarını yakala (de-escalation / deescalation / de escalation)."""
    # Terim tireyle yazılmış olabilir ("de-escalation"); bileşenlerine ayır ki
    # boşluklu ve bitişik yazımlar da yakalanabilsin.
    words = [re.escape(w) for w in re.split(r"[\s\-_]+", _norm(term)) if w]
    if not words:
        return re.compile(r"(?!)")
    # Ayraç isteğe bağlı: "de-escalation", "de escalation", "deescalation".
    body = r"[\s\-_]*".join(words)
    # Bileşik sözcükte ayraç tamamen kaybolabilir: "deescalation".
    if len(words) > 1:
        body = f"(?:{body}|{''.join(words)})"
    return re.compile(rf"\b{body}\b", re.IGNORECASE)


def concept_terms(plan: Dict[str, Any]) -> List[str]:
    terms = plan.get("anchor_terms") or []
    if isinstance(terms, str):
        terms = [terms]
    return [str(t).strip() for t in terms if str(t).strip()]


def check_dictionary(plan: Dict[str, Any], anchors: List[str]) -> Dict[str, Any]:
    haystack = _norm(
        " ".join(
            str(term)
            for section in plan.get("sections") or []
            for term in (section.get("search_terms") or [])
        )
        + " "
        + " ".join(str(s.get("heading") or "") for s in plan.get("sections") or [])
    )
    missing = [a for a in anchors if _norm(a) not in haystack]
    return {
        "ok": not missing,
        "anchors": anchors,
        "missing_from_search_terms": missing,
        "note": (
            "Eksik anchor terim, toplama aşamasında o kavramın hiç aranmayacağı "
            "anlamına gelir."
        ),
    }


def check_corpus(anchors: List[str], pdf_dir: Optional[Path]) -> Dict[str, Any]:
    if pdf_dir is None or not pdf_dir.is_dir():
        return {"ok": None, "note": "PDF klasörü verilmedi; külliyat denetimi atlandı."}
    try:
        import pymupdf
    except ImportError:
        return {"ok": None, "note": "PyMuPDF kurulu değil; külliyat denetimi atlandı."}

    patterns = [(anchor, _variant_pattern(anchor)) for anchor in anchors]
    per_anchor: Dict[str, Dict[str, Any]] = {
        anchor: {"files": 0, "hits": 0, "examples": []} for anchor in anchors
    }
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    for pdf in pdfs:
        try:
            doc = pymupdf.open(pdf)
        except Exception:  # noqa: BLE001
            continue
        try:
            text = "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
        for anchor, pattern in patterns:
            found = len(pattern.findall(text))
            if found:
                row = per_anchor[anchor]
                row["files"] += 1
                row["hits"] += found
                if len(row["examples"]) < 5:
                    row["examples"].append(pdf.name)

    total = len(pdfs)
    results = {}
    problems = []
    for anchor, row in per_anchor.items():
        ratio = (row["files"] / total) if total else 0.0
        effective = anchors[0] if anchors else anchor
        threshold = MIN_CORPUS_RATIO if anchor == effective else 0.0
        ok = ratio >= threshold
        results[anchor] = {**row, "ratio": round(ratio, 3), "ok": ok}
        if not ok:
            problems.append(
                f"'{anchor}' yalnızca {row['files']}/{total} PDF'te geçiyor "
                f"(%{ratio * 100:.0f} < %{threshold * 100:.0f}). Külliyat bu "
                "kavramı taşımıyor."
            )
    return {
        "ok": not problems,
        "pdf_total": total,
        "per_anchor": results,
        "problems": problems,
        "note": (
            "Külliyatta anchor terim yoksa taslak o kavramı hiç kuramaz; "
            "akış 3'e dönüp kavram terimiyle arama yapılmalı."
        ),
    }


def check_pool(
    anchors: List[str],
    pool: Optional[Dict[str, Any]],
    assigned: Optional[set[str]],
    rejections: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if pool is None:
        return {"ok": None, "note": "Havuz verilmedi; seçim denetimi atlandı."}
    records = pool.get("records") or pool.get("candidates") or []
    assigned = assigned or set()
    rejections = rejections or {}
    patterns = [_variant_pattern(a) for a in anchors]

    matches = []
    for record in records:
        if not isinstance(record, dict):
            continue
        doi = str(record.get("doi") or "").strip().lower()
        haystack = f"{record.get('title') or ''} {record.get('abstract') or ''}"
        if not any(p.search(haystack) for p in patterns):
            continue
        matches.append(
            {
                "doi": doi,
                "title": record.get("title"),
                "year": record.get("year"),
                "quartile": record.get("quartile"),
                "citations": record.get("cited_by") or record.get("citations"),
                "assigned": doi in assigned,
                "rejection_reason": rejections.get(doi),
            }
        )

    dropped = [m for m in matches if not m["assigned"] and not m["rejection_reason"]]
    return {
        "ok": not dropped,
        "matches": matches,
        "dropped_without_reason": dropped,
        "note": (
            "Anchor terim geçen kayıt havuzdaysa ve atanmadıysa gerekçesi "
            "yazılmalı; aksi hâlde kavram çekirdeği sessizce dışarıda kalır."
        ),
    }


def analyse(
    plan: Dict[str, Any],
    pdf_dir: Optional[Path] = None,
    pool: Optional[Dict[str, Any]] = None,
    assigned: Optional[set[str]] = None,
    rejections: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    anchors = concept_terms(plan)
    dictionary = check_dictionary(plan, anchors)
    corpus = check_corpus(anchors, pdf_dir)
    selection = check_pool(anchors, pool, assigned, rejections)

    failures = []
    if not anchors:
        failures.append(
            "Plan `anchor_terms` içermiyor. Bölümün kavramsal çekirdeğinin "
            "literatürdeki adı yazılmadan kavram kapsaması doğrulanamaz."
        )
    if dictionary["missing_from_search_terms"]:
        failures.extend(
            f"'{term}' plan search_terms içinde yok."
            for term in dictionary["missing_from_search_terms"]
        )
    if corpus.get("problems"):
        failures.extend(corpus["problems"])
    if selection.get("dropped_without_reason"):
        failures.extend(
            f"{row['doi']} anchor terim içeriyor ama atanmadı ve gerekçesi yok."
            for row in selection["dropped_without_reason"]
        )

    return {
        "schema": SCHEMA_ID,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project": plan.get("project"),
        "title": plan.get("title"),
        "anchor_terms": anchors,
        "dictionary": dictionary,
        "corpus": corpus,
        "selection": selection,
        "ok": not failures,
        "failures": failures,
        "min_corpus_ratio": MIN_CORPUS_RATIO,
    }


def render_html(report: Dict[str, Any]) -> str:
    def badge(ok: Optional[bool]) -> str:
        if ok is None:
            return '<span class="badge skip">atlandı</span>'
        return (
            '<span class="badge ok">geçti</span>'
            if ok
            else '<span class="badge bad">kaldı</span>'
        )

    anchors = "".join(f"<code>{esc(a)}</code> " for a in report["anchor_terms"]) or (
        '<span class="muted">tanımlı değil</span>'
    )

    dict_missing = report["dictionary"]["missing_from_search_terms"]
    dict_rows = "".join(f"<li><code>{esc(t)}</code></li>" for t in dict_missing) or (
        '<li class="muted">Eksik yok.</li>'
    )

    corpus = report["corpus"]
    corpus_rows = ""
    if corpus.get("per_anchor"):
        for anchor, row in corpus["per_anchor"].items():
            corpus_rows += (
                f'<tr><td><code>{esc(anchor)}</code></td>'
                f'<td class="num">{row["files"]}/{corpus["pdf_total"]}</td>'
                f'<td class="num">%{row["ratio"] * 100:.0f}</td>'
                f'<td class="num">{row["hits"]}</td>'
                f'<td>{"✅" if row["ok"] else "❌"}</td></tr>'
            )

    sel = report["selection"]
    sel_rows = ""
    for row in sel.get("matches") or []:
        status = (
            "atanmış"
            if row["assigned"]
            else (f"reddedildi: {row['rejection_reason']}" if row["rejection_reason"] else "ATANMADI")
        )
        cls = "ok" if row["assigned"] or row["rejection_reason"] else "bad"
        sel_rows += (
            f'<tr class="{cls}"><td><code>{esc(row["doi"])}</code></td>'
            f'<td>{esc((row.get("title") or "")[:90])}</td>'
            f'<td class="num">{esc(row.get("year"))}</td>'
            f'<td class="num">{esc(row.get("quartile"))}</td>'
            f"<td>{esc(status)}</td></tr>"
        )
    if not sel_rows:
        sel_rows = '<tr><td colspan="5" class="muted">Anchor terim içeren kayıt bulunamadı.</td></tr>'

    failures = "".join(f"<li>{esc(f)}</li>" for f in report["failures"]) or (
        '<li class="muted">Sorun bulunmadı.</li>'
    )

    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kavram kapsamı — {esc(report.get("title") or "")}</title>
<style>
:root{{--ink:#202833;--muted:#5b6b7b;--line:#d9e0e7;--soft:#f4f7fa;
--ok:#1e7d4f;--bad:#b3261e}}
*{{box-sizing:border-box}}body{{max-width:980px;margin:0 auto;padding:2rem 1.2rem 4rem;
color:var(--ink);font:16px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif}}
h1{{font-size:1.4rem;line-height:1.25}}.muted{{color:var(--muted);font-size:.88rem}}
.card{{border:1px solid var(--line);border-radius:9px;padding:1rem 1.1rem;margin:1rem 0;background:#fff}}
.card header{{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap}}
.card h2{{font-size:1rem;margin:0}}
.badge{{font-size:.72rem;font-weight:700;border-radius:999px;padding:.15rem .5rem}}
.badge.ok{{background:#e2f4ea;color:var(--ok)}}.badge.bad{{background:#fde8e6;color:var(--bad)}}
.badge.skip{{background:var(--soft);color:var(--muted)}}
code{{background:var(--soft);border:1px solid var(--line);border-radius:4px;padding:.05rem .3rem;font-size:.85rem}}
table{{width:100%;border-collapse:collapse;font-size:.85rem;margin:.6rem 0}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .45rem;text-align:left}}
th{{color:var(--muted);font-size:.72rem;text-transform:uppercase}}td.num{{text-align:right;white-space:nowrap}}
tr.bad td{{background:#fff6f5}}
ul.fail{{background:#fde8e6;border:1px solid #f3c9c4;border-radius:8px;padding:1rem 1rem 1rem 2rem}}
ol.chain{{font-size:.88rem;color:var(--muted)}}
</style></head><body>
<h1>Kavram kapsamı denetimi</h1>
<p class="muted">{esc(report.get("title") or "")} · {esc(report.get("project") or "")}</p>
<p><strong>Anchor terimler:</strong> {anchors}</p>

<ol class="chain">
<li>Anchor terim planın <code>search_terms</code> alanında mı?</li>
<li>İndirilen PDF'lerde anchor terim geçiyor mu?</li>
<li>Havuzda anchor terim içeren kayıt atandı mı?</li>
</ol>

<div class="card"><header><h2>1 · Sözlük</h2>{badge(report["dictionary"]["ok"])}</header>
<ul>{dict_rows}</ul>
<p class="muted">{esc(report["dictionary"]["note"])}</p></div>

<div class="card"><header><h2>2 · Külliyat</h2>{badge(corpus.get("ok"))}</header>
{'<table><thead><tr><th>Terim</th><th>PDF</th><th>Oran</th><th>Geçiş</th><th></th></tr></thead><tbody>' + corpus_rows + '</tbody></table>' if corpus_rows else ''}
<p class="muted">{esc(corpus.get("note") or "")}</p></div>

<div class="card"><header><h2>3 · Seçim</h2>{badge(sel.get("ok"))}</header>
<table><thead><tr><th>DOI</th><th>Başlık</th><th>Yıl</th><th>Q</th><th>Durum</th></tr></thead>
<tbody>{sel_rows}</tbody></table>
<p class="muted">{esc(sel.get("note") or "")}</p></div>

<div class="card"><header><h2>Sonuç</h2>{badge(report["ok"])}</header>
<ul class="fail">{failures}</ul></div>
</body></html>"""


def load_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    if Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Anchor terim zincirini denetler: sözlük -> külliyat -> seçim. "
            "Kavramsal çekirdek aramada yoksa hata verir."
        )
    )
    parser.add_argument("plan", type=Path, help="Yazım planı JSON")
    parser.add_argument("--project-root", type=Path, help="Proje kökü (yolları çözer)")
    parser.add_argument("--workflow", default="2", help="Akış numarası (PDF klasörü için)")
    parser.add_argument("--fulltext-dir", type=Path, help="PDF klasörü")
    parser.add_argument("--pool", type=Path, help="DOI havuzu JSON")
    parser.add_argument("--assignments", type=Path, help="Atama dosyası {S1: [doi]}")
    parser.add_argument("--rejections", type=Path, help="Reddedilen DOI gerekçeleri {doi: neden}")
    parser.add_argument("-o", "--output-dir", type=Path, help="Çıktı klasörü")
    parser.add_argument("--check", action="store_true", help="Yalnızca özet; dosya yazma")
    parser.add_argument("--force", action="store_true")
    add_timestamp_argument(parser)
    args = parser.parse_args(argv)

    if not args.plan.is_file():
        print(f"Hata: plan bulunamadı: {args.plan}", file=sys.stderr)
        return 2
    plan = json.loads(args.plan.read_text(encoding="utf-8"))

    pdf_dir = args.fulltext_dir
    if pdf_dir is None and args.project_root:
        pdf_dir = fulltext_dir(args.project_root.expanduser().resolve(), str(args.workflow))

    pool = load_json(args.pool)
    if pool is None and args.project_root:
        candidate = workflow_dir(args.project_root.expanduser().resolve(), "3") / "00_doi_havuzu.json"
        pool = load_json(candidate)

    assigned: set[str] = set()
    assignments_path = args.assignments
    if assignments_path is None and args.project_root:
        assignments_path = workflow_dir(args.project_root.expanduser().resolve(), "3") / "00_atamalar.json"
    assignments = load_json(assignments_path)
    if assignments:
        assigned = {
            str(doi).strip().lower()
            for dois in assignments.values()
            for doi in dois
            if doi
        }

    rejections = load_json(args.rejections) or {}

    report = analyse(
        plan,
        pdf_dir=pdf_dir if pdf_dir and Path(pdf_dir).is_dir() else None,
        pool=pool,
        assigned=assigned,
        rejections=rejections,
    )

    if args.check:
        print(
            f"{'OK' if report['ok'] else 'KALDI'}: anchor={len(report['anchor_terms'])}, "
            f"sözlük_eksik={len(report['dictionary']['missing_from_search_terms'])}, "
            f"külliyat_sorun={len(report['corpus'].get('problems') or [])}, "
            f"seçim_boşluk={len(report['selection'].get('dropped_without_reason') or [])}"
        )
        for failure in report["failures"]:
            print(f"  - {failure}", file=sys.stderr)
        return 0 if report["ok"] else 1

    out_dir = args.output_dir or args.plan.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    target = add_timestamp(out_dir / f"{OUTPUT_STEM}.json", enabled=args.timestamp)
    result = write_versioned_pair(
        target,
        {
            ".json": json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            ".html": render_html(report),
        },
        enabled=args.timestamp,
        force=args.force,
    )
    print(f"Yazıldı: {result['path']}")
    print(f"Yazıldı: {result['path'].with_suffix('.html')}")
    if report["ok"]:
        print("Kavram kapsamı: GEÇTİ")
        return 0
    print("Kavram kapsamı: KALDI", file=sys.stderr)
    for failure in report["failures"]:
        print(f"  - {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
