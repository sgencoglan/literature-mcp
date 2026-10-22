"""Markdown companion for the golden-standard chapter report.

The HTML report is the presentation layer; this Markdown file is the editable
text layer. It intentionally uses the same data and the same section order.
"""

from __future__ import annotations

from typing import Any

from .render import (
    DEFAULT_APPENDIX_INTRO,
    DEFAULT_HEADINGS,
    STATUS_LABELS,
    doi_url,
    is_doi,
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).replace("\r\n", "\n").replace("\r", "\n")


def _inline(value: Any) -> str:
    """Escape only Markdown link/table-sensitive characters.

    ``**bold**`` is preserved because report data uses it intentionally in
    correction notes and evidence cells.
    """
    text = _text(value)
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _cell(value: Any) -> str:
    return _inline(value).replace("|", "\\|").replace("\n", "<br>")


def _quote(value: Any) -> str:
    text = _text(value).strip()
    if text.startswith("“") and text.endswith("”"):
        return text
    return f"“{text}”"


def _status(value: Any) -> str:
    text = _text(value).strip()
    return STATUS_LABELS.get(text.lower(), text) if text else "-"


def _headings(data: dict[str, Any]) -> dict[str, str]:
    merged = dict(DEFAULT_HEADINGS)
    override = data.get("headings")
    if isinstance(override, dict):
        for key, value in override.items():
            if key in merged and value:
                merged[key] = str(value)
    return merged


def _intro(data: dict[str, Any]) -> str:
    intro = data.get("intro") or {}
    paragraphs = intro.get("paragraphs") or []
    out: list[str] = []
    for paragraph in paragraphs:
        if isinstance(paragraph, str):
            out.append(_inline(paragraph))
            continue
        if not isinstance(paragraph, dict):
            continue
        segments = paragraph.get("segments")
        if segments:
            parts: list[str] = []
            for segment in segments:
                if not isinstance(segment, dict):
                    parts.append(_inline(segment))
                    continue
                text = _inline(segment.get("text", ""))
                if segment.get("changed"):
                    leading = text[: len(text) - len(text.lstrip())]
                    trailing = text[len(text.rstrip()) :]
                    core = text.strip()
                    parts.append(f"{leading}**{core}**{trailing}" if core else text)
                else:
                    parts.append(text)
            out.append("".join(parts))
        else:
            out.append(_inline(paragraph.get("text", "")))
    return "\n\n".join(p for p in out if p)


def _change_cards(cards: list[dict[str, Any]], headings: dict[str, str]) -> str:
    out: list[str] = [f"## {headings['appendix_1']}", ""]
    appendix_intro = headings.get("_appendix_intro") or DEFAULT_APPENDIX_INTRO
    out.extend([_inline(appendix_intro), ""])
    for index, card in enumerate(cards, 1):
        if not isinstance(card, dict):
            continue
        title = _text(card.get("title")).strip()
        location = _text(card.get("location")).strip()
        heading = f"### Değişiklik {index}"
        if title:
            heading += f" — {title}"
        if location:
            heading += f" ({location})"
        out.append(heading)
        out.append("")
        if card.get("author_sentence"):
            out.extend([f"**Yazarın yazdığı:** {_quote(card['author_sentence'])}", ""])
        for source in card.get("sources") or []:
            if not isinstance(source, dict):
                continue
            citation = _text(source.get("citation"))
            page = _text(source.get("page"))
            label = f"Makaledeki orijinal cümle — {citation}"
            if page:
                label += f", s. {page}"
            label_md = _inline(label)
            doi = _text(source.get("doi")).strip()
            if is_doi(doi):
                label_md += f" · DOI: [{_text(doi)}]({doi_url(doi)})"
            out.append(f"> **{label_md}**")
            out.append(">")
            out.append(f"> {_quote(source.get('quote', ''))}")
            out.append("")
            out.extend([f"**Türkçesi:** {_quote(source.get('translation', ''))}", ""])
        if card.get("rewritten_sentence"):
            out.extend(
                [
                    f"**Yeniden yazılan cümle:** **{_quote(card['rewritten_sentence'])}**",
                    "",
                ]
            )
        for note in card.get("notes") or []:
            if not isinstance(note, dict):
                continue
            out.append(f"**{_inline(note.get('label') or 'Düzeltme notu')}**")
            out.append("")
            out.append(f"**Ne değişti:** {_inline(note.get('what', ''))}")
            out.append("")
            out.append(f"**Neden:** {_inline(note.get('why', ''))}")
            out.append("")
        out.extend(["---", ""])
    return "\n".join(out).rstrip() + "\n"


