#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arama kapsam raporunu (coverage) JSON ve çevrimdışı HTML olarak yazar.

Girdi, ``search_all`` / ``search_literature`` / ``deep_research`` cevabının
kendisi (``coverage`` alanıyla) veya doğrudan coverage bloğudur. HTML tek
dosyadır, harici CSS/JS kullanmaz ve yazdırılabilir.

Kullanım:
    python3 scripts/build_search_coverage.py kapsam.json
    python3 scripts/build_search_coverage.py arama.json \\
        -o <proje-kökü>/03_kaynak_kesfi
    python3 scripts/build_search_coverage.py kapsam.json --check
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # scripts/ içinden çalışırken
    from output_naming import timestamp_suffix
except ImportError:  # python -m scripts.build_search_coverage
    from scripts.output_naming import timestamp_suffix

SCHEMA_ID = "search-coverage/1"
OUTPUT_STEM = "01_arama_kapsam_raporu"

SOURCE_LABELS = {
    "openalex": "OpenAlex",
    "semantic_scholar": "Semantic Scholar",
    "pubmed": "PubMed",
    "europepmc": "Europe PMC",
    "crossref": "Crossref",
    "arxiv": "arXiv",
    "clinicaltrials": "ClinicalTrials.gov",
}

DEFINITIONS = {
    "score_formula": (
        "0.35 × anlamsal alaka + 0.25 × log10(atıf+1)/4 + "
        "0.15 × güncellik + 0.15 × dergi quartile + 0.10 × çalışma türü"
    ),
    "recency": "Son 2 yıl 1.0; 10 yıl ve üzeri 0.0; arası doğrusal azalır.",
    "quartile": "Q1=1.0, Q2=0.70, Q3=0.40, Q4=0.15, bilinmiyorsa 0.30.",
    "study_type": (
        "Sistematik derleme/meta-analiz ve RCT=1.0; klinik çalışma (girişim)=0.80; "
        "kohort/yarı deneysel=0.60; vaka-kontrol=0.50; kesitsel=0.40; "
        "nitel=0.35; tanımsız=0.25; preprint=0.05."
    ),
    "preprint_penalty": "Preprint sonuçların skoru 0.85 ile çarpılır ve is_preprint=true işaretlenir.",
    "high_quality": (
        "Yüksek kalite: preprint değil, skor ≥ 0.60 ve çalışma türü bileşeni ≥ 0.40."
    ),
    "high_quality_strict": (
        "Katı yüksek kalite: Q1/Q2 + en az 10 atıf + RCT veya "
        "sistematik derleme/meta-analiz."
    ),
    "trend": (
        "Son 3 yılın yıllık yayın sayısı eğimi; |eğim| < 0.34 ise sabit kabul edilir."
    ),
    "evidence_scarcity": (
        "Yüksek kaliteli sonuç sayısı 5'in altındaysa evidence_scarcity=true olur."
    ),
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def extract_payload(data: Any) -> Dict[str, Any]:
    """Girdiden coverage bloğunu ve bağlam alanlarını çıkar."""
    if not isinstance(data, dict):
        raise ValueError("Kök nesne bir JSON nesnesi olmalı.")
    if isinstance(data.get("coverage"), dict):
        coverage = data["coverage"]
        project = data.get("project")
        query = data.get("query") or data.get("question")
        results = data.get("results") or []
    elif "per_source" in data:
        coverage = data
        project = data.get("project")
        query = data.get("query")
        results = data.get("results") or []
    else:
        raise ValueError("'coverage' bloğu veya doğrudan coverage alanları bulunamadı.")
    return {
        "coverage": coverage,
        "project": project,
        "query": query,
        "results": results,
        "selected": data.get("selected") or [],
    }


def validate(data: Any) -> List[str]:
    errors: List[str] = []
    try:
        payload = extract_payload(data)
    except ValueError as exc:
        return [str(exc)]

    coverage = payload["coverage"]
    per_source = coverage.get("per_source")
    if not isinstance(per_source, dict) or not per_source:
        errors.append("coverage.per_source: boş olmayan nesne olmalı.")
    else:
        for name, stats in per_source.items():
            if not isinstance(stats, dict):
                errors.append(f"coverage.per_source.{name}: nesne olmalı.")
                continue
            for key in ("returned", "unique_dois", "high_quality"):
                value = stats.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    errors.append(
                        f"coverage.per_source.{name}.{key}: negatif olmayan tam sayı olmalı."
                    )
    if not isinstance(coverage.get("sources_queried"), list):
        errors.append("coverage.sources_queried: liste olmalı.")
    for key in ("total_unique_dois", "high_quality_total"):
        value = coverage.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"coverage.{key}: negatif olmayan tam sayı olmalı.")
    if not isinstance(coverage.get("evidence_scarcity"), bool):
        errors.append("coverage.evidence_scarcity: boolean olmalı.")
    if not isinstance(coverage.get("query_variants"), list):
        errors.append("coverage.query_variants: liste olmalı.")
    if not coverage.get("timestamp"):
        errors.append("coverage.timestamp: zorunlu.")

    for name, stats in (per_source or {}).items():
        if not isinstance(stats, dict):
            continue
        status = stats.get("status")
        if status is not None and status not in {"ok", "partial", "error", "rate_limited"}:
            errors.append(
                f"coverage.per_source.{name}.status: ok/partial/error/rate_limited olmalı."
            )
        for key in ("requested_limit", "duration_ms"):
            value = stats.get(key)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                errors.append(
                    f"coverage.per_source.{name}.{key}: negatif olmayan tam sayı olmalı."
                )
        if "note" in stats and not isinstance(stats["note"], (str, type(None))):
            errors.append(f"coverage.per_source.{name}.note: metin olmalı.")

    skipped = coverage.get("skipped_sources")
    if skipped is not None and not isinstance(skipped, list):
        errors.append("coverage.skipped_sources: liste olmalı.")
    warnings = coverage.get("warnings")
    if warnings is not None and not isinstance(warnings, list):
        errors.append("coverage.warnings: liste olmalı.")

    distribution = coverage.get("publisher_distribution")
    if distribution is not None:
        if not isinstance(distribution, dict):
            errors.append("coverage.publisher_distribution: nesne olmalı.")
        else:
            counts = distribution.get("counts")
            if counts is not None and not isinstance(counts, dict):
                errors.append("coverage.publisher_distribution.counts: nesne olmalı.")
            elif isinstance(counts, dict):
                for key, value in counts.items():
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                        errors.append(
                            f"coverage.publisher_distribution.counts.{key}: "
                            "negatif olmayan tam sayı olmalı."
                        )
            for key in ("open_access_ratio", "preprint_ratio", "pdf_link_ratio"):
                value = distribution.get(key)
                if value is not None and not isinstance(value, (int, float)):
                    errors.append(
                        f"coverage.publisher_distribution.{key}: sayı olmalı."
                    )

    expansion = coverage.get("query_expansion")
    if expansion is not None:
        if not isinstance(expansion, dict):
            errors.append("coverage.query_expansion: nesne olmalı.")
        else:
            for key in ("expanded", "mesh", "languages", "transformations", "notes"):
                if key in expansion and not isinstance(expansion[key], list):
                    errors.append(f"coverage.query_expansion.{key}: liste olmalı.")

    density = coverage.get("evidence_density")
    if density is not None:
        if not isinstance(density, dict):
            errors.append("coverage.evidence_density: nesne olmalı.")
        else:
            for key in (
                "total_results",
                "high_quality_total",
                "q1_total",
                "recent_total",
                "randomized_controlled_trial_total",
                "systematic_review_or_meta_analysis_total",
            ):
                if key in density and (
                    not isinstance(density[key], int)
                    or isinstance(density[key], bool)
                    or density[key] < 0
                ):
                    errors.append(
                        f"coverage.evidence_density.{key}: negatif olmayan tam sayı olmalı."
                    )
            for key in ("q1_ratio", "recent_ratio"):
                if key in density and not isinstance(density[key], (int, float)):
                    errors.append(f"coverage.evidence_density.{key}: sayı olmalı.")
            strict = density.get("high_quality_strict_total")
            if strict is not None and (
                not isinstance(strict, int) or isinstance(strict, bool) or strict < 0
            ):
                errors.append(
                    "coverage.evidence_density.high_quality_strict_total: "
                    "negatif olmayan tam sayı olmalı."
                )
            trend = density.get("trend")
            if trend is not None:
                if not isinstance(trend, dict):
                    errors.append("coverage.evidence_density.trend: nesne olmalı.")
                else:
                    direction = trend.get("direction")
                    if direction is not None and direction not in {
                        "artıyor", "azalıyor", "sabit", "belirsiz",
                    }:
                        errors.append(
                            "coverage.evidence_density.trend.direction: "
                            "artıyor/azalıyor/sabit/belirsiz olmalı."
                        )
                    counts = trend.get("counts")
                    if counts is not None and not isinstance(counts, dict):
                        errors.append(
                            "coverage.evidence_density.trend.counts: nesne olmalı."
                        )
    return errors


