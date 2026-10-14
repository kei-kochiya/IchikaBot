"""
Birthday Cog - Character birthday announcements for Project Sekai.
"""

import contextlib
import logging
from datetime import datetime, time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.core import database
from utils.data.game_data import character_autocomplete, game_data, get_character_name
from utils.social.birthday_helpers import (
    JST,
    build_birthday_calendar_embed,
    get_characters_with_birthday,
    get_upcoming_birthdays,
    resolve_character_and_countdown,
)
from utils.social.birthday_ui import (
    prepare_birthday_message,
    prepare_daily_card_message,
)

logger = logging.getLogger(__name__)


class BirthdayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = {}

    async def cog_load(self):
        await self.load_settings()
        self.birthday_check_task.start()
        logger.info("Birthday: Started scheduled task.")

    async def cog_unload(self):
        self.birthday_check_task.cancel()

    async def load_settings(self):
        """Load all birthday channel settings from the database into memory."""
        try:
            rows = await database.get_all_settings("birthday_channel")
            self.settings = {str(gid): int(ch_id) for gid, ch_id in rows.items()}
        except Exception as e:
            logger.error("Birthday: Failed to load settings: %s", e)
            self.settings = {}

    # --- Messaging Helpers ---
    async def send_birthday_message(
        self, target, character: dict, prefix_content: str | None = None
    ):
        """Send birthday message with year navigation buttons if multiple cards exist."""
        embed, file, view = await prepare_birthday_message(character)
        kwargs = {"embed": embed}
        if prefix_content:
            kwargs["content"] = prefix_content
        if file:
            kwargs["file"] = file
        if view:
            kwargs["view"] = view

        msg = await target.send(**kwargs)
        if view:
            view.message = msg

    async def send_daily_card_message(self, target, character: dict, days_until_bday: int):
        """Send daily card message with countdown and toggle button."""
        embed, file, view = await prepare_daily_card_message(character, days_until_bday)
        if not embed:
            logger.warning(
                "Birthday: No 3/4 star cards found for character %s", character.get("id")
            )
            return

        kwargs = {"embed": embed}
        if file:
            kwargs["file"] = file
        if view:
            kwargs["view"] = view

        msg = await target.send(**kwargs)
        if view:
            view.message = msg

    # --- Scheduled Task ---
    @tasks.loop(time=time(hour=0, minute=0, tzinfo=JST))
    async def birthday_check_task(self):
        """Daily birthday and card announcement at 12:00 AM JST."""
        now = datetime.now(JST)
        today = now.strftime("%m-%d")
        logger.info("Birthday: Daily check on %s", today)

        birthday_chars = get_characters_with_birthday(today)

        for guild_id_str, channel_id in self.settings.items():
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    continue

                if birthday_chars:
                    logger.info(
                        "Birthday: Sending %d birthday announcement(s)", len(birthday_chars)
                    )
                    for char in birthday_chars:
                        await self.send_birthday_message(channel, char)
                    continue

                res = resolve_character_and_countdown(None)
                if not res:
                    logger.warning("Birthday: No upcoming birthdays found")
                    continue

                days_until, char = res
                logger.info(
                    "Birthday: Sending daily card for %s (birthday in %d days)",
                    char.get("id"),
                    days_until,
                )
                await self.send_daily_card_message(channel, char, days_until)

            except Exception as e:
                logger.error("Birthday: Failed to send to guild %s: %s", guild_id_str, e)

    @birthday_check_task.before_loop
    async def before_birthday_check(self):
        with contextlib.suppress(RuntimeError):
            await self.bot.wait_until_ready()

    @birthday_check_task.error
    async def on_birthday_check_error(self, error: Exception):
        logger.error("BirthdayCog: Exception in background loop: %s", error, exc_info=True)

    # --- Autocomplete ---
    async def char_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return character_autocomplete(current, max_id=26)

    # ===== SLASH COMMANDS =====
    birthday_group = app_commands.Group(name="birthday", description="Quản lý thông báo sinh nhật")

    @birthday_group.command(name="channel", description="Đặt kênh thông báo sinh nhật")
    @app_commands.describe(channel="Kênh để gửi thông báo sinh nhật")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        guild_id = str(interaction.guild_id)
        self.settings[guild_id] = channel.id
        await database.set_setting(interaction.guild_id, "birthday_channel", str(channel.id))
        embed = discord.Embed(
            title="Đã cài đặt thành công!",
            description=f"Thông báo sinh nhật sẽ được gửi đến {channel.mention}\n\n"
            f"Thông báo sẽ được gửi vào **00:00 JST** hàng ngày.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @birthday_group.command(name="test_daily", description="Test daily card announcement (Admin)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def test_daily(self, interaction: discord.Interaction):
        await interaction.response.defer()

        now = datetime.now(JST)
        today = now.strftime("%m-%d")
        birthday_chars = get_characters_with_birthday(today)

        if birthday_chars:
            await interaction.followup.send(
                f"Today is birthday! Sending {len(birthday_chars)} announcement(s)..."
            )
            for char in birthday_chars:
                await self.send_birthday_message(interaction.channel, char)
            return

        res = resolve_character_and_countdown(None)
        if not res:
            await interaction.followup.send("No upcoming birthdays found.")
            return

        days_until, char = res
        full_name = get_character_name(char["id"], full=True)
        await interaction.followup.send(f"Next birthday: {full_name} in {days_until} day(s)")
        await self.send_daily_card_message(interaction.channel, char, days_until)

    @birthday_group.command(name="disable", description="Tắt thông báo sinh nhật")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable_birthday(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if guild_id in self.settings:
            del self.settings[guild_id]
            await database.delete_setting(interaction.guild_id, "birthday_channel")
            await interaction.response.send_message("Đã tắt thông báo sinh nhật.", ephemeral=True)
        else:
            await interaction.response.send_message("Chưa bật thông báo sinh nhật.", ephemeral=True)

    @birthday_group.command(name="test", description="Xem trước thông báo sinh nhật")
    @app_commands.describe(character="Chọn nhân vật để xem thông báo")
    @app_commands.autocomplete(character=char_autocomplete)
    async def test_birthday(self, interaction: discord.Interaction, character: str):
        await interaction.response.defer()

        if character.isdigit():
            cid = int(character)
            char_data = game_data.get_character(cid)
        else:
            cid, char_data = game_data.get_character_by_name(character)

        if not char_data or cid is None:
            await interaction.followup.send("Không tìm thấy nhân vật.", ephemeral=True)
            return

        target_char = {**char_data, "id": str(cid)}
        await self.send_birthday_message(
            interaction.channel,
            target_char,
            prefix_content="**📋 Xem trước thông báo sinh nhật:**",
        )

    @birthday_group.command(name="countdown", description="Xem đếm ngược sinh nhật kèm card")
    @app_commands.describe(character="Chọn nhân vật hoặc để trống cho sinh nhật gần nhất")
    @app_commands.autocomplete(character=char_autocomplete)
    async def countdown_slash(self, interaction: discord.Interaction, character: str = None):
        await interaction.response.defer()
        res = resolve_character_and_countdown(character)
        if not res:
            await interaction.followup.send("Không tìm thấy thông tin sinh nhật sắp tới.")
            return

        days_until, target_char = res
        await self.send_daily_card_message(interaction.channel, target_char, days_until)

    @birthday_group.command(name="check", description="Xem sinh nhật hôm nay và sắp tới")
    async def check_birthday_slash(self, interaction: discord.Interaction):
        now = datetime.now(JST)
        today = now.strftime("%m-%d")

        embed = build_birthday_calendar_embed(
            today,
            get_characters_with_birthday(today),
            get_upcoming_birthdays(days=30),
            discord.Color,
        )
        embed.timestamp = now
        await interaction.response.send_message(embed=embed)

    @set_channel.error
    @disable_birthday.error
    async def birthday_admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Bạn cần quyền **Manage Server** để sử dụng lệnh này.", ephemeral=True
            )

    # ===== PREFIX COMMANDS =====
    @commands.command(name="bday", aliases=["birthday", "bdaycheck"])
    async def bday_check_prefix(self, ctx: commands.Context):
        """Check today's and upcoming birthdays: !bday"""
        now = datetime.now(JST)
        today = now.strftime("%m-%d")

        embed = build_birthday_calendar_embed(
            today,
            get_characters_with_birthday(today),
            get_upcoming_birthdays(days=30),
            discord.Color,
        )
        embed.timestamp = now
        await ctx.send(embed=embed)

    @commands.command(name="bdayu", aliases=["countdown", "upcoming", "bdaycountdown"])
    async def bday_countdown_prefix(self, ctx: commands.Context, *, character: str = None):
        """Check upcoming birthday countdown with card: !bdayu [character]"""
        res = resolve_character_and_countdown(character)
        if not res:
            await ctx.send("Không tìm thấy thông tin sinh nhật sắp tới.")
            return

        days_until, target_char = res
        await self.send_daily_card_message(ctx.channel, target_char, days_until)


async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))
