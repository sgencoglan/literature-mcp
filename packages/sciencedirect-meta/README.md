# sciencedirect-meta MCP

API-key-free literature metadata and local full-text tools exposed as one MCP
server. It uses open metadata sources and never scrapes ScienceDirect, bypasses
paywalls, or downloads PDFs.

> Turkish documentation for the overall workflow lives in
> [`../../docs/`](../../docs/). This package README is the installation and tool
> reference.

## What it does

- Searches OpenAlex, PubMed, Europe PMC, and Crossref.
- Resolves Elsevier PII links through Crossref when possible.
- Verifies DOIs and reports publisher/provenance metadata.
- Looks up SCImago 2024 journal quartiles from a local CSV.
- Reads PDFs that the user has placed in a local project folder.
- Builds lexical evidence tables and exports Markdown/CSV/JSON reports.
- Reads an optional, project-specific citation-audit JSON file.

It does **not** call an LLM. `evidence_check` is lexical TF-IDF matching, not
semantic entailment.

## Tools (19)

### Search and metadata

`search_sciencedirect`, `search_pubmed`, `search_europepmc`, `search_all`,
`search_literature`, `deep_research`, `get_article`, `get_links`.

### Verification and ranking

`verify_doi_and_publisher`, `doi_provenance`, `journal_rank`.

### Projects and local full text

`list_projects`, `project_audit`, `read_paper`, `compare_studies`,
`evidence_check`, `library_status`, `analysis_updates`, `export_review`.

The machine-readable catalog, including JSON input schemas, is at
[`../../docs/tool-catalog.json`](../../docs/tool-catalog.json).

## Install

```bash
cd packages/sciencedirect-meta
python3 -m venv .venv
.venv/bin/pip install -e .
```

Python 3.10+ is required. Dependencies: `mcp`, `httpx`, `PyMuPDF`.

## Journal rank data

The `journal_rank` tool expects a local SCImago CSV. Download it once:

```bash
bash ../../scripts/fetch_scimago.sh
```

Or point to an existing file:

```bash
export JOURNAL_RANK_CSV="$HOME/data/scimagojr_2024.csv.gz"
```

The repository does not redistribute the SCImago dataset. See
[`data/README.md`](data/README.md) for source and license notes.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PAPER_LIBRARY_DIR` | `~/Downloads/papers` | Fallback PDF folder |
| `REVIEW_OUTPUT_DIR` | `~/Downloads/reviews` | Report output folder |
| `ANALYSIS_UPDATES_JSON` | `data/analysis_updates.json` | Optional audit file |
| `JOURNAL_RANK_CSV` | `data/scimagojr_2024.csv.gz` | SCImago CSV |
| `LIT_PROJECTS_REGISTRY` | `~/.literature-mcp/projects.json` | Shared project registry |
| `CROSSREF_MAILTO` | `research@example.org` | Crossref polite-pool contact |

`PAPER_LIBRARY_DIR` is only a fallback. Prefer explicit `project=...` calls so
that searches stay isolated.

## MCP configuration

```json
{
  "mcp": {
    "servers": {
      "sciencedirect-meta": {
        "type": "local",
        "command": ["/path/to/literature-mcp/packages/sciencedirect-meta/.venv/bin/sciencedirect-meta-mcp"],
        "environment": {
          "CROSSREF_MAILTO": "you@example.org",
          "PAPER_LIBRARY_DIR": "/home/you/Downloads/papers",
          "REVIEW_OUTPUT_DIR": "/home/you/Downloads/reviews",
          "JOURNAL_RANK_CSV": "/path/to/literature-mcp/packages/sciencedirect-meta/data/scimagojr_2024.csv.gz",
          "LIT_PROJECTS_REGISTRY": "/home/you/.literature-mcp/projects.json"
        }
      }
    }
  }
}
```

See [`../../config/opencode.example.json`](../../config/opencode.example.json)
for a two-server example.

## Project isolation

The server shares `projects.json` with `paperqa-local`. Each project has its own
PDF folder, manifest CSV, and PaperQA2 index. When `project=...` is supplied,
local text tools only read that project's folder. Without it, the legacy
`PAPER_LIBRARY_DIR` behavior is used for backward compatibility.

## Tests

```bash
cd packages/sciencedirect-meta
.venv/bin/python -m unittest discover -s tests -v
```

## Limitations

- No PDF download, no paywall bypass, no access-control circumvention.
- ScienceDirect pages may return 403 to bots; links should be opened in a browser.
- OpenAlex may lack abstracts for some records.
- `evidence_check` is a lexical pre-screen, not proof.
- Publisher link priority covers Ovid LWW, ScienceDirect, SpringerLink, Wiley,
  and Taylor & Francis only.
- Crossref may rate-limit; the server applies caching and backoff.

## License

MIT. See [`../../LICENSE`](../../LICENSE).
