"""Component tests for data pipelines: JSON streaming, singleton loaders, MusicQuizDB cache, romaji."""

import json
import sys

import openpyxl
import pytest

from utils.core.jsonstream import count_json_array, iter_json_array
from utils.core.romaji import (
    hiragana_to_romaji,
    katakana_to_romaji,
    matches_query,
    normalize_for_search,
    to_romaji,
)
from utils.data import event_data as event_module
from utils.data import music_quiz_db
from utils.data import song_data as song_module
from utils.data.card_data import CARD_KEYS, CardDataManager
from utils.data.event_data import EventDataManager
from utils.data.music_quiz_db import MusicQuizDB, is_correct_guess, normalize
from utils.data.song_data import SongDataManager

# ── Streaming JSON array reader ───────────────────────────────────────────────

SAMPLE_ARRAY = [
    {"id": i, "text": 'quote " comma , bracket ] 日本語', "n": [1, 2.5, None, True]}
    for i in range(40)
]


@pytest.mark.parametrize("chunk_size", [1, 7, 64, 1 << 20])
@pytest.mark.parametrize(
    "dump_kwargs",
    [{}, {"indent": 2}, {"separators": (",", ":")}, {"ensure_ascii": False, "indent": 1}],
)
def test_jsonstream_matches_json_load_across_layouts_and_chunks(tmp_path, chunk_size, dump_kwargs):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(SAMPLE_ARRAY, **dump_kwargs), encoding="utf-8")

    assert list(iter_json_array(path, chunk_size=chunk_size)) == SAMPLE_ARRAY
    assert count_json_array(path) == len(SAMPLE_ARRAY)


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 64])
def test_jsonstream_scalars_empty_and_malformed(tmp_path, chunk_size):
    scalars = [1, 22, 333, 4.5e10, True, None, "str", [1, [2]]]
    path = tmp_path / "scalars.json"
    path.write_text(json.dumps(scalars), encoding="utf-8")
    assert list(iter_json_array(path, chunk_size=chunk_size)) == scalars

    empty = tmp_path / "empty.json"
    empty.write_text("\n [ ] \n", encoding="utf-8")
    assert count_json_array(empty) == 0

    for bad_text in ('{"a": 1}', "[1, 2", "[1 2]", "[{]", "", "[1,]", "nope"):
        bad = tmp_path / "bad.json"
        bad.write_text(bad_text, encoding="utf-8")
        with pytest.raises(ValueError):
            list(iter_json_array(bad))


# ── Streamed singleton loaders & atomic failure preservation ──────────────────


def _dump(path, data, **kwargs):
    path.write_text(json.dumps(data, **kwargs), encoding="utf-8")
    return path


def _blank(cls, **attrs):
    obj = object.__new__(cls)
    for k, v in attrs.items():
        setattr(obj, k, v)
    return obj


def test_card_event_and_song_stream_loaders_prune_and_survive_corrupt_reloads(
    tmp_path, monkeypatch
):
    # Cards: drops heavy tables and keeps EN prefixes only
    cards_jp = _dump(
        tmp_path / "cards_jp.json",
        [{"id": i, "prefix": f"card {i}", "cardParameters": [{"p": 1}]} for i in range(10)],
        separators=(",", ":"),
    )
    loaded_cards = CardDataManager._stream_cards(cards_jp, included_keys=CARD_KEYS)
    assert len(loaded_cards) == 10 and all("cardParameters" not in c for c in loaded_cards)

    cards_en = _dump(
        tmp_path / "cards_en.json",
        [{"id": 1, "prefix": "One"}, {"id": 2, "prefix": ""}, {"id": 3}],
    )
    assert CardDataManager._stream_en_prefixes(cards_en) == {1: "One"}

    # Events: sorted newest-first, reward tables dropped, previous data kept on corrupt reload
    ev_jp = _dump(
        tmp_path / "events_jp.json",
        [
            {"id": 1, "name": "Old", "startAt": 100, "eventRankingRewardRanges": [{"big": 1}]},
            {"id": 2, "name": "New", "startAt": 200, "eventRankingRewardRanges": []},
        ],
    )
    ev_en = _dump(tmp_path / "events_en.json", [{"id": 2, "name": "New EN"}, {"id": 1}])
    monkeypatch.setattr(event_module, "EVENTS_FILE_JP", ev_jp)
    monkeypatch.setattr(event_module, "EVENTS_FILE_EN", ev_en)

    ev_mgr = _blank(EventDataManager, events_jp=[], events_jp_by_id={}, events_en_names={})
    ev_mgr._load()
    assert [e["id"] for e in ev_mgr.events_jp] == [2, 1]
    assert all("eventRankingRewardRanges" not in e for e in ev_mgr.events_jp)
    assert ev_mgr.events_en_names == {2: "New EN"}

    before_ev = (ev_mgr.events_jp, ev_mgr.events_en_names)
    monkeypatch.setattr(event_module, "EVENTS_FILE_JP", tmp_path / "missing.json")
    ev_en.write_text('[{"id": 1, "name"', encoding="utf-8")
    ev_mgr._load()
    assert (ev_mgr.events_jp, ev_mgr.events_en_names) == before_ev

    # Songs: streamed + indexed + previous data kept on corrupt reload
    s_jp = _dump(tmp_path / "musics_jp.json", [{"id": 1, "title": "JP"}, {"id": 2, "title": "JP2"}])
    s_en = _dump(
        tmp_path / "musics_en.json",
        [
            {"id": 1, "title": "EN", "pronunciation": "p", "composer": "c"},
            {"id": 999, "title": "EN-only"},
        ],
    )
    s_diff = _dump(
        tmp_path / "diffs.json",
        [{"musicId": 1, "musicDifficulty": "master", "playLevel": 30, "totalNoteCount": 900}],
    )
    monkeypatch.setattr(song_module, "MUSICS_FILE_JP", s_jp)
    monkeypatch.setattr(song_module, "MUSICS_FILE_EN", s_en)
    monkeypatch.setattr(song_module, "MUSIC_DIFFICULTIES_FILE_JP", s_diff)

    s_mgr = _blank(
        SongDataManager, songs_jp=[], songs_jp_by_id={}, songs_en_meta={}, difficulties={}
    )
    s_mgr._load()
    assert s_mgr.difficulties[1]["master"] == {"playLevel": 30, "noteCount": 900}
    # EN-only ID without JP entry must not leak into autocomplete
    assert not any(c.value == "999" for c in s_mgr.get_autocomplete_choices("EN-only"))

    before_s = (s_mgr.songs_jp, s_mgr.songs_en_meta, s_mgr.difficulties)
    monkeypatch.setattr(song_module, "MUSICS_FILE_JP", tmp_path / "missing_s.json")
    s_diff.write_text("[{", encoding="utf-8")
    s_mgr._load()
    assert (s_mgr.songs_jp, s_mgr.songs_en_meta, s_mgr.difficulties) == before_s


