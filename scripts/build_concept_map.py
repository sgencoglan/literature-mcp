#!/usr/bin/env python3
"""Kavram haritası — başlıktan arama stratejisine.

Neden var
---------
Bir bölümün başlığı bir cümledir; arama motoruna verilebilecek bir yapı değildir.
Kullanıcının gündelik ifadesi alanyazındaki teknik terimi kaybettirebilir:
çerçevenin çekirdeği, yazıldığından farklı bir adla indeksleniyor olabilir. Bu
terim bulunmazsa arama kör kalır.

Bu betik başlığı/çerçeveyi kavram haritasına çevirir ve dört aşamada olgunlaştırır:

1. **Keşif** — kavramları alanyazından (OpenAlex anahtar sözcükleri) veya
   doğrulanmış tohum dosyasından alır; PubMed MeSH projeksiyonuyla kontrollü
   sözlüğe bağlar.
2. **Bağlama** — her kavramı plan alt başlıklarına bağlar; hangi bölümün anchor
   terimi eksik, hangi kavram hiçbir bölüme düşmemiş görünür.
3. **Sorgu ve kapsam** — her kavram için hedefli sorgular üretir ve havuz/atama/
   PDF kapsamını ölçer.
4. **Güncelleme** — akış 4'te fulltext okunurken beliren yeni kavramları haritaya
   ekler (kanıt bankasındaki başlık/özet/pasajlardan).

Kullanım:
    python3 scripts/build_concept_map.py <proje-kökü> --phase 1
    python3 scripts/build_concept_map.py <proje-kökü> --phase 2
    python3 scripts/build_concept_map.py <proje-kökü> --phase 3 --mesh
    python3 scripts/build_concept_map.py <proje-kökü> --phase 4
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
    from project_layout import workflow_dir
except ImportError:
    from scripts.project_layout import workflow_dir

SCHEMA_ID = "concept-map/1"
OUTPUT_STEM = "02_kavram_haritasi"
TARGET_WORKFLOW = "1"

ROLE_LABELS = {
    "anchor": "Çekirdek (anchor)",
    "component": "Yapı taşı",
    "context": "Bağlam",
    "outcome": "Sonuç",
}
STATUS_LABELS = {
    "covered": "kapsandı",
    "partial": "kısmi",
    "missing": "eksik",
    "not_checked": "denetlenmedi",
}
SOURCE_LABELS = {
    "user_stated": "kullanıcı belirtti",
    "derived": "başlıktan çıkarıldı",
    "literature": "alanyazında belirdi",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _norm(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in lowered if not unicodedata.combining(ch)).lower()


def _slug_terms(text: str) -> List[str]:
    return [t for t in re.split(r"[^\w]+", _norm(text)) if len(t) > 3]


# --------------------------------------------------------------------------- #
# Aşama 1 — kavram keşfi
# --------------------------------------------------------------------------- #

# Hangi kavram hangi veritabanında gerçekten indekslenir. Bu bilgi olmadan
# MeSH projeksiyonu yanlış alana kayar: bir terim PubMed'de başka bir alanın
# terimi olabilir; eğitim bağlamındaki karşılığı orada hiç indekslenmeyebilir.
DOMAIN_DATABASES: Dict[str, Dict[str, Any]] = {
    "education": {
        "databases": ["openalex", "semantic_scholar", "crossref", "eric"],
        "mesh_applicable": False,
        "note": (
            "Eğitim alanyazını PubMed'de indekslenmez; aynı terim orada başka "
            "bir alanın terimi olabilir. MeSH projeksiyonu bu kavramlar için "
            "yanıltıcıdır."
        ),
    },
    "medical": {
        "databases": ["pubmed", "europepmc", "openalex", "crossref"],
        "mesh_applicable": True,
        "note": "Klinik alanyazın; MeSH kontrollü sözlüğü burada yetkilidir.",
    },
    "psychology": {
        "databases": ["pubmed", "semantic_scholar", "openalex", "psycinfo"],
        "mesh_applicable": True,
        "note": "Psikoloji sınır alanı; MeSH kısmen kapsar, PsycINFO daha geniş.",
    },
}

def domain_for(concept: Dict[str, Any], default: str = "education") -> str:
    """Alanı kavramın **alanyazın kanıtından** çıkar; sabit terim tablosu yok.

    * Kavram kaydında açık ``domain`` varsa o kullanılır (proje verisi).
    * OpenAlex ``primary_topic.subfield`` alanı varsa oradan eşlenir.
    * Hiçbiri yoksa proje varsayılanı (``default``) kullanılır.

    MeSH varlığı **kanıt olarak kullanılmaz**: MeSH uygulanıp uygulanmayacağına
    karar veren alan bilgisi MeSH'ten önce gelmelidir, yoksa döngüsel olur.
    """
    explicit = str(concept.get("domain") or "").strip()
    if explicit in DOMAIN_DATABASES:
        return explicit
    subfield = str(concept.get("openalex_subfield") or "").lower()
    if subfield:
        if any(word in subfield for word in ("medic", "nurs", "psychiatr", "health")):
            return "medical"
        if "psycholog" in subfield:
            return "psychology"
        if any(word in subfield for word in ("educat", "teach")):
            return "education"
    return default


def apply_domains(concepts: List[Dict[str, Any]], default: str = "education") -> None:
    """Her kavrama alan ve yetkili veritabanlarını ata.

    ``default`` proje düzeyindedir (tıp projesi ``medical`` verir); kavram
    düzeyinde kanıt varsa o önceliklidir.
    """
    for concept in concepts:
        domain = domain_for(concept, default=default)
        spec = DOMAIN_DATABASES[domain]
        concept["domain"] = domain
        concept["authoritative_databases"] = list(spec["databases"])
        concept["mesh_applicable"] = bool(spec["mesh_applicable"])
        concept["domain_note"] = spec["note"]
        if not spec["mesh_applicable"] and concept.get("mesh"):
            concept["mesh_rejected"] = list(concept["mesh"])
            concept["mesh"] = []


def concepts_from_seed(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ajanın/kullanıcının verdiği kavram tohumlarını normalize et.

    Kavram listesi **proje verisidir**, repo kodu değil. Harita kavramları ya
    dışarıdan tohum olarak alır ya da alanyazından çıkarır; kodda projeye özgü
    sabit sözlük tutulmaz.
    """
    raw = seed.get("concepts") if isinstance(seed, dict) else seed
    if not isinstance(raw, list):
        return []
    concepts: List[Dict[str, Any]] = []
    for index, entry in enumerate(raw, start=1):
        if isinstance(entry, str):
            entry = {"term": entry, "english_terms": [entry]}
        if not isinstance(entry, dict):
            continue
        term = str(entry.get("term") or "").strip()
        english = [
            str(t).strip() for t in (entry.get("english_terms") or []) if str(t).strip()
        ]
        if not term and not english:
            continue
        concepts.append(
            {
                "id": str(entry.get("id") or f"C{index}"),
                "term": term or english[0],
                "role": str(entry.get("role") or "component"),
                "english_terms": english or [term],
                "variants": [str(v) for v in (entry.get("variants") or [])],
                "synonyms": [str(v) for v in (entry.get("synonyms") or [])],
                "mesh": [],
                "relations": entry.get("relations") or [],
                "source": str(entry.get("source") or "user_stated"),
                "definition_scope": str(entry.get("definition_scope") or ""),
                **({"domain": str(entry["domain"])} if entry.get("domain") else {}),
            }
        )
    return concepts


