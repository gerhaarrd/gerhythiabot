"""Shared Rhythia account linking (OAuth callback and manual token)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from rhythia.oauth_login import discord_user_id_from_session_jwt

if TYPE_CHECKING:
    from bot.discord_bot import RhythiaBot


class AccountLinkError(Exception):
    pass


def extract_access_token_from_paste(raw: str) -> str:
    """From JWT alone, Supabase LocalStorage JSON object, or full rhythia.com URL with #access_token=..."""
    text = raw.strip()
    if not text:
        raise AccountLinkError("Paste your access_token or the full URL from the address bar.")

    try:
        import json
        data = json.loads(text)
        if isinstance(data, dict) and "access_token" in data:
            return str(data["access_token"])
    except Exception:
        pass

    if "#" in text:
        text = text.split("#", 1)[1]

    if "access_token=" in text:
        params = parse_qs(text, keep_blank_values=False)
        token = (params.get("access_token") or [None])[0]
        if token:
            return str(token)

    if text.count(".") >= 2:
        return text

    raise AccountLinkError(
        "Could not find access_token. After logging in on rhythia.com, copy the full URL "
        "or the long token that starts with eyJ... (or copy the Local Storage auth token)"
    )


def save_rhythia_link(
    bot: RhythiaBot,
    *,
    discord_id: int,
    access_token: str,
) -> str:
    jwt_discord_id = discord_user_id_from_session_jwt(access_token)
    if jwt_discord_id != str(discord_id):
        raise AccountLinkError(
            "This Rhythia session belongs to a different Discord account. "
            "Log in with the same Discord account you use on this server."
        )

    try:
        with RhythiaClient(access_token) as client:
            data = client.get_profile()
    except RhythiaAPIError as exc:
        raise AccountLinkError(f"Rhythia API error: {exc}") from exc

    user = data.get("user") or {}
    username = user.get("username") or user.get("computedUsername") or "?"
    user_id = user.get("id")

    bot.linked_accounts.save(
        discord_id,
        session_token=access_token,
        rhythia_user_id=int(user_id) if user_id is not None else None,
        rhythia_username=str(username),
    )
    return str(username)
