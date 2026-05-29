# mem0-mcp Portable for Windows (v0.4.2)

This fork (`v0.4.2-http-portable`) ships a **single-file Windows .exe** that runs the mem0 MCP server with HTTP transport — no Python install needed on target machines.

## What you get

- **`mem0-mcp.exe`** (~120 MB) — bundled Python + mem0ai + MCP + archive tools
- **18 MCP tools** when archive enabled: 11 mem0 (add_memory, search_memories, ...) + 7 archive (list_old_sessions, get_session_summary, search_compact_summaries, ...)
- **Auto-restart on crash** via Task Scheduler (3 retries)
- **Auto-upload Claude Code transcripts** hourly + immediate trigger on `/compact`
- **Hidden install** in `%LOCALAPPDATA%\mem0-mcp\`
- **No admin needed** — runs at user privilege level

## Quick install

### Option A — Download pre-built .exe from CI

1. Go to [GitHub Actions](https://github.com/thanhiont423/mem0custom/actions)
2. Click **Build Windows EXE** workflow → latest run on `v0.4.2-http-portable`
3. Download artifact `mem0-mcp-exe-v0.4.2`
4. Run installer (see below)

### Option B — Build locally

Requires Python 3.11+ on a Windows machine.

```powershell
git clone https://github.com/thanhiont423/mem0custom.git
cd mem0custom
git checkout v0.4.2-http-portable
python -m pip install -e .
python -m pip install pyinstaller
pyinstaller mem0-mcp.spec --clean --noconfirm
# Output: dist\mem0-mcp.exe
```

## Run

### 1. Create config

Create `.env` next to `mem0-mcp.exe`:

```env
# === User scope ===
MEM0_USER_ID=thanh

# === LLM: Claude Haiku via Claude Max OAT (free) ===
MEM0_PROVIDER=anthropic
MEM0_LLM_MODEL=claude-haiku-4-5-20251001

# === Embedder: OpenAI ===
MEM0_EMBED_PROVIDER=openai
MEM0_EMBED_MODEL=text-embedding-3-small
MEM0_EMBED_DIMS=1536
OPENAI_API_KEY=sk-...

# === Qdrant VPS ===
MEM0_QDRANT_URL=https://your-vps.example.com:443/qdrant
MEM0_QDRANT_API_KEY=<MCP_BEARER_TOKEN>

# === HTTP server binding ===
MEM0_TRANSPORT=streamable-http
MEM0_HOST=127.0.0.1
MEM0_PORT=8765

# === (Optional) Archive API for /sessions + /compact-summaries ===
ARCHIVE_URL=https://your-vps.example.com/archive
ARCHIVE_AUTH_TOKEN=<archive-token>
USER_ID=thanh

# === (Optional) Corporate proxy ===
HTTP_PROXY=http://proxy.example.com:3128
HTTPS_PROXY=http://proxy.example.com:3128
NO_PROXY=localhost,127.0.0.1
```

### 2. Start server

```powershell
.\mem0-mcp.exe
```

Look for banner showing config loaded + `Uvicorn running on http://127.0.0.1:8765`.

### 3. Register with Claude Code

```powershell
claude mcp add --scope user --transport http mem0 http://127.0.0.1:8765/mcp
```

Open VS Code → Claude Code → `/mcp` → should show `mem0` connected with 18 tools.

## Production setup (auto-start + hidden)

Use the included `setup.ps1` script for fully automated install:
- Creates `%LOCALAPPDATA%\mem0-mcp\` folder (hidden)
- Sets up Task Scheduler for auto-start at logon + auto-restart on crash
- Registers archive auto-upload hourly task
- Installs Claude Code hook to upload archive on `/compact`
- Adds MCP entry to Claude Code

```powershell
.\setup.ps1
```

## CLI modes

The exe supports multi-mode dispatch via argv:

```powershell
.\mem0-mcp.exe                    # Run HTTP server (default)
.\mem0-mcp.exe --upload-archive   # Upload Claude Code transcripts + compact summaries
.\mem0-mcp.exe --install-hooks    # Install Claude Code hooks
```

## Common operations

| Action | Command |
|---|---|
| Stop server | `schtasks /End /TN "Mem0 MCP Server"` |
| Start server | `schtasks /Run /TN "Mem0 MCP Server"` |
| View log | `notepad "$env:LOCALAPPDATA\mem0-mcp\mem0-mcp.log"` |
| Force upload now | `& "$env:LOCALAPPDATA\mem0-mcp\mem0-mcp.exe" --upload-archive` |
| Verify all components | `.\verify-install.ps1` |
| Uninstall | `.\uninstall.ps1` |

## Architecture

```
VS Code Claude Code
      |
      | HTTP POST localhost:8765/mcp
      v
mem0-mcp.exe (PyInstaller bundle, runs hidden)
      |
      |--> mem0ai library
      |       |
      |       |--> OpenAI (embeddings, paid)
      |       |--> Anthropic Claude Haiku (LLM, via Claude Max OAT - FREE)
      |       |--> Qdrant (vector store on VPS)
      |
      |--> Archive API on VPS
              |--> POST /sessions (full transcript)
              |--> POST /compact-summaries (only summaries)
              |--> GET /sessions, /compact-summaries (for search tools)
```

## Tests

42 unit tests run in CI on every push (Ubuntu + Windows × Python 3.10/3.11/3.12 = 6 matrix combos):

```bash
pytest tests/unit/test_archive_pipeline.py \
       tests/unit/test_archive_tools_register.py \
       tests/unit/test_http_server_wrapper.py
```

Categories:
- Archive pipeline (parse session, extract compact, dedup hash, regex patterns)
- Archive tools register (conditional based on ARCHIVE_URL)
- HTTP server wrapper (frozen detection, env loading, defaults)
- Schema regression guards (CompactSummary fields match VPS Pydantic model)

## Troubleshooting

### Server logs "ARCHIVE_URL not set - skipping archive tool registration"
Add `ARCHIVE_URL=...` to `.env` and restart the server (`schtasks /End` + `/Run`).

### Only 11 tools showing in Claude Code (expected 18)
Same as above — archive tools require `ARCHIVE_URL` env var.

### Port 8765 already in use
Change `MEM0_PORT` in `.env` and update Claude Code MCP URL to match.

### Windows Defender quarantines the exe
Add exclusion folder `%LOCALAPPDATA%\mem0-mcp\`. PyInstaller-bundled exes often trigger false positives.

### taskkill respawns server immediately
This is the auto-restart behavior. Use `schtasks /End /TN "Mem0 MCP Server"` to stop without triggering restart.

## License

MIT (same as upstream mem0-mcp-selfhosted).
