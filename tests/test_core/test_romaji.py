from utils.core.romaji import (
    hiragana_to_romaji,
    katakana_to_romaji,
    matches_query,
    normalize_for_search,
    to_romaji,
)


def test_hiragana_to_romaji():
    assert hiragana_to_romaji("いちか") == "ichika"
    assert hiragana_to_romaji("きょうこ") == "kyouko"
    assert hiragana_to_romaji("がっこう") == "gakkou"
    assert hiragana_to_romaji("") == ""


def test_katakana_to_romaji():
    assert katakana_to_romaji("イチカ") == "ichika"
    assert katakana_to_romaji("プロジェクト") == "purojekuto"
    assert katakana_to_romaji("セカイ") == "sekai"
    assert katakana_to_romaji("") == ""


def test_to_romaji():
    assert to_romaji("星乃一歌") == "星乃一歌"  # Kanji preserved
    assert to_romaji("ほしのイチカ") == "hoshinoichika"
    assert to_romaji("") == ""


def test_normalize_for_search():
    assert normalize_for_search("Stella-Rium") == "stellarium"
    assert normalize_for_search("テオ") == "teo"
    assert normalize_for_search("ヒバナ -Reloaded-") == "hibanareloaded"


def test_matches_query():
    # Direct case-insensitive match
    assert matches_query("ichika", "Hoshino Ichika")
    assert matches_query("hoshino", "Hoshino Ichika")

    # Romaji query matching Japanese text
    assert matches_query("ichika", "星乃いちか")
    assert matches_query("sekai", "プロジェクトセカイ")

    # Non-matching
    assert not matches_query("kanade", "Hoshino Ichika")
