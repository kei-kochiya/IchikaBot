import asyncio
import contextlib
import random
from datetime import datetime

import discord

from utils.data.game_data import get_character_name, get_unit_color
from utils.game.cards import (
    get_card_image_url,
    is_pre_trained_card,
    supports_trained_art,
    update_card_attachment_message,
)
from utils.social.birthday_helpers import JST, get_birthday_card_for_character

UNIT_NAMES = {
    "leo_need": "Leo/need",
    "more_more_jump": "MORE MORE JUMP!",
    "vivid_bad_squad": "Vivid BAD SQUAD",
    "wonderlands_showtime": "Wonderlands × Showtime",
    "nightcord_at_2500": "Nightcord at 25:00",
    "virtual_singer": "VIRTUAL SINGER",
}


def create_birthday_embed(
    character: dict, card: dict | None = None, attachment_url: str | None = None
) -> discord.Embed:
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

        card_url = attachment_url or get_card_image_url(card["assetbundleName"], trained=False)
        embed.set_image(url=card_url)
        embed.set_footer(text=card.get("prefix", "Birthday Card"))
    else:
        # Fallback to character trim if no birthday card found
        trim_url = (
            attachment_url
            or f"https://storage.sekai.best/sekai-jp-assets/character/character_trim/chr_trim_{char_id}.webp"
        )
        embed.set_image(url=trim_url)
        embed.set_footer(text="Project Sekai Birthday Announcement")

    embed.timestamp = datetime.now(JST)
    return embed


def create_daily_card_embed(
    character: dict, card: dict, days_until_bday: int, attachment_url: str | None = None
) -> discord.Embed:
    """Create daily card embed with birthday countdown."""
    full_name = get_character_name(character["id"], full=True)
    char_id = character.get("id")
    unit = character.get("unit", "virtual_singer")
    unit_display = UNIT_NAMES.get(unit, unit)

    # Countdown text
    if days_until_bday == 0:
        countdown_text = "**Hôm nay** là sinh nhật!"
    elif days_until_bday == 1:
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

    # Use trained art for 3/4 star or pre-trained cards
    is_trained = supports_trained_art(card) or is_pre_trained_card(card)
    card_url = attachment_url or get_card_image_url(card["assetbundleName"], trained=is_trained)

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
        self.message = None
        self._lock = asyncio.Lock()

        self._prev_btn = discord.ui.Button(
            label="Older",
            style=discord.ButtonStyle.secondary,
            custom_id="birthday_prev",
        )
        self._prev_btn.callback = self.prev_callback
        self._year_label = discord.ui.Button(
            label=f"{self.current_index + 1}/{len(self.cards)}",
            style=discord.ButtonStyle.primary,
            disabled=True,
            custom_id="birthday_indicator",
        )
        self._next_btn = discord.ui.Button(
            label="Newer",
            style=discord.ButtonStyle.secondary,
            custom_id="birthday_next",
        )
        self._next_btn.callback = self.next_callback
        self.add_item(self._prev_btn)
        self.add_item(self._year_label)
        self.add_item(self._next_btn)
        self.update_buttons()

    def update_buttons(self):
        # Mutate existing button attributes in place so live ViewStore items stay attached
        self._prev_btn.disabled = self.current_index >= len(self.cards) - 1
        self._year_label.label = f"{self.current_index + 1}/{len(self.cards)}"
        self._next_btn.disabled = self.current_index <= 0

    async def _step(self, interaction: discord.Interaction, delta: int) -> None:
        from utils.media.image_helper import get_card_image_path

        if not interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.defer()

        async with self._lock:
            prev_index = self.current_index
            self.current_index = max(0, min(self.current_index + delta, len(self.cards) - 1))
            self.update_buttons()
            card = self.cards[self.current_index]

            ok = await update_card_attachment_message(
                interaction=interaction,
                fetch_image=get_card_image_path,
                asset_bundle=card["assetbundleName"],
                is_trained=False,
                build_embed=lambda url, c=card: create_birthday_embed(
                    self.character,
                    c,
                    attachment_url=url if url.startswith("attachment://") else None,
                ),
                fallback_url=get_card_image_url(card["assetbundleName"], trained=False),
                view=self,
            )
            if not ok:
                self.current_index = prev_index
                self.update_buttons()

    async def prev_callback(self, interaction: discord.Interaction):
        await self._step(interaction, +1)

    async def next_callback(self, interaction: discord.Interaction):
        await self._step(interaction, -1)

    def _create_embed(self, attachment_url: str | None = None) -> discord.Embed:
        return create_birthday_embed(
            self.character, self.cards[self.current_index], attachment_url=attachment_url
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, "message") and self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


async def prepare_birthday_message(
    character: dict,
) -> tuple[discord.Embed, discord.File | None, discord.ui.View | None]:
    """Prepare embed, cached card image file, and view (if multiple cards) for a birthday announcement."""
    from utils.media.image_helper import get_card_image_path, get_character_trim_path
    from utils.social.birthday_helpers import get_birthday_cards_for_character

    cards = get_birthday_cards_for_character(character["id"])
    if len(cards) > 1:
        view = BirthdayCardView(character, cards, current_index=0)
        img_path = await get_card_image_path(cards[0]["assetbundleName"], is_trained=False)
        file = discord.File(img_path, filename="card.webp") if img_path else None
        embed = view._create_embed(attachment_url="attachment://card.webp" if file else None)
        return embed, file, view

    card = cards[0] if cards else None
    if card:
        img_path = await get_card_image_path(card["assetbundleName"], is_trained=False)
    else:
        img_path = await get_character_trim_path(character["id"])

    file = discord.File(img_path, filename="card.webp") if img_path else None
    attachment_url = "attachment://card.webp" if file else None
    embed = create_birthday_embed(character, card, attachment_url=attachment_url)
    return embed, file, None


async def prepare_daily_card_message(
    character: dict, days_until_bday: int
) -> tuple[discord.Embed | None, discord.File | None, discord.ui.View | None]:
    """Prepare embed, cached card image file, and toggle view for a countdown daily card announcement."""
    from utils.data.card_data import card_data
    from utils.game.cards import CardToggleView, get_random_card
    from utils.media.image_helper import get_card_image_path

    char_pool = card_data.by_char_3_4.get(int(character["id"]))
    card = (
        random.choice(char_pool)
        if char_pool
        else get_random_card(card_data.cards, character["id"], ["rarity_3", "rarity_4"])
    )
    if not card:
        return None, None, None

    can_toggle = supports_trained_art(card)
    is_trained = can_toggle or is_pre_trained_card(card)
    img_path = await get_card_image_path(card["assetbundleName"], is_trained=is_trained)
    file = discord.File(img_path, filename="card.webp") if img_path else None
    attachment_url = "attachment://card.webp" if file else None

    embed = create_daily_card_embed(character, card, days_until_bday, attachment_url=attachment_url)
    view = CardToggleView(embed, card, default_trained=is_trained) if can_toggle else None
    return embed, file, view
