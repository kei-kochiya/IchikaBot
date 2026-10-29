"""Loader behaviour for the streamed game-data singletons (on throwaway instances)."""

import json

import pytest

from utils.data import event_data as event_module
from utils.data import song_data as song_module
from utils.data.card_data import EXCLUDED_HEAVY_KEYS, CardDataManager
from utils.data.event_data import EventDataManager
from utils.data.song_data import SongDataManager


def _dump(path, data, **kwargs):
    path.write_text(json.dumps(data, **kwargs), encoding="utf-8")
    return path


def _blank(cls, **attrs):
    """A manager instance that is not the shared singleton (and does not load on init)."""
    manager = object.__new__(cls)
    for name, value in attrs.items():
        setattr(manager, name, value)
    return manager


# ── Cards ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("dump_kwargs", [{}, {"indent": 2}, {"separators": (",", ":")}])
def test_cards_stream_any_layout_and_drop_heavy_tables(tmp_path, dump_kwargs):
    cards = [
        {"id": i, "prefix": f"card {i}", "cardParameters": [{"p": j} for j in range(50)]}
        for i in range(30)
    ]
    path = _dump(tmp_path / "cards.json", cards, **dump_kwargs)

    loaded = CardDataManager._stream_cards(path, excluded_keys=EXCLUDED_HEAVY_KEYS)

    assert [c["id"] for c in loaded] == list(range(30))
    assert all("cardParameters" not in c for c in loaded)
    assert all(c["prefix"] == f"card {c['id']}" for c in loaded)


def test_cards_without_exclusions_are_returned_whole(tmp_path):
    path = _dump(tmp_path / "cards.json", [{"id": 1, "extra": [1, 2]}])

    assert CardDataManager._stream_cards(path) == [{"id": 1, "extra": [1, 2]}]


def test_en_prefixes_keep_only_id_to_prefix(tmp_path):
    path = _dump(
        tmp_path / "en.json",
        [
            {"id": 1, "prefix": "One", "cardParameters": [1, 2, 3]},
            {"id": 2, "prefix": ""},
            {"id": 3},
            {"id": 4, "prefix": "Four"},
        ],
    )

    assert CardDataManager._stream_en_prefixes(path) == {1: "One", 4: "Four"}


# ── Events ────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def event_files(tmp_path, monkeypatch):
    jp = _dump(
        tmp_path / "events_jp.json",
        [
            {
                "id": 1,
                "name": "Old",
                "startAt": 100,
                "eventRankingRewardRanges": [{"big": [1] * 99}],
            },
            {"id": 2, "name": "New", "startAt": 200, "eventRankingRewardRanges": []},
        ],
    )
    en = _dump(tmp_path / "events_en.json", [{"id": 2, "name": "New EN"}, {"id": 1}])
    monkeypatch.setattr(event_module, "EVENTS_FILE_JP", jp)
    monkeypatch.setattr(event_module, "EVENTS_FILE_EN", en)
    return jp, en


def test_events_load_sorted_newest_first_without_reward_tables(event_files):
    manager = _blank(EventDataManager, events_jp=[], events_jp_by_id={}, events_en_names={})

    manager._load()

    assert [e["id"] for e in manager.events_jp] == [2, 1]
    assert set(manager.events_jp_by_id) == {1, 2}
    assert all("eventRankingRewardRanges" not in e for e in manager.events_jp)
    assert manager.events_en_names == {2: "New EN"}


def test_events_keep_previous_data_if_a_reload_fails(event_files, tmp_path, monkeypatch):
    manager = _blank(EventDataManager, events_jp=[], events_jp_by_id={}, events_en_names={})
    manager._load()
    before = (manager.events_jp, manager.events_jp_by_id, manager.events_en_names)

    # JP file vanishes, EN file is corrupt
    monkeypatch.setattr(event_module, "EVENTS_FILE_JP", tmp_path / "missing.json")
    (tmp_path / "events_en.json").write_text('[{"id": 1, "name"', encoding="utf-8")
    manager._load()

    assert (manager.events_jp, manager.events_jp_by_id, manager.events_en_names) == before


# ── Songs ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def song_files(tmp_path, monkeypatch):
    jp = _dump(tmp_path / "musics_jp.json", [{"id": 1, "title": "JP"}, {"id": 2, "title": "JP2"}])
    en = _dump(
        tmp_path / "musics_en.json",
        [{"id": 1, "title": "EN", "pronunciation": "p", "composer": "c"}, {"id": 2}],
    )
    diffs = _dump(
        tmp_path / "diffs.json",
        [
            {"musicId": 1, "musicDifficulty": "master", "playLevel": 30, "totalNoteCount": 900},
            {"musicId": 1, "musicDifficulty": "easy", "playLevel": 5, "totalNoteCount": 100},
        ],
    )
    monkeypatch.setattr(song_module, "MUSICS_FILE_JP", jp)
    monkeypatch.setattr(song_module, "MUSICS_FILE_EN", en)
    monkeypatch.setattr(song_module, "MUSIC_DIFFICULTIES_FILE_JP", diffs)
    return jp, en, diffs


def _blank_songs():
    return _blank(
        SongDataManager, songs_jp=[], songs_jp_by_id={}, songs_en_meta={}, difficulties={}
    )


def test_songs_load_streamed_files(song_files):
    manager = _blank_songs()

    manager._load()

    assert [s["id"] for s in manager.songs_jp] == [1, 2]
    assert manager.songs_jp_by_id[2]["title"] == "JP2"
    assert manager.songs_en_meta == {1: {"title": "EN", "pronunciation": "p", "composer": "c"}}
    assert manager.difficulties[1]["master"] == {"playLevel": 30, "noteCount": 900}
    assert manager.difficulties[1]["easy"]["playLevel"] == 5


def test_songs_keep_previous_data_if_a_reload_fails(song_files, tmp_path, monkeypatch):
    manager = _blank_songs()
    manager._load()
    before = (manager.songs_jp, manager.songs_en_meta, manager.difficulties)

    monkeypatch.setattr(song_module, "MUSICS_FILE_JP", tmp_path / "missing.json")
    monkeypatch.setattr(song_module, "MUSICS_FILE_EN", tmp_path / "missing_en.json")
    (tmp_path / "diffs.json").write_text("[{", encoding="utf-8")
    manager._load()

    assert (manager.songs_jp, manager.songs_en_meta, manager.difficulties) == before
