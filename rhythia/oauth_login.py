"""Rhythia Discord login URL builder and session JWT parsing."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin

from rhythia.config import RHYTHIA_OAUTH_BASE_URL

# Supabase only allows Rhythia's own URLs — use localhost so the browser exposes
# the access_token in the address bar for the user to copy & paste into Discord.
RHYTHIA_LOGIN_REDIRECT = os.environ.get(
    "RHYTHIA_LOGIN_REDIRECT", "http://127.0.0.1:8765/callback"
).strip()


def build_login_url() -> str:
    """OAuth URL that redirects to RHYTHIA_LOGIN_REDIRECT after login."""
    params = {"provider": "discord", "redirect_to": RHYTHIA_LOGIN_REDIRECT}
    query = urlencode(params)
    return f"{urljoin(RHYTHIA_OAUTH_BASE_URL, '/auth/v1/authorize')}?{query}"


def discord_user_id_from_session_jwt(access_token: str) -> str | None:
    """ID do Discord embutido no JWT após login (campo provider_id)."""
    try:
        payload_segment = access_token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
    except (IndexError, json.JSONDecodeError, ValueError):
        return None

    metadata = payload.get("user_metadata") or {}
    provider_id = metadata.get("provider_id")
    if provider_id:
        return str(provider_id)

    app_metadata = payload.get("app_metadata") or {}
    if app_metadata.get("provider") == "discord":
        return str(payload.get("sub") or "")

    return None


def session_token_expires_at(access_token: str) -> datetime | None:
    """Parse the JWT exp claim from a Rhythia session token."""
    try:
        payload_segment = access_token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
    except (IndexError, json.JSONDecodeError, ValueError):
        return None

    exp = payload.get("exp")
    if exp is None:
        return None

    try:
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def session_token_is_expired(access_token: str, now: datetime | None = None) -> bool:
    expires_at = session_token_expires_at(access_token)
    if expires_at is None:
        return False
    return expires_at <= (now or datetime.now(timezone.utc))
