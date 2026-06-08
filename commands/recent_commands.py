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
from rhythia.site_urls import user_profile_url
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

    @rhythia.command(name="score", description="Show a specific score by its ID")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(score_id="The numeric ID of the score to look up.")
    async def score(self, interaction: discord.Interaction, score_id: int) -> None:
        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()

        try:
            data = await client.get_score(score_id=score_id)

            # The API wraps the score under a string key e.g. {"1": {score_data}}.
            # Fall back to direct dict or "score" key for safety.
            score_obj: dict[str, Any] | None = None
            if isinstance(data, dict):
                if data.get("id"):
                    score_obj = data
                elif "score" in data:
                    score_obj = data["score"]
                else:
                    # Try the first value if all values are dicts ({"1": {...}})
                    for v in data.values():
                        if isinstance(v, dict) and v.get("id"):
                            score_obj = v
                            break

            if not score_obj or not score_obj.get("id"):
                await interaction.followup.send(f"Score `{score_id}` not found.", ephemeral=True)
                return

            # The score has no username field — resolve it from the profile.
            user_id = score_obj.get("userId") or score_obj.get("user_id")
            username = (
                score_obj.get("username")
                or score_obj.get("playerUsername")
                or score_obj.get("ownerUsername")
            )
            if not username and user_id:
                try:
                    profile_data = await client.get_profile(user_id=int(user_id))
                    profile_user = profile_data.get("user") or {}
                    username = (
                        profile_user.get("username")
                        or profile_user.get("computedUsername")
                    )
                except RhythiaAPIError:
                    pass
            if not username:
                username = f"Player {user_id or '?'}"

            # Enrich with beatmap star rating if we have a hash
            beatmap_obj = None
            star_override = None
            beatmap_hash = score_obj.get("beatmapHash")
            if beatmap_hash:
                try:
                    beatmap_obj = await client.find_beatmap(beatmap_hash)
                    star_override = beatmap_obj.get("starRating") if beatmap_obj else None
                except RhythiaAPIError:
                    beatmap_obj = None

            embed = recent_score_embed(score_obj, username=username, stars_override=star_override)
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
            logger.exception("Unexpected error in /gerhythia score")
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

    @rhythia.command(name="top", description="Show a player's top 5 public scores")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def top(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return
        await interaction.response.defer(thinking=True)
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
                await interaction.followup.send(f"**{target_name}** has no top scores.", ephemeral=True)
                return

            top_5 = top_scores[:5]
            
            # Fetch profile to get player avatar
            avatar_url = None
            try:
                profile_data = await client.get_profile(user_id=int(user_id))
                profile_user = profile_data.get("user") or {}
                from rhythia.discord_embeds import _asset_url
                avatar = profile_user.get("avatar_url") or profile_user.get("profile_image")
                avatar_url = _asset_url(avatar)
            except Exception:
                pass

            embed = discord.Embed(
                title=f"🏆 {target_name}'s Top 5 Scores",
                color=0x8B5CF6,
                url=user_profile_url(user_id) if user_id else None
            )
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)

            for index, score in enumerate(top_5, start=1):
                title = score.get("beatmapTitle") or score.get("songId") or "Unknown beatmap"
                awarded = score.get("awarded_sp")
                stars = score.get("beatmapDifficulty") or score.get("difficulty")
                misses = score.get("misses")
                speed = score.get("speed")
                spin = score.get("spin")
                
                diff_text = f"{stars:.2f}★" if isinstance(stars, (int, float)) else "—"
                mode = "Spin" if spin else "Classic"
                speed_text = f"{speed:.2f}x" if isinstance(speed, (int, float)) else "1.00x"
                
                embed.add_field(
                    name=f"{index}. {title}",
                    value=f"🏆 **{awarded:,.0f} SP** | {diff_text} | Misses: {misses} | {mode} ({speed_text})",
                    inline=False
                )

            await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception as exc:
            logger.exception("Unexpected error in /gerhythia top")
            await interaction.followup.send("Internal error.", ephemeral=True)

    @rhythia.command(name="compare", description="Compare stats of two players side by side")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(user1="First player name", user2="Second player name")
    async def compare(self, interaction: discord.Interaction, user1: str, user2: str) -> None:
        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()

        try:
            # Helper to search and resolve exactly one user
            async def resolve_exact(query: str):
                results = await client.search(query=query.strip(), limit=5)
                users = results.get("users") or []
                if not users:
                    raise RhythiaAPIError(f"Player '{query}' not found.")
                exact = next((u for u in users if (u.get("username") or "").lower() == query.strip().lower()), None)
                if len(users) > 1 and exact is None:
                    raise RhythiaAPIError(f"Multiple players found for '{query}'. Use a more exact name.")
                return exact or users[0]

            # Fetch both in parallel
            u1_summary, u2_summary = await asyncio.gather(
                resolve_exact(user1),
                resolve_exact(user2)
            )

            # Fetch detailed profiles to get all required stats
            p1_data, p2_data = await asyncio.gather(
                client.get_profile(user_id=int(u1_summary["id"])),
                client.get_profile(user_id=int(u2_summary["id"]))
            )

            usr1 = p1_data.get("user") or {}
            usr2 = p2_data.get("user") or {}

            # Helper for flag emojis
            from rhythia.discord_embeds import flag_emoji
            flag1 = flag_emoji(usr1.get("flag"))
            flag2 = flag_emoji(usr2.get("flag"))
            
            name1 = usr1.get("username", "User 1")
            name2 = usr2.get("username", "User 2")

            # Determine leaders for visual highlight
            sp1, sp2 = usr1.get("skill_points") or 0.0, usr2.get("skill_points") or 0.0
            pos1, pos2 = usr1.get("position") or 999999, usr2.get("position") or 999999
            pc1, pc2 = usr1.get("play_count") or 0, usr2.get("play_count") or 0

            crown1 = "👑 "
            crown2 = "👑 "

            sp_leader1 = crown1 if sp1 > sp2 else ""
            sp_leader2 = crown2 if sp2 > sp1 else ""
            
            # Position is better if lower (closer to #1)
            pos_leader1 = crown1 if pos1 < pos2 else ""
            pos_leader2 = crown2 if pos2 < pos1 else ""
            
            pc_leader1 = crown1 if pc1 > pc2 else ""
            pc_leader2 = crown2 if pc2 > pc1 else ""

            embed = discord.Embed(
                title="⚔️ Player Comparison",
                color=0x3B82F6,
                description=f"Comparing stats between **{flag1} {name1}** and **{flag2} {name2}**"
            )

            # Set thumbnail to the leader's (highest SP) avatar
            from rhythia.discord_embeds import _asset_url
            leader_user = usr1 if sp1 >= sp2 else usr2
            avatar = leader_user.get("avatar_url") or leader_user.get("profile_image")
            avatar_url = _asset_url(avatar)
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)

            embed.add_field(
                name="🏆 Skill Points (SP)",
                value=f"**{name1}**: {sp_leader1}{sp1:,.2f} SP\n**{name2}**: {sp_leader2}{sp2:,.2f} SP",
                inline=True
            )
            embed.add_field(
                name="🌍 Global Rank",
                value=f"**{name1}**: {pos_leader1}#{pos1:,}\n**{name2}**: {pos_leader2}#{pos2:,}",
                inline=True
            )
            embed.add_field(
                name="🎮 Play Count",
                value=f"**{name1}**: {pc_leader1}{pc1:,}\n**{name2}**: {pc_leader2}{pc2:,}",
                inline=True
            )

            # SP Diff
            sp_diff = sp1 - sp2
            diff_prefix = "+" if sp_diff > 0 else ""
            embed.add_field(
                name="📊 SP Diff",
                value=f"**{name1}** - **{name2}**: {diff_prefix}{sp_diff:,.2f}",
                inline=True
            )

            # Linked accounts count
            linked_count = self.bot.linked_accounts.count()
            embed.add_field(
                name="🔗 Linked Accounts",
                value=f"{linked_count:,}",
                inline=True
            )

            # Add extra detail cards
            embed.add_field(
                name=f"{flag1} {name1}",
                value=f"• **Status:** {'🟢 Online' if usr1.get('is_online') else '⚫ Offline'}",
                inline=True
            )
            embed.add_field(
                name=f"{flag2} {name2}",
                value=f"• **Status:** {'🟢 Online' if usr2.get('is_online') else '⚫ Offline'}",
                inline=True
            )
            embed.add_field(name="\u200b", value="\u200b", inline=True) # Empty field for alignment

            embed.set_footer(text="rhythia.com · 👑 indicates the leader in each stat")
            await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception as exc:
            logger.exception("Unexpected error in /gerhythia compare")
            await interaction.followup.send("Internal error.", ephemeral=True)

    @rhythia.command(name="today", description="Show a player's activity and best score today")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def today(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return
        await interaction.response.defer(thinking=True)
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
            recent_scores = scores_data.get("lastDay") or []
            
            if not recent_scores:
                await interaction.followup.send(f"**{target_name}** has no scores recorded today.", ephemeral=True)
                return

            total_scores = len(recent_scores)
            passed_scores = sum(1 for s in recent_scores if s.get("passed"))
            
            # Find the best score based on awarded_sp
            best_score = max(recent_scores, key=lambda s: s.get("awarded_sp") or 0)

            # Fetch profile to get player avatar
            avatar_url = None
            try:
                profile_data = await client.get_profile(user_id=int(user_id))
                profile_user = profile_data.get("user") or {}
                from rhythia.discord_embeds import _asset_url
                avatar = profile_user.get("avatar_url") or profile_user.get("profile_image")
                avatar_url = _asset_url(avatar)
            except Exception:
                pass

            embed = discord.Embed(
                title=f"📅 Today's Activity for {target_name}",
                color=0x10B981,
                url=user_profile_url(user_id) if user_id else None
            )
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)
            
            embed.add_field(name="Total Plays", value=f"**{total_scores}** ({passed_scores} passed)", inline=True)
            
            best_title = best_score.get("beatmapTitle") or best_score.get("songId") or "Unknown beatmap"
            best_sp = best_score.get("awarded_sp") or 0
            best_stars = best_score.get("beatmapDifficulty") or best_score.get("difficulty")
            best_stars_text = f"{best_stars:.2f}★" if isinstance(best_stars, (int, float)) else "—"
            
            embed.add_field(
                name="⭐ Best Play Today",
                value=f"**{best_title}**\n🏆 **{best_sp:,.0f} SP** | {best_stars_text}",
                inline=False
            )

            await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception as exc:
            logger.exception("Unexpected error in /gerhythia today")
            await interaction.followup.send("Internal error.", ephemeral=True)


    @rhythia.command(name="scores", description="Show a player's recent score history (paginated)")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def scores(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return
        await interaction.response.defer(thinking=True)
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
            all_scores = _sorted_scores_by_created_at(scores_data.get("lastDay") or [])

            if not all_scores:
                await interaction.followup.send(f"**{target_name}** has no recent public scores.", ephemeral=True)
                return

            # Fetch avatar
            avatar_url = None
            try:
                profile_data = await client.get_profile(user_id=int(user_id))
                profile_user = profile_data.get("user") or {}
                from rhythia.discord_embeds import _asset_url
                avatar = profile_user.get("avatar_url") or profile_user.get("profile_image")
                avatar_url = _asset_url(avatar)
            except Exception:
                pass

            PAGE_SIZE = 5

            def build_page(page_items: list[Any], page: int, max_pages: int) -> discord.Embed:
                embed = discord.Embed(
                    title=f"📋 {target_name}'s Recent Scores",
                    color=0xF97316,
                    url=user_profile_url(user_id) if user_id else None,
                )
                if avatar_url:
                    embed.set_thumbnail(url=avatar_url)

                for score in page_items:
                    score_title = score.get("beatmapTitle") or score.get("songId") or "Unknown"
                    sp = score.get("awarded_sp") or 0
                    stars = score.get("beatmapDifficulty") or score.get("difficulty")
                    misses = score.get("misses") or 0
                    speed = score.get("speed")
                    passed = score.get("passed")
                    spin = score.get("spin")
                    created = score.get("created_at") or ""

                    stars_text = f"{stars:.2f}★" if isinstance(stars, (int, float)) else "—"
                    speed_text = f"{float(speed):.2f}x" if isinstance(speed, (int, float)) else "—"
                    result_icon = "✅" if passed else "❌"
                    mode = "🌀 Spin" if spin else "🎯 Classic"

                    # Format timestamp as short date/time
                    try:
                        from datetime import datetime
                        ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        time_str = ts.strftime("%m/%d %H:%M")
                    except Exception:
                        time_str = created[:16].replace("T", " ") if created else "—"

                    embed.add_field(
                        name=f"{result_icon} {score_title}",
                        value=f"🏆 **{sp:,.0f} SP** | {stars_text} | Misses: {misses} | {speed_text} | {mode} | `{time_str}` | ID: `{score.get('id') or '—'}`",
                        inline=False,
                    )

                embed.set_footer(text=f"Page {page}/{max_pages} · {len(all_scores)} scores today · rhythia.com")
                return embed

            from bot.embed_navigator import LocalEmbedNavigatorView
            first_page = all_scores[:PAGE_SIZE]
            max_pages = max(1, (len(all_scores) + PAGE_SIZE - 1) // PAGE_SIZE)
            embed = build_page(first_page, 1, max_pages)
            view = LocalEmbedNavigatorView(interaction, items=all_scores, build=build_page, page_size=PAGE_SIZE)
            await interaction.followup.send(embed=embed, view=view)

        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception as exc:
            logger.exception("Unexpected error in /gerhythia scores")
            await interaction.followup.send("Internal error.", ephemeral=True)

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
