#!/usr/bin/env python3
"""Yazım planı ↔ kaynak atama matrisi üreticisi — akış 3.

Her alt başlığa, havuzdaki adaylardan en uygun kaynakları atar ve
karşılanamayan kanıt ihtiyaçlarını boşluk olarak raporlar.

Eşleştirme şeffaftır: alt başlık metni (başlık + amaç) ile aday metni
(başlık + özet) arasındaki sözcük örtüşmesi + istenen çalışma türü bonusu.
Dergi quartile'ı küçük bir bonus verir; atıf sayısı yalnızca eşitlik bozucudur.
Bu bir "kanıt" değil, **ön atama** önerisidir; akış 4'te sayfa doğrulaması
yapılmadan kanıt sayılmaz.

Kullanım:
    python3 scripts/build_assignment_matrix.py plan.json adaylar.json \\
        -o <proje-kökü>/03_kaynak_kesfi
    python3 scripts/build_assignment_matrix.py plan.json adaylar.json --check
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from project_layout import workflow_dir
except ImportError:
    from scripts.project_layout import workflow_dir

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "has", "have", "had", "not", "but", "its", "into", "onto", "about", "over",
    "under", "between", "among", "their", "there", "these", "those", "than",
    "then", "when", "where", "which", "while", "who", "whom", "whose", "will",
    "would", "can", "could", "should", "may", "might", "does", "did", "how",
    "what", "why", "also", "such", "more", "most", "some", "any", "all", "one",
    "two", "use", "used", "using", "based", "study", "studies", "research",
    "bir", "ve", "ile", "için", "olan", "olarak", "bu", "şu", "da", "de",
    "üzerine", "gibi", "daha", "çok", "en", "her", "veya", "ya", "ki", "ama",
}

DESIGN_PATTERNS: List[Tuple[str, str]] = [
    (r"\bmeta[- ]analys[ie]s\b|\bmeta[- ]analysis\b", "meta_analysis"),
    (r"\bsystematic review\b", "systematic_review"),
    (r"\brandomi[sz]ed controlled\b|\brandomi[sz]ed trial\b|\bcluster[- ]randomi[sz]ed\b|\brct\b", "rct"),
    (r"\bquasi[- ]experimental\b", "quasi_experimental"),
    (r"\bcohort\b|\blongitudinal\b|\bprospective\b", "cohort"),
    (r"\bcross[- ]sectional\b|\bsurvey\b", "cross_sectional"),
    (r"\bqualitative\b|\bfocus group\b|\binterview", "qualitative"),
]

QUARTILE_BONUS = {"Q1": 0.06, "Q2": 0.04, "Q3": 0.02, "Q4": 0.0}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", _normalize(value))
        if len(token) > 2 and token not in STOPWORDS
    }


def detect_design(item: Dict[str, Any]) -> str:
    haystack = " ".join(
        str(item.get(key) or "") for key in ("title", "abstract", "type")
    )
    for pattern, label in DESIGN_PATTERNS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return label
    if str(item.get("type") or "").lower() in {"review", "preprint"}:
        return "systematic_review" if item.get("type") == "review" else "any"
    return "any"


def _relevance(section_tokens: set[str], item: Dict[str, Any]) -> float:
    if not section_tokens:
        return 0.0
    text = _tokens(
        " ".join(
            str(item.get(key) or "") for key in ("title", "abstract", "journal")
        )
    )
    if not text:
        return 0.0
    overlap = len(section_tokens & text) / len(section_tokens)
    title_overlap = len(section_tokens & _tokens(item.get("title"))) / len(section_tokens)
    return round(0.6 * overlap + 0.4 * title_overlap, 4)


def _citation_tiebreak(item: Dict[str, Any]) -> float:
    try:
        count = int(item.get("citations") or 0)
    except (TypeError, ValueError):
        count = 0
    return round(min(1.0, math.log10(count + 1) / 4.0), 4)


def load_plan(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        raise ValueError("Yazım planı 'sections' listesi içermeli.")
    return data


def load_pool(paths: List[Path]) -> List[Dict[str, Any]]:
    """Aday havuzu: fulltext listesi JSON'ları veya düz aday listesi."""
    pool: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("candidates") if isinstance(data, dict) else data
        for item in items or []:
            if not isinstance(item, dict):
                continue
            doi = str(item.get("doi") or "").strip().lower()
            if not doi:
                continue
            entry = pool.setdefault(
                doi,
                {
                    "doi": doi,
                    "title": item.get("title"),
                    "abstract": item.get("abstract"),
                    "journal": item.get("journal"),
                    "year": item.get("year"),
                    "quartile": item.get("quartile"),
                    "citations": item.get("citations"),
                    "open_access": item.get("open_access"),
                    "type": item.get("type"),
                    "score": item.get("score"),
                },
            )
            if not entry.get("abstract") and item.get("abstract"):
                entry["abstract"] = item["abstract"]
    return list(pool.values())


