"""
Card Cog - Display Project Sekai card information.
"""
import discord
from discord.ext import commands
from discord import app_commands
import json
import logging

from config import CARDS_FILE, RARITY_ICONS, ASSETS_PATH
from utils.game_data import game_data, get_character_name, get_unit_color_hex

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
        self.card_data = []
        self.load_data()

    def load_data(self):
        try:
            with open(CARDS_FILE, 'r', encoding='utf-8') as f:
                self.card_data = json.load(f)
            logger.info(f"Card: Loaded {len(self.card_data)} cards.")
        except FileNotFoundError as e:
            logger.error(f"Card: Missing file: {e.filename}")
        except Exception as e:
            logger.error(f"Card: Failed to load data: {e}")

    @app_commands.command(name="card", description="Get Card Information")
    @app_commands.describe(card_name="Search for a card by name")
    async def card_command(self, interaction: discord.Interaction, card_name: str):
        await interaction.response.defer()

        selected_card = next((c for c in self.card_data if str(c['id']) == card_name), None)

        if not selected_card:
            await interaction.followup.send("Card not found.", ephemeral=True)
            return

        char_id = selected_card['characterId']
        char_info = game_data.get_character(char_id)

        if not char_info:
            await interaction.followup.send("Character data missing for this card.", ephemeral=True)
            return

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

        embed = discord.Embed(
            title=selected_card.get('prefix', 'No Prefix'),
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
        choices = []
        current_lower = current.lower()
        
        for card in self.card_data:
            if not card.get('prefix'): 
                continue
            
            char_id = card['characterId']
            char_name = get_character_name(char_id, full=True)

            rarity_str = "🎂" if 'birthday' in card['cardRarityType'] else f"{card['cardRarityType'][-1]}⭐"
            display_name = f"{rarity_str} // {card['prefix']} [{char_name}]"

            if current_lower in display_name.lower():
                choices.append(app_commands.Choice(name=display_name, value=str(card['id'])))
                if len(choices) >= 25: 
                    break
        
        return choices


async def setup(bot):
    await bot.add_cog(CardCog(bot))