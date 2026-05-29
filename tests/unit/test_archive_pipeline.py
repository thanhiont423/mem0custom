"""Unit tests for archive_upload + archive_tools modules.

Khong yeu cau live infrastructure - dung mock JSONL.
Chay tren ca Ubuntu va Windows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mem0_mcp_selfhosted.archive_upload import (
    _COMPACT_PATTERNS,
    _extract_compact_summaries,
    _file_id,
    _parse_session,
    _summary_id,
)


@pytest.fixture
def sample_jsonl(tmp_path: Path) -> Path:
    """Tao mock Claude Code session JSONL file."""
    jsonl = tmp_path / "test-session.jsonl"
    messages = [
        {"type": "user", "cwd": str(tmp_path / "MyProject"),
         "message": {"content": "Hello, can you help me setup mem0?"},
         "timestamp": "2026-05-27T10:00:00Z"},
        {"type": "assistant",
         "message": {"content": [{"text": "Sure, let me explain the setup."}]},
         "timestamp": "2026-05-27T10:00:30Z"},
        {"type": "user",
         "message": {"content": "What about Postgres configuration?"},
         "timestamp": "2026-05-27T10:01:00Z"},
        {"type": "assistant",
         "message": {"content": [{"text": "For Postgres set MEM0_QDRANT_URL..."}]},
         "timestamp": "2026-05-27T10:01:30Z"},
        # Compact summary system message (must match _COMPACT_PATTERNS)
        {"type": "system",
         "message": {"content": "This is a conversation summary of previously discussed topics. "
                                 "We talked about mem0 server setup and Postgres configuration. "
                                 "The user is working on Windows behind a corporate proxy."},
         "timestamp": "2026-05-27T10:02:00Z"},
        {"type": "user",
         "message": {"content": "Continue from where we left off"},
         "timestamp": "2026-05-27T10:03:00Z"},
    ]
    with jsonl.open("w") as f:
        for m in messages:
            f.write(json.dumps(m) + "\n")
    return jsonl


class TestParseSession:
    """Test _parse_session - upload FULL transcript."""

    def test_returns_dict_with_required_fields(self, sample_jsonl):
        session = _parse_session(sample_jsonl)
        assert session is not None
        required = {"user_id", "project_tag", "workspace_path",
                    "started_at", "ended_at", "message_count",
                    "transcript", "summary", "metadata"}
        assert required.issubset(session.keys()), f"Missing: {required - session.keys()}"

    def test_user_id_from_env(self, sample_jsonl, monkeypatch):
        monkeypatch.setenv("USER_ID", "thanh")
        session = _parse_session(sample_jsonl)
        assert session["user_id"] == "thanh"

    def test_user_id_default_when_unset(self, sample_jsonl, monkeypatch):
        monkeypatch.delenv("USER_ID", raising=False)
        session = _parse_session(sample_jsonl)
        assert session["user_id"] == "thanh"  # default

    def test_project_tag_from_cwd_basename(self, sample_jsonl):
        session = _parse_session(sample_jsonl)
        assert session["project_tag"] == "MyProject"

    def test_message_count_includes_user_and_assistant(self, sample_jsonl):
        session = _parse_session(sample_jsonl)
        assert session["message_count"] == 5  # 3 user + 2 assistant (system not counted)

    def test_transcript_preserves_order(self, sample_jsonl):
        session = _parse_session(sample_jsonl)
        roles = [m["role"] for m in session["transcript"]]
        assert roles == ["user", "assistant", "user", "assistant", "user"]

    def test_timestamps_bracket_range(self, sample_jsonl):
        session = _parse_session(sample_jsonl)
        assert session["started_at"] == "2026-05-27T10:00:00Z"
        assert session["ended_at"] == "2026-05-27T10:03:00Z"

    def test_empty_file_returns_none(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert _parse_session(empty) is None

    def test_malformed_jsonl_skipped(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text("not-json\n{\"type\":\"user\",\"message\":{\"content\":\"ok\"},\"timestamp\":\"2026-05-27T10:00:00Z\"}\n")
        session = _parse_session(f)
        # Should skip bad lines, parse valid ones
        assert session is not None
        assert session["message_count"] == 1


class TestExtractCompactSummaries:
    """Test _extract_compact_summaries - upload COMPACT summary only."""

    def test_detects_summary_with_pattern(self, sample_jsonl):
        summaries = _extract_compact_summaries(sample_jsonl)
        assert len(summaries) == 1

    def test_schema_matches_vps_compact_summary(self, sample_jsonl):
        """Verify all fields match VPS CompactSummary Pydantic model."""
        summary = _extract_compact_summaries(sample_jsonl)[0]
        required = {"user_id", "project_tag", "workspace_path",
                    "summary_text", "messages_before", "position_in_session",
                    "metadata"}
        assert required.issubset(summary.keys())

    def test_position_is_top_level_not_in_metadata(self, sample_jsonl):
        """Bug fix #19: position_in_session phai o top-level, khong nest trong metadata."""
        summary = _extract_compact_summaries(sample_jsonl)[0]
        assert "position_in_session" in summary
        assert "source_position" not in summary.get("metadata", {})

    def test_no_compacted_at_field(self, sample_jsonl):
        """Bug fix #19: compacted_at khong co trong VPS schema, da bo top-level."""
        summary = _extract_compact_summaries(sample_jsonl)[0]
        assert "compacted_at" not in summary

    def test_messages_before_counts_correctly(self, sample_jsonl):
        """messages_before = number of user+assistant BEFORE the system summary."""
        summary = _extract_compact_summaries(sample_jsonl)[0]
        assert summary["messages_before"] == 4  # 2 user + 2 assistant

    def test_filters_short_messages(self, tmp_path):
        """Messages shorter than 100 chars are ignored (false positive guard)."""
        f = tmp_path / "short.jsonl"
        f.write_text(json.dumps({
            "type": "system",
            "message": {"content": "previously discussed brief"},  # < 100 chars
            "timestamp": "2026-05-27T10:00:00Z"
        }) + "\n")
        assert _extract_compact_summaries(f) == []

    def test_filters_non_compact_pattern(self, tmp_path):
        """System message without compact pattern is ignored."""
        f = tmp_path / "non.jsonl"
        long_text = "This is just a regular system notification " * 10
        f.write_text(json.dumps({
            "type": "system",
            "message": {"content": long_text},
            "timestamp": "2026-05-27T10:00:00Z"
        }) + "\n")
        assert _extract_compact_summaries(f) == []


