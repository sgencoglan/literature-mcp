#!/usr/bin/env python3
"""Akış 4 — kanıt yetersizliği talebi üretir.

Akış 4'te taslak yazılırken bir alt başlık için yeterli kanıt bulunamazsa model
sessizce davranmaz. Bu betik, "hangi alt başlıkta ne eksik, hangi sorgularla
aranmalı" sorusunu makine okunabilir bir talebe çevirir.

İki ayrı durum vardır ve ikisi karıştırılmamalıdır:

1. **Kaynak eksik, alt başlık geçerli** — yeni hedefli arama ve *ek* fulltext
   listesi üretilir; plan değişmez. Bu betik bu durumu üretir.
2. **Alt başlık sorunlu** — çok geniş, bölünmeli ya da birleştirilmeli. Bu bir
   plan değişikliğidir ve `plan_status: approved` kapısı gereği kullanıcıya
   sorulmadan yapılamaz. Betik bu durumu `plan_change_required` olarak
   işaretler, kendisi değiştirmez.

Kullanım:
    python3 scripts/build_evidence_gap_request.py plan.json taslak.json \\
        -o 03_kaynak_kesfi --min-words-ratio 0.75
    python3 scripts/build_evidence_gap_request.py plan.json --check
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
    from fulltext_reading import reading_advice, reading_gate, render_reading
    from output_naming import (
        add_timestamp,
        add_timestamp_argument,
        write_versioned_pair,
    )
except ImportError:
    from scripts.fulltext_reading import reading_advice, reading_gate, render_reading
    from scripts.output_naming import (
        add_timestamp,
        add_timestamp_argument,
        write_versioned_pair,
    )

SCHEMA_ID = "evidence-gap-request/1"
OUTPUT_STEM = "02_kanit_boslugu_talebi"

# Bu orandan az yazılabilen alt başlık "kanıt yetersiz" sayılır.
DEFAULT_MIN_WORDS_RATIO = 0.75


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def _tokens(value: Any) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _normalize(value)) if len(t) > 2}


def draft_paragraphs(draft: Dict[str, Any]) -> List[str]:
    intro = draft.get("intro") or {}
    paragraphs = intro.get("paragraphs") or [] if isinstance(intro, dict) else []
    result: List[str] = []
    for item in paragraphs:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            if item.get("text"):
                result.append(str(item["text"]))
            else:
                result.extend(
                    str(seg.get("text") or "")
                    for seg in item.get("segments") or []
                    if isinstance(seg, dict)
                )
    return [p for p in result if p.strip()]


def split_sections(paragraphs: List[str]) -> List[Dict[str, Any]]:
    """Taslağı başlıklara böl (varsa markdown başlıkları)."""
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for paragraph in paragraphs:
        heading = paragraph.strip()
        if heading.startswith("#"):
            current = {
                "heading": heading.lstrip("#").strip(),
                "paragraphs": [],
            }
            sections.append(current)
            continue
        if current is None:
            current = {"heading": "(giriş)", "paragraphs": []}
            sections.append(current)
        current["paragraphs"].append(paragraph)
    return sections


def _words(text: str) -> int:
    return len(text.split())


def _pdf_stem(doi: str) -> str:
    """İndiricinin ürettiği PDF dosya adının kökü (uzantısız).

    ``available_pdfs`` PDF klasöründeki dosya köklerini taşır, DOI'yi değil;
    karşılaştırma bu dönüşümle yapılmalı.
    """
    text = unicodedata.normalize("NFKD", str(doi or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9.\-]+", "", text).strip(".-")


def _suggest_queries(section: Dict[str, Any]) -> List[str]:
    """Alt başlık için hedefli arama önerileri üret."""
    terms = section.get("search_terms") or []
    heading = str(section.get("heading") or "")
    queries: List[str] = []
    if terms:
        # 2–4 terimli kombinasyonlar: tek terim çok geniş, hepsi birlikte çok dar.
        words = [str(t).strip() for t in terms if str(t).strip()]
        for size in (3, 2):
            for start in range(0, min(len(words), 8), size):
                chunk = words[start : start + size]
                if len(chunk) == size:
                    query = " ".join(chunk)
                    if query not in queries:
                        queries.append(query)
            if len(queries) >= 4:
                break
    else:
        # search_terms yoksa başlıktan türet.
        base = " ".join(sorted(_tokens(heading))[:5])
        if base:
            queries.append(base)
    return queries[:4]


def analyse(
    plan: Dict[str, Any],
    draft: Optional[Dict[str, Any]],
    min_words_ratio: float = DEFAULT_MIN_WORDS_RATIO,
) -> Dict[str, Any]:
    paragraphs = draft_paragraphs(draft) if draft else []
    actual = split_sections(paragraphs)
    total_words = sum(_words(p) for p in paragraphs)
    actual_by_tokens = [
        (_tokens(section.get("heading")), section) for section in actual
    ]

    gaps: List[Dict[str, Any]] = []
    for section in plan.get("sections") or []:
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id") or "")
        heading = str(section.get("heading") or "")
        target = int(section.get("target_words") or 0)
        section_tokens = _tokens(heading)

        # En iyi eşleşen taslak bölümünü bul.
        best = None
        best_score = 0.0
        for tokens, candidate in actual_by_tokens:
            if not tokens or not section_tokens:
                continue
            overlap = len(tokens & section_tokens) / len(section_tokens)
            if overlap > best_score:
                best_score = overlap
                best = candidate
        written = _words("\n".join(best["paragraphs"])) if best and best_score >= 0.3 else 0

        ratio = (written / target) if target else 1.0
        if ratio >= min_words_ratio:
            continue

        # Kanıt yetersizliği mi, plan sorunu mu?
        needs = [
            str(need.get("design"))
            for need in (section.get("evidence_needs") or [])
            if isinstance(need, dict) and need.get("design") not in (None, "", "any")
        ]
        assigned = section.get("assigned_dois") or []
        kind = "evidence_shortfall"
        reason = (
            f"Hedef {target} kelime, yazılan {written} kelime (%{ratio * 100:.0f}). "
            "Alt başlık geçerli; kaynak havuzu genişletilmeli."
        )
        if not assigned:
            kind = "plan_change_required"
            reason = (
                "Bu alt başlığa hiç kaynak atanmamış. Atama olmadan akış 4 "
                "başlamamalıydı; önce akış 3'te atama yapılmalı."
            )
        elif target and target > 1200 and len(assigned) <= 2:
            kind = "plan_change_required"
            reason = (
                f"Hedef {target} kelimeye karşılık yalnızca {len(assigned)} kaynak var. "
                "Alt başlık bölünmeli ya da hedef küçültülmeli; bu bir plan değişikliğidir."
            )

        gaps.append(
            {
                "section_id": sid,
                "heading": heading,
                "status": kind,
                "target_words": target,
                "written_words": written,
                "completion_ratio": round(ratio, 3),
                "assigned_source_count": len(assigned),
                "required_designs": needs,
                "reason": reason,
                "suggested_queries": _suggest_queries(section),
                "needs_user_decision": kind == "plan_change_required",
            }
        )

    plan_changes = [gap for gap in gaps if gap["status"] == "plan_change_required"]
    return {
        "schema": SCHEMA_ID,
        "project": plan.get("project"),
        "title": plan.get("title"),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "plan_status": plan.get("plan_status"),
        "target_total_words": plan.get("target_total_words"),
        "written_total_words": total_words,
        "min_words_ratio": min_words_ratio,
        "summary": {
            "planned_sections": len(plan.get("sections") or []),
            "draft_sections": len(actual),
            "gap_sections": len(gaps),
            "evidence_shortfall": len(gaps) - len(plan_changes),
            "plan_change_required": len(plan_changes),
        },
        "gaps": gaps,
        "next_action": {
            "if_only_evidence_shortfall": (
                "Akış 3'e dön: `suggested_queries` ile ek arama yap, YENİ zaman "
                "damgalı bir fulltext listesi üret (mevcut listeyi ezme), atama "
                "matrisini güncelle ve `plan.evidence_gaps` alanına bu talebi yaz."
            ),
            "if_plan_change_required": (
                "DUR ve kullanıcıya sor. Plan `approved` durumundadır; alt başlığı "
                "bölmek, birleştirmek, hedef kelimeyi değiştirmek veya kapsamı "
                "daraltmak kullanıcı onayı olmadan yapılamaz."
            ),
            "never": [
                "Kanıt varmış gibi yazmak veya iddiayı sayfa numarası olmadan desteklemek.",
                "Mevcut fulltext listesini yeni listeyle ezmek.",
                "Planda olmayan alt başlık eklemek.",
                "Kelime hedefini sessizce düşürmek.",
            ],
        },
    }



# --------------------------------------------------------------------------- #
# Uçuş öncesi denetim (taslak yazılmadan ÖNCE)
# --------------------------------------------------------------------------- #

# Bir kaynağın sayfa doğrulamalı kanıtla destekleyebileceği yaklaşık kelime.
# Bu bir üst sınır değil, gerçekçi bir ortalama: bir ampirik makale genellikle
# 2-4 paragrafı, bir meta-analiz tek bir paragrafı besler.
WORDS_PER_SOURCE = 450

# Tasarım türüne göre kanıt yoğunluğu çarpanı: sentezler tek başına daha çok
# cümle taşır, tek çalışmalar daha az.
DESIGN_DENSITY = {
    "meta_analysis": 1.5,
    "systematic_review": 1.4,
    "rct": 1.0,
    "quasi_experimental": 1.0,
    "cohort": 0.9,
    "cross_sectional": 0.8,
    "qualitative": 0.8,
    "policy_document": 1.1,
    "any": 0.7,
}


def _detect_design(title: str, abstract: str = "") -> str:
    import re as _re

    haystack = f"{title} {abstract}".lower()
    patterns = [
        (r"meta[- ]analys", "meta_analysis"),
        (r"systematic review|scoping review", "systematic_review"),
        (r"quasi[- ]experimental", "quasi_experimental"),
        (r"randomi[sz]ed|\brct\b|cluster[- ]randomi[sz]ed", "rct"),
        (r"policy statement|position statement", "policy_document"),
        (r"cohort|longitudinal", "cohort"),
        (r"cross[- ]sectional|survey|questionnaire", "cross_sectional"),
        (r"qualitative|interview|focus group|thematic", "qualitative"),
    ]
    for pattern, label in patterns:
        if _re.search(pattern, haystack):
            return label
    return "any"


def preflight(
    plan: Dict[str, Any],
    fulltext_list: Optional[Dict[str, Any]] = None,
    available_pdfs: Optional[set[str]] = None,
    min_words_ratio: float = DEFAULT_MIN_WORDS_RATIO,
    evidence_bank: Optional[Dict[str, Any]] = None,
    reading_manifest: Optional[Dict[str, Any]] = None,
    fulltext_root: Optional[Path] = None,
    workflow: str = "4",
) -> Dict[str, Any]:
    """Taslak yazılmadan önce her alt başlığın kanıt kapasitesini ölçer.

    Soru şudur: bu alt başlık, atanmış kaynaklarla hedef kelimeye ulaşabilir mi?
    Yanıt, kaynak sayısı ve tasarım türüne dayalı bir kapasite tahminidir; kesin
    değildir, ama "yazmaya başlamadan önce eksik olduğunu bil" için yeterlidir.
    """
    # ``None`` = PDF durumu bilinmiyor (denetimi atla); boş küme = hiç PDF yok.
    # Tasarım tespiti için en güvenilir kaynak kanıt bankasıdır: tasarım, PDF
    # tam metninden çıkarılır. Tam metin yoksa başlık+abstrakta düşülür.
    design_by_doi: Dict[str, str] = {}
    pages_by_doi: Dict[str, int] = {}
    for source in (evidence_bank or {}).get("sources") or []:
        if not isinstance(source, dict):
            continue
        doi_key = str(source.get("doi") or "").lower()
        if not doi_key:
            continue
        if source.get("design") and source["design"] != "any":
            design_by_doi[doi_key] = str(source["design"])
        if source.get("pages"):
            pages_by_doi[doi_key] = int(source["pages"])

    by_doi: Dict[str, Dict[str, Any]] = {}
    for candidate in (fulltext_list or {}).get("candidates") or []:
        if isinstance(candidate, dict) and candidate.get("doi"):
            by_doi[str(candidate["doi"]).lower()] = candidate

    gaps: List[Dict[str, Any]] = []
    for section in plan.get("sections") or []:
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id") or "")
        heading = str(section.get("heading") or "")
        target = int(section.get("target_words") or 0)
        assigned = [str(d).lower() for d in (section.get("assigned_dois") or [])]

        designs: List[str] = []
        missing_pdf: List[str] = []
        for doi in assigned:
            record = by_doi.get(doi) or {}
            design = design_by_doi.get(doi) or _detect_design(
                str(record.get("title") or ""), str(record.get("abstract") or "")
            )
            designs.append(design)
            if available_pdfs is not None and _pdf_stem(doi) not in available_pdfs:
                missing_pdf.append(doi)

        # Kapasite: her kaynak tasarımına göre ağırlıklı kelime taşır.
        capacity = sum(
            WORDS_PER_SOURCE * DESIGN_DENSITY.get(design, 0.7) for design in designs
        )
        capacity = int(capacity)
        ratio = (capacity / target) if target else 1.0

        needs = [
            str(need.get("design"))
            for need in (section.get("evidence_needs") or [])
            if isinstance(need, dict) and need.get("design") not in (None, "", "any")
        ]
        covered = {design for design in designs if design in needs}
        missing_designs = [design for design in needs if design not in covered]

        if ratio >= min_words_ratio and not missing_designs and not missing_pdf:
            continue

        # Sınıflandırma: kaynak mı eksik, tasarım mı, plan mı?
        if not assigned:
            status = "plan_change_required"
            reason = (
                "Bu alt başlığa hiç kaynak atanmamış. Akış 3 tamamlanmadan "
                "yazmaya başlanmamalı."
            )
        elif ratio < 0.5:
            status = "plan_change_required"
            reason = (
                f"Kanıt kapasitesi hedefin yarısının altında (≈{capacity} / {target} "
                f"kelime, {len(assigned)} kaynak). Alt başlık bölünmeli, hedef "
                "küçültülmeli ya da kapsam daraltılmalı."
            )
        elif target > 1200 and len(assigned) <= 2:
            status = "plan_change_required"
            reason = (
                f"{target} kelimelik alt başlık için {len(assigned)} kaynak var. "
                "Tek kaynakla uzun bölüm yazmak, kanıtı tekrar etmeye yol açar."
            )
        elif ratio < min_words_ratio or missing_designs or missing_pdf:
            status = "evidence_shortfall"
            parts = [f"≈{capacity} / {target} kelime kapasite"]
            if missing_designs:
                parts.append(f"eksik tasarım: {', '.join(missing_designs)}")
            if missing_pdf:
                parts.append(f"{len(missing_pdf)} PDF erişilebilir değil")
            reason = "Alt başlık geçerli, kanıt yetersiz: " + "; ".join(parts) + "."
        else:
            continue

        gaps.append(
            {
                "section_id": sid,
                "heading": heading,
                "status": status,
                "target_words": target,
                "assigned_source_count": len(assigned),
                "estimated_capacity_words": capacity,
                "capacity_ratio": round(ratio, 3),
                "required_designs": needs,
                "missing_designs": missing_designs,
                "missing_pdf_count": len(missing_pdf),
                "reason": reason,
                "suggested_queries": _suggest_queries(section),
                "needs_user_decision": status == "plan_change_required",
            }
        )

    plan_changes = [gap for gap in gaps if gap["status"] == "plan_change_required"]
    gate = reading_gate(reading_manifest, fulltext_root, workflow)
    return {
        "schema": SCHEMA_ID,
        "mode": "preflight",
        "workflow": workflow,
        "reading_gate": gate,
        "reading_manifest": reading_manifest,
        "reading_advice": reading_advice(reading_manifest, plan) if reading_manifest else None,
        "transition_allowed": gate["complete"] and not gaps and plan.get("plan_status") == "approved",
        "project": plan.get("project"),
        "title": plan.get("title"),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "plan_status": plan.get("plan_status"),
        "target_total_words": plan.get("target_total_words"),
        "written_total_words": None,
        "min_words_ratio": min_words_ratio,
        "summary": {
            "planned_sections": len(plan.get("sections") or []),
            "draft_sections": None,
            "gap_sections": len(gaps),
            "evidence_shortfall": len(gaps) - len(plan_changes),
            "plan_change_required": len(plan_changes),
        },
        "gaps": gaps,
        "next_action": {
            "if_only_evidence_shortfall": (
                "Akış 3'e dön: `suggested_queries` ile ek arama yap, YENİ zaman "
                "damgalı bir fulltext listesi üret (mevcut listeyi ezme), atama "
                "matrisini güncelle ve `plan.evidence_gaps` alanına bu talebi yaz. "
                "Sonra taslağa başla."
            ),
            "if_plan_change_required": (
                "YAZMAYA BAŞLAMA. Kullanıcıya sor: alt başlığı bölmek, hedef "
                "kelimeyi küçültmek veya kapsamı daraltmak gerekiyor. Plan "
                "`approved` durumundadır; değişiklik onay ister."
            ),
            "never": [
                "Kanıt varmış gibi yazmak veya iddiayı sayfa numarası olmadan desteklemek.",
                "Mevcut fulltext listesini yeni listeyle ezmek.",
                "Planda olmayan alt başlık eklemek.",
                "Kelime hedefini sessizce düşürmek.",
            ],
        },
    }


def render_html(report: Dict[str, Any]) -> str:
    summary = report["summary"]
    rows = []
    for gap in report["gaps"]:
        badge = "evidence" if gap["status"] == "evidence_shortfall" else "plan"
        label = (
            "Kanıt eksik — akış 3'e dön"
            if badge == "evidence"
            else "Plan değişikliği — kullanıcıya sor"
        )
        queries = "".join(
            f"<li><code>{esc(query)}</code></li>" for query in gap["suggested_queries"]
        ) or '<li class="muted">Sorgu önerisi üretilemedi.</li>'
        rows.append(
            f'<article class="card {badge}">'
            f'<header><span class="sid">{esc(gap["section_id"])}</span>'
            f'<h2>{esc(gap["heading"])}</h2>'
            f'<span class="badge {badge}">{esc(label)}</span></header>'
            f'<p class="muted">{esc(gap["reason"])}</p>'
            f'<dl>'
            f'<dt>Hedef kelime</dt><dd>{gap["target_words"]}</dd>'
            + (
                f'<dt>Yazılan</dt><dd>{gap["written_words"]} '
                f'(%{gap["completion_ratio"] * 100:.0f})</dd>'
                if gap.get("written_words") is not None
                else f'<dt>Tahmini kapasite</dt>'
                     f'<dd>{gap.get("estimated_capacity_words", 0)} kelime '
                     f'(%{gap.get("capacity_ratio", 0) * 100:.0f})</dd>'
            )
            + f'<dt>Atanan kaynak</dt><dd>{gap["assigned_source_count"]}</dd>'
            f'<dt>Gereken tasarım</dt>'
            f'<dd>{esc(", ".join(gap["required_designs"]) or "—")}</dd>'
            f'</dl>'
            f'<h3>Önerilen arama sorguları</h3><ol class="queries">{queries}</ol>'
            f'</article>'
        )
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kanıt boşluğu talebi — {esc(report.get("title") or "")}</title>
<style>
:root{{--ink:#202833;--muted:#5b6b7b;--line:#d9e0e7;--blue:#174f82;--soft:#f4f7fa;
--red:#b3261e;--green:#1e7d4f;--amber:#9a6400}}
*{{box-sizing:border-box}}body{{max-width:960px;margin:0 auto;padding:2rem 1.2rem 4rem;
color:var(--ink);font:16px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif}}
h1{{line-height:1.25;font-size:1.5rem}}.muted{{color:var(--muted);font-size:.9rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:1rem 0}}
.stat{{border:1px solid var(--line);border-radius:9px;padding:.7rem .9rem;background:#fff}}
.stat b{{display:block;font-size:1.5rem}}.card{{border:1px solid var(--line);border-left-width:4px;
border-radius:9px;padding:1rem 1.1rem;margin:1rem 0;background:#fff}}
.card.evidence{{border-left-color:var(--amber)}}.card.plan{{border-left-color:var(--red)}}
.card header{{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}}
.card h2{{font-size:1.05rem;margin:.1rem 0}}.sid{{background:var(--soft);border-radius:5px;
padding:.1rem .45rem;font-weight:700;font-size:.85rem}}
.badge{{font-size:.75rem;font-weight:700;border-radius:999px;padding:.15rem .55rem}}
.badge.evidence{{background:#fff4d6;color:var(--amber)}}
.badge.plan{{background:#fde8e6;color:var(--red)}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:.2rem .8rem;margin:.7rem 0;font-size:.9rem}}
dt{{color:var(--muted);font-weight:600}}dd{{margin:0}}
h3{{font-size:.9rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:.9rem 0 .4rem}}
code{{background:var(--soft);border:1px solid var(--line);border-radius:4px;padding:.1rem .35rem;font-size:.85rem}}
.next{{background:var(--soft);border:1px solid var(--line);border-radius:9px;padding:1rem 1.1rem;margin-top:1.5rem}}
@media print{{body{{max-width:none;padding:.4in}}.card,.next{{break-inside:avoid}}}}
</style></head><body>
<h1>Kanıt boşluğu talebi</h1>
<p class="muted">{esc(report.get("title") or "")} · {esc(report.get("project") or "")}</p>
<div class="stats">
  <div class="stat"><b>{summary["planned_sections"]}</b><span class="muted">Planlanan alt başlık</span></div>
  <div class="stat"><b>{summary["gap_sections"]}</b><span class="muted">Boşluklu alt başlık</span></div>
  <div class="stat"><b>{summary["evidence_shortfall"]}</b><span class="muted">Kanıt eksik</span></div>
  <div class="stat"><b>{summary["plan_change_required"]}</b><span class="muted">Plan değişikliği</span></div>
  <div class="stat"><b>{report["written_total_words"]}</b><span class="muted">Yazılan kelime</span></div>
</div>
{''.join(rows) or '<p class="muted">Boşluk bulunmadı.</p>'}
{render_reading(report['reading_manifest'], report['reading_gate'], report.get('reading_advice')) if report.get('reading_manifest') else '<p>Tam metin okuma raporu eklenmedi; 4/5 akışına geçiş doğrulanmadı.</p>' if report.get('mode') == 'preflight' else ''}
<div class="next">
<h3>Sonraki adım</h3>
<p><strong>Yalnızca kanıt eksikse:</strong> {esc(report["next_action"]["if_only_evidence_shortfall"])}</p>
<p><strong>Plan değişikliği gerekiyorsa:</strong> {esc(report["next_action"]["if_plan_change_required"])}</p>
<p class="muted"><strong>Asla:</strong> {esc("; ".join(report["next_action"]["never"]))}</p>
</div>
<p class="muted">Bu talep kanıt üretmez; yalnızca neyin eksik olduğunu ve nerede aranacağını kaydeder.</p>
</body></html>"""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Akış 4'te kanıt yetersizliğini makine okunabilir talebe çevirir."
    )
    parser.add_argument("plan", type=Path, help="Yazım planı JSON")
    parser.add_argument(
        "draft",
        type=Path,
        nargs="?",
        help="Taslak JSON (yalnızca taslak-sonrası denetimde gerekli)",
    )
    parser.add_argument("-o", "--output-dir", type=Path, help="Çıktı klasörü")
    parser.add_argument(
        "--min-words-ratio",
        type=float,
        default=DEFAULT_MIN_WORDS_RATIO,
        help=f"Bu oranın altındaki alt başlık boşluk sayılır (varsayılan {DEFAULT_MIN_WORDS_RATIO}).",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Taslak yazılmadan ÖNCE kanıt kapasitesini ölç. "
            "--fulltext-list ve --fulltext-dir ile birlikte kullanılır."
        ),
    )
    parser.add_argument(
        "--fulltext-list",
        type=Path,
        help="Preflight için fulltext listesi JSON (kaynak tasarımları).",
    )
    parser.add_argument(
        "--evidence-bank",
        type=Path,
        help=(
            "Kanıt bankası JSON (tasarım bilgisi buradan alınır; verilmezse "
            "04_taslak/taslak/_kanit_bankasi.json aranır)."
        ),
    )
    parser.add_argument(
        "--fulltext-dir",
        type=Path,
        help="Preflight için PDF klasörü (erişilebilirlik denetimi).",
    )
    parser.add_argument("--check", action="store_true", help="Yalnızca doğrula/özetle")
    parser.add_argument("--reading-report", type=Path, help="Bütün sayfalar için model incelemesi içeren fulltext-reading/1 raporu")
    parser.add_argument("--workflow", choices=["4", "5"], default="4", help="Geçişi denetlenecek hedef akış")
    parser.add_argument("--force", action="store_true", help="Var olan çıktının üzerine yaz")
    add_timestamp_argument(parser)
    args = parser.parse_args(argv)
    if args.reading_report and not args.reading_report.is_file():
        parser.error("Okuma raporu bulunamadı")

    if not args.plan.is_file():
        print(f"Hata: plan bulunamadı: {args.plan}", file=sys.stderr)
        return 2
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    draft = None
    if args.draft:
        if not args.draft.is_file():
            print(f"Hata: taslak bulunamadı: {args.draft}", file=sys.stderr)
            return 2
        draft = json.loads(args.draft.read_text(encoding="utf-8"))

    if args.preflight:
        fulltext_list = None
        if args.fulltext_list and args.fulltext_list.is_file():
            fulltext_list = json.loads(args.fulltext_list.read_text(encoding="utf-8"))
        available: set[str] = set()
        if args.fulltext_dir and args.fulltext_dir.is_dir():
            available = {p.stem.lower() for p in args.fulltext_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"}
        evidence_bank = None
        bank_candidates = [
            args.evidence_bank,
            (args.plan.parent.parent / ("04_taslak" if args.workflow == "4" else "05_analiz") / "taslak" / "_kanit_bankasi.json"),
        ]
        for candidate in bank_candidates:
            if candidate and Path(candidate).is_file():
                evidence_bank = json.loads(Path(candidate).read_text(encoding="utf-8"))
                break
        report = preflight(
            plan,
            fulltext_list=fulltext_list,
            available_pdfs=available,
            min_words_ratio=args.min_words_ratio,
            evidence_bank=evidence_bank,
            reading_manifest=json.loads(args.reading_report.read_text(encoding="utf-8")) if args.reading_report else None,
            fulltext_root=args.fulltext_dir,
            workflow=args.workflow,
        )
    else:
        report = analyse(plan, draft, args.min_words_ratio)
    summary = report["summary"]

    if args.check:
        print(
            f"OK: {summary['planned_sections']} alt başlık, "
            f"{summary['gap_sections']} boşluk "
            f"({summary['evidence_shortfall']} kanıt eksik, "
            f"{summary['plan_change_required']} plan değişikliği)."
        )
        if args.preflight and not report["transition_allowed"]:
            print("GEÇİŞ ENGELLİ: okuma raporu, kaynak boşlukları veya plan onayı tamamlanmadı.", file=sys.stderr)
            return 1
        return 0

    output_dir = args.output_dir or args.plan.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    html_text = render_html(report)
    target = add_timestamp(output_dir / f"{OUTPUT_STEM}.json", enabled=args.timestamp)
    result = write_versioned_pair(
        target,
        {
            ".json": json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            ".html": html_text,
        },
        enabled=args.timestamp,
        force=args.force,
    )
    if result["status"] == "unchanged":
        print(f"Değişiklik yok; mevcut sürüm korundu: {result['path']}")
    else:
        print(f"Yazıldı: {result['path']}")
        print(f"Yazıldı: {result['path'].with_suffix('.html')}")
    print(
        f"Boşluk: {summary['gap_sections']} alt başlık "
        f"({summary['evidence_shortfall']} kanıt eksik, "
        f"{summary['plan_change_required']} plan değişikliği)."
    )
    if summary["plan_change_required"]:
        print(
            "DİKKAT: plan değişikliği gereken alt başlık var; kullanıcıya "
            "sormadan planı değiştirmeyin.",
            file=sys.stderr,
        )
    return 1 if args.preflight and not report["transition_allowed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
