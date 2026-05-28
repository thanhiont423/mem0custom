"""Archive API — REST endpoints for storing/retrieving Claude Code transcripts.

Endpoints:
- POST   /sessions              — store a new session
- GET    /sessions              — list/search sessions
- GET    /sessions/{id}         — get full session
- POST   /compact-summaries     — store a /compact summary
- GET    /compact-summaries     — list/search compact summaries
- GET    /compact-summaries/{id}— get one compact summary
- GET    /health                — health check

Auth: all endpoints except /health require `Authorization: Bearer <ARCHIVE_AUTH_TOKEN>`.
"""
import os
import psycopg2
from psycopg2.extras import Json, RealDictCursor
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

DB_URL = os.environ["DB_URL"]
AUTH = os.environ["ARCHIVE_AUTH_TOKEN"]

app = FastAPI(
    title="Chat Archive API",
    description="REST API for archived Claude Code conversation transcripts.",
    version="1.0.0",
)


def check(token):
    if not token or token != f"Bearer {AUTH}":
        raise HTTPException(401, "Unauthorized")


def conn():
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)


# ----- chat_sessions -----

class Session(BaseModel):
    user_id: str
    project_tag: Optional[str] = None
    started_at: str
    ended_at: Optional[str] = None
    message_count: int
    transcript: list
    summary: Optional[str] = None
    workspace_path: Optional[str] = None
    metadata: dict = {}


@app.post("/sessions")
def create(s: Session, authorization: str = Header(None)):
    check(authorization)
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_sessions
            (user_id, project_tag, started_at, ended_at, message_count,
             transcript, summary, workspace_path, metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (s.user_id, s.project_tag, s.started_at, s.ended_at,
             s.message_count, Json(s.transcript), s.summary,
             s.workspace_path, Json(s.metadata)),
        )
        return {"id": str(cur.fetchone()["id"])}


@app.get("/sessions")
def list_sessions(
    user_id: str,
    project_tag: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    authorization: str = Header(None),
):
    check(authorization)
    sql = "SELECT id, started_at, project_tag, message_count, summary FROM chat_sessions WHERE user_id=%s"
    args = [user_id]
    if project_tag:
        sql += " AND project_tag=%s"
        args.append(project_tag)
    if date_from:
        sql += " AND started_at >= %s"
        args.append(date_from)
    if date_to:
        sql += " AND started_at <= %s"
        args.append(date_to)
    if q:
        sql += " AND summary ILIKE %s"
        args.append(f"%{q}%")
    sql += " ORDER BY started_at DESC LIMIT %s"
    args.append(limit)
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]


@app.get("/sessions/{session_id}")
def get_session(session_id: str, authorization: str = Header(None)):
    check(authorization)
    with conn() as c, c.cursor() as cur:
        cur.execute("SELECT * FROM chat_sessions WHERE id=%s", (session_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(404)
        return dict(r)


# ----- compact_summaries (from /compact events) -----

class CompactSummary(BaseModel):
    user_id: str
    session_id: Optional[str] = None
    summary_text: str
    messages_before: int = 0
    position_in_session: Optional[int] = None
    metadata: dict = {}


@app.post("/compact-summaries")
def create_summary(s: CompactSummary, authorization: str = Header(None)):
    check(authorization)
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO compact_summaries
            (user_id, session_id, summary_text, messages_before,
             position_in_session, metadata)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (s.user_id, s.session_id, s.summary_text, s.messages_before,
             s.position_in_session, Json(s.metadata)),
        )
        return {"id": str(cur.fetchone()["id"])}


@app.get("/compact-summaries")
def list_summaries(
    user_id: str,
    q: Optional[str] = None,
    limit: int = 50,
    authorization: str = Header(None),
):
    check(authorization)
    sql = """
        SELECT id, session_id, compacted_at, summary_text, messages_before
        FROM compact_summaries WHERE user_id=%s
    """
    args = [user_id]
    if q:
        sql += " AND summary_text ILIKE %s"
        args.append(f"%{q}%")
    sql += " ORDER BY compacted_at DESC LIMIT %s"
    args.append(limit)
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]


@app.get("/compact-summaries/{summary_id}")
def get_summary(summary_id: str, authorization: str = Header(None)):
    check(authorization)
    with conn() as c, c.cursor() as cur:
        cur.execute("SELECT * FROM compact_summaries WHERE id=%s", (summary_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(404)
        return dict(r)


@app.get("/health")
def health():
    return "ok"
