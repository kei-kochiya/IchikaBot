"""Mercari Japan item lookup cog (C2C listings & Mercari Shops, 5s cooldown)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from utils.mercari_scraper import ItemSource, MercariItem

if TYPE_CHECKING:
    from utils.mercari_scraper import AsyncMercariScraper

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


def _compute_vnd_price(jpy: int, user_id: int) -> int:
    rate = 180 if user_id in _PREFERRED_RATE_USERS else 182
    return jpy * rate + 10_000


def _build_item_embed(item: MercariItem, user_id: int) -> discord.Embed:
    jpy = item.price
    vnd = _compute_vnd_price(jpy, user_id)

    status_text = "Đã bán" if item.is_sold else "Còn hàng"
    embed_color = discord.Color.red() if item.is_sold else discord.Color.green()
    source_label = "Mercari Shops" if item.source == ItemSource.SHOPS else "Mercari C2C"

    embed = discord.Embed(
        title=(item.name or "Không có tên")[:256],
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
    """Mercari Cog - Look up item info from a Mercari URL or item ID."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._scraper: AsyncMercariScraper | None = None

    async def cog_unload(self) -> None:
        if self._scraper:
            scraper, self._scraper = self._scraper, None
            await scraper.close()

    def _ensure_scraper(self) -> AsyncMercariScraper:
        # Created on first use: mercapi/httpx stay unloaded until someone looks up a link
        if self._scraper is None:
            from utils.mercari_scraper import AsyncMercariScraper

            self._scraper = AsyncMercariScraper()
        return self._scraper

    async def _lookup(self, item_id_or_url: str, user_id: int) -> discord.Embed | str:
        scraper = self._ensure_scraper()
        try:
            item = await scraper.get_item(item_id_or_url)
        except Exception as e:
            logger.error("Mercari: lookup failed for %s: %s", item_id_or_url, e)
            return "Không thể lấy thông tin sản phẩm lúc này. Thử lại sau ít phút nhé."

        if not item:
            return "Không tìm thấy sản phẩm hoặc bị Mercari chặn."

        return _build_item_embed(item, user_id)

    @staticmethod
    async def _reply_slash_cooldown(interaction: discord.Interaction, error) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        else:
            logger.error("Mercari slash error: %s", error)

    @staticmethod
    async def _reply_prefix_cooldown(ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.", delete_after=5)

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
        await self._reply_slash_cooldown(interaction, error)

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
        await self._reply_prefix_cooldown(ctx, error)


async def setup(bot: commands.Bot):
    await bot.add_cog(MercariCog(bot))
