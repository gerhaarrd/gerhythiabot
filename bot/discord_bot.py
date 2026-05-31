from __future__ import annotations

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

    def client_for(self, discord_id: int) -> RhythiaClient:
        return RhythiaClient(self.linked_accounts.get_session_token(discord_id))

    async def setup_hook(self) -> None:
        from bot.slash_commands import RhythiaSlashCommands

        await self.add_cog(RhythiaSlashCommands(self))

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
