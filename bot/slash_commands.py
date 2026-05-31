from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
import discord
from discord import app_commands
from discord.ext import commands

from bot.discord_bot import RhythiaBot
from bot.link_account_ui import LinkView, link_instructions_embed
from rhythia.api_client import RhythiaClient, public_search
from rhythia.api_errors import RhythiaAPIError
from rhythia.constants import COUNTRY_CHOICES, MAP_STATUS_CHOICES
from rhythia.discord_embeds import (
    beatmaps_embed,
    help_embed,
    leaderboard_embed,
    profile_embed,
    search_results_embed,
)
from rhythia.linked_accounts import AccountNotLinkedError
from rhythia.oauth_login import build_login_url

logger = logging.getLogger(__name__)

NOT_LINKED = (
    "You need to link your account first. Use `/rhythia link` "
    "(Rhythia Discord login)."
)


async def country_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    cur = current.lower()
    choices: list[app_commands.Choice[str]] = []
    for name, code in COUNTRY_CHOICES:
        if cur in name.lower() or cur in code.lower() or not cur:
            label = f"{name} ({code})" if code else name
            choices.append(app_commands.Choice(name=label, value=code or "GLOBAL"))
        if len(choices) >= 25:
            break
    return choices


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


class RhythiaSlashCommands(commands.Cog):
    def __init__(self, bot: RhythiaBot) -> None:
        self.bot = bot

    rhythia = app_commands.Group(
        name="gerhythia",
        description="Rhythia API stats and search",
    )

    @rhythia.command(name="help", description="Command list and feedback contact")
    async def help_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=help_embed())

    @rhythia.command(
        name="link",
        description="Link Rhythia by privately pasting the session URL from login",
    )
    async def link(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return

        login_url = build_login_url()
        await interaction.response.send_message(
            embed=link_instructions_embed(),
            view=LinkView(self.bot, login_url),
            ephemeral=True,
        )

    @rhythia.command(name="unlink", description="Remove your Rhythia link")
    async def unlink(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        if self.bot.linked_accounts.delete(interaction.user.id):
            await interaction.response.send_message("Link removed.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "No linked account.", ephemeral=True
            )

    @rhythia.command(name="account", description="Rhythia account linked to this Discord")
    async def account(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        linked = self.bot.linked_accounts.get_account(interaction.user.id)
        if linked is None:
            await interaction.response.send_message(NOT_LINKED, ephemeral=True)
            return
        await interaction.response.send_message(
            f"**{linked.rhythia_username}** · ID `{linked.rhythia_user_id}` · "
            f"since {linked.linked_at[:10]}",
            ephemeral=True,
        )

    @rhythia.command(
        name="search",
        description="Search players and beatmaps (no link required)",
    )
    @app_commands.describe(query="Player or beatmap name")
    async def search(
        self,
        interaction: discord.Interaction,
        query: app_commands.Range[str, 2, 64],
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            data = public_search(query=query.strip(), limit=12)
            await interaction.followup.send(
                embed=search_results_embed(data, query=query.strip())
            )
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Search failed: {exc}", ephemeral=True)

    @rhythia.command(name="profile", description="Rhythia profile (yours or another player)")
    @app_commands.describe(
        username="Player name (empty = you). Requires link.",
    )
    async def profile(
        self,
        interaction: discord.Interaction,
        username: str | None = None,
    ) -> None:
        if interaction.user is None:
            return

        query = (username or "").strip()
        if not query:
            await self._reply_with_embed(
                interaction,
                fetch=lambda c: c.get_profile(),
                build=profile_embed,
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            client = self.bot.client_for(interaction.user.id)
        except AccountNotLinkedError:
            await interaction.followup.send(NOT_LINKED, ephemeral=True)
            return

        try:
            with client:
                results = client.search(query=query, limit=5)
                users = results.get("users") or []
                if not users:
                    await interaction.followup.send(
                        f"No player found for **{query}**.",
                        ephemeral=True,
                    )
                    return
                if len(users) > 1 and not _exact_username_match(users, query):
                    await interaction.followup.send(
                        embed=search_results_embed(results, query=query)
                    )
                    return
                data = client.get_profile(user_id=int(users[0]["id"]))
            await interaction.followup.send(embed=profile_embed(data))
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    @rhythia.command(name="leaderboard", description="Skill points leaderboard")
    @app_commands.describe(
        country="Country (ISO code) or Global",
        page="Page (50 players per page)",
        limit="Rows in embed (max 15)",
        spin="Spin skill ranking",
    )
    @app_commands.autocomplete(country=country_autocomplete)
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        country: str | None = None,
        page: app_commands.Range[int, 1, 100] = 1,
        limit: app_commands.Range[int, 1, 15] = 10,
        spin: bool = False,
    ) -> None:
        try:
            country_code = _normalize_country(country)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await self._reply_with_embed(
            interaction,
            fetch=lambda c: c.get_leaderboard(
                page=page, country=country_code, spin=spin
            ),
            build=lambda d: leaderboard_embed(
                d, limit=limit, country=country_code, spin=spin
            ),
        )

    @rhythia.command(name="maps", description="Browse and filter beatmaps")
    @app_commands.describe(
        title="Text in map title",
        mapper="Mapper username",
        status="Map status",
        min_stars="Minimum star rating",
        max_stars="Maximum star rating",
        page="Page number",
        limit="Maps in embed (max 10)",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name=label, value=value)
            for label, value in MAP_STATUS_CHOICES
        ]
    )
    async def maps(
        self,
        interaction: discord.Interaction,
        title: str | None = None,
        mapper: str | None = None,
        status: app_commands.Choice[str] | None = None,
        min_stars: app_commands.Range[float, 0, 20] = 0,
        max_stars: app_commands.Range[float, 0, 20] = 20,
        page: app_commands.Range[int, 1, 100] = 1,
        limit: app_commands.Range[int, 1, 10] = 8,
    ) -> None:
        if min_stars > max_stars:
            await interaction.response.send_message(
                "Minimum stars cannot be greater than maximum.",
                ephemeral=True,
            )
            return

        status_val = status.value if status else ""
        query = (title or "").strip()
        author = (mapper or "").strip()
        label = _maps_filter_label(
            query=query,
            author=author,
            status=status_val,
            min_stars=min_stars,
            max_stars=max_stars,
        )

        await self._reply_with_embed(
            interaction,
            fetch=lambda c: c.get_beatmaps(
                page=page,
                query=query,
                author=author,
                status=status_val,
                min_stars=min_stars,
                max_stars=max_stars,
            ),
            build=lambda d: beatmaps_embed(d, limit=limit, filters_label=label),
        )

    @rhythia.command(name="suggest", description="Suggest Ranked maps based on user's top scores")
    @app_commands.describe(
        username="Player name (empty = you). Requires link.",
    )
    async def suggest(
        self,
        interaction: discord.Interaction,
        username: str | None = None,
    ) -> None:
        if interaction.user is None:
            return

        await interaction.response.defer(thinking=True)
        try:
            client = self.bot.client_for(interaction.user.id)
        except AccountNotLinkedError:
            await interaction.followup.send(NOT_LINKED, ephemeral=True)
            return

        query = (username or "").strip()
        
        try:
            with client:
                if query:
                    results = client.search(query=query, limit=5)
                    users = results.get("users") or []
                    if not users:
                        await interaction.followup.send(
                            f"No player found for **{query}**.",
                            ephemeral=True,
                        )
                        return
                    if len(users) > 1 and not _exact_username_match(users, query):
                        await interaction.followup.send(
                            embed=search_results_embed(results, query=query)
                        )
                        return
                    user_id = int(users[0]["id"])
                    target_name = users[0].get("username") or query
                else:
                    linked = self.bot.linked_accounts.get_account(interaction.user.id)
                    if not linked:
                        await interaction.followup.send(NOT_LINKED, ephemeral=True)
                        return
                    user_id = linked.rhythia_user_id
                    target_name = linked.rhythia_username
                    if user_id is None:
                        data = client.get_profile()
                        user_id = int(data["user"]["id"])

                scores_data = client.get_user_scores(user_id=user_id)
                top_scores = scores_data.get("top") or []
                
                if not top_scores:
                    await interaction.followup.send(f"**{target_name}** has no top scores yet.")
                    return
                
                # Usar até 10 top scores para a média
                top_10 = top_scores[:10]
                avg_stars = sum(s.get("beatmapDifficulty") or 0 for s in top_10) / len(top_10)
                avg_rp = sum(s.get("awarded_sp") or 0 for s in top_10) / len(top_10)

                min_stars = max(0.0, avg_stars - 0.2)
                max_stars = avg_stars + 0.4
                
                filters_label = f"{target_name} · Avg {avg_rp:.0f} RP · {min_stars:.1f}★–{max_stars:.1f}★"

                maps_data = client.get_beatmaps(
                    page=1,
                    status="RANKED",
                    min_stars=min_stars,
                    max_stars=max_stars,
                )
                
            await interaction.followup.send(embed=beatmaps_embed(maps_data, limit=8, filters_label=filters_label))
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    async def _reply_with_embed(
        self,
        interaction: discord.Interaction,
        *,
        fetch: Callable[[RhythiaClient], dict[str, Any]],
        build: Callable[[dict[str, Any]], discord.Embed],
    ) -> None:
        if interaction.user is None:
            return

        try:
            client = self.bot.client_for(interaction.user.id)
        except AccountNotLinkedError:
            await interaction.response.send_message(NOT_LINKED, ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        try:
            with client:
                data = fetch(client)
            await interaction.followup.send(embed=build(data))
        except RhythiaAPIError as exc:
            logger.warning("API (discord=%s): %s", interaction.user.id, exc)
            hint = ""
            if exc.status_code in (401, 403):
                hint = " Your token may have expired — use `/rhythia link` again."
            await interaction.followup.send(f"Error: {exc}{hint}", ephemeral=True)
        except Exception:
            logger.exception("Error in command %s", interaction.command)
            await interaction.followup.send("Internal error.", ephemeral=True)


def _exact_username_match(users: list[dict[str, Any]], query: str) -> bool:
    q = query.lower()
    return any((u.get("username") or "").lower() == q for u in users)
