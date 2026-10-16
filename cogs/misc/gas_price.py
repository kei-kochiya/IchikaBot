"""
Gas Price Cog - Fetch and display current retail fuel prices from Petrolimex.

Source: https://www.pvoil.com.vn/tin-gia-xang-dau (data sourced via Petrolimex CMS API,
which is the same underlying price data published by all Vietnamese fuel retailers).
Cooldown: 10 seconds per user to avoid hammering the upstream API.
Cache: Lazy daily cache — if cache is from today, use cached data; if from another date
or missing, pull from API and save new cache.
"""

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import BASE_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_CACHE_FILE = BASE_DIR / "gas_price_cache.json"
_VN_TZ = timezone(timedelta(hours=7))

# Petrolimex CMS API — discovered from the portals.petrolimex.com.vn JS bundle.
# The endpoint is unauthenticated and returns live retail price objects.
_API_URL = "https://portals.petrolimex.com.vn/~apis/portals/cms.item/search"
_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.petrolimex.com.vn",
    "Referer": "https://www.petrolimex.com.vn/",
}
_API_FILTER = {
    "FilterBy": {
        "And": [
            {"SystemID": {"Equals": "6783dc1271ff449e95b74a9520964169"}},
            {"RepositoryID": {"Equals": "a95451e23b474fe5886bfb7cf843f53c"}},
            {"RepositoryEntityID": {"Equals": "3801378fe1e045b1afa10de7c5776124"}},
            {"Status": {"Equals": "Published"}},
        ]
    },
    "SortBy": {"DIsplayOrder": "Ascending"},
    "Pagination": {"TotalRecords": -1, "TotalPages": 0, "PageSize": 0, "PageNumber": 0},
}

# Pre-encode the static filter once at import time
_X_REQUEST = (
    base64.urlsafe_b64encode(json.dumps(_API_FILTER, separators=(",", ":")).encode())
    .decode()
    .rstrip("=")
)


# ---------------------------------------------------------------------------
# Cache Helpers
# ---------------------------------------------------------------------------


def _get_current_vn_date() -> str:
    """Return the current date in Vietnam time (UTC+7) in YYYY-MM-DD format."""
    return datetime.now(_VN_TZ).strftime("%Y-%m-%d")


def _load_cache(file_path: Path | str = _CACHE_FILE) -> dict | None:
    """Read the cached prices from file if present and valid."""
    path = Path(file_path)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "date" in data and "products" in data:
            return data
    except Exception as exc:
        logger.warning("GasPrice: Failed to read cache file %s: %s", path, exc)
    return None


