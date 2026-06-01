from __future__ import annotations

import logging
from io import BytesIO
from collections.abc import Callable
from datetime import datetime
from typing import Any
import discord
import requests
from discord import app_commands
from discord.ext import commands

from bot.discord_bot import RhythiaBot
from bot.embed_navigator import EmbedNavigatorView
from bot.link_account_ui import PublicLinkConfirmView, link_confirmation_embed
from rhythia.account_link import (
    AccountLinkError,
    find_link_candidates,
    verify_pending_rhythia_link,
)
from rhythia.api_client import RhythiaClient, public_search
from rhythia.api_errors import RhythiaAPIError
from rhythia.constants import COUNTRY_CHOICES, MAP_STATUS_CHOICES
from rhythia.discord_embeds import (
    beatmap_embed,
    beatmaps_embed,
    help_embed,
    leaderboard_embed,
    profile_embed,
    recent_score_embed,
    search_results_embed,
)

logger = logging.getLogger(__name__)

NOT_LINKED = (
    "You need to link your Rhythia username first. Use `/gerhythia link <username>`."
)
API_COOLDOWN_RATE = 5
API_COOLDOWN_PERIOD = 30.0
HEAVY_COOLDOWN_RATE = 2
HEAVY_COOLDOWN_PERIOD = 60.0


async def country_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    cur = current.lower()
    choices: list[app_commands.Choice[str]] = []
    for name, code in COUNTRY_CHOICES:
        if cur in name.lower() or cur in code.lower() or not cur:
            label = f"{name} ({code})" if code else name
            choices.append(app_commands.Choice(name=label, value=code or "GLOBAL"))
        if len(choices) >= 25:
            break
    return choices


def _normalize_country(value: str | None) -> str | None:
    if not value or value.upper() in {"", "GLOBAL"}:
        return None
    code = value.strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise ValueError("Invalid country. Use a 2-letter ISO code (e.g. BR, US).")
    return code


def _maps_filter_label(
    *,
    query: str,
    author: str,
    status: str,
    min_stars: float,
    max_stars: float,
) -> str:
    bits: list[str] = []
    if query:
        bits.append(f'q="{query}"')
    if author:
        bits.append(f'mapper="{author}"')
    if status:
        bits.append(status)
    if min_stars > 0 or max_stars < 20:
        bits.append(f"★ {min_stars}–{max_stars}")
    return " · ".join(bits) if bits else "Recent"


