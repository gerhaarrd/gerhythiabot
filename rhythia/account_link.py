"""Shared Rhythia public account linking."""

from __future__ import annotations

import secrets
import string
from typing import Any, TYPE_CHECKING

from rhythia.api_client import RhythiaClient, public_search
from rhythia.api_errors import RhythiaAPIError
from rhythia.linked_accounts import PendingLink

if TYPE_CHECKING:
    from bot.discord_bot import RhythiaBot


class AccountLinkError(Exception):
    pass


CODE_PREFIX = "GERHYTHIA"
CODE_ALPHABET = string.ascii_uppercase + string.digits


async def find_link_candidates(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    text = query.strip()
    if len(text) < 2:
        raise AccountLinkError("Type at least 2 characters from your Rhythia username.")

    try:
        results = await public_search(query=text, limit=limit)
    except RhythiaAPIError as exc:
        raise AccountLinkError(f"Rhythia search failed: {exc}") from exc

    users = results.get("users") or []
    if not isinstance(users, list):
        raise AccountLinkError("Rhythia returned an unexpected search response.")
    return [user for user in users if isinstance(user, dict)]


def create_pending_rhythia_link(
    bot: RhythiaBot,
    *,
    discord_id: int,
    user: dict[str, Any],
) -> PendingLink:
    user_id = user.get("id")
    username = user.get("username") or user.get("computedUsername")
    if user_id is None or not username:
        raise AccountLinkError("Rhythia returned a player without an id or username.")

    code = _verification_code()
    return bot.linked_accounts.save_pending(
        discord_id,
        rhythia_user_id=int(user_id),
        rhythia_username=str(username),
        code=code,
    )


async def verify_pending_rhythia_link(bot: RhythiaBot, *, discord_id: int) -> str:
    pending = bot.linked_accounts.get_pending(discord_id)
    if pending is None:
        raise AccountLinkError(
            "No pending verification. Use `/gerhythia link <username>` first."
        )

    try:
        client = bot.client_for()
        data = await client.get_profile(user_id=pending.rhythia_user_id)
    except RhythiaAPIError as exc:
        raise AccountLinkError(f"Rhythia profile lookup failed: {exc}") from exc

    user = data.get("user") or {}
    about_me = str(user.get("about_me") or "")
    if pending.code not in about_me:
        raise AccountLinkError(
            f"I couldn't find `{pending.code}` in **{pending.rhythia_username}**'s about me yet. "
            "Add the code to your Rhythia profile and try `/gerhythia verify` again."
        )

    username = str(
        user.get("username") or user.get("computedUsername") or pending.rhythia_username
    )
    bot.linked_accounts.save(
        discord_id,
        rhythia_user_id=pending.rhythia_user_id,
        rhythia_username=username,
    )
    bot.linked_accounts.delete_pending(discord_id)
    return username


def _verification_code() -> str:
    suffix = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{CODE_PREFIX}-{suffix}"