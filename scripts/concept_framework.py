"""Kaynak izi olan kavram çerçevesi; ağ veya model çağrısı yapmaz.

Kapsamı ve kavram rollerini kullanıcı/ajan verir. Kod, boşlukları doldurmuş
gibi yapmaz; kaynakta sözcük geçmesini tanım veya nedensellik kanıtı saymaz.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

DIMENSIONS = {
    "phenomenon": "Ana olgu",
    "population": "Hedef grup",
    "context": "Ortam ve bağlam",
    "intervention": "Yaklaşım / müdahale",
    "outcome": "Sonuçlar",
    "theory": "Kuram / model",
    "measurement": "Ölçüm",
    "ethics": "Etik ve güvenlik",
    "unclassified": "Sınıflandırılmamış",
}
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/sciencedirect-meta/src"))
from sciencedirect_meta.platform_search import PLATFORMS

PLATFORM_DOMAINS = tuple(
    dict.fromkeys(domain for spec in PLATFORMS.values() for domain in spec["domains"])
)


def _quote(term: str) -> str:
    return '"' + re.sub(r'["\[\]\r\n]', " ", term).strip() + '"'


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        item = str(item).strip()
        if item and item.casefold() not in seen:
            result.append(item)
            seen.add(item.casefold())
    return result


def _query_link(database: str, query: str) -> dict[str, Any]:
    if database == "pubmed":
        url = "https://pubmed.ncbi.nlm.nih.gov/?" + urlencode({"term": query})
    else:
        url = "https://scholar.google.com/scholar?" + urlencode({"q": query})
    return {"database": database, "query": query, "url": url, "status": "not_run"}


def build_framework(
    concepts: list[dict[str, Any]], scope: dict[str, Any] | None = None
) -> dict[str, Any]:
    scope = scope or {}
    dimensions: dict[str, list[str]] = {name: [] for name in DIMENSIONS}
    nodes = []
    edges = []
    queries = []
    concept_ids = {c["id"] for c in concepts}
    term_ids = {str(c.get("term", "")).casefold(): c["id"] for c in concepts}
    warnings = []
    blocks: dict[str, list[str]] = {}
    for concept in concepts:
        cid = concept["id"]
        dimension = concept.get("dimension", "unclassified")
        if dimension not in DIMENSIONS:
            warnings.append(f"{cid}: bilinmeyen boyut '{dimension}'.")
            dimension = "unclassified"
        if dimension == "unclassified":
            dimension = {"anchor": "phenomenon", "context": "context", "outcome": "outcome"}.get(
                concept.get("role"),
                "unclassified",
            )
        dimensions[dimension].append(cid)
        names = _unique(
            list(concept.get("english_terms") or []) + list(concept.get("synonyms") or [])
        )
        # Sözlükte doğrulanmış terimler ile serbest metin terimleri ayrı tutulur.
        entries = concept.get("mesh_entries") or []
        mesh_names = _unique([e["term"] for e in entries if e.get("match_type") == "exact_label"])
        text_block = " OR ".join(f"{_quote(t)}[Title/Abstract]" for t in names)
        mesh_block = " OR ".join(f"{_quote(t)}[MeSH Terms]" for t in mesh_names)
        block = " OR ".join(p for p in (text_block, mesh_block) if p)
        if block:
            blocks.setdefault(dimension, []).append(f"({block})")
            queries.append(
                {
                    "concept_ids": [cid],
                    "purpose": "Kavramı ayrı sına",
                    **_query_link("pubmed", f"({block})"),
                }
            )
        if names:
            general_query = " OR ".join(_quote(name) for name in names[:5])
            queries.append(
                {
                    "concept_ids": [cid],
                    "purpose": "Yayıncıdan bağımsız keşif",
                    "priority": "primary",
                    **_query_link("scholar", general_query),
                }
            )
            for domain in PLATFORM_DOMAINS:
                query = f"site:{domain} {_quote(names[0])}"
                queries.append(
                    {
                        "concept_ids": [cid],
                        "purpose": "Platformda keşif",
                        "priority": "supplementary",
                        **_query_link("scholar", query),
                    }
                )
        evidence = [
            e for e in concept.get("evidence") or [] if e.get("source_id") and e.get("passage")
        ]
        # Dışarıdan gelen tanım ve ilişkiler otomatik onaylanmaz.
        definition = concept.get("definition") or {}
        definition_record = {
            "text": str(definition.get("text") or ""),
            "source_id": definition.get("source_id"),
            "status": "proposed" if definition.get("text") else "missing",
        }
        definitions = [
            {"text": e["scope_note"], "source_id": e.get("uri"), "status": "vocabulary_definition"}
            for e in entries
            if e.get("scope_note") and e.get("match_type") == "exact_label"
        ]
        nodes.append(
            {
                "id": cid,
                "term": concept.get("term"),
                "dimension": dimension,
                "search_terms": names,
                "status": "proposed",
                "observed_in_sources": bool(evidence),
                "vocabulary_match": bool(mesh_names),
                "evidence": evidence,
                "proposed_definition": definition_record,
                "vocabulary_definitions": definitions,
            }
        )
        for relation in concept.get("relations") or []:
            target = relation.get("target")
            if target not in concept_ids:
                target = term_ids.get(str(target).casefold())
            if not target:
                warnings.append(f"{cid}: ilişki hedefi bulunamadı.")
                continue
            edges.append(
                {
                    "source": cid,
                    "target": target,
                    "type": relation.get("type") or "related_to",
                    "status": "proposed",
                    "note": relation.get("note") or "",
                    "evidence": relation.get("evidence") or [],
                }
            )
    # Tüm boyutları AND'lemek aşırı daraltır; önce olgu, sonra tek bağlam.
    core = blocks.get("phenomenon") or []
    if core:
        broad = "(" + " OR ".join(core) + ")"
        queries.append({"purpose": "Geniş olgu taraması", **_query_link("pubmed", broad)})
        for dimension in ("population", "context", "intervention"):
            if blocks.get(dimension):
                focused = broad + " AND (" + " OR ".join(blocks[dimension]) + ")"
                queries.append(
                    {"purpose": f"Olgu + {DIMENSIONS[dimension]}", **_query_link("pubmed", focused)}
                )
    missing = [
        DIMENSIONS[d]
        for d in ("phenomenon", "population", "context", "outcome")
        if not dimensions[d] and not scope.get(d)
    ]
    return {
        "schema": "concept-framework/1",
        "status": "proposed",
        "scope": scope,
        "dimensions": dimensions,
        "nodes": nodes,
        "relations": edges,
        "search_plan": queries,
        "missing_dimensions": missing,
        "warnings": warnings,
        "limitations": [
            "Başlık/özette terim geçmesi, tanımı veya kavramlar arasındaki ilişkiyi kanıtlamaz.",
            "MeSH eşleşmesi sözlük karşılığını gösterir; proje bağlamına uygunluğu ayrıca değerlendirilir.",
            "Model/kullanıcı tanımları ve ilişkileri, kaynak verilse bile otomatik doğrulanmaz.",
            "Arama bağlantıları hazırlandı; bağlantının varlığı aramanın yapıldığı anlamına gelmez.",
        ],
    }


def render_framework(framework: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value or ""), quote=True)

    rows = []
    for node in framework["nodes"]:
        sources = []
        for proof in node["evidence"]:
            doi = str(proof.get("doi") or "")
            doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
            pmid = str(proof.get("pmid") or "")
            # Yalnızca bilinen kimliklerden bağlantı kur; dış girdideki URL'yi çalıştırma.
            url = f"https://doi.org/{doi}" if re.match(r"^10\.\d{4,9}/\S+$", doi) else ""
            if not url and pmid.isdigit():
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            label = esc(proof.get("title") or proof["source_id"])
            link = f'<a href="{esc(url)}">{label}</a>' if url else label
            sources.append(
                f"<li>{link}<br><small>{esc(proof.get('read_level'))}</small><blockquote>{esc(proof['passage'])}</blockquote></li>"
            )
        defs = "".join(
            f"<p>{esc(d['text'])}<br><small>MeSH sözlük tanımı · {esc(d['source_id'])}</small></p>"
            for d in node["vocabulary_definitions"]
        )
        proposed = node["proposed_definition"]
        if proposed["text"]:
            defs += f"<p>{esc(proposed['text'])}<br><small>Önerilen tanım · doğrulanmadı · {esc(proposed.get('source_id'))}</small></p>"
        rows.append(
            f"<tr><td>{esc(node['id'])} · {esc(node['term'])}</td>"
            f"<td>{esc(DIMENSIONS[node['dimension']])}</td>"
            f"<td>Aday · kaynakta görülme: {'var' if node['observed_in_sources'] else 'yok'} · "
            f"MeSH eşleşmesi: {'var' if node['vocabulary_match'] else 'yok'}{defs}</td>"
            f"<td><ul>{''.join(sources) or '<li>Kaynak pasajı eklenmedi.</li>'}</ul></td></tr>"
        )
    queries = "".join(
        f'<li>{esc(q["purpose"])} · <a href="{esc(q["url"])}">{esc(q["database"])}</a>'
        f" · çalıştırılmadı<br><code>{esc(q['query'])}</code></li>"
        for q in framework["search_plan"]
    )
    relations = "".join(
        f"<li>{esc(r['source'])} → {esc(r['target'])}: {esc(r['type'])} · öneri</li>"
        for r in framework["relations"]
    )
    scope_html = "".join(
        f"<li>{esc(DIMENSIONS.get(k, k))}: {esc(v)}</li>" for k, v in framework["scope"].items()
    )
    limits = "".join(f"<li>{esc(t)}</li>" for t in framework["limitations"])
    missing = ", ".join(framework["missing_dimensions"]) or "yok"
    return (
        "<section><h2>Araştırma çerçevesi — doğrulama bekliyor</h2>"
        f"<ul>{scope_html}</ul><p>Netleştirilecek kapsam: {esc(missing)}</p>"
        "<table><thead><tr><th>Kavram</th><th>Boyut</th><th>Durum / tanım</th><th>Kaynak izi</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<h3>İlişki önerileri</h3><ul>{relations or '<li>İlişki çıkarılmadı.</li>'}</ul>"
        f"<details><summary>Arama planı ({len(framework['search_plan'])})</summary><ol>{queries}</ol></details>"
        f"<h3>Yorum sınırları</h3><ul>{limits}</ul></section>"
    )
