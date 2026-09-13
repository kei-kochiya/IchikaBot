"""
Birthday Cog - Character birthday announcements for Project Sekai.
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
from datetime import datetime, time

from utils.data.game_data import game_data, character_autocomplete
from utils.game.cards import get_random_card, CardToggleView, supports_trained_art
from utils.core import database

# Import our new helpers and UI components
from utils.social.birthday_helpers import (
    JST,
    get_characters_with_birthday,
    get_birthday_cards_for_character,
    get_next_birthday,
    build_birthday_calendar_embed
)
from utils.social.birthday_ui import (
    create_birthday_embed,
    create_countdown_embed,
    create_daily_card_embed,
    BirthdayCardView
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
            rows = await database.get_all_settings('birthday_channel')
            self.settings = {str(gid): int(ch_id) for gid, ch_id in rows.items()}
        except Exception as e:
            logger.error(f"Birthday: Failed to load settings: {e}")
            self.settings = {}

    # --- Messaging Helpers ---
    async def send_birthday_message(self, channel, character: dict):
        """Send birthday message with year navigation buttons if multiple cards exist."""
        cards = get_birthday_cards_for_character(character['id'])
        
        if len(cards) > 1:
            view = BirthdayCardView(character, cards, current_index=0)
            embed = view._create_embed()
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            embed = create_birthday_embed(character, cards[0] if cards else None)
            await channel.send(embed=embed)

    async def send_countdown_message(self, channel, days_until: int, character: dict):
        """Send countdown message with card and toggle button."""
        from utils.data.card_data import card_data
        card = get_random_card(card_data.cards, character['id'], ['rarity_3', 'rarity_4'])
        
        if not card:
            logger.warning(f"Birthday: No cards found for character {character['id']}")
            return
        
        embed = create_countdown_embed(days_until, character, card)
        
        if supports_trained_art(card):
            view = CardToggleView(embed, card, default_trained=True)
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            await channel.send(embed=embed)

    async def send_daily_card_message(self, channel, character: dict, days_until_bday: int):
        """Send daily card message with countdown and toggle button."""
        from utils.data.card_data import card_data
        card = get_random_card(card_data.cards, character['id'], ['rarity_3', 'rarity_4'])
        
        if not card:
            logger.warning(f"Birthday: No 3/4 star cards found for character {character['id']}")
            return
        
        embed = create_daily_card_embed(character, card, days_until_bday)
        
        if supports_trained_art(card):
            view = CardToggleView(embed, card, default_trained=True)
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            await channel.send(embed=embed)

    # --- Scheduled Task ---
    @tasks.loop(time=time(hour=0, minute=0, tzinfo=JST))
    async def birthday_check_task(self):
        """Daily birthday and card announcement at 12:00 AM JST."""
        now = datetime.now(JST)
        today = now.strftime('%m-%d')
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
                logger.info(f"Birthday: Sending daily card for {char.get('id')} (birthday in {days_until} days)")
                await self.send_daily_card_message(channel, char, days_until)
                        
            except Exception as e:
                logger.error(f"Birthday: Failed to send to guild {guild_id_str}: {e}")

    @birthday_check_task.before_loop
    async def before_birthday_check(self):
        await self.bot.wait_until_ready()

    @birthday_check_task.error
    async def on_birthday_check_error(self, error: Exception):
        logger.error("BirthdayCog: Exception in background loop: %s", error, exc_info=True)

    # --- Autocomplete ---
    async def char_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
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
        await database.set_setting(interaction.guild_id, 'birthday_channel', str(channel.id))
        embed = discord.Embed(
            title="Đã cài đặt thành công!",
            description=f"Thông báo sinh nhật sẽ được gửi đến {channel.mention}\n\n"
                        f"Thông báo sẽ được gửi vào **00:00 JST** hàng ngày.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @birthday_group.command(name="test_daily", description="Test daily card announcement (Admin)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def test_daily(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        now = datetime.now(JST)
        today = now.strftime('%m-%d')
        birthday_chars = get_characters_with_birthday(today)
        
        if birthday_chars:
            await interaction.followup.send(f"Today is birthday! Sending {len(birthday_chars)} announcement(s)...")
            for char in birthday_chars:
                await self.send_birthday_message(interaction.channel, char)
            return
        
        next_bday = get_next_birthday()
        if not next_bday:
            await interaction.followup.send("No upcoming birthdays found.")
            return
        
        days_until, char = next_bday
        from utils.data.game_data import get_character_name
        full_name = get_character_name(char['id'], full=True)
        await interaction.followup.send(f"Next birthday: {full_name} in {days_until} day(s)")
        await self.send_daily_card_message(interaction.channel, char, days_until)

    @birthday_group.command(name="disable", description="Tắt thông báo sinh nhật")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable_birthday(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if guild_id in self.settings:
            del self.settings[guild_id]
            await database.delete_setting(interaction.guild_id, 'birthday_channel')
            await interaction.response.send_message("Đã tắt thông báo sinh nhật.", ephemeral=True)
        else:
            await interaction.response.send_message("Chưa bật thông báo sinh nhật.", ephemeral=True)

    @birthday_group.command(name="test", description="Xem trước thông báo sinh nhật")
    @app_commands.describe(character="Chọn nhân vật để xem thông báo")
    @app_commands.autocomplete(character=char_autocomplete)
    async def test_birthday(self, interaction: discord.Interaction, character: str):
        char_data = game_data.characters.get(character)
        if not char_data:
            await interaction.response.send_message("Không tìm thấy nhân vật.", ephemeral=True)
            return
        
        char_with_id = {**char_data, 'id': character}
        cards = get_birthday_cards_for_character(character)
        
        if len(cards) > 1:
            view = BirthdayCardView(char_with_id, cards, current_index=0)
            embed = view._create_embed()
            await interaction.response.send_message("**📋 Xem trước thông báo sinh nhật:**", embed=embed, view=view)
        else:
            embed = create_birthday_embed(char_with_id, cards[0] if cards else None)
            await interaction.response.send_message("**📋 Xem trước thông báo sinh nhật:**", embed=embed)

    @birthday_group.command(name="check", description="Xem sinh nhật hôm nay và sắp tới")
    async def check_birthday_slash(self, interaction: discord.Interaction):
        now = datetime.now(JST)
        today = now.strftime('%m-%d')
        from utils.social.birthday_helpers import get_upcoming_birthdays
        
        embed = build_birthday_calendar_embed(
            today,
            get_characters_with_birthday(today),
            get_upcoming_birthdays(days=30),
            discord.Color
        )
        embed.timestamp = now
        await interaction.response.send_message(embed=embed)

    @set_channel.error
    @disable_birthday.error
    async def birthday_admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Bạn cần quyền **Manage Server** để sử dụng lệnh này.",
                ephemeral=True
            )

    # ===== PREFIX COMMANDS =====
    @commands.command(name='bday', aliases=['birthday', 'bdaycheck'])
    async def bday_check_prefix(self, ctx: commands.Context):
        """Check today's and upcoming birthdays: !bday"""
        now = datetime.now(JST)
        today = now.strftime('%m-%d')
        from utils.social.birthday_helpers import get_upcoming_birthdays
        
        embed = build_birthday_calendar_embed(
            today,
            get_characters_with_birthday(today),
            get_upcoming_birthdays(days=30),
            discord.Color
        )
        embed.timestamp = now
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))