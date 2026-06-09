from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import discord
import logging

from rhythia.constants import FEEDBACK_DISCORD_USERNAME
from rhythia.site_urls import beatmap_page_url, leaderboard_page_url, user_profile_url
from rhythia.linked_accounts import LinkedAccountStore

beatmap_url = beatmap_page_url
leaderboard_url = leaderboard_page_url
user_url = user_profile_url

EMBED_COLOR_PROFILE = 0x8B5CF6    # Vibrant Violet
EMBED_COLOR_LEADERBOARD = 0xFBBF24 # Amber Gold
EMBED_COLOR_MAPS = 0x3B82F6        # Bright Blue
EMBED_COLOR_SEARCH = 0x10B981      # Emerald Green
EMBED_COLOR_HELP = 0xEC4899        # Neon Pink
EMBED_COLOR_SCORE = 0xF97316       # Orange
EMBED_COLOR_DARK = 0x0F172A        # Dark (for Tasukete)
EMBED_COLOR_LOGIC = 0x8B5CF6       # Purple (for Logic)
EMBED_COLOR_EASY = 0x10B981        # Green
EMBED_COLOR_MEDIUM = 0xFBBF24      # Yellow
EMBED_COLOR_HARD = 0xEF4444        # Red


def difficulty_to_color(difficulty: Any = None, *, star: Any = None) -> int:
    # If difficulty is a numeric code (1..5) map directly
    try:
        if isinstance(difficulty, (int, float)):
            d = int(difficulty)
            if d == 5:
                return EMBED_COLOR_DARK
            if d == 4:
                return EMBED_COLOR_LOGIC
            if d == 3:
                return EMBED_COLOR_HARD
            if d == 2:
                return EMBED_COLOR_MEDIUM
            if d == 1:
                return EMBED_COLOR_EASY
    except Exception:
        pass

    # If difficulty is a string, match keywords
    if isinstance(difficulty, str):
        v = difficulty.strip().lower()
        if "tasuk" in v:
            return EMBED_COLOR_DARK
        if "logic" in v:
            return EMBED_COLOR_LOGIC
        if "hard" in v:
            return EMBED_COLOR_HARD
        if "medium" in v or "normal" in v:
            return EMBED_COLOR_MEDIUM
        if "easy" in v:
            return EMBED_COLOR_EASY

    # Fallback to starRating if provided
    if isinstance(star, (int, float)):
        try:
            f = float(star)
        except Exception:
            return EMBED_COLOR_MAPS
        if f < 2.0:
            return EMBED_COLOR_EASY
        if f < 4.0:
            return EMBED_COLOR_MEDIUM
        return EMBED_COLOR_HARD

    return EMBED_COLOR_MAPS


def difficulty_to_name(difficulty: Any) -> str | None:
    """Map numeric difficulty codes to human names per project convention.

    5 -> tasukete, 4 -> logic, 3 -> hard, 2 -> medium, 1 -> easy
    """
    try:
        if isinstance(difficulty, (int, float)):
            d = int(difficulty)
            if d == 5:
                return "tasukete"
            if d == 4:
                return "logic"
            if d == 3:
                return "hard"
            if d == 2:
                return "medium"
            if d == 1:
                return "easy"
    except Exception:
        pass
    if isinstance(difficulty, str):
        v = difficulty.strip().lower()
        if v in {"tasukete", "tasuk", "tasuke"}:
            return "tasukete"
        if "logic" in v:
            return "logic"
        if "hard" in v:
            return "hard"
        if "medium" in v or "normal" in v:
            return "medium"
        if "easy" in v:
            return "easy"
    return None


def flag_emoji(country_code: str | None) -> str:
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join(chr(ord(char) + 127397) for char in country_code.upper())


def _num(value: Any, *, decimals: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.{decimals}f}"
    return f"{value:,}"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _duration_ms(value: Any) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return "—"
    total_seconds = int(value / 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _score_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:19].replace("T", " ")
    return parsed.strftime("%m/%d/%Y %H:%M UTC")