# Kavram çıkarımı: yazar etiketleri değil, başlık + özet metni. Yazar
# anahtar sözcükleri seyrek ve düzensiz; asıl teknik terim özetlerde geçer.
# Genel araştırma kalıpları kavram değildir; bunlar alan bağımsız oldukları
# için depo düzeyinde tutulabilir.
GENERIC_PHRASES = {
    "semi-structured", "semi structured", "collected through", "different types",
    "literature review", "systematic review", "scoping review", "focus groups",
    "in-depth interviews", "semi-structured interviews", "professional development",
    "training needs", "management strategies", "management practices",
    "pre-service", "in-service", "quantitative", "qualitative", "participants",
    "current study", "present study", "this study", "research questions",
}

GENERIC_WORDS = set(
    """the and for with that this from are was were been being have has had not
    but its their they them there these those such can may might will would could
    should about into over under between during before after above below more most
    less least other others than then when where which who whom whose also study
    studies research results findings however therefore moreover furthermore
    although while because both each some many much very well used using use based
    approach approaches method methods analysis data paper article journal
    university school schools student students teacher teachers education
    educational classroom teaching learning children child year years group groups
    time high low new two three first second""".split()
)


def _abstract_text(inverted: Optional[Dict[str, List[int]]]) -> str:
    if not inverted:
        return ""
    positions = [(index, word) for word, indexes in inverted.items() for index in indexes]
    return " ".join(word for _, word in sorted(positions))


def _candidate_grams(text: str) -> set[str]:
    """Metinden kavram adayı n-gramları çıkar.

    Tek sözcükler yalnızca tire içeriyorsa aday olur (``teacher-student`` gibi
    bileşik terimler tekniktir); düz tek sözcükler ("intervention") çok genel
    kalır. İki-üç sözcüklü öbekler adaydır.
    """
    words = re.findall(r"[a-z][a-z\-]{2,}", _norm(text))
    found: set[str] = set()
    for size in (1, 2, 3):
        for index in range(len(words) - size + 1):
            seq = words[index : index + size]
            if any(word in GENERIC_WORDS for word in seq):
                continue
            if size == 1 and "-" not in seq[0]:
                continue
            phrase = " ".join(seq)
            if phrase in GENERIC_PHRASES:
                continue
            if seq[-1].endswith(("based", "related", "focused", "oriented")):
                continue  # niteleyici, kavram değil ("school-based")
            found.add(phrase)
    return found


def _fetch_corpus(query: str, limit: int) -> List[Dict[str, Any]]:
    """OpenAlex'ten başlık + özeti olan kayıtları çek."""
    import asyncio

    try:
        sys.path.insert(
            0,
            str(Path(__file__).resolve().parents[1] / "packages" / "sciencedirect-meta" / "src"),
        )
        from sciencedirect_meta.server import _openalex_params, polite_get
    except Exception:  # noqa: BLE001 - paket yoksa harita literatürsüz kurulur
        return []

    async def _run() -> List[Dict[str, Any]]:
        response = await polite_get(
            "https://api.openalex.org/works",
            params=_openalex_params(
                {
                    "search": query,
                    "per-page": max(1, min(limit, 100)),
                    "select": "id,title,doi,publication_year,abstract_inverted_index,primary_topic",
                }
            ),
            attempts=3,
        )
        if response.status_code != 200:
            return []
        return response.json().get("results") or []

    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001
        return []


def _corpus_stats(works: List[Dict[str, Any]]) -> tuple[Dict[str, int], Dict[str, int], int]:
    """Aday terim başına belge sıklığı ve başlık sıklığı."""
    doc_freq: Dict[str, int] = {}
    title_freq: Dict[str, int] = {}
    usable = [w for w in works if w.get("abstract_inverted_index")]
    for work in usable:
        grams = _candidate_grams(
            f"{work.get('title') or ''} {_abstract_text(work.get('abstract_inverted_index'))}"
        )
        for gram in grams:
            doc_freq[gram] = doc_freq.get(gram, 0) + 1
        for gram in _candidate_grams(work.get("title") or ""):
            title_freq[gram] = title_freq.get(gram, 0) + 1
    return doc_freq, title_freq, len(usable)


