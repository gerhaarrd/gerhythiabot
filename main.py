#!/usr/bin/env python3
"""Start the Rhythia Discord bot."""

from __future__ import annotations

import asyncio
import logging
import sys

from bot.discord_bot import RhythiaBot
from rhythia.config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
# Voice warnings (PyNaCl/davey) — this bot does not use voice
logging.getLogger("discord.client").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        settings = Settings.for_bot()
    except ValueError as exc:
        sys.exit(1)

    bot = RhythiaBot(settings)

    @bot.event
    async def on_ready() -> None:
        pass

    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