# ── MusicQuizDB & openpyxl JSON cache ─────────────────────────────────────────


def test_music_quiz_db_normalize_and_parsed_table_cache(tmp_path, monkeypatch):
    # Unicode folding + post-normalize 3-char minimum
    assert normalize("Ángel") == "angel"
    assert normalize("ｔｅｌｌ　ｙｏｕｒ　ｗｏｒｌｄ") == "tellyourworld"
    assert normalize("PaⅢ.SENSATION") == "paiiisensation"
    assert is_correct_guess("h i", ["hibana"]) is False
    assert is_correct_guess("h i b", ["hibana"]) is True
    assert is_correct_guess("Ángel", ["angel"]) is True

    # Real song.xlsx loads commission songs
    real_db = MusicQuizDB.get_instance()
    assert len(real_db._db) > 500
    assert real_db.is_commission("54.mp3") is True
    assert real_db.is_commission("1.mp3") is False

    # Parsed cache avoids importing openpyxl when workbook is unchanged, invalidates on edit
    xlsx = tmp_path / "song.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["index", "jp", "en", "", "", "", "", "romaji", "comm"])
    wb.active.append(
        [1, "テルユアワールド", "Tell Your World", "", "", "", "", "Tell Your World", None]
    )
    wb.active.append([54, "レディステディ", "Ready Steady", "", "", "", "", "Ready Steady", 1])
    wb.save(xlsx)
    monkeypatch.setattr(music_quiz_db, "SONG_DB_PATH", xlsx)
    monkeypatch.setattr(music_quiz_db, "SONG_CACHE_PATH", tmp_path / "cache" / "songs.json")

    first = MusicQuizDB()
    first.load_db()
    assert (tmp_path / "cache" / "songs.json").exists()

    monkeypatch.setitem(sys.modules, "openpyxl", None)
    second = MusicQuizDB()
    second.load_db()
    assert second._db == first._db and second.get_commission_ids() == {"54"}

    monkeypatch.delitem(sys.modules, "openpyxl")
    wb.active.append([63, "ニードル", "needLe", "", "", "", "", "needLe", 1])
    wb.save(xlsx)
    third = MusicQuizDB()
    third.load_db()
    assert third.get_commission_ids() == {"54", "63"}


# ── Romaji conversion & search normalization ──────────────────────────────────


def test_romaji_conversion_combos_and_cache():
    assert hiragana_to_romaji("がっこう") == "gakkou"
    assert katakana_to_romaji("プロジェクトセカイ") == "purojekutosekai"
    assert katakana_to_romaji("トゥデイ") == "tudei"
    assert katakana_to_romaji("ドゥ") == "du"
    assert to_romaji("星乃いちか") == "星乃ichika"

    normalize_for_search.cache_clear()
    for _ in range(3):
        assert matches_query("teo", "テオ")
    assert normalize_for_search.cache_info().hits >= 4
    assert matches_query("sekai", "プロジェクトセカイ")
    assert not matches_query("kanade", "Hoshino Ichika")
