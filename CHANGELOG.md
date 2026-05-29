# Changelog

## v0.4.2 - 2026-05-29

### Added — Portable HTTP Windows EXE
- New entrypoint `mem0-mcp-http` (`http_server.py`) — PyInstaller-aware wrapper that:
  - Resolves runtime dir from `sys.executable` parent when frozen, falls back to cwd in dev mode
  - Loads `.env` from runtime dir (or skips if absent)
  - Sets safe defaults: `MEM0_TRANSPORT=streamable-http`, `MEM0_HOST=127.0.0.1`, `MEM0_PORT=8765`
  - Prints startup banner with config status, OAT file, log file location
- Multi-mode argv dispatch in `http_server.py`:
  - no args → run HTTP server (default)
  - `--upload-archive` → run archive upload routine and exit
  - `--install-hooks` → install Claude Code SessionStart/Stop hooks
- PyInstaller spec file (`mem0-mcp.spec`) with `collect_all` for mem0, mcp, qdrant_client, openai, anthropic, tiktoken
- GitHub Actions workflow `build-windows.yml` — Windows runner, Python 3.11, uploads `dist/mem0-mcp.exe` as artifact
- Bundled Windows install scripts (in companion `mem0-mcp-portable-build` distribution):
  - `setup.ps1` — 10-step one-step installer
  - `install-on-target.ps1` — install on machines without Python
  - `install-autostart.bat` — registers Task Scheduler with auto-restart
  - `install-claude-hook.ps1` — registers SessionStart/`compact` hook (PowerShell 5.1 compatible)
  - `verify-install.ps1` — 8-component health check + auto-fix
  - `uninstall.ps1` — clean removal

### Added — Archive tools (7 MCP tools)
- `archive_tools.py` — new module, conditionally registers archive tools when `ARCHIVE_URL` env var is set
- 7 tools backed by Archive API on VPS:
  - `list_old_sessions` — GET /sessions
  - `get_session_summary` — GET /sessions/{id} with compact view (first/last 5 messages)
  - `get_old_session` — GET /sessions/{id} full transcript
  - `search_old_sessions` — GET /sessions?q=...
  - `list_compact_summaries` — GET /compact-summaries
  - `search_compact_summaries` — GET /compact-summaries?q=... (preferred for "what did I discuss about X" queries)
  - `get_compact_summary` — GET /compact-summaries/{id}
- Server.py registers archive tools after mem0 tools via lazy import (no hard dependency)

### Added — Archive auto-upload
- `archive_upload.py` — scan `~/.claude/projects/*.jsonl`, upload sessions + compact summaries to VPS
- Hash-based dedup via `~/.cache/claude-archive-state.json` (2 keys: `uploaded` + `summaries_uploaded`)
- Compact summary detection via regex: `previously discussed|conversation summary|prior conversation|earlier in this conversation` + length > 100 chars
- Triggered 3 ways:
  - CLI: `mem0-mcp.exe --upload-archive` (via Task Scheduler hourly)
  - Claude Code hook on SessionStart matcher `compact`
  - Manual: `from mem0_mcp_selfhosted.archive_upload import upload_archive`

### Fixed — Schema match with VPS CompactSummary Pydantic model
- `workspace_path` now sent (was missing)
- `position_in_session` moved to top-level (was incorrectly nested in `metadata.source_position`)
- `compacted_at` field removed (not in VPS schema, was being silently dropped)

### Added — Tests (42 unit tests)
- `tests/unit/test_archive_pipeline.py` — 25 tests covering parse_session, extract_compact_summaries, hash dedup, regex patterns
- `tests/unit/test_archive_tools_register.py` — 10 tests for env-gate, headers, user_id, URL normalization
- `tests/unit/test_http_server_wrapper.py` — 7 tests for runtime dir, env loading, defaults
- Regression guards for schema bug fix (position_in_session top-level, no compacted_at, no source_position)

### Added — CI
- GitHub Actions workflow `test.yml`:
  - Matrix: Ubuntu + Windows × Python 3.10/3.11/3.12 = 6 jobs
  - Lint job: `compileall` all modules
  - Schema check job: grep source code for VPS field match

### Changed
- `pyproject.toml` version 0.3.9 → 0.4.2
- Description updated: "Self-hosted mem0 MCP server for Claude Code (HTTP exe + archive 7 tools + auto-upload + hooks)"

# CHANGELOG


## v0.3.2 (2026-03-13)

### Bug Fixes

- Cache-bust Glama badge URL to force fresh camo proxy fetch
  ([`205ecf9`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/205ecf9a6d8d95f23fa0d8fa27826e3348ab0728))


## v0.3.1 (2026-03-12)

### Bug Fixes

- Add .python-version for Glama uv sync compatibility
  ([`e4d1f09`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/e4d1f09008652a84ed1340db9372f621b8ffa785))

Pin Python 3.12 so uv sync resolves the correct interpreter in Glama's Docker build environment
  instead of picking up Debian's externally-managed Python 3.11.

### Chores

- Remove Dockerfile (Glama generates its own)
  ([`33f2f1d`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/33f2f1d25bdb1e4c85617e90b21a72c48fc9c2a2))

Glama's admin page generates a Dockerfile from configuration fields rather than using the repo's
  Dockerfile. No other Docker deployment workflow exists, so the file is unused.


## v0.3.0 (2026-03-12)

### Features

- Lazy Memory init + Glama submission packaging
  ([`c6f2b76`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/c6f2b76aa7fc1f243c86fbcd941825ef7861b539))