def _asset_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    path = quote(parts.path, safe="/%")
    query = quote(parts.query, safe="=&?/:+,%")
    fragment = quote(parts.fragment, safe="")
    return urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def _paginated_footer(
    data: dict[str, Any],
    *,
    extra: str = "",
    user_page: int | None = None,
    user_per_page: int | None = None,
) -> str:
    total = int(data.get("total") or 0)
    # Use user page info if provided, otherwise fall back to API page info
    if user_page is not None:
        page = user_page
        per_page = user_per_page if user_per_page is not None else 10
    else:
        page = int(data.get("currentPage") or 1)
        per_page = int(data.get("viewPerPage") or 0)
    parts = [f"Page {page}", f"{per_page}/page", f"{total:,} total"]
    if extra:
        parts.insert(0, extra)
    return " · ".join(parts)


def help_overview_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Rhythia Bot — Help",
        description=(
            "Welcome to the community bot for Rhythia stats and search! **Not official.**\n\n"
            "Please select a category from the dropdown menu below to see the available commands."
        ),
        color=EMBED_COLOR_HELP,
    )
    embed.set_thumbnail(url="attachment://icon.jpg")
    embed.set_footer(text="Use /gerhythia help anytime")
    return embed


def help_account_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Rhythia Bot — Help (Account)",
        description=(
            "`/gerhythia link` — Start profile ownership verification\n"
            "`/gerhythia verify` — Finish linking after adding the code to your profile\n"
            "`/gerhythia unlink` — Remove your link\n"
            "`/gerhythia account` — Show which account is linked"
        ),
        color=EMBED_COLOR_HELP,
    )
    embed.set_thumbnail(url="attachment://icon.jpg")
    embed.set_footer(text="Linking stores only public Rhythia profile info")
    return embed


def help_stats_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Rhythia Bot — Help (Stats & Search)",
        description=(
            "`/gerhythia profile` — Your profile (or another player's username)\n"
            "`/gerhythia search` — Search players & beatmaps (no link required)\n"
            "`/gerhythia leaderboard` — Skill leaderboard (optional country filter)\n"
            "`/gerhythia nearby` — Show players ranked near you or a target player\n"
            "`/gerhythia milestone` — Show competitive milestones and SP/ranks needed\n"
            "`/gerhythia maps search` — Browse/filter beatmaps\n"
            "`/gerhythia maps new` — Show the most recently added beatmaps\n"
            "`/gerhythia beatmap` — Show one beatmap by id or title\n"
            "`/gerhythia random` — Show a random beatmap from the library\n"
            "`/gerhythia recent` — Show a player's latest public score\n"
            "`/gerhythia score` — Look up any score by its ID\n"
            "`/gerhythia scores` — Full score history today (paginated)\n"
            "`/gerhythia top` — Show a player's top 5 public scores\n"
            "`/gerhythia compare` — Compare stats of two players side by side\n"
            "`/gerhythia today` — Show player's activity & best score today\n"
            "`/gerhythia stats` — Show global Rhythia statistics\n"
            "`/gerhythia suggest` — Suggest Ranked maps based on your top plays"
        ),
        color=EMBED_COLOR_HELP,
    )
    embed.set_thumbnail(url="attachment://icon.jpg")
    embed.set_footer(text="rhythia.com · Browse player stats and beatmaps")
    return embed


def help_utils_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Rhythia Bot — Help (Utilities & Feedback)",
        description=(
            "**Utilities**\n"
            "`/gerhythia ping` — Bot latency & Rhythia API status\n\n"
            "**Feedback**\n"
            "Questions, bugs, or suggestions? Join our [Discord](https://discord.gg/r5khc9TN)!."
        ),
        color=EMBED_COLOR_HELP,
    )
    embed.set_thumbnail(url="attachment://icon.jpg")
    embed.set_footer(text="Not an official bot · Use /gerhythia help anytime")
    return embed


def help_embed() -> discord.Embed:
    return help_overview_embed()



