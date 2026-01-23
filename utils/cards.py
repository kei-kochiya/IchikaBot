"""
Card utilities for Project Sekai Discord bot.
Shared helper functions for card image URLs and views.
"""
import discord
import random
from datetime import datetime


def get_card_image_url(asset_bundle: str, trained: bool = False) -> str:
    """Get card image URL (normal or trained)."""
    suffix = "card_after_training.png" if trained else "card_normal.png"
    return f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_bundle}/{suffix}"


def supports_trained_art(card: dict) -> bool:
    """Check if a card supports trained art (3-star or 4-star only)."""
    return card.get('cardRarityType') in ['rarity_3', 'rarity_4']


def get_random_card(cards: list, char_id: int, rarity: list[str] = None) -> dict | None:
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
            c for c in cards 
            if c['characterId'] == char_id_int and c['cardRarityType'] in rarity and c.get('prefix')
        ]
    else:
        matching_cards = [
            c for c in cards 
            if c['characterId'] == char_id_int and c.get('prefix')
        ]
    
    if not matching_cards:
        return None
    return random.choice(matching_cards)


class CardToggleView(discord.ui.View):
    """Reusable view with trained/untrained toggle for card images.
    
    Works with any embed that has a card image. Default shows trained art
    for 3/4 star cards, untrained for others.
    """
    
    def __init__(self, embed: discord.Embed, card: dict, default_trained: bool = True, timeout: int = 180):
        super().__init__(timeout=timeout)
        self.embed = embed
        self.card = card
        self.supports_trained = supports_trained_art(card)
        
        # Start with trained for 3/4 star, untrained otherwise
        self.is_trained = default_trained and self.supports_trained
        
        if self.supports_trained:
            self.toggle_btn = discord.ui.Button(
                label="Untrained" if self.is_trained else "Trained",
                style=discord.ButtonStyle.primary,
                custom_id="card_toggle"
            )
            self.toggle_btn.callback = self.toggle_callback
            self.add_item(self.toggle_btn)
    
    def get_current_image_url(self) -> str:
        """Get the current image URL based on trained state."""
        return get_card_image_url(self.card['assetbundleName'], self.is_trained)
    
    async def toggle_callback(self, interaction: discord.Interaction):
        self.is_trained = not self.is_trained
        self.toggle_btn.label = "Untrained" if self.is_trained else "Trained"
        
        # Update embed image
        self.embed.set_image(url=self.get_current_image_url())
        
        await interaction.response.edit_message(embed=self.embed, view=self)
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
