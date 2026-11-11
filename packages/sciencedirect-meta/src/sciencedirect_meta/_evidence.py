"""Study comparison, lexical evidence check and review export."""


from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sciencedirect_meta import _common
from sciencedirect_meta._common import (
    _authors_short,
    _error,
    _escape_md,
    _iso_now,
    _safe_slug,
    _split_sentences,
    logger,
)
from sciencedirect_meta._crossref import _metadata_for
from sciencedirect_meta._library import _extract_pdf_pages, _match_local_pdf
from sciencedirect_meta._projects import _project_config, _project_scope
from sciencedirect_meta._search import search_literature
from sciencedirect_meta.server import (
    normalize_doi,
)

_DESIGN_PATTERNS = [
    (r"\bsystematic review\b", "Systematic review"),
    (r"\bmeta-analys[ie]s\b", "Meta-analysis"),
    (r"\brandomi[sz]ed controlled trial\b|\bRCT\b", "Randomized controlled trial"),
    (r"\bcluster[- ]randomi[sz]ed\b", "Cluster-randomized trial"),
    (r"\bquasi[- ]experimental\b", "Quasi-experimental study"),
    (r"\bcohort\b", "Cohort study"),
    (r"\blongitudinal\b", "Longitudinal study"),
    (r"\bcross[- ]sectional\b", "Cross-sectional study"),
    (r"\bcase[- ]control\b", "Case-control study"),
    (r"\bmixed[- ]methods\b", "Mixed-methods study"),
    (r"\bqualitative\b", "Qualitative study"),
    (r"\bsurvey\b", "Survey"),
]


_RESULT_KEYWORDS = [
    "result", "finding", "showed", "found", "associated", "significant",
    "effect", "improved", "increased", "decreased", "higher", "lower",
]


_LIMITATION_KEYWORDS = [
    "limitation", "limited", "generaliz", "caution", "bias", "small sample",
    "cannot", "cross-sectional", "self-report",
]


def _extract_design(text: str) -> str:
    found: List[str] = []
    for pattern, label in _DESIGN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE) and label not in found:
            found.append(label)
    return "; ".join(found) if found else "Not extracted"


