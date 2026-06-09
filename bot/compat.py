from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from utils.helpers import country_autocomplete

logger = logging.getLogger(__name__)


class RhythiaCompat(commands.Cog):
    rhythia = app_commands.Group(name="gerhythia", description="Rhythia API stats and search")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _reply_with_embed(
        self,
        interaction: discord.Interaction,
        *,
        fetch: Callable[[RhythiaClient], Awaitable[dict[str, Any]]],
        build: Callable[[dict[str, Any]], discord.Embed],
    ) -> None:
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

    async def _reply_with_navigable_embed(
        self,
        interaction: discord.Interaction,
        *,
        fetch: Callable[[RhythiaClient, int], Awaitable[dict[str, Any]]],
        build: Callable[[dict[str, Any], int], discord.Embed],
        initial_user_page: int = 1,
        page_size: int | None = None,
    ) -> None:
        if interaction.user is None:
            return

        client = self.bot.client_for()

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                return

        try:
            from bot.embed_navigator import API_PAGE_SIZE, EmbedNavigatorView

            actual_page_size = page_size or API_PAGE_SIZE
            first_item_index = (initial_user_page - 1) * actual_page_size
            api_page = (first_item_index // 50) + 1
            data = await fetch(client, api_page)

            total = data.get("total", 0)
            per_page = actual_page_size
            max_pages = (total + per_page - 1) // per_page if total > 0 else 1

            embed = build(data, initial_user_page)
            view = EmbedNavigatorView(
                interaction,
                fetch=fetch,
                build=build,
                initial_data=data,
                initial_user_page=initial_user_page,
                max_pages=max_pages,
                page_size=page_size,
            )
            await interaction.followup.send(embed=embed, view=view)
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception:
            await interaction.followup.send("Internal error.", ephemeral=True)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            retry_after = max(1, round(error.retry_after))
            message = f"Slow down a bit. Try again in **{retry_after}s**."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                # Interaction expired or already acknowledged; best-effort followup.
                try:
                    await interaction.channel.send(message)
                except Exception:
                    pass
            return

        cmd_name = interaction.command.name if interaction.command else "unknown"
        logger.error(f"Error running command {cmd_name}: {error}", exc_info=error)

        message = "Internal error."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            try:
                await interaction.channel.send(message)
            except Exception:
                pass

