"""Command cog to handle generating graphical profile cards."""

from __future__ import annotations

import logging
import discord
from discord import app_commands
from discord.ext import commands

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError
from bot.compat import RhythiaCompat
from utils.i18n import translate
from utils.card_generator import generate_profile_card

logger = logging.getLogger(__name__)

class ProfileCardCommands(RhythiaCompat):
    rhythia = RhythiaCompat.rhythia

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @rhythia.command(name="card", description="Generate a beautiful graphical profile card with a radar chart")
    @app_commands.checks.cooldown(5, 30.0)
    @app_commands.describe(username="Player name (empty = linked account).")
    async def card(self, interaction: discord.Interaction, username: str | None = None) -> None:
        if interaction.user is None:
            return
        lang = self._get_lang(interaction)
        await interaction.response.defer(thinking=True)

        client = self.bot.client_for()
        query = (username or "").strip()

        try:
            # 1. Resolve user ID
            user_id: int | None = None
            if not query:
                linked = self.bot.linked_accounts.get_account(interaction.user.id)
                if not linked:
                    await interaction.followup.send(translate("link_first", lang), ephemeral=True)
                    return
                user_id = linked.rhythia_user_id
            else:
                results = await client.search(query=query, limit=5)
                users = results.get("users") or []
                if not users:
                    raise RhythiaAPIError(translate("not_found", lang, query=query))
                exact = next((u for u in users if (u.get("username") or "").lower() == query.lower()), None)
                if len(users) > 1 and exact is None:
                    raise RhythiaAPIError(translate("multiple_found", lang, query=query))
                user = exact or users[0]
                user_id = int(user["id"])

            # 2. Fetch full profile data
            profile_data = await client.get_profile(user_id=user_id)
            user_info = profile_data.get("user") or {}

            # 3. Retrieve avatar image bytes if present
            avatar_bytes: bytes | None = None
            avatar_url = user_info.get("avatar_url") or user_info.get("profile_image")
            if avatar_url:
                try:
                    async with self.bot._http_session.get(avatar_url, timeout=5) as resp:
                        if resp.status == 200:
                            avatar_bytes = await resp.read()
                except Exception as e:
                    logger.warning(f"Could not load avatar from {avatar_url}: {e}")

            # 3b. Retrieve flag image bytes if present
            flag_bytes: bytes | None = None
            country_code = user_info.get("flag")
            if country_code and len(country_code) == 2:
                flag_url = f"https://flagcdn.com/w80/{country_code.lower()}.png"
                try:
                    async with self.bot._http_session.get(flag_url, timeout=5) as resp:
                        if resp.status == 200:
                            flag_bytes = await resp.read()
                except Exception as e:
                    logger.warning(f"Could not load flag from {flag_url}: {e}")

            # 4. Generate the card image
            loop = self.bot.loop
            card_stream = await loop.run_in_executor(
                None, 
                generate_profile_card, 
                profile_data, 
                avatar_bytes,
                flag_bytes
            )

            # 5. Send file
            file = discord.File(card_stream, filename="card.png")
            await interaction.followup.send(file=file)

        except RhythiaAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            logger.exception("Unexpected error in /gerhythia card")
            await interaction.followup.send(translate("internal_error", lang), ephemeral=True)