def _extract_sample(text: str) -> str:
    patterns = [
        r"(?:N|n)\s*=\s*[\d,]+",
        r"[\d,]+\s+(?:participants|students|teachers|adolescents|children|patients|respondents|caregivers|parents)",
        r"sample of\s+[\d,]+",
        r"[\d,]+\s+(?:high school|middle school|primary school|university|college)\s+students",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            sentence = next(
                (s for s in _split_sentences(text) if match.group(0).lower() in s.lower()),
                match.group(0),
            )
            return sentence[:500]
    return "Not extracted"


def _best_sentences(text: str, keywords: Sequence[str], max_n: int = 2) -> List[str]:
    sentences = _split_sentences(text)
    scored: List[Tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        low = sentence.lower()
        score = sum(1 for keyword in keywords if keyword in low)
        if score:
            scored.append((score, -index, sentence))
    scored.sort(reverse=True)
    selected: List[str] = []
    for _, _, sentence in scored:
        if sentence not in selected:
            selected.append(sentence[:700])
        if len(selected) >= max_n:
            break
    return selected


async def _study_text(
    study: Dict[str, Any],
    directory: Optional[Path] = None,
    recurse: bool = True,
) -> Tuple[str, str, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (text, source, pages, local_match)."""
    doi = study.get("doi") or ""
    title = study.get("title") or ""
    match = _match_local_pdf(doi, title, directory, recurse)
    if match:
        try:
            _, pages = _extract_pdf_pages(Path(match["path"]), max_pages=_common.PDF_MAX_PAGES)
            text = "\n\n".join(page["text"] for page in pages if page["text"])
            if text.strip():
                return text, "local_pdf", pages, match
        except Exception as exc:  # noqa: BLE001
            logger.info("Local PDF read failed for %s: %s", doi, exc)
    abstract = study.get("abstract") or ""
    pages = [{"page": None, "text": abstract}] if abstract else []
    return abstract, "abstract", pages, None


def _compare_one(study: Dict[str, Any], text: str, text_source: str, match: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "doi": study.get("doi"),
        "pmid": study.get("pmid"),
        "title": study.get("title"),
        "authors": study.get("authors"),
        "year": study.get("year"),
        "journal": study.get("journal"),
        "design": _extract_design(text),
        "sample": _extract_sample(text),
        "results": _best_sentences(text, _RESULT_KEYWORDS, max_n=2),
        "limitations": _best_sentences(text, _LIMITATION_KEYWORDS, max_n=2),
        "text_source": text_source,
        "local_pdf": match["path"] if match else None,
        "links": study.get("links"),
        "source": study.get("source"),
    }


async def compare_studies(
    identifiers: Optional[Sequence[str]] = None,
    query: Optional[str] = None,
    limit: int = 6,
    sources: Optional[Sequence[str]] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare studies; local full texts are looked up inside one project only.

    ``project`` scopes the PDF matching to that project's folder so studies
    from different projects are never mixed.
    """
    try:
        scope_dir, scope_recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    limit = max(1, min(limit, 12))
    studies: List[Dict[str, Any]] = []
    notes: List[str] = []

    if identifiers:
        for identifier in identifiers[:limit]:
            identifier = str(identifier).strip()
            if not identifier:
                continue
            id_type = "pmid" if identifier.isdigit() else "doi"
            item = await _metadata_for(identifier, id_type)
            if not item:
                item = {
                    "doi": normalize_doi(identifier) if id_type == "doi" else None,
                    "pmid": identifier if id_type == "pmid" else None,
                    "title": None,
                    "authors": [],
                    "year": None,
                    "journal": None,
                    "abstract": None,
                    "source": "local_library",
                }
                match = _match_local_pdf(
                    item.get("doi") or "", "", scope_dir, scope_recurse
                )
                if not match:
                    notes.append(f"Metadata and local PDF not found for {identifier}")
                    continue
                item["local_pdf"] = match["path"]
                item["title"] = match.get("title_guess")
                notes.append(f"Using local PDF only for {identifier}")
            studies.append(item)
    elif query:
        payload = await search_literature(
            query, sources=sources, limit=limit, project=project
        )
        studies = payload.get("results") or []
        notes.extend(payload.get("notes") or [])
    else:
        return _error("Provide identifiers or query")

    if not studies:
        return _error("No studies found", identifiers=list(identifiers or []), query=query)

    rows: List[Dict[str, Any]] = []
    notes.append(
        "Design/sample/results/limitations are extracted heuristically; verify against the PDF."
    )
    for study in studies[:limit]:
        text, text_source, _, match = await _study_text(study, scope_dir, scope_recurse)
        rows.append(_compare_one(study, text, text_source, match))

    header = "| Study | Design | Sample | Key findings | Limitations |"
    separator = "|---|---|---|---|---|"
    table_lines = [header, separator]
    for row in rows:
        study_label = f"{_authors_short(row.get('authors'))} ({row.get('year') or 'n.d.'})"
        results = " ".join(row.get("results") or []) or "Not extracted"
        limitations = " ".join(row.get("limitations") or []) or "Not extracted"
        table_lines.append(
            "| "
            + " | ".join(
                _escape_md(value)[:320]
                for value in (
                    study_label,
                    row.get("design"),
                    row.get("sample"),
                    results,
                    limitations,
                )
            )
            + " |"
        )

    return {
        "count": len(rows),
        "table_markdown": "\n".join(table_lines),
        "studies": rows,
        "notes": notes,
    }


_STOPWORDS = set(
    """
    a an the and or but if then than that this these those of to in on for with by from as at is are was were be been being
    it its their they we you he she his her our not no can could may might will would should do does did have has had
    this that there here also into about more most other such only own same so than too very just
    ve bir bu da de için ile olan olarak gibi daha çok az en veya ama fakat ancak ise her hem ya
    """.split()
)


def _tokens(text: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", (text or "").lower())
        if token not in _STOPWORDS and not token.isdigit()
    ]


def _vectorize_sentences(
    sentences: Sequence[str],
) -> Tuple[List[Dict[str, float]], Dict[str, float]]:
    tokenized = [_tokens(sentence) for sentence in sentences]
    document_frequency: Counter = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    total = max(1, len(sentences))
    idf = {
        term: math.log((1 + total) / (1 + frequency)) + 1.0
        for term, frequency in document_frequency.items()
    }
    vectors: List[Dict[str, float]] = []
    for tokens in tokenized:
        counts = Counter(tokens)
        if not counts:
            vectors.append({})
            continue
        length = sum(counts.values())
        vectors.append(
            {
                term: (count / length) * idf.get(term, 1.0)
                for term, count in counts.items()
            }
        )
    return vectors, idf


def _cosine(left: Dict[str, float], right: Dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[term] * right[term] for term in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _verdict(score: float, coverage: float) -> str:
    """Conservative lexical verdict; coverage penalises missing claim terms."""
    if score >= 0.40 and coverage >= 0.65:
        return "strong"
    if score >= 0.25 and coverage >= 0.45:
        return "moderate"
    if score >= 0.12 or coverage >= 0.25:
        return "weak"
    return "not_found"


async def evidence_check(
    claims: Sequence[str],
    identifier: Optional[str] = None,
    id_type: str = "doi",
    pdf_path: Optional[str] = None,
    text: Optional[str] = None,
    top_k: int = 3,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Score claims against one paper's sentences (lexical TF-IDF).

    ``project`` scopes the local PDF lookup to that project's folder and
    rejects explicit pdf_path values outside it, so evidence never comes from
    a different project by accident.
    """
    try:
        scope_dir, scope_recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    claims = [str(claim).strip() for claim in claims if str(claim).strip()]
    if not claims:
        return _error("At least one claim is required")

    paper: Dict[str, Any] = {}
    pages: List[Dict[str, Any]] = []
    text_source = "provided_text"

    if text:
        pages = [{"page": None, "text": text}]
    elif pdf_path:
        path = Path(pdf_path).expanduser().resolve()
        if not path.exists():
            return _error("PDF file not found", pdf_path=str(path))
        if scope_dir is not None:
            try:
                path.relative_to(scope_dir.resolve())
            except ValueError:
                return _error(
                    "Bu PDF seçilen projenin klasöründe değil",
                    project=project,
                    pdf_path=str(path),
                    project_dir=str(scope_dir),
                )
        try:
            _, pages = _extract_pdf_pages(path, max_pages=_common.PDF_MAX_PAGES)
        except Exception as exc:  # noqa: BLE001
            return _error("PDF parsing failed", detail=str(exc))
        text_source = "explicit_pdf"
    else:
        if not identifier:
            return _error("Provide text, identifier, or pdf_path")
        paper = await _metadata_for(identifier, id_type)
        study = paper if paper else {"doi": identifier if id_type == "doi" else None, "title": identifier if id_type == "title" else None}
        _, text_source, pages, match = await _study_text(study, scope_dir, scope_recurse)
        if match:
            paper["local_pdf"] = match["path"]

    sentences: List[Dict[str, Any]] = []
    for page in pages:
        for sentence in _split_sentences(page.get("text")):
            sentences.append({"text": sentence, "page": page.get("page")})
    if not sentences:
        return _error(
            "No extractable sentences found",
            identifier=identifier,
            local_pdf=paper.get("local_pdf"),
        )

    sentence_texts = [sentence["text"] for sentence in sentences]
    sentence_vectors, idf = _vectorize_sentences(sentence_texts)
    sentence_token_sets = [set(_tokens(text)) for text in sentence_texts]

    results: List[Dict[str, Any]] = []
    for claim in claims:
        claim_tokens = _tokens(claim)
        claim_token_set = set(claim_tokens)
        claim_counts = Counter(claim_tokens)
        if claim_counts:
            length = sum(claim_counts.values())
            claim_vector = {
                term: (count / length) * idf.get(term, 1.0)
                for term, count in claim_counts.items()
            }
        else:
            claim_vector = {}

        scored = []
        for index, vector in enumerate(sentence_vectors):
            cosine = _cosine(claim_vector, vector)
            coverage = (
                len(claim_token_set & sentence_token_sets[index]) / len(claim_token_set)
                if claim_token_set
                else 0.0
            )
            combined = 0.6 * cosine + 0.4 * coverage
            scored.append((index, cosine, coverage, combined))
        scored.sort(key=lambda row: row[3], reverse=True)
        top = [
            {
                "text": sentences[index]["text"],
                "page": sentences[index]["page"],
                "score": round(cosine, 4),
                "coverage": round(coverage, 4),
                "combined": round(combined, 4),
            }
            for index, cosine, coverage, combined in scored[: max(1, min(top_k, 10))]
            if combined > 0
        ]
        best = top[0]["combined"] if top else 0.0
        best_coverage = top[0]["coverage"] if top else 0.0
        results.append(
            {
                "claim": claim,
                "verdict": _verdict(best, best_coverage),
                "best_score": best,
                "best_coverage": best_coverage,
                "evidence": top,
            }
        )

    return {
        "identifier": identifier,
        "doi": paper.get("doi"),
        "pmid": paper.get("pmid"),
        "title": paper.get("title"),
        "local_pdf": paper.get("local_pdf"),
        "text_source": text_source,
        "claims": results,
        "notes": [
            "Lexical TF-IDF overlap only; this is not a semantic entailment or fact-checking model.",
            "A high score means the paper contains similar wording, not that the claim is true.",
        ],
    }


def _review_markdown(review: Dict[str, Any]) -> str:
    lines = [
        f"# {review['title']}",
        "",
        f"_Generated: {review['generated_at']}_",
        "",
    ]
    for section in review.get("sections") or []:
        heading = section.get("heading") or "Section"
        body = section.get("body") or ""
        lines.extend([f"## {heading}", "", str(body).strip(), ""])

    references = review.get("references") or []
    if references:
        lines.extend(["## References", ""])
        for index, ref in enumerate(references, 1):
            authors = ", ".join(ref.get("authors") or []) or "Unknown authors"
            year = ref.get("year") or "n.d."
            title = ref.get("title") or ""
            journal = ref.get("journal") or ""
            doi = normalize_doi(ref.get("doi"))
            url = ref.get("url") or (f"https://doi.org/{doi}" if doi else "")
            line = f"{index}. **{authors}** ({year}). *{title}*. {journal}."
            if url:
                line += f" [Link]({url})"
            lines.append(line)
        lines.append("")

    claims = review.get("claims") or []
    if claims:
        lines.extend(
            [
                "## Evidence map",
                "",
                "| Claim | Verdict | Score | Evidence | Source |",
                "|---|---|---|---|---|",
            ]
        )
        for claim in claims:
            evidence = claim.get("evidence") or []
            first = evidence[0] if evidence else {}
            source = claim.get("doi") or claim.get("identifier") or ""
            lines.append(
                "| "
                + " | ".join(
                    _escape_md(value)[:320]
                    for value in (
                        claim.get("claim"),
                        claim.get("verdict"),
                        claim.get("best_score"),
                        first.get("text"),
                        source,
                    )
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _review_csv(review: Dict[str, Any]) -> str:
    buffer = io.StringIO()
    claims = review.get("claims") or []
    references = review.get("references") or []

    if claims:
        fieldnames = [
            "claim", "verdict", "score", "evidence", "page",
            "doi", "title", "year", "journal", "url",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for claim in claims:
            evidence = claim.get("evidence") or []
            first = evidence[0] if evidence else {}
            doi = normalize_doi(claim.get("doi") or "")
            writer.writerow(
                {
                    "claim": claim.get("claim"),
                    "verdict": claim.get("verdict"),
                    "score": claim.get("best_score"),
                    "evidence": first.get("text"),
                    "page": first.get("page"),
                    "doi": doi,
                    "title": claim.get("title"),
                    "year": claim.get("year"),
                    "journal": claim.get("journal"),
                    "url": f"https://doi.org/{doi}" if doi else "",
                }
            )
    else:
        fieldnames = ["authors", "year", "title", "journal", "doi", "url"]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for ref in references:
            doi = normalize_doi(ref.get("doi"))
            writer.writerow(
                {
                    "authors": "; ".join(ref.get("authors") or []),
                    "year": ref.get("year"),
                    "title": ref.get("title"),
                    "journal": ref.get("journal"),
                    "doi": doi,
                    "url": ref.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                }
            )
    return buffer.getvalue()


async def export_review(
    title: str,
    sections: Optional[Sequence[Dict[str, Any]]] = None,
    content: Optional[str] = None,
    references: Optional[Sequence[Dict[str, Any]]] = None,
    claims: Optional[Sequence[Dict[str, Any]]] = None,
    format: str = "markdown",
    filename: Optional[str] = None,
    output_path: Optional[str] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    if not title.strip():
        return _error("title is required")

    fmt = (format or "markdown").lower()
    if fmt in ("md", "markdown"):
        fmt = "markdown"
        extension = ".md"
        encoding = "utf-8"
    elif fmt == "csv":
        extension = ".csv"
        encoding = "utf-8-sig"
    elif fmt == "json":
        extension = ".json"
        encoding = "utf-8"
    else:
        return _error("format must be markdown, csv, or json")

    review: Dict[str, Any] = {
        "title": title.strip(),
        "generated_at": _iso_now(),
        "sections": list(sections or []),
        "references": list(references or []),
        "claims": list(claims or []),
    }
    if content and not review["sections"]:
        review["sections"] = [{"heading": "Review", "body": content}]

    if fmt == "markdown":
        payload = _review_markdown(review)
    elif fmt == "csv":
        payload = _review_csv(review)
    else:
        payload = json.dumps(review, ensure_ascii=False, indent=2) + "\n"

    if project:
        config = _project_config(project)
        base_dir = Path(
            config.get("output_directory") or config["paper_directory"]
        ).expanduser().resolve()
    else:
        base_dir = _common.REVIEW_OUTPUT_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    def _stem(value: str) -> str:
        value = value.strip()
        return value[: -len(extension)] if value.lower().endswith(extension) else value

    if output_path:
        path = Path(output_path).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        path = path.resolve()
        if path.is_dir():
            path = path / (_safe_slug(_stem(filename or title)) + extension)
        try:
            path.relative_to(base_dir)
        except ValueError:
            return _error(
                (
                    "output_path must be inside the project output directory"
                    if project
                    else "output_path must be inside REVIEW_OUTPUT_DIR"
                ),
                output_dir=str(base_dir),
                output_path=str(path),
            )
    elif filename:
        name = _safe_slug(_stem(filename)) + extension
        path = base_dir / name
    else:
        path = base_dir / f"{_safe_slug(title)}-{timestamp}{extension}"

    if path.suffix.lower() != extension:
        path = path.with_suffix(extension)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding=encoding)

    result = {
        "path": str(path),
        "format": fmt,
        "bytes": len(payload.encode(encoding)),
        "references_count": len(review["references"]),
        "claims_count": len(review["claims"]),
        "title": review["title"],
    }
    if project:
        result["project"] = project
        result["output_directory"] = str(base_dir)
    return result


