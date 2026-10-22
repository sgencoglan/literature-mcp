"""Local PaperQA2 MCP server — multi-project, project-isolated.

Kavramlar
---------
- **Proje kaydı** (``projects.json``): her proje için ``paper_directory``,
  ``manifest`` (CSV), ``index_directory`` ve ``index_name`` tutar.
- **İzolasyon:** Her projenin kendi manifesti ve kendi Tantivy indeksi vardır.
  Bir projedeki arama/okuma/indeksleme diğer projelere taşmaz.
- Araçlar ``project`` parametresini açıkça ister; bilinmeyen proje adı kayıtlı
  projeleri listeleyen bir hata döndürür.
- **İndeks üyeliği manifest tarafından belirlenir** (klasör taraması değil):
  klasöre sonradan bırakılan bir PDF, manifeste eklenmedikçe indekse girmez.
  Böylece eski projeler sonradan eklenen dosyalarla karışmaz.

Araçlar
-------
``paperqa_projects``          — kayıtlı projeler ve durumları
``paperqa_register_project``  — klasörü proje olarak kaydet + manifest üret
``paperqa_build_index``       — proje indeksini kur/güncelle (manifest üyeliği)
``paperqa_status``            — proje indeks durumu
``paperqa_search``            — proje içinde semantik arama (LLM'siz)
``paperqa_read_pages``        — projedeki PDF'ten sayfa okuma (DOI ile)
``paperqa_ask``               — yerel Qwen ile soru (taslak; doğrulama gerekir)
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx
import pymupdf
from mcp.server.fastmcp import FastMCP

from paperqa.agents.search import SearchIndex
from paperqa.docs import Docs
from paperqa.settings import AgentSettings, IndexSettings, ParsingSettings, Settings

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_REGISTRY = str(Path.home() / ".literature-mcp" / "projects.json")
REGISTRY_PATH = Path(
    os.environ.get("LIT_PROJECTS_REGISTRY", DEFAULT_REGISTRY)
).expanduser()
DEFAULT_INDEX_ROOT = Path(
    os.environ.get("PAPERQA_INDEX_ROOT", str(Path.home() / ".literature-mcp" / "indexes"))
).expanduser()
DEFAULT_PROJECTS_ROOT = Path(
    os.environ.get("PAPERQA_PROJECTS_ROOT", str(Path.home() / ".literature-mcp" / "projects"))
).expanduser()

EMBEDDING = "st-multi-qa-MiniLM-L6-cos-v1"
LOCAL_LLM = os.environ.get(
    "PAPERQA_LOCAL_LLM", "ollama/qwen2.5:3b-instruct"
)
LOCAL_LLM_CONFIG = {
    "model_list": [
        {
            "model_name": LOCAL_LLM,
            "litellm_params": {
                "model": LOCAL_LLM,
                "api_base": "http://127.0.0.1:11434",
                "timeout": 600,
                "max_tokens": 400,
            },
        }
    ]
}

MAILTO = os.environ.get("CROSSREF_MAILTO", "research@example.org")
HTTP_TIMEOUT = 25.0
MANIFEST_FIELDS = ["file_location", "doi", "title", "journal", "year", "authors"]
INDEX_FIELDS = ["file_location", "body", "title", "year"]
PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,60}$")
PDF_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)

logger = logging.getLogger("paperqa-local")

mcp = FastMCP("paperqa-local")

_registry_cache: dict[str, Any] = {"mtime": None, "data": None}
_settings_cache: dict[str, Settings] = {}
_docs_cache: dict[str, Docs] = {}
_doc_meta: dict[str, dict[str, dict[str, Any]]] = {}
_load_locks: dict[str, asyncio.Lock] = {}
_http_client: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={
                "User-Agent": f"paperqa-local-mcp/0.2 (mailto:{MAILTO})",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )
    return _http_client


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Project registry (shared with the sciencedirect-meta MCP)
# --------------------------------------------------------------------------- #

def _load_registry(force: bool = False) -> dict[str, Any]:
    global _registry_cache
    try:
        mtime = REGISTRY_PATH.stat().st_mtime
    except OSError:
        data = {"schema": 1, "projects": {}}
        _registry_cache = {"mtime": None, "data": data}
        return data
    if (
        not force
        and _registry_cache["data"] is not None
        and _registry_cache["mtime"] == mtime
    ):
        return _registry_cache["data"]
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    data.setdefault("schema", 1)
    data.setdefault("projects", {})
    _registry_cache = {"mtime": mtime, "data": data}
    return data


def _save_registry(data: dict[str, Any]) -> None:
    global _registry_cache
    data["updated_at"] = _now()
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(REGISTRY_PATH)
    _registry_cache = {"mtime": REGISTRY_PATH.stat().st_mtime, "data": data}


def _project_config(name: str) -> dict[str, Any]:
    name = (name or "").strip()
    registry = _load_registry()
    projects = registry.get("projects") or {}
    if name not in projects:
        available = ", ".join(sorted(projects)) or "(kayıtlı proje yok)"
        raise ValueError(
            f"Bilinmeyen proje: {name!r}. Kayıtlı projeler: {available}"
        )
    return projects[name]


def _paper_directory(cfg: dict[str, Any]) -> Path:
    return Path(cfg["paper_directory"]).expanduser()


def _manifest_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg["manifest"]).expanduser()


def _recurse(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("include_subdirectories", False))


def _project_summary(name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    directory = _paper_directory(cfg)
    manifest = _manifest_path(cfg)
    pdfs = _scan_pdfs(directory, _recurse(cfg)) if directory.exists() else []
    manifest_rows: list[dict[str, Any]] = []
    if manifest.exists():
        try:
            manifest_rows = _read_manifest(cfg)
        except Exception:  # noqa: BLE001
            manifest_rows = []
    return {
        "project": name,
        "title": cfg.get("title"),
        "description": cfg.get("description"),
        "paper_directory": str(directory),
        "directory_exists": directory.exists(),
        "recurse_subdirectories": _recurse(cfg),
        "pdf_files_in_directory": len(pdfs),
        "manifest": str(manifest),
        "manifest_rows": len(manifest_rows),
        "index_name": cfg.get("index_name"),
        "index_directory": cfg.get("index_directory"),
        "output_directory": cfg.get("output_directory"),
        "analysis_json": cfg.get("analysis_json"),
        "created_at": cfg.get("created_at"),
        "updated_at": cfg.get("updated_at"),
    }


# --------------------------------------------------------------------------- #
# Settings per project
# --------------------------------------------------------------------------- #

def _settings_for(name: str, cfg: dict[str, Any]) -> Settings:
    if name in _settings_cache:
        return _settings_cache[name]
    settings = Settings(
        llm=LOCAL_LLM,
        llm_config=LOCAL_LLM_CONFIG,
        summary_llm=LOCAL_LLM,
        summary_llm_config=LOCAL_LLM_CONFIG,
        embedding=EMBEDDING,
        parsing=ParsingSettings(
            use_doc_details=False,
            multimodal=False,
            reader_config={
                "chunk_chars": 5000,
                "overlap": 250,
                "use_block_parsing": True,
            },
        ),
        agent=AgentSettings(
            agent_llm=LOCAL_LLM,
            agent_llm_config=LOCAL_LLM_CONFIG,
            agent_type="fake",
            index=IndexSettings(
                name=cfg["index_name"],
                paper_directory=str(_paper_directory(cfg)),
                manifest_file=str(_manifest_path(cfg)),
                index_directory=str(Path(cfg["index_directory"]).expanduser()),
                use_absolute_paper_directory=False,
                recurse_subdirectories=False,
            ),
            rebuild_index=False,
        ),
    )
    settings.answer.evidence_k = 4
    settings.answer.answer_max_sources = 3
    settings.answer.evidence_skip_summary = True
    settings.answer.answer_length = "about 150 words"
    settings.answer.max_concurrent_requests = 1
    _settings_cache[name] = settings
    return settings


def _search_index(cfg: dict[str, Any]) -> SearchIndex:
    return SearchIndex(
        fields=INDEX_FIELDS,
        index_name=cfg["index_name"],
        index_directory=str(Path(cfg["index_directory"]).expanduser()),
    )


# --------------------------------------------------------------------------- #
# Manifest helpers
# --------------------------------------------------------------------------- #

def _read_manifest(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    path = _manifest_path(cfg)
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            file_location = (row.get("file_location") or "").strip()
            if not file_location:
                continue
            row["file_location"] = file_location
            rows.append(row)
    return rows


def _manifest_by_location(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["file_location"]: row for row in _read_manifest(cfg)}


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) or "" for field in MANIFEST_FIELDS})
    tmp.replace(path)


def _parse_authors(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(a).strip() for a in value if str(a).strip()]
    text = str(value).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(a).strip() for a in parsed if str(a).strip()]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _format_authors(authors: list[str], limit: int = 6) -> str:
    if not authors:
        return ""
    shown = authors[:limit]
    if len(authors) == 1:
        return shown[0]
    if len(authors) == 2:
        return f"{shown[0]} and {shown[1]}"
    text = ", ".join(shown[:-1]) + f", and {shown[-1]}"
    if len(authors) > limit:
        text += " et al."
    return text


def _citation_for_row(file_location: str, row: dict[str, Any]) -> str:
    pieces: list[str] = []
    authors = _format_authors(_parse_authors(row.get("authors")))
    if authors:
        pieces.append(authors)
    title = (row.get("title") or "").strip()
    if title:
        pieces.append(title)
    journal = (row.get("journal") or "").strip()
    year = str(row.get("year") or "").strip()
    tail = ", ".join(part for part in (journal, year) if part)
    if tail:
        pieces.append(tail)
    if not pieces:
        pieces.append(Path(file_location).stem)
    citation = ". ".join(pieces)
    if not citation.endswith("."):
        citation += "."
    return citation


# --------------------------------------------------------------------------- #
# PDF / DOI helpers
# --------------------------------------------------------------------------- #

def _scan_pdfs(directory: Path, recurse: bool) -> list[Path]:
    if not directory.exists():
        return []
    iterator = directory.rglob("*") if recurse else directory.iterdir()
    return sorted(
        (
            path
            for path in iterator
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda p: str(p).lower(),
    )


def _doi_candidates_from_filename(name: str) -> list[str]:
    """Dosya adından olası DOI adayları üretir (kayıt numarası belirsizliği için).

    ``10.117701430343231202923.pdf`` gibi dosyalarda kayıt numarası 4, 5, ...
    haneli olabilir; adayları sırayla üretiriz ve Crossref ile doğrularız.
    """
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    match = re.match(r"^(10\.)(\d{4,9})(.*)$", stem)
    if not match:
        return []
    run, tail = match.group(2), match.group(3)
    candidates: list[str] = []
    for length in range(4, min(9, len(run)) + 1):
        rest = (run[length:] + tail).strip(" ._-")
        if not rest:
            continue
        doi = f"10.{run[:length]}/{rest}".rstrip(".,;:)]}\"'").lower()
        if doi not in candidates:
            candidates.append(doi)
    return candidates


async def _validate_doi(doi: str) -> bool:
    try:
        response = await _client().get(
            f"https://api.crossref.org/works/{quote(doi, safe='')}",
            params={"mailto": MAILTO},
        )
        return response.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def _resolve_doi_for_pdf(path: Path, probe: dict[str, Any]) -> tuple[str, bool]:
    """(doi, validasyon_yapıldı) döndürür. Önce doğrulanmış dosya adı adayı."""
    candidates = _doi_candidates_from_filename(path.name)
    validated = False
    if len(candidates) > 1:
        validated = True
        for candidate in candidates:
            if await _validate_doi(candidate):
                return candidate, validated
    probe_doi = (probe.get("doi") or "").strip().lower()
    if probe_doi:
        return probe_doi, validated
    if candidates:
        return candidates[0], validated
    return "", validated


def _pdf_probe(path: Path) -> dict[str, Any]:
    """İlk iki sayfa metni + PDF meta başlığı + DOI tahmini döndürür."""
    probe: dict[str, Any] = {"text": "", "title": "", "doi": ""}
    try:
        with pymupdf.open(str(path)) as document:
            chunks: list[str] = []
            for page_index in range(min(2, document.page_count)):
                try:
                    chunks.append(document.load_page(page_index).get_text("text") or "")
                except Exception:  # noqa: BLE001
                    continue
            probe["text"] = re.sub(r"\s+", " ", "\n".join(chunks)).strip()
            metadata = document.metadata or {}
            probe["title"] = (metadata.get("title") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.info("PDF probe failed for %s: %s", path, exc)
    match = PDF_DOI_RE.search(probe["text"])
    if match:
        probe["doi"] = match.group(0).rstrip(".,;:)]}\"'").lower()
    return probe


# --------------------------------------------------------------------------- #
# Metadata enrichment (Crossref -> OpenAlex, no API key)
# --------------------------------------------------------------------------- #

async def _enrich_crossref(doi: str) -> Optional[dict[str, Any]]:
    try:
        response = await _client().get(
            f"https://api.crossref.org/works/{quote(doi, safe='')}",
            params={"mailto": MAILTO},
        )
        if response.status_code != 200:
            return None
        message = response.json().get("message", {})
        year = None
        for key in ("published-print", "published-online", "issued"):
            parts = (message.get(key) or {}).get("date-parts") or []
            if parts and parts[0] and parts[0][0]:
                year = parts[0][0]
                break
        authors = []
        for author in message.get("author") or []:
            name = " ".join(
                part for part in (author.get("given"), author.get("family")) if part
            ) or author.get("name")
            if name:
                authors.append(name.strip())
        return {
            "title": (message.get("title") or [None])[0],
            "journal": (message.get("container-title") or [None])[0],
            "year": year,
            "authors": authors,
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("Crossref enrichment failed for %s: %s", doi, exc)
        return None


async def _enrich_openalex(doi: str) -> Optional[dict[str, Any]]:
    try:
        response = await _client().get(
            f"https://api.openalex.org/works/doi:{quote(doi, safe='')}",
            params={"mailto": MAILTO},
        )
        if response.status_code != 200:
            return None
        work = response.json()
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        return {
            "title": work.get("title"),
            "journal": source.get("display_name"),
            "year": work.get("publication_year"),
            "authors": [
                a.get("author", {}).get("display_name")
                for a in work.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("OpenAlex enrichment failed for %s: %s", doi, exc)
        return None


async def _enrich(doi: str) -> dict[str, Any]:
    meta = await _enrich_crossref(doi) if doi else None
    if not meta or not meta.get("title"):
        fallback = await _enrich_openalex(doi) if doi else None
        if fallback:
            meta = {
                key: (meta or {}).get(key) or fallback.get(key)
                for key in ("title", "journal", "year", "authors")
            }
    return meta or {}


# --------------------------------------------------------------------------- #
# Docs loading per project
# --------------------------------------------------------------------------- #

def _load_lock(name: str) -> asyncio.Lock:
    if name not in _load_locks:
        _load_locks[name] = asyncio.Lock()
    return _load_locks[name]


async def _load_docs(name: str, cfg: dict[str, Any]) -> Docs:
    if name in _docs_cache:
        return _docs_cache[name]
    async with _load_lock(name):
        if name in _docs_cache:
            return _docs_cache[name]
        index = _search_index(cfg)
        files = await index.index_files
        if not files:
            raise RuntimeError(
                f"{name!r} projesinin indeksi boş. Önce paperqa_build_index çağırın."
            )
        docs = Docs()
        meta_map: dict[str, dict[str, Any]] = {}
        try:
            manifest = _manifest_by_location(cfg)
        except Exception:  # noqa: BLE001
            manifest = {}
        for file_location in files:
            saved = await index.get_saved_object(file_location)
            if saved is None:
                continue
            row = manifest.get(file_location)
            if row:
                meta = {
                    "title": row.get("title") or None,
                    "authors": _parse_authors(row.get("authors")) or None,
                    "year": int(row["year"]) if str(row.get("year") or "").isdigit() else None,
                    "journal": row.get("journal") or None,
                    "doi": (row.get("doi") or "").strip().lower() or None,
                }
            else:
                meta = {}
            for dockey in saved.docs:
                meta_map[dockey] = meta
            docs.docs.update(saved.docs)
            docs.texts.extend(saved.texts)
        if not docs.texts:
            raise RuntimeError(f"{name!r} projesinin indeksi metin içermiyor.")
        _docs_cache[name] = docs
        _doc_meta[name] = meta_map
        return docs


def _page_range(name: str) -> str:
    match = re.search(r"pages\s+(\d+)(?:\s*-\s*(\d+))?", name)
    if not match:
        return ""
    if match.group(2) and match.group(2) != match.group(1):
        return f"{match.group(1)}-{match.group(2)}"
    return match.group(1)


def _text_payload(name: str, text: Any, rank: int, max_chars: int) -> dict[str, Any]:
    doc = text.doc
    meta = _doc_meta.get(name, {}).get(getattr(doc, "dockey", ""), {})
    return {
        "rank": rank,
        "pages": _page_range(text.name),
        "title": meta.get("title") or getattr(doc, "title", None),
        "authors": meta.get("authors") or getattr(doc, "authors", None),
        "year": meta.get("year") or getattr(doc, "year", None),
        "journal": meta.get("journal") or getattr(doc, "journal", None),
        "doi": meta.get("doi") or getattr(doc, "doi", None),
        "citation": getattr(doc, "citation", None),
        "text": text.text[:max_chars],
    }


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was",
    "were", "have", "has", "had", "not", "but", "can", "could", "should",
    "would", "their", "they", "them", "who", "whom", "which", "what",
    "when", "where", "why", "how", "into", "than", "then", "also", "such",
}


def _lexical_payloads(
    name: str,
    docs: Any,
    query: str,
    limit: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    """Keyword fallback for chunks the embedding index ranks poorly.

    Rare query terms get more weight than ubiquitous ones, and exact bigrams
    (e.g. ``risky behavior``) get a bonus, so table-heavy or boilerplate chunks
    do not outrank the substantive paragraph.
    """
    words = [
        token
        for token in re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{4,}", query.lower())
        if token not in _STOPWORDS
    ]
    tokens = set(words)
    if not tokens:
        return []
    texts = list(docs.texts)
    total = max(1, len(texts))
    df = {
        token: sum(1 for text in texts if token in text.text.lower())
        for token in tokens
    }
    weights = {
        token: math.log((total + 1) / (df[token] + 1)) + 1.0
        for token in tokens
    }
    bigrams = {
        f"{words[i]} {words[i + 1]}"
        for i in range(len(words) - 1)
        if words[i] != words[i + 1]
    }
    scored: list[tuple[float, Any]] = []
    for text in texts:
        body = text.text.lower()
        score = sum(weights[token] for token in tokens if token in body)
        score += sum(3.0 for bigram in bigrams if bigram in body)
        if score < 3 or _looks_like_backmatter(text.text):
            continue
        scored.append((score, text))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    payloads: list[dict[str, Any]] = []
    for rank, (score, text) in enumerate(scored[:limit], start=1):
        payload = _text_payload(name, text, rank, max_chars)
        payload["lexical_score"] = score
        payloads.append(payload)
    return payloads


def _looks_like_references(text: str) -> bool:
    """Heuristic filter for reference-list chunks returned by semantic search."""
    head = text[:600].lower()
    year_hits = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
    doi_hits = len(re.findall(r"\bdoi\b|https?://", text, flags=re.IGNORECASE))
    if "references" in head and year_hits >= 4:
        return True
    return year_hits >= 14 and doi_hits >= 2


def _looks_like_backmatter(text: str) -> bool:
    """Filter reference lists, affiliation blocks and journal boilerplate.

    Semantic search sometimes ranks author affiliations, reference lists or
    publisher footers above substantive paragraphs.  These chunks are useless
    as evidence even when lexically close to the query.
    """
    low = text.lower()
    tokens = text.split()
    numeric_ratio = sum(1 for token in tokens if any(ch.isdigit() for ch in token)) / max(1, len(tokens))
    digit_ratio = sum(1 for ch in text if ch.isdigit()) / max(1, len(text))
    if numeric_ratio >= 0.30 or digit_ratio >= 0.16:
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    short_numeric = sum(
        1 for line in lines
        if len(line.split()) <= 2 and any(ch.isdigit() for ch in line)
    )
    if lines and short_numeric / len(lines) >= 0.35:
        return True
    stats_hits = len(re.findall(r"\b(?:CFI|RMSEA|TLI|SRMR)\b|p\s*[<=]|γ\s*=|β\s*=", text, re.IGNORECASE))
    if stats_hits >= 4:
        return True
    # Correlation/mean tables: many "0.60 (0.06)"-style cells.
    if len(re.findall(r"\d+\.\d+\s*\(\s*\d+\.\d+\s*\)", text)) >= 6:
        return True
    head = low[:300]
    # Abstract/introduction/method chunks often also contain a reference block
    # at the end; keep them because the prose is still usable evidence.
    if any(marker in head for marker in ("abstract", "introduction", "methods", "results", "discussion", "conclusion")):
        return False
    if _looks_like_references(text):
        return True
    affiliation_hits = (
        low.count("department of")
        + low.count("university")
        + low.count("faculty of")
    )
    contact_hits = low.count("@") + low.count("corresponding author") + low.count("e-mail")
    if affiliation_hits >= 5 or (affiliation_hits >= 3 and contact_hits >= 1):
        return True
    year_hits = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
    doi_hits = len(re.findall(r"\bdoi\b|https?://", text, flags=re.IGNORECASE))
    if year_hits >= 15:
        return True
    if year_hits >= 8 and doi_hits >= 10:
        return True
    if year_hits >= 8 and doi_hits >= 3:
        return True
    return False


# --------------------------------------------------------------------------- #
# Tools: proje kaydı
# --------------------------------------------------------------------------- #

@mcp.tool()
async def paperqa_projects() -> dict[str, Any]:
    """Kayıtlı projeleri durumlarıyla listeler (izole PDF klasörü + manifest + indeks)."""
    registry = _load_registry()
    projects = [
        _project_summary(name, cfg)
        for name, cfg in sorted((registry.get("projects") or {}).items())
    ]
    return {
        "registry": str(REGISTRY_PATH),
        "count": len(projects),
        "projects": projects,
        "notes": [
            "Her proje kendi manifesti ve indeksiyle izole çalışır.",
            "paperqa_search/read_pages/ask çağrılarında project adı zorunludur.",
        ],
    }


@mcp.tool()
async def paperqa_register_project(
    name: str,
    paper_directory: str,
    title: str | None = None,
    description: str | None = None,
    include_subdirectories: bool = False,
    include_files_without_doi: bool = False,
    refresh_manifest: bool = False,
    enrich_metadata: bool = True,
    index_directory: str | None = None,
    index_name: str | None = None,
) -> dict[str, Any]:
    """Bir PDF klasörünü izole proje olarak kaydeder ve manifest CSV üretir.

    - DOI, dosya adından (``10.1007s...pdf`` gibi) veya ilk iki sayfadan algılanır.
    - Metadata Crossref (yedek: OpenAlex) ile zenginleştirilir; API anahtarı gerekmez.
    - Mevcut manifest ``refresh_manifest=True`` verilmedikçe korunur.
    - DOI'si olmayan dosyalar varsayılan olarak manifeste alınmaz
      (``include_files_without_doi=True`` ile dahil edilir).
    - İndeks kurmak ayrı bir adımdır: ``paperqa_build_index``.
    """
    name = (name or "").strip()
    if not PROJECT_NAME_RE.match(name):
        raise ValueError(
            "Proje adı 2-61 karakter olmalı ve yalnızca harf, rakam, '.', '_', '-' içermelidir."
        )
    directory = Path(paper_directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"Klasör bulunamadı: {directory}")
    pdfs = _scan_pdfs(directory, include_subdirectories)
    if not pdfs:
        raise ValueError(f"Klasörde PDF yok: {directory}")

    registry = _load_registry(force=True)
    projects = registry.setdefault("projects", {})
    existing = projects.get(name) or {}
    manifest = (
        Path(existing["manifest"]).expanduser()
        if existing.get("manifest")
        else DEFAULT_PROJECTS_ROOT / name / "manifest.csv"
    )
    build_manifest = refresh_manifest or not existing.get("manifest") or not manifest.exists()

    rows: list[dict[str, Any]] = []
    skipped_no_doi: list[str] = []
    if build_manifest:
        for path in pdfs:
            rel = path.relative_to(directory).as_posix()
            probe = await asyncio.to_thread(_pdf_probe, path)
            doi, _validated = await _resolve_doi_for_pdf(path, probe)
            if not doi and not include_files_without_doi:
                skipped_no_doi.append(rel)
                continue
            row = {
                "file_location": rel,
                "doi": doi,
                "title": probe.get("title") or path.stem,
                "journal": "",
                "year": "",
                "authors": "",
            }
            if doi and enrich_metadata:
                meta = await _enrich(doi)
                for key in ("title", "journal", "year", "authors"):
                    value = meta.get(key)
                    if key == "authors":
                        row[key] = json.dumps(value, ensure_ascii=False) if value else ""
                    elif value:
                        row[key] = value
            rows.append(row)
        _write_manifest(manifest, rows)
    else:
        rows = _read_manifest(existing)

    entry = {
        **(existing or {}),
        "title": title or existing.get("title") or name,
        "description": description or existing.get("description") or "",
        "paper_directory": str(directory),
        "include_subdirectories": bool(include_subdirectories),
        "manifest": str(manifest),
        "index_directory": str(
            Path(index_directory).expanduser()
            if index_directory
            else existing.get("index_directory") or DEFAULT_INDEX_ROOT
        ),
        "index_name": index_name or existing.get("index_name") or name,
        "output_directory": existing.get("output_directory"),
        "analysis_json": existing.get("analysis_json"),
        "created_at": existing.get("created_at") or _now(),
        "updated_at": _now(),
    }
    projects[name] = entry
    _save_registry(registry)

    return {
        "registered": name,
        "paper_directory": str(directory),
        "pdf_files": len(pdfs),
        "manifest": str(manifest),
        "manifest_built": build_manifest,
        "manifest_rows": len(rows),
        "skipped_no_doi": skipped_no_doi,
        "index": {
            "index_name": entry["index_name"],
            "index_directory": entry["index_directory"],
            "next_step": f"paperqa_build_index(project='{name}')",
        },
        "notes": [
            "Her proje ayrı manifest ve ayrı indeks kullanır; projeler karışmaz.",
            "DOI'si olmayan dosyalar varsayılan olarak dışarıda bırakıldı.",
        ],
    }


@mcp.tool()
async def paperqa_build_index(project: str, rebuild: bool = False) -> dict[str, Any]:
    """Projenin indeksini manifest üyeliğine göre kurar/günceller.

    - İndekse yalnızca manifestteki dosyalar girer (klasör taraması değil).
    - ``rebuild=True`` proje indeks klasörünü silip sıfırdan kurar.
    - Diğer projelerin indekslerine dokunulmaz.
    """
    name = (project or "").strip()
    cfg = _project_config(name)
    directory = _paper_directory(cfg)
    if not directory.is_dir():
        raise ValueError(f"Proje klasörü yok: {directory}")
    rows = _read_manifest(cfg)
    if not rows:
        raise ValueError(f"{name!r} manifesti boş: {_manifest_path(cfg)}")

    index_root = Path(cfg["index_directory"]).expanduser() / cfg["index_name"]
    if rebuild and index_root.exists():
        shutil.rmtree(index_root)

    settings = _settings_for(name, cfg)
    index = _search_index(cfg)
    existing = dict(await index.index_files)
    target = {row["file_location"] for row in rows}

    removed: list[str] = []
    for extra in sorted(set(existing) - target):
        await index.remove_from_index(extra)
        removed.append(extra)

    added: list[str] = []
    unchanged: list[str] = []
    missing: list[str] = []
    failed: list[dict[str, str]] = []
    for row in rows:
        rel = row["file_location"]
        path = directory / rel
        if not path.is_file():
            missing.append(rel)
            continue
        if await index.filecheck(rel):
            unchanged.append(rel)
            continue
        try:
            tmp_docs = Docs()
            await tmp_docs.aadd(
                path=path,
                citation=_citation_for_row(rel, row),
                settings=settings,
                file_location=rel,
            )
            body = "".join(t.text for t in tmp_docs.texts)
            await index.add_document(
                {
                    "title": row.get("title") or Path(rel).name,
                    "year": str(row.get("year") or "Unknown year"),
                    "file_location": rel,
                    "body": body,
                },
                document=tmp_docs,
            )
            added.append(rel)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Index build failed for %s", rel)
            failed.append({"file": rel, "error": str(exc)})
            await index.mark_failed_document(rel)

    if index.changed:
        await index.save_index()

    _docs_cache.pop(name, None)
    _doc_meta.pop(name, None)

    return {
        "project": name,
        "index_name": cfg["index_name"],
        "index_directory": str(index_root),
        "rebuilt": rebuild,
        "manifest_rows": len(rows),
        "added": added,
        "unchanged": unchanged,
        "removed_not_in_manifest": removed,
        "missing_files": missing,
        "failed": failed,
        "indexed_files_total": len(await index.index_files),
        "notes": [
            "İndeks üyeliği manifest ile sabitlendi; klasördeki fazladan PDF'ler alınmaz.",
            "Arama/okuma araçları yalnızca bu projenin indeksini görür.",
        ],
    }


# --------------------------------------------------------------------------- #
# Tools: durum / arama / okuma / soru
# --------------------------------------------------------------------------- #

@mcp.tool()
async def paperqa_status(project: str) -> dict[str, Any]:
    """Bir projenin indeks durumunu (dosya, doküman, metin parçası) döndürür."""
    name = (project or "").strip()
    cfg = _project_config(name)
    index = _search_index(cfg)
    files = await index.index_files
    documents = 0
    chunks = 0
    try:
        docs = await _load_docs(name, cfg)
        documents = len(docs.docs)
        chunks = len(docs.texts)
    except RuntimeError:
        pass
    return {
        "project": name,
        "index_name": cfg["index_name"],
        "index_directory": str(Path(cfg["index_directory"]).expanduser() / cfg["index_name"]),
        "paper_directory": cfg["paper_directory"],
        "manifest": cfg["manifest"],
        "indexed_files": len(files),
        "documents": documents,
        "text_chunks": chunks,
        "embedding": EMBEDDING,
        "llm": LOCAL_LLM,
        "files": sorted(files),
    }


@mcp.tool()
async def paperqa_search(
    project: str,
    query: str,
    k: int = 6,
    max_chars: int = 1600,
) -> dict[str, Any]:
    """Proje içinde semantik arama (yalnızca o projenin indeksi; LLM çağrılmaz).

    Kanıt ve sayfa aralığı bulmak için kullanın; önemli alıntıları
    ``paperqa_read_pages`` ile doğrulayın.
    """
    name = (project or "").strip()
    cfg = _project_config(name)
    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")
    k = max(1, min(int(k), 20))
    max_chars = max(300, min(int(max_chars), 6000))
    docs = await _load_docs(name, cfg)
    settings = _settings_for(name, cfg)
    fetch_k = min(max(k * 4, 12), 40)
    matches = await docs.retrieve_texts(query, k=fetch_k, settings=settings)
    filtered = [match for match in matches if not _looks_like_backmatter(match.text)]
    matches = (filtered or matches)[:k]
    return {
        "project": name,
        "query": query,
        "k": k,
        "results": [
            _text_payload(name, match, rank, max_chars)
            for rank, match in enumerate(matches, start=1)
        ],
    }


@mcp.tool()
async def paperqa_read_pages(
    project: str,
    doi: str,
    page_start: int = 1,
    page_end: int | None = None,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Projedeki bir PDF'ten sayfa metni okur (DOI → manifest eşlemesi).

    Sayfa numaraları 1 tabanlıdır. ``paperqa_search`` sonucundaki alıntıları
    bu araçla doğrulayın. DOI başka bir projede olsa bile burada bulunmaz.
    """
    name = (project or "").strip()
    cfg = _project_config(name)
    doi = (doi or "").strip().lower().removeprefix("https://doi.org/")
    mapping: dict[str, Path] = {}
    for row in _read_manifest(cfg):
        row_doi = (row.get("doi") or "").strip().lower()
        if row_doi:
            mapping[row_doi] = _paper_directory(cfg) / row["file_location"]
    path = mapping.get(doi)
    if path is None:
        raise ValueError(
            f"{name!r} projesinde {doi!r} DOI'sine eşlenmiş PDF yok. "
            "Manifeste eklemek için paperqa_register_project kullanın."
        )
    if not path.exists():
        raise FileNotFoundError(str(path))
    with pymupdf.open(path) as pdf:
        page_count = pdf.page_count
        start = max(1, int(page_start))
        end = min(page_count, int(page_end or page_count))
        pages = []
        for page_number in range(start, end + 1):
            page = pdf.load_page(page_number - 1)
            blocks = page.get_text("blocks", sort=True)
            text = "\n".join(
                block[4] for block in blocks if len(block) > 4 and block[4].strip()
            )
            text = re.sub(r"[ \t]+", " ", text).strip()
            pages.append({"page": page_number, "text": text[:max_chars]})
    return {
        "project": name,
        "doi": doi,
        "path": str(path),
        "page_count": page_count,
        "page_range": [start, end],
        "pages": pages,
    }


