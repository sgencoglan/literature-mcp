#!/usr/bin/env python3
"""Akış 4 ve 5'in ilk adımı: atanmış fulltext'leri sistematik okuma.

Neden bu betik var
------------------
Taslak yazmaya abstrakt okuyarak başlamak, elde yüzlerce sayfa tam metin varken
metni birkaç kaynakla sınırlar. Bu, "kanıt yetmiyor" yanılgısını üretir: eksik
olan kanıt değil, okumadır. Bu betik atanmış PDF'leri okur ve plan alt
başlıklarına ait pasajları **sayfa numarasıyla** çıkarıp kanıt bankası yazar.

İki motor vardır:

``semantic`` (varsayılan)
    PaperQA2 indeksi üzerinde embedding tabanlı arama. Alt başlık başına tek
    sorgu, tüm proje indeksini tarar; hangi PDF'in o alt başlıkla gerçekten
    ilgili olduğunu **anlamsal yakınlıkla** belirler. Kelime eşleşmesine
    takılmaz: eş anlamlıyı, farklı ifadeyi ve bağlamı yakalar. İndeks yoksa
    betik bunu söyler ve ``--engine keyword`` ister.

``keyword``
    PyMuPDF + terim eşleşmesi. PaperQA2 kurulu değilse ya da indeks
    oluşturulmamışsa çalışan yedek yol. Daha kaba, ama bağımlılıksız.

Ne üretir
---------
``<akış>/taslak/_kanit_bankasi.json`` — DOI başına: tasarım, sayfa sayısı,
bölüm bazlı alıntı adayları (sayfa numaralı).
``<akış>/taslak/kanit_bankasi_<zaman>.html`` — insan tarafından okunabilir özet.

Kanıt sayılmaz
--------------
Buradaki cümleler **alıntı adayı**dır. Taslağa giren her cümle, akış 4'te
`paperqa_read_pages` ile o sayfadan yeniden doğrulanır. Betik, doğrulamayı
kendi üstlenmez; yalnızca aramayı daraltır.

Kullanım:
    python3 scripts/build_evidence_bank.py <proje-kökü> --workflow 4
    python3 scripts/build_evidence_bank.py <proje-kökü> --workflow 5 --check
    python3 scripts/build_evidence_bank.py plan.json --fulltext-dir <pdf-klasörü>
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
    from output_naming import (
        add_timestamp,
        add_timestamp_argument,
        write_versioned_pair,
    )
except ImportError:  # python -m scripts.build_evidence_bank
    from scripts.output_naming import (
        add_timestamp,
        add_timestamp_argument,
        write_versioned_pair,
    )

try:
    from project_layout import fulltext_dir, workflow_dir
except ImportError:
    from scripts.project_layout import fulltext_dir, workflow_dir

BANK_STEM = "_kanit_bankasi"
HTML_STEM = "kanit_bankasi"

# Bir cümlenin alıntı adayı sayılması için gereken en az bölüm terimi sayısı.
MIN_TERM_HITS = 2
# Kaynak başına en fazla alıntı adayı (yazma aşamasını boğmamak için).
MAX_QUOTES_PER_SOURCE = 8
# Aynı sayfadan en fazla kaç aday alınır.
MAX_QUOTES_PER_PAGE = 2
# Cümle uzunluk sınırları: çok kısa cümle bağlam taşımaz, çok uzun cümle alıntılanamaz.
MIN_SENTENCE_CHARS = 60
MAX_SENTENCE_CHARS = 420

DESIGN_PATTERNS = [
    (r"meta[- ]analys", "meta_analysis"),
    (r"systematic review|scoping review", "systematic_review"),
    (r"quasi[- ]experimental", "quasi_experimental"),
    (r"randomi[sz]ed|\brct\b|cluster[- ]randomi[sz]ed|group randomized", "rct"),
    (r"policy statement|position statement|clinical report", "policy_document"),
    (r"cohort|longitudinal|prospective", "cohort"),
    (r"cross[- ]sectional|\bsurvey\b|questionnaire|self[- ]report", "cross_sectional"),
    (r"qualitative|interview|focus group|thematic analysis|grounded", "qualitative"),
]

SKIP_PAGE = re.compile(r"^\s*(references|bibliography|kaynakça|appendix)", re.IGNORECASE)

# Plan `search_terms` taşımıyorsa başlık için İngilizce eşleme tablosu.
TERM_FALLBACK: Dict[str, List[str]] = {
    "giriş": ["classroom management", "disruptive behavior", "student achievement", "prevention"],
    "kriz öncesi": ["screening", "identification", "judgment", "perception", "referral", "at risk"],
    "kriz anı": ["reprimand", "praise", "intervention", "escalation", "engagement"],
    "kriz sonrası": ["reintegration", "reentry", "suspension", "expulsion", "follow-up", "outcome"],
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pdf_filename(doi: str) -> str:
    """İndiricinin ürettiği ada birebir eşleşen PDF dosya adı."""
    text = unicodedata.normalize("NFKD", str(doi)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9.\-]+", "", text).strip(".-") + ".pdf"


def clean_page_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"-\n", "", text)  # tire ile bölünmüş kelimeler
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ(\"'])", text)
    return [
        part.strip()
        for part in parts
        if MIN_SENTENCE_CHARS <= len(part.strip()) <= MAX_SENTENCE_CHARS
    ]


def section_terms(section: Dict[str, Any]) -> List[str]:
    """Alt başlığı besleyen İngilizce arama terimleri."""
    terms = [str(t).strip().lower() for t in (section.get("search_terms") or []) if str(t).strip()]
    if terms:
        return terms
    heading = str(section.get("heading") or "").lower()
    for needle, mapped in TERM_FALLBACK.items():
        if needle in heading:
            return mapped
    # Son çare: başlığın kendisi.
    return [heading] if heading else []


def detect_design(title: str, sample_text: str = "") -> str:
    """Tasarımı başlıktan, sonra metinden çıkar.

    Başlık daha güvenilirdir: bir çalışma hem yarı deneysel hem randomize kol
    bildirebilir; künyede yazan tasarım esas alınır. Bu yüzden başlık önce ve
    ``quasi_experimental`` deseni ``rct`` deseninden önce denenir.
    """
    for haystack in (title or "", sample_text[:4000] if sample_text else ""):
        lowered = haystack.lower()
        for pattern, label in DESIGN_PATTERNS:
            if re.search(pattern, lowered):
                return label
    return "any"


def _score(sentence: str, terms: List[str]) -> int:
    lowered = sentence.lower()
    return sum(1 for term in terms if term in lowered)


def read_source(
    doi: str,
    path: Path,
    terms: List[str],
    title: Optional[str] = None,
    min_hits: int = MIN_TERM_HITS,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "doi": doi,
        "pdf": path.name,
        "exists": path.is_file(),
        "pages": 0,
        "design": "any",
        "title": title,
        "quotes": [],
        "error": None,
    }
    if not path.is_file():
        entry["error"] = "PDF bulunamadı"
        return entry

    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        entry["error"] = "PyMuPDF kurulu değil (pip install pymupdf)"
        return entry

    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001
        entry["error"] = str(exc)[:160]
        return entry

    try:
        entry["pages"] = doc.page_count
        page_texts = [clean_page_text(doc[page].get_text()) for page in range(doc.page_count)]
    finally:
        doc.close()

    entry["design"] = detect_design(title or "", " ".join(page_texts[:3]))

    scored: List[tuple[int, int, str]] = []
    for page_number, text in enumerate(page_texts, start=1):
        if not text or SKIP_PAGE.match(text):
            continue
        for sentence in split_sentences(text):
            hits = _score(sentence, terms)
            if hits >= min_hits:
                scored.append((hits, page_number, sentence))

    scored.sort(key=lambda item: (-item[0], item[1]))
    per_page: Dict[int, int] = {}
    picked: List[Dict[str, Any]] = []
    for hits, page_number, sentence in scored:
        if per_page.get(page_number, 0) >= MAX_QUOTES_PER_PAGE:
            continue
        per_page[page_number] = per_page.get(page_number, 0) + 1
        picked.append({"page": page_number, "term_hits": hits, "text": sentence})
        if len(picked) >= MAX_QUOTES_PER_SOURCE:
            break

    entry["quotes"] = picked
    return entry


def build(
    plan: Dict[str, Any],
    assignments: Dict[str, List[str]],
    pdf_dir: Path,
    titles: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    titles = titles or {}
    sources: List[Dict[str, Any]] = []

    for section in plan.get("sections") or []:
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id") or "")
        dois = assignments.get(sid) or []
        terms = section_terms(section)
        for doi in dois:
            entry = read_source(doi, pdf_dir / pdf_filename(doi), terms, titles.get(doi))
            entry["section_id"] = sid
            entry["section_heading"] = section.get("heading")
            entry["terms_used"] = terms
            sources.append(entry)

    total_pages = sum(s["pages"] for s in sources)
    quotes = sum(len(s["quotes"]) for s in sources)
    return {
        "schema": "evidence-bank/1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project": plan.get("project"),
        "title": plan.get("title"),
        "pdf_directory": str(pdf_dir),
        "rules": {
            "min_term_hits": MIN_TERM_HITS,
            "max_quotes_per_source": MAX_QUOTES_PER_SOURCE,
            "max_quotes_per_page": MAX_QUOTES_PER_PAGE,
            "note": (
                "Bu cümleler alıntı adayıdır, kanıt değildir. Taslağa giren her "
                "cümle paperqa_read_pages ile aynı sayfadan doğrulanmalıdır."
            ),
        },
        "coverage": {
            "sources_assigned": sum(len(v) for v in assignments.values()),
            "sources_found": sum(1 for s in sources if s["exists"]),
            "sources_with_quotes": sum(1 for s in sources if s["quotes"]),
            "pages_total": total_pages,
            "quote_candidates": quotes,
        },
        "sections": {},
        "sources": sources,
    }



# --------------------------------------------------------------------------- #
# Semantik motor — PaperQA2 indeksi üzerinde embedding araması
# --------------------------------------------------------------------------- #

def _paperqa_module():
    """paperqa_mcp'yi içe aktar (paket ya da depo yolu)."""
    try:
        import paperqa_mcp  # type: ignore

        return paperqa_mcp
    except ImportError:
        pass
    repo = Path(__file__).resolve().parents[1]
    candidate = repo / "packages" / "paperqa-local"
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))
        try:
            import paperqa_mcp  # type: ignore

            return paperqa_mcp
        except ImportError:
            return None
    return None


