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
        from utils.i18n import translate
        lang = self._get_lang(interaction)

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            cog = self.bot.get_cog("RecentCommands")
            resolver = getattr(cog, "_resolve_user_for_scores", None) if cog else None
            if resolver is None or not callable(resolver):
                async def _inline_resolve(d_id: int, c: RhythiaClient, *, query: str, lang: str = "en"):
                    if not query:
                        linked = self.bot.linked_accounts.get_account(d_id)
                        if not linked:
                            return None, ""
                        return linked.rhythia_user_id, linked.rhythia_username

                    results = await c.search(query=query, limit=5)
                    users = results.get("users") or []
                    if not users:
                        raise RhythiaAPIError(translate("not_found", lang, query=query))
                    exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                    if len(users) > 1 and exact is None:
                        raise RhythiaAPIError(translate("multiple_found", lang, query=query))
                    user = exact or users[0]
                    return int(user["id"]), str(user.get("username") or query)

                resolver = _inline_resolve

            # Pass lang to the resolver if it supports it
            try:
                user_id, target_name = await resolver(interaction.user.id, client, query=query, lang=lang)
            except TypeError:
                user_id, target_name = await resolver(interaction.user.id, client, query=query)

            if user_id is None:
                await interaction.followup.send(translate("link_first", lang), ephemeral=True)
                return

            scores_data = await client.get_user_scores(user_id=user_id)
            recent_scores = _sorted_scores_by_created_at(scores_data.get("lastDay") or [])
            if not recent_scores:
                no_scores_msg = translate("recent_no_scores", lang, target_name=target_name)
                await interaction.followup.send(no_scores_msg, ephemeral=True)
                return

            recent_score = recent_scores[0]
            beatmap_hash = recent_score.get("beatmapHash")
            beatmap_obj = None
            star_override = None
            if beatmap_hash:
                try:
                    beatmap_obj = await client.find_beatmap(beatmap_hash)
                    star_override = beatmap_obj.get("starRating") if beatmap_obj else None
                except RhythiaAPIError:
                    beatmap_obj = None

            embed = recent_score_embed(recent_score, username=target_name, stars_override=star_override, lang=lang)
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
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

    @rhythia.command(name="score", description="Show a specific score by its ID")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(score_id="The numeric ID of the score to look up.")
    async def score(self, interaction: discord.Interaction, score_id: int) -> None:
        from utils.i18n import translate
        lang = self._get_lang(interaction)
        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()

        try:
            data = await client.get_score(score_id=score_id)

            score_obj: dict[str, Any] | None = None
            if isinstance(data, dict):
                if data.get("id"):
                    score_obj = data
                elif "score" in data:
                    score_obj = data["score"]
                else:
                    for v in data.values():
                        if isinstance(v, dict) and v.get("id"):
                            score_obj = v
                            break

            if not score_obj or not score_obj.get("id"):
                not_found_msg = translate("score_not_found", lang, score_id=score_id)
                await interaction.followup.send(not_found_msg, ephemeral=True)
                return

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

            beatmap_obj = None
            star_override = None
            beatmap_hash = score_obj.get("beatmapHash")
            if beatmap_hash:
                try:
                    beatmap_obj = await client.find_beatmap(beatmap_hash)
                    star_override = beatmap_obj.get("starRating") if beatmap_obj else None
                except RhythiaAPIError:
                    beatmap_obj = None

            embed = recent_score_embed(score_obj, username=username, stars_override=star_override, lang=lang)
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
            await interaction.followup.send(translate("api_error", lang), ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in /gerhythia score")
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

    @rhythia.command(name="suggest", description="Suggest Ranked maps based on user's top scores (10 maps per page)")
    @app_commands.checks.cooldown(2, 60.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def suggest(self, interaction: discord.Interaction, username: str | None = None) -> None:
        from utils.i18n import translate
        lang = self._get_lang(interaction)
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
                async def _inline_resolve(d_id: int, c: RhythiaClient, *, query: str, lang: str = "en"):
                    if not query:
                        linked = self.bot.linked_accounts.get_account(d_id)
                        if not linked:
                            return None, ""
                        return linked.rhythia_user_id, linked.rhythia_username

                    results = await c.search(query=query, limit=5)
                    users = results.get("users") or []
                    if not users:
                        raise RhythiaAPIError(translate("not_found", lang, query=query))
                    exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                    if len(users) > 1 and exact is None:
                        raise RhythiaAPIError(translate("multiple_found", lang, query=query))
                    user = exact or users[0]
                    return int(user["id"]), str(user.get("username") or query)

                resolver = _inline_resolve

            try:
                user_id, target_name = await resolver(interaction.user.id, client, query=query, lang=lang)
            except TypeError:
                user_id, target_name = await resolver(interaction.user.id, client, query=query)

            if user_id is None:
                await interaction.followup.send(translate("link_first", lang), ephemeral=True)
                return

            scores_data = await client.get_user_scores(user_id=user_id)
            top_scores = scores_data.get("top") or []
            if not top_scores:
                no_top_msg = translate("suggest_no_top", lang, target_name=target_name)
                await interaction.followup.send(no_top_msg)
                return

            top_10 = top_scores[:10]
            avg_stars = sum(s.get("beatmapDifficulty") or 0 for s in top_10) / len(top_10)
            avg_rp = sum(s.get("awarded_sp") or 0 for s in top_10) / len(top_10)

            min_stars = max(0.0, avg_stars - 0.2)
            max_stars = avg_stars + 0.4

            filters_label = f"{target_name} · Avg {avg_rp:.0f} RP · {min_stars:.1f}★–{max_stars:.1f}★"

            await self._reply_with_navigable_embed(interaction, fetch=lambda c, p: c.get_beatmaps(page=p, status="RANKED", min_stars=min_stars, max_stars=max_stars), build=lambda d, up=1, l=lang: beatmaps_embed(d, up, limit=SUGGEST_LIMIT, filters_label=filters_label, lang=l), page_size=SUGGEST_LIMIT)
        except RhythiaAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)

    @rhythia.command(name="top", description="Show a player's top 5 public scores")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def top(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return
        from utils.i18n import translate
        lang = self._get_lang(interaction)
        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            cog = self.bot.get_cog("RecentCommands")
            resolver = getattr(cog, "_resolve_user_for_scores", None) if cog else None
            if resolver is None or not callable(resolver):
                async def _inline_resolve(d_id: int, c: RhythiaClient, *, query: str, lang: str = "en"):
                    if not query:
                        linked = self.bot.linked_accounts.get_account(d_id)
                        if not linked:
                            return None, ""
                        return linked.rhythia_user_id, linked.rhythia_username
                    results = await c.search(query=query, limit=5)
                    users = results.get("users") or []
                    if not users:
                        raise RhythiaAPIError(translate("not_found", lang, query=query))
                    exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                    if len(users) > 1 and exact is None:
                        raise RhythiaAPIError(translate("multiple_found", lang, query=query))
                    user = exact or users[0]
                    return int(user["id"]), str(user.get("username") or query)
                resolver = _inline_resolve

            try:
                user_id, target_name = await resolver(interaction.user.id, client, query=query, lang=lang)
            except TypeError:
                user_id, target_name = await resolver(interaction.user.id, client, query=query)

            if user_id is None:
                await interaction.followup.send(translate("link_first", lang), ephemeral=True)
                return

            scores_data = await client.get_user_scores(user_id=user_id)
            top_scores = scores_data.get("top") or []
            if not top_scores:
                no_top_msg = translate("top_no_scores", lang, target_name=target_name)
                await interaction.followup.send(no_top_msg, ephemeral=True)
                return

            top_5 = top_scores[:5]

            async def _fetch_stars(score_item: dict[str, Any]) -> float | None:
                h = score_item.get("beatmapHash")
                if not h:
                    return score_item.get("starRating")
                try:
                    bm = await client.find_beatmap(h)
                    return bm.get("starRating") if bm else score_item.get("starRating")
                except Exception:
                    return score_item.get("starRating")

            stars_tasks = [_fetch_stars(s) for s in top_5]
            stars_results = await asyncio.gather(*stars_tasks)

            avatar_url = None
            try:
                profile_data = await client.get_profile(user_id=int(user_id))
                profile_user = profile_data.get("user") or {}
                from rhythia.discord_embeds import _asset_url
                avatar = profile_user.get("avatar_url") or profile_user.get("profile_image")
                avatar_url = _asset_url(avatar)
            except Exception:
                pass

            title_text = translate("top_title", lang, target_name=target_name)
            embed = discord.Embed(
                title=title_text,
                color=0x8B5CF6,
                url=user_profile_url(user_id) if user_id else None
            )
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)

            for index, (score, stars) in enumerate(zip(top_5, stars_results), start=1):
                title = score.get("beatmapTitle") or score.get("songId") or "Unknown beatmap"
                awarded = score.get("awarded_sp") or 0.0
                misses = score.get("misses") or 0
                speed = score.get("speed")
                spin = score.get("spin")
                
                diff_text = f"{stars:.2f}★" if isinstance(stars, (int, float)) else "—"
                mode = translate("score_spin" if spin else "score_classic", lang)
                speed_text = f"{speed:.2f}x" if isinstance(speed, (int, float)) else "1.00x"
                
                score_id = score.get("id") or "—"
                
                miss_label = translate("score_misses", lang)
                value_fmt = translate("top_score_value", lang, awarded=awarded, diff_text=diff_text, miss_label=miss_label, misses=misses, mode=mode, speed_text=speed_text, score_id=score_id)
                embed.add_field(
                    name=f"{index}. {title}",
                    value=value_fmt,
                    inline=False
                )

            await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in /gerhythia top")
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

    @rhythia.command(name="compare", description="Compare stats of two players side by side")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(user1="First player name", user2="Second player name")
    async def compare(self, interaction: discord.Interaction, user1: str, user2: str) -> None:
        from utils.i18n import translate
        lang = self._get_lang(interaction)
        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()

        try:
            async def resolve_exact(query: str):
                results = await client.search(query=query.strip(), limit=5)
                users = results.get("users") or []
                if not users:
                    raise RhythiaAPIError(translate("not_found", lang, query=query))
                exact = next((u for u in users if (u.get("username") or "").lower() == query.strip().lower()), None)
                if len(users) > 1 and exact is None:
                    raise RhythiaAPIError(translate("multiple_found", lang, query=query))
                return exact or users[0]

            u1_summary, u2_summary = await asyncio.gather(
                resolve_exact(user1),
                resolve_exact(user2)
            )

            p1_data, p2_data = await asyncio.gather(
                client.get_profile(user_id=int(u1_summary["id"])),
                client.get_profile(user_id=int(u2_summary["id"]))
            )

            usr1 = p1_data.get("user") or {}
            usr2 = p2_data.get("user") or {}

            # Download avatars & flags
            async def download_image(url: str | None) -> bytes | None:
                if not url:
                    return None
                try:
                    async with self.bot._http_session.get(url, timeout=5) as resp:
                        if resp.status == 200:
                            return await resp.read()
                except Exception:
                    pass
                return None

            c1 = usr1.get("flag")
            c2 = usr2.get("flag")
            
            p1_avatar, p2_avatar, p1_flag, p2_flag = await asyncio.gather(
                download_image(usr1.get("avatar_url") or usr1.get("profile_image")),
                download_image(usr2.get("avatar_url") or usr2.get("profile_image")),
                download_image(f"https://flagcdn.com/w80/{c1.lower()}.png" if c1 else None),
                download_image(f"https://flagcdn.com/w80/{c2.lower()}.png" if c2 else None)
            )

            from utils.card_generator import generate_compare_card
            loop = self.bot.loop
            card_stream = await loop.run_in_executor(
                None,
                generate_compare_card,
                p1_data,
                p2_data,
                p1_avatar,
                p2_avatar,
                p1_flag,
                p2_flag
            )

            file = discord.File(card_stream, filename="compare.png")
            await interaction.followup.send(file=file)

        except RhythiaAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in /gerhythia compare")
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

    @rhythia.command(name="today", description="Show a player's activity and best score today")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def today(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return
        from utils.i18n import translate
        lang = self._get_lang(interaction)
        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            cog = self.bot.get_cog("RecentCommands")
            resolver = getattr(cog, "_resolve_user_for_scores", None) if cog else None
            if resolver is None or not callable(resolver):
                async def _inline_resolve(d_id: int, c: RhythiaClient, *, query: str, lang: str = "en"):
                    if not query:
                        linked = self.bot.linked_accounts.get_account(d_id)
                        if not linked:
                            return None, ""
                        return linked.rhythia_user_id, linked.rhythia_username
                    results = await c.search(query=query, limit=5)
                    users = results.get("users") or []
                    if not users:
                        raise RhythiaAPIError(translate("not_found", lang, query=query))
                    exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                    if len(users) > 1 and exact is None:
                        raise RhythiaAPIError(translate("multiple_found", lang, query=query))
                    user = exact or users[0]
                    return int(user["id"]), str(user.get("username") or query)
                resolver = _inline_resolve

            try:
                user_id, target_name = await resolver(interaction.user.id, client, query=query, lang=lang)
            except TypeError:
                user_id, target_name = await resolver(interaction.user.id, client, query=query)

            if user_id is None:
                await interaction.followup.send(translate("link_first", lang), ephemeral=True)
                return

            scores_data = await client.get_user_scores(user_id=user_id)
            recent_scores = scores_data.get("lastDay") or []
            
            if not recent_scores:
                no_scores_today = translate("today_no_scores", lang, target_name=target_name)
                await interaction.followup.send(no_scores_today, ephemeral=True)
                return

            total_scores = len(recent_scores)
            passed_scores = sum(1 for s in recent_scores if s.get("passed"))
            
            best_score = max(recent_scores, key=lambda s: s.get("awarded_sp") or 0)

            avatar_url = None
            try:
                profile_data = await client.get_profile(user_id=int(user_id))
                profile_user = profile_data.get("user") or {}
                from rhythia.discord_embeds import _asset_url
                avatar = profile_user.get("avatar_url") or profile_user.get("profile_image")
                avatar_url = _asset_url(avatar)
            except Exception:
                pass

            today_title = translate("today_title", lang, target_name=target_name)
            embed = discord.Embed(
                title=today_title,
                color=0x10B981,
                url=user_profile_url(user_id) if user_id else None
            )
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)
            
            plays_value = translate("today_plays_value", lang, total_scores=total_scores, passed_scores=passed_scores)
            embed.add_field(name=translate("profile_plays", lang), value=plays_value, inline=True)
            
            best_title = best_score.get("beatmapTitle") or best_score.get("songId") or "Unknown beatmap"
            best_sp = best_score.get("awarded_sp") or 0
            best_stars = best_score.get("beatmapDifficulty") or best_score.get("difficulty")
            best_stars_text = f"{best_stars:.2f}★" if isinstance(best_stars, (int, float)) else "—"
            
            best_play_name = translate("today_best_play_name", lang)
            embed.add_field(
                name=best_play_name,
                value=f"**{best_title}**\n🏆 **{best_sp:,.0f} SP** | {best_stars_text}",
                inline=False
            )

            await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in /gerhythia today")
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

    @rhythia.command(name="scores", description="Show a player's recent score history (paginated)")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def scores(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return
        from utils.i18n import translate
        lang = self._get_lang(interaction)
        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            cog = self.bot.get_cog("RecentCommands")
            resolver = getattr(cog, "_resolve_user_for_scores", None) if cog else None
            if resolver is None or not callable(resolver):
                async def _inline_resolve(d_id: int, c: RhythiaClient, *, query: str, lang: str = "en"):
                    if not query:
                        linked = self.bot.linked_accounts.get_account(d_id)
                        if not linked:
                            return None, ""
                        return linked.rhythia_user_id, linked.rhythia_username
                    results = await c.search(query=query, limit=5)
                    users = results.get("users") or []
                    if not users:
                        raise RhythiaAPIError(translate("not_found", lang, query=query))
                    exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                    if len(users) > 1 and exact is None:
                        raise RhythiaAPIError(translate("multiple_found", lang, query=query))
                    user = exact or users[0]
                    return int(user["id"]), str(user.get("username") or query)
                resolver = _inline_resolve

            try:
                user_id, target_name = await resolver(interaction.user.id, client, query=query, lang=lang)
            except TypeError:
                user_id, target_name = await resolver(interaction.user.id, client, query=query)

            if user_id is None:
                await interaction.followup.send(translate("link_first", lang), ephemeral=True)
                return

            scores_data = await client.get_user_scores(user_id=user_id)
            all_scores = _sorted_scores_by_created_at(scores_data.get("lastDay") or [])

            if not all_scores:
                no_scores_msg = translate("recent_no_scores", lang, target_name=target_name)
                await interaction.followup.send(no_scores_msg, ephemeral=True)
                return

            avatar_url = None
            try:
                profile_data = await client.get_profile(user_id=int(user_id))
                profile_user = profile_data.get("user") or {}
                from rhythia.discord_embeds import _asset_url
                avatar = profile_user.get("avatar_url") or profile_user.get("profile_image")
                avatar_url = _asset_url(avatar)
            except Exception:
                pass

            unique_hashes = list({s.get("beatmapHash") for s in all_scores if s.get("beatmapHash")})
            hash_to_stars: dict[str, float | None] = {}
            
            async def _fetch_single_hash(h: str):
                try:
                    bm = await client.find_beatmap(h)
                    hash_to_stars[h] = bm.get("starRating") if bm else None
                except Exception:
                    hash_to_stars[h] = None

            if unique_hashes:
                await asyncio.gather(*(_fetch_single_hash(h) for h in unique_hashes))

            PAGE_SIZE = 5

            def build_page(page_items: list[Any], page: int, max_pages: int) -> discord.Embed:
                title_text = translate("scores_title", lang, target_name=target_name)
                embed = discord.Embed(
                    title=title_text,
                    color=0xF97316,
                    url=user_profile_url(user_id) if user_id else None,
                )
                if avatar_url:
                    embed.set_thumbnail(url=avatar_url)

                for score in page_items:
                    score_title = score.get("beatmapTitle") or score.get("songId") or "Unknown"
                    sp = score.get("awarded_sp") or 0
                    
                    h = score.get("beatmapHash")
                    stars = hash_to_stars.get(h) if h else score.get("starRating")
                    if stars is None:
                        stars = score.get("beatmapDifficulty") or score.get("difficulty")
                    
                    misses = score.get("misses") or 0
                    speed = score.get("speed")
                    passed = score.get("passed")
                    spin = score.get("spin")
                    created = score.get("created_at") or ""

                    stars_text = f"{stars:.2f}★" if isinstance(stars, (int, float)) else "—"
                    speed_text = f"{float(speed):.2f}x" if isinstance(speed, (int, float)) else "—"
                    result_icon = "✅" if passed else "❌"
                    mode = translate("score_spin" if spin else "score_classic", lang)

                    try:
                        from datetime import datetime
                        ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        time_str = ts.strftime("%m/%d %H:%M")
                    except Exception:
                        time_str = created[:16].replace("T", " ") if created else "—"

                    miss_label = translate("score_misses", lang)
                    embed.add_field(
                        name=f"{result_icon} {score_title}",
                        value=f"🏆 **{sp:,.0f} SP** | {stars_text} | {miss_label}: {misses} | {speed_text} | {mode} | `{time_str}` | ID: `{score.get('id') or '—'}`",
                        inline=False,
                    )

                footer_text = translate("scores_footer", lang, page=page, max_pages=max_pages, count=len(all_scores))
                embed.set_footer(text=footer_text)
                return embed

            from bot.embed_navigator import LocalEmbedNavigatorView
            first_page = all_scores[:PAGE_SIZE]
            max_pages = max(1, (len(all_scores) + PAGE_SIZE - 1) // PAGE_SIZE)
            embed = build_page(first_page, 1, max_pages)
            view = LocalEmbedNavigatorView(interaction, items=all_scores, build=build_page, page_size=PAGE_SIZE)
            await interaction.followup.send(embed=embed, view=view)

        except RhythiaAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in /gerhythia scores")
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)

    async def _resolve_user_for_scores(self, discord_id: int, client: RhythiaClient, *, query: str, lang: str = "en") -> tuple[int | None, str]:
        from utils.i18n import translate

        if not query:
            linked = self.bot.linked_accounts.get_account(discord_id)
            if not linked:
                return None, ""
            return linked.rhythia_user_id, linked.rhythia_username

        results = await client.search(query=query, limit=5)
        users = results.get("users") or []
        if not users:
            raise RhythiaAPIError(translate("not_found", lang, query=query))
        exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
        if len(users) > 1 and exact is None:
            raise RhythiaAPIError(translate("multiple_found", lang, query=query))
        user = exact or users[0]
        return int(user["id"]), str(user.get("username") or query)