def _source_table(items: list[dict[str, Any]]) -> str:
    out = [
        "| # | Kaynak | DOI | Dergi (yıl) | Q (2024) | Atıf (Crossref/OpenAlex) | OA | Retraction |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for item in items:
        if not isinstance(item, dict):
            continue
        doi = _text(item.get("doi")).strip()
        doi_cell = f"[{_text(doi)}]({doi_url(doi)})" if is_doi(doi) else _text(doi)
        crossref = item.get("citations_crossref")
        openalex = item.get("citations_openalex")
        if item.get("citations") is not None:
            citations = _text(item.get("citations"))
        elif crossref is not None or openalex is not None:
            citations = f"{crossref if crossref is not None else '-'} / {openalex if openalex is not None else '-'}"
        else:
            citations = "-"
        oa = item.get("open_access")
        oa_text = "✓" if oa is True else "✗" if oa is False else _text(oa) if oa is not None else "-"
        journal = _text(item.get("journal"))
        year = _text(item.get("year"))
        journal_year = f"{journal} ({year})" if journal and year else (journal or year or "-")
        out.append(
            "| {no} | {citation} | {doi} | {journal_year} | {q} | {citations} | {oa} | {retraction} |".format(
                no=_cell(item.get("no", "")),
                citation=_cell(item.get("citation", "")),
                doi=doi_cell,
                journal_year=_cell(journal_year),
                q=_cell(item.get("quartile") or "-"),
                citations=_cell(citations),
                oa=_cell(oa_text),
                retraction=_cell(item.get("retraction") or "yok"),
            )
        )
    return "\n".join(out)


def _claim_table(items: list[dict[str, Any]]) -> str:
    out = [
        "| # | İddia (özet) | Atıf(lar) | Durum | Kanıt / gerekçe (PDF sayfası) |",
        "|---|---|---|---|---|",
    ]
    for item in items:
        if not isinstance(item, dict):
            continue
        citations = item.get("citations")
        if isinstance(citations, (list, tuple)):
            citations = ", ".join(str(v) for v in citations)
        out.append(
            "| {cid} | {claim} | {citations} | {status} | {evidence} |".format(
                cid=_cell(item.get("claim_id", "")),
                claim=_cell(item.get("claim", "")),
                citations=_cell(citations if citations not in (None, "") else "-"),
                status=_cell(_status(item.get("status"))),
                evidence=_cell(item.get("evidence", "")),
            )
        )
    return "\n".join(out)


def render_markdown(data: dict[str, Any]) -> str:
    headings = _headings(data)
    if data.get("appendix_intro"):
        headings["_appendix_intro"] = str(data["appendix_intro"])
    title = _text(data.get("title") or "Bölüm raporu")
    project = _text(data.get("project") or "proje")
    meta_prefix = _text(data.get("meta_prefix") or "Düzeltilmiş taslak")
    meta_note = _text(
        data.get("meta_note")
        or "Kırmızı zemin: önceki taslağa göre değiştirilen veya eklenen cümleler"
    )
    meta = f"{meta_prefix} — **{project}** · {meta_note}"
    if data.get("generated_at"):
        meta += f" · Tarih: {_text(data['generated_at'])}"

    body: list[str] = [f"# {_inline(title)}", "", f"_{meta}_", ""]
    intro = _intro(data)
    if intro:
        body.extend([intro, ""])

    cards = data.get("change_cards") or []
    if cards:
        body.extend([_change_cards(cards, headings), ""])

    sources = data.get("source_audit") or []
    claims = data.get("claim_matrix") or []
    if sources or claims:
        body.extend([f"## {headings['appendix_2']}", ""])
        note = []
        if data.get("method"):
            note.append(_inline(data["method"]))
        if data.get("generated_at"):
            note.append(f"Tarih: {_text(data['generated_at'])}")
        note.append(f"Proje: {_text(project)}")
        body.extend(["_" + " · ".join(note) + "_", ""])

        if sources:
            body.extend([f"### {headings['source_inventory']}", "", _source_table(sources), ""])
            if data.get("source_note"):
                body.extend([f"_{_inline(data['source_note'])}_", ""])
        if claims:
            body.extend([f"### {headings['claim_matrix']}", "", _claim_table(claims), ""])
            body.extend(
                [
                    "_Durum işaretleri: ✅ destekliyor · 🟡 kısmi/nüanslı · 🔴 atıf–iddia uyumsuz · ➖ kapsam dışı (amaç beyanı)_",
                    "",
                ]
            )
        corrections = data.get("correction_summary") or []
        if corrections:
            body.extend([f"### {headings['corrections']}", ""])
            for index, item in enumerate(corrections, 1):
                body.append(f"{index}. {_inline(item)}")
            body.append("")
        limitations = data.get("limitations") or []
        if limitations:
            body.extend([f"### {headings['limitations']}", ""])
            for item in limitations:
                body.append(f"- {_inline(item)}")
            body.append("")
        references = data.get("references") or []
        if references:
            body.extend([f"### {headings['references']}", ""])
            for index, ref in enumerate(references, 1):
                if not isinstance(ref, dict):
                    continue
                authors = _text(ref.get("authors"))
                year = _text(ref.get("year"))
                title_ref = _text(ref.get("title"))
                journal = _text(ref.get("journal"))
                doi = _text(ref.get("doi")).strip()
                line = f"{index}. {authors} ({year}). *{title_ref}*."
                if journal:
                    line += f" {journal}."
                if is_doi(doi):
                    line += f" [{doi}]({doi_url(doi)})"
                body.append(line)
            body.append("")

    if data.get("footer"):
        body.extend([f"_{_inline(data['footer'])}_", ""])
    return "\n".join(body).rstrip() + "\n"
