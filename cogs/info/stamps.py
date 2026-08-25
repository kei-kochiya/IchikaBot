"""
Stamp Database Cog - Browse and search Project Sekai stamps.
Supports both JP and EN stamp data with English search.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging

from utils.data.stamp_data import stamp_data
from utils.data.game_data import get_character_name, get_unit_color, character_autocomplete, game_data

logger = logging.getLogger(__name__)

# Stamp image base URL - Always uses JP storage
STAMP_IMAGE_URL = "https://storage.sekai.best/sekai-jp-assets/stamp/{asset}/{asset}.png"


class StampsCog(commands.Cog):
    """Cog for browsing and searching Project Sekai stamps."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    async def cog_load(self):
        logger.info("StampsCog loaded with %d JP stamps and %d EN stamp names (shared singleton)", 
                    len(stamp_data.stamps_jp), len(stamp_data.stamps_en_names))
    
    def load_data(self):
        """Stamp data is managed by utils.stamp_data singleton."""
        pass

    def get_stamp_by_id(self, stamp_id: int) -> dict | None:
        """Get stamp by ID."""
        return stamp_data.get_stamp_by_id(stamp_id)

    def get_display_name(self, stamp: dict, stamp_id: int) -> str:
        """Get display name, using EN if available."""
        return stamp_data.get_display_name(stamp, stamp_id)
    
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
    
    def search_stamps(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search stamps by keyword, ID, or romaji in both JP and EN."""
        return stamp_data.search_stamps(keyword, limit)
    
    def get_stamps_by_character(self, char_id: int) -> list[dict]:
        """Get all stamps for a character."""
        return stamp_data.get_stamps_by_character(char_id)
    
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
        
        stamp = stamp_data.get_random_stamp()
        if not stamp:
            await interaction.followup.send("Không có dữ liệu stamp!")
            return
        
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
        stamp = stamp_data.get_random_stamp()
        if not stamp:
            await ctx.send("Không có dữ liệu stamp!")
            return
        
        embed = self.create_stamp_embed(stamp)
        embed.set_footer(text="🎲 Stamp ngẫu nhiên")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StampsCog(bot))