def assign(
    plan: Dict[str, Any],
    pool: List[Dict[str, Any]],
    max_per_section: int = 4,
    min_score: float = 0.12,
) -> Dict[str, Any]:
    designs = {item["doi"]: detect_design(item) for item in pool}
    sections_out: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []

    for section in plan["sections"]:
        if not isinstance(section, dict):
            continue
        section_text = f"{section.get('heading') or ''} {section.get('purpose') or ''}"
        section_tokens = _tokens(section_text)
        needs = [
            need
            for need in (section.get("evidence_needs") or [])
            if isinstance(need, dict) and need.get("design")
        ]
        wanted = {str(need["design"]) for need in needs if need["design"] != "any"}

        scored: List[Dict[str, Any]] = []
        for item in pool:
            relevance = _relevance(section_tokens, item)
            if relevance < min_score:
                continue
            design = designs.get(item["doi"], "any")
            design_bonus = 0.15 if design in wanted else 0.0
            quartile_bonus = QUARTILE_BONUS.get(
                str(item.get("quartile") or "").upper(), 0.0
            )
            total = round(
                relevance + design_bonus + quartile_bonus
                + 0.02 * _citation_tiebreak(item),
                4,
            )
            scored.append(
                {
                    "doi": item["doi"],
                    "title": item.get("title"),
                    "journal": item.get("journal"),
                    "year": item.get("year"),
                    "quartile": item.get("quartile"),
                    "citations": item.get("citations"),
                    "open_access": item.get("open_access"),
                    "design": design,
                    "relevance": relevance,
                    "design_matched": design in wanted,
                    "score": total,
                }
            )
        scored.sort(key=lambda entry: (-entry["score"], entry["doi"]))

        assigned: List[Dict[str, Any]] = []
        used: set[str] = set()
        # Önce karşılanmamış kanıt ihtiyaçları için birer uygun tasarım seç.
        for need in needs:
            design = str(need["design"])
            if design == "any":
                continue
            for entry in scored:
                if entry["design"] == design and entry["doi"] not in used:
                    assigned.append(entry)
                    used.add(entry["doi"])
                    break
        # Kalan slotları en yüksek skorla doldur.
        for entry in scored:
            if len(assigned) >= max_per_section:
                break
            if entry["doi"] in used:
                continue
            assigned.append(entry)
            used.add(entry["doi"])

        covered_designs = {entry["design"] for entry in assigned}
        missing = [
            str(need["design"])
            for need in needs
            if need["design"] != "any"
            and str(need["design"]) not in covered_designs
        ]
        status = "covered" if assigned and not missing else ("gap" if not assigned else "covered")
        if missing or not assigned:
            status = "gap"
            gaps.append(
                {
                    "section_id": section.get("id"),
                    "heading": section.get("heading"),
                    "missing": missing,
                    "note": (
                        "Bu alt başlık için istenen kanıt türü bulunamadı."
                        if missing
                        else "Bu alt başlıkla yeterince örtüşen kaynak bulunamadı."
                    ),
                }
            )
        sections_out.append(
            {
                "section_id": section.get("id"),
                "heading": section.get("heading"),
                "target_words": section.get("target_words"),
                "evidence_needs": needs,
                "assigned": assigned,
                "missing_designs": missing,
                "status": status,
            }
        )

    assigned_dois = sorted(
        {entry["doi"] for section in sections_out for entry in section["assigned"]}
    )
    return {
        "schema": "assignment-matrix/1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project": plan.get("project"),
        "title": plan.get("title"),
        "genre": plan.get("genre"),
        "pool_size": len(pool),
        "sections_total": len(sections_out),
        "assigned_doi_total": len(assigned_dois),
        "gap_sections": len(gaps),
        "sections": sections_out,
        "evidence_gaps": gaps,
        "assigned_dois": assigned_dois,
        "notes": [
            "Atama, alt başlık metni ile aday başlık/özet örtüşmesine dayanır; kanıt değildir.",
            "Akış 4'te her iddia sayfa numarasıyla doğrulanmadan kanıt sayılmaz.",
            "Yalnızca atanmış DOI'lerin PDF'leri indirilmelidir.",
        ],
    }


