"""
Card utilities for Project Sekai Discord bot.
Shared helper functions for card image URLs and views.
"""

import asyncio
import contextlib
import random

import discord


def get_card_image_url(asset_bundle: str, trained: bool = False) -> str:
    """Get card image URL (normal or trained)."""
    suffix = "card_after_training.png" if trained else "card_normal.png"
    return f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_bundle}/{suffix}"


def is_pre_trained_card(card: dict) -> bool:
    """Check if a card is pre-trained (only has trained art, no normal art)."""
    return isinstance(card, dict) and card.get("initialSpecialTrainingStatus") == "done"


def supports_trained_art(card: dict) -> bool:
    """Check if a card supports toggleable trained art (has both normal and trained versions)."""
    if not isinstance(card, dict):
        return False
    if is_pre_trained_card(card):
        return False
    return card.get("cardRarityType") in ["rarity_3", "rarity_4"]


def get_random_card(cards: list, char_id: int, rarity: list[str] | None = None) -> dict | None:
    """Get a random card for a character from a list of cards.

    Args:
        cards: List of all card dictionaries
        char_id: Character ID to filter by
        rarity: List of rarity types to include (default: all with prefix)

    Returns:
        Random matching card or None if not found
    """
    char_id_int = int(char_id) if isinstance(char_id, str) else char_id

    if rarity:
        matching_cards = [
            c
            for c in cards
            if c["characterId"] == char_id_int and c["cardRarityType"] in rarity and c.get("prefix")
        ]
    else:
        matching_cards = [c for c in cards if c["characterId"] == char_id_int and c.get("prefix")]

    if not matching_cards:
        return None
    return random.choice(matching_cards)


async def update_card_attachment_message(
    interaction: discord.Interaction,
    fetch_image,
    asset_bundle: str,
    is_trained: bool,
    build_embed,
    fallback_url: str,
    view: discord.ui.View,
) -> bool:
    """Defer a button interaction, fetch/attach card art, and edit the message.

    Returns True if the edit succeeded, False if a Discord HTTP error occurred.
    """
    if not interaction.response.is_done():
        with contextlib.suppress(discord.HTTPException):
            await interaction.response.defer()

    img_path = await fetch_image(asset_bundle, is_trained=is_trained)
    keep_attachments = [
        att
        for att in (interaction.message.attachments if interaction.message else [])
        if att.filename not in ("card.png", "card.webp")
    ]

    try:
        if img_path:
            file = discord.File(img_path, filename="card.webp")
            embed = build_embed("attachment://card.webp")
            target_attachments = [*keep_attachments, file]
        else:
            embed = build_embed(fallback_url)
            target_attachments = keep_attachments

        if interaction.response.is_done():
            await interaction.edit_original_response(
                embed=embed, attachments=target_attachments, view=view
            )
        else:
            await interaction.response.edit_message(
                embed=embed, attachments=target_attachments, view=view
            )
        return True
    except discord.HTTPException:
        return False


class CardToggleView(discord.ui.View):
    """Reusable view with trained/untrained toggle for card images.

    Works with any embed that has a card image. Default shows trained art
    for 3/4 star cards, untrained for others.
    """

    def __init__(
        self, embed: discord.Embed, card: dict, default_trained: bool = True, timeout: int = 180
    ):
        self.is_pre_trained = is_pre_trained_card(card)
        self.supports_trained = supports_trained_art(card)
        super().__init__(timeout=timeout if self.supports_trained else None)
        self.embed = embed
        self.card = card
        self.message = None  # Set by caller after sending: view.message = msg
        self._lock = asyncio.Lock()

        # Start with trained for pre-trained cards, or if default_trained requested on toggleable cards
        self.is_trained = (default_trained and self.supports_trained) or self.is_pre_trained

        if self.supports_trained:
            self.toggle_btn = discord.ui.Button(
                label="Untrained" if self.is_trained else "Trained",
                style=discord.ButtonStyle.primary,
                custom_id="card_toggle",
            )
            self.toggle_btn.callback = self.toggle_callback
            self.add_item(self.toggle_btn)
        else:
            self.stop()

    def get_current_image_url(self) -> str:
        """Get the current image URL based on trained state."""
        return get_card_image_url(self.card["assetbundleName"], self.is_trained)

    async def toggle_callback(self, interaction: discord.Interaction):
        from utils.media.image_helper import get_card_image_path

        if not interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.defer()

        async with self._lock:
            self.is_trained = not self.is_trained
            self.toggle_btn.label = "Untrained" if self.is_trained else "Trained"

            embed = (
                interaction.message.embeds[0]
                if interaction.message and interaction.message.embeds
                else self.embed
            )

            def build_embed(url: str) -> discord.Embed:
                embed.set_image(url=url)
                return embed

            ok = await update_card_attachment_message(
                interaction=interaction,
                fetch_image=get_card_image_path,
                asset_bundle=self.card["assetbundleName"],
                is_trained=self.is_trained,
                build_embed=build_embed,
                fallback_url=self.get_current_image_url(),
                view=self,
            )
            if not ok:
                self.is_trained = not self.is_trained
                self.toggle_btn.label = "Untrained" if self.is_trained else "Trained"

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, "message") and self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)
