from __future__ import annotations

from typing import Any, TYPE_CHECKING

import discord
from discord import ui

from rhythia.account_link import AccountLinkError, create_pending_rhythia_link
from rhythia.discord_embeds import flag_emoji, user_url

if TYPE_CHECKING:
    from bot.discord_bot import RhythiaBot


from utils.i18n import translate


def link_confirmation_embed(user: dict[str, Any], lang: str = "en") -> discord.Embed:
    username = user.get("username") or user.get("computedUsername") or "Unknown"
    user_id = user.get("id")
    flag = flag_emoji(user.get("flag"))
    embed = discord.Embed(
        title=translate("link_confirm_title", lang, flag=flag, username=username),
        description=translate("link_confirm_desc", lang),
        url=user_url(user_id) if user_id else None,
        color=discord.Color.blurple(),
    )
    avatar = user.get("avatar_url") or user.get("profile_image")
    if avatar:
        embed.set_thumbnail(url=avatar)
    embed.add_field(name="Rhythia ID", value=f"`{user_id}`", inline=True)
    embed.add_field(name="Username", value=f"**{username}**", inline=True)
    embed.set_footer(text=translate("link_confirm_footer", lang))
    return embed


class PublicLinkConfirmView(ui.View):
    def __init__(self, bot: RhythiaBot, discord_id: int, user: dict[str, Any], lang: str = "en") -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.discord_id = discord_id
        self.user = user
        self.lang = lang
        self.confirm.label = translate("btn_confirm", lang)
        self.cancel.label = translate("btn_cancel", lang)

    @ui.button(label="Confirm link", style=discord.ButtonStyle.primary)
    async def confirm(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        if interaction.user is None or interaction.user.id != self.discord_id:
            await interaction.response.send_message(
                translate("err_only_initiator_confirm", self.lang),
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
            content=translate(
                "verification_started",
                self.lang,
                username=pending.rhythia_username,
                code=pending.code,
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
                translate("err_only_initiator_cancel", self.lang),
                ephemeral=True,
            )
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=translate("link_cancelled", self.lang),
            embed=None,
            view=self,
        )
