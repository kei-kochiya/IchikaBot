"""
Card Cog - Display Project Sekai card information.
Supports both JP and EN card data with English search.
"""
import discord
from discord.ext import commands
from discord import app_commands
import json
import logging

from config import CARDS_FILE_JP, CARDS_FILE_EN, RARITY_ICONS, ASSETS_PATH
from utils.data.game_data import game_data, get_character_name, get_unit_color_hex
from utils.data.card_data import card_data

logger = logging.getLogger(__name__)


class CardView(discord.ui.View):
    def __init__(self, card_data, char_data, base_image_url):
        super().__init__(timeout=120)
        self.card_data = card_data
        self.char_data = char_data
        self.base_image_url = base_image_url
        self.is_normal = True
        
        self.switch_button = discord.ui.Button(
            label='Trained',
            style=discord.ButtonStyle.primary,
            custom_id=f"switch_{card_data['id']}_type"
        )
        
        if card_data['cardRarityType'] in ['rarity_birthday', 'rarity_1']:
            self.switch_button.disabled = True
            self.switch_button.label = "No Trained Art"
            self.switch_button.style = discord.ButtonStyle.secondary
        
        self.switch_button.callback = self.switch_callback
        self.add_item(self.switch_button)

    async def switch_callback(self, interaction: discord.Interaction):
        self.is_normal = not self.is_normal
        self.switch_button.label = "Trained" if self.is_normal else "Normal"
        self.switch_button.style = discord.ButtonStyle.primary if self.is_normal else discord.ButtonStyle.secondary
        
        suffix = 'card_normal.png' if self.is_normal else 'card_after_training.png'
        new_image_url = f"{self.base_image_url}/{suffix}"
        
        embed = interaction.message.embeds[0]
        embed.set_image(url=new_image_url)
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class CardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def load_data(self):
        """Card data is managed by utils.card_data singleton — nothing to do here."""
        pass

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
            # Search EN prefixes first
            for cid, prefix in card_data.en_prefix.items():
                if name_lower in prefix.lower():
                    selected_card = card_data.get_by_id(cid)
                    break
            # Fall back to JP
            if not selected_card:
                for card in card_data.cards:
                    if card.get('prefix') and name_lower in card['prefix'].lower():
                        selected_card = card
                        break

        if not selected_card:
            await interaction.followup.send("Card not found.", ephemeral=True)
            return

        card_id = selected_card['id']

        char_id = selected_card['characterId']
        char_info = game_data.get_character(char_id)

        if not char_info:
            await interaction.followup.send("Character data missing for this card.", ephemeral=True)
            return

        # Asset URLs always use JP storage
        base_url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{selected_card['assetbundleName']}"
        image_url = f"{base_url}/card_normal.png"

        unit_img_path = ASSETS_PATH / 'common' / 'logo_mini' / f"{char_info.get('unit', 'unknown')}.png"
        
        clean_name = char_info.get('givenName', '').lower().replace(' ', '')
        icon_img_path = ASSETS_PATH / 'chara_icons' / f"{clean_name}.png"

        files_to_send = []
        
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
            color=discord.Color.from_str(color_hex)
        )
        
        embed.set_author(name=get_character_name(char_id, full=True), icon_url=author_icon_url)
        embed.set_image(url=image_url)
        embed.set_footer(text=char_info.get('fullUnit', 'Unknown Unit'), icon_url=footer_icon_url)
        embed.timestamp = interaction.created_at

        view = CardView(selected_card, char_info, base_url)
        msg = await interaction.followup.send(embed=embed, files=files_to_send, view=view)
        view.message = msg

    @card_command.autocomplete('card_name')
    async def card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete that searches both EN and JP card names."""
        choices = []
        current_lower = current.lower()
        seen_ids: set[int] = set()

        # 1. EN-named cards first
        for card_id, en_pfx in card_data.en_prefix.items():
            if card_id in seen_ids:
                continue
            card = card_data.get_by_id(card_id)
            if not card:
                continue
            char_id = card['characterId']
            char_name = get_character_name(char_id, full=True)
            rarity_str = "🎂" if 'birthday' in card['cardRarityType'] else f"{card['cardRarityType'][-1]}⭐"
            display_name = f"{rarity_str} // {en_pfx} [{char_name}]"
            if current_lower in display_name.lower():
                choices.append(app_commands.Choice(name=display_name[:100], value=str(card_id)))
                seen_ids.add(card_id)
                if len(choices) >= 25:
                    return choices

        # 2. JP-only cards (no EN prefix)
        if len(choices) < 25:
            for card in card_data.cards:
                if not card.get('prefix'):
                    continue
                card_id = card['id']
                if card_id in seen_ids:
                    continue
                char_id = card['characterId']
                char_name = get_character_name(char_id, full=True)
                rarity_str = "🎂" if 'birthday' in card['cardRarityType'] else f"{card['cardRarityType'][-1]}⭐"
                display_name = f"{rarity_str} // {card['prefix']} [{char_name}]"
                if current_lower in display_name.lower() or current_lower in card['prefix'].lower():
                    choices.append(app_commands.Choice(name=display_name[:100], value=str(card_id)))
                    seen_ids.add(card_id)
                    if len(choices) >= 25:
                        break

        return choices


async def setup(bot):
    await bot.add_cog(CardCog(bot))