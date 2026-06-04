from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
import discord
from discord.ext import commands

from rhythia.api_client import RhythiaClient, BASE_URL
from rhythia.config import Settings
from rhythia.linked_accounts import LinkedAccountStore

logger = logging.getLogger(__name__)


class RhythiaBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        # Create a shared ThreadPoolExecutor for DB workers and pass to store
        from concurrent.futures import ThreadPoolExecutor
        self._db_executor = ThreadPoolExecutor(max_workers=8)
        self.linked_accounts = LinkedAccountStore(executor=self._db_executor)
        deleted = self.linked_accounts.cleanup_expired_pending()
        if deleted:
            pass
        self._presence_task: asyncio.Task[None] | None = None
        self._stats_cache: dict[str, int] = {}
        self._stats_updated: datetime | None = None
        self._http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        # Create shared HTTP session for connection reuse
        self._http_session = aiohttp.ClientSession()

        # Register per-category command Cogs (migration). We no longer
        # register the legacy consolidated `RhythiaSlashCommands` Cog to
        # avoid duplicate `gerhythia` group registration.
        from bot.compat import RhythiaCompat
        from commands.verify_commands import VerifyCommands
        from commands.account_commands import AccountCommands
        from commands.search_commands import SearchCommands
        from commands.maps_commands import MapsCommands
        from commands.leaderboard_commands import LeaderboardCommands
        from commands.recent_commands import RecentCommands
        from commands.misc_commands import MiscCommands

        # Register a single compatibility Cog that defines the shared `gerhythia`
        # app command group. Per-category cogs attach subcommands to this group
        # and must not recreate it.
        await self.add_cog(RhythiaCompat(self))

        # Register per-category command Cogs. These attach subcommands to the
        # already-registered `gerhythia` group exposed by `RhythiaCompat`.
        from discord import app_commands

        for cog_cls in (
            VerifyCommands,
            AccountCommands,
            SearchCommands,
            MapsCommands,
            LeaderboardCommands,
            RecentCommands,
            MiscCommands,
        ):
            try:
                await self.add_cog(cog_cls(self))
            except app_commands.errors.CommandAlreadyRegistered:
                # Already registered elsewhere (bot restart or previously registered group).
                # Safe to ignore and continue so startup doesn't crash.
                pass
        self._start_presence_task()

        if not self.settings.sync_commands:
            return

        await self.tree.sync()

        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)

    async def close(self) -> None:
        if self._presence_task:
            self._presence_task.cancel()
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        await super().close()

    def client_for(self, discord_id: int | None = None) -> RhythiaClient:
        """Return a RhythiaClient using the shared HTTP session."""
        return RhythiaClient(session=self._http_session)

    def _start_presence_task(self) -> None:
        if self._presence_task and not self._presence_task.done():
            return
        self._presence_task = asyncio.create_task(
            self._rotate_presence(),
            name="rhythia-presence",
        )

    async def _rotate_presence(self) -> None:
        await self.wait_until_ready()
        index = 0

        while not self.is_closed():
            messages = await self._get_presence_messages()
            message = messages[index % len(messages)]
            index += 1
            try:
                await self.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=message,
                    )
                )
            except discord.DiscordException:
                pass
            await asyncio.sleep(60)

    async def _get_presence_messages(self) -> list[str]:
        """Generate presence messages with real Rhythia stats."""
        await self._update_stats_cache()

        messages = [
            "/gerhythia help",
            "/gerhythia search",
        ]

        if beatmap_count := self._stats_cache.get("beatmaps"):
            messages.append(f"{beatmap_count:,} beatmaps")
        else:
            messages.append("/gerhythia maps")

        if player_count := self._stats_cache.get("players"):
            messages.append(f"{player_count:,} players")
        else:
            messages.append("Rhythia profiles")

        return messages

    async def _update_stats_cache(self) -> None:
        """Fetch Rhythia stats if cache is stale (older than 30 minutes)."""
        now = datetime.now()

        if self._stats_updated and (now - self._stats_updated) < timedelta(minutes=30):
            return

        try:
            stats = await self._fetch_rhythia_stats()
            self._stats_cache = stats
            self._stats_updated = now
        except Exception:
            pass

    async def _fetch_rhythia_stats(self) -> dict[str, int]:
        """Fetch stats from Rhythia API using the shared session."""
        stats = {}
        session = self._http_session
        if session is None or session.closed:
            return stats

        timeout = aiohttp.ClientTimeout(total=5)

        try:
            async with session.post(
                f"{BASE_URL}/getBeatmaps",
                headers={"Content-Type": "application/json"},
                json={
                    "session": "",
                    "page": 1,
                    "textFilter": "",
                    "authorFilter": "",
                    "tagsFilter": "",
                    "minStars": 0,
                    "maxStars": 20,
                    "status": "",
                },
                timeout=timeout,
            ) as response:
                if response.ok:
                    data = await response.json()
                    if isinstance(data, dict) and "total" in data:
                        stats["beatmaps"] = data["total"]
        except Exception:
            pass

        try:
            async with session.post(
                f"{BASE_URL}/getLeaderboard",
                headers={"Content-Type": "application/json"},
                json={"session": "", "page": 1, "spin": False, "include_inactive": False},
                timeout=timeout,
            ) as response:
                if response.ok:
                    data = await response.json()
                    if isinstance(data, dict) and "total" in data:
                        stats["players"] = data["total"]
        except Exception:
            pass

        return stats