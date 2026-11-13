"""Kaynak havuzu, dış arama sonuçları ve bilinen yayınlar için kapsam denetimi.

Ağ çağrısı veya kalite/eksiksizlik iddiası üretmez. DOI/PMID eşleşmesi,
başlık benzerliği ve gerçek arama durumları birbirinden ayrılır.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlencode

SOURCE_CATALOG = {
    "pubmed": ("PubMed / MEDLINE", "https://pubmed.ncbi.nlm.nih.gov/", "bibliographic"),
    "embase": ("Embase", "https://www.embase.com/", "bibliographic"),
    "psycinfo": ("APA PsycInfo", "https://www.apa.org/pubs/databases/psycinfo", "bibliographic"),
    "central": ("Cochrane CENTRAL", "https://www.cochranelibrary.com/central", "trials"),
    "scholar": ("Google Scholar", "https://scholar.google.com/", "discovery"),
    "citation_chaining": ("Kaynakça ve ileri atıf takibi", None, "citation_tracking"),
    "clinicaltrials": ("ClinicalTrials.gov", "https://clinicaltrials.gov/", "registry"),
    "openalex": ("OpenAlex", "https://openalex.org/", "discovery"),
    "crossref": ("Crossref", "https://search.crossref.org/", "metadata"),
    "europepmc": ("Europe PMC", "https://europepmc.org/", "bibliographic"),
    "scopus": ("Scopus", "https://www.scopus.com/", "citation_index"),
    "webofscience": ("Web of Science", "https://www.webofscience.com/", "citation_index"),
}
PROFILES = {
    "medical": ["pubmed", "embase", "scholar", "citation_chaining"],
    "psychology": ["pubmed", "psycinfo", "embase", "scholar", "citation_chaining"],
    "education": ["scholar", "openalex", "citation_chaining"],
}
SEARCH_STATUSES = {"ok", "partial", "error", "rate_limited", "not_run", "unavailable"}


def normalize_source(value: Any) -> str:
    key = re.sub(r"[^a-z0-9]", "", str(value or "").casefold())
    return {"googlescholar": "scholar", "clinicaltrialsgov": "clinicaltrials"}.get(key, key)


def normalize_doi(value: Any) -> str:
    text = unquote(str(value or "").strip())
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text, flags=re.I)
    return text.casefold() if re.fullmatch(r"10\.\d{4,9}/\S+", text) else ""


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(str(value or ""))).casefold()
    return " ".join(re.findall(r"\w+", text))


def normalize_record(record: dict[str, Any], origin: str, position: int) -> dict[str, Any]:
    pmid = str(record.get("pmid") or "").strip()
    year = str(record.get("year") or record.get("publication_year") or "").strip()
    result = {
        "record_id": f"{origin}-{position}",
        "origin": origin,
        "doi": normalize_doi(record.get("doi")),
        "pmid": pmid if pmid.isdigit() else "",
        "title": str(record.get("title") or ""),
        "title_key": normalize_title(record.get("title")),
        "year": int(year) if re.fullmatch(r"\d{4}", year) else None,
        "abstract": str(record.get("abstract") or ""),
        "source": str(record.get("source") or record.get("database") or "unspecified"),
        "publication_type": str(
            record.get("publication_type") or record.get("study_design") or "unknown"
        ),
        "is_retracted": record.get("is_retracted")
        if isinstance(record.get("is_retracted"), bool)
        else None,
        "read_level": "abstract" if record.get("abstract") else "metadata",
    }
    if not (result["doi"] or result["pmid"] or result["title_key"]):
        raise ValueError("Her kayıt geçerli DOI, PMID veya başlık içermeli.")
    return result


class RecordIndex:
    def __init__(self, records: list[dict[str, Any]]):
        self.records = records
        self.by_doi: dict[str, list[int]] = {}
        self.by_pmid: dict[str, list[int]] = {}
        self.by_title: dict[str, list[int]] = {}
        for index, record in enumerate(records):
            self.add(record, index)

    def add(self, record: dict[str, Any], index: int) -> None:
        for name, table in (
            ("doi", self.by_doi),
            ("pmid", self.by_pmid),
            ("title_key", self.by_title),
        ):
            if record[name]:
                table.setdefault(record[name], []).append(index)

    def match(self, record: dict[str, Any]) -> dict[str, Any]:
        strong = set(self.by_doi.get(record["doi"], [])) | set(self.by_pmid.get(record["pmid"], []))
        title_matches = set(self.by_title.get(record["title_key"], []))
        conflicts = []
        confirmed = []
        for i in sorted(strong):
            candidate = self.records[i]
            if any(
                record[k] and candidate[k] and record[k] != candidate[k] for k in ("doi", "pmid")
            ):
                conflicts.append(candidate["record_id"])
            else:
                confirmed.append(candidate["record_id"])
        if conflicts:
            return {
                "status": "identifier_conflict",
                "matched_ids": conflicts + confirmed,
                "basis": "doi_or_pmid",
            }
        if confirmed:
            return {"status": "confirmed", "matched_ids": confirmed, "basis": "doi_or_pmid"}
        if title_matches:
            candidates = [self.records[i] for i in sorted(title_matches)]
            return {
                "status": "title_candidate",
                "matched_ids": [r["record_id"] for r in candidates],
                "basis": "normalized_title",
                "note": "Başlık eşleşmesi; kimlik/yıl farkı elle kontrol edilmeli.",
            }
        return {"status": "not_found", "matched_ids": [], "basis": None}


def records_from(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = next(
            (
                data[k]
                for k in ("records", "results", "candidates", "selected")
                if isinstance(data.get(k), list)
            ),
            None,
        )
    else:
        records = None
    if records is None or any(not isinstance(r, dict) for r in records):
        raise ValueError(
            "Kaynak girdisi records/results/candidates listesi veya doğrudan kayıt listesi olmalı."
        )
    return records


def _term_hit(term: str, record: dict[str, Any]) -> bool:
    needle = normalize_title(term)
    text = normalize_title(record["title"] + " " + record["abstract"])
    return bool(needle and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", text))


def build_audit(
    baseline: list[dict[str, Any]],
    additional: list[dict[str, Any]],
    known_items: list[dict[str, Any]],
    framework: dict[str, Any],
    searches: list[dict[str, Any]] | None = None,
    domain: str = "psychology",
    purpose: str = "overview",
) -> dict[str, Any]:
    if domain not in PROFILES or purpose not in {"overview", "intervention"}:
        raise ValueError("Geçersiz alan veya araştırma amacı.")
    base = [normalize_record(r, "baseline", i) for i, r in enumerate(baseline, 1)]
    incoming = [normalize_record(r, "additional", i) for i, r in enumerate(additional, 1)]
    base_index = RecordIndex(base)
    combined = list(base)
    index = RecordIndex(combined)
    comparisons = []
    for record in incoming:
        match = index.match(record)
        classification = {
            "confirmed": "already_present",
            "title_candidate": "possible_duplicate",
            "identifier_conflict": "identifier_conflict",
            "not_found": "new_candidate",
        }[match["status"]]
        comparisons.append({"record": record, "classification": classification, "match": match})
        # Aynı yayının ek kaydındaki yeni kimlik ve kaynak izini de koru.
        combined.append(record)
        index.add(record, len(combined) - 1)
    recovered = []
    for i, known in enumerate(known_items, 1):
        normalized = normalize_record(known, "known", i)
        found = index.match(normalized)
        title_query = '"' + normalized["title"].replace('"', " ") + '"'
        query = normalized["doi"] or normalized["pmid"] or title_query
        recovered.append(
            {
                "record": normalized,
                "baseline_match": base_index.match(normalized),
                "combined_match": found,
                "search_url": "https://scholar.google.com/scholar?" + urlencode({"q": query}),
            }
        )
    concepts = []
    for node in framework.get("nodes", []):
        terms = node.get("search_terms") or [node["term"]]
        concepts.append(
            {
                "concept_id": node["id"],
                "term": node["term"],
                "terms_checked": terms,
                "baseline_ids": [
                    r["record_id"] for r in base if any(_term_hit(t, r) for t in terms)
                ],
                "additional_ids": [
                    r["record_id"] for r in incoming if any(_term_hit(t, r) for t in terms)
                ],
                "basis": "lexical_title_or_abstract",
                "evidence_status": "not_assessed",
            }
        )
    for concept in concepts:
        concept["status"] = (
            "present_in_baseline"
            if concept["baseline_ids"]
            else ("additional_only" if concept["additional_ids"] else "not_observed")
        )
        concept["suggested_searches"] = [
            q
            for q in framework.get("search_plan", [])
            if concept["concept_id"] in q.get("concept_ids", [])
            and "site:" not in q.get("query", "")
        ]
    source_states = {}
    search_log = []
    for search in searches or []:
        source = normalize_source(search.get("source"))
        status = search.get("status", "not_run")
        if not source or status not in SEARCH_STATUSES:
            raise ValueError("Her arama source ve geçerli status içermeli.")
        item = {
            "source": source,
            "query": str(search.get("query") or ""),
            "status": status,
            "searched_at": search.get("searched_at"),
            "note": str(search.get("note") or ""),
            "screening_status": search.get("screening_status", "not_reported"),
        }
        if status in {"ok", "partial"} and (not item["query"] or not item["searched_at"]):
            raise ValueError("Başarılı/kısmi arama için query ve searched_at zorunlu.")
        search_log.append(item)
        source_states.setdefault(source, []).append(status)
    recommended = list(PROFILES[domain])
    if purpose == "intervention":
        recommended = ["central", *recommended, "clinicaltrials"]
    priorities = []
    for position, source in enumerate(recommended, 1):
        label, url, kind = SOURCE_CATALOG[source]
        states = source_states.get(source, [])
        # Bir sorgunun başarılı olması başka sorgudaki hatayı gizlemez.
        status = (
            "partial"
            if states and any(s != "ok" for s in states) and "ok" in states
            else (states[-1] if states else "not_run")
        )
        priorities.append(
            {
                "order": position,
                "source": source,
                "label": label,
                "url": url,
                "kind": kind,
                "status": status,
                "action": "Sonuçları ve sorgu kapsamını incele"
                if status == "ok"
                else "Aramayı tamamla veya erişim sınırını kaydet",
            }
        )
    new = [r for r in comparisons if r["classification"] == "new_candidate"]
    recovered_ids = {
        record_id
        for item in recovered
        if item["baseline_match"]["status"] != "confirmed"
        for record_id in item["combined_match"]["matched_ids"]
        if item["combined_match"]["status"] == "confirmed"
    }
    for item in new:
        record = item["record"]
        reasons = []
        if record["record_id"] in recovered_ids:
            reasons.append("Başlangıçta bulunmayan bilinen yayınla kimlik eşleşmesi")
        for concept in concepts:
            if not concept["baseline_ids"] and record["record_id"] in concept["additional_ids"]:
                reasons.append(
                    f"Başlangıçta görülmeyen kavramla sözcüksel eşleşme: {concept['term']}"
                )
        priority = 1 if reasons else 2
        if record["is_retracted"] is True:
            priority = 3
            reasons.append("Geri çekilmiş olarak işaretli; durumu doğrulanmalı")
        item["triage"] = {
            "priority": priority,
            "reasons": reasons or ["Konu ve yöntem uygunluğu değerlendirilmeli"],
            "quality_status": "not_assessed",
        }
    actions = []
    missing_known = [r for r in recovered if r["combined_match"]["status"] != "confirmed"]
    if missing_known:
        actions.append(
            f"{len(missing_known)} bilinen yayın doğrulanmış kimlikle bulunamadı; DOI/PMID ve sorguları kontrol et."
        )
    missing_concepts = [r for r in concepts if r["status"] == "not_observed"]
    if missing_concepts:
        actions.append(
            "Havuzda görülmeyen kavramları yeniden ara: "
            + ", ".join(r["term"] for r in missing_concepts)
        )
    incomplete_sources = [r["label"] for r in priorities if r["status"] != "ok"]
    if incomplete_sources:
        actions.append("Tarama durumu tamamlanmamış kaynaklar: " + ", ".join(incomplete_sources))
    actions.extend(
        [
            "Yeni adayların konuya uygunluğunu, yöntemini ve varsa geri çekilme bilgisini değerlendir.",
            "İlgili derlemelerin kaynakçalarını ve temel yayınlara atıf yapan çalışmaları tara.",
        ]
    )
    confirmed = sum(r["combined_match"]["status"] == "confirmed" for r in recovered)
    return {
        "schema": "literature-audit/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domain": domain,
        "purpose": purpose,
        "completeness": "not_established",
        "summary": {
            "baseline_records": len(base),
            "additional_records": len(incoming),
            "new_candidates": len(new),
            "already_present": sum(r["classification"] == "already_present" for r in comparisons),
            "review_required": sum(
                r["classification"] in {"possible_duplicate", "identifier_conflict"}
                for r in comparisons
            ),
            "known_total": len(recovered),
            "known_confirmed": confirmed,
            "known_item_recovery": round(confirmed / len(recovered), 3) if recovered else None,
        },
        "comparison": comparisons,
        "known_items": recovered,
        "concept_coverage": concepts,
        "source_priorities": priorities,
        "search_log": search_log,
        "next_actions": actions,
        "limitations": [
            "Eksiksizlik kanıtlanmadı; sonuçlar yalnızca verilen kayıt ve arama günlüğü için geçerlidir.",
            "Bilinen yayınları bulma oranı, tüm literatürün yakalanma oranı değildir.",
            "Yeni aday, önemli/kaliteli veya konuya uygun olduğu doğrulanmış yayın anlamına gelmez.",
            "İndeks, yayıncı ve atıf sayısı tek başına makalenin yöntem kalitesini göstermez.",
            "Başlık eşleşmesi otomatik tekilleştirilmez; DOI/PMID çelişkileri incelemeye bırakılır.",
            "Kavramın başlık/özette görülmesi içerik kapsamı veya bilimsel kanıt değildir.",
            "Arama bağlantısı veya içe aktarılan kaydın source alanı, veritabanı tarandığını kanıtlamaz.",
        ],
    }


def render_audit(report: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else "—"), quote=True)

    def cell(value: Any) -> str:
        if not isinstance(value, dict):
            return esc(value)
        doi = normalize_doi(value.get("doi"))
        pmid = str(value.get("pmid") or "")
        if doi:
            url = f"https://doi.org/{doi}"
            return f'<a href="{esc(url)}">{esc(url)}</a>'
        if pmid.isdigit():
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            return f'<a href="{esc(url)}">PMID {esc(pmid)}</a>'
        query = '"' + str(value.get("title") or "").replace('"', " ") + '"'
        url = "https://scholar.google.com/scholar?" + urlencode({"q": query})
        return f'<a href="{esc(url)}">Scholar’da başlığı ara</a>'

    def table(headers: list[str], rows: list[list[Any]]) -> str:
        return (
            "<table><thead><tr>"
            + "".join(f"<th>{esc(h)}</th>" for h in headers)
            + "</tr></thead><tbody>"
            + "".join(
                "<tr>" + "".join(f"<td>{cell(v)}</td>" for v in row) + "</tr>" for row in rows
            )
            + "</tbody></table>"
        )

    summary = report["summary"]
    result = "<section><h2>Eksik kaynak ve kapsam denetimi</h2><p><strong>Eksiksizlik kanıtlanmadı.</strong></p>"
    result += f"<p>Yeni aday: {summary['new_candidates']} · İncelenecek eşleşme: {summary['review_required']} · Bilinen yayın: {summary['known_confirmed']}/{summary['known_total']}</p>"
    result += "<h3>Öncelikli kaynaklar ve arama durumları</h3>" + table(
        ["Sıra", "Kaynak", "Tür", "Durum", "Sonraki işlem"],
        [
            [r["order"], r["label"], r["kind"], r["status"], r["action"]]
            for r in report["source_priorities"]
        ],
    )
    result += "<h3>Bilinen önemli yayınlarla kontrol</h3>" + table(
        ["Yayın", "DOI / PMID", "Başlangıç", "Birleşik havuz"],
        [
            [
                r["record"]["title"],
                r["record"],
                r["baseline_match"]["status"],
                r["combined_match"]["status"],
            ]
            for r in report["known_items"]
        ],
    )
    result += (
        "<h3>Öncelikli incelenecek yeni adaylar</h3><p>Bu sıra kalite puanı değildir; bilinen kaynak ve kavram boşluklarına göre inceleme sırasıdır.</p>"
        + table(
            ["Öncelik", "Yayın", "Bağlantı", "Gerekçe"],
            [
                [
                    r["triage"]["priority"],
                    r["record"]["title"],
                    r["record"],
                    "; ".join(r["triage"]["reasons"]),
                ]
                for r in sorted(
                    (i for i in report["comparison"] if i.get("triage")),
                    key=lambda i: i["triage"]["priority"],
                )
            ],
        )
    )
    result += "<h3>Yeni kayıtlar ve eşleşme kararları</h3>" + table(
        ["Başlık", "DOI / PMID", "Kaynak", "Karar", "Eşleşen kayıtlar"],
        [
            [
                r["record"]["title"],
                r["record"],
                r["record"]["source"],
                r["classification"],
                ", ".join(r["match"]["matched_ids"]),
            ]
            for r in report["comparison"]
        ],
    )
    result += "<h3>Kavramların kayıtlarda görülmesi</h3>" + table(
        ["Kavram", "Başlangıç kayıtları", "Ek kayıtlar", "Değerlendirme"],
        [
            [
                r["term"],
                len(r["baseline_ids"]),
                len(r["additional_ids"]),
                "Sözcüksel eşleşme; kanıt değil",
            ]
            for r in report["concept_coverage"]
        ],
    )
    result += "<h3>Arama günlüğü</h3>" + table(
        ["Kaynak", "Sorgu", "Durum", "Tarih", "Not"],
        [
            [r["source"], r["query"], r["status"], r["searched_at"], r["note"]]
            for r in report["search_log"]
        ],
    )
    for heading, key in (("Sonraki işlemler", "next_actions"), ("Yorum sınırları", "limitations")):
        result += (
            f"<h3>{heading}</h3><ul>" + "".join(f"<li>{esc(s)}</li>" for s in report[key]) + "</ul>"
        )
    return result + "</section>"
