"""Miscellaneous commands like help and link confirmation."""
from __future__ import annotations

import os
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import BASE_URL
from rhythia.discord_embeds import (
    help_embed,
    help_overview_embed,
    help_account_embed,
    help_stats_embed,
    help_utils_embed,
)


from bot.compat import RhythiaCompat


from utils.i18n import translate


class HelpDropdown(discord.ui.Select):
    def __init__(self, lang: str = "en") -> None:
        options = [
            discord.SelectOption(
                label=translate("help_label_overview", lang),
                description=translate("help_desc_overview", lang),
                emoji="📖",
                value="overview",
                default=True,
            ),
            discord.SelectOption(
                label=translate("help_label_account", lang),
                description=translate("help_desc_account", lang),
                emoji="🔑",
                value="account",
            ),
            discord.SelectOption(
                label=translate("help_label_stats", lang),
                description=translate("help_desc_stats", lang),
                emoji="📊",
                value="stats",
            ),
            discord.SelectOption(
                label=translate("help_label_utils", lang),
                description=translate("help_desc_utils", lang),
                emoji="⚙️",
                value="utils",
            ),
        ]
        super().__init__(
            placeholder=translate("help_placeholder", lang),
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        for option in self.options:
            option.default = option.value == self.values[0]

        lang = getattr(self.view, "lang", "en")
        category = self.values[0]
        if category == "overview":
            embed = help_overview_embed(lang=lang)
        elif category == "account":
            embed = help_account_embed(lang=lang)
        elif category == "stats":
            embed = help_stats_embed(lang=lang)
        else:
            embed = help_utils_embed(lang=lang)

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, user_id: int, lang: str = "en") -> None:
        super().__init__(timeout=180)
        self.user_id = user_id
        self.lang = lang
        self.add_item(HelpDropdown(lang))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                translate("help_err_only_user", self.lang),
                ephemeral=True,
            )
            return False
        return True


class MiscCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="help", description="Command list and feedback contact")
    async def help_command(self, interaction: discord.Interaction) -> None:
        lang = self._get_lang(interaction)
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(root_dir, "assets", "icon.jpg")
        icon_file = discord.File(icon_path, filename="icon.jpg")
        view = HelpView(interaction.user.id, lang=lang)
        await interaction.response.send_message(embed=help_embed(lang=lang), file=icon_file, view=view)

    @rhythia.command(name="stats", description="Show global Rhythia statistics")
    async def stats(self, interaction: discord.Interaction) -> None:
        lang = self._get_lang(interaction)
        await interaction.response.defer(thinking=True)
        # Force cache update if stale
        await self.bot._update_stats_cache()
        
        beatmaps = self.bot._stats_cache.get("beatmaps")
        players = self.bot._stats_cache.get("players")
        
        embed = discord.Embed(
            title=translate("stats_title", lang),
            color=0x8B5CF6, # Vibrant Violet
            url="https://rhythia.com",
            description=translate("stats_desc", lang)
        )
        
        embed.add_field(
            name=translate("stats_total_maps", lang),
            value=f"```md\n# {beatmaps:,}\n```" if beatmaps else "```\n—\n```",
            inline=True
        )
        embed.add_field(
            name=translate("stats_active_players", lang),
            value=f"```md\n# {players:,}\n```" if players else "```\n—\n```",
            inline=True
        )
        embed.add_field(
            name=translate("stats_server_status", lang),
            value="```diff\n+ Online\n```" if (beatmaps or players) else "```diff\n- Issues\n```",
            inline=True
        )

        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(root_dir, "assets", "icon.jpg")
        icon_file = discord.File(icon_path, filename="icon.jpg")
        embed.set_thumbnail(url="attachment://icon.jpg")
        embed.set_footer(text=translate("stats_footer", lang))
        
        await interaction.followup.send(embed=embed, file=icon_file)

    @rhythia.command(name="ping", description="Show bot latency and Rhythia API status")
    async def ping(self, interaction: discord.Interaction) -> None:
        lang = self._get_lang(interaction)
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
            title=translate("ping_title", lang),
            color=color,
            description=(
                f"```diff\n+ {translate('ping_online', lang)}\n```"
                if api_ok else
                f"```diff\n- {translate('ping_offline', lang)}\n```"
            ),
        )

        # Row 1 — Latencies
        embed.add_field(
            name=translate("ping_bot_latency", lang),
            value=_latency_label(ws_latency_ms),
            inline=True,
        )
        embed.add_field(
            name=translate("ping_api", lang),
            value=_latency_label(api_latency_ms),
            inline=True,
        )
        embed.add_field(
            name=translate("ping_api_status", lang),
            value="```diff\n+ Online\n```" if api_ok else "```diff\n- Unavailable\n```",
            inline=True,
        )

        # Row 2 — Bot presence
        embed.add_field(
            name=translate("ping_servers", lang),
            value=f"```md\n# {guild_count:,}\n```",
            inline=True,
        )
        embed.add_field(
            name=translate("ping_users", lang),
            value=f"```md\n# {user_count:,}\n```",
            inline=True,
        )
        embed.add_field(
            name=translate("ping_linked", lang),
            value=f"```md\n# {self.bot.linked_accounts.count():,}\n```",
            inline=True,
        )

        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(root_dir, "assets", "icon.jpg")
        icon_file = discord.File(icon_path, filename="icon.jpg")
        embed.set_thumbnail(url="attachment://icon.jpg")
        embed.set_footer(text=translate("ping_footer", lang))
        await interaction.followup.send(embed=embed, file=icon_file)

