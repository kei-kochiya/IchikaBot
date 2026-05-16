"""
Birthday Cog - Character birthday announcements for Project Sekai.
"""
import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
from datetime import datetime, time, timezone, timedelta

from utils.card_data import card_data
from utils.game_data import (
    game_data, get_character_name, get_unit_color, character_autocomplete
)
from utils.cards import get_card_image_url, get_random_card, CardToggleView, supports_trained_art
from utils import database

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

UNIT_NAMES = {
    'leo_need': 'Leo/need',
    'more_more_jump': 'MORE MORE JUMP!',
    'vivid_bad_squad': 'Vivid BAD SQUAD',
    'wonderlands_showtime': "Wonderlands × Showtime",
    'nightcord_at_2500': 'Nightcord at 25:00',
    'virtual_singer': 'VIRTUAL SINGER'
}


class BirthdayCardView(discord.ui.View):
    """View with year navigation buttons for birthday cards."""
    
    def __init__(self, character: dict, cards: list[dict], current_index: int = 0):
        super().__init__(timeout=180)
        self.character = character
        self.cards = cards  # Sorted newest first
        self.current_index = current_index
        self.update_buttons()
    
    def update_buttons(self):
        # Clear existing buttons
        self.clear_items()
        
        # Previous (older) button
        prev_btn = discord.ui.Button(
            label="Older",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_index >= len(self.cards) - 1,
            custom_id="birthday_prev"
        )
        prev_btn.callback = self.prev_callback
        self.add_item(prev_btn)
        
        # Year indicator
        year_label = discord.ui.Button(
            label=f"{self.current_index + 1}/{len(self.cards)}",
            style=discord.ButtonStyle.primary,
            disabled=True,
            custom_id="birthday_indicator"
        )
        self.add_item(year_label)
        
        # Next (newer) button
        next_btn = discord.ui.Button(
            label="Newer",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_index <= 0,
            custom_id="birthday_next"
        )
        next_btn.callback = self.next_callback
        self.add_item(next_btn)
    
    async def prev_callback(self, interaction: discord.Interaction):
        self.current_index = min(self.current_index + 1, len(self.cards) - 1)
        self.update_buttons()
        embed = self._create_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def next_callback(self, interaction: discord.Interaction):
        self.current_index = max(self.current_index - 1, 0)
        self.update_buttons()
        embed = self._create_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    def _create_embed(self) -> discord.Embed:
        card = self.cards[self.current_index]
        full_name = get_character_name(self.character['id'], full=True)
        char_id = self.character.get('id')
        unit = self.character.get('unit', 'virtual_singer')
        unit_display = UNIT_NAMES.get(unit, unit)
        
        # Extract year from releaseAt timestamp
        release_ts = card.get('releaseAt', 0)
        if release_ts:
            release_year = datetime.fromtimestamp(release_ts / 1000, tz=JST).year
        else:
            release_year = "???"
        
        embed = discord.Embed(
            title=f"Happy Birthday, {full_name}!",
            description=f"Hôm nay là sinh nhật của **{full_name}** từ **{unit_display}**!\n\n"
                        f"Hãy cùng chúc mừng sinh nhật nào!",
            color=get_unit_color(char_id)
        )
        embed.add_field(name="Unit", value=unit_display, inline=True)
        embed.add_field(name="Birthday", value=self.character.get('birthday', 'Unknown'), inline=True)
        embed.add_field(name="Card Year", value=str(release_year), inline=True)
        
        card_url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{card['assetbundleName']}/card_normal.png"
        embed.set_image(url=card_url)
        embed.set_footer(text=card.get('prefix', 'Birthday Card'))
        embed.timestamp = datetime.now(JST)
        
        return embed
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass



class BirthdayCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.characters = game_data.characters  # shared ref, no copy
        self.cards = card_data.cards            # shared ref, no copy
        self.settings = {}

    async def cog_load(self):
        await self.load_settings()
        self.birthday_check_task.start()
        logger.info("Birthday: Started scheduled task.")

    async def cog_unload(self):
        self.birthday_check_task.cancel()

    def load_data(self):
        """Refresh references after card_data/game_data reload."""
        self.characters = game_data.characters
        self.cards = card_data.cards
        logger.info("Birthday: Refreshed shared singleton refs.")

    async def load_settings(self):
        """Load all birthday channel settings from the database into memory."""
        try:
            rows = await database.get_all_settings('birthday_channel')
            # Store as {guild_id_str: channel_id} to preserve existing access patterns
            self.settings = {str(gid): int(ch_id) for gid, ch_id in rows.items()}
        except Exception as e:
            logger.error(f"Birthday: Failed to load settings: {e}")
            self.settings = {}

    async def save_settings(self):
        """Deprecated — settings are now written directly in set/delete helpers."""
        pass

    def get_characters_with_birthday(self, date_str: str) -> list:
        birthday_chars = []
        for char_id, char in self.characters.items():
            if char.get('birthday') == date_str:
                birthday_chars.append({**char, 'id': char_id})
        return birthday_chars

    def get_birthday_cards_for_character(self, char_id) -> list[dict]:
        """Get all birthday cards for a character, sorted by newest first (highest ID/releaseAt)."""
        char_id_int = int(char_id) if isinstance(char_id, str) else char_id
        matching_cards = [
            c for c in self.cards 
            if c['characterId'] == char_id_int and c['cardRarityType'] == 'rarity_birthday'
        ]
        # Sort by releaseAt descending (newest first), fallback to id
        matching_cards.sort(key=lambda c: (c.get('releaseAt', 0), c.get('id', 0)), reverse=True)
        return matching_cards

    def get_birthday_card_for_character(self, char_id) -> dict | None:
        """Get the newest birthday card for a character (kept for compatibility)."""
        cards = self.get_birthday_cards_for_character(char_id)
        return cards[0] if cards else None

    def create_birthday_embed(self, character: dict, card: dict = None) -> discord.Embed:
        """Create birthday embed with optional specific card."""
        full_name = get_character_name(character['id'], full=True)
        char_id = character.get('id')
        unit = character.get('unit', 'virtual_singer')
        unit_display = UNIT_NAMES.get(unit, unit)
        
        embed = discord.Embed(
            title=f"Happy Birthday, {full_name}!",
            description=f"Hôm nay là sinh nhật của **{full_name}** từ **{unit_display}**!\n\n"
                        f"Hãy cùng chúc mừng sinh nhật nào!",
            color=get_unit_color(char_id)
        )
        embed.add_field(name="Unit", value=unit_display, inline=True)
        embed.add_field(name="Birthday", value=character.get('birthday', 'Unknown'), inline=True)
        
        # Use provided card or get newest
        if card is None:
            card = self.get_birthday_card_for_character(char_id)
        
        if card:
            # Add year field
            release_ts = card.get('releaseAt', 0)
            if release_ts:
                release_year = datetime.fromtimestamp(release_ts / 1000, tz=JST).year
                embed.add_field(name="Card Year", value=str(release_year), inline=True)
            
            card_url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{card['assetbundleName']}/card_normal.png"
            embed.set_image(url=card_url)
            embed.set_footer(text=card.get('prefix', 'Birthday Card'))
        else:
            # Fallback to character trim if no birthday card found
            embed.set_image(
                url=f"https://storage.sekai.best/sekai-jp-assets/character/character_trim/chr_trim_{char_id}.webp"
            )
            embed.set_footer(text="Project Sekai Birthday Announcement")
        
        embed.timestamp = datetime.now(JST)
        return embed

    async def send_birthday_message(self, channel, character: dict):
        """Send birthday message with year navigation buttons if multiple cards exist."""
        cards = self.get_birthday_cards_for_character(character['id'])
        
        if len(cards) > 1:
            # Multiple cards - add navigation buttons
            view = BirthdayCardView(character, cards, current_index=0)
            embed = view._create_embed()
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            # Single or no cards - send without buttons
            embed = self.create_birthday_embed(character, cards[0] if cards else None)
            await channel.send(embed=embed)

    def get_upcoming_birthdays(self, days: int = 7) -> list[tuple[int, dict]]:
        """Get characters with birthdays within the next N days.
        Returns list of (days_until, character_dict) tuples, sorted by days.
        """
        today = datetime.now(JST)
        upcoming = []
        
        for i in range(1, days + 1):
            future_date = today + timedelta(days=i)
            date_str = future_date.strftime('%m-%d')
            chars = self.get_characters_with_birthday(date_str)
            for char in chars:
                upcoming.append((i, char))
        
        return upcoming

    def get_random_card_for_character(self, char_id, rarity: list[str] = None) -> dict | None:
        """Get a random card for a character, optionally filtered by rarity."""
        if rarity is None:
            rarity = ['rarity_3', 'rarity_4']  # Default to 3/4 star
        return get_random_card(self.cards, char_id, rarity)

    def get_next_birthday(self) -> tuple[int, dict] | None:
        """Get the character with the nearest upcoming birthday (within 365 days)."""
        today = datetime.now(JST)
        
        for days_ahead in range(1, 366):
            future_date = today + timedelta(days=days_ahead)
            date_str = future_date.strftime('%m-%d')
            chars = self.get_characters_with_birthday(date_str)
            if chars:
                return (days_ahead, chars[0])
        return None



    def create_countdown_embed(self, days_until: int, character: dict, card: dict) -> discord.Embed:
        """Create a countdown embed for an upcoming birthday with card image."""
        full_name = get_character_name(character['id'], full=True)
        char_id = character.get('id')
        unit = character.get('unit', 'virtual_singer')
        unit_display = UNIT_NAMES.get(unit, unit)
        
        if days_until == 1:
            countdown_text = "**Ngày mai**"
            title = f"Ngày mai là sinh nhật của {full_name}!"
        else:
            countdown_text = f"**{days_until} ngày**"
            title = f"Còn {days_until} ngày nữa là sinh nhật của {full_name}!"
        
        embed = discord.Embed(
            title=title,
            description=f"Đừng quên chúc mừng sinh nhật **{full_name}** từ **{unit_display}** nhé!",
            color=get_unit_color(char_id)
        )
        embed.add_field(name="Countdown", value=countdown_text, inline=True)
        embed.add_field(name="Birthday", value=character.get('birthday', 'Unknown'), inline=True)
        
        # Use card image (default trained for 3/4 star)
        is_trained = supports_trained_art(card)
        card_url = get_card_image_url(card['assetbundleName'], trained=is_trained)
        
        embed.set_image(url=card_url)
        embed.set_footer(text=card.get('prefix', 'Card'))
        embed.timestamp = datetime.now(JST)
        return embed

    async def send_countdown_message(self, channel, days_until: int, character: dict):
        """Send countdown message with card and toggle button."""
        card = self.get_random_card_for_character(character['id'])
        
        if not card:
            logger.warning(f"Birthday: No cards found for character {character['id']}")
            return
        
        embed = self.create_countdown_embed(days_until, character, card)
        
        # Add view with toggle button if 3/4 star
        if supports_trained_art(card):
            view = CardToggleView(embed, card, default_trained=True)
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            await channel.send(embed=embed)

    def create_daily_card_embed(self, character: dict, card: dict, days_until_bday: int) -> discord.Embed:
        """Create daily card embed with birthday countdown."""
        full_name = get_character_name(character['id'], full=True)
        char_id = character.get('id')
        unit = character.get('unit', 'virtual_singer')
        unit_display = UNIT_NAMES.get(unit, unit)
        
        # Countdown text
        if days_until_bday == 1:
            countdown_text = "**Ngày mai** là sinh nhật!"
        elif days_until_bday <= 7:
            countdown_text = f"Còn **{days_until_bday} ngày** nữa là sinh nhật!"
        else:
            countdown_text = f"Sinh nhật: còn **{days_until_bday} ngày**"
        
        embed = discord.Embed(
            title=f"Daily Card: {full_name}",
            description=f"**{unit_display}**\n\n{countdown_text}",
            color=get_unit_color(char_id)
        )
        embed.add_field(name="Birthday", value=character.get('birthday', 'Unknown'), inline=True)
        
        # Use trained art for 3/4 star
        is_trained = supports_trained_art(card)
        card_url = get_card_image_url(card['assetbundleName'], trained=is_trained)
        
        embed.set_image(url=card_url)
        embed.set_footer(text=card.get('prefix', 'Card'))
        embed.timestamp = datetime.now(JST)
        return embed

    async def send_daily_card_message(self, channel, character: dict, days_until_bday: int):
        """Send daily card message with countdown and toggle button."""
        card = self.get_random_card_for_character(character['id'])
        
        if not card:
            logger.warning(f"Birthday: No 3/4 star cards found for character {character['id']}")
            return
        
        embed = self.create_daily_card_embed(character, card, days_until_bday)
        
        # Add view with toggle button if 3/4 star
        if supports_trained_art(card):
            view = CardToggleView(embed, card, default_trained=True)
            msg = await channel.send(embed=embed, view=view)
            view.message = msg
        else:
            await channel.send(embed=embed)

    @tasks.loop(time=time(hour=0, minute=0, tzinfo=JST))
    async def birthday_check_task(self):
        """Daily birthday and card announcement at 12:00 AM JST."""
        now = datetime.now(JST)
        today = now.strftime('%m-%d')
        logger.info(f"Birthday: Daily check on {today}")
        
        # Get today's birthdays
        birthday_chars = self.get_characters_with_birthday(today)
        
        for guild_id_str, channel_id in self.settings.items():
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    continue
                
                # CASE 1: Birthday today - send birthday cards only
                if birthday_chars:
                    logger.info(f"Birthday: Sending {len(birthday_chars)} birthday announcement(s)")
                    for char in birthday_chars:
                        await self.send_birthday_message(channel, char)
                    continue  # Don't send daily card on birthday
                
                # CASE 2: No birthday today - show card from nearest upcoming birthday character
                next_bday = self.get_next_birthday()
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
        """Manually trigger the daily card logic for testing."""
        await interaction.response.defer()
        
        now = datetime.now(JST)
        today = now.strftime('%m-%d')
        
        # Get today's birthdays
        birthday_chars = self.get_characters_with_birthday(today)
        
        if birthday_chars:
            # Birthday today
            await interaction.followup.send(f"Today is birthday! Sending {len(birthday_chars)} announcement(s)...")
            for char in birthday_chars:
                await self.send_birthday_message(interaction.channel, char)
            return
        
        # No birthday today - show card from nearest upcoming birthday character
        next_bday = self.get_next_birthday()
        if not next_bday:
            await interaction.followup.send("No upcoming birthdays found.")
            return
        
        days_until, char = next_bday
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
        char_data = self.characters.get(character)
        if not char_data:
            await interaction.response.send_message("Không tìm thấy nhân vật.", ephemeral=True)
            return
        
        char_with_id = {**char_data, 'id': character}
        cards = self.get_birthday_cards_for_character(character)
        
        if len(cards) > 1:
            # Multiple cards - show with navigation buttons
            view = BirthdayCardView(char_with_id, cards, current_index=0)
            embed = view._create_embed()
            await interaction.response.send_message("**📋 Xem trước thông báo sinh nhật:**", embed=embed, view=view)
        else:
            # Single or no cards - show without buttons
            embed = self.create_birthday_embed(char_with_id, cards[0] if cards else None)
            await interaction.response.send_message("**📋 Xem trước thông báo sinh nhật:**", embed=embed)

    @birthday_group.command(name="check", description="Xem sinh nhật hôm nay và sắp tới")
    async def check_birthday_slash(self, interaction: discord.Interaction):
        now = datetime.now(JST)
        today = now.strftime('%m-%d')
        
        # Get today's birthdays
        birthday_chars = self.get_characters_with_birthday(today)
        
        # Get upcoming birthdays (30 days)
        upcoming = self.get_upcoming_birthdays(days=30)
        
        # Build embed
        embed = discord.Embed(
            title="Lịch sinh nhật",
            color=discord.Color.purple()
        )
        
        # Today section
        if birthday_chars:
            today_names = [f"**{get_character_name(c['id'], full=True)}**" for c in birthday_chars]
            embed.add_field(
                name="🎉 Hôm nay!",
                value='\n'.join(today_names),
                inline=False
            )
        else:
            embed.add_field(
                name="Hôm nay",
                value="Không có sinh nhật",
                inline=False
            )
        
        # Upcoming section
        if upcoming:
            upcoming_lines = []
            for days_until, char in upcoming[:10]:
                name = get_character_name(char['id'], full=True)
                date_str = char.get('birthday', '')
                if days_until == 1:
                    upcoming_lines.append(f"⏰ **Ngày mai** - {name}")
                else:
                    upcoming_lines.append(f"📌 **{days_until} ngày** ({date_str}) - {name}")
            
            if len(upcoming) > 10:
                upcoming_lines.append(f"*...và {len(upcoming) - 10} sinh nhật khác*")
            
            embed.add_field(
                name="📆 Sắp tới (30 ngày)",
                value='\n'.join(upcoming_lines),
                inline=False
            )
        else:
            embed.add_field(
                name="Sắp tới",
                value="Không có sinh nhật trong 30 ngày tới",
                inline=False
            )
        
        embed.set_footer(text=f"Ngày hiện tại: {today} (JST)")
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
        
        # Get today's birthdays
        birthday_chars = self.get_characters_with_birthday(today)
        
        # Get upcoming birthdays (30 days)
        upcoming = self.get_upcoming_birthdays(days=30)
        
        # Build embed
        embed = discord.Embed(
            title="Lịch sinh nhật",
            color=discord.Color.purple()
        )
        
        # Today section
        if birthday_chars:
            today_names = [f"**{get_character_name(c['id'], full=True)}**" for c in birthday_chars]
            embed.add_field(
                name="🎉 Hôm nay!",
                value='\n'.join(today_names),
                inline=False
            )
        else:
            embed.add_field(
                name="Hôm nay",
                value="Không có sinh nhật",
                inline=False
            )
        
        # Upcoming section
        if upcoming:
            upcoming_lines = []
            for days_until, char in upcoming[:10]:
                name = get_character_name(char['id'], full=True)
                date_str = char.get('birthday', '')
                if days_until == 1:
                    upcoming_lines.append(f"**Ngày mai** - {name}")
                else:
                    upcoming_lines.append(f"**{days_until} ngày** ({date_str}) - {name}")
            
            if len(upcoming) > 10:
                upcoming_lines.append(f"*...và {len(upcoming) - 10} sinh nhật khác*")
            
            embed.add_field(
                name="📆 Sắp tới (30 ngày)",
                value='\n'.join(upcoming_lines),
                inline=False
            )
        else:
            embed.add_field(
                name="Sắp tới",
                value="Không có sinh nhật trong 30 ngày tới",
                inline=False
            )
        
        embed.set_footer(text=f"Ngày hiện tại: {today} (JST)")
        embed.timestamp = now
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))