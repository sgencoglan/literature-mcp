"""PubMed MeSH sözlüğü: kavramı kontrollü terime çevirir.

Neden gerekli
-------------
Serbest metin aramaları eş anlamlıyı kaçırır. "de-escalation" yazınca
"aggression management", "coercion reduction", "restraint minimization"
literatürü gelmez. PubMed'in MeSH (Medical Subject Headings) sözlüğü bu boşluğu
kapatır: terim bir kez MeSH'te bulunur, oradan hem PubMed'de hem de diğer
motorlarda (OpenAlex, Semantic Scholar, Crossref) arama anahtarı olarak
kullanılır.

MeSH hiyerarşiktir: bir terimin alt terimleri (narrower) genellikle arama için
üst terimden daha verimlidir. Bu modül terim, eş anlamlı ve alt terimleri
birlikte döndürür ki kavram haritası bunları sorguya çevirebilsin.

Kullanım:
    async with mesh.session():
        entry = await mesh.lookup("de-escalation")
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from sciencedirect_meta.server import _pubmed_params, polite_get

logger = logging.getLogger("sciencedirect-meta.mesh")

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# MeSH XML ad alanı yok; düz etiket adları kullanılır.
DEFAULT_ENTRY_TERMS: Dict[str, List[str]] = {
    # Sık kullanılan kavramlar için hazır karşılıklar: MeSH isteği başarısız
    # olduğunda ağ erişimi olmadan da harita kurulabilsin.
    "de-escalation": [
        "De-escalation",
        "Crisis Intervention",
        "Aggression",
        "Restraint, Physical",
        "Coercion",
    ],
    "classroom management": ["School Teachers", "Behavior Control", "Schools"],
    "behavior screening": ["Mass Screening", "Risk Assessment", "School Health Services"],
    "teacher referral": ["Referral and Consultation", "School Teachers"],
}


class MeshError(RuntimeError):
    """MeSH sorgusu tamamlanamadı."""


async def _esearch(term: str, retmax: int = 5) -> List[str]:
    response = await polite_get(
        ESEARCH,
        params=_pubmed_params(
            {
                "db": "mesh",
                "term": term,
                "retmode": "json",
                "retmax": retmax,
            }
        ),
        attempts=3,
    )
    if response.status_code != 200:
        raise MeshError(f"MeSH esearch HTTP {response.status_code}")
    payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
    if payload is None:
        # NCBI bazen JSON yerine XML döndürür; kimlikleri XML'den çek.
        root = ET.fromstring(response.text)
        return [el.text for el in root.findall(".//IdList/Id") if el.text]
    return list(payload.get("esearchresult", {}).get("idlist") or [])


async def _efetch(ids: List[str]) -> str:
    response = await polite_get(
        EFETCH,
        params=_pubmed_params({"db": "mesh", "id": ",".join(ids), "retmode": "xml"}),
        attempts=3,
    )
    if response.status_code != 200:
        raise MeshError(f"MeSH efetch HTTP {response.status_code}")
    return response.text


def _parse(xml_text: str) -> List[Dict[str, Any]]:
    """MeSH kayıtlarını terim, kapsam notu ve alt terimlerle ayrıştır."""
    entries: List[Dict[str, Any]] = []
    root = ET.fromstring(xml_text)
    for record in root.findall(".//DescriptorRecord"):
        name = record.findtext("DescriptorName/String") or ""
        if not name:
            continue
        tree_numbers = [
            el.text for el in record.findall("TreeNumberList/TreeNumber") if el.text
        ]
        concept_terms: List[str] = []
        scope_note = None
        for concept in record.findall("ConceptList/Concept"):
            term_text = concept.findtext("ConceptName/String")
            if term_text:
                concept_terms.append(term_text)
            note = concept.findtext("ScopeNote")
            if note and not scope_note:
                scope_note = note
            for term in concept.findall("TermList/Term"):
                term_text = term.findtext("String")
                if term_text:
                    concept_terms.append(term_text)
        # Alt terimler: AllowableQualifiers değil, alt ağaç düğümleri.
        narrower: List[str] = []
        for node in record.findall(".//TreeNumberList/TreeNumber"):
            if node.text and "." in node.text:
                narrower.append(node.text)
        entries.append(
            {
                "term": name,
                "scope_note": scope_note,
                "synonyms": sorted({t for t in concept_terms if t and t != name}),
                "tree_numbers": [t for t in tree_numbers if t],
                "narrower_tree_numbers": narrower,
            }
        )
    return entries


async def lookup(term: str, retmax: int = 3) -> Dict[str, Any]:
    """Bir terimi MeSH'te ara; kayıt yoksa boş sonuç döndür."""
    term = (term or "").strip()
    if not term:
        return {"term": term, "found": False, "entries": [], "error": "boş terim"}
    try:
        ids = await _esearch(term, retmax=retmax)
    except Exception as exc:  # noqa: BLE001 - ağ hatası haritayı düşürmesin
        logger.info("MeSH esearch başarısız (%s): %s", term, exc)
        return {"term": term, "found": False, "entries": [], "error": str(exc)[:200]}
    if not ids:
        return {"term": term, "found": False, "entries": [], "error": None}
    try:
        xml_text = await _efetch(ids)
        entries = _parse(xml_text)
    except Exception as exc:  # noqa: BLE001
        logger.info("MeSH efetch başarısız (%s): %s", term, exc)
        return {"term": term, "found": False, "entries": [], "error": str(exc)[:200]}

    # Arama terimleri: kayıt adı + eş anlamlılar, en fazla 10.
    search_terms: List[str] = []
    for entry in entries:
        for candidate in [entry["term"], *entry["synonyms"]]:
            normalized = candidate.strip()
            if normalized and normalized.lower() not in {t.lower() for t in search_terms}:
                search_terms.append(normalized)
    return {
        "term": term,
        "found": bool(entries),
        "entries": entries,
        "search_terms": search_terms[:10],
        "error": None,
    }


