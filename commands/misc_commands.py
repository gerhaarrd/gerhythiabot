"""Miscellaneous commands like help and link confirmation."""
from __future__ import annotations

import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import BASE_URL
from rhythia.discord_embeds import help_embed


from bot.compat import RhythiaCompat


class MiscCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="help", description="Command list and feedback contact")
    async def help_command(self, interaction: discord.Interaction) -> None:
        icon_file = discord.File("assets/icon.jpg", filename="icon.jpg")
        await interaction.response.send_message(embed=help_embed(), file=icon_file)

    @rhythia.command(name="stats", description="Show global Rhythia statistics")
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        # Force cache update if stale
        await self.bot._update_stats_cache()
        
        beatmaps = self.bot._stats_cache.get("beatmaps")
        players = self.bot._stats_cache.get("players")
        
        embed = discord.Embed(
            title="📊 Rhythia Server Statistics",
            color=0x8B5CF6, # Vibrant Violet
            url="https://rhythia.com",
            description="Real-time global statistics and server status of the Rhythia network."
        )
        
        embed.add_field(
            name="🎵 Total Beatmaps",
            value=f"```md\n# {beatmaps:,}\n```" if beatmaps else "```\n—\n```",
            inline=True
        )
        embed.add_field(
            name="👥 Active Players",
            value=f"```md\n# {players:,}\n```" if players else "```\n—\n```",
            inline=True
        )
        embed.add_field(
            name="📡 Server Status",
            value="```diff\n+ Online\n```" if (beatmaps or players) else "```diff\n- Issues\n```",
            inline=True
        )

        icon_file = discord.File("assets/icon.jpg", filename="icon.jpg")
        embed.set_thumbnail(url="attachment://icon.jpg")
        embed.set_footer(text="rhythia.com · Updated every 30 minutes")
        
        await interaction.followup.send(embed=embed, file=icon_file)

    @rhythia.command(name="ping", description="Show bot latency and Rhythia API status")
    async def ping(self, interaction: discord.Interaction) -> None:
        # Measure Discord WS latency before deferring
        ws_latency_ms = round(self.bot.latency * 1000)
        await interaction.response.defer(thinking=True)

        # Probe the Rhythia API
        api_latency_ms: int | None = None
        api_ok = False
        try:
            session = self.bot._http_session
            if session and not session.closed:
                t0 = time.monotonic()
                async with session.post(
                    f"{BASE_URL}/getLeaderboard",
                    headers={"Content-Type": "application/json"},
                    json={"session": "", "page": 1, "spin": False, "include_inactive": False},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    api_latency_ms = round((time.monotonic() - t0) * 1000)
                    api_ok = resp.ok
        except Exception:
            pass

        # Color by API health
        color = 0x10B981 if api_ok else 0xEF4444

        guild_count = len(self.bot.guilds)
        user_count = sum(g.member_count or 0 for g in self.bot.guilds)

        # Latency quality label
        def _latency_label(ms: int | None) -> str:
            if ms is None:
                return "—"
            if ms < 100:
                return f"```md\n# {ms} ms\n```"
            if ms < 250:
                return f"```fix\n{ms} ms\n```"
            return f"```diff\n- {ms} ms\n```"

        embed = discord.Embed(
            title="🏓 Pong!",
            color=color,
            description=(
                "```diff\n+ Rhythia Bot is Online\n```"
                if api_ok else
                "```diff\n- Rhythia API is Unavailable\n```"
            ),
        )

        # Row 1 — Latencies
        embed.add_field(
            name="🤖 Bot Latency",
            value=_latency_label(ws_latency_ms),
            inline=True,
        )
        embed.add_field(
            name="🌐 Rhythia API",
            value=_latency_label(api_latency_ms),
            inline=True,
        )
        embed.add_field(
            name="📡 API Status",
            value="```diff\n+ Online\n```" if api_ok else "```diff\n- Unavailable\n```",
            inline=True,
        )

        # Row 2 — Bot presence
        embed.add_field(
            name="🏠 Servers",
            value=f"```md\n# {guild_count:,}\n```",
            inline=True,
        )
        embed.add_field(
            name="👥 Users Reached",
            value=f"```md\n# {user_count:,}\n```",
            inline=True,
        )
        embed.add_field(
            name="🔗 Linked Accounts",
            value=f"```md\n# {self.bot.linked_accounts.count():,}\n```",
            inline=True,
        )


        icon_file = discord.File("assets/icon.jpg", filename="icon.jpg")
        embed.set_thumbnail(url="attachment://icon.jpg")
        embed.set_footer(text="rhythia.com · Not an official bot")
        await interaction.followup.send(embed=embed, file=icon_file)

