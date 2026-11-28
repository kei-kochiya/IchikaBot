"""Character birthday announcements and countdown cog for Project Sekai."""

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
        self._last_post_dates: dict[str, str] = {}  # guild_id_str -> YYYY-MM-DD (JST)

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
            dates = await database.get_all_settings("birthday_last_post_date")
            self._last_post_dates = {str(gid): val for gid, val in dates.items()}
        except Exception as e:
            logger.error("Birthday: Failed to load settings: %s", e)
            self.settings = {}
            self._last_post_dates = {}

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

    async def send_daily_card_message(self, target, character: dict, days_until_bday: int) -> bool:
        """Send daily card message with countdown and toggle button. False if the character
        has no 3/4★ card to show (nothing is sent then)."""
        embed, file, view = await prepare_daily_card_message(character, days_until_bday)
        if not embed:
            logger.warning(
                "Birthday: No 3/4 star cards found for character %s", character.get("id")
            )
            return False

        kwargs = {"embed": embed}
        if file:
            kwargs["file"] = file
        if view:
            kwargs["view"] = view

        msg = await target.send(**kwargs)
        if view:
            view.message = msg
        return True

    async def _run_daily_announcements(self, *, catch_up_only: bool = False) -> None:
        now = datetime.now(JST)
        today = now.strftime("%m-%d")
        today_iso = now.strftime("%Y-%m-%d")
        logger.info("Birthday: Daily check on %s (catch_up=%s)", today, catch_up_only)

        birthday_chars = get_characters_with_birthday(today)
        countdown_res = None if birthday_chars else resolve_character_and_countdown(None)

        # A copy: /birthday channel or disable may change settings while this loop awaits
        for guild_id_str, channel_id in list(self.settings.items()):
            last_date = self._last_post_dates.get(guild_id_str)
            if last_date == today_iso:
                continue  # Already posted today
            if catch_up_only and (last_date is None or last_date >= today_iso):
                continue

            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    continue

                if birthday_chars:
                    logger.info(
                        "Birthday: Sending %d birthday announcement(s) to guild %s",
                        len(birthday_chars),
                        guild_id_str,
                    )
                    for char in birthday_chars:
                        await self.send_birthday_message(channel, char)
                else:
                    if not countdown_res:
                        logger.warning("Birthday: No upcoming birthdays found")
                        continue
                    days_until, char = countdown_res
                    logger.info(
                        "Birthday: Sending daily card for %s (birthday in %d days)",
                        char.get("id"),
                        days_until,
                    )
                    await self.send_daily_card_message(channel, char, days_until)

                if guild_id_str in self.settings:
                    self._last_post_dates[guild_id_str] = today_iso
                    await database.set_setting(
                        int(guild_id_str), "birthday_last_post_date", today_iso
                    )
            except Exception as e:
                logger.error("Birthday: Failed to send to guild %s: %s", guild_id_str, e)

    # --- Scheduled Task ---
    @tasks.loop(time=time(hour=0, minute=0, tzinfo=JST))
    async def birthday_check_task(self):
        """Daily birthday and card announcement at 12:00 AM JST."""
        await self._run_daily_announcements(catch_up_only=False)

    @birthday_check_task.before_loop
    async def before_birthday_check(self):
        with contextlib.suppress(RuntimeError):
            await self.bot.wait_until_ready()
        # Catch up any guild whose restart/outage spanned 00:00 JST
        await self._run_daily_announcements(catch_up_only=True)

    @birthday_check_task.error
    async def on_birthday_check_error(self, error: Exception):
        logger.error("BirthdayCog: Exception in background loop: %s", error, exc_info=True)

    async def _require_bot_guild(self, interaction: discord.Interaction) -> bool:
        """Ensure the command runs in a guild where the bot itself is installed."""
        is_guild_install = getattr(interaction, "is_guild_integration", None)
        not_guild_bot = (
            interaction.guild_id is None
            or (callable(is_guild_install) and not is_guild_install())
            or (self.bot.is_ready() and self.bot.get_guild(interaction.guild_id) is None)
        )
        if not_guild_bot:
            msg = "Lệnh này chỉ dùng được trong server có bot tham gia."
            with contextlib.suppress(discord.HTTPException):
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    # --- Autocomplete ---
    async def char_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return character_autocomplete(current, max_id=26)

    # ===== SLASH COMMANDS =====
    birthday_group = app_commands.Group(name="birthday", description="Quản lý thông báo sinh nhật")

    @birthday_group.command(name="channel", description="Đặt kênh thông báo sinh nhật")
    @app_commands.describe(channel="Kênh để gửi thông báo sinh nhật")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._require_bot_guild(interaction):
            return
        guild_id = str(interaction.guild_id)
        self.settings[guild_id] = channel.id
        to_save = {"birthday_channel": str(channel.id)}
        if guild_id not in self._last_post_dates:
            today_iso = datetime.now(JST).strftime("%Y-%m-%d")
            self._last_post_dates[guild_id] = today_iso
            to_save["birthday_last_post_date"] = today_iso
        await database.set_settings(interaction.guild_id, to_save)
        embed = discord.Embed(
            title="Đã cài đặt thành công!",
            description=f"Thông báo sinh nhật sẽ được gửi đến {channel.mention}\n\n"
            f"Thông báo sẽ được gửi vào **00:00 JST** hàng ngày.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @birthday_group.command(name="test_daily", description="Test daily card announcement (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_daily(self, interaction: discord.Interaction):
        if not await self._require_bot_guild(interaction):
            return
        await interaction.response.defer()

        now = datetime.now(JST)
        today = now.strftime("%m-%d")
        birthday_chars = get_characters_with_birthday(today)

        if birthday_chars:
            await interaction.followup.send(
                f"Hôm nay có sinh nhật: đang gửi {len(birthday_chars)} thông báo."
            )
            for char in birthday_chars:
                await self.send_birthday_message(interaction.followup, char)
            return

        res = resolve_character_and_countdown(None)
        if not res:
            await interaction.followup.send("Không tìm thấy sinh nhật sắp tới.")
            return

        days_until, char = res
        full_name = get_character_name(char["id"], full=True)
        await interaction.followup.send(f"Sinh nhật tiếp theo: {full_name}, còn {days_until} ngày.")
        await self.send_daily_card_message(interaction.followup, char, days_until)

    @birthday_group.command(name="disable", description="Tắt thông báo sinh nhật")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable_birthday(self, interaction: discord.Interaction):
        if not await self._require_bot_guild(interaction):
            return
        guild_id = str(interaction.guild_id)
        if guild_id in self.settings:
            del self.settings[guild_id]
            self._last_post_dates.pop(guild_id, None)
            await database.delete_settings(
                interaction.guild_id, ("birthday_channel", "birthday_last_post_date")
            )
            await interaction.response.send_message("Đã tắt thông báo sinh nhật.", ephemeral=True)
        else:
            await interaction.response.send_message("Chưa bật thông báo sinh nhật.", ephemeral=True)

    @birthday_group.command(name="test", description="Xem trước thông báo sinh nhật")
    @app_commands.describe(character="Chọn nhân vật để xem thông báo")
    @app_commands.autocomplete(character=char_autocomplete)
    async def test_birthday(self, interaction: discord.Interaction, character: str):
        await interaction.response.defer()

        if character.isascii() and character.isdigit():
            cid = int(character)
            char_data = game_data.get_character(cid)
        else:
            cid, char_data = game_data.get_character_by_name(character)

        if not char_data or cid is None:
            await interaction.followup.send("Không tìm thấy nhân vật.", ephemeral=True)
            return

        target_char = {**char_data, "id": str(cid)}
        # Through the followup: it answers the deferred interaction (channel.send left it
        # "thinking" forever) and also works in DMs and user-installed contexts
        await self.send_birthday_message(
            interaction.followup,
            target_char,
            prefix_content="**Xem trước thông báo sinh nhật**",
        )

    @birthday_group.command(name="countdown", description="Xem đếm ngược sinh nhật kèm card")
    @app_commands.describe(character="Chọn nhân vật hoặc để trống cho sinh nhật gần nhất")
    @app_commands.autocomplete(character=char_autocomplete)
    async def countdown_slash(self, interaction: discord.Interaction, character: str | None = None):
        await interaction.response.defer()
        res = resolve_character_and_countdown(character)
        if not res:
            await interaction.followup.send("Không tìm thấy thông tin sinh nhật sắp tới.")
            return

        days_until, target_char = res
        if not await self.send_daily_card_message(interaction.followup, target_char, days_until):
            await interaction.followup.send("Nhân vật này chưa có card 3★ hoặc 4★ nào.")

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
            msg = (
                "Lệnh này chỉ dùng được trong server có bot tham gia."
                if interaction.guild_id is None
                else "Bạn cần quyền **Manage Server** để sử dụng lệnh này."
            )
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))
