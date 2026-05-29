"""OAuth 2.1 + RFC 7591 Dynamic Client Registration for Claude Desktop App.

Minimal single-tenant implementation: Claude Desktop registers as a client,
goes through auth code flow with PKCE (S256), receives an access token that
maps internally to MCP_BEARER_TOKEN.

Endpoints (mounted under /mcp prefix by mcp-http-server/app.py):

- GET  /.well-known/oauth-protected-resource   resource metadata (RFC 9728)
- GET  /.well-known/oauth-authorization-server authorization server metadata (RFC 8414)
- POST /register                                Dynamic Client Registration (RFC 7591)
- GET  /authorize                               authorization code endpoint (auto-approve)
- POST /token                                   token exchange with PKCE

Auto-approve design: this is a single-user setup, so /authorize redirects
back to the client with a code immediately — no user consent prompt.

State storage: in-memory dicts. Restart clears all clients + tokens.
For single-user use this is acceptable; a multi-user deployment should
persist to Postgres.
"""
from __future__ import annotations
import base64
import hashlib
import os
import secrets
import time
import uuid
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse


ISSUER = os.environ.get("OAUTH_ISSUER", "https://claude.hangocthanh.io.vn/mcp")
INTERNAL_TOKEN = os.environ.get("MCP_BEARER_TOKEN", "")

# In-memory state — single user, restart resets
CLIENTS: dict[str, dict] = {}
AUTH_CODES: dict[str, dict] = {}
ACCESS_TOKENS: dict[str, dict] = {}

CODE_LIFETIME_SECONDS = 600         # 10 min
TOKEN_LIFETIME_SECONDS = 3600       # 1 hour

router = APIRouter()


# ============================================================
# Helpers
# ============================================================

def _pkce_verify(verifier: str, challenge: str) -> bool:
    """Verify PKCE: SHA256(verifier) base64url-encoded == challenge."""
    h = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(h).decode("ascii").rstrip("=")
    return secrets.compare_digest(computed, challenge)


def _now() -> float:
    return time.time()


def reset_state() -> None:
    """Test helper — clear all state."""
    CLIENTS.clear()
    AUTH_CODES.clear()
    ACCESS_TOKENS.clear()


# ============================================================
# Discovery endpoints
# ============================================================

@router.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata():
    """RFC 9728 — Protected Resource Metadata."""
    return {
        "resource": ISSUER,
        "authorization_servers": [ISSUER],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata():
    """RFC 8414 — Authorization Server Metadata."""
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "registration_endpoint": f"{ISSUER}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp"],
    }


# ============================================================
# Dynamic Client Registration (RFC 7591)
# ============================================================

@router.post("/register")
async def register_client(request: Request):
    """RFC 7591 — Dynamic Client Registration.

    Accepts client metadata, returns assigned client_id. No secret since
    public client (PKCE provides security).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid_client_metadata: body not JSON")

    redirect_uris = body.get("redirect_uris", [])
    if not redirect_uris or not isinstance(redirect_uris, list):
        raise HTTPException(400, "invalid_redirect_uri: redirect_uris required")

    client_id = str(uuid.uuid4())
    CLIENTS[client_id] = {
        "client_id": client_id,
        "redirect_uris": redirect_uris,
        "grant_types": body.get("grant_types", ["authorization_code"]),
        "response_types": body.get("response_types", ["code"]),
        "client_name": body.get("client_name", "Unknown"),
        "token_endpoint_auth_method": "none",
        "registered_at": _now(),
    }

    return {
        "client_id": client_id,
        "redirect_uris": redirect_uris,
        "grant_types": CLIENTS[client_id]["grant_types"],
        "response_types": CLIENTS[client_id]["response_types"],
        "token_endpoint_auth_method": "none",
        "client_name": CLIENTS[client_id]["client_name"],
    }


# ============================================================
# Authorization endpoint
# ============================================================

@router.get("/authorize")
def authorize(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    state: Optional[str] = None,
    scope: Optional[str] = None,
):
    """OAuth 2.1 authorization endpoint with PKCE.

    Auto-approves (single user) — no consent UI. Returns 302 redirect
    to client's redirect_uri with code (and state if provided).
    """
    if response_type != "code":
        raise HTTPException(400, "unsupported_response_type")
    if code_challenge_method != "S256":
        raise HTTPException(400, "unsupported_code_challenge_method")
    if client_id not in CLIENTS:
        raise HTTPException(400, "invalid_client")
    if redirect_uri not in CLIENTS[client_id]["redirect_uris"]:
        raise HTTPException(400, "invalid_redirect_uri")
    if not code_challenge or len(code_challenge) < 32:
        raise HTTPException(400, "invalid_request: code_challenge too short")

    code = secrets.token_urlsafe(32)
    AUTH_CODES[code] = {
        "client_id": client_id,
        "code_challenge": code_challenge,
        "redirect_uri": redirect_uri,
        "scope": scope or "mcp",
        "expires_at": _now() + CODE_LIFETIME_SECONDS,
    }

    params: dict[str, str] = {"code": code}
    if state:
        params["state"] = state
    redirect = f"{redirect_uri}?{urlencode(params)}"
    return RedirectResponse(url=redirect, status_code=302)


# ============================================================
# Token endpoint
# ============================================================

@router.post("/token")
async def token_exchange(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    code_verifier: str = Form(...),
):
    """OAuth 2.1 token endpoint with PKCE.

    Exchanges authorization code + PKCE verifier for access token.
    """
    if grant_type != "authorization_code":
        return JSONResponse(
            {"error": "unsupported_grant_type"}, status_code=400
        )
    auth = AUTH_CODES.get(code)
    if not auth:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    # One-time use
    del AUTH_CODES[code]

    if auth["client_id"] != client_id:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if auth["redirect_uri"] != redirect_uri:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if _now() > auth["expires_at"]:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if not _pkce_verify(code_verifier, auth["code_challenge"]):
        return JSONResponse(
            {"error": "invalid_grant", "error_description": "PKCE verification failed"},
            status_code=400,
        )

    access_token = secrets.token_urlsafe(32)
    ACCESS_TOKENS[access_token] = {
        "client_id": client_id,
        "expires_at": _now() + TOKEN_LIFETIME_SECONDS,
        "scope": auth.get("scope", "mcp"),
    }

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": TOKEN_LIFETIME_SECONDS,
        "scope": auth.get("scope", "mcp"),
    }


# ============================================================
# Token verification (called from main app auth middleware)
# ============================================================

def verify_token(token: str) -> bool:
    """Return True if token is valid (either internal or OAuth-issued)."""
    if not token:
        return False
    # Internal static token always valid (for direct API access)
    if INTERNAL_TOKEN and secrets.compare_digest(token, INTERNAL_TOKEN):
        return True
    info = ACCESS_TOKENS.get(token)
    if not info:
        return False
    if _now() > info["expires_at"]:
        del ACCESS_TOKENS[token]
        return False
    return True
