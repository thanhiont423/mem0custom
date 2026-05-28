# mem0custom

Self-hosted memory server combining **mem0** (vector facts) and **transcript archive** (full chat history) on a single VPS. Used with Claude Max via Claude Code, Claude App, and ChatGPT App.

Production deployment: `claude.hangocthanh.io.vn` (VPS Ubuntu 24.04, IP 45.119.87.220).

## Architecture

```
Client (Mac / Windows)              VPS (claude.hangocthanh.io.vn)
┌─────────────────────────┐         ┌──────────────────────────────┐
│ Claude Code (stdio MCP) │────────▶│  Caddy (TLS + auth)          │
│ Claude App (HTTP MCP)   │────────▶│  ├── /qdrant    → Qdrant     │
│ ChatGPT App (HTTP/MCP)  │────────▶│  ├── /archive   → archive-api│
│ ChatGPT GPT Action      │────────▶│  └── /mcp       → mcp-http   │
└─────────────────────────┘         │                              │
                                    │  Storage:                    │
                                    │  - Qdrant (vector facts)     │
                                    │  - Postgres (sessions)       │
                                    │  - R2/B2 (transcripts)*      │
                                    └──────────────────────────────┘
                                    *only on new-features branch
```

## Two storage layers

| Layer | Purpose | Backend | Search |
|---|---|---|---|
| **mem0 facts** | "AI nhớ về tôi" — short extracted facts injected when chatting | Qdrant vectors | Semantic |
| **Transcript archive** | "Tôi muốn xem lại" — full conversation history | Postgres + (R2 on new-features) | Keyword (+ semantic on new-features) |

## Branches

- **`main`** — current production code (mem0 + archive layer with ILIKE search, full transcript in Postgres JSONB). Reflects the deployed state as of 2026-05-28.
- **`new-features`** — 5 enhancements on top of `main`:
  1. **LLM-based summary** — replace `first_user[:200]` with Haiku-generated summary via OAT Max
  2. **Semantic search** — embed summaries → Qdrant collection `chat_summaries`
  3. **Hybrid R2/B2 storage** — gzipped transcripts on object storage, only metadata in Postgres
  4. **`load_context_for_continuation` MCP tool** — RAG-based context loader for continuing past conversations
  5. **Multi-platform support** — `mcp-http-server` for Claude App + ChatGPT App, OpenAPI for ChatGPT Custom GPT

## Quick start (current `main` branch)

```bash
# On VPS
git clone https://github.com/thanhiont423/mem0custom.git
cd mem0custom
cp .env.example .env
# Edit .env: set QDRANT_API_KEY, POSTGRES_PASSWORD, MCP_BEARER_TOKEN, ARCHIVE_AUTH_TOKEN
docker compose up -d --build
```

See `docs/plan-trien-khai-memory-server-mac-windows.md` for full deployment guide (Vietnamese, 4200+ lines, copy-paste-runnable).

## Repo layout

```
mem0custom/
├── README.md
├── docker-compose.yml          # Stack: Qdrant + Postgres + archive-api + Caddy
├── Caddyfile                   # HTTPS reverse proxy + auth
├── .env.example
├── archive-api/                # FastAPI for transcript CRUD
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
├── scripts/                    # Client-side scripts (run on Mac/Windows)
│   ├── archive-upload.py       # Uploads ~/.claude/projects/*.jsonl → VPS
│   ├── archive-mcp.py          # stdio MCP for Claude Code
│   ├── archive-env.example.sh
│   └── archive-env.example.ps1
└── docs/
    └── plan-trien-khai-memory-server-mac-windows.md
```

## Auth model

Single bearer token per service:

- `MCP_BEARER_TOKEN` — clients use this to call `/qdrant/*` (Caddy verifies, swaps for real Qdrant key)
- `ARCHIVE_AUTH_TOKEN` — clients use this in `Authorization: Bearer <token>` to call `/archive/*`

Both tokens generated via `openssl rand -hex 32` on first deploy.

## License

Personal use. Not affiliated with mem0.ai or Anthropic.
