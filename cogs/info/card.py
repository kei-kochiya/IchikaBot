"""
Card Cog - Display Project Sekai card information.
Supports both JP and EN card data with English search.
"""

import asyncio
import contextlib
import logging
from itertools import islice

import discord
from discord import app_commands
from discord.ext import commands

from config import ASSETS_PATH, RARITY_ICONS
from utils.data.card_data import card_data
from utils.data.game_data import game_data, get_character_name, get_unit_color_hex
from utils.game.cards import (
    is_pre_trained_card,
    supports_trained_art,
    update_card_attachment_message,
)
from utils.media.image_helper import get_card_image_path

logger = logging.getLogger(__name__)


class CardView(discord.ui.View):
    def __init__(self, card_data, char_data, base_image_url):
        toggleable = supports_trained_art(card_data)
        super().__init__(timeout=120 if toggleable else None)
        self.card_data = card_data
        self.base_image_url = base_image_url
        self._lock = asyncio.Lock()
        is_pre_trained = is_pre_trained_card(card_data)
        self.is_normal = not is_pre_trained

        self.switch_button = discord.ui.Button(
            label="Trained" if self.is_normal else "Normal",
            style=discord.ButtonStyle.primary if self.is_normal else discord.ButtonStyle.secondary,
            custom_id=f"switch_{card_data['id']}_type",
        )

        if not toggleable:
            self.switch_button.disabled = True
            self.switch_button.label = "Trained Only" if is_pre_trained else "No Trained Art"
            self.switch_button.style = discord.ButtonStyle.secondary

        self.switch_button.callback = self.switch_callback
        self.add_item(self.switch_button)
        if not toggleable:
            self.stop()

    async def switch_callback(self, interaction: discord.Interaction):
        embed = (
            interaction.message.embeds[0]
            if interaction.message and interaction.message.embeds
            else None
        )
        if not embed:
            if not interaction.response.is_done():
                with contextlib.suppress(discord.HTTPException):
                    await interaction.response.defer()
            return

        if not interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.defer()

        async with self._lock:
            self.is_normal = not self.is_normal
            self.switch_button.label = "Trained" if self.is_normal else "Normal"
            self.switch_button.style = (
                discord.ButtonStyle.primary if self.is_normal else discord.ButtonStyle.secondary
            )

            suffix = "card_normal.png" if self.is_normal else "card_after_training.png"

            def build_embed(url: str) -> discord.Embed:
                embed.set_image(url=url)
                return embed

            ok = await update_card_attachment_message(
                interaction=interaction,
                fetch_image=get_card_image_path,
                asset_bundle=self.card_data["assetbundleName"],
                is_trained=not self.is_normal,
                build_embed=build_embed,
                fallback_url=f"{self.base_image_url}/{suffix}",
                view=self,
            )
            if not ok:
                self.is_normal = not self.is_normal
                self.switch_button.label = "Trained" if self.is_normal else "Normal"
                self.switch_button.style = (
                    discord.ButtonStyle.primary if self.is_normal else discord.ButtonStyle.secondary
                )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, "message") and self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


class CardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._autocomplete_index: list[tuple[str, str, str]] = []
        self._build_autocomplete_index()

    def load_data(self):
        """Rebuild the autocomplete index when card data reloads."""
        self._build_autocomplete_index()

    def _build_autocomplete_index(self) -> None:
        """Precompute (search_lower, choice_label, card_id_str) with EN-named cards first."""
        index: list[tuple[str, str, str]] = []
        seen_ids: set[int] = set()

        def format_entry(card: dict, prefix: str) -> tuple[str, str, str]:
            char_name = get_character_name(card["characterId"], full=True)
            rarity = card["cardRarityType"]
            rarity_str = "Birthday" if "birthday" in rarity else f"{rarity[-1]}★"
            full_label = f"{rarity_str} // {prefix} [{char_name}]"
            display = full_label[:100]
            jp_prefix = card.get("prefix") or ""
            hay = (
                f"{full_label}\x00{jp_prefix}" if jp_prefix and jp_prefix != prefix else full_label
            )
            return (hay.lower(), display, str(card["id"]))

        for card_id, en_pfx in card_data.en_prefix.items():
            if card_id in seen_ids:
                continue
            card = card_data.get_by_id(card_id)
            if not card:
                continue
            seen_ids.add(card_id)
            index.append(format_entry(card, en_pfx))

        for card in card_data.cards:
            prefix = card.get("prefix")
            card_id = card["id"]
            if not prefix or card_id in seen_ids:
                continue
            seen_ids.add(card_id)
            index.append(format_entry(card, prefix))

        self._autocomplete_index = index

    def get_card_by_id(self, card_id: int) -> dict | None:
        """O(1) lookup via shared singleton."""
        return card_data.get_by_id(card_id)

    def get_display_name(self, card: dict, card_id: int) -> str:
        """Return EN prefix if available, otherwise JP prefix."""
        return card_data.get_display_prefix(card)

    @app_commands.command(name="card", description="Get Card Information")
    @app_commands.describe(card_name="Search for a card by name (JP/EN)")
    async def card_command(self, interaction: discord.Interaction, card_name: str):
        await interaction.response.defer()

        selected_card = None
        try:
            card_id = int(card_name)
            selected_card = card_data.get_by_id(card_id)
        except ValueError:
            name_lower = card_name.lower()
            # Search EN prefixes first (skip EN-only IDs missing from JP cards)
            for cid, prefix in card_data.en_prefix.items():
                if name_lower in prefix.lower():
                    candidate = card_data.get_by_id(cid)
                    if candidate is not None:
                        selected_card = candidate
                        break
            # Fall back to JP
            if not selected_card:
                for card in card_data.cards:
                    if card.get("prefix") and name_lower in card["prefix"].lower():
                        selected_card = card
                        break

        if not selected_card:
            await interaction.followup.send(
                "Không tìm thấy card. Thử gõ một phần tên card hoặc chọn từ gợi ý.", ephemeral=True
            )
            return

        card_id = selected_card["id"]

        char_id = selected_card["characterId"]
        char_info = game_data.get_character(char_id)

        if not char_info:
            await interaction.followup.send("Thiếu dữ liệu nhân vật của card này.", ephemeral=True)
            return

        # Asset URLs always use JP storage
        base_url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{selected_card['assetbundleName']}"

        unit_img_path = (
            ASSETS_PATH / "common" / "logo_mini" / f"{char_info.get('unit', 'unknown')}.png"
        )

        clean_name = (
            (char_info.get("givenName") or char_info.get("firstName") or "")
            .lower()
            .replace(" ", "")
        )
        icon_img_path = ASSETS_PATH / "chara_icons" / f"{clean_name}.png"

        files_to_send = []

        is_pre_trained = is_pre_trained_card(selected_card)
        initial_trained = is_pre_trained

        # Check cache / download card image
        card_img_path = await get_card_image_path(
            selected_card["assetbundleName"], is_trained=initial_trained
        )
        if card_img_path:
            files_to_send.append(discord.File(card_img_path, filename="card.webp"))
            image_url = "attachment://card.webp"
        else:
            suffix = "card_after_training.png" if initial_trained else "card_normal.png"
            image_url = f"{base_url}/{suffix}"

        author_icon_url = None
        if icon_img_path.exists():
            files_to_send.append(discord.File(str(icon_img_path), filename="icon.png"))
            author_icon_url = "attachment://icon.png"

        footer_icon_url = None
        if unit_img_path.exists():
            files_to_send.append(discord.File(str(unit_img_path), filename="unit.png"))
            footer_icon_url = "attachment://unit.png"

        color_hex = get_unit_color_hex(char_id)

        # Use EN name if available
        display_title = self.get_display_name(selected_card, card_id)

        embed = discord.Embed(
            title=display_title,
            description=f"**Rarity:** {RARITY_ICONS.get(selected_card['cardRarityType'], selected_card['cardRarityType'])}",
            color=discord.Color.from_str(color_hex),
        )

        embed.set_author(name=get_character_name(char_id, full=True), icon_url=author_icon_url)
        embed.set_image(url=image_url)
        embed.set_footer(text=char_info.get("fullUnit", "Unknown Unit"), icon_url=footer_icon_url)
        embed.timestamp = interaction.created_at

        view = CardView(selected_card, char_info, base_url)
        msg = await interaction.followup.send(embed=embed, files=files_to_send, view=view)
        view.message = msg

    @card_command.autocomplete("card_name")
    async def card_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete that searches both EN and JP card names."""
        current_lower = current.lower()
        return list(
            islice(
                (
                    app_commands.Choice(name=label, value=cid)
                    for hay, label, cid in self._autocomplete_index
                    if current_lower in hay
                ),
                25,
            )
        )


async def setup(bot):
    await bot.add_cog(CardCog(bot))