def _source_label(name: str) -> str:
    return SOURCE_LABELS.get(name, name)


def _status_badge(status: str) -> str:
    mapping = {
        "ok": ("✓", "ok", "Tamam"),
        "partial": ("◐", "warn", "Kısmi"),
        "error": ("!", "err", "Hata"),
        "rate_limited": ("⏳", "warn", "Hız limiti"),
        "skipped": ("✗", "skip", "Sorgulanmadı"),
    }
    symbol, css, label = mapping.get(status, ("?", "skip", status))
    return f'<span class="badge {css}">{symbol} {esc(label)}</span>'


def _render_warnings(coverage: Dict[str, Any]) -> str:
    warnings = coverage.get("warnings") or []
    if not warnings:
        return ""
    items = "".join(f"<li>{esc(value)}</li>" for value in warnings)
    return (
        '<div class="notice"><strong>Kaynak uyarıları:</strong>'
        f'<ul class="warning-list">{items}</ul></div>'
    )


def _render_publisher_distribution(coverage: Dict[str, Any]) -> str:
    distribution = coverage.get("publisher_distribution") or {}
    if not distribution:
        return ""
    counts = distribution.get("counts") or {}
    labels = distribution.get("labels") or {}
    ratios = distribution.get("ratios") or {}
    total = distribution.get("total", 0)
    rows = "".join(
        "<tr>"
        f"<td>{esc(labels.get(key, key))}</td>"
        f'<td class="num">{esc(count)}</td>'
        f'<td class="num">%{esc(round(float(ratios.get(key) or 0) * 100))}</td>'
        "</tr>"
        for key, count in counts.items()
    )
    oa_ratio = round(float(distribution.get("open_access_ratio") or 0) * 100)
    preprint_ratio = round(float(distribution.get("preprint_ratio") or 0) * 100)
    pdf_ratio = round(float(distribution.get("pdf_link_ratio") or 0) * 100)
    return f"""
  <section class="card">
    <h2>Publisher ve fulltext erişim dağılımı</h2>
    <div class="stats compact">
      <div class="stat"><span class="num">{esc(distribution.get("open_access_total", 0))}</span><small>Açık erişim (%{esc(oa_ratio)})</small></div>
      <div class="stat"><span class="num">{esc(distribution.get("preprint_total", 0))}</span><small>Preprint (%{esc(preprint_ratio)})</small></div>
      <div class="stat"><span class="num">{esc(distribution.get("pdf_link_total", 0))}</span><small>PDF bağlantısı (%{esc(pdf_ratio)})</small></div>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Platform / yayıncı</th><th>Kayıt</th><th>Oran</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div>
    <p class="muted">“Diğer yayıncı” beş öncelikli platform dışında bir yayıncı adı veya linki olan kayıtlardır; “Yayıncı bilinmiyor” hiç yayıncı bilgisi çözülemeyen kayıtlardır. Toplam: {esc(total)}.</p>
  </section>"""


