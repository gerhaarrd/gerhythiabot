from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ui

from rhythia.account_link import AccountLinkError, extract_access_token_from_paste, save_rhythia_link

if TYPE_CHECKING:
    from bot.discord_bot import RhythiaBot

PRIVACY_NOTICE = (
    "**Privacy & data**\n"
    "By linking, you allow this bot to store an encrypted **session token** for your "
    "Rhythia account (the same one used when you log in on the website) on the server "
    "where this bot runs.\n\n"
    "That token is used **only** to run bot commands on your behalf (profile, "
    "leaderboard, maps, etc.) and can be revoked anytime with `/gerhythia unlink`, which "
    "deletes the link and token here.\n\n"
    "The **bot operator** (server/VPS owner) has technical access to the bot files and "
    "**could** read that token while it remains valid — as with any community account-link "
    "bot. This project is **not official** Rhythia / Capo Games.\n\n"
    "Tokens are not shared with third parties by this code; hosting is the operator’s "
    "responsibility. If you disagree, **do not** use `/gerhythia link` — commands like "
    "`/gerhythia search` work without linking."
)


def link_instructions_embed() -> discord.Embed:
    description = (
        "**Step 1** — Click **Log in with Discord** (opens Rhythia's official login).\n\n"
        "**Step 2** — You will land on a page that **fails to load** — that is expected! "
        "It means the login worked.\n\n"
        "**Step 3** — Copy the **full address bar URL** (starts with `http://127.0.0.1` "
        "and contains `access_token`) and click **Paste session here** below.\n\n"
        "Use the **same Discord account** as on this server.\n\n"
        "_Ephemeral. Delete messages with your URL after linking._"
    )
    embed = discord.Embed(
        title="Link Rhythia account",
        description=description,
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="⚠️ Legal notice",
        value=PRIVACY_NOTICE,
        inline=False,
    )
    return embed


class SessionModal(ui.Modal, title="Complete Rhythia link"):
    session = ui.TextInput(
        label="URL or access_token",
        style=discord.TextStyle.paragraph,
        placeholder="https://www.rhythia.com/#access_token=eyJ...  (or paste eyJ... only)",
        required=True,
        max_length=4000,
    )

    def __init__(self, bot: RhythiaBot) -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user is None:
            return
        await interaction.response.defer(ephemeral=True)
        raw = self.session.value or ""
        try:
            access_token = extract_access_token_from_paste(raw)
            username = save_rhythia_link(
                self.bot,
                discord_id=interaction.user.id,
                access_token=access_token,
            )
        except AccountLinkError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f"**{username}** linked. Use `/gerhythia profile`.\n"
            "Delete this message — it contains sensitive data.",
            ephemeral=True,
        )


class LinkView(ui.View):
    def __init__(self, bot: RhythiaBot, login_url: str) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.add_item(
            ui.Button(
                label="1. Log in with Discord",
                style=discord.ButtonStyle.link,
                url=login_url,
                emoji="🔗",
            )
        )

    @ui.button(
        label="2. Paste session here",
        style=discord.ButtonStyle.primary,
        emoji="📋",
    )
    async def paste_session(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        await interaction.response.send_modal(SessionModal(self.bot))
