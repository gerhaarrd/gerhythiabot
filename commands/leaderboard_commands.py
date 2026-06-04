"""Leaderboard-related commands."""
from __future__ import annotations

from typing import Any

import logging
import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from rhythia.constants import COUNTRY_CHOICES
from rhythia.discord_embeds import leaderboard_embed
from utils.helpers import _exact_username_match, _exact_user, country_autocomplete
from typing import Callable, Awaitable
from rhythia.discord_embeds import search_results_embed

logger = logging.getLogger(__name__)


from bot.compat import RhythiaCompat


class LeaderboardCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="leaderboard", description="Skill points leaderboard (10 players per page)")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(country="Country (ISO code) or Global", spin="Spin skill ranking")
    @app_commands.autocomplete(country=country_autocomplete)
    async def leaderboard(self, interaction: discord.Interaction, country: str | None = None, spin: bool = False) -> None:
        LEADERBOARD_LIMIT = 10
        if interaction.user is None:
            return

        try:
            country_code = country and country.strip().upper()
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                logger.warning("Interaction expired (discord=%s)", interaction.user.id)
                return

        user_position: int | None = None
        linked = self.bot.linked_accounts.get_account(interaction.user.id)
        if linked and linked.rhythia_user_id:
            try:
                client = self.bot.client_for()
                profile = await client.get_profile(user_id=linked.rhythia_user_id)
                user_data = profile.get("user", {})
                raw_pos = user_data.get("country_position") if country_code else user_data.get("position")
                if raw_pos is not None:
                    try:
                        pos_int = int(raw_pos)
                        if pos_int > 0:
                            user_position = pos_int
                    except (TypeError, ValueError):
                        pass
            except RhythiaAPIError:
                pass

        await self._reply_with_navigable_embed(
            interaction,
            fetch=lambda c, p: c.get_leaderboard(page=p, country=country_code, spin=spin),
            build=lambda d, up=1: leaderboard_embed(d, up, limit=LEADERBOARD_LIMIT, country=country_code, spin=spin, user_position=user_position),
            page_size=LEADERBOARD_LIMIT,
        )

    async def _reply_with_navigable_embed(self, interaction: discord.Interaction, *, fetch: Callable[[RhythiaClient, int], Awaitable[dict[str, Any]]], build: Callable[[dict[str, Any], int], discord.Embed], initial_user_page: int = 1, page_size: int | None = None) -> None:
        from bot.embed_navigator import API_PAGE_SIZE, EmbedNavigatorView
        if interaction.user is None:
            return
        client = self.bot.client_for()
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                return
        try:
            actual_page_size = page_size or API_PAGE_SIZE
            first_item_index = (initial_user_page - 1) * actual_page_size
            api_page = (first_item_index // 50) + 1
            data = await fetch(client, api_page)
            total = data.get("total", 0)
            per_page = actual_page_size
            max_pages = (total + per_page - 1) // per_page if total > 0 else 1
            embed = build(data, initial_user_page)
            view = EmbedNavigatorView(interaction, fetch=fetch, build=build, initial_data=data, initial_user_page=initial_user_page, max_pages=max_pages, page_size=page_size)
            await interaction.followup.send(embed=embed, view=view)
        except RhythiaAPIError as exc:
            logger.warning("API (discord=%s): %s", interaction.user.id, exc)
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception:
            logger.exception("Error in leaderboard command")
            await interaction.followup.send("Internal error.", ephemeral=True)
