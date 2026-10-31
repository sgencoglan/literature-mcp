"""HTML renderer for the golden-standard chapter report.

All report content is escaped. The only intentionally generated markup is the
template itself and the small, controlled ``**bold**`` emphasis used in notes
and evidence cells.
"""

from __future__ import annotations

import html
import re
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)

DEFAULT_HEADINGS = {
    "appendix_1": "Ek 1 — Değişikliklerin Kaynak Cümleleriyle Karşılaştırması",
    "appendix_2": "Ek 2 — Kaynak Denetimi ve İddia–Kanıt Matrisi",
    "source_inventory": "1) Kaynak Envanteri",
    "claim_matrix": "2) İddia–Kanıt Matrisi",
    "corrections": "3) Düzeltme Önerileri (özet)",
    "limitations": "4) Notlar ve Sınırlılıklar",
    "next_steps": "5) Sonraki Adımlar",
    "references": "Kaynakça",
}

DEFAULT_APPENDIX_INTRO = (
    "Kırmızı ile işaretlenen her değişiklik için sırasıyla: yazarın taslakta "
    "yazdığı cümle, makaledeki orijinal cümle, bu cümlenin Türkçesi, yeniden "
    "yazılan cümle ve ilgili cümlenin düzeltme notu (ne değişti, neden) "
    "verilmiştir. İngilizce alıntılar kaynaklardan birebir alınmış; Türkçe "
    "çevirileri bu belge için yapılmıştır. Sayfa numaraları kaynak PDF’lerine "
    "göredir."
)

STATUS_LABELS = {
    "supported": "✅ Destekli",
    "full": "✅ Destekli",
    "partial": "🟡 Kısmi",
    "partially_supported": "🟡 Kısmi",
    "contradicted": "🔴 Çelişkili",
    "contradicts": "🔴 Çelişkili",
    "not_found": "🔴 Kaynakta yok",
    "none": "🔴 Kaynakta yok",
    "out_of_scope": "➖ Kapsam dışı",
    "scope": "➖ Kapsam dışı",
    "interpretation": "🟡 Yorum",
}

STATUS_CLASSES = {
    "supported": "ok",
    "full": "ok",
    "partial": "warn",
    "partially_supported": "warn",
    "interpretation": "warn",
    "contradicted": "bad",
    "contradicts": "bad",
    "not_found": "bad",
    "none": "bad",
    "out_of_scope": "muted",
    "scope": "muted",
}


def escape(value: Any) -> str:
    """Escape text for HTML text nodes."""
    return html.escape("" if value is None else str(value), quote=False)


def escape_attr(value: Any) -> str:
    """Escape text for HTML attributes."""
    return html.escape("" if value is None else str(value), quote=True)


def is_doi(value: Any) -> bool:
    return bool(DOI_RE.match(str(value or "").strip()))


def doi_url(doi: Any) -> str:
    return f"https://doi.org/{str(doi).strip()}"


def doi_link(doi: Any, label: Any = None) -> str:
    """Return a doi.org link, or escaped text when the DOI is invalid.

    Invalid DOIs never become arbitrary links; callers still get a readable
    value and the quality gate reports the invalid DOI separately.
    """
    raw = str(doi or "").strip()
    text = str(label if label is not None else raw)
    if not is_doi(raw):
        return escape(text)
    return f'<a href="{escape_attr(doi_url(raw))}">{escape(text)}</a>'


def rich(value: Any) -> str:
    """Escape then apply the report's only inline markup: ``**bold**``."""
    text = escape(value)
    text = BOLD_RE.sub(r"<b>\1</b>", text)
    return text.replace("\n", "<br>")


def quote(value: Any) -> str:
    """Render a quotation with Turkish quotation marks, without double quoting."""
    text = escape(value).strip()
    if not text:
        return "“”"
    if text.startswith("“") and text.endswith("”"):
        return text
    return f"“{text}”"