def profile_embed(
    data: dict[str, Any],
    *,
    title_prefix: str = "",
) -> discord.Embed:
    user = data.get("user") or {}
    username = user.get("username") or user.get("computedUsername") or "Unknown"
    user_id = user.get("id")
    flag = flag_emoji(user.get("flag"))
    profile_link = user_url(user_id) if user_id else "https://rhythia.com"

    embed = discord.Embed(
        title=_truncate(f"{title_prefix}{flag} {username}".strip(), 256),
        url=profile_link,
        color=EMBED_COLOR_PROFILE,
    )

    avatar = user.get("avatar_url") or user.get("profile_image")
    avatar_url = _asset_url(avatar)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    clan = user.get("clan")
    clan_text = clan.get("acronym") if isinstance(clan, dict) else "—"

    embed.add_field(
        name="🏆 RP",
        value=f"**{_num(user.get('skill_points'), decimals=2)}** RP",
        inline=True,
    )
    embed.add_field(
        name="🌀 Spin",
        value=f"**{_num(user.get('spin_skill_points'), decimals=2)}** SP",
        inline=True,
    )
    embed.add_field(name="🎮 Plays", value=_num(user.get("play_count")), inline=True)
    embed.add_field(
        name="🌍 Global",
        value=f"**#{_num(user.get('position'))}**",
        inline=True,
    )
    embed.add_field(
        name="📍 Country",
        value=f"**#{_num(user.get('country_position'))}**",
        inline=True,
    )

    status_parts: list[str] = []
    if user.get("is_online"):
        status_parts.append("🟢 Online")
    else:
        status_parts.append("⚫ Offline")
    # Show linked status from local DB instead of Rhythia's public `verified` flag
    try:
        store = LinkedAccountStore()
        linked = store.get_by_rhythia_user_id(int(user.get("id") or 0))
    except Exception:
        linked = None
    if linked is not None:
        status_parts.append("🔗 Linked")
    status_parts.append(str(user.get("activity_status") or "—").capitalize())
    embed.add_field(name="📡 Status", value=" · ".join(status_parts), inline=False)

    if clan_text != "—":
        embed.add_field(name="Clan", value=clan_text, inline=True)

    embed.set_footer(text=f"ID {user_id} · rhythia.com")
    return embed


def leaderboard_embed(
    data: dict[str, Any],
    user_page: int | None = None,
    *,
    limit: int = 10,
    country: str | None = None,
    spin: bool = False,
    user_position: int | None = None,
) -> discord.Embed:
    entries = data.get("leaderboard") or []
    # Use user_page to calculate ranks and slice the correct portion
    if user_page is not None:
        start_rank = (user_page - 1) * limit
        # Calculate offset within the API page (API returns 50 items per page)
        api_page_size = int(data.get("viewPerPage") or 50)
        offset = ((user_page - 1) * limit) % api_page_size
        entries = entries[offset:offset + limit]
    else:
        # Fallback to API page info
        page = int(data.get("currentPage") or 1)
        per_page = int(data.get("viewPerPage") or 50)
        start_rank = (page - 1) * per_page
        entries = entries[:limit]

    filter_bits: list[str] = []
    if country:
        filter_bits.append(f"{flag_emoji(country)} {country.upper()}")
    else:
        filter_bits.append("🌍 Global")
    if spin:
        filter_bits.append("Spin")

    lines: list[str] = []
    for index, entry in enumerate(entries, start=1):
        rank = start_rank + index
        flag = flag_emoji(entry.get("flag"))
        username = entry.get("username", "?")
        user_id = entry.get("id")
        name = (
            f"[{username}]({user_url(user_id)})"
            if user_id
            else f"**{username}**"
        )
        skill = _num(entry.get("skill_points"), decimals=1)
        clans = entry.get("clans")
        clan = f" `{clans['acronym']}`" if isinstance(clans, dict) else ""
        if rank == 1:
            rank_str = "🥇"
        elif rank == 2:
            rank_str = "🥈"
        elif rank == 3:
            rank_str = "🥉"
        else:
            rank_str = f"`#{rank:>3}`"

        lines.append(f"{rank_str} {flag} {name} — **{skill}** SP{clan}")

    title = "🏆 Rhythia Leaderboard"
    if country:
        title += f" · {country.upper()}"

    embed = discord.Embed(
        title=title,
        url=leaderboard_url(country=country),
        description="\n".join(lines) if lines else "_No players on this page._",
        color=EMBED_COLOR_LEADERBOARD,
    )

    # Use provided user_position, fall back to data.get("userPosition")
    raw_position = user_position if user_position is not None else data.get("userPosition")
    # Convert to int when possible and only show if > 0
    if raw_position is not None:
        try:
            pos_int = int(raw_position)
            if pos_int > 0:
                embed.add_field(name="Your rank", value=f"**#{pos_int:,}**", inline=False)
        except (TypeError, ValueError):
            # If position isn't an int, skip showing it
            pass

    embed.set_footer(text=_paginated_footer(
        data,
        extra=" · ".join(filter_bits),
        user_page=user_page,
        user_per_page=limit,
    ))
    return embed


