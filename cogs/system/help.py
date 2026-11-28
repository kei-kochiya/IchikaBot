"""Interactive `/help` cog listing all slash commands by category."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# Command categories with descriptions: (slash_usage, description)
COMMAND_CATEGORIES = {
    "Card & Gacha": {
        "description": "Thẻ và quay gacha",
        "commands": [
            ("/card <name>", "Xem thông tin thẻ"),
            ("/gacha pull [amount]", "Quay gacha (1 hoặc 10 lần)"),
            ("/gacha pity", "Kiểm tra pity"),
        ],
    },
    "Music & Games": {
        "description": "Nhạc và mini-game",
        "commands": [
            ("/song search <query>", "Tìm bài hát"),
            ("/song info <name>", "Xem chi tiết bài hát"),
            ("/song random", "Bài hát ngẫu nhiên"),
            ("/songguess [mode] [pool]", "Đoán tên bài hát qua đoạn nhạc trong kênh voice"),
            ("/guess [độ khó]", "Đoán nhân vật qua hình ảnh (Dễ / Thường / Khó)"),
            ("/guessmode [độ khó]", "Đặt độ khó mặc định của bạn cho /guess"),
            ("/jacketguess [độ khó]", "Đoán bài hát qua ảnh bìa (Jacket)"),
            ("/chartguess [master/append] [độ khó]", "Đoán bài hát qua đoạn chart Master/Append"),
        ],
    },
    "Profiles": {
        "description": "Thông tin nhân vật",
        "commands": [
            ("/profile info <name>", "Thông tin nhân vật"),
        ],
    },
    "Events": {
        "description": "Sự kiện game",
        "commands": [
            ("/event current", "Sự kiện hiện tại"),
            ("/event history", "Lịch sử sự kiện"),
            ("/event search <name>", "Tìm sự kiện"),
        ],
    },
    "Birthday": {
        "description": "Sinh nhật nhân vật",
        "commands": [
            ("/birthday check", "Kiểm tra sinh nhật hôm nay"),
            ("/birthday countdown [name]", "Đếm ngược đến sinh nhật tiếp theo"),
            ("/birthday channel", "Đặt kênh thông báo (Admin)"),
        ],
    },
    "Utility": {
        "description": "Tiện ích",
        "commands": [
            ("/help [category]", "Hiển thị trợ giúp"),
            ("/gasprice", "Tra cứu giá xăng dầu PVOIL"),
            ("/update_data", "Cập nhật dữ liệu game ngay (Admin)"),
        ],
    },
    "Card of the Day": {
        "description": "Card ngẫu nhiên tự động",
        "commands": [
            ("/cotd channel", "Đặt kênh gửi Card of the Day (Admin)"),
            ("/cotd interval", "Đặt tần suất gửi (Admin)"),
            ("/cotd now", "Gửi card ngay lập tức (Admin)"),
            ("/cotd disable", "Tắt Card of the Day (Admin)"),
            ("/cotd status", "Xem trạng thái hiện tại"),
        ],
    },
    "Mercari": {
        "description": "Tra cứu giá Mercari JP",
        "commands": [
            ("/mercari <url_or_id>", "Tra cứu sản phẩm theo link hoặc ID"),
        ],
    },
    "PJSK & B30": {
        "description": "Liên kết tài khoản PJSK (EN/JP), đồng bộ FC/AP & bảng B30",
        "commands": [
            ("/pjsk link [region]", "Liên kết tài khoản PJSK qua Bio"),
            ("/pjsk unlink [region]", "Hủy liên kết và xóa dữ liệu đã lưu"),
            ("/pjsk profile [region] [user]", "Xem hồ sơ PJSK đã liên kết"),
            ("/pjsk sync [region]", "Đồng bộ FC/AP qua Transfer ID và nhận mã mới"),
            ("/pjsk recover [region]", "Khôi phục Transfer ID nếu sync bị gián đoạn"),
            ("/b30 [region] [user]", "Xem bảng Best 30 (B30) rating (hoặc /pjsk b30)"),
        ],
    },
}


class HelpCog(commands.Cog):
    """Slash `/help` command grouped by feature category."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _find_category(name: str | None) -> str | None:
        """Look up a category by name, ignoring case and spaces."""
        if not name:
            return None
        wanted = name.replace(" ", "").lower()
        return next((c for c in COMMAND_CATEGORIES if c.replace(" ", "").lower() == wanted), None)

    def create_help_embed(self, category: str | None = None) -> discord.Embed:
        """Build the overview embed or one category's detailed embed."""
        found = self._find_category(category)
        if found:
            cat_data = COMMAND_CATEGORIES[found]
            embed = discord.Embed(
                title=found, description=cat_data["description"], color=discord.Color.blue()
            )
            for slash, desc in cat_data["commands"]:
                embed.add_field(name=desc, value=f"`{slash}`", inline=False)
            return embed

        embed = discord.Embed(
            title="Danh sách lệnh",
            description="Gõ `/` để dùng lệnh slash.\nXem chi tiết một mục: `/help <mục>`.",
            color=discord.Color.blue(),
        )
        for cat_name, cat_data in COMMAND_CATEGORIES.items():
            names = [slash.split(" <")[0].split(" [")[0] for slash, _ in cat_data["commands"]]
            embed.add_field(
                name=f"{cat_name} · {cat_data['description']}",
                value=" ".join(f"`{name}`" for name in names),
                inline=False,
            )
        return embed

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
            app_commands.Choice(name="PJSK & B30", value="PJSK & B30"),
        ]
    )
    async def help_slash(self, interaction: discord.Interaction, category: str | None = None):
        """Show help information via slash command."""
        embed = self.create_help_embed(category)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
