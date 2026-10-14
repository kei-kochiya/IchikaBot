"""
Birthday Cog - Character birthday announcements for Project Sekai.
"""

import contextlib
import logging
from datetime import datetime, time, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.core import database
from utils.data.game_data import character_autocomplete, game_data
from utils.game.cards import CardToggleView, get_random_card, supports_trained_art

# Import our new helpers and UI components
from utils.social.birthday_helpers import (
    JST,
    build_birthday_calendar_embed,
    get_birthday_cards_for_character,
    get_characters_with_birthday,
    get_next_birthday,
)
from utils.social.birthday_ui import (
    BirthdayCardView,
    create_birthday_embed,
    create_countdown_embed,
    create_daily_card_embed,
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

    def load_data(self):
        """Deprecated: Data is now fetched directly via singletons in helpers."""
        logger.info("Birthday: Singleton refs are handled externally now.")

    async def load_settings(self):
        """Load all birthday channel settings from the database into memory."""
        try:
            rows = await database.get_all_settings("birthday_channel")
            self.settings = {str(gid): int(ch_id) for gid, ch_id in rows.items()}
        except Exception as e:
            logger.error(f"Birthday: Failed to load settings: {e}")
            self.settings = {}

    # --- Messaging Helpers ---
    async def send_birthday_message(self, channel, character: dict):
        """Send birthday message with year navigation buttons if multiple cards exist."""
        from utils.media.image_helper import get_card_image_path, get_character_trim_path

        cards = get_birthday_cards_for_character(character["id"])

        if len(cards) > 1:
            view = BirthdayCardView(character, cards, current_index=0)
            img_path = await get_card_image_path(cards[0]["assetbundleName"], is_trained=False)
            file = discord.File(img_path, filename="card.png") if img_path else None
            embed = view._create_embed(attachment_url="attachment://card.png" if file else None)
            if file:
                msg = await channel.send(embed=embed, file=file, view=view)
            else:
                msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            card = cards[0] if cards else None
            img_path = None
            if card:
                img_path = await get_card_image_path(card["assetbundleName"], is_trained=False)
            else:
                img_path = await get_character_trim_path(character["id"])

            file = discord.File(img_path, filename="card.png") if img_path else None
            attachment_url = "attachment://card.png" if file else None
            embed = create_birthday_embed(character, card, attachment_url=attachment_url)
            if file:
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

    async def send_countdown_message(self, channel, days_until: int, character: dict):
        """Send countdown message with card and toggle button."""
        from utils.data.card_data import card_data
        from utils.media.image_helper import get_card_image_path

        card = get_random_card(card_data.cards, character["id"], ["rarity_3", "rarity_4"])

        if not card:
            logger.warning(f"Birthday: No cards found for character {character['id']}")
            return

        is_trained = supports_trained_art(card)
        img_path = await get_card_image_path(card["assetbundleName"], is_trained=is_trained)
        file = discord.File(img_path, filename="card.png") if img_path else None
        attachment_url = "attachment://card.png" if file else None

        embed = create_countdown_embed(days_until, character, card, attachment_url=attachment_url)

        if is_trained:
            view = CardToggleView(embed, card, default_trained=True)
            if file:
                msg = await channel.send(embed=embed, file=file, view=view)
            else:
                msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            if file:
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

    async def send_daily_card_message(self, channel, character: dict, days_until_bday: int):
        """Send daily card message with countdown and toggle button."""
        from utils.data.card_data import card_data
        from utils.media.image_helper import get_card_image_path

        card = get_random_card(card_data.cards, character["id"], ["rarity_3", "rarity_4"])

        if not card:
            logger.warning(f"Birthday: No 3/4 star cards found for character {character['id']}")
            return

        is_trained = supports_trained_art(card)
        img_path = await get_card_image_path(card["assetbundleName"], is_trained=is_trained)
        file = discord.File(img_path, filename="card.png") if img_path else None
        attachment_url = "attachment://card.png" if file else None

        embed = create_daily_card_embed(
            character, card, days_until_bday, attachment_url=attachment_url
        )

        if is_trained:
            view = CardToggleView(embed, card, default_trained=True)
            if file:
                msg = await channel.send(embed=embed, file=file, view=view)
            else:
                msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            if file:
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

    # --- Scheduled Task ---
    @tasks.loop(time=time(hour=0, minute=0, tzinfo=JST))
    async def birthday_check_task(self):
        """Daily birthday and card announcement at 12:00 AM JST."""
        now = datetime.now(JST)
        today = now.strftime("%m-%d")
        logger.info(f"Birthday: Daily check on {today}")

        birthday_chars = get_characters_with_birthday(today)

        for guild_id_str, channel_id in self.settings.items():
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    continue

                if birthday_chars:
                    logger.info(f"Birthday: Sending {len(birthday_chars)} birthday announcement(s)")
                    for char in birthday_chars:
                        await self.send_birthday_message(channel, char)
                    continue

                next_bday = get_next_birthday()
                if not next_bday:
                    logger.warning("Birthday: No upcoming birthdays found")
                    continue

                days_until, char = next_bday
                logger.info(
                    f"Birthday: Sending daily card for {char.get('id')} (birthday in {days_until} days)"
                )
                await self.send_daily_card_message(channel, char, days_until)

            except Exception as e:
                logger.error(f"Birthday: Failed to send to guild {guild_id_str}: {e}")

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

        next_bday = get_next_birthday()
        if not next_bday:
            await interaction.followup.send("No upcoming birthdays found.")
            return

        days_until, char = next_bday
        from utils.data.game_data import get_character_name

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
        from utils.media.image_helper import get_card_image_path, get_character_trim_path

        await interaction.response.defer()

        char_data = game_data.characters.get(character)
        if not char_data:
            # Try searching by name or unit
            char_id, found_data = game_data.get_character_by_name(character)
            if char_id:
                character = str(char_id)
                char_data = found_data

        if not char_data:
            await interaction.followup.send("Không tìm thấy nhân vật.", ephemeral=True)
            return

        char_with_id = {**char_data, "id": character}
        cards = get_birthday_cards_for_character(character)

        if len(cards) > 1:
            view = BirthdayCardView(char_with_id, cards, current_index=0)
            img_path = await get_card_image_path(cards[0]["assetbundleName"], is_trained=False)
            file = discord.File(img_path, filename="card.png") if img_path else None
            embed = view._create_embed(attachment_url="attachment://card.png" if file else None)
            if file:
                msg = await interaction.followup.send(
                    "**📋 Xem trước thông báo sinh nhật:**", embed=embed, file=file, view=view
                )
            else:
                msg = await interaction.followup.send(
                    "**📋 Xem trước thông báo sinh nhật:**", embed=embed, view=view
                )
            view.message = msg
        else:
            card = cards[0] if cards else None
            img_path = None
            if card:
                img_path = await get_card_image_path(card["assetbundleName"], is_trained=False)
            else:
                img_path = await get_character_trim_path(character)

            file = discord.File(img_path, filename="card.png") if img_path else None
            attachment_url = "attachment://card.png" if file else None
            embed = create_birthday_embed(char_with_id, card, attachment_url=attachment_url)
            if file:
                await interaction.followup.send(
                    "**📋 Xem trước thông báo sinh nhật:**", embed=embed, file=file
                )
            else:
                await interaction.followup.send(
                    "**📋 Xem trước thông báo sinh nhật:**", embed=embed
                )

    @birthday_group.command(name="countdown", description="Xem đếm ngược sinh nhật kèm card")
    @app_commands.describe(character="Chọn nhân vật hoặc để trống cho sinh nhật gần nhất")
    @app_commands.autocomplete(character=char_autocomplete)
    async def countdown_slash(self, interaction: discord.Interaction, character: str = None):
        await interaction.response.defer()
        target_char = None
        days_until = None

        if character:
            char_data = game_data.characters.get(character)
            if not char_data:
                cid, found_data = game_data.get_character_by_name(character)
                if cid:
                    character = str(cid)
                    char_data = found_data
            if char_data:
                target_char = {**char_data, "id": character}
                # Calculate days until this character's birthday
                now = datetime.now(JST)
                for days_ahead in range(0, 366):
                    d_str = (now + timedelta(days=days_ahead)).strftime("%m-%d")
                    if char_data.get("birthday") == d_str:
                        days_until = days_ahead
                        break

        if not target_char or days_until is None:
            next_bday = get_next_birthday()
            if not next_bday:
                await interaction.followup.send("Không tìm thấy thông tin sinh nhật sắp tới.")
                return
            days_until, target_char = next_bday

        await self.send_daily_card_message(interaction.channel, target_char, days_until)

    @birthday_group.command(name="check", description="Xem sinh nhật hôm nay và sắp tới")
    async def check_birthday_slash(self, interaction: discord.Interaction):
        now = datetime.now(JST)
        today = now.strftime("%m-%d")
        from utils.social.birthday_helpers import get_upcoming_birthdays

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
        from utils.social.birthday_helpers import get_upcoming_birthdays

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
        target_char = None
        days_until = None

        if character:
            char_data = game_data.characters.get(character)
            if not char_data:
                cid, found_data = game_data.get_character_by_name(character)
                if cid:
                    character = str(cid)
                    char_data = found_data
            if char_data:
                target_char = {**char_data, "id": character}
                now = datetime.now(JST)
                for days_ahead in range(0, 366):
                    d_str = (now + timedelta(days=days_ahead)).strftime("%m-%d")
                    if char_data.get("birthday") == d_str:
                        days_until = days_ahead
                        break

        if not target_char or days_until is None:
            next_bday = get_next_birthday()
            if not next_bday:
                await ctx.send("Không tìm thấy thông tin sinh nhật sắp tới.")
                return
            days_until, target_char = next_bday

        await self.send_daily_card_message(ctx.channel, target_char, days_until)


async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))
