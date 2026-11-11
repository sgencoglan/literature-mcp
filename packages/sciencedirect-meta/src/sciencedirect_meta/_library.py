"""Local PDF library: scan, DOI/title matching, read and audit."""


from __future__ import annotations

import asyncio
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pymupdf

from sciencedirect_meta import _common
from sciencedirect_meta._common import _DOI_RE, _authors_short, _clean_doi, _error, logger
from sciencedirect_meta._crossref import _metadata_for, doi_provenance
from sciencedirect_meta._journals import journal_rank
from sciencedirect_meta._projects import (
    _openalex_flags,
    _project_analysis_path,
    _project_config,
    _project_scope,
    _projects_registry,
    _resolve_filename_doi,
)
from sciencedirect_meta.server import (
    normalize_doi,
    redact_secrets,
)

_LIBRARY_CACHE: Dict[str, Dict[str, Any]] = {}


_TITLE_STOPWORDS = set(
    """
    a an the and or of to in on for with by from as at is are was were be been
    this that these those using based study studies research paper article
    ve bir bu da de için ile olan olarak gibi
    """.split()
)


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _title_tokens(value: str) -> set:
    return {
        token
        for token in re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", (value or "").lower())
        if token not in _TITLE_STOPWORDS
    }


def _first_page_metadata(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    cached = _LIBRARY_CACHE.get(str(path))
    if cached and cached.get("mtime") == stat.st_mtime and cached.get("size") == stat.st_size:
        return cached

    doi = ""
    title_guess = ""
    first_text = ""
    try:
        with pymupdf.open(str(path)) as document:
            chunks: List[str] = []
            for page_index in range(min(2, document.page_count)):
                try:
                    chunks.append(document.load_page(page_index).get_text("text") or "")
                except Exception:  # noqa: BLE001
                    continue
            first_text = re.sub(r"\s+", " ", "\n".join(chunks)).strip()
            match = _DOI_RE.search(first_text)
            if match:
                doi = _clean_doi(match.group(0))
            if not title_guess:
                try:
                    metadata = document.metadata or {}
                    title_guess = metadata.get("title") or metadata.get("/Title") or ""
                except Exception:  # noqa: BLE001
                    title_guess = ""
            if not title_guess and first_text:
                for line in re.split(r"(?<=[.!?])\s+|\n", first_text):
                    line = line.strip()
                    if 20 <= len(line) <= 300 and not line.lower().startswith(("doi", "http")):
                        title_guess = line
                        break
    except Exception as exc:  # noqa: BLE001
        logger.info("PDF metadata extraction failed for %s: %s", path, exc)

    record = {
        "path": str(path),
        "filename": path.name,
        "doi": doi,
        "title_guess": title_guess,
        "first_text": first_text[:4000],
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }
    _LIBRARY_CACHE[str(path)] = record
    return record


def _library_scan(
    directory: Optional[Path] = None,
    recurse: bool = True,
) -> List[Dict[str, Any]]:
    root = Path(directory).expanduser() if directory else _common.PAPER_LIBRARY_DIR
    if not root.exists():
        return []
    iterator = root.rglob("*") if recurse else root.iterdir()
    paths = sorted(
        (
            path
            for path in iterator
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:300]
    return [_first_page_metadata(path) for path in paths if path.is_file()]


def _title_similarity(left: str, right: str) -> float:
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _match_local_pdf(
    doi: str = "",
    title: str = "",
    directory: Optional[Path] = None,
    recurse: bool = True,
) -> Optional[Dict[str, Any]]:
    records = _library_scan(directory, recurse)
    if not records:
        return None

    doi = normalize_doi(doi)
    doi_token = _normalize_token(doi)
    best: Optional[Dict[str, Any]] = None

    if doi_token:
        for record in records:
            if doi_token in _normalize_token(record["filename"]):
                return {
                    "path": record["path"],
                    "filename": record["filename"],
                    "match": "doi_in_filename",
                    "score": 1.0,
                    "detected_doi": record["doi"] or doi,
                    "title_guess": record["title_guess"],
                }
        for record in records:
            if doi and normalize_doi(record["doi"]) == doi:
                return {
                    "path": record["path"],
                    "filename": record["filename"],
                    "match": "doi_in_pdf_text",
                    "score": 1.0,
                    "detected_doi": record["doi"],
                    "title_guess": record["title_guess"],
                }
        for record in records:
            if doi_token and doi_token in _normalize_token(record["first_text"]):
                return {
                    "path": record["path"],
                    "filename": record["filename"],
                    "match": "doi_in_pdf_text",
                    "score": 0.95,
                    "detected_doi": record["doi"] or doi,
                    "title_guess": record["title_guess"],
                }

    if title:
        for record in records:
            score = max(
                _title_similarity(title, record["title_guess"]),
                _title_similarity(title, record["filename"].replace("_", " ")),
            )
            if score >= 0.55 and (best is None or score > best["score"]):
                best = {
                    "path": record["path"],
                    "filename": record["filename"],
                    "match": "title_similarity",
                    "score": round(score, 3),
                    "detected_doi": record["doi"] or None,
                    "title_guess": record["title_guess"],
                }

    return best


def _annotate_local_pdfs(
    items: Sequence[Dict[str, Any]],
    directory: Optional[Path] = None,
    recurse: bool = True,
) -> None:
    root = Path(directory).expanduser() if directory else _common.PAPER_LIBRARY_DIR
    if not root.exists():
        return
    for item in list(items)[:25]:
        try:
            match = _match_local_pdf(
                item.get("doi") or "", item.get("title") or "", root, recurse
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("Local PDF matching failed: %s", exc)
            match = None
        item["local_pdf"] = match["path"] if match else None
        item["local_pdf_match"] = match["match"] if match else None
        item["local_pdf_score"] = match["score"] if match else None


def list_projects() -> Dict[str, Any]:
    """List registered projects with per-project PDF inventory and manifest status.

    Projects come from the shared registry (``~/.literature-mcp/projects.json``); each
    project is isolated (own folder + manifest + PaperQA2 index).  Callers
    should then pass ``project=...`` to read_paper / evidence_check /
    library_status so that lookups stay inside one project.
    """
    registry = _projects_registry()
    projects = registry.get("projects") or {}
    entries: List[Dict[str, Any]] = []
    for name, config in sorted(projects.items()):
        directory = Path(config["paper_directory"]).expanduser()
        recurse = bool(config.get("include_subdirectories", False))
        records = _library_scan(directory, recurse) if directory.exists() else []
        manifest_path = (
            Path(config["manifest"]).expanduser() if config.get("manifest") else None
        )
        manifest_files: List[str] = []
        if manifest_path and manifest_path.exists():
            try:
                with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
                    manifest_files = [
                        row.get("file_location") or ""
                        for row in csv.DictReader(handle)
                    ]
            except Exception as exc:  # noqa: BLE001
                logger.info("Manifest could not be read (%s): %s", manifest_path, exc)
        manifest_set = {value for value in manifest_files if value}
        filenames = {record["filename"] for record in records}
        entries.append(
            {
                "project": name,
                "title": config.get("title"),
                "description": config.get("description"),
                "paper_directory": str(directory),
                "directory_exists": directory.exists(),
                "include_subdirectories": recurse,
                "pdf_files": len(records),
                "files_with_detected_doi": sum(1 for r in records if r["doi"]),
                "manifest": str(manifest_path) if manifest_path else None,
                "manifest_rows": len(manifest_set),
                "files_not_in_manifest": sorted(filenames - manifest_set),
                "index_name": config.get("index_name"),
                "index_directory": config.get("index_directory"),
                "output_directory": config.get("output_directory"),
                "analysis_json": config.get("analysis_json"),
            }
        )
    return {
        "registry": str(_common.LIT_PROJECTS_REGISTRY),
        "registry_exists": _common.LIT_PROJECTS_REGISTRY.exists(),
        "count": len(entries),
        "projects": entries,
        "notes": [
            "Projeler izole kayıtlardır: paper_directory + manifest + PaperQA indeksi.",
            "Yerel metin araçlarına project=... verin; böylece yalnızca o projenin PDF'leri taranır.",
            "project verilmezse eski PAPER_LIBRARY_DIR davranışı korunur.",
        ],
    }


async def project_audit(
    project: str,
    include_quartiles: bool = True,
    check_retractions: bool = True,
    max_dois: int = 50,
) -> Dict[str, Any]:
    """Audit one project's PDFs: DOI detection + metadata + citations + quartiles.

    Per unique DOI it reports: metadata (OpenAlex/Europe PMC, Crossref fallback),
    in which databases the DOI is indexed, Crossref vs OpenAlex citation counts,
    SCImago journal quartile, and (optionally) OpenAlex retraction flags.
    Only this project's folder is scanned; nothing mixes across projects.
    """
    try:
        config = _project_config(project)
    except KeyError as exc:
        return _error(str(exc))
    directory = Path(config["paper_directory"]).expanduser()
    recurse = bool(config.get("include_subdirectories", False))
    if not directory.exists():
        return _error("Proje klasörü bulunamadı", paper_directory=str(directory))

    records = _library_scan(directory, recurse)
    if not records:
        return _error("Proje klasöründe PDF yok", paper_directory=str(directory))

    files: List[Dict[str, Any]] = []
    doi_to_files: Dict[str, List[str]] = {}
    for record in records:
        doi = await _resolve_filename_doi(record)
        files.append(
            {
                "file": record["filename"],
                "path": record["path"],
                "detected_doi": doi or None,
                "title_guess": record["title_guess"] or None,
                "size_mb": round(record["size"] / (1024 * 1024), 2),
            }
        )
        if doi:
            doi_to_files.setdefault(doi, []).append(record["filename"])

    dois = list(doi_to_files)[: max(1, min(int(max_dois), 200))]
    semaphore = asyncio.Semaphore(3)

    async def audit_one(doi: str, number: int) -> Dict[str, Any]:
        async with semaphore:
            row: Dict[str, Any] = {
                "no": number,
                "doi": doi,
                "local_files": doi_to_files.get(doi, []),
            }
            try:
                meta = await _metadata_for(doi)
            except Exception as exc:  # noqa: BLE001
                meta = {}
                row["metadata_error"] = redact_secrets(exc)
            row.update(
                {
                    "title": meta.get("title"),
                    "authors_short": _authors_short(meta.get("authors")),
                    "year": meta.get("year"),
                    "journal": meta.get("journal"),
                    "publisher": meta.get("publisher_label") or meta.get("publisher"),
                    "pmid": meta.get("pmid"),
                    "open_access": meta.get("open_access") if "open_access" in meta else meta.get("is_oa"),
                }
            )
            try:
                provenance = await doi_provenance(doi)
                checks = provenance.get("checks") or {}
            except Exception as exc:  # noqa: BLE001
                checks = {}
                row["provenance_error"] = redact_secrets(exc)
            for source_name in ("crossref", "openalex", "europepmc", "pubmed"):
                check = checks.get(source_name) or {}
                row[f"{source_name}_found"] = bool(check.get("found"))
            crossref_citations = (checks.get("crossref") or {}).get("cited_by")
            openalex_citations = (checks.get("openalex") or {}).get("cited_by")
            row["crossref_citations"] = crossref_citations
            row["openalex_citations"] = openalex_citations
            if crossref_citations is not None and openalex_citations is not None:
                row["citations_difference"] = openalex_citations - crossref_citations
            row["found_in"] = provenance.get("found_in")
            if include_quartiles and row.get("journal"):
                try:
                    quartiles = await journal_rank(
                        [str(row["journal"])], include_categories=False
                    )
                    results = quartiles.get("results") or []
                    if results and results[0].get("found"):
                        row["scimago_quartile"] = results[0].get("quartile")
                except Exception as exc:  # noqa: BLE001
                    logger.info("Quartile lookup failed for %s: %s", doi, exc)
            if check_retractions:
                flags = await _openalex_flags(doi)
                row["is_retracted"] = flags.get("is_retracted")
                row["counts_by_year"] = flags.get("counts_by_year")
            return row

    audits = await asyncio.gather(
        *(audit_one(doi, number) for number, doi in enumerate(dois, start=1))
    )

    no_doi_files = [f["file"] for f in files if not f["detected_doi"]]
    return {
        "project": project,
        "title": config.get("title"),
        "paper_directory": str(directory),
        "files": files,
        "no_doi_files": no_doi_files,
        "dois": audits,
        "summary": {
            "pdf_files": len(files),
            "files_with_doi": len(files) - len(no_doi_files),
            "unique_dois": len(dois),
            "missing_metadata": sum(1 for a in audits if not a.get("title")),
            "retracted": sum(1 for a in audits if a.get("is_retracted")),
        },
        "notes": [
            "Metadata: OpenAlex + Europe PMC (yedek: Crossref); atıf sayıları Crossref ve OpenAlex'ten.",
            "is_retracted OpenAlex kaydından gelir; null = bilinmiyor.",
            "Bu denetim yalnızca bu projenin klasörünü tarar; diğer projelere dokunmaz.",
        ],
    }


def _extract_pdf_pages(
    path: Path,
    max_pages: int = _common.PDF_MAX_PAGES,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> Tuple[int, List[Dict[str, Any]]]:
    with pymupdf.open(str(path)) as document:
        page_count = document.page_count

        if page_start or page_end:
            start = max(1, int(page_start or 1))
            end = min(page_count, int(page_end or page_count))
            indexes = list(range(start - 1, max(start - 1, end)))
        else:
            indexes = list(range(min(page_count, max(1, max_pages))))

        pages: List[Dict[str, Any]] = []
        for index in indexes:
            try:
                text = document.load_page(index).get_text("text") or ""
            except Exception as exc:  # noqa: BLE001
                text = ""
                logger.info("PDF page %s extraction failed in %s: %s", index + 1, path, exc)
            pages.append(
                {
                    "page": index + 1,
                    "text": re.sub(r"[ \t]+", " ", text).strip(),
                }
            )
        return page_count, pages


def analysis_updates(
    doi: Optional[str] = None,
    entry_id: Optional[int] = None,
    query: Optional[str] = None,
    include_entries: bool = True,
    include_corrections: bool = True,
    include_matrices: bool = True,
    include_gap_analysis: bool = True,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the saved full-text citation audit and its evidence matrices.

    The audit is a local, versioned JSON record.  It is not a literature
    search: it documents how abstract-level claims were checked against the
    page-level full text and which sentences were used in the draft.  The
    same file also stores the claim-evidence matrix, the methodological
    quality/risk-of-bias assessment, the source budget, and an optional gap
    analysis so they remain queryable from the MCP server.

    Pass ``project`` to read that project's own ``analysis_json`` file from the
    shared registry; without it the legacy global audit file is used.
    """
    path = _common.ANALYSIS_UPDATES_PATH
    if project:
        try:
            config = _project_config(project)
        except KeyError as exc:
            return _error(str(exc))
        resolved = _project_analysis_path(config)
        if not resolved:
            return _error(
                "Bu proje için analiz dosyası yolu tanımlı değil",
                project=project,
                hint=(
                    "Proje kaydına analysis_json ya da output_directory ekleyin; "
                    "ardından proje için analysis_updates dosyasını oluşturun."
                ),
            )
        path = resolved
    if not path.exists():
        hint = (
            "Bu proje için analysis_updates dosyasını oluşturun."
            if project
            else "Set ANALYSIS_UPDATES_JSON or add analysis_json to the project registry."
        )
        return _error("analysis updates file not found", path=str(path), hint=hint)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return _error("analysis updates file could not be read", path=str(path), detail=str(exc))

    entries = list(data.get("entries") or [])
    documents = list(data.get("documents") or [])
    corrections = list(data.get("corrections") or [])
    claim_matrix = list(data.get("claim_matrix") or [])
    risk_of_bias = list(data.get("risk_of_bias") or [])
    source_budget = list(data.get("source_budget") or [])
    gap_analysis = dict(data.get("gap_analysis") or {})

    normalized_doi = normalize_doi(doi) if doi else ""
    if normalized_doi:
        entries = [e for e in entries if normalize_doi(e.get("doi")) == normalized_doi]
        documents = [d for d in documents if normalize_doi(d.get("doi")) == normalized_doi]
        corrections = [c for c in corrections if normalize_doi(c.get("doi")) == normalized_doi]
        claim_matrix = [c for c in claim_matrix if normalize_doi(c.get("doi")) == normalized_doi]
        risk_of_bias = [r for r in risk_of_bias if normalize_doi(r.get("doi")) == normalized_doi]

    if entry_id is not None:
        try:
            wanted = int(entry_id)
        except (TypeError, ValueError):
            return _error("entry_id must be an integer")
        entries = [e for e in entries if int(e.get("id", -1)) == wanted]
        claim_matrix = [c for c in claim_matrix if int(c.get("id", -1)) == wanted]

    if query:
        needle = query.strip().casefold()
        if needle:
            def _haystack(item: Dict[str, Any]) -> str:
                parts: List[str] = [
                    str(item.get("citation") or item.get("heading") or ""),
                    str(item.get("constructed_sentence") or ""),
                    str(item.get("notes") or ""),
                ]
                for evidence in item.get("full_text_evidence") or []:
                    parts.append(str(evidence.get("original") or ""))
                    parts.append(str(evidence.get("turkish") or ""))
                parts.extend(str(s) for s in (item.get("original_sentences") or []))
                return " ".join(parts).casefold()

            entries = [e for e in entries if needle in _haystack(e)]
            documents = [
                d for d in documents
                if needle in " ".join(
                    str(d.get(k) or "") for k in ("authors", "journal", "doi", "quartile")
                ).casefold()
            ]
            corrections = [
                c for c in corrections
                if needle in " ".join(
                    str(c.get(k) or "") for k in ("author_year", "abstract_claim", "full_text_finding", "action", "doi")
                ).casefold()
            ]
            claim_matrix = [
                c for c in claim_matrix
                if needle in " ".join(
                    str(c.get(k) or "") for k in (
                        "id", "paragraph", "doi", "citation", "claim", "key_evidence",
                        "evidence_type", "support", "strength", "decision",
                    )
                ).casefold()
            ]
            risk_of_bias = [
                r for r in risk_of_bias
                if needle in " ".join(
                    str(r.get(k) or "") for k in (
                        "doi", "study", "design", "strengths", "limitations",
                        "overall", "chapter_implication",
                    )
                ).casefold()
            ]
            source_budget = [
                b for b in source_budget
                if needle in " ".join(
                    str(b.get(k) or "") for k in (
                        "level", "words", "ideal_sources", "max_sources", "note",
                    )
                ).casefold()
            ]
            if gap_analysis:
                gap_analysis["comparison"] = [
                    row for row in (gap_analysis.get("comparison") or [])
                    if needle in " ".join(
                        str(row.get(k) or "") for k in (
                            "capability", "reference", "local", "gap", "chapter_relevance",
                        )
                    ).casefold()
                ]
                gap_analysis["chapter_improvements"] = [
                    row for row in (gap_analysis.get("chapter_improvements") or [])
                    if needle in " ".join(
                        str(row.get(k) or "") for k in (
                            "priority", "improvement", "status", "detail",
                        )
                    ).casefold()
                ]

    result: Dict[str, Any] = {
        "revision": data.get("revision"),
        "schema": data.get("schema"),
        "matrix_revision": data.get("matrix_revision"),
        "entry_format": data.get("entry_format"),
        "topic": data.get("topic"),
        "generated_at": data.get("generated_at"),
        "source_policy": data.get("source_policy"),
        "path": str(path),
        "entry_count": len(entries),
        "evidence_count": sum(len(e.get("full_text_evidence") or []) for e in entries),
        "document_count": len(documents),
        "correction_count": len(corrections),
        "claim_count": len(claim_matrix),
        "risk_of_bias_count": len(risk_of_bias),
        "source_budget_count": len(source_budget),
        "documents": documents,
    }
    if include_entries:
        result["entries"] = entries
    if include_corrections:
        result["corrections"] = corrections
    if include_matrices:
        result["claim_matrix"] = claim_matrix
        result["risk_of_bias"] = risk_of_bias
        result["source_budget"] = source_budget
    if include_gap_analysis:
        result["gap_analysis"] = gap_analysis
    for key in ("report_title", "corrected_text", "limitations", "next_steps"):
        if key in data:
            result[key] = data.get(key)
    return result


def library_status(project: Optional[str] = None) -> Dict[str, Any]:
    """List local PDFs, optionally scoped to a single registered project.

    With ``project`` given, only that project's folder is scanned, so the
    inventory never mixes files from other projects.  Without it, the legacy
    PAPER_LIBRARY_DIR folder is scanned (recursively).
    """
    try:
        directory, recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    root = directory or _common.PAPER_LIBRARY_DIR
    records = _library_scan(directory, recurse)
    files = [
        {
            "path": record["path"],
            "filename": record["filename"],
            "detected_doi": record["doi"] or None,
            "title_guess": record["title_guess"] or None,
            "size_mb": round(record["size"] / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(record["mtime"], tz=timezone.utc).isoformat(),
        }
        for record in records
    ]
    notes = [
        "Place PDFs in the library folder; filenames containing the DOI work best.",
        "The DOI is also detected from the first two pages of each PDF.",
    ]
    if project:
        notes.append(
            f"Yalnızca {project!r} projesinin klasörü tarandı; diğer projeler dışarıda bırakıldı."
        )
    return {
        "project": project or None,
        "library_dir": str(root),
        "exists": root.exists(),
        "recurse_subdirectories": recurse,
        "count": len(files),
        "with_detected_doi": sum(1 for f in files if f["detected_doi"]),
        "files": files,
        "notes": notes,
    }


async def read_paper(
    identifier: Optional[str] = None,
    id_type: str = "doi",
    pdf_path: Optional[str] = None,
    max_chars: int = _common.READ_MAX_CHARS,
    max_pages: int = _common.PDF_MAX_PAGES,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    project: Optional[str] = None,
) -> Dict[str, Any]:
    """Read one local PDF, optionally scoped to a single registered project.

    With ``project`` given, DOI/title matching only searches that project's
    folder and an explicit ``pdf_path`` outside the project folder is rejected,
    so lookups never leak across projects.
    """
    try:
        scope_dir, scope_recurse = _project_scope(project)
    except KeyError as exc:
        return _error(str(exc))
    if not identifier and not pdf_path:
        return library_status(project)

    identifier = (identifier or "").strip()
    id_type = (id_type or "doi").lower()
    meta: Dict[str, Any] = {}
    doi = ""
    title = ""

    if identifier:
        if id_type == "doi":
            doi = normalize_doi(identifier)
        elif id_type == "title":
            title = identifier
        elif id_type != "pmid":
            return _error("id_type must be doi, pmid, or title")
        if id_type != "title":
            maybe_meta = await _metadata_for(identifier, id_type)
            if maybe_meta:
                meta = maybe_meta
                doi = doi or normalize_doi(meta.get("doi"))
                title = title or (meta.get("title") or "")

    if pdf_path:
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
        match = {
            "path": str(path),
            "filename": path.name,
            "match": "explicit_path",
            "score": 1.0,
            "detected_doi": doi or None,
            "title_guess": title or None,
        }
    else:
        match = _match_local_pdf(doi, title, scope_dir, scope_recurse)
        if not match:
            return _error(
                "No matching PDF found in the local library",
                identifier=identifier,
                doi=doi or None,
                title=title or None,
                project=project or None,
                library_dir=str(scope_dir or _common.PAPER_LIBRARY_DIR),
                notes=[
                    "Place the full-text PDF in the library folder.",
                    "Using filenames that contain the DOI gives the most reliable match.",
                    "Call library_status to inspect the folder.",
                ],
            )
        path = Path(match["path"])

    if path.suffix.lower() != ".pdf":
        return _error("Selected file is not a PDF", path=str(path))
    try:
        page_count, pages = _extract_pdf_pages(
            path,
            max_pages=max_pages,
            page_start=page_start,
            page_end=page_end,
        )
    except Exception as exc:  # noqa: BLE001
        return _error("PDF parsing failed", path=str(path), detail=str(exc))

    full_text = "\n\n".join(page["text"] for page in pages if page["text"])
    truncated = len(full_text) > max_chars
    notes: List[str] = ["Text was read from the local library; nothing was downloaded."]
    if not full_text.strip():
        notes.append("No extractable text found; the PDF may be scanned or image-only.")

    return {
        "identifier": identifier or None,
        "doi": doi or meta.get("doi") or match.get("detected_doi"),
        "pmid": meta.get("pmid"),
        "title": meta.get("title") or match.get("title_guess"),
        "authors": meta.get("authors"),
        "year": meta.get("year"),
        "journal": meta.get("journal"),
        "path": str(path),
        "filename": path.name,
        "match": match.get("match"),
        "match_score": match.get("score"),
        "detected_doi": match.get("detected_doi"),
        "page_count": page_count,
        "pages_read": len(pages),
        "page_range": [pages[0]["page"], pages[-1]["page"]] if pages else [],
        "truncated": truncated,
        "text": full_text[:max_chars],
        "notes": notes,
    }


