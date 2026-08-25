from datetime import datetime, timedelta, timezone

from utils.data.card_data import card_data
from utils.data.game_data import game_data

JST = timezone(timedelta(hours=9))

def get_characters_with_birthday(date_str: str) -> list[dict]:
    """Get all characters whose birthday matches the given MM-DD string."""
    birthday_chars = []
    for char_id, char in game_data.characters.items():
        if char.get('birthday') == date_str:
            birthday_chars.append({**char, 'id': char_id})
    return birthday_chars

def get_birthday_cards_for_character(char_id) -> list[dict]:
    """Get all birthday cards for a character, sorted by newest first."""
    char_id_int = int(char_id) if isinstance(char_id, str) else char_id
    matching_cards = [
        c for c in card_data.cards 
        if c['characterId'] == char_id_int and c['cardRarityType'] == 'rarity_birthday'
    ]
    # Sort by releaseAt descending (newest first), fallback to id
    matching_cards.sort(key=lambda c: (c.get('releaseAt', 0), c.get('id', 0)), reverse=True)
    return matching_cards

def get_birthday_card_for_character(char_id) -> dict | None:
    """Get the newest birthday card for a character."""
    cards = get_birthday_cards_for_character(char_id)
    return cards[0] if cards else None

def get_upcoming_birthdays(days: int = 7) -> list[tuple[int, dict]]:
    """Get characters with birthdays within the next N days.
    Returns list of (days_until, character_dict) tuples, sorted by days.
    """
    today = datetime.now(JST)
    upcoming = []
    
    for i in range(1, days + 1):
        future_date = today + timedelta(days=i)
        date_str = future_date.strftime('%m-%d')
        chars = get_characters_with_birthday(date_str)
        for char in chars:
            upcoming.append((i, char))
    
    return upcoming

def get_next_birthday() -> tuple[int, dict] | None:
    """Get the character with the nearest upcoming birthday (within 365 days)."""
    today = datetime.now(JST)
    for days_ahead in range(1, 366):
        future_date = today + timedelta(days=days_ahead)
        date_str = future_date.strftime('%m-%d')
        chars = get_characters_with_birthday(date_str)
        if chars:
            return (days_ahead, chars[0])
    return None

def build_birthday_calendar_embed(today: str, birthday_chars: list, upcoming: list, discord_Color_class) -> "discord.Embed":
    """Helper logic to build the calendar embed content (to avoid duplicating code).
    Returns an embed to be sent by the cog.
    """
    from utils.data.game_data import get_character_name
    import discord

    embed = discord.Embed(
        title="Lịch sinh nhật",
        color=discord_Color_class.purple()
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
    return embed
