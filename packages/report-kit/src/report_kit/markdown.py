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


def _notice(value: Any) -> str:
    if isinstance(value, dict):
        title = _text(value.get("title")).strip()
        text = _text(value.get("text") or value.get("body")).strip()
        if title and not title.endswith((".", ":", "!", "?")):
            title += "."
        parts = [f"**{_inline(title)}**"] if title else []
        if text:
            parts.append(_inline(text))
        return "> " + " ".join(parts) if parts else ""
    text = _text(value).strip()
    return "> " + _inline(text) if text else ""


def _summary_strip(summary: Any) -> str:
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
        if text.isdigit():
            items.append(f"**{text}** {label}")
    return " · ".join(items)


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
                if segment.get("added_by_mcp"):
                    parts.append(f"**⟦MCP ekledi: {text}⟧**")
                elif segment.get("changed"):
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
        heading = f"### {_text(card.get('card_label') or 'Değişiklik')} {index}"
        if title:
            heading += f" — {title}"
        if location:
            heading += f" ({location})"
        out.append(heading)
        out.append("")
        if card.get("author_sentence"):
            author_label = _text(card.get("author_label") or "Yazarın yazdığı")
            out.extend([f"**{_inline(author_label)}:** {_quote(card['author_sentence'])}", ""])
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
            rewritten_label = _text(card.get("rewritten_label") or "Yeniden yazılan cümle")
            segments = card.get("rewritten_segments") or []
            segment_text = "".join(
                str(segment.get("text", ""))
                for segment in segments
                if isinstance(segment, dict)
            )
            if segments and segment_text == str(card["rewritten_sentence"]):
                rewritten = "".join(
                    f"⟦MCP ekledi: {_inline(segment.get('text', ''))}⟧"
                    if segment.get("added_by_mcp")
                    else _inline(segment.get("text", ""))
                    for segment in segments
                    if isinstance(segment, dict)
                )
                rewritten_quote = _quote(rewritten)
            else:
                rewritten_quote = _quote(card["rewritten_sentence"])
            out.extend(
                [
                    f"**{_inline(rewritten_label)}:** **{rewritten_quote}**",
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


def _context_review(review: dict[str, Any], headings: dict[str, str]) -> str:
    out = [f"## {review.get('heading') or headings['context_assessment']}", ""]
    out.extend([f"**İncelenen kapsam:** {_inline(review.get('scope', ''))}", ""])
    out.extend([f"**Genel değerlendirme:** {_inline(review.get('overall', ''))}", ""])
    for index, item in enumerate(review.get("paragraphs") or [], 1):
        if not isinstance(item, dict):
            continue
        out.extend([f"### {_inline(item.get('location') or f'Paragraf {index}')}", ""])
        if item.get("paragraph_excerpt"):
            out.extend([f"> {_quote(item['paragraph_excerpt'])}", ""])
        for key, label in (
            ("paragraph_function", "Paragrafın işlevi"),
            ("sentence_fit", "Cümlenin paragrafa uyumu"),
            ("flow_fit", "Cümleler arası akış"),
            ("article_fit", "Makale/bölüm bağlamına uyum"),
            ("recommended_action", "Bağlam için öneri"),
        ):
            if item.get(key):
                out.extend([f"**{label}:** {_inline(item[key])}", ""])
    return "\n".join(out)


def _source_recommendations(
    items: list[dict[str, Any]], note: str | None, headings: dict[str, str]
) -> str:
    out = [f"## {headings['appendix_3']}", ""]
    out.extend([
        "_Bunlar bağlama göre önerilen aday kaynaklardır. Ek 2'de sayfa doğrulamalı kanıt olarak değerlendirilmedikçe taslağı desteklediği kabul edilmez._",
        "",
    ])
    if not items:
        out.extend([_inline(note or "Bu bağlam için doğrulanmış kaynak önerisi bulunamadı."), ""])
        return "\n".join(out)
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        title = _inline(item.get("title") or item.get("citation") or f"Öneri {index}")
        doi = _text(item.get("doi")).strip()
        if is_doi(doi):
            title = f"[{title}]({doi_url(doi)})"
        out.extend([f"### {index}. {title}", ""])
        details = " · ".join(
            part for part in (
                _inline(item.get("authors") or ""),
                f"{_inline(item.get('journal'))} ({_inline(item.get('year'))})"
                if item.get("journal") and item.get("year")
                else _inline(item.get("journal") or item.get("year") or ""),
            ) if part
        )
        if details:
            out.extend([details, ""])
        out.extend([f"**İlgili konum:** {_inline(item.get('related_location', ''))}", ""])
        if item.get("fit_dimensions"):
            out.extend([f"**Bağlam eşleşmesi:** {_inline(', '.join(item['fit_dimensions']))}", ""])
        out.extend([f"**Neden daha uygun olabilir:** {_inline(item.get('fit_reason', ''))}", ""])
        status = "Tam metni incelendi" if item.get("fulltext_reviewed") else "Aday kaynak; tam metin incelenmedi ve kanıt değildir"
        out.extend([f"_{status}_", ""])
    return "\n".join(out)


def _source_contributions(items: list[dict[str, Any]], headings: dict[str, str]) -> str:
    out = [f"## {headings['appendix_4']}", ""]
    out.extend([
        "_Her kaynağın bu çalışmadaki olası katkısı ve sınırları ayrı değerlendirilir. "
        "Özet veya metaveriye dayalı değerlendirme, PDF sayfası doğrulanmış kanıt yerine geçmez._",
        "",
    ])
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        title = _inline(item.get("citation") or item.get("title") or f"Kaynak {index}")
        doi = _text(item.get("doi")).strip()
        if is_doi(doi):
            title = f"[{title}]({doi_url(doi)})"
        out.extend([f"### {index}. {title}", ""])
        if item.get("project_relevance"):
            out.extend([f"**Bu çalışmadaki rolü:** {_inline(item['project_relevance'])}", ""])
        for key, label in (
            ("supports", "Neyi destekliyor"),
            ("does_not_support", "Neyi desteklemiyor / göstermiyor"),
            ("limits", "Sınırlar ve dikkat noktaları"),
        ):
            values = item.get(key) or []
            if values:
                out.append(f"**{label}:**")
                out.extend(f"- {_inline(value)}" for value in values)
                out.append("")
        basis_key = _text(item.get("assessment_basis") or "metadata")
        basis = {
            "metadata": "Bibliyografik metaveri",
            "abstract": "Özet",
            "fulltext": "Tam metin",
            "fulltext_pages": "Sayfa numarası doğrulanmış tam metin",
        }.get(basis_key, basis_key)
        if item.get("pages"):
            basis += f" · incelenen sayfa(lar): {_text(item['pages'])}"
        if basis_key not in {"fulltext", "fulltext_pages"}:
            basis += " · ön değerlendirme; tam metin kanıtı değildir"
        out.extend([f"**Değerlendirme dayanağı:** {_inline(basis)}", ""])
    return "\n".join(out)


def _source_table(items: list[dict[str, Any]]) -> str:
    out = [
        "| # | Kaynak | DOI | Dergi (yıl) | Q (2024) | Atıf (Crossref/OpenAlex) | OA | Retraction | Rol | Sınırlılık |",
        "|---:|---|---|---|---|---|---|---|---|---|",
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
            "| {no} | {citation} | {doi} | {journal_year} | {q} | {citations} | {oa} | {retraction} | {role} | {limitation} |".format(
                no=_cell(item.get("no", "")),
                citation=_cell(item.get("citation", "")),
                doi=doi_cell,
                journal_year=_cell(journal_year),
                q=_cell(item.get("quartile") or "-"),
                citations=_cell(citations),
                oa=_cell(oa_text),
                retraction=_cell(item.get("retraction") or "yok"),
                role=_cell(item.get("role") or "-"),
                limitation=_cell(item.get("limitation") or "-"),
            )
        )
    return "\n".join(out)


def _claim_table(items: list[dict[str, Any]]) -> str:
    out = [
        "| # | Konum | İddia (özet) | Atıf(lar) | Kanıt türü | Destek | Kanıt / gerekçe (PDF sayfası) | Not |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in items:
        if not isinstance(item, dict):
            continue
        citations = item.get("citations")
        if isinstance(citations, (list, tuple)):
            citations = ", ".join(str(v) for v in citations)
        out.append(
            "| {cid} | {location} | {claim} | {citations} | {evidence_type} | {status} | {evidence} | {note} |".format(
                cid=_cell(item.get("claim_id", "")),
                location=_cell(item.get("location") or "-"),
                claim=_cell(item.get("claim", "")),
                citations=_cell(citations if citations not in (None, "") else "-"),
                evidence_type=_cell(item.get("evidence_type") or "-"),
                status=_cell(_status(item.get("status"))),
                evidence=_cell(item.get("evidence", "")),
                note=_cell(item.get("note") or "-"),
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
        or "Kırmızı: yeniden düzenlenen ifade · Mavi/yeşil: MCP'nin eklediği anlamlı ifade"
    )
    meta = f"{meta_prefix} — **{project}** · {meta_note}"
    if data.get("generated_at"):
        meta += f" · Tarih: {_text(data['generated_at'])}"

    body: list[str] = [f"# {_inline(title)}", "", f"_{meta}_", ""]
    summary = _summary_strip(data.get("summary"))
    if summary:
        body.extend([summary, ""])
    notice = _notice(data.get("notice"))
    if notice:
        body.extend([notice, ""])
    intro_data = data.get("intro") or {}
    intro_heading = intro_data.get("heading") if isinstance(intro_data, dict) else None
    if intro_heading and str(intro_heading).strip() and str(intro_heading).strip() != data.get("title"):
        body.extend([f"## {_inline(intro_heading)}", ""])
    intro = _intro(data)
    if intro:
        body.extend([intro, ""])

    context_review = data.get("context_review")
    if isinstance(context_review, dict):
        body.extend([_context_review(context_review, headings), ""])

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
        next_steps = data.get("next_steps") or []
        if next_steps:
            body.extend([f"### {headings['next_steps']}", ""])
            for index, item in enumerate(next_steps, 1):
                body.append(f"{index}. {_inline(item)}")
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

    if isinstance(data.get("source_recommendations"), list):
        body.extend([
            _source_recommendations(
                data["source_recommendations"],
                data.get("source_recommendations_note"),
                headings,
            ),
            "",
        ])

    if isinstance(data.get("source_contributions"), list):
        body.extend([_source_contributions(data["source_contributions"], headings), ""])

    if data.get("footer"):
        body.extend([f"_{_inline(data['footer'])}_", ""])
    return "\n".join(body).rstrip() + "\n"
