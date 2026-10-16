"""
Mercari Cog - Look up Mercari item info from a URL or item ID, and search Mercari listings.
Supports both Individual C2C Marketplace items and Mercari Shops storefront items.
Global cooldown: 5 seconds per user.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.mercari_scraper import (
    AsyncMercariScraper,
    ItemSource,
    ItemStatus,
    MercariItem,
    extract_item_info,
)

logger = logging.getLogger(__name__)

# Users who receive the lower exchange rate (JPY × 180 + 10 000 VND)
# Everyone else uses JPY × 182 + 10 000 VND
_PREFERRED_RATE_USERS: frozenset[int] = frozenset(
    {
        304351602637012992,
        602357018782597120,
        458547599947857920,
    }
)


def extract_item_id(text: str) -> str:
    """Extract the Mercari item ID from a full URL or bare ID string."""
    item_id, _ = extract_item_info(text)
    return item_id


def _compute_vnd_price(jpy: int, user_id: int) -> int:
    rate = 180 if user_id in _PREFERRED_RATE_USERS else 182
    return jpy * rate + 10_000


def _build_item_embed(item: MercariItem, user_id: int) -> discord.Embed:
    jpy = item.price
    vnd = _compute_vnd_price(jpy, user_id)

    status_text = "🔴 Sold" if item.is_sold else "🟢 Còn hàng"
    embed_color = discord.Color.red() if item.is_sold else discord.Color.green()
    source_label = "Mercari Shops" if item.source == ItemSource.SHOPS else "Mercari C2C"

    embed = discord.Embed(
        title=item.name or "Không có tên",
        url=item.item_url,
        color=embed_color,
    )
    embed.add_field(
        name="Giá gốc (JPY)",
        value=f"¥{jpy:,}",
        inline=True,
    )
    embed.add_field(
        name="Giá (VND)",
        value=f"{vnd:,} VND",
        inline=True,
    )
    embed.add_field(name="Trạng thái", value=status_text, inline=True)

    photos = item.photos or []
    if photos:
        embed.set_image(url=photos[0])
        if len(photos) > 1:
            embed.set_footer(text=f"{len(photos)} ảnh • {source_label}")
        else:
            embed.set_footer(text=source_label)
    elif item.thumbnail_url:
        embed.set_image(url=item.thumbnail_url)
        embed.set_footer(text=source_label)
    else:
        embed.set_footer(text=f"Không có ảnh • {source_label}")

    return embed


class MercariCog(commands.Cog):
    """Mercari Cog - Look up item info and search listings using mercari_scraper."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._scraper: AsyncMercariScraper | None = None

    async def cog_load(self) -> None:
        self._scraper = AsyncMercariScraper()

    async def cog_unload(self) -> None:
        if self._scraper:
            await self._scraper.close()

    def _ensure_scraper(self) -> AsyncMercariScraper:
        if self._scraper is None:
            self._scraper = AsyncMercariScraper()
        return self._scraper

    # Shared lookup logic
    async def _lookup(self, item_id_or_url: str, user_id: int) -> discord.Embed | str:
        scraper = self._ensure_scraper()
        try:
            item = await scraper.get_item(item_id_or_url)
        except Exception as e:
            logger.error("Mercari: lookup failed for %s: %s", item_id_or_url, e)
            return f"Không thể lấy thông tin sản phẩm: `{e}`"

        if not item:
            return "Không tìm thấy sản phẩm hoặc bị Mercari chặn."

        return _build_item_embed(item, user_id)

    # Slash command: /mercari
    @app_commands.command(
        name="mercari",
        description="Tra cứu sản phẩm Mercari theo URL hoặc ID (C2C & Shops)",
    )
    @app_commands.describe(link="Link Mercari hoặc ID sản phẩm (m... hoặc Shops)")
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def slash_mercari(self, interaction: discord.Interaction, link: str):
        await interaction.response.defer()
        result = await self._lookup(link, interaction.user.id)

        if isinstance(result, str):
            await interaction.followup.send(result, ephemeral=True)
        else:
            await interaction.followup.send(embed=result)

    @slash_mercari.error
    async def slash_mercari_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            try:
                await interaction.response.send_message(
                    f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.",
                    ephemeral=True,
                )
            except discord.InteractionResponded:
                await interaction.followup.send(
                    f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.",
                    ephemeral=True,
                )
        else:
            logger.error("Mercari slash error: %s", error)
            msg = "Đã xảy ra lỗi khi tra cứu sản phẩm."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

    # Prefix command: !mercari
    @commands.command(name="mercari", aliases=["mer", "merca"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def prefix_mercari(self, ctx: commands.Context, *, link: str | None = None):
        if not link:
            await ctx.send("Vui lòng cung cấp link hoặc ID sản phẩm: `!mercari <link>`")
            return

        async with ctx.typing():
            result = await self._lookup(link, ctx.author.id)

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

    # Search command: /mercarisearch
    @app_commands.command(
        name="mercarisearch",
        description="Tìm kiếm sản phẩm trên Mercari JP (C2C & Shops)",
    )
    @app_commands.describe(
        query="Từ khóa tìm kiếm (tiếng Nhật hoặc tiếng Anh)",
        source="Nguồn tìm kiếm (Tất cả, C2C, Shops)",
    )
    @app_commands.choices(
        source=[
            app_commands.Choice(name="Tất cả (C2C + Shops)", value="all"),
            app_commands.Choice(name="Cá nhân (C2C)", value="individual"),
            app_commands.Choice(name="Cửa hàng (Shops)", value="shops"),
        ]
    )
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def slash_mercarisearch(
        self,
        interaction: discord.Interaction,
        query: str,
        source: str = "all",
    ):
        await interaction.response.defer()
        result = await self._search_embed(query, source, interaction.user.id)
        if isinstance(result, str):
            await interaction.followup.send(result, ephemeral=True)
        else:
            await interaction.followup.send(embed=result)

    @slash_mercarisearch.error
    async def slash_mercarisearch_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            try:
                await interaction.response.send_message(
                    f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.",
                    ephemeral=True,
                )
            except discord.InteractionResponded:
                await interaction.followup.send(
                    f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.",
                    ephemeral=True,
                )
        else:
            logger.error("Mercari search error: %s", error)

    # Prefix search: !mercarisearch
    @commands.command(name="mercarisearch", aliases=["msearch", "mersearch"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def prefix_mercarisearch(self, ctx: commands.Context, *, query: str | None = None):
        if not query:
            await ctx.send("Vui lòng cung cấp từ khóa: `!mercarisearch <từ khóa>`")
            return

        async with ctx.typing():
            result = await self._search_embed(query, "all", ctx.author.id)

        if isinstance(result, str):
            await ctx.send(result)
        else:
            await ctx.send(embed=result)

    @prefix_mercarisearch.error
    async def prefix_mercarisearch_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.",
                delete_after=5,
            )

    async def _search_embed(self, query: str, source_str: str, user_id: int) -> discord.Embed | str:
        scraper = self._ensure_scraper()
        item_source = ItemSource.ALL
        if source_str == "individual":
            item_source = ItemSource.INDIVIDUAL
        elif source_str == "shops":
            item_source = ItemSource.SHOPS

        try:
            items = await scraper.search(
                query=query,
                source=item_source,
                status=ItemStatus.ON_SALE,
                limit=6,
            )
        except Exception as e:
            logger.error("Mercari search failed for '%s': %s", query, e)
            return f"Lỗi khi tìm kiếm: `{e}`"

        if not items:
            return f"🔍 Không tìm thấy sản phẩm nào đang bán cho từ khóa `{query}`."

        embed = discord.Embed(
            title=f"🔍 Kết quả tìm kiếm: {query}",
            color=discord.Color.blue(),
        )

        for i, it in enumerate(items, 1):
            vnd = _compute_vnd_price(it.price, user_id)
            src_tag = "Shops" if it.source == ItemSource.SHOPS else "C2C"
            short_name = (it.name[:55] + "...") if len(it.name) > 55 else it.name
            embed.add_field(
                name=f"{i}. [{src_tag}] ¥{it.price:,} (~{vnd:,} VND)",
                value=f"[{short_name}]({it.item_url})",
                inline=False,
            )

        if items[0].thumbnail_url:
            embed.set_thumbnail(url=items[0].thumbnail_url)

        embed.set_footer(text=f"Hiển thị {len(items)} kết quả đang bán • Mercari JP")
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(MercariCog(bot))
