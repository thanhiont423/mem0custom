"""Test http_server.py wrapper logic (runtime dir, env loading, defaults)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


class TestRuntimeDir:
    """Test _resolve_runtime_dir - PyInstaller-aware path."""

    def test_dev_mode_uses_cwd(self, monkeypatch, tmp_path):
        # KHONG frozen -> Path.cwd()
        monkeypatch.chdir(tmp_path)
        if hasattr(sys, "frozen"):
            monkeypatch.delattr(sys, "frozen", raising=False)
        from mem0_mcp_selfhosted.http_server import _resolve_runtime_dir
        assert _resolve_runtime_dir() == tmp_path.resolve() or _resolve_runtime_dir() == tmp_path

    def test_frozen_mode_uses_executable_parent(self, monkeypatch, tmp_path):
        # Simulate PyInstaller frozen
        fake_exe = tmp_path / "mem0-mcp.exe"
        fake_exe.write_text("")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        from mem0_mcp_selfhosted.http_server import _resolve_runtime_dir
        assert _resolve_runtime_dir() == tmp_path


class TestEnvFileLoading:
    """Test _load_env_file - load .env from runtime dir."""

    def test_loads_env_when_present(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("CUSTOM_TEST_VAR=hello_world\n")
        monkeypatch.delenv("CUSTOM_TEST_VAR", raising=False)
        from mem0_mcp_selfhosted.http_server import _load_env_file
        result = _load_env_file(tmp_path)
        assert result == env_file
        assert os.environ.get("CUSTOM_TEST_VAR") == "hello_world"
        monkeypatch.delenv("CUSTOM_TEST_VAR", raising=False)

    def test_returns_none_when_no_env(self, tmp_path):
        from mem0_mcp_selfhosted.http_server import _load_env_file
        assert _load_env_file(tmp_path) is None

    def test_does_not_override_existing_env(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_VAR=from_file\n")
        monkeypatch.setenv("EXISTING_VAR", "from_shell")
        from mem0_mcp_selfhosted.http_server import _load_env_file
        _load_env_file(tmp_path)
        # override=False semantic - shell wins
        assert os.environ.get("EXISTING_VAR") == "from_shell"


class TestHttpDefaults:
    """Test _apply_http_defaults - set HTTP transport vars."""

    def test_sets_defaults_when_unset(self, monkeypatch, tmp_path):
        for k in ["MEM0_TRANSPORT", "MEM0_HOST", "MEM0_PORT", "MEM0_LOG_FILE"]:
            monkeypatch.delenv(k, raising=False)
        from mem0_mcp_selfhosted.http_server import _apply_http_defaults
        _apply_http_defaults(tmp_path)
        assert os.environ["MEM0_TRANSPORT"] == "streamable-http"
        assert os.environ["MEM0_HOST"] == "127.0.0.1"
        assert os.environ["MEM0_PORT"] == "8765"
        assert os.environ["MEM0_LOG_FILE"] == str(tmp_path / "mem0-mcp.log")

    def test_respects_existing_values(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEM0_PORT", "9999")
        monkeypatch.setenv("MEM0_HOST", "0.0.0.0")
        monkeypatch.setenv("MEM0_TRANSPORT", "sse")
        from mem0_mcp_selfhosted.http_server import _apply_http_defaults
        _apply_http_defaults(tmp_path)
        # user vars NOT overridden
        assert os.environ["MEM0_PORT"] == "9999"
        assert os.environ["MEM0_HOST"] == "0.0.0.0"
        assert os.environ["MEM0_TRANSPORT"] == "sse"
