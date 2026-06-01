"""Navigation buttons for paginated Discord embeds."""

from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

import discord
from discord import ui

from rhythia.api_client import RhythiaClient
from rhythia.api_errors import RhythiaAPIError

if TYPE_CHECKING:
    pass


class EmbedNavigatorView(ui.View):
    """View for navigating paginated embeds with arrow buttons."""

    def __init__(
        self,
        interaction: discord.Interaction,
        *,
        fetch: Callable[[RhythiaClient, int], dict[str, Any]],
        build: Callable[[dict[str, Any]], discord.Embed],
        initial_data: dict[str, Any],
        initial_page: int = 1,
        max_pages: int | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.interaction = interaction
        self.fetch = fetch
        self.build = build
        self.current_page = initial_page
        self.max_pages = max_pages
        self.current_data = initial_data
        self._update_buttons()

    def _update_buttons(self) -> None:
        """Enable/disable navigation buttons based on current page."""
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = (
            self.max_pages is not None and self.current_page >= self.max_pages
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

        if self.current_page > 1:
            self.current_page -= 1
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

        if self.max_pages is None or self.current_page < self.max_pages:
            self.current_page += 1
            await self._update_embed(interaction)

    async def _update_embed(self, interaction: discord.Interaction) -> None:
        """Fetch new page and update the embed."""
        # Import here to avoid circular imports
        from bot.discord_bot import RhythiaBot

        if interaction.user is None:
            return

        # Get the bot from the interaction's client
        bot = interaction.client
        if not isinstance(bot, RhythiaBot):
            await interaction.response.send_message(
                "Internal error: bot not found.",
                ephemeral=True,
            )
            return

        client = bot.client_for()

        try:
            with client:
                # Pass current_page to the fetch function
                self.current_data = self.fetch(client, self.current_page)

            # Update max_pages if available from the data
            if "total" in self.current_data and "viewPerPage" in self.current_data:
                total = self.current_data["total"]
                per_page = self.current_data["viewPerPage"]
                self.max_pages = (total + per_page - 1) // per_page

            embed = self.build(self.current_data)
            self._update_buttons()
            await interaction.response.edit_message(embed=embed, view=self)
        except RhythiaAPIError as exc:
            await interaction.response.send_message(
                f"Error: {exc}",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.response.send_message(
                f"Internal error: {exc}",
                ephemeral=True,
            )
