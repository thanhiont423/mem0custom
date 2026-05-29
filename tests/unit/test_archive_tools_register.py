"""Test archive_tools.register_archive_tools - conditional based on ARCHIVE_URL env."""

from __future__ import annotations

import os
import pytest


class TestArchiveEnabled:
    """Test _archive_enabled gate."""

    def test_enabled_with_url(self, monkeypatch):
        monkeypatch.setenv("ARCHIVE_URL", "https://test.example/archive")
        from mem0_mcp_selfhosted.archive_tools import _archive_enabled
        assert _archive_enabled() is True

    def test_disabled_without_url(self, monkeypatch):
        monkeypatch.delenv("ARCHIVE_URL", raising=False)
        from mem0_mcp_selfhosted.archive_tools import _archive_enabled
        assert _archive_enabled() is False

    def test_disabled_with_empty_url(self, monkeypatch):
        monkeypatch.setenv("ARCHIVE_URL", "")
        from mem0_mcp_selfhosted.archive_tools import _archive_enabled
        assert _archive_enabled() is False

    def test_disabled_with_whitespace_url(self, monkeypatch):
        monkeypatch.setenv("ARCHIVE_URL", "   ")
        from mem0_mcp_selfhosted.archive_tools import _archive_enabled
        assert _archive_enabled() is False


class TestHeadersHelper:
    """Test _get_headers - bearer token auth."""

    def test_with_token(self, monkeypatch):
        monkeypatch.setenv("ARCHIVE_AUTH_TOKEN", "secret123")
        from mem0_mcp_selfhosted.archive_tools import _get_headers
        h = _get_headers()
        assert h["Authorization"] == "Bearer secret123"

    def test_without_token_returns_empty(self, monkeypatch):
        monkeypatch.delenv("ARCHIVE_AUTH_TOKEN", raising=False)
        from mem0_mcp_selfhosted.archive_tools import _get_headers
        assert _get_headers() == {}


class TestUserId:
    """Test _get_user_id - default + override."""

    def test_default_thanh(self, monkeypatch):
        monkeypatch.delenv("USER_ID", raising=False)
        from mem0_mcp_selfhosted.archive_tools import _get_user_id
        assert _get_user_id() == "thanh"

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("USER_ID", "alice")
        from mem0_mcp_selfhosted.archive_tools import _get_user_id
        assert _get_user_id() == "alice"


class TestUrlNormalization:
    """Test _get_archive_url - strips trailing slash."""

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("ARCHIVE_URL", "https://example.com/archive/")
        from mem0_mcp_selfhosted.archive_tools import _get_archive_url
        assert _get_archive_url() == "https://example.com/archive"

    def test_keeps_no_slash(self, monkeypatch):
        monkeypatch.setenv("ARCHIVE_URL", "https://example.com/archive")
        from mem0_mcp_selfhosted.archive_tools import _get_archive_url
        assert _get_archive_url() == "https://example.com/archive"
