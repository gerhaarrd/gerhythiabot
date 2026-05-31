from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.config import Settings
from rhythia.linked_accounts import LinkedAccountStore

logger = logging.getLogger(__name__)


class RhythiaBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.linked_accounts = LinkedAccountStore()
        deleted = self.linked_accounts.cleanup_expired_tokens()
        if deleted:
            logger.info("Removed %d expired linked account(s)", deleted)
        self._presence_task: asyncio.Task[None] | None = None

    def client_for(self, discord_id: int) -> RhythiaClient:
        return RhythiaClient(self.linked_accounts.get_session_token(discord_id))

    async def setup_hook(self) -> None:
        from bot.slash_commands import RhythiaSlashCommands

        await self.add_cog(RhythiaSlashCommands(self))
        self._start_presence_task()

        if not self.settings.sync_commands:
            logger.info("Command sync skipped (SKIP_COMMAND_SYNC=1)")
            return

        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            self.tree.clear_commands(guild=None)
            await self.tree.sync(guild=None)
            logger.info("Commands synced to guild %s (global cleared to avoid duplicates)", self.settings.guild_id)
        else:
            await self.tree.sync()
            logger.info("Commands synced globally")

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

        messages = self._presence_messages()
        index = 0

        while not self.is_closed():
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

    @staticmethod
    def _presence_messages() -> list[str]:
        return [
            "/gerhythia help",
            "/gerhythia search",
            "/gerhythia maps",
            "Rhythia profiles",
            "Rhythia beatmaps",
        ]
