"""Map browsing and beatmap commands."""
from __future__ import annotations

from typing import Callable, Awaitable, Any
import asyncio
import random as _random

import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from rhythia.discord_embeds import beatmaps_embed, beatmap_embed
from utils.helpers import _beatmap_image_file


from bot.compat import RhythiaCompat


class MapsCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia
    maps = app_commands.Group(name="maps", parent=rhythia, description="Browse and search beatmaps")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @maps.command(name="search", description="Browse and filter beatmaps (10 maps per page)")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(title="Text in map title", mapper="Mapper username", status="Map status", min_stars="Minimum star rating", max_stars="Maximum star rating")
    @app_commands.choices(status=[app_commands.Choice(name=label, value=value) for label, value in []])
    async def maps_search(self, interaction: discord.Interaction, title: str | None = None, mapper: str | None = None, status: app_commands.Choice[str] | None = None, min_stars: app_commands.Range[float, 0, 20] = 0, max_stars: app_commands.Range[float, 0, 20] = 20) -> None:
        from utils.i18n import translate
        lang = self._get_lang(interaction)

        MAPS_LIMIT = 10
        if min_stars > max_stars:
            await interaction.response.send_message(translate("min_stars_greater", lang), ephemeral=True)
            return
        status_val = status.value if status else ""
        query = (title or "").strip()
        author = (mapper or "").strip()
        label = f"{query} · {author}"
        await self._reply_with_navigable_embed(interaction, fetch=lambda c, p: c.get_beatmaps(page=p, query=query, author=author, status=status_val, min_stars=min_stars, max_stars=max_stars), build=lambda d, up=1: beatmaps_embed(d, up, limit=MAPS_LIMIT, filters_label=label), page_size=MAPS_LIMIT)

    @rhythia.command(name="beatmap", description="Show one beatmap by id or title")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(query="Beatmap id or title")
    async def beatmap(self, interaction: discord.Interaction, query: app_commands.Range[str, 1, 120]) -> None:
        from utils.i18n import translate
        lang = self._get_lang(interaction)

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        try:
            beatmap = await client.find_beatmap(query)
            # `find_beatmap` performs enrichment and caching; rely on it.
            if not beatmap:
                await interaction.followup.send(translate("no_beatmap_found", lang, query=query), ephemeral=True)
                return
            embed = beatmap_embed(beatmap)
            image_task = asyncio.create_task(_beatmap_image_file(beatmap, session=self.bot._http_session))
            image_file = await image_task
            if image_file:
                embed.set_image(url=f"attachment://{image_file.filename}")
                await interaction.followup.send(embed=embed, file=image_file)
            else:
                await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            await interaction.followup.send(translate("api_error", lang), ephemeral=True)

    @rhythia.command(name="random", description="Show a random beatmap from the library")
    @app_commands.checks.cooldown(5, 30.0)
    async def random(self, interaction: discord.Interaction) -> None:
        from utils.i18n import translate
        lang = self._get_lang(interaction)

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        try:
            # Get total beatmap count first
            first_page = await client.get_beatmaps(page=1)
            total = first_page.get("total") or 0
            view_per_page = int(first_page.get("viewPerPage") or 50)
            if total <= 0:
                await interaction.followup.send(translate("no_beatmaps_found", lang), ephemeral=True)
                return

            max_api_page = max(1, (total + view_per_page - 1) // view_per_page)
            rand_page = _random.randint(1, max_api_page)
            data = await client.get_beatmaps(page=rand_page)
            beatmaps = data.get("beatmaps") or []
            if not beatmaps:
                beatmaps = first_page.get("beatmaps") or []
            if not beatmaps:
                await interaction.followup.send(translate("no_beatmaps_found", lang), ephemeral=True)
                return

            beatmap = _random.choice(beatmaps)
            embed = beatmap_embed(beatmap)
            embed.title = translate("random_map_title", lang, title=embed.title)

            image_task = asyncio.create_task(_beatmap_image_file(beatmap, session=self.bot._http_session))
            image_file = await image_task
            if image_file:
                embed.set_image(url=f"attachment://{image_file.filename}")
                await interaction.followup.send(embed=embed, file=image_file)
            else:
                await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            await interaction.followup.send(translate("api_error", lang), ephemeral=True)
        except Exception:
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

    @maps.command(name="new", description="Show the most recently added beatmaps")
    @app_commands.checks.cooldown(5, 30.0)
    async def mapsnew(self, interaction: discord.Interaction) -> None:
        from utils.i18n import translate
        lang = self._get_lang(interaction)

        MAPS_LIMIT = 10
        await self._reply_with_navigable_embed(
            interaction,
            fetch=lambda c, p: c.get_beatmaps(page=p),
            build=lambda d, up=1: beatmaps_embed(d, up, limit=MAPS_LIMIT, filters_label=translate("newest_maps_label", lang)),
            page_size=MAPS_LIMIT,
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
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception:
            await interaction.followup.send("Internal error.", ephemeral=True)