def resolve_paperqa_project(pdf_dir: Path, hints: List[str]) -> Optional[str]:
    """PDF klasörüne karşılık gelen kayıtlı PaperQA proje adını bul.

    Plan `project` alanı ile kayıtlı proje adı farklı olabilir (örn. plan
    ``deneme7``, indeks ``deneme7-draft``). Yol eşleşmesi en güvenilir sinyaldir.
    """
    paperqa = _paperqa_module()
    if paperqa is None:
        return None
    try:
        import asyncio

        payload = asyncio.run(paperqa.paperqa_projects())
    except Exception:  # noqa: BLE001
        return None
    projects = payload.get("projects") or []
    target = str(pdf_dir.resolve())
    for entry in projects:
        if not isinstance(entry, dict):
            continue
        paper_directory = str(entry.get("paper_directory") or "")
        if paper_directory and str(Path(paper_directory).resolve()) == target:
            return str(entry.get("project") or "")
    available = {str(entry.get("project")) for entry in projects if isinstance(entry, dict)}
    for hint in hints:
        if hint and hint in available:
            return hint
    return None


def build_semantic(
    plan: Dict[str, Any],
    project: str,
    k_per_section: int = 12,
    max_chars: int = 900,
    pdf_dir: Optional[Path] = None,
    include_keyword: bool = True,
    titles: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Alt başlık başına tek semantik arama; hangi PDF'in ilgili olduğunu bulur.

    Kelime eşleşmesi yerine anlamsal yakınlık kullanıldığı için, aynı kavramı
    farklı sözcüklerle anlatan pasajlar da yakalanır. Dönen her pasaj DOI ve
    sayfa numarası taşır; taslak aşaması bunları ``paperqa_read_pages`` ile
    doğrular.
    """
    import asyncio

    titles = titles or {}
    paperqa = _paperqa_module()
    if paperqa is None:
        raise RuntimeError(
            "paperqa_mcp bulunamadı; PaperQA2 kurulu değil. "
            "`--engine keyword` ile devam edin veya bağımlılıkları kurun."
        )

    async def run() -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        for section in plan.get("sections") or []:
            if not isinstance(section, dict):
                continue
            sid = str(section.get("id") or "")
            terms = section_terms(section)
            query = ", ".join(terms) if terms else str(section.get("heading") or "")
            if not query.strip():
                continue
            try:
                payload = await paperqa.paperqa_search(
                    project=project, query=query, k=k_per_section, max_chars=max_chars
                )
            except Exception as exc:  # noqa: BLE001 - tek bölüm hatası tümünü düşürmesin
                collected.append(
                    {
                        "section_id": sid,
                        "section_heading": section.get("heading"),
                        "query": query,
                        "error": str(exc)[:200],
                        "hits": [],
                    }
                )
                continue
            hits = []
            for result in payload.get("results") or []:
                hits.append(
                    {
                        "doi": str(result.get("doi") or "").lower(),
                        "pages": result.get("pages"),
                        "title": result.get("title"),
                        "journal": result.get("journal"),
                        "year": result.get("year"),
                        "text": result.get("text"),
                        "rank": result.get("rank"),
                    }
                )
            collected.append(
                {
                    "section_id": sid,
                    "section_heading": section.get("heading"),
                    "query": query,
                    "hits": hits,
                }
            )
        return collected

    per_section = asyncio.run(run())

    # DOI -> pasajlar (yazma aşaması kaynak bazında çalışır)
    by_doi: Dict[str, Dict[str, Any]] = {}
    for block in per_section:
        for hit in block["hits"]:
            doi = hit["doi"]
            if not doi:
                continue
            entry = by_doi.setdefault(
                doi,
                {
                    "doi": doi,
                    "pdf": pdf_filename(doi),
                    "exists": True,
                    "title": hit.get("title") or titles.get(doi) or None,
                    "pages": 0,
                    "design": detect_design(
                        (hit.get("title") or titles.get(doi) or ""),
                        hit.get("text") or "",
                    ),
                    "quotes": [],
                    "error": None,
                    "sections": set(),
                    "semantic": True,
                },
            )
            entry["sections"].add(block["section_id"])
            entry["quotes"].append(
                {
                    "page": hit.get("pages"),
                    "term_hits": None,
                    "text": hit.get("text"),
                    "section_id": block["section_id"],
                    "rank": hit.get("rank"),
                    "source": "semantic",
                }
            )

    # Keyword taraması: semantik top-k kesmesinde dışarıda kalan kaynakların
    # kapsamı garanti altına alınır. Semantik isabeti, keyword kapsamı sağlar.
    if include_keyword and pdf_dir is not None:
        for section in plan.get("sections") or []:
            if not isinstance(section, dict):
                continue
            sid = str(section.get("id") or "")
            terms = section_terms(section)
            for doi in (plan.get("_assignments") or {}).get(sid) or []:
                key = str(doi).lower()
                entry = by_doi.get(key)
                needs_fill = entry is None or not entry["quotes"]
                if not needs_fill:
                    continue
                fallback = read_source(
                    key, pdf_dir / pdf_filename(key), terms, titles.get(key)
                )
                if not fallback["quotes"] and len(terms) > 1:
                    # Tek terim eşleşmesi de kapsam için yeterli: hassasiyeti
                    # semantik aşama sağlıyor, burada amaç boşluk bırakmamak.
                    fallback = read_source(
                        key,
                        pdf_dir / pdf_filename(key),
                        terms,
                        titles.get(key),
                        min_hits=1,
                    )
                if not fallback["quotes"]:
                    continue
                if entry is None:
                    entry = {
                        "doi": key,
                        "pdf": fallback["pdf"],
                        "exists": fallback["exists"],
                        "title": fallback["title"],
                        "pages": fallback["pages"],
                        "design": fallback["design"],
                        "quotes": [],
                        "error": fallback["error"],
                        "sections": set(),
                        "semantic": True,
                    }
                    by_doi[key] = entry
                entry["pages"] = fallback["pages"] or entry["pages"]
                entry["title"] = entry["title"] or fallback["title"]
                # Başlık artık elimizdeyse tasarımı yeniden çıkar: künyede
                # "quasi-experimental" yazıyorsa rct etiketi düzeltilir.
                redesign = detect_design(entry["title"] or "", "")
                if redesign != "any":
                    entry["design"] = redesign
                else:
                    entry["design"] = fallback["design"] or entry["design"]
                entry["sections"].add(sid)
                for quote in fallback["quotes"]:
                    quote["section_id"] = sid
                    quote["source"] = "keyword"
                    entry["quotes"].append(quote)

    sources = []
    for entry in by_doi.values():
        entry["sections"] = sorted(entry["sections"])
        sources.append(entry)

    # Atanmış ama semantik aramada hiç görünmemiş kaynaklar da raporlanır:
    # bu, "bu kaynak plana atanmış ama hiçbir alt başlıkla anlamsal yakınlık
    # göstermiyor" demektir ve yazma aşamasında dikkate alınmalıdır.
    assigned = {
        str(doi).lower()
        for dois in (plan.get("_assignments") or {}).values()
        for doi in dois
    }
    for doi in sorted(assigned - set(by_doi)):
        sources.append(
            {
                "doi": doi,
                "pdf": pdf_filename(doi),
                "exists": True,
                "title": None,
                "pages": 0,
                "design": "any",
                "quotes": [],
                "error": None,
                "sections": [],
                "semantic": True,
                "note": "Semantik aramada hiçbir alt başlıkla eşleşmedi.",
            }
        )

    quotes = sum(len(s["quotes"]) for s in sources)
    return {
        "schema": "evidence-bank/1",
        "engine": "semantic",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project": project,
        "title": plan.get("title"),
        "rules": {
            "note": (
                "PaperQA2 embedding araması (st-multi-qa-MiniLM-L6-cos-v1). "
                "Pasajlar alıntı adayıdır; taslağa giren her cümle "
                "paperqa_read_pages ile aynı sayfadan doğrulanmalıdır."
            ),
        },
        "coverage": {
            "sources_assigned": len(assigned),
            "sources_found": len(sources),
            "sources_with_quotes": sum(1 for s in sources if s["quotes"]),
            "quote_candidates": quotes,
        },
        "per_section": [
            {
                "section_id": block["section_id"],
                "section_heading": block["section_heading"],
                "query": block["query"],
                "hit_count": len(block["hits"]),
                "error": block.get("error"),
            }
            for block in per_section
        ],
        "sources": sources,
    }


def summarize_per_section(bank: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for source in bank["sources"]:
        sid = source.get("section_id") or "?"
        row = summary.setdefault(
            sid,
            {"sources": 0, "quotes": 0, "pages": 0, "designs": {}, "missing_pdf": 0},
        )
        row["sources"] += 1
        row["quotes"] += len(source["quotes"])
        row["pages"] += source["pages"]
        if not source["exists"]:
            row["missing_pdf"] += 1
        design = source["design"]
        row["designs"][design] = row["designs"].get(design, 0) + 1
    return summary


def render_html(bank: Dict[str, Any]) -> str:
    coverage = bank["coverage"]
    summary = summarize_per_section(bank)
    cards = []
    for sid, row in summary.items():
        designs = ", ".join(f"{k} {v}" for k, v in sorted(row["designs"].items()))
        cards.append(
            f'<div class="stat"><b>{esc(sid)}</b>'
            f'<span>{row["sources"]} kaynak · {row["quotes"]} aday · {row["pages"]} sayfa</span>'
            f'<small>{esc(designs)}</small></div>'
        )

    sections_block = ""
    per_section = bank.get("per_section") or []
    if per_section:
        row_html = []
        for row in per_section:
            error = row.get("error")
            status = f"<td class=err>{esc(error)}</td>" if error else "<td>—</td>"
            row_html.append(
                f'<tr><td>{esc(row["section_id"])}</td>'
                f'<td>{esc(row["section_heading"] or "")}</td>'
                f'<td><code>{esc(row["query"])}</code></td>'
                f'<td class="num">{row["hit_count"]}</td>'
                f"{status}</tr>"
            )
        sections_block = (
            '<h2 style="font-size:1rem;margin:1.5rem 0 .5rem">'
            "Alt başlık başına semantik sorgu</h2>"
            "<table><thead><tr><th>#</th><th>Alt başlık</th><th>Sorgu</th>"
            f"<th>Pasaj</th><th>Durum</th></tr></thead><tbody>{''.join(row_html)}</tbody></table>"
        )

    blocks = []
    for source in bank["sources"]:
        quotes = "".join(
            f'<li><span class="page">s. {quote["page"]}</span> {esc(quote["text"])}</li>'
            for quote in source["quotes"]
        ) or '<li class="muted">Bu alt başlık için aday cümle çıkarılamadı.</li>'
        blocks.append(
            f'<article class="card">'
            f'<header><span class="sid">{esc(source.get("section_id"))}</span>'
            f'<h2>{esc(source.get("title") or source["doi"])}</h2></header>'
            f'<p class="muted">{esc(source["doi"])} · {esc(source["design"])} · '
            f'{source["pages"]} sayfa · {len(source["quotes"])} aday</p>'
            f'<ol class="quotes">{quotes}</ol></article>'
        )

    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kanıt bankası — {esc(bank.get("title") or "")}</title>
<style>
:root{{--ink:#202833;--muted:#5b6b7b;--line:#d9e0e7;--soft:#f4f7fa;--blue:#174f82}}
*{{box-sizing:border-box}}body{{max-width:960px;margin:0 auto;padding:2rem 1.2rem 4rem;
color:var(--ink);font:16px/1.6 system-ui,-apple-system,'Segoe UI',sans-serif}}
h1{{font-size:1.45rem;line-height:1.25}}.muted{{color:var(--muted);font-size:.88rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:1rem 0}}
.stat{{border:1px solid var(--line);border-radius:9px;padding:.7rem .9rem;background:#fff}}
.stat b{{display:block;font-size:1.15rem}}.stat span{{display:block;font-size:.85rem}}
.stat small{{color:var(--muted);font-size:.75rem}}
.card{{border:1px solid var(--line);border-radius:9px;padding:.9rem 1.1rem;margin:.9rem 0;background:#fff}}
.card header{{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap}}
.card h2{{font-size:.98rem;margin:.1rem 0;font-weight:650}}
.sid{{background:var(--soft);border-radius:5px;padding:.05rem .4rem;font-weight:700;font-size:.8rem}}
.quotes{{margin:.5rem 0 0;padding-left:1.2rem;font-size:.9rem}}
.quotes li{{margin:.35rem 0}}
.page{{display:inline-block;background:var(--soft);border-radius:4px;padding:0 .3rem;
font-size:.72rem;font-weight:700;color:var(--blue);margin-right:.3rem}}
table{{width:100%;border-collapse:collapse;font-size:.85rem;margin:.5rem 0 1rem}}
th,td{{border-bottom:1px solid var(--line);padding:.4rem .5rem;text-align:left;vertical-align:top}}
th{{color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.03em}}
td.num{{text-align:right;width:60px}}.err{{color:#b3261e}}
.note{{background:var(--soft);border:1px solid var(--line);border-radius:9px;padding:1rem 1.1rem;margin-top:1.5rem}}
@media print{{body{{max-width:none;padding:.4in}}.card{{break-inside:avoid}}}}
</style></head><body>
<h1>Kanıt bankası — akış 4/5 okuma adımı</h1>
<p class="muted">{esc(bank.get("title") or "")} · {esc(bank.get("project") or "")}</p>
<div class="stats">
  <div class="stat"><b>{coverage["sources_found"]}/{coverage["sources_assigned"]}</b>
    <span>PDF bulundu</span><small>atanmış kaynak</small></div>
  <div class="stat"><b>{coverage.get("pages_total", coverage["quote_candidates"])}</b>
    <span>{'taranan sayfa' if coverage.get("pages_total") else 'semantik pasaj'}</span></div>
  <div class="stat"><b>{coverage["quote_candidates"]}</b>
    <span>alıntı adayı</span><small>{coverage["sources_with_quotes"]} kaynakta</small></div>
</div>
{''.join(cards)}
{sections_block}
{''.join(blocks)}
<div class="note">
<p><strong>Bu dosya kanıt değildir.</strong> Cümleler alıntı adayıdır; taslağa
giren her cümle <code>paperqa_read_pages</code> ile aynı sayfadan yeniden
doğrulanmalıdır.</p>
</div>
</body></html>"""


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    """(plan_json, assignments_json, pdf_dir, output_dir) çöz."""
    if args.project_root:
        root = args.project_root.expanduser().resolve()
        workflow = str(args.workflow)
        plan_json = args.plan or (workflow_dir(root, "2") / "01_yazim_plani.json")
        assignments = args.assignments or (workflow_dir(root, "3") / "00_atamalar.json")
        pdfs = args.fulltext_dir or fulltext_dir(root, workflow)
        out = args.output_dir or (workflow_dir(root, workflow) / "taslak")
    else:
        plan_json = args.plan
        assignments = args.assignments
        pdfs = args.fulltext_dir
        out = args.output_dir
    missing = [
        str(path)
        for path in (plan_json, assignments, pdfs)
        if path is None
    ]
    if missing:
        raise SystemExit(
            "Eksik argüman: proje kökü ya da plan + --assignments + --fulltext-dir verin."
        )
    return plan_json, assignments, pdfs, out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Akış 4/5 ilk adımı: atanmış fulltext'leri okuyup kanıt bankası üretir."
    )
    parser.add_argument("project_root", type=Path, nargs="?", help="Proje kökü")
    parser.add_argument("--workflow", default="4", choices=["4", "5"], help="Hedef akış")
    parser.add_argument("--plan", type=Path, help="Yazım planı JSON (kök verilmezse)")
    parser.add_argument("--assignments", type=Path, help="Atama dosyası {S1: [doi]}")
    parser.add_argument("--fulltext-dir", type=Path, help="PDF klasörü")
    parser.add_argument("-o", "--output-dir", type=Path, help="Çıktı klasörü")
    parser.add_argument(
        "--engine",
        choices=["semantic", "keyword"],
        default="semantic",
        help=(
            "semantic: PaperQA2 indeksi üzerinde embedding araması (varsayılan). "
            "keyword: PyMuPDF + terim eşleşmesi (indeks yoksa)."
        ),
    )
    parser.add_argument(
        "--project-name",
        help="Kayıtlı PaperQA proje adı (verilmezse PDF klasöründen çözülür).",
    )
    parser.add_argument(
        "--per-section-k",
        type=int,
        default=12,
        help="Semantik motorda alt başlık başına getirilecek pasaj sayısı.",
    )
    parser.add_argument(
        "--no-keyword-fill",
        action="store_true",
        help=(
            "Semantik aramada pasaj çıkmayan kaynaklar için keyword taraması "
            "yapma (kapsam düşer, hız artar)."
        ),
    )
    parser.add_argument("--check", action="store_true", help="Yalnızca doğrula/özetle")
    parser.add_argument("--force", action="store_true", help="Var olan çıktının üzerine yaz")
    add_timestamp_argument(parser)
    args = parser.parse_args(argv)

    plan_json, assignments_path, pdfs, out_dir = resolve_inputs(args)
    for label, path in (("plan", plan_json), ("atama", assignments_path)):
        if not path.is_file():
            print(f"Hata: {label} bulunamadı: {path}", file=sys.stderr)
            return 2
    if not pdfs.is_dir():
        print(f"Hata: PDF klasörü bulunamadı: {pdfs}", file=sys.stderr)
        return 2

    plan = load_json(plan_json)
    assignments = load_json(assignments_path)

    titles: Dict[str, str] = {}
    ft_list = plan_json.parent.parent / "03_kaynak_kesfi" / "01_fulltext_listesi.json"
    if ft_list.is_file():
        for candidate in load_json(ft_list).get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("doi"):
                titles[str(candidate["doi"]).lower()] = str(candidate.get("title") or "")

    if args.engine == "semantic":
        plan["_assignments"] = assignments
        hints = [
            args.project_name or "",
            str(plan.get("project") or ""),
            f"{plan.get('project')}-draft" if plan.get("project") else "",
            pdfs.parent.parent.name,
        ]
        project_name = resolve_paperqa_project(pdfs, hints)
        if not project_name:
            print(
                "Hata: bu PDF klasörü için kayıtlı PaperQA projesi bulunamadı. "
                "Önce `paperqa_register_project` + `paperqa_build_index` çalıştırın, "
                "ya da `--project-name` verin; indeks yoksa `--engine keyword` kullanın.",
                file=sys.stderr,
            )
            return 2
        try:
            bank = build_semantic(
                plan,
                project=project_name,
                k_per_section=max(1, min(int(args.per_section_k), 20)),
                pdf_dir=pdfs,
                include_keyword=not args.no_keyword_fill,
                titles=titles,
            )
        except RuntimeError as exc:
            print(f"Hata: {exc}", file=sys.stderr)
            return 2
    else:
        bank = build(plan, assignments, pdfs, titles)
        bank["engine"] = "keyword"

    if args.check:
        cov = bank["coverage"]
        pages = cov.get("pages_total")
        pages_text = f"{pages} sayfa, " if pages else ""
        print(
            f"OK: {cov['sources_found']}/{cov['sources_assigned']} kaynak, "
            f"{pages_text}{cov['quote_candidates']} alıntı adayı "
            f"({cov.get('sources_with_quotes', 0)} kaynakta)."
        )
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    target = add_timestamp(out_dir / f"{HTML_STEM}.json", enabled=args.timestamp)
    result = write_versioned_pair(
        target,
        {
            ".json": json.dumps(bank, ensure_ascii=False, indent=2) + "\n",
            ".html": render_html(bank),
        },
        enabled=args.timestamp,
        force=args.force,
    )
    # Sabit adlı, makine tarafından okunan kopya (taslak üretimi bunu kullanır).
    (out_dir / f"{BANK_STEM}.json").write_text(
        json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    cov = bank["coverage"]
    pages = cov.get("pages_total")
    pages_text = f"{pages} sayfa, " if pages else ""
    print(
        f"Kanıt bankası [{bank.get('engine', 'keyword')}]: "
        f"{cov['sources_found']}/{cov['sources_assigned']} kaynak, "
        f"{pages_text}{cov['quote_candidates']} alıntı adayı "
        f"({cov['sources_with_quotes']} kaynakta)."
    )
    print(f"Yazıldı: {out_dir / (BANK_STEM + '.json')}")
    if result["status"] != "unchanged":
        print(f"Yazıldı: {result['path']}")
        print(f"Yazıldı: {result['path'].with_suffix('.html')}")
    else:
        print(f"Değişiklik yok; mevcut sürüm korundu: {result['path']}")
    if cov["sources_found"] < cov["sources_assigned"]:
        print(
            f"DİKKAT: {cov['sources_assigned'] - cov['sources_found']} kaynağın PDF'i yok; "
            "o alt başlıkların kanıtı eksik kalacak.",
            file=sys.stderr,
        )
    print("Not: bu cümleler alıntı adayıdır; taslağa giren her cümle sayfa numarasıyla doğrulanır.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