def _format_citations(value: Any) -> str:
    if isinstance(value, dict):
        crossref = value.get("crossref")
        openalex = value.get("openalex")
        if crossref is None and openalex is None:
            return "-"
        return f"{crossref if crossref is not None else '-'} / {openalex if openalex is not None else '-'}"
    if isinstance(value, (list, tuple)):
        return escape(", ".join(str(v) for v in value))
    return escape(value if value not in (None, "") else "-")


def _format_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if value is None:
        return "-"
    text = str(value).strip().lower()
    if text in {"true", "evet", "yes", "1"}:
        return "✓"
    if text in {"false", "hayır", "hayir", "no", "0"}:
        return "✗"
    return escape(value)


def _status(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    label = STATUS_LABELS.get(text.lower())
    if label:
        return label
    return escape(text)


def _status_class(value: Any) -> str:
    return STATUS_CLASSES.get(str(value or "").strip().lower(), "muted")


def _headings(data: dict[str, Any]) -> dict[str, str]:
    merged = dict(DEFAULT_HEADINGS)
    override = data.get("headings")
    if isinstance(override, dict):
        for key, value in override.items():
            if key in merged and value:
                merged[key] = str(value)
    return merged


def render_notice(notice: Any) -> str:
    """Render the optional source-policy / method notice box."""
    if notice is None or notice == "":
        return ""
    if isinstance(notice, dict):
        title = str(notice.get("title") or "").strip()
        text = notice.get("text")
        if text in (None, ""):
            text = notice.get("body", "")
        parts: list[str] = []
        if title:
            title_html = escape(title)
            if not title_html.endswith((".", ":", "!", "?")):
                title_html += "."
            parts.append(f"<strong>{title_html}</strong>")
        body = rich(text).strip()
        if body:
            parts.append(body)
        if not parts:
            return ""
        return f'<div class="notice">{" ".join(parts)}</div>'
    if isinstance(notice, str):
        text = rich(notice).strip()
        return f'<div class="notice">{text}</div>' if text else ""
    return ""


def render_summary_strip(summary: Any) -> str:
    """Render report counts as compact pills, b1-style."""
    if not isinstance(summary, dict):
        return ""
    labels = [
        ("change_cards", "değişiklik kartı"),
        ("sources", "kaynak"),
        ("claims", "iddia"),
        ("not_found", "kanıtlanamayan iddia"),
    ]
    items: list[str] = []
    for key, label in labels:
        value = summary.get(key)
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if not text.isdigit():
            continue
        items.append(f"<span><b>{escape(text)}</b> {escape(label)}</span>")
    if not items:
        return ""
    return '<p class="summary-strip">' + "".join(items) + "</p>"


def render_intro(intro: dict[str, Any]) -> str:
    paragraphs = intro.get("paragraphs") or []
    out: list[str] = []
    for paragraph in paragraphs:
        if isinstance(paragraph, str):
            out.append(f"<p>{rich(paragraph)}</p>")
            continue
        if not isinstance(paragraph, dict):
            continue
        segments = paragraph.get("segments")
        if segments:
            parts: list[str] = []
            for segment in segments:
                if not isinstance(segment, dict):
                    parts.append(rich(segment).strip())
                    continue
                text = rich(segment.get("text", "")).strip()
                if not text:
                    continue
                if segment.get("changed"):
                    parts.append(f"<mark>{text}</mark>")
                else:
                    parts.append(text)
            out.append("<p>\n  " + "\n  ".join(parts) + "\n</p>")
        else:
            out.append(f"<p>{rich(paragraph.get('text', ''))}</p>")
    return "\n".join(out)


def render_change_cards(cards: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for index, card in enumerate(cards, 1):
        if not isinstance(card, dict):
            continue
        title = str(card.get("title") or card.get("id") or "").strip()
        location = str(card.get("location") or "").strip()
        heading = f"{escape(card.get('card_label') or 'Değişiklik')} {index}"
        if title:
            heading += f" — {escape(title)}"
        if location:
            heading += f" ({escape(location)})"
        status = card.get("evidence_status")
        badge = ""
        if status:
            badge = (
                f' <span class="badge {_status_class(status)}">'
                f"{escape(_status(status))}</span>"
            )
        out.append(f'<article class="card" id="degisiklik-{index}">')
        out.append(f"  <h3>{heading}{badge}</h3>")

        author_sentence = card.get("author_sentence")
        if author_sentence:
            author_label = escape(card.get("author_label") or "Yazarın yazdığı")
            out.append(
                f'  <div class="row"><span class="lbl">{author_label}</span>'
                f"<p>{quote(author_sentence)}</p></div>"
            )

        for source in card.get("sources") or []:
            if not isinstance(source, dict):
                continue
            citation = escape(source.get("citation", ""))
            page = escape(source.get("page", ""))
            label = f"Makaledeki orijinal cümle — {citation}"
            if page:
                label += f", s. {page}"
            if source.get("doi"):
                label += f" · DOI: {doi_link(source['doi'])}"
            lang = str(source.get("quote_language") or "en")
            out.append('  <div class="ev">')
            out.append(f'    <div class="ev-head">{label}</div>')
            out.append(
                f'    <p class="en" lang="{escape_attr(lang)}">'
                f'{quote(source.get("quote", ""))}</p>'
            )
            out.append(
                '    <p class="tr"><span class="lbl">Türkçesi</span>'
                f'{quote(source.get("translation", ""))}</p>'
            )
            out.append("  </div>")

        rewritten = card.get("rewritten_sentence")
        if rewritten:
            rewritten_label = escape(card.get("rewritten_label") or "Yeniden yazılan cümle")
            out.append(
                f'  <div class="row"><span class="lbl">{rewritten_label}</span>'
                f'<p class="rewritten"><mark>{quote(rewritten)}</mark></p></div>'
            )

        notes = [note for note in (card.get("notes") or []) if isinstance(note, dict)]
        if notes:
            out.append('  <div class="notes">')
            notes_heading = card.get("notes_heading")
            if not notes_heading:
                notes_heading = "Düzeltme notları" if len(notes) > 1 else "Düzeltme notu"
            out.append(
                f"    <h4>{escape(notes_heading)}</h4>"
            )
            out.append("    <ol>")
            for note in notes:
                label = escape(note.get("label") or "Düzeltme notu")
                if not label.endswith((".", ":", "!", "?")):
                    label += ":"
                what = rich(note.get("what", ""))
                why = rich(note.get("why", ""))
                out.append(
                    f'      <li><strong>{label}</strong> '
                    f"<b>Ne değişti:</b> {what}<br><b>Neden:</b> {why}</li>"
                )
            out.append("    </ol>")
            out.append("  </div>")

        out.append("</article>")
    return "\n".join(out)


def render_source_table(source_audit: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in source_audit:
        if not isinstance(item, dict):
            continue
        number = escape(item.get("no", ""))
        citation = escape(item.get("citation", ""))
        doi = doi_link(item.get("doi", ""))
        journal = escape(item.get("journal", ""))
        year = escape(item.get("year", ""))
        journal_year = f"{journal} ({year})" if journal and year else (journal or year or "-")
        quartile = escape(item.get("quartile") or "-")
        citations = _format_citations(
            item.get("citations")
            if item.get("citations") is not None
            else {
                "crossref": item.get("citations_crossref"),
                "openalex": item.get("citations_openalex"),
            }
        )
        open_access = _format_bool(item.get("open_access"))
        retraction = escape(item.get("retraction") or "yok")
        role = escape(item.get("role") or "-")
        limitation = escape(item.get("limitation") or "-")
        rows.append(
            "<tr>"
            f"<td>{number}</td><td>{citation}</td><td>{doi}</td>"
            f"<td>{journal_year}</td><td>{quartile}</td><td>{citations}</td>"
            f"<td>{open_access}</td><td>{retraction}</td>"
            f"<td>{role}</td><td>{limitation}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_claim_table(claims: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in claims:
        if not isinstance(item, dict):
            continue
        claim_id = escape(item.get("claim_id", ""))
        location = escape(item.get("location") or "-")
        claim = rich(item.get("claim", ""))
        citations = _format_citations(item.get("citations"))
        evidence_type = escape(item.get("evidence_type") or "-")
        status = _status(item.get("status"))
        status_html = f'<span class="status {_status_class(item.get("status"))}">{escape(status)}</span>'
        evidence = rich(item.get("evidence", ""))
        note = rich(item.get("note") or "-")
        rows.append(
            "<tr>"
            f"<td>{claim_id}</td><td>{location}</td><td>{claim}</td>"
            f"<td>{citations}</td><td>{evidence_type}</td><td>{status_html}</td>"
            f"<td>{evidence}</td><td>{note}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_list(items: list[Any], ordered: bool = False) -> str:
    if not items:
        return ""
    tag = "ol" if ordered else "ul"
    body = "\n".join(f"  <li>{rich(item)}</li>" for item in items)
    return f"<{tag}>\n{body}\n</{tag}>"


def render_references(references: list[dict[str, Any]]) -> str:
    if not references:
        return ""
    rows: list[str] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        authors = escape(ref.get("authors", ""))
        year = escape(ref.get("year", ""))
        title = escape(ref.get("title", ""))
        journal = escape(ref.get("journal", ""))
        doi = doi_link(ref.get("doi", ""))
        parts = [f"{authors} ({year}).", f"<i>{title}</i>."]
        if journal:
            parts.append(f"{journal}.")
        if doi:
            parts.append(doi)
        rows.append("  <li>" + " ".join(p for p in parts if p) + "</li>")
    return "<ol>\n" + "\n".join(rows) + "\n</ol>"


def render_report(data: dict[str, Any]) -> str:
    """Render a complete, self-contained HTML report."""
    title = escape(data.get("title", "Bölüm raporu"))
    project = escape(data.get("project", "proje"))
    headings = _headings(data)

    meta_parts: list[str] = []
    meta_prefix = escape(data.get("meta_prefix") or "Düzeltilmiş taslak")
    meta_parts.append(f"{meta_prefix} — <strong>{project}</strong>")
    meta_note = escape(
        data.get("meta_note")
        or "Kırmızı zemin: önceki taslağa göre değiştirilen veya eklenen cümleler"
    )
    meta_parts.append(meta_note)
    if data.get("generated_at"):
        meta_parts.append(f"Tarih: {escape(data['generated_at'])}")
    meta_html = " · ".join(meta_parts)

    body: list[str] = [f"<h1>{title}</h1>", f'<p class="meta">{meta_html}</p>']

    summary_html = render_summary_strip(data.get("summary"))
    if summary_html:
        body.append(summary_html)

    notice_html = render_notice(data.get("notice"))
    if notice_html:
        body.append(notice_html)

    intro = data.get("intro")
    if isinstance(intro, dict):
        body.append('<section id="metin">')
        intro_heading = intro.get("heading")
        if intro_heading and str(intro_heading).strip() and str(intro_heading).strip() != data.get("title"):
            body.append(f"<h2>{escape(intro_heading)}</h2>")
        body.append(render_intro(intro))
        body.append("</section>")

    cards = data.get("change_cards") or []
    if cards:
        body.append('<section class="appendix appendix-cards">')
        body.append(f"  <h2>{escape(headings['appendix_1'])}</h2>")
        appendix_intro = data.get("appendix_intro") or DEFAULT_APPENDIX_INTRO
        body.append(f'  <p class="legend">{rich(appendix_intro)}</p>')
        body.append(render_change_cards(cards))
        body.append("</section>")

    source_audit = data.get("source_audit") or []
    claims = data.get("claim_matrix") or []
    if source_audit or claims:
        body.append('<section class="appendix appendix-matrix">')
        body.append(f"  <h2>{escape(headings['appendix_2'])}</h2>")
        note_parts: list[str] = []
        if data.get("method"):
            note_parts.append(rich(data["method"]))
        if data.get("generated_at"):
            note_parts.append(f"Tarih: {escape(data['generated_at'])}")
        note_parts.append(f"Proje: {project}")
        body.append(f'  <p class="legend">{" · ".join(note_parts)}</p>')

        if source_audit:
            body.append(f"  <h3>{escape(headings['source_inventory'])}</h3>")
            body.append('  <div class="table-wrap"><table>')
            body.append(
                "    <thead><tr>"
                "<th scope=\"col\">#</th><th scope=\"col\">Kaynak</th>"
                "<th scope=\"col\">DOI</th><th scope=\"col\">Dergi (yıl)</th>"
                "<th scope=\"col\">Q (2024)</th><th scope=\"col\">Atıf (Crossref/OpenAlex)</th>"
                "<th scope=\"col\">OA</th><th scope=\"col\">Retraction</th>"
                "<th scope=\"col\">Rol</th><th scope=\"col\">Sınırlılık</th>"
                "</tr></thead>"
            )
            body.append(f"    <tbody>\n{render_source_table(source_audit)}\n    </tbody>")
            body.append("  </table></div>")
            if data.get("source_note"):
                body.append(f'  <p class="legend">{rich(data["source_note"])}</p>')

        if claims:
            body.append(f"  <h3>{escape(headings['claim_matrix'])}</h3>")
            body.append('  <div class="table-wrap"><table>')
            body.append(
                "    <thead><tr>"
                "<th scope=\"col\">#</th><th scope=\"col\">Konum</th>"
                "<th scope=\"col\">İddia (özet)</th><th scope=\"col\">Atıf(lar)</th>"
                "<th scope=\"col\">Kanıt türü</th><th scope=\"col\">Destek</th>"
                "<th scope=\"col\">Kanıt / gerekçe (PDF sayfası)</th><th scope=\"col\">Not</th>"
                "</tr></thead>"
            )
            body.append(f"    <tbody>\n{render_claim_table(claims)}\n    </tbody>")
            body.append("  </table></div>")
            body.append(
                '  <p class="legend">Durum işaretleri: ✅ destekliyor · 🟡 kısmi/nüanslı · '
                "🔴 atıf–iddia uyumsuz · ➖ kapsam dışı (amaç beyanı)</p>"
            )

        corrections = data.get("correction_summary") or []
        if corrections:
            body.append(f"  <h3>{escape(headings['corrections'])}</h3>")
            body.append(render_list(corrections, ordered=True))

        limitations = data.get("limitations") or []
        if limitations:
            body.append(f"  <h3>{escape(headings['limitations'])}</h3>")
            body.append(render_list(limitations, ordered=False))

        next_steps = data.get("next_steps") or []
        if next_steps:
            body.append(f"  <h3>{escape(headings['next_steps'])}</h3>")
            body.append(render_list(next_steps, ordered=True))

        references = data.get("references") or []
        if references:
            body.append(f"  <h3>{escape(headings['references'])}</h3>")
            body.append(render_references(references))

        body.append("</section>")

    if data.get("footer"):
        body.append(f'<footer class="report-footer"><p>{rich(data["footer"])}</p></footer>')

    css = files("report_kit").joinpath("templates/chapter-report.css").read_text(encoding="utf-8")
    shell = files("report_kit").joinpath("templates/chapter-report.html").read_text(encoding="utf-8")
    return Template(shell).substitute(
        title=title,
        project=project,
        css=css,
        body="\n".join(body),
    )


def write_report(data: dict[str, Any], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(data), encoding="utf-8")
    return path
