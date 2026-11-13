"""PubMed MeSH sözlüğü: kavramı kontrollü terime çevirir.

Neden gerekli
-------------
Serbest metin aramaları eş anlamlıları kaçırabilir. PubMed'in MeSH
(Medical Subject Headings) sözlüğünden doğrulanan karşılıklar arama
anahtarı olarak kullanılabilir. Alan bağlamı proje verisinden alınır.

MeSH hiyerarşiktir: bir terimin alt terimleri (narrower) genellikle arama için
üst terimden daha verimlidir. Bu modül terim, eş anlamlı ve alt terimleri
birlikte döndürür ki kavram haritası bunları sorguya çevirebilsin.

Kullanım:
    entry = await mesh.lookup("<search-term>")
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from sciencedirect_meta.server import _pubmed_params, polite_get

logger = logging.getLogger("sciencedirect-meta.mesh")

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

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
        entries.append(
            {
                "term": name,
                "scope_note": scope_note,
                "synonyms": sorted({t for t in concept_terms if t and t != name}),
                "tree_numbers": [t for t in tree_numbers if t],
                "narrower_tree_numbers": [],
                "identifier": record.findtext("DescriptorUI"),
            }
        )
    return entries


async def lookup(term: str, retmax: int = 3) -> Dict[str, Any]:
    """NLM RDF sözlüğünden tam etiket eşleşmesi getir; kısmi ad eşleşmesini doğrulama sayma.

    Entrez MeSH EFetch, DescriptorRecord XML döndürmeyi garanti etmez.
    RDF kaydı ve tercih edilen kavram ayrı okunur. Giriş terimleri ayrıca
    döndürülür; bu terimler bütün bağlamlarda birebir eş anlamlı sayılmaz.
    """
    term = (term or "").strip()
    if not term:
        return {"term": term, "found": False, "entries": [], "error": "boş terim"}
    try:
        response = await polite_get(
            "https://id.nlm.nih.gov/mesh/lookup/descriptor",
            params={"label": term, "match": "exact", "limit": max(1, min(retmax, 10))},
            attempts=3,
        )
        response.raise_for_status()
        matches = response.json()
        entries = []
        for match in matches:
            identifier = str(match.get("resource", "")).rsplit("/", 1)[-1]
            if not re.fullmatch(r"D\d+", identifier):
                continue
            descriptor = await polite_get(
                f"https://id.nlm.nih.gov/mesh/{identifier}.json", attempts=3,
            )
            descriptor.raise_for_status()
            data = descriptor.json()
            if data.get("http://id.nlm.nih.gov/mesh/vocab#active") is False:
                continue
            preferred = str(data.get("preferredConcept", "")).rsplit("/", 1)[-1]
            if not re.fullmatch(r"M\d+", preferred):
                raise MeshError("MeSH tercih edilen kavram kimliği eksik")
            concept = await polite_get(
                f"https://id.nlm.nih.gov/mesh/{preferred}.json", attempts=3,
            )
            concept.raise_for_status()
            details = concept.json()
            term_response = await polite_get(
                "https://id.nlm.nih.gov/mesh/lookup/details",
                params={"descriptor": identifier, "includes": "terms"}, attempts=3,
            )
            term_response.raise_for_status()
            entry_terms = [str(t["label"]) for t in term_response.json().get("terms", []) if t.get("label")]
            label = _rdf_text(data.get("label"))
            entries.append({
                "identifier": identifier,
                "term": label,
                "scope_note": _rdf_text(details.get("scopeNote")),
                "synonyms": [],
                "entry_terms": entry_terms,
                "tree_numbers": [str(t).rsplit("/", 1)[-1] for t in data.get("treeNumber", [])],
                "narrower_tree_numbers": [],
                "broader_descriptors": data.get("broaderDescriptor", []),
                "uri": f"https://id.nlm.nih.gov/mesh/{identifier}",
                "match_type": "exact_label",
            })
    except Exception as exc:  # noqa: BLE001 - ağ hatası haritayı düşürmesin
        logger.info("MeSH RDF sorgusu başarısız: %s", type(exc).__name__)
        return {"term": term, "found": False, "entries": [], "error": type(exc).__name__}

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


def _rdf_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("@value") or "")
    return str(value or "")


def fallback_terms(
    term: str, mappings: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """Yalnızca çağıranın verdiği proje sözlüğünden karşılık döndür.

    Ağ hatası projeye özel bir kavram listesini otomatik olarak devreye sokmaz.
    """
    key = (term or "").strip().lower()
    if not key:
        return []
    for known, values in (mappings or {}).items():
        if key == known.strip().lower():
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
        title = "".join(article.find(".//Article/ArticleTitle").itertext()) if article.find(".//Article/ArticleTitle") is not None else ""
        abstract = "\n".join(
            ((node.get("Label") + ": ") if node.get("Label") else "")
            + "".join(node.itertext())
            for node in article.findall(".//Article/Abstract/AbstractText")
        )
        doi = next((n.text for n in article.findall(".//ArticleId") if n.get("IdType") == "doi"), None)
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
                "abstract": abstract,
                "doi": doi,
                "year": article.findtext(".//JournalIssue/PubDate/Year"),
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

    Dönen kontrollü terimler sorgunun bağlamına göre değerlendirilir ve
    diğer motorlara arama anahtarı olarak taşınabilir.

    İki koruma vardır:

    * ``context_terms`` — terim tek başına birden çok alana yayılabilir
      ve farklı anlamlarda kullanılabilir. Alan bağlamı
      eklenince MeSH terimleri de o alana çekilir.
    * ``min_share`` — makalelerin yalnızca küçük bir kısmında geçen MeSH terimi
      kavramın karşılığı sayılmaz; düşük sıklıklı terimler elenir.
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
        search = response.json().get("esearchresult", {})
        if search.get("ERROR") or search.get("errorlist"):
            raise MeshError("PubMed sorgusu geçersiz")
        ids = list(search.get("idlist") or [])
    except Exception as exc:  # noqa: BLE001
        logger.info("PubMed esearch başarısız (%s): %s", query, exc)
        return {"query": query, "found": False, "articles": [], "mesh_terms": [], "error": type(exc).__name__}

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
        return {"query": query, "found": False, "articles": [], "mesh_terms": [], "error": type(exc).__name__}

    counts: Dict[str, int] = {}
    for article in articles:
        for term in set(article["mesh"]):
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
            "pmids": [a["pmid"] for a in articles if term in a["mesh"]],
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
        "total_results": int(search.get("count") or 0),
        "query_translation": search.get("querytranslation"),
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
