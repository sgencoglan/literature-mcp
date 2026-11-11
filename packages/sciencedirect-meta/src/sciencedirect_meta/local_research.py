"""Local research tools, exposed by the unified MCP.

This module is a facade. The implementation is split into focused
modules so no single file carries search, PDF handling, auditing and MCP
schemas at once. Every name that used to live here is re-exported,
so ``local_research.read_paper`` and friends keep working.
"""

from __future__ import annotations

from sciencedirect_meta._common import (  # noqa: F401
    _DOI_RE,
    _PROJECTS_CACHE,
    AVAILABLE_SOURCES,
    DEFAULT_SOURCES,
    _authors_short,
    _clean_doi,
    _error,
    _escape_md,
    _iso_now,
    _json_text,
    _safe_slug,
    _split_sentences,
    _strip_html,
    logger,
)
from sciencedirect_meta._crossref import (  # noqa: F401
    _crossref_cache,
    _crossref_paper,
    _crossref_sem,
    _metadata_for,
    crossref_work,
    doi_provenance,
    search_crossref,
)
from sciencedirect_meta._evidence import (  # noqa: F401
    _DESIGN_PATTERNS,
    _LIMITATION_KEYWORDS,
    _RESULT_KEYWORDS,
    _STOPWORDS,
    _best_sentences,
    _compare_one,
    _cosine,
    _extract_design,
    _extract_sample,
    _review_csv,
    _review_markdown,
    _study_text,
    _tokens,
    _vectorize_sentences,
    _verdict,
    compare_studies,
    evidence_check,
    export_review,
)
from sciencedirect_meta._journals import (  # noqa: F401
    _JOURNAL_RANK_CACHE,
    JOURNAL_RANK_YEAR,
    _attach_quartiles,
    _find_journal_rank,
    _load_journal_rank_data,
    _normalize_journal_title,
    _parse_scimago_categories,
    _parse_scimago_number,
    journal_rank,
)
from sciencedirect_meta._library import (  # noqa: F401
    _LIBRARY_CACHE,
    _TITLE_STOPWORDS,
    _annotate_local_pdfs,
    _extract_pdf_pages,
    _first_page_metadata,
    _library_scan,
    _match_local_pdf,
    _normalize_token,
    _title_similarity,
    _title_tokens,
    analysis_updates,
    library_status,
    list_projects,
    project_audit,
    read_paper,
)
from sciencedirect_meta._mcp_tools import (  # noqa: F401
    handle_call_tool,
    handle_list_tools,
)
from sciencedirect_meta._projects import (  # noqa: F401
    _apply_project_setup,
    _citation_band,
    _doi_candidates_from_filename,
    _openalex_flags,
    _openalex_flags_cache,
    _project_analysis_path,
    _project_config,
    _project_scope,
    _project_setup_root,
    _projects_registry,
    _resolve_filename_doi,
)
from sciencedirect_meta._search import (  # noqa: F401
    _research_plan,
    deep_research,
    search_literature,
    verify_doi_and_publisher,
)

__all__ = [
    "AVAILABLE_SOURCES",
    "DEFAULT_SOURCES",
    "JOURNAL_RANK_YEAR",
    "analysis_updates",
    "compare_studies",
    "crossref_work",
    "deep_research",
    "doi_provenance",
    "evidence_check",
    "export_review",
    "handle_call_tool",
    "handle_list_tools",
    "journal_rank",
    "library_status",
    "list_projects",
    "logger",
    "project_audit",
    "read_paper",
    "search_crossref",
    "search_literature",
    "verify_doi_and_publisher",
]

# --- Tunable settings live in one place ------------------------------------ #
# The implementation modules read these through ``_common`` so a caller (or a
# test) can retarget them at runtime. Without this forwarding, assigning
# ``local_research.PAPER_LIBRARY_DIR`` would only change a copy on the facade
# and the tools would keep using the old value.
import sys as _sys  # noqa: E402
import types as _types  # noqa: E402

from sciencedirect_meta import _common as _common  # noqa: E402

_TUNING = frozenset(
    {
        "PAPER_LIBRARY_DIR",
        "REVIEW_OUTPUT_DIR",
        "PDF_MAX_PAGES",
        "READ_MAX_CHARS",
        "JOURNAL_RANK_PATH",
        "ANALYSIS_UPDATES_PATH",
        "LIT_PROJECTS_REGISTRY",
    }
)


# Captured before anyone can patch them, so deleting a patched attribute
# (``mock.patch.object`` restores by deleting) returns to the shipped default
# instead of leaking the test's temporary value into later calls.
_DEFAULTS = {name: getattr(_common, name) for name in _TUNING}


class _FacadeModule(_types.ModuleType):
    def __getattr__(self, name: str):
        if name in _TUNING:
            return getattr(_common, name)
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value) -> None:
        if name in _TUNING:
            setattr(_common, name, value)
            return
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in _TUNING:
            setattr(_common, name, _DEFAULTS[name])
            return
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _FacadeModule
