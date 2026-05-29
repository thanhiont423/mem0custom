"""Auto-upload Claude Code transcripts + compact summaries to Archive API on VPS.

Doc theo plan-trien-khai-memory-server-mac-windows.md (Buoc 7 + Phase 3).
Workflow:
  1. Scan ~/.claude/projects/*.jsonl tim session moi (hash file)
  2. Parse JSONL -> POST /sessions
  3. Extract compact summaries (regex pattern) -> POST /compact-summaries
  4. State file ~/.cache/claude-archive-state.json track da upload (tranh duplicate)

Goi qua 3 cach:
  - CLI mode: `mem0-mcp.exe --upload-archive` (Task Scheduler hourly)
  - Claude Code hook: chay sau session Stop hoac /compact
  - Manual: import va goi main()
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# Pattern detect compact summary: system message + chua tu khoa typical
_COMPACT_PATTERNS = re.compile(
    r"(previously discussed|conversation summary|prior conversation|earlier in this conversation)",
    re.IGNORECASE,
)


def _state_file() -> Path:
    return Path.home() / ".cache" / "claude-archive-state.json"


def _load_state() -> dict[str, list[str]]:
    sf = _state_file()
    if sf.exists():
        try:
            data = json.loads(sf.read_text())
        except Exception:
            data = {}
    else:
        data = {}
    # Default schema
    data.setdefault("uploaded", [])
    data.setdefault("summaries_uploaded", [])
    return data


def _save_state(state: dict) -> None:
    sf = _state_file()
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(state))


def _file_id(p: Path) -> str:
    h = hashlib.sha256()
    h.update(str(p).encode())
    h.update(str(p.stat().st_mtime).encode())
    return h.hexdigest()[:16]


def _summary_id(jsonl_path: Path, idx: int, text: str) -> str:
    """Unique ID per compact summary - based on file + position + content hash."""
    h = hashlib.sha256()
    h.update(str(jsonl_path).encode())
    h.update(str(idx).encode())
    h.update(text[:500].encode())  # first 500 chars suffice
    return h.hexdigest()[:16]


def _parse_session(jsonl_path: Path) -> dict[str, Any] | None:
    messages, workspace, times = [], None, []
    try:
        text = jsonl_path.read_text(errors="ignore")
    except Exception:
        return None
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if "cwd" in m and not workspace:
            workspace = m["cwd"]
        if m.get("type") in ("user", "assistant"):
            content = m.get("message", {}).get("content")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict)
                )
            messages.append({
                "role": m.get("type"),
                "content": content,
                "timestamp": m.get("timestamp"),
            })
            if m.get("timestamp"):
                times.append(m["timestamp"])
    if not messages or not times:
        return None
    project_tag = Path(workspace).name if workspace else None
    first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
    return {
        "user_id": os.environ.get("USER_ID", "thanh"),
        "project_tag": project_tag,
        "workspace_path": workspace,
        "started_at": min(times),
        "ended_at": max(times),
        "message_count": len(messages),
        "transcript": messages,
        "summary": (first_user or "")[:200],
        "metadata": {"source_file": jsonl_path.name},
    }


def _extract_compact_summaries(jsonl_path: Path) -> list[dict[str, Any]]:
    """Detect compact summary messages in JSONL.

    Heuristic: type=system + content matches compact patterns + len > 100 chars.
    Returns list of dicts ready for POST /compact-summaries.
    """
    results: list[dict[str, Any]] = []
    project_tag = None
    workspace = None
    try:
        text = jsonl_path.read_text(errors="ignore")
    except Exception:
        return results

    msg_count_before = 0
    for idx, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue

        if "cwd" in m and not workspace:
            workspace = m["cwd"]
            project_tag = Path(workspace).name if workspace else None

        msg_type = m.get("type")
        if msg_type in ("user", "assistant"):
            msg_count_before += 1
        elif msg_type == "system":
            content = m.get("message", {}).get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict)
                )
            content_str = str(content or "")
            if len(content_str) > 100 and _COMPACT_PATTERNS.search(content_str):
                # Match VPS schema chinh xac: CompactSummary Pydantic model
                # Fields: session_id, user_id, project_tag, workspace_path,
                #         summary_text, messages_before, position_in_session, metadata
                results.append({
                    "user_id": os.environ.get("USER_ID", "thanh"),
                    "project_tag": project_tag,
                    "workspace_path": workspace,
                    "summary_text": content_str,
                    "messages_before": msg_count_before,
                    "position_in_session": idx,  # top-level, dung schema
                    "metadata": {
                        "source_file": jsonl_path.name,
                        "timestamp": m.get("timestamp"),
                    },
                    "_local_id": _summary_id(jsonl_path, idx, content_str),
                })

    return results


def _upload(endpoint: str, data: dict, timeout: int = 30) -> dict:
    archive_url = os.environ["ARCHIVE_URL"].rstrip("/")
    token = os.environ["ARCHIVE_AUTH_TOKEN"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout, headers=headers) as c:
        r = c.post(f"{archive_url}{endpoint}", json=data)
        r.raise_for_status()
        return r.json()


def upload_archive() -> dict[str, int]:
    """Main upload routine. Returns counts: {'sessions': N, 'summaries': M}."""
    if not os.environ.get("ARCHIVE_URL"):
        logger.warning("[ARCHIVE-UPLOAD] ARCHIVE_URL not set - skip upload")
        return {"sessions": 0, "summaries": 0}
    if not os.environ.get("ARCHIVE_AUTH_TOKEN"):
        logger.warning("[ARCHIVE-UPLOAD] ARCHIVE_AUTH_TOKEN not set - skip upload")
        return {"sessions": 0, "summaries": 0}

    state = _load_state()
    uploaded = set(state["uploaded"])
    summaries_uploaded = set(state["summaries_uploaded"])

    sessions_dir = Path.home() / ".claude" / "projects"
    if not sessions_dir.exists():
        logger.warning("[ARCHIVE-UPLOAD] No Claude Code sessions dir: %s", sessions_dir)
        return {"sessions": 0, "summaries": 0}

    new_sessions = 0
    new_summaries = 0

    for jsonl in sessions_dir.rglob("*.jsonl"):
        fid = _file_id(jsonl)

        # Upload session if new
        if fid not in uploaded:
            data = _parse_session(jsonl)
            if data:
                try:
                    _upload("/sessions", data)
                    uploaded.add(fid)
                    new_sessions += 1
                    logger.info("[ARCHIVE-UPLOAD] Session uploaded: %s -> project=%s",
                                jsonl.name, data["project_tag"])
                except Exception as exc:
                    logger.error("[ARCHIVE-UPLOAD] Session FAIL %s: %s", jsonl.name, exc)

        # Extract + upload compact summaries (always rescan, hash-based dedup)
        for summary in _extract_compact_summaries(jsonl):
            sid = summary.pop("_local_id")
            if sid in summaries_uploaded:
                continue
            try:
                _upload("/compact-summaries", summary)
                summaries_uploaded.add(sid)
                new_summaries += 1
                logger.info("[ARCHIVE-UPLOAD] Compact summary uploaded: %s pos=%d",
                            jsonl.name, summary["metadata"]["source_position"])
            except Exception as exc:
                logger.error("[ARCHIVE-UPLOAD] Summary FAIL %s: %s", jsonl.name, exc)

    state["uploaded"] = list(uploaded)
    state["summaries_uploaded"] = list(summaries_uploaded)
    _save_state(state)

    logger.info("[ARCHIVE-UPLOAD] Done. %d new sessions, %d new summaries.",
                new_sessions, new_summaries)
    return {"sessions": new_sessions, "summaries": new_summaries}


def main() -> int:
    """CLI entrypoint. Returns exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stderr,
    )

    # Load .env from same dir as exe if frozen
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
    else:
        exe_dir = Path.cwd()
    env_file = exe_dir / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)

    try:
        result = upload_archive()
        print(f"OK: {result['sessions']} sessions, {result['summaries']} summaries uploaded.")
        return 0
    except Exception as exc:
        logger.error("[ARCHIVE-UPLOAD] FATAL: %s", exc, exc_info=True)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
nt(f"OK: {result['sessions']} sessions, {result['summaries']} summaries uploaded.")
        return 0
    except Exception as exc:
        logger.error("[ARCHIVE-UPLOAD] FATAL: %s", exc, exc_info=True)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
