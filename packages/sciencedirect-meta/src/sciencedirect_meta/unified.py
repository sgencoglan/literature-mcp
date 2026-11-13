"""Single MCP server: DOI discovery + local full-text research tools.

This module combines the six tools from ``sciencedirect_meta.server`` with the
thirteen project-aware tools from ``sciencedirect_meta.local_research``.  One process,
one MCP connection, no duplicate servers.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from sciencedirect_meta import local_research as local
from sciencedirect_meta import platform_search
from sciencedirect_meta import server as metadata

server = Server("literature")

METADATA_TOOLS = {
    "search_sciencedirect",
    "search_pubmed",
    "search_europepmc",
    "search_semantic_scholar",
    "search_arxiv",
    "search_clinicaltrials",
    "search_all",
    "get_article",
    "get_links",
    "search_diagnostics",
}

LOCAL_TOOLS = {
    "list_projects",
    "project_audit",
    "search_literature",
    "deep_research",
    "verify_doi_and_publisher",
    "doi_provenance",
    "read_paper",
    "compare_studies",
    "evidence_check",
    "export_review",
    "journal_rank",
    "analysis_updates",
    "library_status",
}


def platform_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name="prepare_platform_search",
            description="Prepare site: web-search tasks for the host model across medical/psychiatry publishers. Includes unrestricted searches first. Does not execute searches; use the host's web tool, record the actual engine, and preserve books/new/low-citation sources to minimize missed publications.",
            inputSchema={
                "type": "object",
                "required": ["topic"],
                "properties": {
                    "topic": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "query_variants": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(platform_search.PLATFORMS)},
                    },
                    "exact_title": {"type": "boolean", "default": False},
                },
            },
        ),
        types.Tool(
            name="collect_platform_results",
            description="Consolidate real host-model web-search runs against a prepared platform plan. Returns records, per-query coverage, missing searches and source sightings. Source domain is not an indexing/quality check. Feed records into the literature coverage audit and present citations with the actual reading level.",
            inputSchema={
                "type": "object",
                "required": ["plan", "runs"],
                "properties": {
                    "plan": {"type": "object"},
                    "runs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["task_id", "status", "engine", "searched_at"],
                            "properties": {
                                "task_id": {"type": "string"},
                                "status": {
                                    "enum": [
                                        "ok",
                                        "partial",
                                        "error",
                                        "rate_limited",
                                        "unavailable",
                                    ]
                                },
                                "engine": {"type": "string", "minLength": 1},
                                "searched_at": {"type": "string", "minLength": 1},
                                "note": {"type": "string"},
                            "retry_after_seconds": {"type": "number", "minimum": 0},
                                "results": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["title", "url"],
                                        "properties": {
                                            "title": {"type": "string"},
                                            "url": {"type": "string"},
                                            "doi": {"type": "string"},
                                            "year": {"type": "integer"},
                                            "publication_type": {"type": "string"},
                                            "excerpt": {"type": "string"},
                                            "abstract": {"type": "string"},
                                            "read_level": {
                                                "enum": [
                                                    "metadata",
                                                    "snippet",
                                                    "abstract",
                                                    "fulltext",
                                                ]
                                            },
                                            "relevance_note": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        ),
    ]


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return await metadata.handle_list_tools() + await local.handle_list_tools() + platform_tools()


@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: Optional[Dict[str, Any]],
) -> List[types.TextContent]:
    if name in {"prepare_platform_search", "collect_platform_results"}:
        try:
            function = getattr(platform_search, name)
            result = function(**(arguments or {}))
        except (ValueError, TypeError, KeyError, AttributeError):
            result = {
                "error": "Geçersiz platform arama girdisi; araç şemasını ve görev kimliklerini kontrol edin."
            }
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    if name in METADATA_TOOLS:
        return await metadata.handle_call_tool(name, arguments)
    if name in LOCAL_TOOLS:
        return await local.handle_call_tool(name, arguments)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False),
        )
    ]


async def _run() -> None:
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await metadata._client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
