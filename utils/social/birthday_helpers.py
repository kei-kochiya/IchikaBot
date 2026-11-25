from datetime import date, datetime, timedelta, timezone

import discord

from utils.data.card_data import card_data
from utils.data.game_data import game_data

JST = timezone(timedelta(hours=9))


def _days_until_mm_dd(mm_dd: str, today: date, min_days: int = 0) -> int | None:
    """Return days from *today* until the next occurrence of MM-DD (>= min_days)."""
    try:
        month, day = map(int, mm_dd.split("-", 1))
    except (ValueError, AttributeError):
        return None

    for offset in range(5):
        year = today.year + offset
        try:
            target = date(year, month, day)
        except ValueError:
            continue  # e.g. Feb 29 in a non-leap year
        delta = (target - today).days
        if delta >= min_days:
            return delta
    return None


def get_characters_with_birthday(date_str: str) -> list[dict]:
    """Get all characters whose birthday matches the given MM-DD string."""
    return [
        {**char, "id": char_id}
        for char_id, char in game_data.characters.items()
        if char.get("birthday") == date_str
    ]


def get_birthday_cards_for_character(char_id) -> list[dict]:
    """Get all birthday cards for a character, sorted by newest first."""
    char_id_int = int(char_id) if isinstance(char_id, str) else char_id
    matching_cards = [
        c
        for c in card_data.cards
        if c["characterId"] == char_id_int and c["cardRarityType"] == "rarity_birthday"
    ]
    # Sort by releaseAt descending (newest first), fallback to id
    matching_cards.sort(key=lambda c: (c.get("releaseAt", 0), c.get("id", 0)), reverse=True)
    return matching_cards


def get_birthday_card_for_character(char_id) -> dict | None:
    """Get the newest birthday card for a character."""
    cards = get_birthday_cards_for_character(char_id)
    return cards[0] if cards else None


def get_upcoming_birthdays(days: int = 7) -> list[tuple[int, dict]]:
    """Get characters with birthdays within the next N days, sorted by days."""
    today = datetime.now(JST).date()
    upcoming: list[tuple[int, int, dict]] = []

    for idx, (char_id, char) in enumerate(game_data.characters.items()):
        delta = _days_until_mm_dd(char.get("birthday", ""), today, min_days=1)
        if delta is not None and delta <= days:
            upcoming.append((delta, idx, {**char, "id": char_id}))

    upcoming.sort(key=lambda item: (item[0], item[1]))
    return [(delta, char) for delta, _, char in upcoming]


def get_next_birthday() -> tuple[int, dict] | None:
    """Get the character with the nearest upcoming birthday (within 365 days)."""
    today = datetime.now(JST).date()
    best: tuple[int, int, dict] | None = None

    for idx, (char_id, char) in enumerate(game_data.characters.items()):
        delta = _days_until_mm_dd(char.get("birthday", ""), today, min_days=1)
        if delta is None:
            continue
        candidate = (delta, idx, {**char, "id": char_id})
        if best is None or (delta, idx) < (best[0], best[1]):
            best = candidate

    return (best[0], best[2]) if best else None


def build_birthday_calendar_embed(
    today: str, birthday_chars: list, upcoming: list, discord_Color_class
) -> discord.Embed:
    """Helper logic to build the calendar embed content (to avoid duplicating code).
    Returns an embed to be sent by the cog.
    """
    from utils.data.game_data import get_character_name

    embed = discord.Embed(title="Lịch sinh nhật", color=discord_Color_class.purple())

    # Today section
    if birthday_chars:
        today_names = [f"**{get_character_name(c['id'], full=True)}**" for c in birthday_chars]
        embed.add_field(name="Hôm nay", value="\n".join(today_names), inline=False)
    else:
        embed.add_field(name="Hôm nay", value="Không có sinh nhật", inline=False)

    # Upcoming section
    if upcoming:
        upcoming_lines = []
        for days_until, char in upcoming[:10]:
            name = get_character_name(char["id"], full=True)
            date_str = char.get("birthday", "")
            if days_until == 1:
                upcoming_lines.append(f"**Ngày mai** · {name}")
            else:
                upcoming_lines.append(f"**{days_until} ngày nữa** ({date_str}) · {name}")

        if len(upcoming) > 10:
            upcoming_lines.append(f"*...và {len(upcoming) - 10} sinh nhật khác*")

        embed.add_field(name="Sắp tới (30 ngày)", value="\n".join(upcoming_lines), inline=False)
    else:
        embed.add_field(name="Sắp tới", value="Không có sinh nhật trong 30 ngày tới", inline=False)

    embed.set_footer(text=f"Ngày hiện tại: {today} (JST)")
    return embed


def resolve_character_and_countdown(
    character_query: str | None = None,
) -> tuple[int, dict] | None:
    """Resolve character and days until birthday.

    If character_query is provided, looks up by ID or name and calculates days until next birthday.
    If omitted or not found, falls back to the nearest upcoming birthday.
    """
    if character_query:
        if character_query.isascii() and character_query.isdigit():
            cid = int(character_query)
            target_char = game_data.get_character(cid)
        else:
            cid, target_char = game_data.get_character_by_name(character_query)

        if target_char and cid is not None:
            delta = _days_until_mm_dd(
                target_char.get("birthday", ""), datetime.now(JST).date(), min_days=0
            )
            if delta is not None:
                return (delta, {**target_char, "id": str(cid)})
    return get_next_birthday()