def beatmaps_embed(
    data: dict[str, Any],
    user_page: int | None = None,
    *,
    limit: int = 10,
    filters_label: str = "",
) -> discord.Embed:
    beatmaps = data.get("beatmaps") or []

    # Slice the correct portion of beatmaps based on user_page
    if user_page is not None:
        api_page_size = int(data.get("viewPerPage") or 50)
        offset = ((user_page - 1) * limit) % api_page_size
        beatmaps = beatmaps[offset:offset + limit]
    else:
        beatmaps = beatmaps[:limit]

    lines: list[str] = []
    for bm in beatmaps:
        bm_id = bm.get("id", "?")
        stars = bm.get("starRating")
        stars_text = f"{stars:.2f}★" if isinstance(stars, (int, float)) else "—"
        diff_val = bm.get("difficulty") or bm.get("diffName") or bm.get("starRating")
        diff_name = difficulty_to_name(diff_val)
        diff_text = f"{diff_name.capitalize()}" if diff_name else "—"
        title = _truncate(bm.get("title") or "?", 55)
        mapper = bm.get("ownerUsername", "?")
        status = bm.get("status", "—")
        link = beatmap_url(bm_id)
        owner_id = bm.get("owner")
        if owner_id:
            mapper_part = f"[**{mapper}**]({user_url(owner_id)})"
        else:
            mapper_part = f"**{mapper}**"
        
        lines.append(
            f"**[{title}]({link})**\n"
            f"> 🎫 `#{bm_id}`  |  ⭐ **{stars_text}**  |  🎚️ **{diff_text}**  |  🏷️ **{status}**  |  👤 {mapper_part}"
        )

    # If first beatmap has difficulty info, use it for embed color
    list_color = EMBED_COLOR_MAPS
    if beatmaps:
        first = beatmaps[0]
        list_color = difficulty_to_color(first.get("difficulty") or first.get("diffName") or first.get("starRating"), star=first.get("starRating"))

    embed = discord.Embed(
        title="🎵 Beatmaps",
        url="https://rhythia.com/maps",
        description="\n\n".join(lines) if lines else "_No maps found._",
        color=list_color,
    )
    if filters_label:
        embed.set_footer(text=_paginated_footer(
            data,
            extra=filters_label,
            user_page=user_page,
            user_per_page=limit,
        ))
    else:
        embed.set_footer(text=_paginated_footer(
            data,
            user_page=user_page,
            user_per_page=limit,
        ))
    return embed


def beatmap_embed(beatmap: dict[str, Any]) -> discord.Embed:
    bm_id = beatmap.get("id")
    title = beatmap.get("title") or "Unknown beatmap"
    mapper = beatmap.get("ownerUsername") or "Unknown mapper"
    owner_id = beatmap.get("owner")
    stars = beatmap.get("starRating")
    stars_text = f"{stars:.2f}★" if isinstance(stars, (int, float)) else "—"
    status = beatmap.get("status") or "—"
    length = _duration_ms(beatmap.get("length"))
    playcount = beatmap.get("playcount")
    playcount = _num(playcount) if playcount is not None else "—"
    map_url = beatmap_url(bm_id) if bm_id else "https://rhythia.com/maps"

    color = difficulty_to_color(beatmap.get("difficulty") or beatmap.get("diffName") or beatmap.get("beatmapDifficulty"), star=stars)
    embed = discord.Embed(
        title=_truncate(title, 256),
        url=map_url,
        color=color,
    )
    image = _asset_url(beatmap.get("image"))
    if image:
        embed.set_image(url=image)
    owner_avatar = _asset_url(beatmap.get("ownerAvatar"))
    if owner_avatar:
        embed.set_thumbnail(url=owner_avatar)

    mapper_text = (
        f"[{mapper}]({user_url(owner_id)})" if owner_id else mapper
    )
    embed.add_field(name="Mapper", value=mapper_text, inline=True)
    diff_val = beatmap.get("difficulty") or beatmap.get("diffName") or beatmap.get("beatmapDifficulty") or beatmap.get("starRating")
    diff_name = difficulty_to_name(diff_val)
    diff_display = f"**{diff_name.capitalize()}**" if diff_name else "—"
    embed.add_field(name="Difficulty", value=diff_display, inline=True)
    embed.add_field(name="Stars", value=f"**{stars_text}**", inline=True)
    embed.add_field(name="Status", value=f"**{status}**", inline=True)
    embed.add_field(name="Length", value=length, inline=True)
    embed.add_field(name="Playcount", value=playcount, inline=True)
    embed.add_field(name="ID", value=f"`{bm_id}`", inline=True)

    description = beatmap.get("description")
    if description:
        embed.description = _truncate(str(description), 500)
    tags = beatmap.get("tags")
    if tags:
        embed.add_field(name="Tags", value=_truncate(str(tags), 512), inline=False)

    embed.set_footer(text="rhythia.com/maps")
    return embed