def _merge_selected_into_results(
    results: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Sonuç listesine seçilip listede görünmeyen kaynakları ekle.

    Arama havuzu ile fulltext listesi farklı sorgulardan beslenebilir; bu
    yüzden seçilen bir kaynak ilk N sonuçta yer almayabilir. Tek bir tutarlı
    tabloda tüm seçimlerin görünmesi için eksik seçilmişler sona eklenir.
    """
    shown = list(results[:limit])
    present = {str(item.get("doi") or "").strip().lower() for item in shown}
    for entry in selected:
        doi = str(entry.get("doi") or "").strip().lower()
        if not doi or doi in present:
            continue
        shown.append(
            {
                "doi": entry.get("doi"),
                "title": entry.get("title"),
                "year": entry.get("year"),
                "journal": entry.get("journal"),
                "score": entry.get("score"),
                "cited_by": entry.get("citations"),
                "study_design": None,
            }
        )
        present.add(doi)
    return shown


def _render_results(
    results: List[Dict[str, Any]],
    selected_dois: Optional[set] = None,
) -> str:
    if not results:
        return '<p class="muted">Sonuç listesi bu raporda yer almıyor.</p>'
    selected_dois = selected_dois or set()
    rows: List[str] = []
    for index, item in enumerate(results, start=1):
        doi = str(item.get("doi") or "").strip()
        doi_html = (
            f'<a href="https://doi.org/{esc(doi)}" target="_blank" rel="noopener">{esc(doi)}</a>'
            if doi
            else "—"
        )
        score = item.get("score")
        score_text = f"{float(score):.3f}" if isinstance(score, (int, float)) else "—"
        selected_badge = (
            '<span class="badge selected">seçildi</span>'
            if doi and doi.lower() in selected_dois
            else ""
        )
        rows.append(
            "<tr>"
            f'<td class="num">{index}{selected_badge}</td>'
            f'<td><div class="title">{esc(item.get("title") or "—")}</div>'
            f'<div class="muted">{esc(item.get("journal") or "")}'
            f'{" · " + esc(item.get("year")) if item.get("year") else ""}</div></td>'
            f'<td>{esc(item.get("study_design") or "—")}</td>'
            f'<td class="num">{esc(score_text)}</td>'
            f'<td class="num">{esc(item.get("cited_by") if item.get("cited_by") is not None else "—")}</td>'
            f'<td class="doi">{doi_html}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>#</th><th>Kaynak</th><th>Çalışma türü</th><th>Skor</th>"
        "<th>Atıf</th><th>DOI</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        '<p class="muted">“seçildi” etiketi, kaynağın fulltext listesi HTML\'ine '
        "aktarıldığını gösterir.</p>"
    )


def _render_query_expansion(coverage: Dict[str, Any], query: str) -> str:
    expansion = coverage.get("query_expansion") or {}
    original = expansion.get("original") or query
    expanded = expansion.get("expanded") or []
    mesh = expansion.get("mesh") or []
    languages = expansion.get("languages") or []
    transformations = expansion.get("transformations") or []
    notes = expansion.get("notes") or []

    def chips(values: List[str], empty: str) -> str:
        return (
            "".join(
                f'<span class="chip">{esc("yok" if value == "none" else value)}</span>'
                for value in values
            )
            or f'<span class="muted">{esc(empty)}</span>'
        )

    expanded_html = (
        "<ol class=\"query-list\">"
        + "".join(f"<li><code>{esc(value)}</code></li>" for value in expanded)
        + "</ol>"
        if expanded
        else '<p class="muted">Ek genişletilmiş sorgu bildirilmedi.</p>'
    )
    notes_html = (
        "<ul class=\"defs\">"
        + "".join(f"<li>{esc(value)}</li>" for value in notes)
        + "</ul>"
        if notes
        else ""
    )
    return f"""
  <section class="card">
    <h2>Sorgu ve genişletme</h2>
    <p><span class="label">Orijinal sorgu</span><br><code>{esc(original or "—")}</code></p>
    <p><span class="label">Genişletilmiş sorgular</span></p>
    {expanded_html}
    <div class="grid2">
      <div>
        <span class="label">MeSH terimleri</span>
        <p>{chips(mesh, "MeSH terimi bildirilmedi")}</p>
      </div>
      <div>
        <span class="label">Dil / dönüşüm</span>
        <p>{chips(languages, "Dil dönüşümü bildirilmedi")}</p>
      </div>
    </div>
    <p><span class="label">Kullanılan dönüşümler</span><br>{chips(transformations, "Belirtilmedi")}</p>
    {notes_html}
  </section>"""


def _render_evidence_density(coverage: Dict[str, Any]) -> str:
    density = coverage.get("evidence_density") or {}
    if not density:
        return ""
    total = density.get("total_results", 0)
    high_quality = density.get("high_quality_total", 0)
    q1 = density.get("q1_total", 0)
    recent = density.get("recent_total", 0)
    recent_ratio = density.get("recent_ratio", 0.0)
    window = density.get("recent_window_years", 5)
    window_start = density.get("recent_window_start", "—")
    rct = density.get("randomized_controlled_trial_total", 0)
    review = density.get("systematic_review_or_meta_analysis_total", 0)
    clinical = density.get("clinical_trial_total", 0)
    preprint = density.get("preprint_total", 0)
    strict = density.get("high_quality_strict_total", 0)
    trend = density.get("trend") or {}
    trend_html = ""
    if trend:
        counts = trend.get("counts") or {}
        count_text = " · ".join(f"{esc(year)}: <strong>{esc(count)}</strong>" for year, count in counts.items())
        change = trend.get("change_ratio")
        change_text = (
            f" · değişim %{esc(round(float(change) * 100))}" if isinstance(change, (int, float)) else ""
        )
        trend_html = (
            '<p class="trend"><span class="label">Yayın sayısı trendi '
            f'(son {esc(trend.get("window_years", 3))} yıl)</span><br>'
            f'<span class="badge {"good" if trend.get("direction") == "artıyor" else "skip"}">'
            f'{esc(trend.get("direction"))}</span> {count_text}{change_text}</p>'
        )
    designs = density.get("study_designs") or {}
    design_rows = "".join(
        f"<tr><td>{esc(label)}</td><td class=\"num\">{esc(count)}</td></tr>"
        for label, count in designs.items()
    )
    return f"""
  <section class="card">
    <h2>Kanıt yoğunluğu ve negatif sinyaller</h2>
    <div class="stats compact">
      <div class="stat"><span class="num">{esc(high_quality)}</span><small>Yüksek kaliteli (eşik {esc(coverage.get("high_quality_threshold", 0.6))})</small></div>
      <div class="stat"><span class="num">{esc(strict)}</span><small>Katı yüksek kalite (Q1/Q2 + atıf + RCT/SR/MA)</small></div>
      <div class="stat"><span class="num">{esc(q1)}</span><small>Q1 dergi</small></div>
      <div class="stat"><span class="num">{esc(recent)}</span><small>Son {esc(window)} yıl ({esc(window_start)}+)</small></div>
      <div class="stat"><span class="num">%{esc(round(float(recent_ratio or 0) * 100))}</span><small>Son {esc(window)} yıl oranı</small></div>
      <div class="stat"><span class="num">{esc(rct)}</span><small>RCT</small></div>
      <div class="stat"><span class="num">{esc(review)}</span><small>Sistematik derleme / meta-analiz</small></div>
      <div class="stat"><span class="num">{esc(clinical)}</span><small>Klinik çalışma</small></div>
      <div class="stat"><span class="num">{esc(preprint)}</span><small>Preprint</small></div>
    </div>
    <p class="muted">Toplam değerlendirilen kayıt: {esc(total)}. Sinyaller ön eleme göstergesidir; sistematik derleme yerine geçmez.</p>
    {trend_html}
    <details>
      <summary>Çalışma türü dağılımı</summary>
      <div class="table-wrap"><table>
        <thead><tr><th>Çalışma türü</th><th>Kayıt</th></tr></thead>
        <tbody>{design_rows or '<tr><td>—</td><td class="num">0</td></tr>'}</tbody>
      </table></div>
    </details>
  </section>"""


def _render_closest(coverage: Dict[str, Any]) -> str:
    closest = coverage.get("closest_studies") or []
    if not closest:
        return ""
    rows = []
    for index, item in enumerate(closest, start=1):
        doi = str(item.get("doi") or "").strip()
        doi_html = (
            f'<a href="https://doi.org/{esc(doi)}" target="_blank" rel="noopener">{esc(doi)}</a>'
            if doi
            else "—"
        )
        score = item.get("score")
        score_text = f"{float(score):.3f}" if isinstance(score, (int, float)) else "—"
        rows.append(
            "<tr>"
            f'<td class="num">{index}</td>'
            f'<td><div class="title">{esc(item.get("title") or "—")}</div>'
            f'<div class="muted">{esc(item.get("year") or "yıl yok")}'
            f'{" · " + esc(item.get("study_design")) if item.get("study_design") else ""}</div></td>'
            f'<td class="num">{esc(score_text)}</td>'
            f'<td class="doi">{doi_html}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>#</th><th>En yakın çalışma</th><th>Skor</th><th>DOI</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def render(data: Any) -> str:
    payload = extract_payload(data if isinstance(data, dict) else {})
    if not payload["coverage"].get("per_source"):
        raise ValueError("coverage.per_source boş.")
    coverage = payload["coverage"]
    per_source = coverage.get("per_source") or {}
    results = payload.get("results") or []
    scarcity = bool(coverage.get("evidence_scarcity"))
    generated = coverage.get("timestamp") or datetime.now(timezone.utc).date().isoformat()
    project = payload.get("project") or "—"
    query = payload.get("query") or "—"
    variants = coverage.get("query_variants") or []

    source_count = len(coverage.get("sources_queried") or [])
    total_dois = coverage.get("total_unique_dois", 0)
    high_quality_total = coverage.get("high_quality_total", 0)

    source_rows = "".join(
        "<tr>"
        f"<td><strong>{esc(_source_label(name))}</strong></td>"
        f"<td>{_status_badge(stats.get('status', 'ok'))}</td>"
        f'<td class="num">{esc(stats.get("returned", 0))}</td>'
        f'<td class="num">{esc(stats.get("unique_dois", 0))}</td>'
        f'<td class="num">{esc(stats.get("high_quality", 0))}</td>'
        f'<td class="num">{esc(stats.get("requested_limit") if stats.get("requested_limit") is not None else "—")}</td>'
        f'<td class="num">{esc(str(stats.get("duration_ms")) + " ms" if stats.get("duration_ms") is not None else "—")}</td>'
        f'<td class="note">{esc(stats.get("note") or "—")}'
        + (
            f'<div class="error-text">{esc(stats.get("error"))}</div>'
            if stats.get("error")
            else ""
        )
        + "</td>"
        "</tr>"
        for name, stats in per_source.items()
    )
    skipped_rows = "".join(
        "<tr class=\"skipped\">"
        f"<td><strong>{esc(_source_label(entry.get('source', '?')))}</strong></td>"
        f"<td>{_status_badge('skipped')}</td>"
        '<td class="num">—</td><td class="num">—</td><td class="num">—</td>'
        '<td class="num">—</td><td class="num">—</td>'
        f"<td class=\"note\">{esc(entry.get('reason') or 'istekte bulunulmadı')}</td>"
        "</tr>"
        for entry in coverage.get("skipped_sources") or []
    )
    source_total_row = (
        "<tr class=\"total\">"
        "<td><strong>Toplam (tekilleştirilmiş)</strong></td>"
        "<td>—</td>"
        f'<td class="num">{esc(sum(int(s.get("returned") or 0) for s in per_source.values()))}</td>'
        f'<td class="num">{esc(total_dois)}</td>'
        f'<td class="num">{esc(high_quality_total)}</td>'
        '<td class="num">—</td><td class="num">—</td>'
        '<td class="note">Tekilleştirme sonrası toplam DOI ve yüksek kalite sayısı.</td>'
        "</tr>"
    )
    variant_html = "".join(
        f'<span class="chip">{esc(value)}</span>' for value in variants
    ) or '<span class="muted">Belirtilmedi</span>'
    scarcity_badge = (
        '<span class="badge warn">Evet</span>'
        if scarcity
        else '<span class="badge good">Hayır</span>'
    )

    definitions_html = "".join(
        f"<li><strong>{esc(key)}:</strong> {esc(value)}</li>"
        for key, value in DEFINITIONS.items()
    )
    scarcity_html = ""
    if scarcity:
        message = coverage.get("evidence_scarcity_message") or (
            "Bu konuda yüksek kaliteli kanıt sınırlı görünüyor."
        )
        closest_html = _render_closest(coverage)
        scarcity_html = (
            '<div class="alert"><strong>Kanıt sınırlılığı:</strong> '
            f"{esc(message)}"
            + (f'<div class="closest">{closest_html}</div>' if closest_html else "")
            + "</div>"
        )
    query_html = _render_query_expansion(coverage, query)
    density_html = _render_evidence_density(coverage)
    warnings_html = _render_warnings(coverage)
    publisher_html = _render_publisher_distribution(coverage)
    selected_entries = _selected_section(coverage, data)
    selected_dois = {
        str(entry.get("doi") or "").strip().lower()
        for entry in selected_entries
        if str(entry.get("doi") or "").strip()
    }
    display_results = _merge_selected_into_results(results, selected_entries)

    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arama kapsam raporu — {esc(query)}</title>
<style>
:root {{ --bg:#f4f6f8; --card:#fff; --ink:#16212b; --muted:#5b6b7b; --line:#dbe2e9; --blue:#0b5cad; --green:#1e7d4f; --red:#b3261e; --amber:#9a6400; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
header {{ background:#0b2540; color:#fff; padding:28px 22px; }}
header h1 {{ margin:6px 0; font-size:25px; }}
header p {{ margin:0; opacity:.9; max-width:900px; }}
main {{ max-width:1100px; margin:0 auto; padding:20px 22px 40px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:16px 0; }}
.stats.compact {{ grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
.stat .num {{ font-size:24px; font-weight:700; display:block; }}
.stat small {{ color:var(--muted); }}
.label {{ font-size:12px; font-weight:700; letter-spacing:.03em; text-transform:uppercase; color:var(--muted); }}
.query-list {{ margin:6px 0 12px 20px; padding:0; }}
.query-list li {{ margin:4px 0; }}
.grid2 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }}
.closest {{ margin-top:10px; color:var(--ink); }}
.closest th {{ color:var(--muted); }}
details {{ margin-top:10px; }}
summary {{ cursor:pointer; color:var(--blue); font-size:13px; }}
.alert {{ background:#fff4f2; border:1px solid #f2c2bd; color:#7d1f18; border-radius:10px; padding:12px 14px; margin:14px 0; }}
.ok {{ background:#eefaf2; border:1px solid #bfe3cd; color:var(--green); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:16px 0; }}
h2 {{ font-size:18px; margin:4px 0 10px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); border-bottom:1px solid var(--line); padding:8px 10px; }}
td {{ border-bottom:1px solid var(--line); padding:9px 10px; vertical-align:top; }}
td.num {{ text-align:right; white-space:nowrap; }}
.table-wrap {{ overflow-x:auto; }}
.title {{ font-weight:600; }}
.muted {{ color:var(--muted); font-size:12.5px; }}
.chip {{ display:inline-block; background:#e7f0fa; color:var(--blue); border-radius:999px; padding:2px 10px; margin:2px 6px 2px 0; font-size:12.5px; }}
.defs {{ font-size:13px; color:var(--muted); }}
.defs li {{ margin:4px 0; }}
.badge {{ display:inline-block; border-radius:999px; padding:2px 10px; font-size:12px; font-weight:700; }}
.badge.warn {{ background:#fde8e6; color:var(--red); }}
.badge.good {{ background:#e2f4ea; color:var(--green); }}
.badge.selected {{ background:#e2f4ea; color:var(--green); margin-left:6px; }}
.badge.ok {{ background:#e2f4ea; color:var(--green); }}
.badge.err {{ background:#fde8e6; color:var(--red); }}
.badge.skip {{ background:#f0f2f4; color:var(--muted); }}
.badge.prio {{ background:#e7f0fa; color:var(--blue); }}
td.why {{ font-size:12.5px; max-width:380px; }}
.notice {{ background:#fffdf3; border:1px solid #f0e2b6; color:#6b4f00; border-radius:10px; padding:12px 14px; margin:14px 0; }}
.warning-list {{ margin:6px 0 0 20px; padding:0; }}
.warning-list li {{ margin:3px 0; }}
tr.skipped td {{ color:var(--muted); }}
tr.total td {{ background:#f8fafc; font-weight:600; }}
td.note {{ font-size:12.5px; color:var(--muted); max-width:300px; }}
.error-text {{ color:var(--red); font-size:12px; margin-top:3px; }}
footer {{ max-width:1100px; margin:0 auto; padding:0 22px 36px; color:var(--muted); font-size:12.5px; }}
@media print {{ body {{ background:#fff; }} header {{ background:#fff; color:#000; border-bottom:2px solid #000; }} .card,.stat {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<header>
  <div class="muted" style="color:#cfe0f2;text-transform:uppercase;letter-spacing:.08em">Arama kapsam raporu</div>
  <h1>{esc(query)}</h1>
  <p>Proje: <strong>{esc(project)}</strong> · Oluşturma: {esc(generated)}</p>
</header>
<main>
  <section class="stats">
    <div class="stat"><span class="num">{source_count}</span><small>Sorgulanan kaynak</small></div>
    <div class="stat"><span class="num">{esc(total_dois)}</span><small>Tekil DOI</small></div>
    <div class="stat"><span class="num">{esc(high_quality_total)}</span><small>Yüksek kalite</small></div>
    <div class="stat"><span class="num">{scarcity_badge}</span><small>Kanıt sınırlılığı</small></div>
  </section>
  {scarcity_html}
  {warnings_html}
  {query_html}
  {density_html}
  {publisher_html}
  <section class="card">
    <h2>Kaynak bazında kapsam</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Kaynak</th><th>Durum</th><th>Dönen kayıt</th><th>Tekil DOI</th><th>Yüksek kalite</th><th>İstenen limit</th><th>Süre</th><th>Not</th></tr></thead>
      <tbody>{source_rows}{skipped_rows}{source_total_row}</tbody>
    </table></div>
    <p class="muted">“Dönen kayıt” kaynağın verdiği ham sonuç sayısıdır; tekilleştirme sonrası toplam DOI sayısı toplam satırındadır.</p>
  </section>
  <section class="card">
    <h2>Sorgu varyantları</h2>
    <p>{variant_html}</p>
  </section>
  <section class="card">
    <h2>Öne çıkan sonuçlar</h2>
    {_render_results(display_results, selected_dois)}
    <p class="muted">Skor bir ön eleme göstergesidir; kanıt değildir. Kanıt için tam metin sayfası doğrulanmalıdır.</p>
  </section>
  <section class="card">
    <h2>Yöntem ve tanımlar</h2>
    <ul class="defs">{definitions_html}</ul>
  </section>
</main>
<footer>
  Bu rapor yalnızca sorgulanan açık metadata kaynaklarının kapsamını gösterir.
  Kaynakların sessizce başarısız olduğu durumlar dönen kayıt sayısına yansımaz;
  ayrıntı için arama cevabındaki <code>notes</code> alanına bakın.
</footer>
</body>
</html>
"""


def _md_cell(value: Any) -> str:
    """Escape a value for a Markdown table cell.

    ``<``/``>`` are escaped so untrusted titles cannot inject raw HTML when the
    Markdown file is rendered by a viewer that allows inline HTML.
    """
    text = str("" if value is None else value)
    text = text.replace("|", "\\|").replace("\n", " ")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return text.strip()


def render_markdown(data: Any) -> str:
    """Render the coverage report as a compact, printable Markdown document."""
    payload = extract_payload(data if isinstance(data, dict) else {})
    coverage = payload["coverage"]
    if not coverage.get("per_source"):
        raise ValueError("coverage.per_source boş.")
    per_source = coverage.get("per_source") or {}
    results = payload.get("results") or []
    query = payload.get("query") or "—"
    project = payload.get("project") or "—"
    generated = coverage.get("timestamp") or datetime.now(timezone.utc).isoformat()

    lines: List[str] = []
    lines.append(f"# Arama Kapsam Raporu — {_md_cell(query)}")
    lines.append("")
    lines.append(f"- Proje: **{_md_cell(project)}**")
    lines.append(f"- Oluşturma: {_md_cell(generated)}")
    lines.append(f"- Sorgulanan kaynak: {len(coverage.get('sources_queried') or [])}")
    lines.append(f"- Tekil DOI: {coverage.get('total_unique_dois', 0)}")
    lines.append(f"- Yüksek kalite: {coverage.get('high_quality_total', 0)}")
    lines.append(
        "- Kanıt sınırlılığı: "
        + ("**Evet**" if coverage.get("evidence_scarcity") else "Hayır")
    )
    lines.append("")

    if coverage.get("evidence_scarcity"):
        lines.append("> **Kanıt sınırlılığı:** " + _md_cell(coverage.get("evidence_scarcity_message")))
        lines.append("")

    warnings = coverage.get("warnings") or []
    if warnings:
        lines.append("## Kaynak uyarıları")
        lines.append("")
        lines.extend(f"- {_md_cell(value)}" for value in warnings)
        lines.append("")

    expansion = coverage.get("query_expansion") or {}
    lines.append("## Sorgu ve genişletme")
    lines.append("")
    lines.append(f"- Orijinal sorgu: `{_md_cell(expansion.get('original') or query)}`")
    expanded = expansion.get("expanded") or []
    if expanded:
        lines.append("- Genişletilmiş sorgular:")
        lines.extend(f"  {index}. `{_md_cell(value)}`" for index, value in enumerate(expanded, 1))
    lines.append(
        "- MeSH: " + (", ".join(f"`{_md_cell(v)}`" for v in expansion.get("mesh") or []) or "bildirilmedi")
    )
    lines.append(
        "- Dil: " + (", ".join(_md_cell(v) for v in expansion.get("languages") or []) or "bildirilmedi")
    )
    lines.append(
        "- Dönüşümler: "
        + (
            ", ".join(
                "yok" if value == "none" else _md_cell(value)
                for value in expansion.get("transformations") or []
            )
            or "belirtilmedi"
        )
    )
    for note in expansion.get("notes") or []:
        lines.append(f"- Not: {_md_cell(note)}")
    lines.append("")

    density = coverage.get("evidence_density") or {}
    if density:
        lines.append("## Kanıt yoğunluğu")
        lines.append("")
        lines.append("| Gösterge | Değer |")
        lines.append("|---|---|")
        lines.append(f"| Yüksek kaliteli | {density.get('high_quality_total', 0)} |")
        lines.append(
            f"| Yüksek kaliteli (katı: Q1/Q2 + atıf + RCT/SR/MA) | "
            f"{density.get('high_quality_strict_total', 0)} |"
        )
        lines.append(f"| Q1 dergi | {density.get('q1_total', 0)} (%{round(float(density.get('q1_ratio') or 0) * 100)}) |")
        lines.append(
            f"| Son {density.get('recent_window_years', 5)} yıl | "
            f"{density.get('recent_total', 0)} (%{round(float(density.get('recent_ratio') or 0) * 100)}) |"
        )
        lines.append(f"| RCT | {density.get('randomized_controlled_trial_total', 0)} |")
        lines.append(f"| Sistematik derleme / meta-analiz | {density.get('systematic_review_or_meta_analysis_total', 0)} |")
        lines.append(f"| Klinik çalışma | {density.get('clinical_trial_total', 0)} |")
        lines.append(f"| Preprint | {density.get('preprint_total', 0)} |")
        trend = density.get("trend") or {}
        if trend:
            counts = trend.get("counts") or {}
            count_text = ", ".join(f"{year}: {count}" for year, count in counts.items())
            lines.append(
                f"| Trend (son {trend.get('window_years', 3)} yıl) | "
                f"{_md_cell(trend.get('direction'))} ({count_text}) |"
            )
        lines.append("")

    distribution = coverage.get("publisher_distribution") or {}
    if distribution:
        lines.append("## Publisher ve fulltext erişim dağılımı")
        lines.append("")
        lines.append("| Platform / yayıncı | Kayıt | Oran |")
        lines.append("|---|---|---|")
        labels = distribution.get("labels") or {}
        ratios = distribution.get("ratios") or {}
        for key, count in (distribution.get("counts") or {}).items():
            lines.append(
                f"| {_md_cell(labels.get(key, key))} | {count} | "
                f"%{round(float(ratios.get(key) or 0) * 100)} |"
            )
        lines.append("")
        lines.append(
            f"- Açık erişim: {distribution.get('open_access_total', 0)} "
            f"(%{round(float(distribution.get('open_access_ratio') or 0) * 100)})"
        )
        lines.append(
            f"- Preprint: {distribution.get('preprint_total', 0)} "
            f"(%{round(float(distribution.get('preprint_ratio') or 0) * 100)})"
        )
        lines.append(
            f"- PDF bağlantısı: {distribution.get('pdf_link_total', 0)} "
            f"(%{round(float(distribution.get('pdf_link_ratio') or 0) * 100)})"
        )
        lines.append("")

    lines.append("## Kaynak bazında kapsam")
    lines.append("")
    lines.append("| Kaynak | Durum | Dönen | Tekil DOI | Yüksek kalite | İstenen limit | Süre | Not |")
    lines.append("|---|---|---|---|---|---|---|---|")
    status_labels = {
        "ok": "Tamam",
        "partial": "Kısmi",
        "error": "Hata",
        "rate_limited": "Hız limiti",
        "skipped": "Sorgulanmadı",
    }
    for name, stats in per_source.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(_source_label(name)),
                    _md_cell(status_labels.get(stats.get("status", "ok"), stats.get("status"))),
                    _md_cell(stats.get("returned", 0)),
                    _md_cell(stats.get("unique_dois", 0)),
                    _md_cell(stats.get("high_quality", 0)),
                    _md_cell(stats.get("requested_limit") if stats.get("requested_limit") is not None else "—"),
                    _md_cell(f"{stats.get('duration_ms')} ms" if stats.get("duration_ms") is not None else "—"),
                    _md_cell(stats.get("note") or "—"),
                ]
            )
            + " |"
        )
    for entry in coverage.get("skipped_sources") or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(_source_label(entry.get("source", "?"))),
                    "Sorgulanmadı",
                    "—", "—", "—", "—", "—",
                    _md_cell(entry.get("reason") or "istekte bulunulmadı"),
                ]
            )
            + " |"
        )
    lines.append(
        f"| **Toplam (tekilleştirilmiş)** | — | "
        f"{sum(int(s.get('returned') or 0) for s in per_source.values())} | "
        f"{coverage.get('total_unique_dois', 0)} | "
        f"{coverage.get('high_quality_total', 0)} | — | — | — |"
    )
    lines.append("")

    if results:
        lines.append("## Öne çıkan sonuçlar")
        lines.append("")
        lines.append("| # | Kaynak | Çalışma türü | Skor | Atıf | DOI |")
        lines.append("|---|---|---|---|---|---|")
        for index, item in enumerate(results[:25], start=1):
            doi = str(item.get("doi") or "").strip()
            score = item.get("score")
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(index),
                        _md_cell(item.get("title") or "—"),
                        _md_cell(item.get("study_design") or "—"),
                        f"{float(score):.3f}" if isinstance(score, (int, float)) else "—",
                        _md_cell(item.get("cited_by") if item.get("cited_by") is not None else "—"),
                        f"[{_md_cell(doi)}](https://doi.org/{doi})" if doi else "—",
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.append("## Yöntem ve tanımlar")
    lines.append("")
    lines.extend(f"- **{key}:** {value}" for key, value in DEFINITIONS.items())
    lines.append("")
    lines.append(
        "_Bu rapor yalnızca sorgulanan açık metadata kaynaklarının kapsamını gösterir. "
        "Skor bir ön eleme göstergesidir; kanıt değildir._"
    )
    lines.append("")
    return "\n".join(lines)