class TestHashDedup:
    """Test deterministic hashing for dedup state."""

    def test_file_id_stable_across_calls(self, sample_jsonl):
        h1 = _file_id(sample_jsonl)
        h2 = _file_id(sample_jsonl)
        assert h1 == h2
        assert len(h1) == 16

    def test_summary_id_stable_for_same_input(self, sample_jsonl):
        text = "test content"
        h1 = _summary_id(sample_jsonl, 5, text)
        h2 = _summary_id(sample_jsonl, 5, text)
        assert h1 == h2

    def test_summary_id_differs_for_different_position(self, sample_jsonl):
        text = "same content"
        h1 = _summary_id(sample_jsonl, 1, text)
        h2 = _summary_id(sample_jsonl, 2, text)
        assert h1 != h2

    def test_summary_id_differs_for_different_content(self, sample_jsonl):
        h1 = _summary_id(sample_jsonl, 1, "content A")
        h2 = _summary_id(sample_jsonl, 1, "content B")
        assert h1 != h2


class TestCompactPatterns:
    """Test regex patterns dùng detect compact summaries."""

    def test_matches_previously_discussed(self):
        assert _COMPACT_PATTERNS.search("we previously discussed setup")

    def test_matches_conversation_summary(self):
        assert _COMPACT_PATTERNS.search("This is a conversation summary")

    def test_matches_prior_conversation(self):
        assert _COMPACT_PATTERNS.search("In the prior conversation")

    def test_case_insensitive(self):
        assert _COMPACT_PATTERNS.search("PREVIOUSLY DISCUSSED")
        assert _COMPACT_PATTERNS.search("Previously Discussed")

    def test_does_not_match_unrelated(self):
        assert not _COMPACT_PATTERNS.search("Hello world")
        assert not _COMPACT_PATTERNS.search("Random system notice")
