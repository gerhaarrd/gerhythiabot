"""Commands related to account verification and linking.

Move the verification-related methods from `bot/slash_commands.py` here.
Example: `verify`, `link`, `unlink` command handlers.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from rhythia.account_link import (
    AccountLinkError,
    find_link_candidates,
    verify_pending_rhythia_link,
)
from rhythia.discord_embeds import search_results_embed
from bot.link_account_ui import link_confirmation_embed, PublicLinkConfirmView
from utils.helpers import _date_mmddyyyy

logger = logging.getLogger(__name__)


from bot.compat import RhythiaCompat


class VerifyCommands(RhythiaCompat):
    """Account verification and linking commands."""

    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(
        name="link",
        description="Link your Discord to a public Rhythia profile",
    )
    @app_commands.checks.cooldown(2, 60.0)
    @app_commands.describe(username="Your Rhythia username")
    async def link(self, interaction: discord.Interaction, username: app_commands.Range[str, 2, 64]) -> None:
        if interaction.user is None:
            return

        from utils.i18n import translate
        lang = self._get_lang(interaction)

        deferred = True
        try:
            await interaction.response.defer(thinking=True, ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            # Interaction expired or already acknowledged; we'll use followup sends instead.
            deferred = False
        query = username.strip()
        try:
            users = await find_link_candidates(query, limit=5)
        except AccountLinkError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        if not users:
            await interaction.followup.send(translate("not_found", lang, query=query), ephemeral=True)
            return

        exact = [user for user in users if (user.get("username") or "").lower() == query.lower()]
        selected = exact[0] if exact else users[0]
        if len(users) > 1 and not exact:
            hint = translate("multiple_matches_hint", lang)
            if deferred:
                await interaction.followup.send(
                    hint,
                    embed=search_results_embed({"users": users, "beatmaps": []}, query=query),
                    ephemeral=True,
                )
            else:
                await interaction.channel.send(
                    hint,
                    embed=search_results_embed({"users": users, "beatmaps": []}, query=query),
                )

        if deferred:
            await interaction.followup.send(
                embed=link_confirmation_embed(selected, lang=lang),
                view=PublicLinkConfirmView(self.bot, interaction.user.id, selected, lang=lang),
                ephemeral=True,
            )
        else:
            # Fallback: send a normal channel message if the interaction cannot be followed up.
            await interaction.channel.send(
                embed=link_confirmation_embed(selected, lang=lang),
                view=PublicLinkConfirmView(self.bot, interaction.user.id, selected, lang=lang),
            )

    @rhythia.command(name="unlink", description="Remove your Rhythia link")
    async def unlink(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        lang = self._get_lang(interaction)
        from utils.i18n import translate
        deleted_link = self.bot.linked_accounts.delete(interaction.user.id)
        deleted_pending = self.bot.linked_accounts.delete_pending(interaction.user.id)
        if deleted_link or deleted_pending:
            await interaction.response.send_message(translate("link_removed", lang), ephemeral=True)
        else:
            await interaction.response.send_message(translate("no_linked_account", lang), ephemeral=True)

    @rhythia.command(name="verify", description="Verify your pending Rhythia profile link")
    @app_commands.checks.cooldown(2, 60.0)
    async def verify(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        lang = self._get_lang(interaction)
        from utils.i18n import translate

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            username = await verify_pending_rhythia_link(self.bot, discord_id=interaction.user.id)
        except AccountLinkError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        await interaction.followup.send(
            translate("verified_and_linked", lang, username=username),
            ephemeral=True,
        )
