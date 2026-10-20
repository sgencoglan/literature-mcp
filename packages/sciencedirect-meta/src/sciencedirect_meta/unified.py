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
from sciencedirect_meta import server as metadata

server = Server("literature")

METADATA_TOOLS = {
    "search_sciencedirect",
    "search_pubmed",
    "search_europepmc",
    "search_all",
    "get_article",
    "get_links",
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


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return await metadata.handle_list_tools() + await local.handle_list_tools()


@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: Optional[Dict[str, Any]],
) -> List[types.TextContent]:
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
