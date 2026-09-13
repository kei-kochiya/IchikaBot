import contextlib
from datetime import datetime, timedelta, timezone

import discord

from utils.data.game_data import get_character_name, get_unit_color
from utils.game.cards import get_card_image_url, supports_trained_art
from utils.social.birthday_helpers import get_birthday_card_for_character

JST = timezone(timedelta(hours=9))

UNIT_NAMES = {
    "leo_need": "Leo/need",
    "more_more_jump": "MORE MORE JUMP!",
    "vivid_bad_squad": "Vivid BAD SQUAD",
    "wonderlands_showtime": "Wonderlands × Showtime",
    "nightcord_at_2500": "Nightcord at 25:00",
    "virtual_singer": "VIRTUAL SINGER",
}


def create_birthday_embed(character: dict, card: dict = None) -> discord.Embed:
    """Create birthday embed with optional specific card."""
    full_name = get_character_name(character["id"], full=True)
    char_id = character.get("id")
    unit = character.get("unit", "virtual_singer")
    unit_display = UNIT_NAMES.get(unit, unit)

    embed = discord.Embed(
        title=f"Happy Birthday, {full_name}!",
        description=f"Hôm nay là sinh nhật của **{full_name}** từ **{unit_display}**!\n\n"
        f"Hãy cùng chúc mừng sinh nhật nào!",
        color=get_unit_color(char_id),
    )
    embed.add_field(name="Unit", value=unit_display, inline=True)
    embed.add_field(name="Birthday", value=character.get("birthday", "Unknown"), inline=True)

    # Use provided card or get newest
    if card is None:
        card = get_birthday_card_for_character(char_id)

    if card:
        # Add year field
        release_ts = card.get("releaseAt", 0)
        if release_ts:
            release_year = datetime.fromtimestamp(release_ts / 1000, tz=JST).year
            embed.add_field(name="Card Year", value=str(release_year), inline=True)

        card_url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{card['assetbundleName']}/card_normal.png"
        embed.set_image(url=card_url)
        embed.set_footer(text=card.get("prefix", "Birthday Card"))
    else:
        # Fallback to character trim if no birthday card found
        embed.set_image(
            url=f"https://storage.sekai.best/sekai-jp-assets/character/character_trim/chr_trim_{char_id}.webp"
        )
        embed.set_footer(text="Project Sekai Birthday Announcement")

    embed.timestamp = datetime.now(JST)
    return embed


def create_countdown_embed(days_until: int, character: dict, card: dict) -> discord.Embed:
    """Create a countdown embed for an upcoming birthday with card image."""
    full_name = get_character_name(character["id"], full=True)
    char_id = character.get("id")
    unit = character.get("unit", "virtual_singer")
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
        color=get_unit_color(char_id),
    )
    embed.add_field(name="Countdown", value=countdown_text, inline=True)
    embed.add_field(name="Birthday", value=character.get("birthday", "Unknown"), inline=True)

    # Use card image (default trained for 3/4 star)
    is_trained = supports_trained_art(card)
    card_url = get_card_image_url(card["assetbundleName"], trained=is_trained)

    embed.set_image(url=card_url)
    embed.set_footer(text=card.get("prefix", "Card"))
    embed.timestamp = datetime.now(JST)
    return embed


def create_daily_card_embed(character: dict, card: dict, days_until_bday: int) -> discord.Embed:
    """Create daily card embed with birthday countdown."""
    full_name = get_character_name(character["id"], full=True)
    char_id = character.get("id")
    unit = character.get("unit", "virtual_singer")
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
        color=get_unit_color(char_id),
    )
    embed.add_field(name="Birthday", value=character.get("birthday", "Unknown"), inline=True)

    # Use trained art for 3/4 star
    is_trained = supports_trained_art(card)
    card_url = get_card_image_url(card["assetbundleName"], trained=is_trained)

    embed.set_image(url=card_url)
    embed.set_footer(text=card.get("prefix", "Card"))
    embed.timestamp = datetime.now(JST)
    return embed


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
            custom_id="birthday_prev",
        )
        prev_btn.callback = self.prev_callback
        self.add_item(prev_btn)

        # Year indicator
        year_label = discord.ui.Button(
            label=f"{self.current_index + 1}/{len(self.cards)}",
            style=discord.ButtonStyle.primary,
            disabled=True,
            custom_id="birthday_indicator",
        )
        self.add_item(year_label)

        # Next (newer) button
        next_btn = discord.ui.Button(
            label="Newer",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_index <= 0,
            custom_id="birthday_next",
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
        return create_birthday_embed(self.character, self.cards[self.current_index])

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, "message") and self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)
