"""Archive MCP tools - tich hop vao cung server voi mem0.

Goi HTTP toi Archive API tren VPS (FastAPI service chay phia sau Caddy
tai duong dan /archive/*). Endpoints tuong duong plan trien khai Buoc 7.

Cac env var can co (neu thieu ARCHIVE_URL thi register_archive_tools()
KHONG dang ky tool nao - server van chay binh thuong voi mem0 only):

    ARCHIVE_URL          (e.g. https://claude.hangocthanh.io.vn/archive)
    ARCHIVE_AUTH_TOKEN   (bearer token cho FastAPI)
    USER_ID              (default 'thanh', dung de filter sessions)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)


def _archive_enabled() -> bool:
    """True if ARCHIVE_URL is set in env - guard for register_archive_tools."""
    return bool(os.environ.get("ARCHIVE_URL", "").strip())


def _get_headers() -> dict[str, str]:
    token = os.environ.get("ARCHIVE_AUTH_TOKEN", "").strip()
    if not token:
        # Allow unauthenticated calls if user has not set token (Caddy may handle it)
        return {}
    return {"Authorization": f"Bearer {token}"}


def _get_user_id() -> str:
    return os.environ.get("USER_ID", "thanh").strip() or "thanh"


def _get_archive_url() -> str:
    return os.environ["ARCHIVE_URL"].rstrip("/")


def register_archive_tools(mcp: FastMCP) -> None:
    """Register 4 archive tools onto an existing FastMCP instance.

    Call this AFTER mem0 tools are registered, so all show up in one
    'tools/list' response. No-op if ARCHIVE_URL not set in env.
    """
    if not _archive_enabled():
        logger.info("[ARCHIVE] ARCHIVE_URL not set - skipping archive tool registration")
        return

    archive_url = _get_archive_url()
    logger.info("[ARCHIVE] Registering 4 archive tools, target=%s", archive_url)

    @mcp.tool()
    def list_old_sessions(
        project_tag: Annotated[str | None, Field(description="Filter by project tag.")] = None,
        date_from: Annotated[str | None, Field(description="ISO date YYYY-MM-DD.")] = None,
        date_to: Annotated[str | None, Field(description="ISO date YYYY-MM-DD.")] = None,
        limit: Annotated[int, Field(description="Max results.")] = 50,
    ) -> str:
        """List archived chat sessions by project and date range."""
        t0 = time.perf_counter()
        params: dict[str, Any] = {"user_id": _get_user_id(), "limit": limit}
        if project_tag:
            params["project_tag"] = project_tag
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        logger.info("[ARCHIVE] list_old_sessions params=%s", params)
        try:
            with httpx.Client(timeout=30, headers=_get_headers()) as c:
                r = c.get(f"{_get_archive_url()}/sessions", params=params)
                logger.info("[ARCHIVE] list_old_sessions status=%d in %.2fs",
                            r.status_code, time.perf_counter() - t0)
                return r.text
        except Exception as exc:
            logger.error("[ARCHIVE] list_old_sessions FAIL: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    @mcp.tool()
    def get_session_summary(
        session_id: Annotated[str, Field(description="Session UUID.")],
    ) -> str:
        """Get compact view of an archived session: metadata + first/last 5 messages.

        USE THIS instead of get_old_session for most cases - response is much smaller.
        """
        t0 = time.perf_counter()
        logger.info("[ARCHIVE] get_session_summary session_id=%s", session_id)
        try:
            with httpx.Client(timeout=30, headers=_get_headers()) as c:
                r = c.get(f"{_get_archive_url()}/sessions/{session_id}")
                logger.info("[ARCHIVE] get_session_summary status=%d in %.2fs",
                            r.status_code, time.perf_counter() - t0)
                if r.status_code != 200:
                    return r.text
                data = r.json()
                transcript = data.get("transcript", []) or []
                compact = {
                    "id": data.get("id"),
                    "started_at": data.get("started_at"),
                    "ended_at": data.get("ended_at"),
                    "project_tag": data.get("project_tag"),
                    "summary": data.get("summary"),
                    "message_count": data.get("message_count"),
                    "first_messages": transcript[:5],
                    "last_messages": transcript[-5:] if len(transcript) > 5 else [],
                }
                return json.dumps(compact, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("[ARCHIVE] get_session_summary FAIL: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    @mcp.tool()
    def get_old_session(
        session_id: Annotated[str, Field(description="Session UUID.")],
    ) -> str:
        """Fetch FULL transcript of an archived session.

        WARNING: response can be very large. Prefer get_session_summary for overview.
        """
        t0 = time.perf_counter()
        logger.info("[ARCHIVE] get_old_session session_id=%s", session_id)
        try:
            with httpx.Client(timeout=60, headers=_get_headers()) as c:
                r = c.get(f"{_get_archive_url()}/sessions/{session_id}")
                logger.info("[ARCHIVE] get_old_session status=%d in %.2fs len=%d",
                            r.status_code, time.perf_counter() - t0, len(r.text))
                return r.text
        except Exception as exc:
            logger.error("[ARCHIVE] get_old_session FAIL: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    @mcp.tool()
    def search_old_sessions(
        q: Annotated[str, Field(description="Search query.")],
        limit: Annotated[int, Field(description="Max results.")] = 20,
    ) -> str:
        """Search archived sessions by keyword in their summary."""
        t0 = time.perf_counter()
        params = {"user_id": _get_user_id(), "q": q, "limit": limit}
        logger.info("[ARCHIVE] search_old_sessions q=%r", q)
        try:
            with httpx.Client(timeout=30, headers=_get_headers()) as c:
                r = c.get(f"{_get_archive_url()}/sessions", params=params)
                logger.info("[ARCHIVE] search_old_sessions status=%d in %.2fs",
                            r.status_code, time.perf_counter() - t0)
                return r.text
        except Exception as exc:
            logger.error("[ARCHIVE] search_old_sessions FAIL: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    @mcp.tool()
    def list_compact_summaries(
        project_tag: Annotated[str | None, Field(description="Filter by project.")] = None,
        date_from: Annotated[str | None, Field(description="ISO date YYYY-MM-DD.")] = None,
        date_to: Annotated[str | None, Field(description="ISO date YYYY-MM-DD.")] = None,
        limit: Annotated[int, Field(description="Max results.")] = 50,
    ) -> str:
        """List compact summaries (output of /compact in Claude Code).

        PREFERRED tool for 'what did I discuss about X' queries - smaller payload than full sessions.
        """
        t0 = time.perf_counter()
        params: dict[str, Any] = {"user_id": _get_user_id(), "limit": limit}
        if project_tag: params["project_tag"] = project_tag
        if date_from: params["date_from"] = date_from
        if date_to: params["date_to"] = date_to
        logger.info("[ARCHIVE] list_compact_summaries params=%s", params)
        try:
            with httpx.Client(timeout=30, headers=_get_headers()) as c:
                r = c.get(f"{_get_archive_url()}/compact-summaries", params=params)
                logger.info("[ARCHIVE] list_compact_summaries status=%d in %.2fs",
                            r.status_code, time.perf_counter() - t0)
                return r.text
        except Exception as exc:
            logger.error("[ARCHIVE] list_compact_summaries FAIL: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    @mcp.tool()
    def search_compact_summaries(
        q: Annotated[str, Field(description="Search query.")],
        limit: Annotated[int, Field(description="Max results.")] = 20,
    ) -> str:
        """Search compact summaries by keyword.

        PREFERRED tool for 'what did I discuss about X' queries.
        """
        t0 = time.perf_counter()
        params = {"user_id": _get_user_id(), "q": q, "limit": limit}
        logger.info("[ARCHIVE] search_compact_summaries q=%r", q)
        try:
            with httpx.Client(timeout=30, headers=_get_headers()) as c:
                r = c.get(f"{_get_archive_url()}/compact-summaries", params=params)
                logger.info("[ARCHIVE] search_compact_summaries status=%d in %.2fs",
                            r.status_code, time.perf_counter() - t0)
                return r.text
        except Exception as exc:
            logger.error("[ARCHIVE] search_compact_summaries FAIL: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    @mcp.tool()
    def get_compact_summary(
        summary_id: Annotated[str, Field(description="Summary UUID.")],
    ) -> str:
        """Get full text of a specific compact summary."""
        t0 = time.perf_counter()
        logger.info("[ARCHIVE] get_compact_summary id=%s", summary_id)
        try:
            with httpx.Client(timeout=30, headers=_get_headers()) as c:
                r = c.get(f"{_get_archive_url()}/compact-summaries/{summary_id}")
                logger.info("[ARCHIVE] get_compact_summary status=%d in %.2fs",
                            r.status_code, time.perf_counter() - t0)
                return r.text
        except Exception as exc:
            logger.error("[ARCHIVE] get_compact_summary FAIL: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
