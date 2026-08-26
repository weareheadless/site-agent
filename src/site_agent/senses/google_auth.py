"""google_auth.py — credentials for Google read APIs (GA4, Search Console).

Two modes, chosen per sense via config (e.g. ga.auth):

  "sa"    (default) service-account JSON key — the classic path, works when
          the SA is invited to the property.
  "oauth" user-consent refresh token — bypasses org/domain restrictions
          entirely because the OWNER authorizes their own account once.
          Requires env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
          GOOGLE_REFRESH_TOKEN (names remappable via config.env).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_KEY_PATH = "/home/admin/.config/ga4-service-account.json"


class GoogleAuthError(RuntimeError):
    pass


def resolve_key_path(config: dict[str, Any], section: str) -> str:
    conf = config.get(section) or {}
    return str(
        conf.get("key_path")
        or os.environ.get("GA4_SERVICE_ACCOUNT")
        or DEFAULT_KEY_PATH
    )


def service_account_token(key_path: str, scopes: list[str]) -> str:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:
        raise GoogleAuthError("google-auth not installed; run pip install 'site-agent[ga]'") from exc
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=scopes)
    creds.refresh(Request())
    return creds.token


def _env(config: dict[str, Any], name: str) -> str:
    var = str((config.get("env") or {}).get(name, name))
    return os.environ.get(var, "")


def oauth_refresh_token(config: dict[str, Any], scopes: list[str]) -> str:
    client_id = _env(config, "google_client_id")
    client_secret = _env(config, "google_client_secret")
    refresh_token = _env(config, "google_refresh_token")
    if not (client_id and client_secret and refresh_token):
        raise GoogleAuthError(
            "oauth auth configured but missing env vars: "
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN"
        )
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except Exception as exc:  # noqa: BLE001
        raise GoogleAuthError(f"oauth token refresh failed: {exc}") from exc
    token = payload.get("access_token")
    if not token:
        raise GoogleAuthError(f"oauth refresh returned no token: {payload}")
    return token


def get_token(config: dict[str, Any], section: str, scopes: list[str]) -> str:
    conf = config.get(section) or {}
    mode = str(conf.get("auth", "sa"))
    if mode == "oauth":
        return oauth_refresh_token(config, scopes)
    return service_account_token(resolve_key_path(config, section), scopes)


def consent_url(client_id: str, redirect_uri: str, scopes: list[str]) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": " ".join(scopes),
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
            "grant_type": "authorization_code",
        }
    ).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)