def payload_label(data: Any) -> str:
    """Short label for one side of a comparison."""
    payload = extract_payload(data if isinstance(data, dict) else {})
    coverage = payload["coverage"]
    expansion = coverage.get("query_expansion") or {}
    query = expansion.get("original") or payload.get("query") or "A"
    return str(query)[:60]


def compare_coverage(
    left_payload: Any,
    right_payload: Any,
    left_label: str = "A",
    right_label: str = "B",
) -> Dict[str, Any]:
    """Compare two search payloads for the same topic.

    ``total_unique_dois``/``high_quality_total`` and per-source counts come from
    the coverage block (all merged records). DOI overlap is computed only from
    the ``results`` arrays actually returned to the caller, so it reflects the
    visible page, not the full merged pool.
    """
    left = extract_payload(left_payload) if isinstance(left_payload, dict) else None
    right = extract_payload(right_payload) if isinstance(right_payload, dict) else None
    if not left or not right:
        raise ValueError("Karşılaştırma için iki geçerli arama cevabı gerekir.")

    def stats(payload: Dict[str, Any]) -> Dict[str, Any]:
        block = payload["coverage"]
        return {
            "total_unique_dois": int(block.get("total_unique_dois") or 0),
            "high_quality_total": int(block.get("high_quality_total") or 0),
            "evidence_scarcity": bool(block.get("evidence_scarcity")),
            "sources": {
                name: {
                    "returned": int(value.get("returned") or 0),
                    "unique_dois": int(value.get("unique_dois") or 0),
                    "high_quality": int(value.get("high_quality") or 0),
                    "status": value.get("status", "ok"),
                }
                for name, value in (block.get("per_source") or {}).items()
            },
        }

    left_stats = stats(left)
    right_stats = stats(right)
    names = sorted(set(left_stats["sources"]) | set(right_stats["sources"]))
    per_source: Dict[str, Dict[str, Any]] = {}
    for name in names:
        a = left_stats["sources"].get(
            name, {"returned": 0, "unique_dois": 0, "high_quality": 0, "status": "skipped"}
        )
        b = right_stats["sources"].get(
            name, {"returned": 0, "unique_dois": 0, "high_quality": 0, "status": "skipped"}
        )
        per_source[name] = {
            "left": a,
            "right": b,
            "delta_unique_dois": b["unique_dois"] - a["unique_dois"],
            "delta_high_quality": b["high_quality"] - a["high_quality"],
        }

    def dois(payload: Dict[str, Any]) -> set:
        found = set()
        for item in payload.get("results") or []:
            doi = str(item.get("doi") or "").strip().lower()
            if doi:
                found.add(doi)
        return found

    left_dois = dois(left)
    right_dois = dois(right)
    overlap: Optional[int] = None
    only_left: List[str] = []
    only_right: List[str] = []
    if left_dois or right_dois:
        overlap = len(left_dois & right_dois)
        only_left = sorted(left_dois - right_dois)
        only_right = sorted(right_dois - left_dois)

    return {
        "left_label": left_label,
        "right_label": right_label,
        "left": left_stats,
        "right": right_stats,
        "per_source": per_source,
        "delta_total_unique_dois": (
            right_stats["total_unique_dois"] - left_stats["total_unique_dois"]
        ),
        "delta_high_quality_total": (
            right_stats["high_quality_total"] - left_stats["high_quality_total"]
        ),
        "doi_overlap": overlap,
        "doi_only_left_total": len(only_left),
        "doi_only_right_total": len(only_right),
        "doi_only_left": only_left[:50],
        "doi_only_right": only_right[:50],
        "left_timestamp": left["coverage"].get("timestamp"),
        "right_timestamp": right["coverage"].get("timestamp"),
    }


