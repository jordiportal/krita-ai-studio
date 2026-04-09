"""
Microsoft Entra ID (single-tenant) OAuth2 + OpenID Connect helpers.
"""

import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx
import jwt
from jwt import PyJWKClient

# JWKS cache (url, fetched_at, client)
_jwks_cache: Tuple[Optional[str], float, Optional[PyJWKClient]] = (None, 0.0, None)
_JWKS_TTL = 3600


def oauth_env_configured() -> bool:
    cid = (os.getenv("MICROSOFT_CLIENT_ID") or "").strip()
    sec = (os.getenv("MICROSOFT_CLIENT_SECRET") or "").strip()
    tenant = (os.getenv("MICROSOFT_TENANT_ID") or "").strip()
    redir = (os.getenv("OAUTH_REDIRECT_URI") or "").strip()
    return bool(cid and sec and tenant and redir)


def get_oauth_admin_emails() -> set:
    raw = os.getenv("OAUTH_ADMIN_EMAILS", "") or ""
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def get_app_public_url() -> str:
    return (os.getenv("APP_PUBLIC_URL") or "http://localhost:3333").rstrip("/")


def allow_legacy_login() -> bool:
    return (os.getenv("ALLOW_LEGACY_LOGIN", "true") or "true").lower() in ("1", "true", "yes")


def cookie_secure() -> bool:
    return (os.getenv("COOKIE_SECURE", "false") or "").lower() in ("1", "true", "yes")


def build_authorize_url(state: str) -> str:
    tenant = (os.getenv("MICROSOFT_TENANT_ID") or "").strip()
    client_id = (os.getenv("MICROSOFT_CLIENT_ID") or "").strip()
    redirect_uri = (os.getenv("OAUTH_REDIRECT_URI") or "").strip()
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    from urllib.parse import urlencode

    q = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": "openid profile email",
            "state": state,
        }
    )
    return f"{base}?{q}"


def _get_jwks_client(tenant: str) -> PyJWKClient:
    global _jwks_cache
    url = f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
    now = time.time()
    cached_url, ts, client = _jwks_cache
    if client and cached_url == url and now - ts < _JWKS_TTL:
        return client
    client = PyJWKClient(url)
    _jwks_cache = (url, now, client)
    return client


def validate_microsoft_id_token(id_token: str) -> Dict[str, Any]:
    tenant = (os.getenv("MICROSOFT_TENANT_ID") or "").strip()
    client_id = (os.getenv("MICROSOFT_CLIENT_ID") or "").strip()
    if not tenant or not client_id:
        raise ValueError("OAuth not configured")

    jwks = _get_jwks_client(tenant)
    signing_key = jwks.get_signing_key_from_jwt(id_token)
    issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
    payload = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=client_id,
        issuer=issuer,
        options={"verify_aud": True, "verify_iss": True},
    )
    tid = payload.get("tid")
    if tid and tid.lower() != tenant.lower():
        raise ValueError("Invalid token tenant")
    return payload


async def exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    tenant = (os.getenv("MICROSOFT_TENANT_ID") or "").strip()
    client_id = (os.getenv("MICROSOFT_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("MICROSOFT_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("OAUTH_REDIRECT_URI") or "").strip()
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
    if r.status_code != 200:
        raise ValueError(f"Token exchange failed: {r.status_code} {r.text[:500]}")
    return r.json()
