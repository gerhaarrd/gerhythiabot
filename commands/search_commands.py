"""Search and lookup commands."""
from __future__ import annotations

from typing import Callable, Awaitable, Any

import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import public_search, RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from rhythia.discord_embeds import search_results_embed


from bot.compat import RhythiaCompat


class SearchCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="search", description="Search players and beatmaps (no link required)")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(query="Player or beatmap name")
    async def search(self, interaction: discord.Interaction, query: app_commands.Range[str, 2, 64]) -> None:
        from utils.i18n import translate
        lang = self._get_lang(interaction)
        await interaction.response.defer(thinking=True)
        try:
            data = await public_search(query=query.strip(), limit=12)
            await interaction.followup.send(embed=search_results_embed(data, query=query.strip(), lang=lang))
        except RhythiaAPIError as exc:
            await interaction.followup.send(translate("api_error", lang), ephemeral=True)
