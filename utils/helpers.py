from __future__ import annotations

import logging
from io import BytesIO
from datetime import datetime
import aiohttp
import discord
from discord import app_commands

from rhythia.constants import COUNTRY_CHOICES

logger = logging.getLogger(__name__)


async def country_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    try:
        cur = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for name, code in COUNTRY_CHOICES:
            if cur in name.lower() or cur in code.lower() or not cur:
                label = f"{name} ({code})" if code else name
                choices.append(app_commands.Choice(name=label, value=code or "GLOBAL"))
            if len(choices) >= 25:
                break
        return choices
    except discord.NotFound:
        return []


def _normalize_country(value: str | None) -> str | None:
    if not value or value.upper() in {"", "GLOBAL"}:
        return None
    code = value.strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise ValueError("Invalid country. Use a 2-letter ISO code (e.g. BR, US).")
    return code


def _maps_filter_label(
    *,
    query: str,
    author: str,
    status: str,
    min_stars: float,
    max_stars: float,
) -> str:
    bits: list[str] = []
    if query:
        bits.append(f'q="{query}"')
    if author:
        bits.append(f'mapper="{author}"')
    if status:
        bits.append(status)
    if min_stars > 0 or max_stars < 20:
        bits.append(f"★ {min_stars}–{max_stars}")
    return " · ".join(bits) if bits else "Recent"


def _exact_user(users: list[dict[str, any]], query: str) -> dict[str, any] | None:
    q = query.lower()
    return next((u for u in users if (u.get("username") or "").lower() == q), None)


def _exact_username_match(users: list[dict[str, any]], query: str) -> bool:
    return _exact_user(users, query) is not None


def _sorted_scores_by_created_at(scores: list[any]) -> list[dict[str, any]]:
    typed_scores = [score for score in scores if isinstance(score, dict)]
    return sorted(
        typed_scores,
        key=lambda score: str(score.get("created_at") or ""),
        reverse=True,
    )


async def _beatmap_image_file(beatmap: dict[str, any] | None, session: aiohttp.ClientSession | None = None) -> discord.File | None:
    if beatmap is None:
        return None

    image_url = beatmap.get("image")
    if not isinstance(image_url, str) or not image_url.strip():
        return None

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with session.get(image_url, timeout=timeout) as response:
            if not response.ok:
                return None

            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            extensions = {
                "image/gif": "gif",
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/webp": "webp",
            }
            extension = extensions.get(content_type)
            if extension is None:
                return None

            content = await response.read()
            if len(content) > 8_000_000:
                return None

            beatmap_id = beatmap.get("id") or "cover"
            return discord.File(
                BytesIO(content),
                filename=f"beatmap-{beatmap_id}.{extension}",
            )
    except aiohttp.ClientError:
        return None
    finally:
        if close_session:
            await session.close()


def _date_mmddyyyy(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%m/%d/%Y")
    except ValueError:
        return value[:10]


__all__ = [
    "country_autocomplete",
    "_exact_username_match",
    "_exact_user",
    "_sorted_scores_by_created_at",
    "_date_mmddyyyy",
    "_beatmap_image_file",
]