def _save_cache(data: dict, file_path: Path | str = _CACHE_FILE) -> None:
    """Persist price cache to disk."""
    path = Path(file_path)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("GasPrice: Failed to save cache file %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Upstream API & Embed
# ---------------------------------------------------------------------------


async def fetch_prices(session: aiohttp.ClientSession) -> list[dict]:
    """Return a list of price objects sorted by DIsplayOrder ascending."""
    async with session.get(
        _API_URL,
        params={"x-request": _X_REQUEST},
        headers=_API_HEADERS,
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    objects = data.get("Objects", [])
    return sorted(objects, key=lambda o: int(o.get("DIsplayOrder") or 99))


def _build_embed(products: list[dict]) -> discord.Embed:
    """Build a Discord embed from the list of price products."""
    updated_times = [
        datetime.fromisoformat(o["LastModified"].rstrip("Z")).replace(tzinfo=UTC).astimezone(_VN_TZ)
        for o in products
        if o.get("LastModified")
    ]
    last_update = max(updated_times) if updated_times else None

    embed = discord.Embed(
        title="⛽ Giá xăng dầu bán lẻ",
        url="https://www.pvoil.com.vn/tin-gia-xang-dau",
        color=discord.Color.orange(),
    )

    for product in products:
        name = product.get("Title") or product.get("EnglishTitle") or "?"
        z1 = product.get("Zone1Price")
        z2 = product.get("Zone2Price")
        value = (
            f"Vùng 1: **{z1:,} đ**\nVùng 2: **{z2:,} đ**"
            if z1 is not None and z2 is not None
            else "Không có dữ liệu"
        )
        embed.add_field(name=name, value=value, inline=True)

    if last_update:
        embed.set_footer(
            text=f"Kỳ điều hành: {last_update.strftime('%d/%m/%Y %H:%M')} (GMT+7) • Nguồn: Petrolimex"
        )
    else:
        embed.set_footer(text="Nguồn: Petrolimex")

    return embed


class GasPriceCog(commands.Cog):
    """Slash and prefix command to show current Vietnamese fuel retail prices."""

    def __init__(self, bot: commands.Bot, cache_file: Path | str = _CACHE_FILE) -> None:
        self.bot = bot
        self.cache_file = Path(cache_file)
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict | None = None
        self._lock = asyncio.Lock()

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession()
        self._cache = _load_cache(self.cache_file)

    async def cog_unload(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_prices(self, session: aiohttp.ClientSession) -> list[dict]:
        """Fetch fuel prices from upstream, delegating to module-level fetch_prices."""
        return await fetch_prices(session)

    # ------------------------------------------------------------------
    # Shared fetch + embed logic with daily caching
    # ------------------------------------------------------------------

    async def _price_embed(self) -> discord.Embed | str:
        today_str = _get_current_vn_date()

        # Fast path: in-memory cache hit for today
        if self._cache and self._cache.get("date") == today_str and self._cache.get("products"):
            return _build_embed(self._cache["products"])

        async with self._lock:
            # Re-check under lock
            if self._cache and self._cache.get("date") == today_str and self._cache.get("products"):
                return _build_embed(self._cache["products"])

            # Check persistent disk cache
            disk_cache = _load_cache(self.cache_file)
            if disk_cache and disk_cache.get("date") == today_str and disk_cache.get("products"):
                self._cache = disk_cache
                return _build_embed(disk_cache["products"])

            # Stale or missing cache -> pull fresh data from API
            if self._session is None:
                self._session = aiohttp.ClientSession()

            try:
                products = await self.fetch_prices(self._session)
            except aiohttp.ClientResponseError as exc:
                logger.error("GasPrice: HTTP error %s from upstream API", exc.status)
                fallback = self._cache or disk_cache
                if fallback and fallback.get("products"):
                    return _build_embed(fallback["products"])
                return f"❌ Không thể lấy dữ liệu (HTTP {exc.status}). Thử lại sau nhé."
            except Exception as exc:
                logger.error("GasPrice: Unexpected error: %s", exc, exc_info=True)
                fallback = self._cache or disk_cache
                if fallback and fallback.get("products"):
                    return _build_embed(fallback["products"])
                return "❌ Đã xảy ra lỗi khi lấy giá xăng dầu."

            if not products:
                fallback = self._cache or disk_cache
                if fallback and fallback.get("products"):
                    return _build_embed(fallback["products"])
                return "⚠️ Không tìm thấy dữ liệu giá."

            # Save new cache
            new_cache = {
                "date": today_str,
                "products": products,
            }
            self._cache = new_cache
            _save_cache(new_cache, self.cache_file)

            return _build_embed(products)

    # ------------------------------------------------------------------
    # Slash command
    # ------------------------------------------------------------------

    @app_commands.command(name="gasprice", description="Xem giá xăng dầu bán lẻ hiện tại")
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def slash_gasprice(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        result = await self._price_embed()
        if isinstance(result, str):
            await interaction.followup.send(result, ephemeral=True)
        else:
            await interaction.followup.send(embed=result)

    @slash_gasprice.error
    async def slash_gasprice_error(self, interaction: discord.Interaction, error) -> None:
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
            logger.error("GasPrice slash error: %s", error)

    # ------------------------------------------------------------------
    # Prefix command
    # ------------------------------------------------------------------

    @commands.command(name="gasprice", aliases=["gas", "xangdau", "xăngdầu"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def prefix_gasprice(self, ctx: commands.Context) -> None:
        async with ctx.typing():
            result = await self._price_embed()
        if isinstance(result, str):
            await ctx.send(result)
        else:
            await ctx.send(embed=result)

    @prefix_gasprice.error
    async def prefix_gasprice_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"Chờ **{error.retry_after:.1f}s** trước khi dùng lại.",
                delete_after=5,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GasPriceCog(bot))