def fallback_terms(term: str) -> List[str]:
    """Ağ yoksa hazır karşılıkları döndür."""
    key = (term or "").strip().lower()
    if key in DEFAULT_ENTRY_TERMS:
        return list(DEFAULT_ENTRY_TERMS[key])
    # Kısmi eşleşme: "de-escalation training" -> "de-escalation" karşılığı.
    for known, values in DEFAULT_ENTRY_TERMS.items():
        if known in key:
            return list(values)
    return []


async def lookup_many(terms: List[str], retmax: int = 2) -> Dict[str, Dict[str, Any]]:
    """Sıralı MeSH sorgusu; NCBI hız limitine uyar (polite_get zaten aralık koyar)."""
    results: Dict[str, Dict[str, Any]] = {}
    for term in terms:
        results[term] = await lookup(term, retmax=retmax)
    return results


def describe(entry: Dict[str, Any]) -> str:
    """İnsan okunur tek satır özet."""
    if not entry.get("found"):
        return f"{entry.get('term')}: MeSH kaydı yok" + (
            f" ({entry['error']})" if entry.get("error") else ""
        )
    names = ", ".join(e["term"] for e in entry["entries"][:3])
    return f"{entry.get('term')}: {names}"


# --------------------------------------------------------------------------- #
# Meş projeksiyonu: serbest metinden kontrollü sözlüğe
# --------------------------------------------------------------------------- #

# MeSH "check tags": demografik/metodolojik etiketler kavram değildir.
CHECK_TAGS = {
    "humans", "male", "female", "adult", "middle aged", "aged", "adolescent",
    "child", "child, preschool", "infant", "young adult", "aged, 80 and over",
    "animals", "mice", "rats", "retrospective studies", "prospective studies",
    "follow-up studies", "cross-sectional studies", "longitudinal studies",
    "questionnaires", "interview", "surveys and questionnaires",
    "reproducibility of results", "treatment outcome", "time factors",
    "risk factors", "program evaluation", "pilot projects", "feasibility studies",
}

PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _parse_pubmed_mesh(xml_text: str) -> List[Dict[str, Any]]:
    """PubmedArticle XML'inden MeSH başlıklarını çıkar."""
    out: List[Dict[str, Any]] = []
    root = ET.fromstring(xml_text)
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//MedlineCitation/PMID")
        title = article.findtext(".//Article/ArticleTitle") or ""
        descriptors: List[str] = []
        qualifiers: List[str] = []
        for heading in article.findall(".//MeshHeadingList/MeshHeading"):
            name = heading.findtext("DescriptorName")
            if name:
                descriptors.append(name)
            for qual in heading.findall("QualifierName"):
                if qual.text:
                    qualifiers.append(qual.text)
        out.append(
            {
                "pmid": pmid,
                "title": title.strip(),
                "mesh": descriptors,
                "qualifiers": qualifiers,
            }
        )
    return out


async def concepts_from_pubmed(
    query: str,
    limit: int = 20,
    min_share: float = 0.25,
    context_terms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Serbest metin terimini PubMed'de ara, sonuçların MeSH terimlerini topla.

    Bu, MeSH'in doğru kullanımıdır: MeSH'te "de-escalation" diye bir descriptor
    yoktur, ama o konudaki makalelerin MeSH başlıkları vardır (Crisis
    Intervention, Aggression, Restraint, Physical ...). Makalelerden çıkan
    terimler, kavramın kontrollü sözlükteki karşılığıdır ve diğer motorlara
    arama anahtarı olarak taşınabilir.

    İki koruma vardır:

    * ``context_terms`` — terim tek başına birden çok alana yayılabilir
      ("de-escalation" tıpta kemoterapi dozu azaltma demektir). Alan bağlamı
      eklenince MeSH terimleri de o alana çekilir.
    * ``min_share`` — makalelerin yalnızca küçük bir kısmında geçen MeSH terimi
      kavramın karşılığı sayılmaz; gürültü (örn. Chemoradiotherapy) elenir.
    """
    query = (query or "").strip()
    if not query:
        return {"query": query, "found": False, "articles": [], "mesh_terms": [], "error": "boş sorgu"}
    if context_terms:
        context = " OR ".join(f'"{t.strip()}"' for t in context_terms if str(t).strip())
        if context:
            query = f"({query}) AND ({context})"

    try:
        response = await polite_get(
            PUBMED_ESEARCH,
            params=_pubmed_params(
                {
                    "db": "pubmed",
                    "term": query,
                    "retmode": "json",
                    "retmax": max(1, min(limit, 50)),
                    "sort": "relevance",
                }
            ),
            attempts=3,
        )
        if response.status_code != 200:
            raise MeshError(f"PubMed esearch HTTP {response.status_code}")
        ids = list(response.json().get("esearchresult", {}).get("idlist") or [])
    except Exception as exc:  # noqa: BLE001
        logger.info("PubMed esearch başarısız (%s): %s", query, exc)
        return {"query": query, "found": False, "articles": [], "mesh_terms": [], "error": str(exc)[:200]}

    if not ids:
        return {"query": query, "found": False, "articles": [], "mesh_terms": [], "error": None}

    try:
        fetch = await polite_get(
            PUBMED_EFETCH,
            params=_pubmed_params({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}),
            attempts=3,
        )
        if fetch.status_code != 200:
            raise MeshError(f"PubMed efetch HTTP {fetch.status_code}")
        articles = _parse_pubmed_mesh(fetch.text)
    except Exception as exc:  # noqa: BLE001
        logger.info("PubMed efetch başarısız (%s): %s", query, exc)
        return {"query": query, "found": False, "articles": [], "mesh_terms": [], "error": str(exc)[:200]}

    counts: Dict[str, int] = {}
    for article in articles:
        for term in article["mesh"]:
            if term.strip().lower() in CHECK_TAGS:
                continue  # demografik/metodolojik etiket, kavram değil
            counts[term] = counts.get(term, 0) + 1
    total = max(1, len(articles))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    kept = [
        {
            "term": term,
            "count": count,
            "share": round(count / total, 2),
        }
        for term, count in ranked
        if count / total >= min_share
    ]
    return {
        "query": query,
        "found": bool(kept),
        "articles": articles,
        "mesh_terms": kept[:15],
        "dropped_below_share": [
            {"term": term, "count": count, "share": round(count / total, 2)}
            for term, count in ranked
            if count / total < min_share
        ][:10],
        "min_share": min_share,
        "error": None,
    }


__all__ = [
    "lookup",
    "lookup_many",
    "concepts_from_pubmed",
    "fallback_terms",
    "describe",
    "MeshError",
]
