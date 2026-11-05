"""
Help Cog - Custom help command for both prefix and slash commands.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# Command categories with descriptions
COMMAND_CATEGORIES = {
    "Card & Gacha": {
        "description": "Thẻ và quay gacha",
        "commands": [
            ("/card <name>", "-", "Xem thông tin thẻ"),
            ("/gacha pull", "-", "Quay gacha (1 hoặc 10 lần)"),
            ("/gacha pity", "-", "Kiểm tra pity"),
        ],
    },
    "Music & Games": {
        "description": "Nhạc và mini-game",
        "commands": [
            ("/song search <query>", "!song <query>", "Tìm bài hát"),
            ("/song random", "!songr", "Bài hát ngẫu nhiên"),
            ("/songguess", "!sg", "Đoán tên bài hát qua đoạn nhạc trong kênh voice"),
            ("-", "!sgv / !sga", "Đoán nhạc có hiệu ứng / với tất cả bài hát"),
            ("/guess [độ khó]", "-", "Đoán nhân vật qua hình ảnh (Dễ / Thường / Khó)"),
            ("/guessmode <độ khó>", "-", "Đặt độ khó mặc định của bạn cho /guess"),
        ],
    },
    "Profiles": {
        "description": "Thông tin nhân vật",
        "commands": [
            ("/profile info <name>", "!profile <name>", "Thông tin nhân vật"),
        ],
    },
    "Events": {
        "description": "Sự kiện game",
        "commands": [
            ("/event current", "!event", "Sự kiện hiện tại"),
            ("/event history", "!events", "Lịch sử sự kiện"),
            ("/event search <name>", "!eventsearch <name>", "Tìm sự kiện"),
        ],
    },
    "Birthday": {
        "description": "Sinh nhật nhân vật",
        "commands": [
            ("/birthday check", "!bday", "Kiểm tra sinh nhật hôm nay"),
            ("/birthday countdown", "!bdayu / !countdown", "Đếm ngược đến sinh nhật tiếp theo"),
            ("/birthday channel", "-", "Đặt kênh thông báo (Admin)"),
        ],
    },
    "Utility": {
        "description": "Tiện ích",
        "commands": [
            ("/help", "!help", "Hiển thị trợ giúp"),
            ("/gasprice", "!gasprice", "Tra cứu giá xăng dầu PVOIL"),
            ("/update_data", "-", "Cập nhật dữ liệu game ngay (Admin)"),
        ],
    },
    "Card of the Day": {
        "description": "Card ngẫu nhiên tự động",
        "commands": [
            ("/cotd channel", "-", "Đặt kênh gửi Card of the Day (Admin)"),
            ("/cotd interval", "-", "Đặt tần suất gửi (Admin)"),
            ("/cotd now", "-", "Gửi card ngay lập tức (Admin)"),
            ("/cotd disable", "-", "Tắt Card of the Day (Admin)"),
            ("/cotd status", "-", "Xem trạng thái hiện tại"),
        ],
    },
    "Mercari": {
        "description": "Tra cứu giá Mercari JP",
        "commands": [
            ("/mercari <url_or_id>", "!mercari / !mer", "Tra cứu sản phẩm theo link hoặc ID"),
            (
                "/mercarisearch <keyword>",
                "!mercarisearch / !msearch",
                "Tìm kiếm sản phẩm trên Mercari",
            ),
        ],
    },
}


class HelpCog(commands.Cog):
    """Custom help command for both prefix and slash."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _find_category(name: str | None) -> str | None:
        """Category by name, ignoring case and spaces ("card & gacha", "mercari")."""
        if not name:
            return None
        wanted = name.replace(" ", "").lower()
        return next((c for c in COMMAND_CATEGORIES if c.replace(" ", "").lower() == wanted), None)

    @staticmethod
    def _forms(slash: str, prefix: str) -> str:
        """`/song search` · `!song`: only the forms that exist (no dangling "-"), each
        alias ("!mercari / !mer") as its own code span."""
        forms = [alias for form in (slash, prefix) if form != "-" for alias in form.split(" / ")]
        return " · ".join(f"`{form}`" for form in forms)

    def create_help_embed(self, category: str | None = None) -> discord.Embed:
        """The overview of every command, or one category in detail."""
        found = self._find_category(category)
        if found:
            cat_data = COMMAND_CATEGORIES[found]
            embed = discord.Embed(
                title=found, description=cat_data["description"], color=discord.Color.blue()
            )
            for slash, prefix, desc in cat_data["commands"]:
                embed.add_field(name=desc, value=self._forms(slash, prefix), inline=False)
            return embed

        embed = discord.Embed(
            title="Danh sách lệnh",
            description=(
                "Gõ `/` để dùng lệnh slash, hoặc `!` cho lệnh thường.\n"
                "Xem chi tiết một mục: `/help <mục>` hoặc `!help <mục>`."
            ),
            color=discord.Color.blue(),
        )
        for cat_name, cat_data in COMMAND_CATEGORIES.items():
            # The commands themselves (slash form, else the prefix aliases), so the
            # overview alone is enough to find one
            names = [
                name.split(" <")[0].split(" [")[0]
                for slash, prefix, _ in cat_data["commands"]
                for name in ([slash] if slash != "-" else prefix.split(" / "))
            ]
            embed.add_field(
                name=f"{cat_name} · {cat_data['description']}",
                value=" ".join(f"`{name}`" for name in names),
                inline=False,
            )
        return embed

    # --- Prefix Command ---
    @commands.command(name="help", aliases=["h", "commands"])
    async def help_prefix(self, ctx: commands.Context, *, category: str | None = None):
        """Show help information."""
        embed = self.create_help_embed(category)
        await ctx.send(embed=embed)

    # --- Slash Command ---
    @app_commands.command(name="help", description="Hiển thị danh sách các lệnh")
    @app_commands.describe(category="Chọn danh mục để xem chi tiết")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Card & Gacha", value="Card & Gacha"),
            app_commands.Choice(name="Music & Games", value="Music & Games"),
            app_commands.Choice(name="Profiles", value="Profiles"),
            app_commands.Choice(name="Events", value="Events"),
            app_commands.Choice(name="Birthday", value="Birthday"),
            app_commands.Choice(name="Utility", value="Utility"),
            app_commands.Choice(name="Card of the Day", value="Card of the Day"),
            app_commands.Choice(name="Mercari", value="Mercari"),
        ]
    )
    async def help_slash(self, interaction: discord.Interaction, category: str | None = None):
        """Show help information via slash command."""
        embed = self.create_help_embed(category)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
