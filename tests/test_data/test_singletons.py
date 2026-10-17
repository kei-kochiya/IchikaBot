from utils.data.card_data import card_data
from utils.data.event_data import event_data
from utils.data.game_data import (
    character_autocomplete,
    game_data,
    get_character_name,
    get_unit_color,
)
from utils.data.song_data import song_data


def test_game_data_singleton():
    assert len(game_data.characters) >= 26
    assert len(game_data.profiles) >= 26
    assert len(game_data.unit_colors) >= 26

    # Test helpers
    name = get_character_name(1, full=True)
    assert name != "Character 1"
    assert len(name) > 0

    color = get_unit_color(1)
    assert isinstance(color, int)
    assert color > 0

    choices = character_autocomplete("ichi")
    assert len(choices) >= 1
    assert any("Ichika" in c.name or "一歌" in c.name for c in choices)


def test_card_data_singleton(tmp_path):
    assert len(card_data.cards) >= 1
    assert len(card_data.pool_2) >= 1
    assert len(card_data.pool_3) >= 1
    assert len(card_data.pool_4) >= 1

    sample_card = card_data.cards[0]
    prefix = card_data.get_display_prefix(sample_card)
    assert isinstance(prefix, str)

    # Verify that heavy nested tables were excluded to save RAM
    assert "cardParameters" not in sample_card
    assert "specialTrainingCosts" not in sample_card
    assert "masterLessonAchieveResources" not in sample_card

    # Test fallback on minified single-line json
    minified_file = tmp_path / "minified.json"
    minified_file.write_text(
        '[{"id": 9999, "cardRarityType": "rarity_4", "prefix": "Test", "cardParameters": [1, 2]}]',
        encoding="utf-8",
    )
    res = card_data._stream_cards(minified_file, excluded_keys={"cardParameters"})
    assert len(res) == 1
    assert res[0]["id"] == 9999
    assert "cardParameters" not in res[0]


def test_event_data_singleton():
    assert len(event_data.events_jp) >= 1
    curr = event_data.get_current_event()
    assert curr is not None
    assert "id" in curr

    past = event_data.get_past_events(5)
    assert isinstance(past, list)

    search_res = event_data.search_events("Stella")
    assert isinstance(search_res, list)


def test_song_data_singleton():
    assert len(song_data.songs_jp) >= 1
    assert len(song_data.difficulties) >= 1

    random_song = song_data.get_random_song()
    assert random_song is not None
    assert "id" in random_song

    choices = song_data.get_autocomplete_choices("Tell Your World")
    assert len(choices) >= 1