@mcp.tool()
async def paperqa_ask(
    project: str,
    question: str,
    evidence_k: int = 3,
    max_sources: int = 3,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Proje indeksi üzerinde yerel Qwen modeline soru sorar (taslak cevap).

    CPU'da yavaştır ve yerel model atıf hatası yapabilir. Cevabı taslak kabul
    edip her iddiayı ``paperqa_search`` veya ``paperqa_read_pages`` ile
    doğrulayın.
    """
    name = (project or "").strip()
    cfg = _project_config(name)
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty")
    docs = await _load_docs(name, cfg)
    settings = _settings_for(name, cfg)
    settings.answer.evidence_k = max(1, min(int(evidence_k), 8))
    settings.answer.answer_max_sources = max(1, min(int(max_sources), 5))
    settings.answer.evidence_skip_summary = True
    settings.answer.max_concurrent_requests = 1

    async def run() -> Any:
        return await docs.aquery(question, settings=settings)

    try:
        session = await asyncio.wait_for(
            run(), timeout=max(30, min(int(timeout_seconds), 600))
        )
    except TimeoutError:
        return {
            "project": name,
            "question": question,
            "error": "local model timed out",
            "timeout_seconds": timeout_seconds,
        }
    return {
        "project": name,
        "question": question,
        "answer": session.answer,
        "contexts": [
            {
                "pages": _page_range(context.text.name),
                "doi": getattr(context.text.doc, "doi", None),
                "title": getattr(context.text.doc, "title", None),
                "text": context.context[:1600],
            }
            for context in session.contexts
        ],
        "warning": (
            "Local model answer; verify every claim against paperqa_search "
            "or paperqa_read_pages."
        ),
    }


if __name__ == "__main__":
    mcp.run()
