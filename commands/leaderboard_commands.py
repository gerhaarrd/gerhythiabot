"""Leaderboard-related commands."""
from __future__ import annotations

from typing import Any

import logging
import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from rhythia.constants import COUNTRY_CHOICES
from rhythia.discord_embeds import leaderboard_embed
from utils.helpers import _exact_username_match, _exact_user, country_autocomplete
from typing import Callable, Awaitable
from rhythia.discord_embeds import search_results_embed

logger = logging.getLogger(__name__)


from bot.compat import RhythiaCompat


class LeaderboardCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="leaderboard", description="Skill points leaderboard (10 players per page)")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(country="Country (ISO code) or Global", spin="Spin skill ranking")
    @app_commands.autocomplete(country=country_autocomplete)
    async def leaderboard(self, interaction: discord.Interaction, country: str | None = None, spin: bool = False) -> None:
        LEADERBOARD_LIMIT = 10
        if interaction.user is None:
            return

        try:
            country_code = country and country.strip().upper()
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                return

        user_position: int | None = None
        linked = self.bot.linked_accounts.get_account(interaction.user.id)
        if linked and linked.rhythia_user_id:
            try:
                client = self.bot.client_for()
                profile = await client.get_profile(user_id=linked.rhythia_user_id)
                user_data = profile.get("user", {})
                raw_pos = user_data.get("country_position") if country_code else user_data.get("position")
                if raw_pos is not None:
                    try:
                        pos_int = int(raw_pos)
                        if pos_int > 0:
                            user_position = pos_int
                    except (TypeError, ValueError):
                        pass
            except RhythiaAPIError:
                pass

        await self._reply_with_navigable_embed(
            interaction,
            fetch=lambda c, p: c.get_leaderboard(page=p, country=country_code, spin=spin),
            build=lambda d, up=1: leaderboard_embed(d, up, limit=LEADERBOARD_LIMIT, country=country_code, spin=spin, user_position=user_position),
            page_size=LEADERBOARD_LIMIT,
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

    @rhythia.command(name="nearby", description="Show players ranked near you or a target player")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account)", spin="Spin skill ranking")
    async def nearby(self, interaction: discord.Interaction, username: str | None = None, spin: bool = False) -> None:
        if interaction.user is None:
            return

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            # Resolve target user id & username
            if not query:
                linked = self.bot.linked_accounts.get_account(interaction.user.id)
                if not linked:
                    await interaction.followup.send("You need to link your Rhythia username first. Use `/gerhythia link <username>`.", ephemeral=True)
                    return
                user_id = linked.rhythia_user_id
                target_name = linked.rhythia_username
            else:
                results = await client.search(query=query, limit=5)
                users = results.get("users") or []
                if not users:
                    await interaction.followup.send(f"No player found for {query}.", ephemeral=True)
                    return
                exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                if len(users) > 1 and exact is None:
                    await interaction.followup.send(f"Multiple players found for {query}. Use a more exact username.", ephemeral=True)
                    return
                user = exact or users[0]
                user_id = int(user["id"])
                target_name = str(user.get("username") or query)

            # Fetch profile
            profile = await client.get_profile(user_id=user_id)
            user_data = profile.get("user", {})
            position = user_data.get("position")
            if position is None:
                await interaction.followup.send(f"Player **{target_name}** has no rank position.", ephemeral=True)
                return

            try:
                pos_int = int(position)
            except (TypeError, ValueError):
                await interaction.followup.send(f"Player **{target_name}** has an invalid rank position.", ephemeral=True)
                return

            if pos_int <= 0:
                await interaction.followup.send(f"Player **{target_name}** is unranked.", ephemeral=True)
                return

            # Center 10 players around pos_int
            api_page = (pos_int - 1) // 50 + 1
            data = await client.get_leaderboard(page=api_page, spin=spin)
            entries = data.get("leaderboard") or []
            
            # Find the user's index in the leaderboard entries list
            idx = -1
            for i, entry in enumerate(entries):
                if entry.get("id") == user_id:
                    idx = i
                    break
            
            if idx == -1:
                idx = (pos_int - 1) % 50
            
            start = max(0, idx - 4)
            if start + 10 > len(entries):
                start = max(0, len(entries) - 10)
            
            sliced_entries = entries[start:start + 10]
            start_rank = (api_page - 1) * 50 + start + 1
            
            from rhythia.discord_embeds import flag_emoji, EMBED_COLOR_LEADERBOARD, user_url
            lines = []
            for index, entry in enumerate(sliced_entries):
                rank = start_rank + index
                flag = flag_emoji(entry.get("flag"))
                username_val = entry.get("username", "?")
                uid = entry.get("id")
                name_str = f"[{username_val}]({user_url(uid)})" if uid else f"**{username_val}**"
                skill = entry.get("skill_points")
                skill_str = f"{skill:,.1f}" if isinstance(skill, (int, float)) else "—"
                clans = entry.get("clans")
                clan = f" `{clans['acronym']}`" if isinstance(clans, dict) else ""
                
                if uid == user_id:
                    line = f"👉 `#{rank:>3}` {flag} **{username_val}** — **{skill_str}** SP{clan}"
                else:
                    if rank == 1:
                        rank_str = "🥇"
                    elif rank == 2:
                        rank_str = "🥈"
                    elif rank == 3:
                        rank_str = "🥉"
                    else:
                        rank_str = f"`#{rank:>3}`"
                    line = f"{rank_str} {flag} {name_str} — **{skill_str}** SP{clan}"
                lines.append(line)
            
            spin_label = " (Spin)" if spin else ""
            embed = discord.Embed(
                title=f"👥 Players Nearby {target_name}{spin_label}",
                description="\n".join(lines) if lines else "_No players nearby found._",
                color=EMBED_COLOR_LEADERBOARD
            )
            embed.set_footer(text=f"Centered around rank #{pos_int:,}")
            await interaction.followup.send(embed=embed)
            
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in /gerhythia nearby")
            await interaction.followup.send("Internal error.", ephemeral=True)

    @rhythia.command(name="milestone", description="Show competitive milestones and SP/ranks needed")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account)")
    async def milestone(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            # Resolve target user
            if not query:
                linked = self.bot.linked_accounts.get_account(interaction.user.id)
                if not linked:
                    await interaction.followup.send("You need to link your Rhythia username first. Use `/gerhythia link <username>`.", ephemeral=True)
                    return
                user_id = linked.rhythia_user_id
                target_name = linked.rhythia_username
            else:
                results = await client.search(query=query, limit=5)
                users = results.get("users") or []
                if not users:
                    await interaction.followup.send(f"No player found for {query}.", ephemeral=True)
                    return
                exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                if len(users) > 1 and exact is None:
                    await interaction.followup.send(f"Multiple players found for {query}. Use a more exact username.", ephemeral=True)
                    return
                user = exact or users[0]
                user_id = int(user["id"])
                target_name = str(user.get("username") or query)

            # Fetch profile
            profile = await client.get_profile(user_id=user_id)
            user_data = profile.get("user", {})
            sp = user_data.get("skill_points") or 0.0
            position = user_data.get("position")
            
            try:
                sp_val = float(sp)
            except (TypeError, ValueError):
                sp_val = 0.0

            try:
                pos_val = int(position) if position is not None else 0
            except (TypeError, ValueError):
                pos_val = 0

            # 1. SP Milestones
            import math
            sp_100_target = math.ceil((sp_val + 0.01) / 100) * 100
            sp_500_target = math.ceil((sp_val + 0.01) / 500) * 500
            sp_1000_target = math.ceil((sp_val + 0.01) / 1000) * 1000

            sp_100_diff = sp_100_target - sp_val
            sp_500_diff = sp_500_target - sp_val
            sp_1000_diff = sp_1000_target - sp_val

            # 2. Rank Milestones
            rank_targets = [1000, 500, 250, 100, 50, 10, 1]
            next_rank_target = None
            for t in rank_targets:
                if pos_val > t:
                    next_rank_target = t
                    break
            
            rank_threshold_sp = None
            if next_rank_target is not None:
                api_page = (next_rank_target - 1) // 50 + 1
                lead_data = await client.get_leaderboard(page=api_page)
                lead_entries = lead_data.get("leaderboard") or []
                
                target_idx = (next_rank_target - 1) % 50
                if len(lead_entries) > target_idx:
                    entry = lead_entries[target_idx]
                    rank_threshold_sp = entry.get("skill_points")

            from rhythia.discord_embeds import EMBED_COLOR_PROFILE
            embed = discord.Embed(
                title=f"🎯 Milestone Progress for {target_name}",
                color=EMBED_COLOR_PROFILE
            )
            
            sp_text = (
                f"• **{sp_100_target:,} SP** Milestone: needs **+{sp_100_diff:.2f} SP**\n"
                f"• **{sp_500_target:,} SP** Milestone: needs **+{sp_500_diff:.2f} SP**\n"
                f"• **{sp_1000_target:,} SP** Milestone: needs **+{sp_1000_diff:.2f} SP**"
            )
            embed.add_field(name="✨ Skill Points Milestones", value=sp_text, inline=False)

            if pos_val > 0:
                rank_milestone_title = f"🏆 Next Rank Milestone: Top {next_rank_target}"
                if next_rank_target == 1:
                    rank_milestone_title = "🏆 Next Rank Milestone: Top 1 (Rank Leader)"
                
                if next_rank_target is None:
                    rank_text = "You are already rank #1! There are no higher rank milestones."
                elif rank_threshold_sp is not None:
                    try:
                        thresh_val = float(rank_threshold_sp)
                        diff = thresh_val - sp_val
                        if diff <= 0:
                            rank_text = f"You are currently rank **#{pos_val:,}**. Rank **#{next_rank_target:,}** has **{thresh_val:,.2f} SP** (you are very close!)."
                        else:
                            rank_text = (
                                f"• Current Rank: **#{pos_val:,}** ({sp_val:,.2f} SP)\n"
                                f"• Target Rank: **#{next_rank_target:,}** ({thresh_val:,.2f} SP)\n"
                                f"• SP needed: **+{diff:.2f} SP**"
                            )
                    except Exception:
                        rank_text = f"Could not retrieve threshold SP for Rank **#{next_rank_target}**."
                else:
                    rank_text = f"Current Rank: **#{pos_val:,}**. Next rank target is **#{next_rank_target}** (threshold SP unavailable)."
                
                embed.add_field(name=rank_milestone_title, value=rank_text, inline=False)
            else:
                embed.add_field(name="🏆 Rank Milestone", value="Unranked player has no rank milestone.", inline=False)

            embed.set_footer(text="rhythia.com · Keep pushing!")
            await interaction.followup.send(embed=embed)

        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in /gerhythia milestone")
            await interaction.followup.send("Internal error.", ephemeral=True)
