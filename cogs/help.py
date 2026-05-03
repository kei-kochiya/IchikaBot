"""
Help Cog - Custom help command for both prefix and slash commands.
"""
import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger(__name__)

# Command categories with descriptions
COMMAND_CATEGORIES = {
    "Card & Gacha": {
        "description": "Thẻ và quay gacha",
        "commands": [
            ("/card <name>", "!card <name>", "Xem thông tin thẻ"),
            ("/gacha pull", "!gacha", "Quay gacha 10 lần"),
            ("/gacha pity", "!pity", "Kiểm tra pity"),
        ]
    },
    "Music & Games": {
        "description": "Nhạc và mini-game",
        "commands": [
            ("/song search <query>", "!song <query>", "Tìm bài hát"),
            ("/song random", "!songr", "Bài hát ngẫu nhiên"),
            ("/songguess", "!songguess", "Chơi đoán nhạc"),
            ("/guess", "!guess", "Chơi đoán nhân vật"),
        ]
    },
    "Stamps & Profiles": {
        "description": "Stamp và thông tin nhân vật",
        "commands": [
            ("/stamp search <keyword>", "!stamp <keyword>", "Tìm stamp"),
            ("/stamp character <name>", "!stampc <name>", "Stamp của nhân vật"),
            ("/stamp random", "!stampr", "Stamp ngẫu nhiên"),
            ("/profile info <name>", "!profile <name>", "Thông tin nhân vật"),
            ("/profile voice <name>", "!voice <name>", "Thông tin seiyuu"),
            ("/profile random_fact", "!fact", "Sự thật ngẫu nhiên"),
        ]
    },
    "Events": {
        "description": "Sự kiện game",
        "commands": [
            ("/event current", "!event", "Sự kiện hiện tại"),
            ("/event history", "!events", "Lịch sử sự kiện"),
            ("/event search <name>", "!eventsearch <name>", "Tìm sự kiện"),
        ]
    },
    "Birthday": {
        "description": "Sinh nhật nhân vật",
        "commands": [
            ("/birthday today", "!bday", "Sinh nhật hôm nay"),
            ("/birthday upcoming", "!bdayu", "Sinh nhật sắp tới"),
            ("/birthday channel", "-", "Đặt kênh thông báo (Admin)"),
        ]
    },
    "Utility": {
        "description": "Tiện ích",
        "commands": [
            ("/help", "!help", "Hiển thị trợ giúp"),
            ("-", "!sync", "Đồng bộ slash commands"),
            ("/update_data", "-", "Cập nhật dữ liệu (Admin)"),
        ]
    },
    "Card of the Day": {
        "description": "Card ngẫu nhiên tự động",
        "commands": [
            ("/cotd channel", "-", "Đặt kênh gửi Card of the Day (Admin)"),
            ("/cotd interval", "-", "Đặt tần suất gửi (Admin)"),
            ("/cotd now", "-", "Gửi card ngay lập tức (Admin)"),
            ("/cotd disable", "-", "Tắt Card of the Day (Admin)"),
            ("/cotd status", "-", "Xem trạng thái hiện tại"),
        ]
    },
    "Tournament": {
        "description": "Tournament đoán card (5 vòng)",
        "commands": [
            ("/tournament", "!tournament", "Bắt đầu tournament"),
            ("/tournament_stop", "!tourstop", "Dừng tournament (Admin)"),
        ]
    },
    "Mercari": {
        "description": "Tra cứu giá Mercari JP",
        "commands": [
            ("/mercari", "!mercari / !mer", "Tra cứu sản phẩm theo link hoặc ID"),
        ]
    }
}


class HelpCog(commands.Cog):
    """Custom help command for both prefix and slash."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    def create_help_embed(self, category: str = None) -> discord.Embed:
        """Create the help embed."""
        if category and category in COMMAND_CATEGORIES:
            # Show specific category
            cat_data = COMMAND_CATEGORIES[category]
            embed = discord.Embed(
                title=f"{category}",
                description=cat_data['description'],
                color=discord.Color.blue()
            )
            
            for slash, prefix, desc in cat_data['commands']:
                embed.add_field(
                    name=f"`{slash}` / `{prefix}`",
                    value=desc,
                    inline=False
                )
        else:
            # Show all categories
            embed = discord.Embed(
                title="📚 Trợ giúp - Project Sekai Bot",
                description="Dưới đây là danh sách các lệnh. Sử dụng `/` cho slash commands hoặc `!` cho prefix commands.",
                color=discord.Color.blue()
            )
            
            for cat_name, cat_data in COMMAND_CATEGORIES.items():
                # Get first 3 commands as preview
                preview = [cmd[2] for cmd in cat_data['commands'][:3]]
                embed.add_field(
                    name=cat_name,
                    value=f"{cat_data['description']}\n" + ", ".join(preview),
                    inline=False
                )
            
            embed.set_footer(text="Tip: Sử dụng !help <category> để xem chi tiết từng danh mục")
        
        return embed
    
    # --- Prefix Command ---
    @commands.command(name='help', aliases=['h', 'commands'])
    async def help_prefix(self, ctx: commands.Context, *, category: str = None):
        """Show help information."""
        embed = self.create_help_embed(category)
        await ctx.send(embed=embed)
    
    # --- Slash Command ---
    @app_commands.command(name='help', description='Hiển thị danh sách các lệnh')
    @app_commands.describe(category="Chọn danh mục để xem chi tiết")
    @app_commands.choices(category=[
        app_commands.Choice(name="Card & Gacha", value="Card & Gacha"),
        app_commands.Choice(name="Music & Games", value="Music & Games"),
        app_commands.Choice(name="Stamps & Profiles", value="Stamps & Profiles"),
        app_commands.Choice(name="Events", value="Events"),
        app_commands.Choice(name="Birthday", value="Birthday"),
        app_commands.Choice(name="Utility", value="Utility"),
        app_commands.Choice(name="Card of the Day", value="Card of the Day"),
        app_commands.Choice(name="Tournament", value="Tournament"),
        app_commands.Choice(name="Mercari", value="Mercari"),
    ])
    async def help_slash(self, interaction: discord.Interaction, category: str = None):
        """Show help information via slash command."""
        embed = self.create_help_embed(category)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))