class RhythiaSlashCommands(commands.Cog):
    def __init__(self, bot: RhythiaBot) -> None:
        self.bot = bot

    rhythia = app_commands.Group(
        name="gerhythia",
        description="Rhythia API stats and search",
    )

    @rhythia.command(name="help", description="Command list and feedback contact")
    async def help_command(self, interaction: discord.Interaction) -> None:
        icon_file = discord.File("assets/icon.jpg", filename="icon.jpg")
        await interaction.response.send_message(embed=help_embed(), file=icon_file)

    @rhythia.command(
        name="link",
        description="Link your Discord to a public Rhythia profile",
    )
    @app_commands.checks.cooldown(HEAVY_COOLDOWN_RATE, HEAVY_COOLDOWN_PERIOD)
    @app_commands.describe(username="Your Rhythia username")
    async def link(
        self,
        interaction: discord.Interaction,
        username: app_commands.Range[str, 2, 64],
    ) -> None:
        if interaction.user is None:
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        query = username.strip()
        try:
            users = find_link_candidates(query, limit=5)
        except AccountLinkError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        if not users:
            await interaction.followup.send(
                f"No Rhythia player found for **{query}**.",
                ephemeral=True,
            )
            return

        exact = [
            user
            for user in users
            if (user.get("username") or "").lower() == query.lower()
        ]
        selected = exact[0] if exact else users[0]
        if len(users) > 1 and not exact:
            await interaction.followup.send(
                "I found multiple close matches. Confirm the first result below, "
                "or use `/gerhythia search` to inspect the list and link with a more exact username.",
                embed=search_results_embed({"users": users, "beatmaps": []}, query=query),
                ephemeral=True,
            )

        await interaction.followup.send(
            embed=link_confirmation_embed(selected),
            view=PublicLinkConfirmView(self.bot, interaction.user.id, selected),
            ephemeral=True,
        )

    @rhythia.command(name="unlink", description="Remove your Rhythia link")
    async def unlink(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        deleted_link = self.bot.linked_accounts.delete(interaction.user.id)
        deleted_pending = self.bot.linked_accounts.delete_pending(interaction.user.id)
        if deleted_link or deleted_pending:
            await interaction.response.send_message("Link removed.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "No linked account.", ephemeral=True
            )

    @rhythia.command(name="verify", description="Verify your pending Rhythia profile link")
    @app_commands.checks.cooldown(HEAVY_COOLDOWN_RATE, HEAVY_COOLDOWN_PERIOD)
    async def verify(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            username = verify_pending_rhythia_link(
                self.bot,
                discord_id=interaction.user.id,
            )
        except AccountLinkError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        await interaction.followup.send(
            f"**{username}** verified and linked. You can remove the code from your Rhythia about me now.",
            ephemeral=True,
        )

    @rhythia.command(name="account", description="Rhythia account linked to this Discord")
    async def account(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        linked = self.bot.linked_accounts.get_account(interaction.user.id)
        if linked is None:
            await interaction.response.send_message(NOT_LINKED, ephemeral=True)
            return
        await interaction.response.send_message(
            f"**{linked.rhythia_username}** · ID `{linked.rhythia_user_id}` · "
            f"since {_date_mmddyyyy(linked.linked_at)}",
            ephemeral=True,
        )

    @rhythia.command(
        name="search",
        description="Search players and beatmaps (no link required)",
    )
    @app_commands.checks.cooldown(API_COOLDOWN_RATE, API_COOLDOWN_PERIOD)
    @app_commands.describe(query="Player or beatmap name")
    async def search(
        self,
        interaction: discord.Interaction,
        query: app_commands.Range[str, 2, 64],
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            data = public_search(query=query.strip(), limit=12)
            await interaction.followup.send(
                embed=search_results_embed(data, query=query.strip())
            )
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Search failed: {exc}", ephemeral=True)

    @rhythia.command(name="profile", description="Rhythia profile (yours or another player)")
    @app_commands.checks.cooldown(API_COOLDOWN_RATE, API_COOLDOWN_PERIOD)
    @app_commands.describe(
        username="Player name (empty = linked account).",
    )
    async def profile(
        self,
        interaction: discord.Interaction,
        username: str | None = None,
    ) -> None:
        if interaction.user is None:
            return

        query = (username or "").strip()
        if not query:
            linked = self.bot.linked_accounts.get_account(interaction.user.id)
            if not linked or linked.rhythia_user_id is None:
                await interaction.response.send_message(NOT_LINKED, ephemeral=True)
                return
            await self._reply_with_embed(
                interaction,
                fetch=lambda c: c.get_profile(user_id=linked.rhythia_user_id),
                build=profile_embed,
            )
            return

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()

        try:
            with client:
                results = client.search(query=query, limit=5)
                users = results.get("users") or []
                if not users:
                    await interaction.followup.send(
                        f"No player found for **{query}**.",
                        ephemeral=True,
                    )
                    return
                if len(users) > 1 and not _exact_username_match(users, query):
                    await interaction.followup.send(
                        embed=search_results_embed(results, query=query)
                    )
                    return
                data = client.get_profile(user_id=int(users[0]["id"]))
            await interaction.followup.send(embed=profile_embed(data))
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    @rhythia.command(name="leaderboard", description="Skill points leaderboard")
    @app_commands.checks.cooldown(API_COOLDOWN_RATE, API_COOLDOWN_PERIOD)
    @app_commands.describe(
        country="Country (ISO code) or Global",
        page="Page (50 players per page)",
        limit="Rows in embed (max 15)",
        spin="Spin skill ranking",
    )
    @app_commands.autocomplete(country=country_autocomplete)
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        country: str | None = None,
        page: app_commands.Range[int, 1, 100] = 1,
        limit: app_commands.Range[int, 1, 15] = 10,
        spin: bool = False,
    ) -> None:
        if interaction.user is None:
            return

        try:
            country_code = _normalize_country(country)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        # Defer early to avoid interaction timeout / double-ack errors
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                logger.warning("Interaction expired (discord=%s)", interaction.user.id)
                return

        # Get user's rank from linked account if available
        user_position: int | None = None
        linked = self.bot.linked_accounts.get_account(interaction.user.id)
        if linked and linked.rhythia_user_id:
            try:
                client = self.bot.client_for()
                with client:
                    profile = client.get_profile(user_id=linked.rhythia_user_id)
                    user_data = profile.get("user", {})
                    # Use global position for global leaderboard, country_position for country leaderboard
                    raw_pos = user_data.get("country_position") if country_code else user_data.get("position")
                    if raw_pos is not None:
                        try:
                            pos_int = int(raw_pos)
                            if pos_int > 0:
                                user_position = pos_int
                        except (TypeError, ValueError):
                            # ignore non-integer positions
                            pass
            except RhythiaAPIError:
                # If we can't fetch position, just show leaderboard without user position
                pass

        await self._reply_with_navigable_embed(
            interaction,
            fetch=lambda c, p: c.get_leaderboard(
                page=p, country=country_code, spin=spin
            ),
            build=lambda d: leaderboard_embed(
                d, limit=limit, country=country_code, spin=spin, user_position=user_position
            ),
            initial_page=page,
        )

    @rhythia.command(name="maps", description="Browse and filter beatmaps")
    @app_commands.checks.cooldown(API_COOLDOWN_RATE, API_COOLDOWN_PERIOD)
    @app_commands.describe(
        title="Text in map title",
        mapper="Mapper username",
        status="Map status",
        min_stars="Minimum star rating",
        max_stars="Maximum star rating",
        page="Page number",
        limit="Maps in embed (max 10)",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name=label, value=value)
            for label, value in MAP_STATUS_CHOICES
        ]
    )
    async def maps(
        self,
        interaction: discord.Interaction,
        title: str | None = None,
        mapper: str | None = None,
        status: app_commands.Choice[str] | None = None,
        min_stars: app_commands.Range[float, 0, 20] = 0,
        max_stars: app_commands.Range[float, 0, 20] = 20,
        page: app_commands.Range[int, 1, 100] = 1,
        limit: app_commands.Range[int, 1, 10] = 8,
    ) -> None:
        if min_stars > max_stars:
            await interaction.response.send_message(
                "Minimum stars cannot be greater than maximum.",
                ephemeral=True,
            )
            return

        status_val = status.value if status else ""
        query = (title or "").strip()
        author = (mapper or "").strip()
        label = _maps_filter_label(
            query=query,
            author=author,
            status=status_val,
            min_stars=min_stars,
            max_stars=max_stars,
        )

        await self._reply_with_navigable_embed(
            interaction,
            fetch=lambda c, p: c.get_beatmaps(
                page=p,
                query=query,
                author=author,
                status=status_val,
                min_stars=min_stars,
                max_stars=max_stars,
            ),
            build=lambda d: beatmaps_embed(d, limit=limit, filters_label=label),
            initial_page=page,
        )

    @rhythia.command(name="beatmap", description="Show one beatmap by id or title")
    @app_commands.checks.cooldown(API_COOLDOWN_RATE, API_COOLDOWN_PERIOD)
    @app_commands.describe(query="Beatmap id or title")
    async def beatmap(
        self,
        interaction: discord.Interaction,
        query: app_commands.Range[str, 1, 120],
    ) -> None:
        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        try:
            with client:
                beatmap = client.find_beatmap(query)
            if not beatmap:
                await interaction.followup.send(
                    f"No beatmap found for **{query}**.",
                    ephemeral=True,
                )
                return
            embed = beatmap_embed(beatmap)
            image_file = _beatmap_image_file(beatmap)
            if image_file:
                embed.set_image(url=f"attachment://{image_file.filename}")
                await interaction.followup.send(embed=embed, file=image_file)
            else:
                await interaction.followup.send(embed=embed)
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    @rhythia.command(name="recent", description="Show a player's latest public score")
    @app_commands.checks.cooldown(API_COOLDOWN_RATE, API_COOLDOWN_PERIOD)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def recent(
        self,
        interaction: discord.Interaction,
        username: str | None = None,
    ) -> None:
        if interaction.user is None:
            return

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            with client:
                user_id, target_name = self._resolve_user_for_scores(
                    interaction.user.id,
                    client,
                    query=query,
                )
                if user_id is None:
                    await interaction.followup.send(NOT_LINKED, ephemeral=True)
                    return

                scores_data = client.get_user_scores(user_id=user_id)
                recent_scores = _sorted_scores_by_created_at(scores_data.get("lastDay") or [])
                if not recent_scores:
                    await interaction.followup.send(
                        f"**{target_name}** has no recent public scores.",
                        ephemeral=True,
                    )
                    return

            await interaction.followup.send(
                embed=recent_score_embed(recent_scores[0], username=target_name)
            )
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    @rhythia.command(name="suggest", description="Suggest Ranked maps based on user's top scores")
    @app_commands.checks.cooldown(HEAVY_COOLDOWN_RATE, HEAVY_COOLDOWN_PERIOD)
    @app_commands.describe(
        username="Player name (empty = linked account).",
    )
    async def suggest(
        self,
        interaction: discord.Interaction,
        username: str | None = None,
    ) -> None:
        if interaction.user is None:
            return

        await interaction.response.defer(thinking=True)
        client = self.bot.client_for()

        query = (username or "").strip()
        
        try:
            with client:
                user_id, target_name = self._resolve_user_for_scores(
                    interaction.user.id,
                    client,
                    query=query,
                )
                if user_id is None:
                    await interaction.followup.send(NOT_LINKED, ephemeral=True)
                    return

                scores_data = client.get_user_scores(user_id=user_id)
                top_scores = scores_data.get("top") or []
                
                if not top_scores:
                    await interaction.followup.send(f"**{target_name}** has no top scores yet.")
                    return
                
                # Usar até 10 top scores para a média
                top_10 = top_scores[:10]
                avg_stars = sum(s.get("beatmapDifficulty") or 0 for s in top_10) / len(top_10)
                avg_rp = sum(s.get("awarded_sp") or 0 for s in top_10) / len(top_10)

                min_stars = max(0.0, avg_stars - 0.2)
                max_stars = avg_stars + 0.4
                
                filters_label = f"{target_name} · Avg {avg_rp:.0f} RP · {min_stars:.1f}★–{max_stars:.1f}★"

                maps_data = client.get_beatmaps(
                    page=1,
                    status="RANKED",
                    min_stars=min_stars,
                    max_stars=max_stars,
                )
                
            await interaction.followup.send(embed=beatmaps_embed(maps_data, limit=8, filters_label=filters_label))
        except RhythiaAPIError as exc:
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)

    def _resolve_user_for_scores(
        self,
        discord_id: int,
        client: RhythiaClient,
        *,
        query: str,
    ) -> tuple[int | None, str]:
        if not query:
            linked = self.bot.linked_accounts.get_account(discord_id)
            if not linked:
                return None, ""
            return linked.rhythia_user_id, linked.rhythia_username

        results = client.search(query=query, limit=5)
        users = results.get("users") or []
        if not users:
            raise RhythiaAPIError(f"No player found for {query}.")
        exact = _exact_user(users, query)
        if len(users) > 1 and exact is None:
            raise RhythiaAPIError(
                f"Multiple players found for {query}. Use a more exact username."
            )
        user = exact or users[0]
        return int(user["id"]), str(user.get("username") or query)

    async def _reply_with_embed(
        self,
        interaction: discord.Interaction,
        *,
        fetch: Callable[[RhythiaClient], dict[str, Any]],
        build: Callable[[dict[str, Any]], discord.Embed],
    ) -> None:
        if interaction.user is None:
            return

        client = self.bot.client_for()

        # Only defer if response hasn't been sent yet
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                # Interaction expired, can't respond
                logger.warning("Interaction expired (discord=%s)", interaction.user.id)
                return
        
        try:
            with client:
                data = fetch(client)
            await interaction.followup.send(embed=build(data))
        except RhythiaAPIError as exc:
            logger.warning("API (discord=%s): %s", interaction.user.id, exc)
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception:
            logger.exception("Error in command %s", interaction.command)
            await interaction.followup.send("Internal error.", ephemeral=True)

    async def _reply_with_navigable_embed(
        self,
        interaction: discord.Interaction,
        *,
        fetch: Callable[[RhythiaClient, int], dict[str, Any]],
        build: Callable[[dict[str, Any]], discord.Embed],
        initial_page: int = 1,
    ) -> None:
        """Reply with an embed that has navigation buttons."""
        if interaction.user is None:
            return

        client = self.bot.client_for()

        # Only defer if response hasn't been sent yet
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                # Interaction expired, can't respond
                logger.warning("Interaction expired (discord=%s)", interaction.user.id)
                return
        
        try:
            with client:
                data = fetch(client, initial_page)

            # Calculate max pages from response data
            total = data.get("total", 0)
            per_page = data.get("viewPerPage", 50)
            max_pages = (total + per_page - 1) // per_page if total > 0 else 1

            embed = build(data)
            view = EmbedNavigatorView(
                interaction,
                fetch=fetch,
                build=build,
                initial_data=data,
                initial_page=initial_page,
                max_pages=max_pages,
            )
            await interaction.followup.send(embed=embed, view=view)
        except RhythiaAPIError as exc:
            logger.warning("API (discord=%s): %s", interaction.user.id, exc)
            await interaction.followup.send(f"Error: {exc}", ephemeral=True)
        except Exception:
            logger.exception("Error in command %s", interaction.command)
            await interaction.followup.send("Internal error.", ephemeral=True)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            retry_after = max(1, round(error.retry_after))
            message = f"Slow down a bit. Try again in **{retry_after}s**."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        logger.exception("Unhandled app command error: %s", interaction.command, exc_info=error)
        message = "Internal error."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def _exact_username_match(users: list[dict[str, Any]], query: str) -> bool:
    return _exact_user(users, query) is not None


def _exact_user(users: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    q = query.lower()
    return next((u for u in users if (u.get("username") or "").lower() == q), None)


def _sorted_scores_by_created_at(scores: list[Any]) -> list[dict[str, Any]]:
    typed_scores = [score for score in scores if isinstance(score, dict)]
    return sorted(
        typed_scores,
        key=lambda score: str(score.get("created_at") or ""),
        reverse=True,
    )


def _beatmap_image_file(beatmap: dict[str, Any]) -> discord.File | None:
    image_url = beatmap.get("image")
    if not isinstance(image_url, str) or not image_url.strip():
        return None

    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return None

    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    extensions = {
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    extension = extensions.get(content_type)
    if extension is None or len(response.content) > 8_000_000:
        return None

    beatmap_id = beatmap.get("id") or "cover"
    return discord.File(
        BytesIO(response.content),
        filename=f"beatmap-{beatmap_id}.{extension}",
    )


def _date_mmddyyyy(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%m/%d/%Y")
    except ValueError:
        return value[:10]