def mine_candidates(
    query: str,
    background_query: str = "classroom",
    min_count: int = 3,
    limit: int = 14,
) -> Dict[str, Any]:
    """Alanyazından kavram adaylarını çıkar ve ayırt ediciliğe göre sırala.

    Yöntem:

    * Hedef külliyat: sorgunun ilk 50 sonucu (başlık + özet).
    * Arka plan külliyatı: aynı alanın genel sorgusu (varsayılan ``classroom``).
    * Aday, hedef külliyatta en az ``min_count`` makalede geçmeli.
    * Ayırt edicilik = hedef oran / arka plan oranı. Genel terimler her iki
      külliyatta da geçtiği için düşer; alana özgü teknik terimler öne çıkar.
    * Başlıkta geçen aday ek puan alır: başlık, makalenin asıl konusunu söyler.

    Dönen ``candidates`` listesi ajanın doğrulaması içindir; hiçbiri kendiliğinden
    "doğru kavram" ilan edilmez.
    """
    target = _fetch_corpus(query, 50)
    background = _fetch_corpus(background_query, 100)
    doc_freq, title_freq, target_n = _corpus_stats(target)
    bg_freq, _, bg_n = _corpus_stats(background)

    if target_n == 0:
        return {"query": query, "candidates": [], "sample_size": 0, "note": "hedef külliyat boş"}

    examples: Dict[str, List[str]] = {}
    for work in target:
        if not work.get("abstract_inverted_index"):
            continue
        grams = _candidate_grams(
            f"{work.get('title') or ''} {_abstract_text(work.get('abstract_inverted_index'))}"
        )
        for gram in grams:
            bucket = examples.setdefault(gram, [])
            title = str(work.get("title") or "").strip()
            if title and len(bucket) < 2:
                bucket.append(title)

    candidates = []
    for gram, count in doc_freq.items():
        if count < min_count:
            continue
        target_share = count / target_n
        background_share = bg_freq.get(gram, 0) / max(1, bg_n)
        ratio = target_share / (background_share + 0.004)
        score = ratio * (1 + 2 * title_freq.get(gram, 0))
        candidates.append(
            {
                "term": gram,
                "documents": count,
                "sample_size": target_n,
                "share": round(target_share, 3),
                "background_share": round(background_share, 3),
                "title_hits": title_freq.get(gram, 0),
                "specificity": round(ratio, 1),
                "score": round(score, 1),
                "examples": examples.get(gram, []),
            }
        )
    candidates.sort(key=lambda row: (-row["score"], -row["documents"], row["term"]))
    return {
        "query": query,
        "background_query": background_query,
        "candidates": candidates[:limit],
        "sample_size": target_n,
        "background_size": bg_n,
        "note": None,
    }


