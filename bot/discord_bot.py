from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import discord
import requests
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.config import Settings
from rhythia.linked_accounts import LinkedAccountStore

logger = logging.getLogger(__name__)

BASE_URL = "https://production.rhythia.com/api"


class RhythiaBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.linked_accounts = LinkedAccountStore()
        deleted = self.linked_accounts.cleanup_expired_pending()
        if deleted:
            logger.info("Removed %d expired pending link(s)", deleted)
        self._presence_task: asyncio.Task[None] | None = None
        self._stats_cache: dict[str, int] = {}
        self._stats_updated: datetime | None = None

    def client_for(self, discord_id: int | None = None) -> RhythiaClient:
        return RhythiaClient()

    async def setup_hook(self) -> None:
        from bot.slash_commands import RhythiaSlashCommands

        await self.add_cog(RhythiaSlashCommands(self))
        self._start_presence_task()

        if not self.settings.sync_commands:
            logger.info("Command sync skipped (SKIP_COMMAND_SYNC=1)")
            return

        # Always sync globally for public bot
        await self.tree.sync()
        logger.info("Commands synced globally")

        # Optionally also sync to a specific guild for faster testing
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Commands also synced to guild %s for faster testing", self.settings.guild_id)

    async def close(self) -> None:
        if self._presence_task:
            self._presence_task.cancel()
        await super().close()

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
            except discord.DiscordException as exc:
                logger.warning("Could not update Discord presence: %s", exc)
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
        
        # Only update if cache is empty or older than 30 minutes
        if self._stats_updated and (now - self._stats_updated) < timedelta(minutes=30):
            return
        
        loop = asyncio.get_event_loop()
        try:
            stats = await loop.run_in_executor(None, self._fetch_rhythia_stats)
            self._stats_cache = stats
            self._stats_updated = now
            logger.info("Updated Rhythia stats: %s", stats)
        except Exception as exc:
            logger.warning("Failed to fetch Rhythia stats: %s", exc)

    @staticmethod
    def _fetch_rhythia_stats() -> dict[str, int]:
        """Fetch stats from Rhythia API (blocking call, run in executor)."""
        stats = {}
        
        try:
            # Get beatmap count
            response = requests.post(
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
                timeout=5,
            )
            if response.ok:
                data = response.json()
                if isinstance(data, dict) and "total" in data:
                    stats["beatmaps"] = data["total"]
        except Exception as exc:
            logger.debug("Failed to get beatmap stats: %s", exc)
        
        try:
            # Get player/leaderboard count
            response = requests.post(
                f"{BASE_URL}/getLeaderboard",
                headers={"Content-Type": "application/json"},
                json={"session": "", "page": 1, "spin": False, "include_inactive": False},
                timeout=5,
            )
            if response.ok:
                data = response.json()
                if isinstance(data, dict) and "total" in data:
                    stats["players"] = data["total"]
        except Exception as exc:
            logger.debug("Failed to get leaderboard stats: %s", exc)
        
        return stats