def recent_score_embed(score: dict[str, Any], *, username: str, stars_override: Any = None) -> discord.Embed:
    title = score.get("beatmapTitle") or score.get("songId") or "Unknown beatmap"
    score_id = score.get("id")
    awarded = score.get("awarded_sp")
    stars = score.get("beatmapDifficulty") or score.get("difficulty")
    misses = score.get("misses")
    notes = score.get("beatmapNotes")
    speed = score.get("speed")
    passed = score.get("passed")
    spin = score.get("spin")
    replay_url = score.get("replay_url")

    embed = discord.Embed(
        title=_truncate(f"{username}'s recent score", 256),
        description=f"**{_truncate(str(title), 180)}**",
        color=difficulty_to_color(stars, star=stars),
        url=replay_url or None,
    )
    embed.add_field(name="SP", value=f"**{_num(awarded)}**", inline=True)
    # Show difficulty name when difficulty is the numeric code (1..5),
    # otherwise show star rating if available.
    diff_name = difficulty_to_name(stars)
    if diff_name:
        diff_value = f"**{diff_name.capitalize()}**"
    else:
        diff_value = f"**{_num(stars, decimals=2)}★**" if stars is not None else "—"
    embed.add_field(name="Difficulty", value=diff_value, inline=True)

    # If an explicit star value was provided (from beatmap lookup), show it
    # next to Difficulty in its own inline field.
    if stars_override is not None:
        try:
            star_text = f"**{float(stars_override):.2f}★**"
        except Exception:
            star_text = _num(stars_override)
        embed.add_field(name="Stars", value=star_text, inline=True)
    embed.add_field(name="Misses", value=_num(misses), inline=True)
    embed.add_field(name="Notes", value=_num(notes), inline=True)
    embed.add_field(
        name="Speed",
        value=f"{float(speed):.2f}x" if isinstance(speed, (int, float)) else "—",
        inline=True,
    )
    embed.add_field(
        name="Mode",
        value="Spin" if spin else "Classic",
        inline=True,
    )
    embed.add_field(
        name="Result",
        value="Passed" if passed else "Failed",
        inline=True,
    )
    embed.add_field(name="Played", value=_score_time(score.get("created_at")), inline=True)
    if replay_url:
        embed.add_field(name="Replay", value=f"[Download]({replay_url})", inline=True)
    embed.set_footer(text=f"Score ID {score_id}")
    return embed


def search_results_embed(
    data: dict[str, Any],
    *,
    query: str,
    limit_users: int = 8,
    limit_maps: int = 5,
) -> discord.Embed:
    users = data.get("users") or []
    maps = data.get("beatmaps") or []

    parts: list[str] = []

    if users:
        parts.append("**Players**")
        for u in users[:limit_users]:
            uid = u.get("id")
            name = u.get("username", "?")
            flag = flag_emoji(u.get("flag"))
            link = user_url(uid) if uid else "https://rhythia.com"
            parts.append(f"> {flag} [{name}]({link})  |  `ID {uid}`")

    if maps:
        parts.append("\n🎵 **Beatmaps**")
        for bm in maps[:limit_maps]:
            bm_id = bm.get("id")
            title = _truncate(bm.get("title") or "?", 50)
            stars = bm.get("starRating")
            stars_text = f"⭐ **{stars:.2f}★**" if isinstance(stars, (int, float)) else ""
            link = beatmap_url(bm_id) if bm_id else "https://rhythia.com/maps"
            parts.append(f"> [{title}]({link})  |  {stars_text}  |  `#{bm_id}`")

    if not parts:
        description = f"No results for **{query}**."
    else:
        description = "\n".join(parts)

    embed = discord.Embed(
        title=f"Search: {query}",
        description=_truncate(description, 4000),
        color=EMBED_COLOR_SEARCH,
        url="https://rhythia.com",
    )
    embed.set_footer(text="Use /gerhythia profile username:… for full stats")
    return embed
