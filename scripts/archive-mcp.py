#!/usr/bin/env python3
"""MCP server (stdio transport) exposing archive read tools to Claude Code.

Used by Claude Code in VS Code/CLI as a local stdio MCP server.
For remote MCP (Claude App, ChatGPT App), see mcp-http-server/ on the new-features branch.

Required env vars:
    ARCHIVE_URL          e.g. https://claude.hangocthanh.io.vn/archive
    ARCHIVE_AUTH_TOKEN   bearer token (matches VPS .env)
    USER_ID              default "thanh"

Register with Claude Code:
    claude mcp add --scope user --transport stdio archive \\
        --env ARCHIVE_URL=... \\
        --env ARCHIVE_AUTH_TOKEN=... \\
        --env USER_ID=thanh \\
        -- python3 ~/scripts/archive-mcp.py
"""
import os
import asyncio
import json
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

ARCHIVE_URL = os.environ["ARCHIVE_URL"]
TOKEN = os.environ["ARCHIVE_AUTH_TOKEN"]
USER_ID = os.environ.get("USER_ID", "thanh")
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

server = Server("archive")


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="list_old_sessions",
            description="List archived chat sessions by project and date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_tag": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        ),
        Tool(
            name="get_session_summary",
            description=(
                "Get compact view: metadata + first/last 5 messages. "
                "USE THIS instead of get_old_session for most cases."
            ),
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="get_old_session",
            description=(
                "Fetch FULL transcript. WARNING: very large response. "
                "Prefer get_session_summary for overview."
            ),
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="search_old_sessions",
            description="Search archived sessions by keyword in their summary.",
            inputSchema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name, args):
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as c:
        if name == "list_old_sessions":
            r = await c.get(
                f"{ARCHIVE_URL}/sessions",
                params={"user_id": USER_ID, **args},
            )
            return [TextContent(type="text", text=r.text)]
        elif name == "get_session_summary":
            r = await c.get(f"{ARCHIVE_URL}/sessions/{args['session_id']}")
            data = r.json()
            transcript = data.get("transcript", [])
            compact = {
                "id": data["id"],
                "started_at": data["started_at"],
                "ended_at": data["ended_at"],
                "project_tag": data.get("project_tag"),
                "summary": data.get("summary"),
                "message_count": data["message_count"],
                "first_messages": transcript[:5],
                "last_messages": (
                    transcript[-5:] if len(transcript) > 5 else []
                ),
            }
            return [TextContent(
                type="text",
                text=json.dumps(compact, ensure_ascii=False, indent=2),
            )]
        elif name == "get_old_session":
            r = await c.get(f"{ARCHIVE_URL}/sessions/{args['session_id']}")
            return [TextContent(type="text", text=r.text)]
        elif name == "search_old_sessions":
            r = await c.get(
                f"{ARCHIVE_URL}/sessions",
                params={"user_id": USER_ID, "q": args["q"], "limit": 20},
            )
            return [TextContent(type="text", text=r.text)]
        else:
            return [TextContent(type="text", text=f"unknown tool {name}")]


async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
