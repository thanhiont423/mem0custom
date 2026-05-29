"""HTTP/Streamable transport entrypoint for mem0-mcp-selfhosted.

This module is a thin wrapper around `server.run_server()` that:

1. Loads `.env` from the directory of the executable (PyInstaller-aware).
   When packaged as a single-file `.exe`, `sys.executable` is the .exe path
   and the user's `.env` is expected to sit next to it. When running from
   source in dev mode, falls back to current working directory.

2. Sets sensible defaults for HTTP transport so the user doesn't need to
   specify MEM0_TRANSPORT / MEM0_HOST / MEM0_PORT explicitly:
     - MEM0_TRANSPORT = streamable-http   (instead of stdio)
     - MEM0_HOST      = 127.0.0.1         (loopback only - DO NOT expose)
     - MEM0_PORT      = 8765              (chosen to avoid common conflicts)
     - MEM0_LOG_FILE  = mem0-mcp.log      (next to exe, for debugging)

3. Prints a banner with the resolved paths so the user knows where config
   and logs are.

Override any default by setting the env var (either in .env or shell).

Usage:
    # Dev mode (from source)
    mem0-mcp-http

    # PyInstaller bundle
    .\\mem0-mcp.exe
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_runtime_dir() -> Path:
    """Where to look for .env and write logs.

    PyInstaller sets `sys.frozen=True` and `sys.executable` to the .exe path.
    In dev mode, fall back to current working directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def _load_env_file(runtime_dir: Path) -> Path | None:
    """Load .env from runtime_dir if present. Returns path loaded, or None."""
    env_file = runtime_dir / ".env"
    if not env_file.exists():
        return None

    # python-dotenv is already a dependency of mem0-mcp-selfhosted
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=env_file, override=False)
    return env_file


def _apply_http_defaults(runtime_dir: Path) -> None:
    """Set env defaults for HTTP transport - only if user hasn't already set them."""
    defaults = {
        "MEM0_TRANSPORT": "streamable-http",
        "MEM0_HOST": "127.0.0.1",
        "MEM0_PORT": "8765",
        # Default log file next to exe - easy to find when debugging
        "MEM0_LOG_FILE": str(runtime_dir / "mem0-mcp.log"),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _print_banner(runtime_dir: Path, env_file: Path | None) -> None:
    """Print a startup banner to stderr (stdout reserved for MCP if any)."""
    host = os.environ.get("MEM0_HOST", "127.0.0.1")
    port = os.environ.get("MEM0_PORT", "8765")
    transport = os.environ.get("MEM0_TRANSPORT", "streamable-http")

    home = Path.home()
    oat_path = home / ".claude" / ".credentials.json"
    oat_status = "FOUND" if oat_path.exists() else "MISSING (Claude Max LLM will fail)"

    archive_url = os.environ.get("ARCHIVE_URL", "").strip()
    if archive_url:
        archive_status = f"ENABLED -> {archive_url}"
    else:
        archive_status = "DISABLED (set ARCHIVE_URL in .env to enable)"

    banner = [
        "=" * 60,
        "mem0-mcp HTTP server (with optional archive tools)",
        "=" * 60,
        f"Runtime dir : {runtime_dir}",
        f"Config file : {env_file if env_file else '(no .env found)'}",
        f"Log file    : {os.environ.get('MEM0_LOG_FILE', '(stderr only)')}",
        f"Listen on   : http://{host}:{port}/mcp  (transport={transport})",
        f"OAT file    : {oat_path}  [{oat_status}]",
        f"User ID     : {os.environ.get('MEM0_USER_ID', '(default)')}",
        f"LLM model   : {os.environ.get('MEM0_LLM_MODEL', '(default)')}",
        f"Qdrant URL  : {os.environ.get('MEM0_QDRANT_URL', '(localhost:6333 - default)')}",
        f"Archive     : {archive_status}",
        "=" * 60,
        "",
        "Add to Claude Code (one-time):",
        f"  claude mcp add --scope user --transport http mem0 http://{host}:{port}/mcp",
        "",
        "Press Ctrl+C to stop.",
        "",
    ]
    print("\n".join(banner), file=sys.stderr, flush=True)


def main() -> None:
    """Entry point for `mem0-mcp-http` console script and PyInstaller bundle.

    Multi-mode dispatch via sys.argv:
      - no argv      -> chay HTTP server (default)
      - --upload-archive -> chay archive upload routine, exit
      - --install-hooks  -> install Claude Code hooks, exit
    """
    runtime_dir = _resolve_runtime_dir()
    env_file = _load_env_file(runtime_dir)

    # --- ARGV dispatch ---
    argv = sys.argv[1:]
    if argv and argv[0] == "--upload-archive":
        # Chay archive upload routine roi exit
        from mem0_mcp_selfhosted.archive_upload import main as upload_main
        sys.exit(upload_main())

    if argv and argv[0] == "--install-hooks":
        # Chay Claude Code hooks installer
        from mem0_mcp_selfhosted.hooks import install_main
        install_main()
        sys.exit(0)

    # --- Default: HTTP server mode ---
    _apply_http_defaults(runtime_dir)
    _print_banner(runtime_dir, env_file)

    # Defer the heavy import until after env is wired up - server.py reads
    # several env vars at module level via build_config().
    from mem0_mcp_selfhosted.server import run_server

    run_server()


if __name__ == "__main__":
    main()
