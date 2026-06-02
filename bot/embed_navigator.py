"""Navigation buttons for paginated Discord embeds."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

import discord
from discord import ui

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError

if TYPE_CHECKING:
    pass

# The Rhythia API always returns 50 items per page
API_PAGE_SIZE = 50


class EmbedNavigatorView(ui.View):
    """View for navigating paginated embeds with arrow buttons."""

    def __init__(
        self,
        interaction: discord.Interaction,
        *,
        fetch: Callable[[RhythiaClient, int], Awaitable[dict[str, Any]]],
        build: Callable[[dict[str, Any], int], discord.Embed],
        initial_data: dict[str, Any],
        initial_user_page: int = 1,
        max_pages: int | None = None,
        page_size: int | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.interaction = interaction
        self.fetch = fetch
        self.build = build
        self.current_user_page = initial_user_page
        self.max_pages = max_pages
        self.page_size = page_size or API_PAGE_SIZE
        self.current_data = initial_data
        self._update_buttons()

    def _user_page_to_api_page(self, user_page: int) -> int:
        """Convert user-facing page number to API page number.

        The API always returns 50 items per page, but the user sees
        `page_size` items per page. So multiple user pages map to one API page.
        """
        first_item_index = (user_page - 1) * self.page_size
        return (first_item_index // API_PAGE_SIZE) + 1

    def _update_buttons(self) -> None:
        """Enable/disable navigation buttons based on current page."""
        self.prev_button.disabled = self.current_user_page <= 1
        self.next_button.disabled = (
            self.max_pages is not None and self.current_user_page >= self.max_pages
        )

    @ui.button(label="◀ Previous", style=discord.ButtonStyle.gray)
    async def prev_button(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        if interaction.user is None or interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "Only the user who started this can navigate.",
                ephemeral=True,
            )
            return

        if self.current_user_page > 1:
            self.current_user_page -= 1
            await self._update_embed(interaction)

    @ui.button(label="Next ▶", style=discord.ButtonStyle.gray)
    async def next_button(
        self, interaction: discord.Interaction, button: ui.Button
    ) -> None:
        if interaction.user is None or interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "Only the user who started this can navigate.",
                ephemeral=True,
            )
            return

        if self.max_pages is None or self.current_user_page < self.max_pages:
            self.current_user_page += 1
            await self._update_embed(interaction)

    async def _update_embed(self, interaction: discord.Interaction) -> None:
        """Fetch new page and update the embed."""
        from bot.discord_bot import RhythiaBot

        if interaction.user is None:
            return

        # Defer first so the interaction doesn't expire (API call may take >3s)
        try:
            await interaction.response.defer()
        except discord.NotFound:
            logging.getLogger(__name__).warning(
                "Cannot defer update: interaction not found (user_id=%s)",
                interaction.user.id,
            )
            return

        # Get the bot from the interaction's client
        bot = interaction.client
        if not isinstance(bot, RhythiaBot):
            try:
                await interaction.followup.send(
                    "Internal error: bot not found.",
                    ephemeral=True,
                )
            except discord.NotFound:
                pass
            return

        client = bot.client_for()

        try:
            # Convert user page number to API page number
            api_page = self._user_page_to_api_page(self.current_user_page)
            self.current_data = await self.fetch(client, api_page)

            # Update max_pages if available from the data
            if "total" in self.current_data:
                total = self.current_data["total"]
                self.max_pages = (total + self.page_size - 1) // self.page_size

            embed = self.build(self.current_data, self.current_user_page)
            self._update_buttons()
            await interaction.edit_original_response(embed=embed, view=self)
        except discord.NotFound:
            logging.getLogger(__name__).warning(
                "Cannot update embed: interaction not found (user_id=%s)",
                interaction.user.id,
            )
        except RhythiaAPIError as exc:
            try:
                await interaction.followup.send(
                    f"Error: {exc}",
                    ephemeral=True,
                )
            except discord.NotFound:
                pass
        except Exception:
            logging.getLogger(__name__).exception(
                "Error updating embed (user_id=%s)", interaction.user.id
            )
            try:
                await interaction.followup.send(
                    "Internal error.",
                    ephemeral=True,
                )
            except discord.NotFound:
                pass