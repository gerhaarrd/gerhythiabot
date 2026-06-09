"""Commands to configure guild settings like language."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.compat import RhythiaCompat
from utils.i18n import translate, LANGUAGES


class LanguageCommands(RhythiaCompat):
    """Commands for bot settings like language."""

    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)

    @rhythia.command(name="language", description="Set the bot's language for this server")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(lang="Language choice")
    @app_commands.choices(lang=[
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="Português", value="pt"),
        app_commands.Choice(name="Español", value="es"),
    ])
    async def language(self, interaction: discord.Interaction, lang: app_commands.Choice[str]) -> None:
        if not interaction.guild_id:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        selected_lang = lang.value
        if selected_lang not in LANGUAGES:
            await interaction.response.send_message(
                translate("lang_invalid", "en"),
                ephemeral=True,
            )
            return

        self.bot.linked_accounts.set_guild_language(interaction.guild_id, selected_lang)
        await interaction.response.send_message(
            translate("lang_updated", selected_lang),
            ephemeral=True,
        )
