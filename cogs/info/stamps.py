"""
Stamp Database Cog - Browse and search Project Sekai stamps.
Supports both JP and EN stamp data with English search.
"""
import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import aiofiles
import random

from config import STAMPS_FILE_JP, STAMPS_FILE_EN
from utils.game_data import get_character_name, get_unit_color, character_autocomplete, game_data
from utils.romaji import matches_query, normalize_for_search

logger = logging.getLogger(__name__)

# Stamp image base URL - Always uses JP storage
STAMP_IMAGE_URL = "https://storage.sekai.best/sekai-jp-assets/stamp/{asset}/{asset}.png"


class StampsCog(commands.Cog):
    """Cog for browsing and searching Project Sekai stamps."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.stamps_jp = []
        self.stamps_en = []
        self.stamps_en_by_id = {}
        
    async def cog_load(self):
        """Load stamp data when the cog loads."""
        await self.load_data()
        logger.info("StampsCog loaded with %d JP stamps and %d EN stamps", 
                    len(self.stamps_jp), len(self.stamps_en))
    
    async def load_data(self):
        """Load both JP and EN stamps data from JSON files."""
        # Load JP stamps
        try:
            async with aiofiles.open(STAMPS_FILE_JP, 'r', encoding='utf-8') as f:
                self.stamps_jp = json.loads(await f.read())
        except FileNotFoundError as e:
            logger.error("Stamps: Missing JP file: %s", e.filename)
            self.stamps_jp = []
        except Exception as e:
            logger.error("Failed to load JP stamp data: %s", e)
            self.stamps_jp = []
        
        # Load EN stamps
        try:
            async with aiofiles.open(STAMPS_FILE_EN, 'r', encoding='utf-8') as f:
                self.stamps_en = json.loads(await f.read())
            self.stamps_en_by_id = {s['id']: s for s in self.stamps_en}
        except FileNotFoundError as e:
            logger.warning("Stamps: Missing EN file: %s", e.filename)
            self.stamps_en = []
            self.stamps_en_by_id = {}
        except Exception as e:
            logger.error("Failed to load EN stamp data: %s", e)
            self.stamps_en = []
            self.stamps_en_by_id = {}

    def get_stamp_by_id(self, stamp_id: int) -> dict | None:
        """Get stamp by ID, prioritizing EN data, fallback to JP."""
        if stamp_id in self.stamps_en_by_id:
            return self.stamps_en_by_id[stamp_id]
        for stamp in self.stamps_jp:
            if stamp['id'] == stamp_id:
                return stamp
        return None

    def get_display_name(self, stamp: dict, stamp_id: int) -> str:
        """Get display name, using EN if available."""
        en_stamp = self.stamps_en_by_id.get(stamp_id)
        name = stamp.get('name', 'Unknown')
        
        if en_stamp and en_stamp.get('name'):
            name = en_stamp['name']
        
        # Strip prefix
        if name.startswith('[スタンプ]'):
            name = name[6:]
        if name.startswith('[Stamp]'):
            name = name[7:]
        
        return name
    
    def create_stamp_embed(self, stamp: dict) -> discord.Embed:
        """Create an embed for a stamp."""
        stamp_id = stamp.get('id', 0)
        char_id = stamp.get('characterId1', stamp.get('gameCharacterUnitId', 0))
        char_name = get_character_name(char_id)
        
        name = self.get_display_name(stamp, stamp_id)
        
        embed = discord.Embed(
            title=f"{name}",
            color=get_unit_color(char_id)
        )
        
        embed.add_field(name="Nhân vật", value=char_name, inline=True)
        embed.add_field(name="ID", value=str(stamp_id), inline=True)
        embed.add_field(name="Loại", value=stamp.get('stampType', 'illustration'), inline=True)
        
        if stamp.get('description'):
            embed.add_field(name="Cách nhận", value=stamp['description'], inline=False)
        
        # Asset URLs always use JP storage
        asset = stamp.get('assetbundleName', '')
        if asset:
            embed.set_image(url=STAMP_IMAGE_URL.format(asset=asset))
        
        return embed
    
    def search_stamps(self, keyword: str, limit: int = 10) -> list:
        """Search stamps by keyword, ID, or romaji in both JP and EN."""
        # If keyword is a number, try ID-based search
        if keyword.isdigit():
            target_id = int(keyword)
            stamp = self.get_stamp_by_id(target_id)
            if stamp:
                return [stamp]
            # Find nearest ID
            all_stamps = self.stamps_jp if self.stamps_jp else self.stamps_en
            sorted_stamps = sorted(all_stamps, key=lambda s: (abs(s['id'] - target_id), -s['id']))
            if sorted_stamps:
                return [sorted_stamps[0]]
            return []
        
        results = []
        seen_ids = set()
        
        # Search EN stamps first
        for stamp in self.stamps_en:
            name = stamp.get('name', '')
            if matches_query(keyword, name):
                if stamp['id'] not in seen_ids:
                    results.append(stamp)
                    seen_ids.add(stamp['id'])
                    if len(results) >= limit:
                        return results
        
        # Then search JP stamps
        for stamp in self.stamps_jp:
            if stamp['id'] in seen_ids:
                continue
            name = stamp.get('name', '')
            if matches_query(keyword, name):
                results.append(stamp)
                seen_ids.add(stamp['id'])
                if len(results) >= limit:
                    break
        
        return results
    
    def get_stamps_by_character(self, char_id: int) -> list:
        """Get all stamps for a character (from JP data as it's more complete)."""
        return [s for s in self.stamps_jp 
                if s.get('characterId1') == char_id or s.get('gameCharacterUnitId') == char_id]
    
    # --- Autocomplete ---
    async def char_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return character_autocomplete(current)
    
    # ===== SLASH COMMANDS =====
    stamp_group = app_commands.Group(name="stamp", description="Tìm kiếm và xem stamp")
    
    @stamp_group.command(name="search", description="Tìm stamp theo từ khóa (JP/EN)")
    @app_commands.describe(keyword="Từ khóa tìm kiếm (tên stamp)")
    async def stamp_search(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer()
        results = self.search_stamps(keyword)
        
        if not results:
            await interaction.followup.send(f"Không tìm thấy stamp với từ khóa: **{keyword}**")
            return
        
        embed = discord.Embed(
            title=f"🔍 Kết quả tìm kiếm: {keyword}",
            description=f"Tìm thấy {len(results)} stamp",
            color=0x5865F2
        )
        
        for stamp in results:
            name = self.get_display_name(stamp, stamp['id'])
            char_id = stamp.get('characterId1', stamp.get('gameCharacterUnitId', 0))
            char_name = get_character_name(char_id)
            embed.add_field(name=name, value=f"ID: {stamp['id']} | {char_name}", inline=False)
        
        if results and results[0].get('assetbundleName'):
            embed.set_thumbnail(url=STAMP_IMAGE_URL.format(asset=results[0]['assetbundleName']))
        
        await interaction.followup.send(embed=embed)
    
    @stamp_group.command(name="character", description="Xem tất cả stamp của một nhân vật")
    @app_commands.describe(character="Chọn nhân vật")
    @app_commands.autocomplete(character=char_autocomplete)
    async def stamp_character(self, interaction: discord.Interaction, character: str):
        await interaction.response.defer()
        
        try:
            char_id = int(character)
        except ValueError:
            char_id, _ = game_data.get_character_by_name(character)
            if char_id is None:
                await interaction.followup.send(f"Không tìm thấy nhân vật: **{character}**")
                return
        
        char_name = get_character_name(char_id)
        results = self.get_stamps_by_character(char_id)
        
        if not results:
            await interaction.followup.send(f"Không tìm thấy stamp của **{char_name}**")
            return
        
        embed = discord.Embed(
            title=f"Stamp của {char_name}",
            description=f"Tìm thấy {len(results)} stamp",
            color=get_unit_color(char_id)
        )
        
        for stamp in results[:10]:
            name = self.get_display_name(stamp, stamp['id'])
            embed.add_field(name=name, value=f"ID: {stamp['id']}", inline=True)
        
        if len(results) > 10:
            embed.set_footer(text=f"Và {len(results) - 10} stamp khác...")
        
        if results and results[0].get('assetbundleName'):
            embed.set_thumbnail(url=STAMP_IMAGE_URL.format(asset=results[0]['assetbundleName']))
        
        await interaction.followup.send(embed=embed)
    
    @stamp_group.command(name="random", description="Xem một stamp ngẫu nhiên")
    async def stamp_random_slash(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        all_stamps = self.stamps_jp if self.stamps_jp else self.stamps_en
        if not all_stamps:
            await interaction.followup.send("Không có dữ liệu stamp!")
            return
        
        stamp = random.choice(all_stamps)
        embed = self.create_stamp_embed(stamp)
        embed.set_footer(text="🎲 Stamp ngẫu nhiên")
        
        await interaction.followup.send(embed=embed)
    
    # ===== PREFIX COMMANDS =====
    @commands.command(name='stamp', aliases=['st'])
    async def stamp_prefix(self, ctx: commands.Context, *, keyword: str = None):
        """Search for stamps: !stamp <keyword>"""
        if not keyword:
            await ctx.send("Vui lòng nhập từ khóa: `!stamp <keyword>`")
            return
        
        results = self.search_stamps(keyword)
        
        if not results:
            await ctx.send(f"Không tìm thấy stamp với từ khóa: **{keyword}**")
            return
        
        embed = discord.Embed(
            title=f"🔍 Kết quả tìm kiếm: {keyword}",
            description=f"Tìm thấy {len(results)} stamp",
            color=0x5865F2
        )
        
        for stamp in results[:5]:
            name = self.get_display_name(stamp, stamp['id'])
            char_name = get_character_name(stamp.get('characterId1', 0))
            embed.add_field(name=name, value=f"ID: {stamp['id']} | {char_name}", inline=False)
        
        if results and results[0].get('assetbundleName'):
            embed.set_thumbnail(url=STAMP_IMAGE_URL.format(asset=results[0]['assetbundleName']))
        
        await ctx.send(embed=embed)
    
    @commands.command(name='stampc')
    async def stamp_char_prefix(self, ctx: commands.Context, *, name: str = None):
        """Get stamps by character: !stampc <name>"""
        if not name:
            await ctx.send("Vui lòng nhập tên nhân vật: `!stampc <name>`")
            return
        
        char_id, char = game_data.get_character_by_name(name)
        if char_id is None:
            await ctx.send(f"Không tìm thấy nhân vật: **{name}**")
            return
        
        char_name = get_character_name(char_id)
        results = self.get_stamps_by_character(char_id)
        
        if not results:
            await ctx.send(f"Không tìm thấy stamp của **{char_name}**")
            return
        
        embed = discord.Embed(
            title=f"🎨 Stamp của {char_name}",
            description=f"Tìm thấy {len(results)} stamp",
            color=get_unit_color(char_id)
        )
        
        for stamp in results[:10]:
            stamp_name = self.get_display_name(stamp, stamp['id'])
            embed.add_field(name=stamp_name, value=f"ID: {stamp['id']}", inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='stampr')
    async def stamp_random_prefix(self, ctx: commands.Context):
        """Get a random stamp: !stampr"""
        all_stamps = self.stamps_jp if self.stamps_jp else self.stamps_en
        if not all_stamps:
            await ctx.send("Không có dữ liệu stamp!")
            return
        
        stamp = random.choice(all_stamps)
        embed = self.create_stamp_embed(stamp)
        embed.set_footer(text="🎲 Stamp ngẫu nhiên")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StampsCog(bot))