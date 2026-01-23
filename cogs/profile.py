"""
Character Profile Cog - Detailed character information from Project Sekai.
"""
import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import aiofiles
import random

from config import PROFILES_FILE, CARDS_FILE
from utils.game_data import (
    game_data, get_character_name, get_unit_color, character_autocomplete
)
from utils.cards import get_card_image_url, get_random_card, CardToggleView

logger = logging.getLogger(__name__)



class ProfileCog(commands.Cog):
    """Cog for displaying detailed character profiles."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.profiles = {}
        self.cards = []
        
    async def cog_load(self):
        await self.load_data()
        logger.info("ProfileCog loaded with %d profiles, %d cards", len(self.profiles), len(self.cards))
    
    async def load_data(self):
        try:
            async with aiofiles.open(PROFILES_FILE, 'r', encoding='utf-8') as f:
                profiles = json.loads(await f.read())
                self.profiles = {p['characterId']: p for p in profiles}
            
            async with aiofiles.open(CARDS_FILE, 'r', encoding='utf-8') as f:
                self.cards = json.loads(await f.read())
        except Exception as e:
            logger.error("Failed to load profile data: %s", e)
    
    def get_random_card_for_character(self, char_id: int, rarity: list[str] = None) -> dict | None:
        """Get a random 3-star or 4-star card for a character."""
        if rarity is None:
            rarity = ['rarity_3', 'rarity_4']
        return get_random_card(self.cards, char_id, rarity)
    
    def get_birthday_card_for_character(self, char_id: int) -> dict | None:
        """Get a birthday card for a character."""
        return get_random_card(self.cards, char_id, ['rarity_birthday'])
    
    def create_profile_embed(self, char_id: int, card: dict = None) -> discord.Embed | None:
        profile = self.profiles.get(char_id)
        if not profile:
            return None
        
        name = get_character_name(char_id, full=True)
        
        embed = discord.Embed(
            title=f"📋 {name}",
            description=profile.get('introduction', ''),
            color=get_unit_color(char_id)
        )
        
        embed.add_field(name="Seiyuu", value=profile.get('characterVoice', 'N/A'), inline=True)
        embed.add_field(name="Sinh nhật", value=profile.get('birthday', 'N/A'), inline=True)
        embed.add_field(name="Chiều cao", value=profile.get('height', 'N/A'), inline=True)
        embed.add_field(name="Trường", value=profile.get('school', 'N/A'), inline=True)
        embed.add_field(name="Lớp", value=profile.get('schoolYear', 'N/A'), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        if profile.get('hobby'):
            embed.add_field(name="Sở thích", value=profile['hobby'].replace('\\n', ' '), inline=False)
        if profile.get('specialSkill'):
            embed.add_field(name="Kỹ năng", value=profile['specialSkill'], inline=True)
        if profile.get('weak'):
            embed.add_field(name="Điểm yếu", value=profile['weak'], inline=True)
        if profile.get('favoriteFood'):
            embed.add_field(name="Món ăn yêu thích", value=profile['favoriteFood'], inline=True)
        if profile.get('hatedFood'):
            embed.add_field(name="Món ăn không thích", value=profile['hatedFood'], inline=True)
        
        # Set card image
        if card:
            embed.set_image(url=get_card_image_url(card['assetbundleName'], False))
            rarity = "🎂" if card['cardRarityType'] == 'rarity_birthday' else f"{card['cardRarityType'][-1]}⭐"
            embed.set_footer(text=f"Card: {card.get('prefix', 'Unknown')} ({rarity})")
        
        return embed
    
    # --- Autocomplete ---
    async def char_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return character_autocomplete(current, max_id=26)
    
    # ===== SLASH COMMANDS =====
    profile_group = app_commands.Group(name="profile", description="Thông tin chi tiết nhân vật")
    
    @profile_group.command(name="info", description="Xem thông tin đầy đủ của một nhân vật")
    @app_commands.describe(character="Chọn nhân vật")
    @app_commands.autocomplete(character=char_autocomplete)
    async def profile_info(self, interaction: discord.Interaction, character: str):
        await interaction.response.defer()
        
        try:
            char_id = int(character)
        except ValueError:
            char_id, _ = game_data.get_character_by_name(character)
            if char_id is None:
                await interaction.followup.send(f"Không tìm thấy nhân vật: **{character}**")
                return
        
        card = self.get_random_card_for_character(char_id)
        embed = self.create_profile_embed(char_id, card)
        
        if embed is None:
            await interaction.followup.send("Không có thông tin profile cho nhân vật này.")
            return
        
        if card:
            view = CardToggleView(embed, card)
            msg = await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed)
    
    @profile_group.command(name="voice", description="Xem thông tin seiyuu của nhân vật")
    @app_commands.describe(character="Chọn nhân vật")
    @app_commands.autocomplete(character=char_autocomplete)
    async def profile_voice(self, interaction: discord.Interaction, character: str):
        await interaction.response.defer()
        
        try:
            char_id = int(character)
        except ValueError:
            char_id, _ = game_data.get_character_by_name(character)
            if char_id is None:
                await interaction.followup.send(f"Không tìm thấy nhân vật: **{character}**")
                return
        
        profile = self.profiles.get(char_id)
        if not profile:
            await interaction.followup.send("Không có thông tin profile.")
            return
        
        name = get_character_name(char_id, full=True)
        seiyuu = profile.get('characterVoice', 'N/A')
        
        embed = discord.Embed(
            title=f"🎤 Seiyuu của {name}",
            description=f"**{seiyuu}**",
            color=get_unit_color(char_id)
        )
        
        card = self.get_random_card_for_character(char_id)
        if card:
            embed.set_image(url=get_card_image_url(card['assetbundleName'], False))
            view = CardToggleView(embed, card)
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed)
    
    @profile_group.command(name="random_fact", description="Một sự thật ngẫu nhiên về nhân vật")
    async def profile_random_fact(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        main_chars = [cid for cid in self.profiles.keys() if cid <= 26]
        if not main_chars:
            await interaction.followup.send("Không có dữ liệu profile!")
            return
        
        char_id = random.choice(main_chars)
        profile = self.profiles[char_id]
        name = get_character_name(char_id, full=True)
        
        facts = []
        if profile.get('hobby'):
            facts.append(("Sở thích", profile['hobby'].replace('\\n', ' ')))
        if profile.get('specialSkill'):
            facts.append(("Kỹ năng đặc biệt", profile['specialSkill']))
        if profile.get('weak'):
            facts.append(("Điểm yếu", profile['weak']))
        if profile.get('favoriteFood'):
            facts.append(("Món ăn yêu thích", profile['favoriteFood']))
        if profile.get('hatedFood'):
            facts.append(("Món ăn không thích", profile['hatedFood']))
        
        if not facts:
            await interaction.followup.send("Không có thông tin thú vị!")
            return
        
        category, fact = random.choice(facts)
        
        embed = discord.Embed(
            title=f"🎲 Bạn có biết về {name}?",
            color=get_unit_color(char_id)
        )
        embed.add_field(name=category, value=fact, inline=False)
        
        card = self.get_random_card_for_character(char_id)
        if card:
            embed.set_image(url=get_card_image_url(card['assetbundleName'], False))
            view = CardToggleView(embed, card)
            embed.set_footer(text="Dùng /profile random_fact để xem thêm!")
            await interaction.followup.send(embed=embed, view=view)
        else:
            embed.set_footer(text="Dùng /profile random_fact để xem thêm!")
            await interaction.followup.send(embed=embed)
    
    # ===== PREFIX COMMANDS =====
    @commands.command(name='profile', aliases=['char', 'character'])
    async def profile_prefix(self, ctx: commands.Context, *, name: str = None):
        """Get character profile: !profile <name>"""
        if not name:
            await ctx.send("Vui lòng nhập tên nhân vật: `!profile <name>`")
            return
        
        char_id, _ = game_data.get_character_by_name(name)
        if char_id is None:
            await ctx.send(f"Không tìm thấy nhân vật: **{name}**")
            return
        
        card = self.get_random_card_for_character(char_id)
        embed = self.create_profile_embed(char_id, card)
        
        if embed is None:
            await ctx.send("Không có thông tin profile cho nhân vật này.")
            return
        
        if card:
            view = CardToggleView(embed, card)
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(embed=embed)
    
    @commands.command(name='voice', aliases=['seiyuu', 'va'])
    async def voice_prefix(self, ctx: commands.Context, *, name: str = None):
        """Get voice actor info: !voice <name>"""
        if not name:
            await ctx.send("Vui lòng nhập tên nhân vật: `!voice <name>`")
            return
        
        char_id, _ = game_data.get_character_by_name(name)
        if char_id is None:
            await ctx.send(f"Không tìm thấy nhân vật: **{name}**")
            return
        
        profile = self.profiles.get(char_id)
        if not profile:
            await ctx.send("Không có thông tin profile.")
            return
        
        char_name = get_character_name(char_id, full=True)
        seiyuu = profile.get('characterVoice', 'N/A')
        
        embed = discord.Embed(
            title=f"Seiyuu của {char_name}",
            description=f"**{seiyuu}**",
            color=get_unit_color(char_id)
        )
        
        card = self.get_random_card_for_character(char_id)
        if card:
            embed.set_image(url=get_card_image_url(card['assetbundleName'], False))
            view = CardToggleView(embed, card)
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(embed=embed)
    
    @commands.command(name='fact', aliases=['randomfact'])
    async def fact_prefix(self, ctx: commands.Context):
        """Get a random character fact: !fact"""
        main_chars = [cid for cid in self.profiles.keys() if cid <= 26]
        if not main_chars:
            await ctx.send("Không có dữ liệu profile!")
            return
        
        char_id = random.choice(main_chars)
        profile = self.profiles[char_id]
        name = get_character_name(char_id, full=True)
        
        facts = []
        if profile.get('hobby'):
            facts.append(("Sở thích", profile['hobby'].replace('\\n', ' ')))
        if profile.get('specialSkill'):
            facts.append(("Kỹ năng", profile['specialSkill']))
        if profile.get('favoriteFood'):
            facts.append(("Món yêu thích", profile['favoriteFood']))
        
        if not facts:
            await ctx.send("Không có thông tin thú vị!")
            return
        
        category, fact = random.choice(facts)
        
        embed = discord.Embed(
            title=f"Bạn có biết về {name}?",
            color=get_unit_color(char_id)
        )
        embed.add_field(name=category, value=fact, inline=False)
        embed.set_footer(text="Dùng !fact để xem thêm!")
        
        card = self.get_random_card_for_character(char_id)
        if card:
            embed.set_image(url=get_card_image_url(card['assetbundleName'], False))
            view = CardToggleView(embed, card)
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))
