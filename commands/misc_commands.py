"""Miscellaneous commands like help and link confirmation."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from rhythia.discord_embeds import help_embed


from bot.compat import RhythiaCompat


class MiscCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="help", description="Command list and feedback contact")
    async def help_command(self, interaction: discord.Interaction) -> None:
        icon_file = discord.File("assets/icon.jpg", filename="icon.jpg")
        await interaction.response.send_message(embed=help_embed(), file=icon_file)