def derive_concepts_from_literature(
    framing: str,
    title: str,
    min_share: float = 0.05,
    max_concepts: int = 10,
    query_en: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    """Başlık/çerçeveden alanyazın taramasıyla kavram çıkar.

    Projeye özgü sabit sözlük kullanılmaz. Adaylar başlık + özet metninden
    çıkarılır ve genel alan külliyatına karşı ayırt edicilikle sıralanır.
    İlk sıradaki aday anchor olur; geri kalanı bileşen.

    Türkçe sorgu İngilizce veritabanıyla eşleşmez. Bu durumda örneklem boş
    kalır ve fonksiyon bunu açıkça bildirir; kavramlar ``--concept-seed`` ile
    verilmelidir.
    """
    query = (query_en or " ".join(part for part in (title, framing) if part)).strip()
    if not query:
        return [], "Boş başlık/çerçeve; kavram çıkarılamadı.", {"candidates": []}

    mined = mine_candidates(query)
    candidates = mined.get("candidates") or []
    sample = int(mined.get("sample_size") or 0)

    concepts: List[Dict[str, Any]] = []
    note_parts: List[str] = []

    if sample >= 5:
        kept = [row for row in candidates if row["share"] >= min_share]
        for index, row in enumerate(kept[:max_concepts], start=1):
            concepts.append(
                {
                    "id": f"C{index}",
                    "term": row["term"],
                    "role": "anchor" if index == 1 else "component",
                    "english_terms": [row["term"]],
                    "variants": [],
                    "synonyms": [],
                    "mesh": [],
                    "relations": [],
                    "source": "literature",
                    "definition_scope": (
                        f"Hedef külliyatta {row['documents']}/{row['sample_size']} "
                        f"makalede geçti; genel alana göre ayırt edicilik "
                        f"{row['specificity']}×."
                    ),
                }
            )
        note_parts.append(
            f"Kavramlar başlık+özet metninden çıkarıldı (OpenAlex, {sample} "
            f"makale, ayırt edicilik eşiği %{min_share * 100:.0f}). Projeye "
            "özgü sabit sözlük kullanılmadı."
        )
    elif sample:
        note_parts.append(
            f"UYARI: OpenAlex yalnızca {sample} özetli makale döndürdü. Sorgu "
            "büyük olasılıkla İngilizce değil; kavram çıkarımı güvenilir değil. "
            "`--concept-seed` ile kavramları verin veya `--query-en` ile "
            "İngilizce sorgu girin."
        )

    if not concepts:
        concepts = [
            {
                "id": "C1",
                "term": title or framing,
                "role": "anchor",
                "english_terms": _slug_terms(title or framing)[:3] or [title or framing],
                "variants": [],
                "synonyms": [],
                "mesh": [],
                "relations": [],
                "source": "derived",
                "definition_scope": "Alanyazın taraması yapılamadı; başlık anchor alındı.",
            }
        ]
        if sample < 5:
            note_parts.append(
                "OpenAlex taraması güvenilir sonuç vermedi; başlık anchor alındı."
            )

    return concepts, " ".join(note_parts), mined


def attach_mesh(concepts: List[Dict[str, Any]], mesh_results: Dict[str, Any]) -> None:
    """MeSH projeksiyonunu kavramlara bağla."""
    for concept in concepts:
        if concept.get("mesh_applicable") is False:
            continue  # bu alan PubMed'de indekslenmiyor; MeSH yanıltır
        primary = (concept.get("english_terms") or [""])[0]
        result = mesh_results.get(primary)
        if not result or not result.get("found"):
            continue
        descriptors = [
            row["term"]
            for row in result.get("mesh_terms") or []
            if row.get("count", 0) >= 2
        ][:6]
        concept["mesh"] = descriptors
        # MeSH'ten gelen ek arama terimleri: İngilizce karşılık listesini genişlet.
        for term in descriptors:
            if term.lower() not in {t.lower() for t in concept["english_terms"]}:
                concept["english_terms"].append(term)


# --------------------------------------------------------------------------- #
# Aşama 2 — plana bağlama
# --------------------------------------------------------------------------- #

def link_sections(
    concepts: List[Dict[str, Any]], plan: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Her kavramı, terimleri geçen alt başlıklara bağla."""
    if not plan:
        return []
    sections = [s for s in plan.get("sections") or [] if isinstance(s, dict)]
    for concept in concepts:
        terms = [concept["term"]] + list(concept.get("english_terms") or [])
        needles = [_norm(t) for t in terms if t]
        matched = []
        for section in sections:
            haystack = _norm(
                " ".join(
                    str(x)
                    for x in (
                        section.get("heading"),
                        section.get("purpose"),
                        " ".join(section.get("search_terms") or []),
                    )
                )
            )
            if any(needle in haystack for needle in needles):
                matched.append(str(section.get("id") or ""))
        concept["sections"] = matched

    coverage = []
    for section in sections:
        sid = str(section.get("id") or "")
        linked = [c["id"] for c in concepts if sid in (c.get("sections") or [])]
        has_anchor = any(
            c["role"] == "anchor" for c in concepts if c["id"] in linked
        )
        if not linked:
            status = "concept_missing"
        elif not has_anchor:
            status = "anchor_missing"
        else:
            status = "ok"
        coverage.append(
            {
                "section_id": sid,
                "heading": str(section.get("heading") or ""),
                "concept_ids": linked,
                "has_anchor": has_anchor,
                "status": status,
            }
        )
    return coverage


# --------------------------------------------------------------------------- #
# Aşama 3 — sorgu ve kapsam
# --------------------------------------------------------------------------- #

def build_queries(concepts: List[Dict[str, Any]]) -> None:
    """Her kavram için hedefli sorgular üret."""
    for concept in concepts:
        queries: List[Dict[str, Any]] = []
        primary = (concept.get("english_terms") or [""])[0]
        if not primary:
            concept["queries"] = queries
            continue
        # 1) Anchor terim yalnız başına: genel terimlerle seyreltilmesin.
        queries.append(
            {
                "query": primary,
                "databases": ["pubmed", "openalex", "semantic_scholar"],
                "note": "Kavram tek başına; genel terimlerle karıştırılmadan.",
                "status": "not_run",
                "result_count": None,
            }
        )
        # 2) MeSH terimleri birlikte: kontrollü sözlük genişletmesi.
        mesh = concept.get("mesh") or []
        if mesh:
            queries.append(
                {
                    "query": " OR ".join(f'"{m}"' for m in mesh[:3]),
                    "databases": ["pubmed", "openalex"],
                    "note": "MeSH projeksiyonu: kontrollü sözlük terimleri.",
                    "status": "not_run",
                    "result_count": None,
                }
            )
        # 3) Bağlamla birlikte: eğitim bağlamına yerleştirme.
        context_terms = [
            c["english_terms"][0]
            for c in concepts
            if c["role"] == "context" and c.get("english_terms")
        ]
        if context_terms:
            queries.append(
                {
                    "query": f"{primary} {context_terms[0]}",
                    "databases": ["openalex", "semantic_scholar", "crossref"],
                    "note": "Kavram + bağlam; kavramın bu alanda kullanımı.",
                    "status": "not_run",
                    "result_count": None,
                }
            )
        concept["queries"] = queries


def measure_coverage(
    concepts: List[Dict[str, Any]],
    pool: Optional[Dict[str, Any]],
    assigned: Optional[set[str]],
    evidence_bank: Optional[Dict[str, Any]],
) -> None:
    """Havuz, atama ve PDF kapsamını kavram bazında ölç."""
    records = (pool or {}).get("records") or (pool or {}).get("candidates") or []
    assigned = assigned or set()
    bank_sources = (evidence_bank or {}).get("sources") or []
    total_pdfs = len([s for s in bank_sources if s.get("exists")])

    for concept in concepts:
        patterns = [_compile_variant(t) for t in _all_terms(concept)]
        patterns = [p for p in patterns if p]
        in_pool = 0
        in_assigned = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            haystack = f"{record.get('title') or ''} {record.get('abstract') or ''}"
            if any(p.search(haystack) for p in patterns):
                in_pool += 1
                doi = str(record.get("doi") or "").strip().lower()
                if doi in assigned:
                    in_assigned += 1
        pdf_hits = 0
        for source in bank_sources:
            if not source.get("exists"):
                continue
            text = " ".join(
                str(q.get("text") or "") for q in source.get("quotes") or []
            )
            if any(p.search(text) for p in patterns):
                pdf_hits += 1

        if not patterns:
            status = "not_checked"
        elif in_pool == 0:
            status = "missing"
        elif in_assigned == 0:
            status = "partial"
        elif total_pdfs and pdf_hits == 0:
            status = "partial"
        else:
            status = "covered"

        concept["coverage"] = {
            "pool_records": in_pool,
            "assigned_records": in_assigned,
            "pdf_with_term": pdf_hits,
            "status": status,
        }


def _all_terms(concept: Dict[str, Any]) -> List[str]:
    terms = [concept.get("term") or ""]
    terms.extend(concept.get("english_terms") or [])
    terms.extend(concept.get("synonyms") or [])
    terms.extend(concept.get("variants") or [])
    terms.extend(concept.get("mesh") or [])
    return [t for t in terms if t]


def _compile_variant(term: str) -> Optional[re.Pattern[str]]:
    words = [re.escape(w) for w in re.split(r"[\s\-_]+", _norm(term)) if w]
    if not words:
        return None
    body = r"[\s\-_]*".join(words)
    if len(words) > 1:
        body = f"(?:{body}|{''.join(words)})"
    return re.compile(rf"\b{body}\b", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Aşama 4 — fulltext okumasından güncelleme
# --------------------------------------------------------------------------- #

def update_from_literature(
    concepts: List[Dict[str, Any]],
    evidence_bank: Optional[Dict[str, Any]],
    min_count: int = 3,
) -> List[str]:
    """Kanıt bankasındaki pasajlarda sık geçen, haritada olmayan kavramları ekle.

    Akış 4'te tam metin okunurken alanyazının kendi kavramları belirir. Bunlar
    "literature" kaynaklı olarak haritaya eklenir; kullanıcının çerçevesinde
    olmayan ama kaynakların ısrarla kullandığı terimler böylece görünür olur.
    """
    sources = (evidence_bank or {}).get("sources") or []
    known = {_norm(t) for c in concepts for t in _all_terms(c)}
    counts: Dict[str, int] = {}

    # Tek terimler ve ikili öbekler ayrı ayrı sayılır. Tek bir "2-3 sözcüklü
    # öbek" kalıbı kullanmak yanıltıcı: aynı kavram her cümlede farklı devam
    # sözcüğüyle geçtiğinde sayaç hiçbir zaman eşiğe ulaşmaz.
    word = re.compile(r"[a-z][a-z\-]{4,}")
    stop = {
        "which", "there", "these", "those", "their", "about", "would", "could",
        "should", "other", "where", "while", "after", "before", "between",
        "students", "student", "teachers", "teacher", "study", "studies",
        "research", "findings", "results", "however", "therefore", "moreover",
        # Genel akademik sözcükler kavram değildir; tek başına haritaya girmez.
        "classroom", "school", "schools", "management", "behavior", "behaviour",
        "practice", "practices", "support", "supports", "intervention",
        "interventions", "education", "educational", "positive", "negative",
        "significant", "associated", "increased", "decreased", "evidence",
        "approach", "approaches", "strategies", "strategy", "outcomes", "outcome",
        "children", "child", "years", "level", "levels", "forms", "based",
    }
    for source in sources:
        text = _norm(" ".join(str(q.get("text") or "") for q in source.get("quotes") or []))
        words = [w for w in word.findall(text) if w not in stop]
        for token in words:
            if token in known:
                continue
            counts[token] = counts.get(token, 0) + 1
        for index in range(len(words) - 1):
            bigram = f"{words[index]} {words[index + 1]}"
            if bigram in known:
                continue
            counts[bigram] = counts.get(bigram, 0) + 1

    # İkili öbekler tek sözcüklerden daha bilgilendirici: "classroom
    # management" bir kavramdır, "classroom" değildir. Aynı sayımda geçen ve
    # bir öbeğin parçası olan tek sözcük eklenmez.
    added: List[str] = []
    chosen: List[str] = []
    ordered = sorted(counts.items(), key=lambda x: (-len(x[0].split()), -x[1], x[0]))
    for candidate, count in ordered:
        if count < min_count or len(added) >= 5:
            continue
        if len(candidate.split()) == 1 and any(
            candidate in phrase.split() for phrase in chosen
        ):
            continue  # öbeğin parçası; tek başına ekleme
        if candidate in chosen:
            continue
        chosen.append(candidate)
        concepts.append(
            {
                "id": f"C{len(concepts) + 1}",
                "term": candidate,
                "role": "component",
                "english_terms": [candidate],
                "variants": [],
                "synonyms": [],
                "mesh": [],
                "relations": [],
                "source": "literature",
                "definition_scope": (
                    f"Tam metin okumasında {count} kaynakta geçti; haritaya "
                    "alanyazından eklendi."
                ),
            }
        )
        added.append(candidate)
    return added


# --------------------------------------------------------------------------- #
# Rapor
# --------------------------------------------------------------------------- #

def build_report(
    plan: Dict[str, Any],
    phase: int,
    framing: str,
    concepts: List[Dict[str, Any]],
    section_coverage: Optional[List[Dict[str, Any]]] = None,
    title: Optional[str] = None,
    derivation_note: str = "",
    mined: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    warnings: List[str] = []
    anchors = [c for c in concepts if c["role"] == "anchor"]
    seedless = [c for c in concepts if c.get("source") in {"literature", "derived"}]
    if seedless and not any(c.get("source") == "user_stated" for c in concepts):
        warnings.append(
            "Kavramların hiçbiri kullanıcı/ajan tarafından doğrulanmadı; hepsi "
            "otomatik türetildi. Alanyazın terimi (anchor) için `--concept-seed` "
            "ile doğrulanmış liste verin."
        )
    if not anchors:
        warnings.append(
            "Anchor terim tanımlı değil. Bölümün kavramsal çekirdeği "
            "alanyazındaki adıyla yazılmalı."
        )
    elif all(c.get("source") == "literature" for c in concepts):
        warnings.append(
            f"Anchor otomatik önerildi: '{anchors[0].get('term')}'. Bu bir "
            "sıralama sonucudur, doğrulanmış çekirdek değildir. Adayları "
            "sorguyla sına: anchor, bölümün asıl konusunu getiren terim "
            "olmalı. Doğrulanmış listeyi `--concept-seed` ile ver."
        )
    for concept in concepts:
        if concept.get("mesh") and concept.get("mesh_applicable") is False:
            warnings.append(
                f"'{concept['term']}' için MeSH terimi var ama alan eğitim: "
                "PubMed'deki karşılığı başka bir anlama geliyor, kullanma."
            )
        coverage = concept.get("coverage") or {}
        if coverage.get("status") == "missing":
            warnings.append(
                f"'{concept['term']}' hiçbir havuz kaydında geçmiyor; "
                "kavram-önce arama yapılmalı."
            )
        elif coverage.get("status") == "partial" and coverage.get("pool_records", 0) > 0:
            warnings.append(
                f"'{concept['term']}' havuzda {coverage['pool_records']} kayıtta var "
                f"ama {coverage.get('assigned_records', 0)} tanesi atanmış."
            )
    if section_coverage:
        for row in section_coverage:
            if row["status"] == "concept_missing":
                warnings.append(
                    f"{row['section_id']} hiçbir kavrama bağlanmadı: {row['heading']}"
                )
            elif row["status"] == "anchor_missing":
                warnings.append(
                    f"{row['section_id']} bir kavrama bağlı ama anchor terim yok: "
                    f"{row['heading']}"
                )

    next_actions = []
    if phase == 1:
        next_actions.append(
            "Aday listesini ve kavramları kullanıcıyla doğrula; eksik alan "
            "terimini sor."
        )
        next_actions.append(
            "MeSH projeksiyonu için `--mesh` ver; kontrollü sözlük terimleri eklensin."
        )
    elif phase == 2:
        next_actions.append(
            "Anchor terimsiz alt başlıkları düzelt veya gerekçelendir."
        )
        next_actions.append(
            "Eksik kavramları plan search_terms alanına ekle."
        )
    elif phase == 3:
        next_actions.append(
            "`missing` kavramlar için sorguları çalıştır ve havuza ekle."
        )
        next_actions.append(
            "`partial` kavramlarda anchor kaydı atamaya al."
        )
    else:
        next_actions.append(
            "Yeni eklenen kavramları doğrula; gerekirse akış 3'e dönüp ara."
        )

    return {
        "schema": SCHEMA_ID,
        "project": plan.get("project"),
        "title": title or plan.get("title") or "",
        "phase": phase,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "genre": plan.get("genre"),
        "user_framing": framing,
        "derivation_note": derivation_note,
        "concepts": concepts,
        "candidates": (mined or {}).get("candidates") or [],
        "candidate_query": (mined or {}).get("query"),
        "candidate_background": (mined or {}).get("background_query"),
        "section_coverage": section_coverage or [],
        "warnings": warnings,
        "next_actions": next_actions,
    }


def render_html(report: Dict[str, Any]) -> str:
    concepts = report["concepts"]
    anchors = [c for c in concepts if c.get("role") == "anchor"]

    def concept_card(concept: Dict[str, Any]) -> str:
        role = concept.get("role", "component")
        eng = "".join(
            f"<code>{esc(t)}</code> " for t in concept.get("english_terms") or []
        )
        variants = "".join(
            f'<span class="variant">{esc(v)}</span>' for v in concept.get("variants") or []
        )
        mesh = "".join(f'<span class="mesh">{esc(m)}</span>' for m in concept.get("mesh") or [])
        queries = "".join(
            f'<li><code>{esc(q.get("query"))}</code> '
            f'<span class="muted">({esc(", ".join(q.get("databases") or []))})</span></li>'
            for q in concept.get("queries") or []
        )
        domain = concept.get("domain")
        domain_html = ""
        if domain:
            dbs = ", ".join(concept.get("authoritative_databases") or [])
            mesh_flag = (
                "MeSH uygun" if concept.get("mesh_applicable") else "MeSH uygun değil"
            )
            domain_html = (
                f'<div class="row"><span class="lbl">Alan</span><div>'
                f'<strong>{esc(domain)}</strong> · yetkili: {esc(dbs)} · '
                f'<span class="muted">{esc(mesh_flag)}</span></div></div>'
            )
        cov = concept.get("coverage") or {}
        cov_html = ""
        if cov:
            cov_html = (
                f'<p class="cov {esc(cov.get("status"))}">'
                f'Kapsam: <strong>{esc(STATUS_LABELS.get(cov.get("status"), cov.get("status")))}</strong> · '
                f'havuz {cov.get("pool_records")} · atanmış {cov.get("assigned_records")} · '
                f'PDF {cov.get("pdf_with_term")}</p>'
            )
        sections = "".join(
            f'<span class="sec">{esc(s)}</span>' for s in concept.get("sections") or []
        )
        rel = "".join(
            f'<li>{esc(r.get("type"))} → {esc(r.get("target"))}'
            + (f' <span class="muted">{esc(r.get("note"))}</span>' if r.get("note") else "")
            + "</li>"
            for r in concept.get("relations") or []
        )
        return f"""
        <article class="concept role-{esc(role)}">
          <header>
            <span class="cid">{esc(concept.get("id"))}</span>
            <h3>{esc(concept.get("term"))}</h3>
            <span class="role">{esc(ROLE_LABELS.get(role, role))}</span>
            <span class="src">{esc(SOURCE_LABELS.get(concept.get("source"), concept.get("source") or ""))}</span>
          </header>
          {f'<p class="scope">{esc(concept.get("definition_scope"))}</p>' if concept.get("definition_scope") else ''}
          {domain_html}
          <div class="row"><span class="lbl">İngilizce</span><div>{eng or '<span class="muted">—</span>'}</div></div>
          {f'<div class="row"><span class="lbl">Varyant</span><div>{variants}</div></div>' if variants else ''}
          {f'<div class="row"><span class="lbl">MeSH</span><div>{mesh}</div></div>' if mesh else ''}
          {f'<div class="row"><span class="lbl">Bölümler</span><div>{sections}</div></div>' if sections else ''}
          {f'<div class="row"><span class="lbl">İlişkiler</span><ul class="rel">{rel}</ul></div>' if rel else ''}
          {f'<div class="row"><span class="lbl">Sorgular</span><ol class="queries">{queries}</ol></div>' if queries else ''}
          {cov_html}
        </article>"""

    section_rows = ""
    for row in report.get("section_coverage") or []:
        cls = "ok" if row["status"] == "ok" else "warn"
        section_rows += (
            f"<tr class='{cls}'><td>{esc(row['section_id'])}</td>"
            f"<td>{esc(row['heading'])}</td>"
            f"<td>{esc(', '.join(row['concept_ids']) or '—')}</td>"
            f"<td>{'✅' if row['has_anchor'] else '❌'}</td></tr>"
        )
    section_block = (
        "<h2>Alt başlık kapsaması</h2>"
        "<table><thead><tr><th>#</th><th>Başlık</th><th>Kavramlar</th>"
        f"<th>Anchor</th></tr></thead><tbody>{section_rows}</tbody></table>"
        if section_rows
        else ""
    )

    candidate_rows = ""
    for row in report.get("candidates") or []:
        example = row.get("examples") or []
        example_html = (
            f'<div class="muted">{esc(example[0])}</div>' if example else ""
        )
        candidate_rows += (
            f"<tr><td><code>{esc(row['term'])}</code>{example_html}</td>"
            f"<td>{row['documents']}/{row['sample_size']}</td>"
            f"<td>{row['title_hits']}</td>"
            f"<td>{row['specificity']}×</td>"
            f"<td>{row['score']}</td></tr>"
        )
    candidate_block = (
        "<h2>Alanyazından kavram adayları</h2>"
        f"<p class=\"muted\">Sorgu: <code>{esc(report.get('candidate_query') or '')}</code> · "
        f"arka plan: <code>{esc(report.get('candidate_background') or '')}</code>. "
        "Adaylar başlık+özet metninden çıkarıldı; genel alana göre ayırt "
        "edicilikle sıralandı. Hiçbiri kendiliğinden doğru kavram değildir — "
        "doğrulama ajanın/kullanıcının işidir.</p>"
        "<table><thead><tr><th>Aday</th><th>Belge</th><th>Başlık</th>"
        f"<th>Ayırt edicilik</th><th>Puan</th></tr></thead><tbody>{candidate_rows}</tbody></table>"
        if candidate_rows
        else ""
    )

    warnings = "".join(f"<li>{esc(w)}</li>" for w in report.get("warnings") or [])
    actions = "".join(f"<li>{esc(a)}</li>" for a in report.get("next_actions") or [])
    anchor_line = ", ".join(
        f"<code>{esc(a.get('english_terms', [''])[0])}</code>" for a in anchors
    ) or '<span class="muted">tanımlı değil</span>'

    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kavram haritası — {esc(report.get("title") or "")}</title>
<style>
:root{{--ink:#202833;--muted:#5b6b7b;--line:#d9e0e7;--soft:#f4f7fa;--blue:#174f82;
--amber:#9a6400;--green:#1e7d4f;--red:#b3261e}}
*{{box-sizing:border-box}}body{{max-width:1000px;margin:0 auto;padding:2rem 1.2rem 4rem;
color:var(--ink);font:16px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif}}
h1{{font-size:1.45rem;line-height:1.25}}h2{{font-size:1.05rem;margin:2rem 0 .6rem}}
.muted{{color:var(--muted);font-size:.88rem}}
.hero{{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:1rem 1.2rem;margin:1rem 0}}
.hero .big{{font-size:.95rem}}
.concept{{border:1px solid var(--line);border-left-width:4px;border-radius:9px;
padding:.9rem 1.1rem;margin:.9rem 0;background:#fff}}
.concept.role-anchor{{border-left-color:var(--red);background:#fffdfd}}
.concept.role-component{{border-left-color:var(--blue)}}
.concept.role-context{{border-left-color:var(--amber)}}
.concept.role-outcome{{border-left-color:var(--green)}}
.concept header{{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}}
.concept h3{{font-size:1rem;margin:0}}
.cid{{background:var(--soft);border-radius:5px;padding:.05rem .4rem;font-weight:700;font-size:.8rem}}
.role{{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}}
.src{{font-size:.72rem;color:var(--muted);margin-left:auto}}
.scope{{font-size:.86rem;color:var(--muted);margin:.4rem 0}}
.row{{display:flex;gap:.6rem;margin:.35rem 0;font-size:.86rem}}
.lbl{{flex:0 0 88px;color:var(--muted);font-weight:600;font-size:.78rem;
text-transform:uppercase;letter-spacing:.03em}}
code{{background:var(--soft);border:1px solid var(--line);border-radius:4px;
padding:.05rem .3rem;font-size:.83rem}}
.variant{{background:#f0f4f8;border-radius:4px;padding:.05rem .35rem;font-size:.78rem;margin-right:.2rem}}
.mesh{{background:#e8f3ec;color:var(--green);border-radius:4px;padding:.05rem .35rem;
font-size:.78rem;margin-right:.2rem}}
.sec{{display:inline-block;background:var(--soft);border-radius:4px;padding:.05rem .4rem;
font-size:.78rem;margin-right:.2rem}}
ul.rel,ol.queries{{margin:.2rem 0;padding-left:1.1rem}}
ul.rel li,ol.queries li{{margin:.15rem 0}}
.cov{{font-size:.83rem;margin:.5rem 0 0;padding:.35rem .6rem;border-radius:6px}}
.cov.covered{{background:#e2f4ea;color:var(--green)}}
.cov.partial{{background:#fff4d6;color:var(--amber)}}
.cov.missing{{background:#fde8e6;color:var(--red)}}
table{{width:100%;border-collapse:collapse;font-size:.86rem;margin:.5rem 0}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .45rem;text-align:left}}
th{{font-size:.72rem;text-transform:uppercase;color:var(--muted)}}
tr.warn td{{background:#fffaf2}}
ul.warn{{background:#fff4d6;border:1px solid #f0e2b6;border-radius:8px;padding:1rem 1rem 1rem 2rem}}
ul.act{{padding-left:1.2rem}}
@media print{{body{{max-width:none;padding:.4in}}.concept{{break-inside:avoid}}}}
</style></head><body>
<h1>Kavram haritası — aşama {report["phase"]}</h1>
<p class="muted">{esc(report.get("title") or "")} · {esc(report.get("project") or "")}</p>

<div class="hero">
  <div class="big"><strong>Anchor terim:</strong> {anchor_line}</div>
  <div class="big muted">Kullanıcı çerçevesi: {esc(report.get("user_framing") or "—")}</div>
  {f'<p class="muted">{esc(report.get("derivation_note"))}</p>' if report.get("derivation_note") else ''}
</div>

<h2>Kavramlar ({len(concepts)})</h2>
{''.join(concept_card(c) for c in concepts)}

{section_block}

{candidate_block}

{f'<h2>Uyarılar</h2><ul class="warn">{warnings}</ul>' if warnings else ''}
<h2>Sonraki adımlar</h2>
<ul class="act">{actions}</ul>
</body></html>"""


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def load_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Başlığı kavram haritasına çevirir; 1-4 aşamalı."
    )
    parser.add_argument("project_root", type=Path, help="Proje kökü")
    parser.add_argument(
        "--phase", type=int, default=1, choices=[1, 2, 3, 4],
        help="1 keşif, 2 plana bağlama, 3 sorgu+kapsam, 4 fulltext güncellemesi",
    )
    parser.add_argument("--title", help="Başlık (verilmezse plandan okunur)")
    parser.add_argument("--framing", help="Kullanıcının kendi ifadesi")
    parser.add_argument(
        "--concept-seed",
        type=Path,
        help=(
            "Kavram tohumları (proje verisi). Verilmezse kavramlar alanyazından "
            "çıkarılır; kodda projeye özgü sabit sözlük tutulmaz."
        ),
    )
    parser.add_argument(
        "--query-en",
        help=(
            "Kavram çıkarımı için İngilizce sorgu. Türkçe başlık İngilizce "
            "veritabanlarıyla eşleşmez; bu nedenle önerilir."
        ),
    )
    parser.add_argument(
        "--min-share",
        type=float,
        default=0.05,
        help=(
            "Kavramın alanyazın örnekleminde geçme oranı eşiği (varsayılan 0.05). "
            "Ayırt edicilik ayrıca ölçülür; eşik tek başına yeterli değildir."
        ),
    )
    parser.add_argument(
        "--domain",
        choices=sorted(DOMAIN_DATABASES),
        default=None,
        help=(
            "Projenin alanı. Kavram düzeyinde kanıt yoksa bu kullanılır; MeSH "
            "yalnızca medical/psychology alanlarında uygulanır."
        ),
    )
    parser.add_argument("--mesh", action="store_true", help="PubMed MeSH projeksiyonu yap")
    parser.add_argument("--plan", type=Path, help="Yazım planı JSON")
    parser.add_argument("--input", type=Path, help="Önceki kavram haritası (aşama zinciri)")
    parser.add_argument("-o", "--output-dir", type=Path, help="Çıktı klasörü")
    parser.add_argument("--check", action="store_true", help="Yalnızca özet")
    parser.add_argument("--force", action="store_true")
    add_timestamp_argument(parser)
    args = parser.parse_args(argv)

    root = args.project_root.expanduser().resolve()
    work1 = workflow_dir(root, "1")
    plan = load_json(args.plan or (workflow_dir(root, "2") / "01_yazim_plani.json"))

    # Önceki harita varsa kavramları ondan devral.
    seed = load_json(args.concept_seed)
    previous = load_json(args.input)
    mined: Dict[str, Any] = {"candidates": []}
    if previous is None:
        for candidate in sorted(work1.glob(f"{OUTPUT_STEM}_*.json")):
            previous = load_json(candidate)
        previous = previous or load_json(work1 / f"{OUTPUT_STEM}.json")

    title = args.title or (plan or {}).get("title") or (previous or {}).get("title") or ""
    framing = (
        args.framing
        or (previous or {}).get("user_framing")
        or ""
    )

    if previous and previous.get("concepts"):
        concepts = previous["concepts"]
        for index, concept in enumerate(concepts, start=1):
            concept.setdefault("id", f"C{index}")
    elif seed:
        concepts = concepts_from_seed(seed)
        derivation_note = (
            f"Kavramlar tohum dosyasından alındı: {args.concept_seed}"
        )
    else:
        concepts, derivation_note, mined = derive_concepts_from_literature(
            framing, title, min_share=args.min_share, query_en=args.query_en
        )

    project_domain = args.domain or (seed or {}).get("domain") or "education"
    if args.phase == 1:
        apply_domains(concepts, default=project_domain)
        if args.mesh:
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "sciencedirect-meta" / "src"))
                import asyncio

                from sciencedirect_meta import mesh as mesh_mod

                applicable = [c for c in concepts if c.get("mesh_applicable")]
                skipped = [c for c in concepts if not c.get("mesh_applicable")]
                # Alan bağlamı: bir terim tek başına başka alana kayabilir.
                # Proje bağlamı verilmişse MeSH projeksiyonu ona daraltılır.
                context_terms = [
                    str(t).strip()
                    for t in ((seed or {}).get("context_terms") or [])
                    if str(t).strip()
                ]

                async def _run() -> Dict[str, Any]:
                    out = {}
                    for concept in applicable:
                        primary = (concept.get("english_terms") or [""])[0]
                        if primary:
                            out[primary] = await mesh_mod.concepts_from_pubmed(
                                primary,
                                limit=20,
                                min_share=0.25,
                                context_terms=context_terms or None,
                            )
                    return out

                mesh_results = asyncio.run(_run()) if applicable else {}
                attach_mesh(concepts, mesh_results)
                found = sum(1 for c in concepts if c.get("mesh"))
                parts = [
                    f"MeSH projeksiyonu: {found}/{len(applicable)} uygun kavram "
                    "için kontrollü sözlük terimi bulundu." if applicable
                    else "MeSH projeksiyonu: bu haritadaki kavramların hiçbiri "
                         "PubMed'de indekslenmiyor."
                ]
                if skipped:
                    parts.append(
                        f"{len(skipped)} kavram atlandı ("
                        + ", ".join(c["term"] for c in skipped)
                        + "): eğitim alanyazını PubMed'de indekslenmez, MeSH "
                          "burada yanıltıcı olur."
                    )
                derivation_note = " ".join(parts)
            except Exception as exc:  # noqa: BLE001
                derivation_note = f"MeSH projeksiyonu atlandı: {str(exc)[:120]}"

    section_coverage = None
    if args.phase >= 2:
        section_coverage = link_sections(concepts, plan)

    if args.phase >= 3:
        build_queries(concepts)
        pool = load_json(workflow_dir(root, "3") / "00_doi_havuzu.json")
        assignments = load_json(workflow_dir(root, "3") / "00_atamalar.json") or {}
        assigned = {
            str(d).strip().lower() for v in assignments.values() for d in v if d
        }
        bank = load_json(workflow_dir(root, "4") / "taslak" / "_kanit_bankasi.json")
        measure_coverage(concepts, pool, assigned, bank)

    if args.phase == 4:
        bank = load_json(workflow_dir(root, "4") / "taslak" / "_kanit_bankasi.json")
        added = update_from_literature(concepts, bank)
        derivation_note = (
            f"Tam metin okumasından {len(added)} yeni kavram eklendi: "
            + ", ".join(added)
            if added
            else "Tam metin okumasında yeni kavram bulunmadı."
        )

    report = build_report(
        plan or {},
        args.phase,
        framing,
        concepts,
        section_coverage,
        title=title,
        derivation_note=derivation_note,
        mined=mined,
    )

    if args.check:
        print(
            f"aşama {args.phase}: {len(concepts)} kavram, "
            f"{sum(1 for c in concepts if c.get('role') == 'anchor')} anchor, "
            f"{len(report['warnings'])} uyarı"
        )
        for warning in report["warnings"]:
            print(f"  - {warning}", file=sys.stderr)
        return 0

    out_dir = args.output_dir or work1
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
    # Sabit adlı kopya: sonraki aşamalar bunu okur.
    (out_dir / f"{OUTPUT_STEM}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Yazıldı: {result['path']}")
    print(f"Yazıldı: {result['path'].with_suffix('.html')}")
    print(
        f"Kavram: {len(concepts)} | anchor: "
        f"{sum(1 for c in concepts if c.get('role') == 'anchor')} | "
        f"uyarı: {len(report['warnings'])}"
    )
    if report["warnings"]:
        for warning in report["warnings"][:6]:
            print(f"  - {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
