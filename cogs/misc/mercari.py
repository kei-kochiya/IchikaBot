"""
Mercari Cog - Look up Mercari item info from a URL or item ID.
Shows item name, price (raw JPY + two VND estimates), status, and cover photo.
Global cooldown: 5 seconds per user.
"""
import discord
from discord.ext import commands
from discord import app_commands
import logging
from math import ceil

logger = logging.getLogger(__name__)

try:
    from mercapi import Mercapi
    MERCAPI_AVAILABLE = True
except ImportError:
    MERCAPI_AVAILABLE = False
    logger.error("Mercari: 'mercapi' package not installed. Run: pip install mercapi")


def extract_item_id(text: str) -> str:
    """Extract the Mercari item ID from a full URL or bare ID string."""
    # Strip query params then grab the last path segment
    return text.strip().split("?")[0].rstrip("/").split("/")[-1]


class MercariCog(commands.Cog):
    """Fetch Mercari item info by URL or item ID."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._mercapi = Mercapi() if MERCAPI_AVAILABLE else None

    # ── Shared lookup logic ────────────────────────────────────────────────────

    async def _lookup(self, item_id: str) -> discord.Embed | str:
        """
        Fetch the item and return a ready-made Embed, or an error string.
        """
        if not MERCAPI_AVAILABLE or self._mercapi is None:
            return "❌ Dependency `mercapi` chưa được cài. Chạy `pip install mercapi`."

        try:
            item = await self._mercapi.item(item_id)
        except Exception as e:
            logger.error("Mercari: lookup failed for %s: %s", item_id, e)
            return f"Không thể lấy thông tin sản phẩm: `{e}`"

        if not item:
            return "Không tìm thấy sản phẩm hoặc bị Mercari chặn."

        # ── Price calculations (mirror mer.py logic) ─────────────────────
        jpy        = item.price
        vnd_vanh   = ceil(0.185 * jpy)          # Nguyễn Vanh rate
        vnd_kho    = ceil(0.17 * (jpy + 100))   # Kho mới rate

        # ── Status ───────────────────────────────────────────────────────
        status_raw = getattr(item, "status", "")
        if status_raw == "on_sale":
            status_text  = "🟢 Còn hàng"
            embed_color  = discord.Color.green()
        else:
            status_text  = "🔴 Đã Sold"
            embed_color  = discord.Color.red()

        # ── Build embed ───────────────────────────────────────────────────
        embed = discord.Embed(
            title=item.name or "Không có tên",
            url=f"https://jp.mercari.com/item/{item_id}",
            color=embed_color,
        )
        embed.add_field(
            name="Giá gốc (JPY)",
            value=f"¥{jpy:,}",
            inline=True,
        )
        embed.add_field(
            name="Nguyễn Vanh",
            value=f"{vnd_vanh:,}k VND",
            inline=True,
        )
        embed.add_field(
            name="Kho mới",
            value=f"{vnd_kho:,}k VND",
            inline=True,
        )
        embed.add_field(name="Trạng thái", value=status_text, inline=True)

        photos = getattr(item, "photos", None) or []
        if photos:
            embed.set_image(url=photos[0])
            if len(photos) > 1:
                embed.set_footer(text=f"{len(photos)} ảnh")
        else:
            embed.set_footer(text="Không có ảnh")

        return embed

    # ── Slash command ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="mercari",
        description="Tra cứu sản phẩm Mercari theo URL hoặc ID",
    )
    @app_commands.describe(link="Link Mercari hoặc ID sản phẩm (m...)")
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def slash_mercari(self, interaction: discord.Interaction, link: str):
        await interaction.response.defer()
        item_id = extract_item_id(link)
        result  = await self._lookup(item_id)

        if isinstance(result, str):
            await interaction.followup.send(result, ephemeral=True)
        else:
            await interaction.followup.send(embed=result)

    @slash_mercari.error
    async def slash_mercari_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.",
                ephemeral=True,
            )
        else:
            logger.error("Mercari slash error: %s", error)

    # ── Prefix command ─────────────────────────────────────────────────────────

    @commands.command(name="mercari", aliases=["mer", "merca"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def prefix_mercari(self, ctx: commands.Context, *, link: str = None):
        """Look up a Mercari item: !mercari <url or ID>"""
        if not link:
            await ctx.send("Vui lòng cung cấp link hoặc ID sản phẩm: `!mercari <link>`")
            return

        async with ctx.typing():
            item_id = extract_item_id(link)
            result  = await self._lookup(item_id)

        if isinstance(result, str):
            await ctx.send(result)
        else:
            await ctx.send(embed=result)

    @prefix_mercari.error
    async def prefix_mercari_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.",
                delete_after=5,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(MercariCog(bot))
