"""
Card of the Day Cog - Posts a random 3/4★ trained card at a configurable interval.
Admins can set the channel and interval (in hours) per guild.
"""

import logging
import random
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.core import database
from utils.data.card_data import card_data
from utils.data.game_data import get_character_name, get_unit_color
from utils.game.cards import CardToggleView, get_card_image_url

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_HOURS = 1
MIN_INTERVAL_HOURS = 0.5
MAX_INTERVAL_HOURS = 24


class CardOfDayCog(commands.Cog):
    """Posts a random 3/4★ card at a configurable interval per guild."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = {}  # guild_id_str -> {channel_id, interval_hours, last_post_ts}

    async def cog_load(self):
        await self.load_settings()
        self.card_loop.start()
        logger.info("CardOfDay: Started with %d guilds configured.", len(self.settings))

    async def cog_unload(self):
        self.card_loop.cancel()

    # --- Data loading ---

    def load_data(self):
        """Card pool comes from shared card_data singleton — nothing to load."""
        pass

    # --- Settings persistence ---

    async def load_settings(self):
        """Load all cotd guild configs from the database into memory."""
        try:
            rows = await database.get_all_settings_prefix("cotd_")
            # Rebuild the in-memory dict: {guild_id_str: {channel_id, interval_hours, last_post_ts}}
            self.settings = {}
            for gid, kv in rows.items():
                cfg: dict = {}
                if "channel_id" in kv:
                    cfg["channel_id"] = int(kv["channel_id"])
                if "interval_hours" in kv:
                    cfg["interval_hours"] = float(kv["interval_hours"])
                if "last_post_ts" in kv:
                    cfg["last_post_ts"] = float(kv["last_post_ts"])
                if cfg:
                    self.settings[str(gid)] = cfg
        except Exception as e:
            logger.error("CardOfDay: Failed to load settings: %s", e)
            self.settings = {}

    async def save_settings(self):
        """Deprecated — DB writes happen directly in the command handlers."""
        pass

    async def _save_guild_cfg(self, guild_id: int, cfg: dict) -> None:
        """Persist a single guild's cotd config to the DB."""
        for key, val in cfg.items():
            await database.set_setting(guild_id, f"cotd_{key}", str(val))

    # --- Helpers ---

    def get_display_prefix(self, card: dict) -> str:
        return card_data.get_display_prefix(card)

    def create_card_embed(self, card: dict) -> discord.Embed:
        """Create a Card of the Day embed (trained art by default)."""
        char_id = card["characterId"]
        char_name = get_character_name(char_id, full=True)
        rarity = f"{card['cardRarityType'][-1]}⭐"
        display_name = self.get_display_prefix(card)

        embed = discord.Embed(
            title="Card of the Day",
            description=f"**{display_name}**\n{rarity} — {char_name}",
            color=get_unit_color(char_id),
        )
        embed.set_image(url=get_card_image_url(card["assetbundleName"], trained=True))
        embed.set_footer(text=f"ID: {card['id']}")
        embed.timestamp = datetime.now(UTC)
        return embed

    # --- Loop ---

    @tasks.loop(minutes=1)
    async def card_loop(self):
        """Check every minute if any guild is due for a new card."""
        if not card_data.pool_3_4:
            return

        now_ts = datetime.now(UTC).timestamp()

        for guild_id_str, cfg in list(self.settings.items()):
            channel_id = cfg.get("channel_id")
            interval_hours = cfg.get("interval_hours", DEFAULT_INTERVAL_HOURS)
            last_post = cfg.get("last_post_ts", 0)

            if now_ts - last_post < interval_hours * 3600:
                continue  # Not time yet

            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                continue

            try:
                card = random.choice(card_data.pool_3_4)
                embed = self.create_card_embed(card)
                view = CardToggleView(embed, card, default_trained=True)
                msg = await channel.send(embed=embed, view=view)
                view.message = msg

                cfg["last_post_ts"] = now_ts
                await database.set_setting(int(guild_id_str), "cotd_last_post_ts", str(now_ts))
                logger.info("CardOfDay: Posted card %d in guild %s", card["id"], guild_id_str)
            except Exception as e:
                logger.error("CardOfDay: Failed to post in guild %s: %s", guild_id_str, e)

    @card_loop.before_loop
    async def before_card_loop(self):
        await self.bot.wait_until_ready()

    @card_loop.error
    async def on_card_loop_error(self, error: Exception):
        logger.error("CardOfDayCog: Exception in background loop: %s", error, exc_info=True)

    # --- Slash commands ---

    cotd_group = app_commands.Group(
        name="cotd",
        description="Card of the Day",
        guild_only=True,  # requires a guild: uses guild_id and manage_guild perms
    )

    @cotd_group.command(name="channel", description="Đặt kênh gửi Card of the Day")
    @app_commands.describe(channel="Kênh để gửi card")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = str(interaction.guild_id)
        if guild_id not in self.settings:
            self.settings[guild_id] = {
                "channel_id": channel.id,
                "interval_hours": DEFAULT_INTERVAL_HOURS,
                "last_post_ts": 0,
            }
        else:
            self.settings[guild_id]["channel_id"] = channel.id

        await self._save_guild_cfg(interaction.guild_id, self.settings[guild_id])
        interval = self.settings[guild_id]["interval_hours"]

        embed = discord.Embed(
            title="Card of the Day đã được cài đặt!",
            description=(
                f"Kênh: {channel.mention}\n"
                f"Tần suất: mỗi **{interval}** giờ\n\n"
                f"Dùng `/cotd interval` để thay đổi tần suất."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @cotd_group.command(name="interval", description="Đặt tần suất gửi card (giờ)")
    @app_commands.describe(hours="Số giờ giữa mỗi card (0.5 – 24)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_interval(self, interaction: discord.Interaction, hours: float):
        if hours < MIN_INTERVAL_HOURS or hours > MAX_INTERVAL_HOURS:
            await interaction.response.send_message(
                f"Tần suất phải từ **{MIN_INTERVAL_HOURS}** đến **{MAX_INTERVAL_HOURS}** giờ.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild_id)
        if guild_id not in self.settings:
            await interaction.response.send_message(
                "Chưa đặt kênh. Dùng `/cotd channel` trước.",
                ephemeral=True,
            )
            return

        self.settings[guild_id]["interval_hours"] = hours
        await self._save_guild_cfg(interaction.guild_id, self.settings[guild_id])

        await interaction.response.send_message(
            f"Tần suất đã cập nhật: mỗi **{hours}** giờ.",
            ephemeral=True,
        )

    @cotd_group.command(name="now", description="Gửi card ngay lập tức")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def send_now(self, interaction: discord.Interaction):
        if not card_data.pool_3_4:
            await interaction.response.send_message("Không có dữ liệu card.", ephemeral=True)
            return

        await interaction.response.defer()

        card = random.choice(card_data.pool_3_4)
        embed = self.create_card_embed(card)
        view = CardToggleView(embed, card, default_trained=True)
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

        # Reset timer so the next automatic post is a full interval away
        guild_id = str(interaction.guild_id)
        if guild_id in self.settings:
            self.settings[guild_id]["last_post_ts"] = datetime.now(UTC).timestamp()
            await self._save_guild_cfg(interaction.guild_id, self.settings[guild_id])

    @cotd_group.command(name="disable", description="Tắt Card of the Day")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if guild_id in self.settings:
            del self.settings[guild_id]
            for key in ("channel_id", "interval_hours", "last_post_ts"):
                await database.delete_setting(interaction.guild_id, f"cotd_{key}")
            await interaction.response.send_message("Đã tắt Card of the Day.", ephemeral=True)
        else:
            await interaction.response.send_message("Chưa bật Card of the Day.", ephemeral=True)

    @cotd_group.command(name="status", description="Xem cài đặt Card of the Day hiện tại")
    async def status(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        cfg = self.settings.get(guild_id)

        if not cfg:
            await interaction.response.send_message(
                "Card of the Day chưa được bật.", ephemeral=True
            )
            return

        channel = self.bot.get_channel(int(cfg["channel_id"]))
        channel_mention = channel.mention if channel else f"ID: {cfg['channel_id']}"
        interval = cfg.get("interval_hours", DEFAULT_INTERVAL_HOURS)
        last_ts = cfg.get("last_post_ts", 0)

        if last_ts > 0:
            next_ts = int(last_ts + interval * 3600)
            next_text = f"<t:{next_ts}:R>"
        else:
            next_text = "Sắp tới"

        embed = discord.Embed(
            title="Card of the Day — Trạng thái",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Kênh", value=channel_mention, inline=True)
        embed.add_field(name="Tần suất", value=f"Mỗi {interval} giờ", inline=True)
        embed.add_field(name="Lần tiếp theo", value=next_text, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Error handlers ---

    @set_channel.error
    @set_interval.error
    @send_now.error
    @disable.error
    async def cotd_admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Bạn cần quyền **Manage Server** để sử dụng lệnh này.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(CardOfDayCog(bot))