Defer Memory.from_config() to the first tool call via _ensure_memory(), allowing the MCP server to
  respond to initialize/tools/list without live Qdrant/Neo4j/Ollama. This unblocks Glama's
  Docker-based inspection pipeline which builds and runs the container in an ephemeral sandbox.

Add LICENSE (MIT), glama.json, Dockerfile, and Glama badge in README.


## v0.2.1 (2026-02-28)

### Bug Fixes

- Update hooks to nested format for Claude Code schema compatibility
  ([`2f86dee`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/2f86dee99c3fa73220270b721c1621881beea655))

Migrate hook installer from the deprecated flat format to the current nested schema (matcher group
  -> hooks array -> handler objects). Add legacy format detection and auto-migration so existing
  users upgrading do not end up with duplicate or broken entries.

### Documentation

- Clarify hooks and CLAUDE.md as complementary layers
  ([`94f29dc`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/94f29dca52582ee18ce9ae256fc06d8cf1adab30))

Update README to explain that hooks (automated memory at session boundaries) and CLAUDE.md
  (behavioral instructions for mid-session engagement) work best together rather than as
  alternatives.


## v0.2.0 (2026-02-28)

### Features

- Add Claude Code session hooks for cross-session memory
  ([`113df26`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/113df2678b05091dd0acffa2776c755d4c380644))

Add SessionStart and Stop hooks that give Claude Code automatic cross-session memory without
  requiring CLAUDE.md rules or manual tool calls.

- SessionStart hook (mem0-hook-context): searches mem0 with multi-query strategy, deduplicates by
  ID, injects formatted memories as additionalContext on startup and compact events - Stop hook
  (mem0-hook-stop): reads last ~3 exchanges from JSONL transcript via bounded deque, saves session
  summary to mem0 with infer=True for atomic fact extraction - CLI installer (mem0-install-hooks):
  patches .claude/settings.json with idempotent hook entries, supports --global and --project-dir -
  Graph force-disabled in hooks to stay within 15s/30s timeout budgets - Atomic settings.json write
  via tempfile + os.replace - 43 unit tests covering protocol, edge cases, and error handling - 6
  integration tests against live Qdrant + Ollama infrastructure - README updated with hooks
  documentation, architecture diagram, and test structure


## v0.1.1 (2026-02-27)

### Bug Fixes

- Use NEO4J_DATABASE env var instead of config dict for non-default database
  ([`74e1188`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/74e1188d38154846ec8b12602fde1d757197873b))

mem0ai's graph_memory.py passes config as positional args to Neo4jGraph() where pos 3 is `token`,
  not `database`. Setting database in the config dict causes it to land in the token parameter,
  resulting in AuthenticationError. Use NEO4J_DATABASE env var which langchain_neo4j reads via
  get_from_dict_or_env().

Upstream: mem0ai #3906, #3981, #4085 (none merged)

Resolves: PAR-57


## v0.1.0 (2026-02-27)

### Bug Fixes

- **ci**: Use angular parser compatible with PSR v9.15.2
  ([`b5bc6ab`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/b5bc6ab45edff26f07fc73774c7e0c57d22cb40d))

The v9 GitHub Action does not recognize "conventional" parser name (v10+ only). Reverts to "angular"
  and changelog.changelog_file format.

### Continuous Integration

- Add python-semantic-release configuration and GitHub Actions workflow
  ([`2473ee4`](https://github.com/elvismdev/mem0-mcp-selfhosted/commit/2473ee4ec9c0db90b2bb412d3714caae7dc41498))

Automated versioning via Conventional Commits analysis, changelog generation, git tagging
  (v{version}), and GitHub Release creation on push to main.

## v0.3.8 (2026-05-26) — Minimal dependencies (Option B)

### Changed
- **BREAKING (config-level only)**: Removed `mem0ai[graph,llms]` extras and explicit `neo4j` from `dependencies` in `pyproject.toml`. Reduces install size by ~80–120MB and prewarm time by ~70–80%.
- Now installs: `mcp[cli]`, `mem0ai` (core, no extras), `anthropic`, `openai`, `qdrant-client`, `httpx`, `python-dotenv`.

### Added — defensive imports (graceful fallback)
- `src/mem0_mcp_selfhosted/llm_ollama.py`: top-level `from mem0.llms.ollama import OllamaLLM` wrapped in try/except. Defines stub class if import fails (raises ImportError on instantiation with clear message). Lets server load even without `ollama` runtime — Ollama provider class is always registered via class_path string even when unused.
- `src/mem0_mcp_selfhosted/helpers.py`: `patch_graph_sanitizer()` now wraps `import mem0.memory.utils` in try/except. Skips patching if mem0[graph] modules unavailable.

### To re-enable removed features
- Graph (Neo4j + langchain): add `"mem0ai[graph]>=1.0.3,<2.0"` and `"neo4j>=5.23.1"` back to dependencies, set `MEM0_ENABLE_GRAPH=true`.
- Ollama LLM provider: add `"ollama"` to dependencies, set `MEM0_LLM_PROVIDER=ollama`.
- Gemini graph LLM: add `"google-generativeai"` to dependencies, set `MEM0_GRAPH_LLM_PROVIDER=gemini`.

### Rationale
- Setup target: Anthropic (OAT) + OpenAI (embed) + Qdrant only.
- Previous `[graph,llms]` installed ~150MB of unused clients (langchain, neo4j, networkx, rank-bm25, ollama, google-generativeai, groq, mistralai, cohere).
- Prewarm time on Windows machine with corporate AV: 95–195s → expected 15–40s.
- Avoids VS Code Claude Code default 30s MCP timeout (root cause of respawn loop B19/B28).
