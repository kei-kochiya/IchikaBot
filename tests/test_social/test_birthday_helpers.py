import pytest
import discord
from utils.social.birthday_helpers import (
    get_characters_with_birthday,
    get_birthday_cards_for_character,
    get_upcoming_birthdays,
    get_next_birthday,
    build_birthday_calendar_embed,
)


def test_get_characters_with_birthday():
    # Ichika's birthday is August 11 (08-11)
    chars = get_characters_with_birthday("08-11")
    assert len(chars) >= 1
    assert any(c.get("firstName") == "Ichika" or c.get("givenName") == "Hoshino" for c in chars)

    # Empty on non-existent day or invalid format
    assert get_characters_with_birthday("99-99") == []


def test_get_birthday_cards_for_character():
    # Character 1 (Ichika) has birthday cards
    cards = get_birthday_cards_for_character(1)
    assert isinstance(cards, list)
    for c in cards:
        assert c["characterId"] == 1
        assert c["cardRarityType"] == "rarity_birthday"


def test_upcoming_and_next_birthdays():
    upcoming = get_upcoming_birthdays(days=365)
    assert len(upcoming) >= 20

    next_bday = get_next_birthday()
    assert next_bday is not None
    days_ahead, char = next_bday
    assert 1 <= days_ahead <= 365
    assert "id" in char


def test_build_birthday_calendar_embed():
    embed = build_birthday_calendar_embed(
        today="08-11",
        birthday_chars=[{"id": 1, "givenName": "Ichika"}],
        upcoming=[(5, {"id": 2, "givenName": "Saki", "birthday": "08-16"})],
        discord_Color_class=discord.Color
    )
    assert isinstance(embed, discord.Embed)
    assert len(embed.fields) >= 2