def render_comparison(comparison: Dict[str, Any]) -> str:
    """Render a two-run coverage comparison as a small offline HTML page."""
    left_label = esc(comparison.get("left_label"))
    right_label = esc(comparison.get("right_label"))
    rows = []
    status_labels = {
        "ok": "Tamam",
        "partial": "Kısmi",
        "error": "Hata",
        "rate_limited": "Hız limiti",
        "skipped": "Sorgulanmadı",
    }
    for name, entry in (comparison.get("per_source") or {}).items():
        a = entry.get("left") or {}
        b = entry.get("right") or {}
        rows.append(
            "<tr>"
            f"<td><strong>{esc(_source_label(name))}</strong></td>"
            f"<td>{esc(status_labels.get(a.get('status'), a.get('status')))}</td>"
            f'<td class="num">{esc(a.get("unique_dois", 0))}</td>'
            f"<td>{esc(status_labels.get(b.get('status'), b.get('status')))}</td>"
            f'<td class="num">{esc(b.get("unique_dois", 0))}</td>'
            f'<td class="num">{entry.get("delta_unique_dois", 0):+d}</td>'
            f'<td class="num">{entry.get("delta_high_quality", 0):+d}</td>'
            "</tr>"
        )
    overlap = comparison.get("doi_overlap")
    overlap_text = "—" if overlap is None else str(overlap)
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arama kapsamı karşılaştırması</title>
<style>
body {{ margin:0; background:#f4f6f8; color:#16212b; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
main {{ max-width:1000px; margin:0 auto; padding:24px 22px 40px; }}
h1 {{ font-size:22px; }}
.card {{ background:#fff; border:1px solid #dbe2e9; border-radius:10px; padding:16px; margin:16px 0; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; font-size:12px; text-transform:uppercase; color:#5b6b7b; border-bottom:1px solid #dbe2e9; padding:8px 10px; }}
td {{ border-bottom:1px solid #dbe2e9; padding:9px 10px; }}
td.num {{ text-align:right; white-space:nowrap; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
.stat {{ background:#fff; border:1px solid #dbe2e9; border-radius:10px; padding:12px 14px; }}
.stat .num {{ font-size:22px; font-weight:700; display:block; }}
.muted {{ color:#5b6b7b; font-size:12.5px; }}
@media print {{ body {{ background:#fff; }} }}
</style></head><body><main>
<h1>Arama kapsamı karşılaştırması</h1>
<p class="muted">Sol: <strong>{left_label}</strong> · Sağ: <strong>{right_label}</strong></p>
<section class="stats">
  <div class="stat"><span class="num">{comparison.get("delta_total_unique_dois", 0):+d}</span><small>Tekil DOI farkı (sağ − sol)</small></div>
  <div class="stat"><span class="num">{comparison.get("delta_high_quality_total", 0):+d}</span><small>Yüksek kalite farkı</small></div>
  <div class="stat"><span class="num">{overlap_text}</span><small>Ortak DOI</small></div>
  <div class="stat"><span class="num">{comparison.get("doi_only_right_total", 0)}</span><small>Yalnızca sağda</small></div>
</section>
<section class="card">
  <h2>Kaynak bazında</h2>
  <table>
    <thead><tr><th>Kaynak</th><th>Sol durum</th><th>Sol DOI</th><th>Sağ durum</th><th>Sağ DOI</th><th>DOI farkı</th><th>Yüksek kalite farkı</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <p class="muted">Farklar yalnızca iki taramanın ulaştığı kapsamı gösterir; bir sorgunun diğerinden “daha iyi” olduğunu göstermez. DOI örtüşmesi yalnızca cevapta dönen sonuç sayfasından hesaplanır; toplam havuz değildir.</p>
</section>
</main></body></html>
"""


def _selected_section(coverage: Dict[str, Any], data: Any) -> List[Dict[str, Any]]:
    """Kapsam raporundaki ``selected`` listesini (seçilen makaleler) oku."""
    source = data if isinstance(data, dict) else {}
    selected = source.get("selected") or coverage.get("selected") or []
    return [entry for entry in selected if isinstance(entry, dict)]


def load_selected(
    path: Path,
    fulltext_dirs: Optional[List[Path]] = None,
) -> List[Dict[str, Any]]:
    """Fulltext listesi JSON'undan seçilen makaleleri kapsam raporuna taşı."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Fulltext listesi kök nesnesi bir JSON nesnesi olmalı.")
    candidates = data.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError("Fulltext listesinde 'candidates' bir liste olmalı.")
    fulltext_dirs = list(fulltext_dirs or [])
    pdf_names: List[str] = []
    for directory in fulltext_dirs:
        if directory.is_dir():
            pdf_names.extend(item.name for item in directory.glob("*.pdf"))

    selected: List[Dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        doi = str(item.get("doi") or "").strip()
        downloaded = False
        if doi:
            keys = [
                doi.replace("/", "_"),
                doi.replace("/", ""),
                doi.replace("/", "-"),
            ]
            downloaded = any(
                key and any(key in name for name in pdf_names) for key in keys
            )
        selected.append(
            {
                "doi": doi,
                "title": item.get("title"),
                "year": item.get("year"),
                "journal": item.get("journal"),
                "priority": item.get("priority"),
                "quartile": item.get("quartile"),
                "citations": item.get("citations"),
                "open_access": item.get("open_access"),
                "rationale": item.get("rationale"),
                "transfer_note": (
                    "Fulltext HTML'e aktarıldı; PDF indirildi"
                    if downloaded
                    else "Fulltext HTML'e aktarıldı; PDF bekliyor"
                ),
            }
        )
    return selected


def _unique_stem(output_dir: Path, stem: str, suffixes: List[str]) -> str:
    """Aynı saniyedeki ikinci çalıştırma için ``-01``, ``-02`` … üret.

    Hiçbir dosya silinmez veya ezilmez; çakışan ada sahip bir sürüm varsa
    yeni sürüm numaralı bir ad alır.
    """
    if not any((output_dir / f"{stem}{suffix}").exists() for suffix in suffixes):
        return stem
    for index in range(1, 100):
        candidate = f"{stem}-{index:02d}"
        if not any((output_dir / f"{candidate}{suffix}").exists() for suffix in suffixes):
            return candidate
    raise FileExistsError(f"Boş bir çıktı adı bulunamadı: {stem}")


def build_report(data: Any) -> Dict[str, Any]:
    payload = extract_payload(data)
    return {
        "schema": SCHEMA_ID,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project": payload.get("project"),
        "query": payload.get("query"),
        "coverage": payload["coverage"],
        "definitions": DEFINITIONS,
        "selected": payload.get("selected") or [],
        "results": payload.get("results") or [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Arama kapsam raporunu JSON + HTML olarak üretir."
    )
    parser.add_argument("input", type=Path, help="Arama cevabı veya coverage JSON dosyası")
    parser.add_argument(
        "-o", "--output-dir", type=Path,
        help="Çıktı klasörü (varsayılan: girdinin klasörü)",
    )
    parser.add_argument("--check", action="store_true", help="Yalnızca doğrula; dosya yazma")
    parser.add_argument("--force", action="store_true", help="Var olan çıktının üzerine yaz")
    parser.add_argument(
        "--markdown",
        dest="markdown",
        action="store_true",
        default=True,
        help="Markdown çıktısı da yaz (varsayılan: açık).",
    )
    parser.add_argument(
        "--no-markdown",
        dest="markdown",
        action="store_false",
        help="Markdown çıktısı yazma.",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        help="İkinci bir arama cevabı/coverage JSON'u; iki taramanın kapsam farkını da yaz.",
    )
    parser.add_argument(
        "--compare-label",
        default="B",
        help="--compare dosyası için etiket (varsayılan: B).",
    )
    parser.add_argument(
        "--auto-report",
        action="store_true",
        help="Rapor yazıldıktan sonra kapsam özetini stdout'a bas.",
    )
    parser.add_argument(
        "--fulltext-list",
        type=Path,
        help=(
            "Seçilen makaleleri rapora eklemek için fulltext listesi JSON'u. "
            "Gerekçe ve fulltext HTML'e aktarım durumu tabloya yazılır."
        ),
    )
    parser.add_argument(
        "--no-timestamp",
        dest="timestamp",
        action="store_false",
        help="Sabit dosya adı kullan (varsayılan: zaman soneki).",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Hata: girdi bulunamadı: {args.input}", file=sys.stderr)
        return 2
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Hata: JSON çözümlenemedi: {exc}", file=sys.stderr)
        return 2

    errors = validate(data)
    if errors:
        print("Girdi doğrulama hataları:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    if args.check:
        print(f"OK: {args.input} geçerli arama kapsam raporu.")
        return 0

    if args.fulltext_list:
        if not args.fulltext_list.is_file():
            print(
                f"Hata: fulltext listesi bulunamadı: {args.fulltext_list}",
                file=sys.stderr,
            )
            return 2
        fulltext_dir = (args.fulltext_list.parent / "fulltext").expanduser()
        try:
            selected = load_selected(args.fulltext_list, [fulltext_dir])
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Hata: fulltext listesi çözümlenemedi: {exc}", file=sys.stderr)
            return 2
        data = dict(data)
        data["selected"] = selected
        data["selected_source"] = args.fulltext_list.name
        print(f"Seçilen makale: {len(selected)} ({args.fulltext_list.name})")

    report = build_report(data)
    try:
        html_text = render(data)
        markdown_text = render_markdown(data) if args.markdown else None
    except ValueError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    output_dir = (args.output_dir or args.input.parent).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    moment = datetime.now().astimezone()
    stem = f"{OUTPUT_STEM}_{timestamp_suffix(moment)}" if args.timestamp else OUTPUT_STEM
    suffixes = [".json", ".html"]
    if args.markdown:
        suffixes.append(".md")
    if args.compare:
        suffixes.extend(["_karsilastirma.json", "_karsilastirma.html"])
    if not args.force:
        stem = _unique_stem(output_dir, stem, suffixes)
    json_path = output_dir / f"{stem}.json"
    html_path = output_dir / f"{stem}.html"
    markdown_path = output_dir / f"{stem}.md"
    comparison_json_path = output_dir / f"{stem}_karsilastirma.json"
    comparison_html_path = output_dir / f"{stem}_karsilastirma.html"
    planned = [json_path, html_path]
    if markdown_text is not None:
        planned.append(markdown_path)
    if args.compare:
        planned.extend([comparison_json_path, comparison_html_path])
    if not args.force:
        for path in planned:
            if path.exists():
                print(
                    f"Hata: çıktı zaten var: {path}\n"
                    "Üzerine yazmak için --force kullanın.",
                    file=sys.stderr,
                )
                return 2

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    html_path.write_text(html_text, encoding="utf-8")
    print(f"Yazıldı: {json_path}")
    print(f"Yazıldı: {html_path}")
    if markdown_text is not None:
        markdown_path.write_text(markdown_text, encoding="utf-8")
        print(f"Yazıldı: {markdown_path}")

    if args.compare:
        if not args.compare.is_file():
            print(f"Hata: karşılaştırma dosyası bulunamadı: {args.compare}", file=sys.stderr)
            return 2
        try:
            other = json.loads(args.compare.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Hata: karşılaştırma JSON çözümlenemedi: {exc}", file=sys.stderr)
            return 2
        other_errors = validate(other)
        if other_errors:
            print("Karşılaştırma dosyası doğrulama hataları:", file=sys.stderr)
            for error in other_errors:
                print(f"  - {error}", file=sys.stderr)
            return 1
        comparison = compare_coverage(
            data,
            other,
            left_label=payload_label(data),
            right_label=args.compare_label,
        )
        comparison_json_path.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        comparison_html_path.write_text(render_comparison(comparison), encoding="utf-8")
        print(f"Yazıldı: {comparison_json_path}")
        print(f"Yazıldı: {comparison_html_path}")
        print(
            "Kapsam farkı: "
            f"tekil DOI {comparison['delta_total_unique_dois']:+d}, "
            f"yüksek kalite {comparison['delta_high_quality_total']:+d}."
        )

    if args.auto_report:
        coverage = extract_payload(data)["coverage"]
        print(
            "Özet: "
            f"{len(coverage.get('sources_queried') or [])} kaynak, "
            f"{coverage.get('total_unique_dois', 0)} tekil DOI, "
            f"{coverage.get('high_quality_total', 0)} yüksek kalite, "
            f"evidence_scarcity={coverage.get('evidence_scarcity')}"
        )
    print("Not: önceki rapor dosyaları silinmedi; her çalıştırma yeni bir sürüm ekler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
