from __future__ import annotations

from typing import Any, TYPE_CHECKING

import discord
from discord import ui

from rhythia.account_link import AccountLinkError, create_pending_rhythia_link
from rhythia.discord_embeds import flag_emoji, user_url

if TYPE_CHECKING:
    from bot.discord_bot import RhythiaBot


def link_confirmation_embed(user: dict[str, Any]) -> discord.Embed:
    username = user.get("username") or user.get("computedUsername") or "Unknown"
    user_id = user.get("id")
    flag = flag_emoji(user.get("flag"))
    embed = discord.Embed(
        title=f"Verify {flag} {username}?",
        description=(
            "To prove this profile is yours, confirm below and I will generate a code "
            "for you to place in your Rhythia about me."
        ),
        url=user_url(user_id) if user_id else None,
        color=discord.Color.blurple(),
    )
    avatar = user.get("avatar_url") or user.get("profile_image")
    if avatar:
        embed.set_thumbnail(url=avatar)
    embed.add_field(name="Rhythia ID", value=f"`{user_id}`", inline=True)
    embed.add_field(name="Username", value=f"**{username}**", inline=True)
    embed.set_footer(text="No access token or private session is stored.")
    return embed


class PublicLinkConfirmView(ui.View):
    def __init__(self, bot: RhythiaBot, discord_id: int, user: dict[str, Any]) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.discord_id = discord_id
        self.user = user

    @ui.button(label="Confirm link", style=discord.ButtonStyle.primary)
    async def confirm(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        if interaction.user is None or interaction.user.id != self.discord_id:
            await interaction.response.send_message(
                "Only the user who started this link can confirm it.",
                ephemeral=True,
            )
            return

        try:
            pending = create_pending_rhythia_link(
                self.bot,
                discord_id=interaction.user.id,
                user=self.user,
            )
        except AccountLinkError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=(
                f"Verification started for **{pending.rhythia_username}**.\n\n"
                "Add this code to your Rhythia **about me**:\n"
                f"`{pending.code}`\n\n"
                "Then run `/gerhythia verify`. This code expires in 15 minutes."
            ),
            embed=None,
            view=self,
        )

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        if interaction.user is None or interaction.user.id != self.discord_id:
            await interaction.response.send_message(
                "Only the user who started this link can cancel it.",
                ephemeral=True,
            )
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Link cancelled.",
            embed=None,
            view=self,
        )