def render_html(matrix: Dict[str, Any]) -> str:
    rows = []
    for section in matrix["sections"]:
        dois = "".join(
            f'<li><a href="https://doi.org/{esc(entry["doi"])}" target="_blank" rel="noopener">'
            f'{esc(entry["doi"])}</a> <span class="muted">'
            f'{esc(entry["design"])} · skor {esc(entry["score"])}'
            f'{" · Q" + esc(entry["quartile"]) if entry.get("quartile") else ""}</span></li>'
            for entry in section["assigned"]
        ) or '<li class="muted">Kaynak atanamadı.</li>'
        badge = "gap" if section["status"] == "gap" else "covered"
        rows.append(
            f'<article class="section {badge}">'
            f'<header><span class="sid">{esc(section["section_id"])}</span>'
            f'<h3>{esc(section["heading"])}</h3>'
            f'<span class="badge {badge}">'
            f'{"Kanıt boşluğu" if badge == "gap" else "Atandı"}</span>'
            f'<span class="words">{len(section["assigned"])} kaynak</span></header>'
            f'<ul>{dois}</ul>'
            + (
                f'<p class="gap">Eksik kanıt türü: {esc(", ".join(section["missing_designs"]))}</p>'
                if section["missing_designs"]
                else ""
            )
            + "</article>"
        )
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atama matrisi — {esc(matrix.get("title"))}</title>
<style>
body {{ margin:0; background:#f5f7f9; color:#16212b; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
header.hero {{ background:#0b2540; color:#fff; padding:24px 22px; }}
main {{ max-width:1000px; margin:0 auto; padding:20px 22px 40px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:16px 0; }}
.stat {{ background:#fff; border:1px solid #dce3ea; border-radius:10px; padding:12px 14px; }}
.stat .num {{ font-size:22px; font-weight:700; display:block; }}
.section {{ background:#fff; border:1px solid #dce3ea; border-radius:10px; padding:14px 16px; margin:12px 0; }}
.section.gap {{ border-left:4px solid #b3261e; }}
.section.covered {{ border-left:4px solid #1e7d4f; }}
.section header {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
.section h3 {{ font-size:16px; margin:0; }}
.sid {{ font-family:ui-monospace,monospace; font-size:12px; color:#5b6b7b; }}
.words {{ margin-left:auto; font-size:12px; color:#5b6b7b; }}
.badge {{ border-radius:999px; padding:2px 10px; font-size:11.5px; font-weight:700; }}
.badge.covered {{ background:#e2f4ea; color:#1e7d4f; }}
.badge.gap {{ background:#fde8e6; color:#b3261e; }}
.muted {{ color:#5b6b7b; font-size:12.5px; }}
.gap {{ background:#fff4f2; padding:8px 10px; border-radius:4px; }}
ul {{ margin:8px 0 0; padding-left:20px; font-size:13.5px; }}
a {{ color:#0b5cad; }}
footer {{ max-width:1000px; margin:0 auto; padding:0 22px 36px; color:#5b6b7b; font-size:12.5px; }}
@media print {{ body {{ background:#fff; }} header.hero {{ background:#fff; color:#000; border-bottom:2px solid #000; }} .section {{ break-inside:avoid; }} }}
</style></head><body>
<header class="hero"><div style="text-transform:uppercase;letter-spacing:.08em;font-size:12px;opacity:.8">Kaynak atama matrisi · Akış 3</div>
<h1>{esc(matrix.get("title"))}</h1><p>Havuz: {matrix["pool_size"]} DOI · Atanan: {matrix["assigned_doi_total"]} DOI</p></header>
<main>
<section class="stats">
  <div class="stat"><span class="num">{matrix["sections_total"]}</span><small>Alt başlık</small></div>
  <div class="stat"><span class="num">{matrix["assigned_doi_total"]}</span><small>Atanmış DOI</small></div>
  <div class="stat"><span class="num">{matrix["gap_sections"]}</span><small>Kanıt boşluğu</small></div>
  <div class="stat"><span class="num">{matrix["pool_size"]}</span><small>Havuz</small></div>
</section>
{"".join(rows)}
</main>
<footer>Bu matris ön atamadır; kanıt değildir. Yalnızca atanmış DOI'lerin PDF'leri indirilir;
akış 4'te her iddia sayfa numarasıyla doğrulanır.</footer>
</body></html>"""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Yazım planına göre kaynak atama matrisi üretir."
    )
    parser.add_argument("plan", type=Path, help="Yazım planı JSON")
    parser.add_argument(
        "pool",
        type=Path,
        nargs="+",
        help="Aday havuzu: fulltext listesi JSON'u veya aday listesi.",
    )
    parser.add_argument("-o", "--output-dir", type=Path, help="Çıktı klasörü")
    parser.add_argument("--max-per-section", type=int, default=4)
    parser.add_argument("--min-score", type=float, default=0.12)
    parser.add_argument("--check", action="store_true", help="Yalnızca doğrula/özetle")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--update-plan",
        action="store_true",
        help="Atamaları yazım planı JSON'una geri yaz (assigned_dois/status).",
    )
    parser.add_argument(
        "--no-timestamp", dest="timestamp", action="store_false",
        help="Sabit dosya adı kullan.",
    )
    args = parser.parse_args(argv)

    if not args.plan.is_file():
        print(f"Hata: plan bulunamadı: {args.plan}", file=sys.stderr)
        return 2
    try:
        plan = load_plan(args.plan)
        pool = load_pool([path for path in args.pool if path.is_file()])
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2
    if not pool:
        print("Hata: aday havuzu boş.", file=sys.stderr)
        return 2

    matrix = assign(plan, pool, args.max_per_section, args.min_score)
    print(
        f"Alt başlık: {matrix['sections_total']} | atanan DOI: "
        f"{matrix['assigned_doi_total']} | boşluk: {matrix['gap_sections']}"
    )
    for gap in matrix["evidence_gaps"]:
        print(f"  BOŞLUK {gap['section_id']}: {gap['heading']} ({gap['note']})")

    if args.check:
        return 0

    output_dir = (args.output_dir or workflow_dir(args.plan.parent.parent, "3")).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    from output_naming import write_versioned_pair

    json_text = json.dumps(matrix, ensure_ascii=False, indent=2) + "\n"
    html_text = render_html(matrix)
    try:
        result = write_versioned_pair(
            output_dir / "00_atama_matrisi.json",
            {".json": json_text, ".html": html_text},
            enabled=args.timestamp,
            force=args.force,
        )
    except FileExistsError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2

    json_path = result["path"]
    html_path = json_path.with_suffix(".html")
    if result["status"] == "unchanged":
        print(f"Değişiklik yok; mevcut sürüm korundu: {json_path}")
    else:
        print(f"Yazıldı: {json_path}")
        print(f"Yazıldı: {html_path}")
        if result["archived"]:
            print(f"Eski sürümler arşivlendi: {len(result['archived'])} dosya")

    if args.update_plan:
        by_id = {section["section_id"]: section for section in matrix["sections"]}
        for section in plan.get("sections") or []:
            if not isinstance(section, dict):
                continue
            match = by_id.get(section.get("id"))
            if not match:
                continue
            section["assigned_dois"] = [entry["doi"] for entry in match["assigned"]]
            section["status"] = match["status"]
            if match["missing_designs"]:
                section["gap_note"] = (
                    "Eksik kanıt türü: " + ", ".join(match["missing_designs"])
                )
        plan["evidence_gaps"] = matrix["evidence_gaps"]
        args.plan.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Plan güncellendi: {args.plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
