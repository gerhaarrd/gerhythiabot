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
from utils.i18n import translate


class RhythiaCompat(commands.Cog):
    rhythia = app_commands.Group(name="gerhythia", description="Rhythia API stats and search")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _get_lang(self, interaction: discord.Interaction) -> str:
        if interaction.guild_id and hasattr(self.bot, "linked_accounts"):
            return self.bot.linked_accounts.get_guild_language(interaction.guild_id)
        return "en"

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
        lang = self._get_lang(interaction)

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                return

        try:
            data = await fetch(client)
            try:
                embed = build(data, lang=lang)
            except TypeError:
                embed = build(data)
            await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            logger.warning("Rhythia API error in command %s: %s", interaction.command.name if interaction.command else "unknown", exc)
            await interaction.followup.send(translate("api_error", lang), ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in command %s", interaction.command.name if interaction.command else "unknown")
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

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
        lang = self._get_lang(interaction)

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

            try:
                embed = build(data, initial_user_page, lang=lang)
            except TypeError:
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
            logger.warning("Rhythia API error in command %s: %s", interaction.command.name if interaction.command else "unknown", exc)
            await interaction.followup.send(translate("api_error", lang), ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in command %s", interaction.command.name if interaction.command else "unknown")
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        lang = self._get_lang(interaction)

        if isinstance(error, app_commands.CommandOnCooldown):
            message = translate("cooldown", lang, time=error.retry_after)
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

        if isinstance(error, app_commands.errors.MissingPermissions):
            message = translate("admin_required", lang)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
            except Exception:
                pass
            return

        cmd_name = interaction.command.name if interaction.command else "unknown"
        original_error = getattr(error, "original", error)

        # Handle specific RhythiaAPIError if raised unhandled
        from rhythia.api_errors import RhythiaAPIError
        if isinstance(original_error, RhythiaAPIError):
            logger.warning("Rhythia API error in command %s: %s", cmd_name, original_error)
            message = translate("api_error", lang)
        else:
            logger.error(f"Error running command {cmd_name}: {original_error}", exc_info=original_error)
            message = translate("internal_error", lang)

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

