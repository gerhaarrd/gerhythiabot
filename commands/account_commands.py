"""Account-related commands (profile, account info)."""
from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from utils.helpers import _date_mmddyyyy, _exact_username_match
from rhythia.discord_embeds import profile_embed, search_results_embed


from bot.compat import RhythiaCompat


class AccountCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="account", description="Rhythia account linked to this Discord")
    async def account(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        linked = self.bot.linked_accounts.get_account(interaction.user.id)
        if linked is None:
            await interaction.response.send_message("You need to link your Rhythia username first. Use `/gerhythia link <username>`.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**{linked.rhythia_username}** · ID `{linked.rhythia_user_id}` · since {_date_mmddyyyy(linked.linked_at)}",
            ephemeral=True,
        )

    @rhythia.command(name="profile", description="Rhythia profile (yours or another player)")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def profile(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return

        query = (username or "").strip()
        if not query:
            linked = self.bot.linked_accounts.get_account(interaction.user.id)
            if not linked or linked.rhythia_user_id is None:
                await interaction.response.send_message("You need to link your Rhythia username first. Use `/gerhythia link <username>`.", ephemeral=True)
                return
            await self._reply_with_embed(interaction, fetch=lambda c: c.get_profile(user_id=linked.rhythia_user_id), build=profile_embed)
            return

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()

        try:
            results = await client.search(query=query, limit=5)
            users = results.get("users") or []
            if not users:
                await interaction.followup.send(f"No player found for **{query}**.", ephemeral=True)
                return
            if len(users) > 1 and not _exact_username_match(users, query):
                await interaction.followup.send(embed=search_results_embed(results, query=query))
                return
            data = await client.get_profile(user_id=int(users[0]["id"]))
            await interaction.followup.send(embed=profile_embed(data))
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    async def _reply_with_embed(self, interaction: discord.Interaction, *, fetch: Callable[[RhythiaClient], Awaitable[dict[str, Any]]], build: Callable[[dict[str, Any]], discord.Embed]) -> None:
        if interaction.user is None:
            return

        client = self.bot.client_for()

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                return

        try:
            data = await fetch(client)
            await interaction.followup.send(embed=build(data))
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception:
            await interaction.followup.send("Internal error.", ephemeral=True)
