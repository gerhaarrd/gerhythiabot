"""Recent scores and suggestions commands."""
from __future__ import annotations

from typing import Any
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from rhythia.discord_embeds import recent_score_embed, beatmaps_embed
from utils.helpers import _sorted_scores_by_created_at, _beatmap_image_file


from bot.compat import RhythiaCompat
logger = logging.getLogger(__name__)


class RecentCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="recent", description="Show a player's latest public score with beatmap image")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def recent(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            # Commands may be invoked with `self` bound to the RhythiaCompat cog
            # (see bot.compat). Prefer the per-category `RecentCommands` cog
            # implementation when available on the bot instance.
            cog = self.bot.get_cog("RecentCommands")
            resolver = getattr(cog, "_resolve_user_for_scores", None) if cog else None
            if resolver is None or not callable(resolver):
                # Inline fallback: replicate the resolution logic to avoid
                # depending on a method that may not exist on `self`.
                async def _inline_resolve(d_id: int, c: RhythiaClient, *, query: str):
                    if not query:
                        linked = self.bot.linked_accounts.get_account(d_id)
                        if not linked:
                            return None, ""
                        return linked.rhythia_user_id, linked.rhythia_username

                    results = await c.search(query=query, limit=5)
                    users = results.get("users") or []
                    if not users:
                        raise RhythiaAPIError(f"No player found for {query}.")
                    exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                    if len(users) > 1 and exact is None:
                        raise RhythiaAPIError(f"Multiple players found for {query}. Use a more exact username.")
                    user = exact or users[0]
                    return int(user["id"]), str(user.get("username") or query)

                resolver = _inline_resolve

            user_id, target_name = await resolver(interaction.user.id, client, query=query)
            if user_id is None:
                await interaction.followup.send("You need to link your Rhythia username first. Use `/gerhythia link <username>`.", ephemeral=True)
                return

            scores_data = await client.get_user_scores(user_id=user_id)
            recent_scores = _sorted_scores_by_created_at(scores_data.get("lastDay") or [])
            if not recent_scores:
                await interaction.followup.send(f"**{target_name}** has no recent public scores.", ephemeral=True)
                return

            recent_score = recent_scores[0]
            # Defer embedding until after we may fetch the beatmap so we can
            # include the beatmap's starRating as `Stars` next to Difficulty.
            beatmap_hash = recent_score.get("beatmapHash")
            beatmap_obj = None
            star_override = None
            if beatmap_hash:
                try:
                    # Parallelize beatmap enrichment and image fetch to save round trips.
                    coro_find = client.find_beatmap(beatmap_hash)
                    coro_image = None
                    # We'll fetch image only after we have a beatmap object, but allow
                    # the image fetch to run concurrently by starting it with whatever
                    # image URL is present after enrichment. To avoid double work,
                    # run find_beatmap first and then start image fetch concurrently
                    # with any other awaited tasks. For simplicity, run find_beatmap
                    # and then start image fetch concurrently with nothing else here.
                    beatmap_obj = await coro_find
                    star_override = beatmap_obj.get("starRating") if beatmap_obj else None
                except RhythiaAPIError:
                    beatmap_obj = None

            embed = recent_score_embed(recent_score, username=target_name, stars_override=star_override)
            # Start image fetch as a background task so embed building isn't
            # blocked by network. We still await the result before sending.
            image_task = None
            if beatmap_obj:
                image_task = asyncio.create_task(_beatmap_image_file(beatmap_obj, session=self.bot._http_session))
            image_file = await image_task if image_task else None
            if image_file:
                embed.set_thumbnail(url=f"attachment://{image_file.filename}")
                await interaction.followup.send(embed=embed, file=image_file)
            else:
                await interaction.followup.send(embed=embed)

        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send("Internal error.", ephemeral=True)

    @rhythia.command(name="suggest", description="Suggest Ranked maps based on user's top scores (10 maps per page)")
    @app_commands.checks.cooldown(2, 60.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def suggest(self, interaction: discord.Interaction, username: str | None = None) -> None:
        SUGGEST_LIMIT = 10
        if interaction.user is None:
            return

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                return

        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            cog = self.bot.get_cog("RecentCommands")
            resolver = getattr(cog, "_resolve_user_for_scores", None) if cog else None
            if resolver is None or not callable(resolver):
                async def _inline_resolve(d_id: int, c: RhythiaClient, *, query: str):
                    if not query:
                        linked = self.bot.linked_accounts.get_account(d_id)
                        if not linked:
                            return None, ""
                        return linked.rhythia_user_id, linked.rhythia_username

                    results = await c.search(query=query, limit=5)
                    users = results.get("users") or []
                    if not users:
                        raise RhythiaAPIError(f"No player found for {query}.")
                    exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                    if len(users) > 1 and exact is None:
                        raise RhythiaAPIError(f"Multiple players found for {query}. Use a more exact username.")
                    user = exact or users[0]
                    return int(user["id"]), str(user.get("username") or query)

                resolver = _inline_resolve

            user_id, target_name = await resolver(interaction.user.id, client, query=query)
            if user_id is None:
                await interaction.followup.send("You need to link your Rhythia username first. Use `/gerhythia link <username>`.", ephemeral=True)
                return

            scores_data = await client.get_user_scores(user_id=user_id)
            top_scores = scores_data.get("top") or []
            if not top_scores:
                await interaction.followup.send(f"**{target_name}** has no top scores yet.")
                return

            top_10 = top_scores[:10]
            avg_stars = sum(s.get("beatmapDifficulty") or 0 for s in top_10) / len(top_10)
            avg_rp = sum(s.get("awarded_sp") or 0 for s in top_10) / len(top_10)

            min_stars = max(0.0, avg_stars - 0.2)
            max_stars = avg_stars + 0.4

            filters_label = f"{target_name} · Avg {avg_rp:.0f} RP · {min_stars:.1f}★–{max_stars:.1f}★"

            await self._reply_with_navigable_embed(interaction, fetch=lambda c, p: c.get_beatmaps(page=p, status="RANKED", min_stars=min_stars, max_stars=max_stars), build=lambda d, up=1: beatmaps_embed(d, up, limit=SUGGEST_LIMIT, filters_label=filters_label), page_size=SUGGEST_LIMIT)
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    async def _resolve_user_for_scores(self, discord_id: int, client: RhythiaClient, *, query: str) -> tuple[int | None, str]:
        if not query:
            linked = self.bot.linked_accounts.get_account(discord_id)
            if not linked:
                return None, ""
            return linked.rhythia_user_id, linked.rhythia_username

        results = await client.search(query=query, limit=5)
        users = results.get("users") or []
        if not users:
            raise RhythiaAPIError(f"No player found for {query}.")
        exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
        if len(users) > 1 and exact is None:
            raise RhythiaAPIError(f"Multiple players found for {query}. Use a more exact username.")
        user = exact or users[0]
        return int(user["id"]), str(user.get("username") or query)

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
        except Exception as exc:
            await interaction.followup.send("Internal error.", ephemeral=True)
