"""Shared song and difficulty data singleton loading JP music data and lightweight EN titles."""

import logging
import random
import sys

from discord import app_commands

from config import MUSIC_DIFFICULTIES_FILE_JP, MUSICS_FILE_EN, MUSICS_FILE_JP
from utils.core.jsonstream import iter_json_array
from utils.core.romaji import matches_query, normalize_for_search

logger = logging.getLogger(__name__)

SONG_KEYS = frozenset(
    {
        "id",
        "title",
        "pronunciation",
        "composer",
        "lyricist",
        "arranger",
        "publishedAt",
        "categories",
        "assetbundleName",
    }
)


def _search_entry(
    song_id: int, song: dict | None, title: str, pron: str, comp: str, ac_label: str
) -> tuple:
    # Call uncached normalization here: results are stored permanently in the index, so
    # routing them through normalize_for_search's LRU cache would evict live query entries.
    norm_uncached = getattr(normalize_for_search, "__wrapped__", normalize_for_search)
    ac_fields = [f for f in (title, pron) if f]
    ac_lower = "\x00".join(f.lower() for f in ac_fields)
    ac_norm = "\x00".join(norm_uncached(f) for f in ac_fields)
    all_lower = f"{ac_lower}\x00{comp.lower()}" if comp else ac_lower
    all_norm = f"{ac_norm}\x00{norm_uncached(comp)}" if comp else ac_norm
    return (song_id, song, all_lower, all_norm, ac_lower, ac_norm, ac_label, str(song_id))


def _entry_matches(entry: tuple, q_lower: str, q_norm: str, ac_only: bool = False) -> bool:
    if "\x00" in q_lower:
        return False
    lowers, norms = (entry[4], entry[5]) if ac_only else (entry[2], entry[3])
    return q_lower in lowers or (bool(q_norm) and q_norm in norms)


class SongDataManager:
    """Singleton managing Project Sekai songs, difficulties, and multilingual search indices."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if SongDataManager._initialized:
            return
        self.songs_jp: list[dict] = []
        self.songs_jp_by_id: dict[int, dict] = {}
        self.songs_en_meta: dict[int, dict] = {}  # id -> {title, pronunciation, composer}
        self.difficulties: dict[int, dict] = {}
        self._en_index: list[tuple] = []
        self._jp_index: list[tuple] = []
        self._load()
        SongDataManager._initialized = True

    def _load(self):
        """Load JP songs, difficulties, and lightweight EN metadata atomically.

        Files are streamed element by element; if a file fails to load, the
        previously loaded data for it is kept.
        """
        new_songs_jp: list[dict] | None = None
        new_songs_en_meta: dict[int, dict] | None = None
        new_difficulties: dict[int, dict] | None = None

        # ── JP Songs ────────────────────────────────────────────────────────
        try:
            new_songs_jp = [
                {k: s[k] for k in SONG_KEYS if k in s} for s in iter_json_array(MUSICS_FILE_JP)
            ]
            logger.info("SongData: %d JP songs loaded", len(new_songs_jp))
        except FileNotFoundError as e:
            logger.error("SongData: Missing JP file: %s", e.filename)
        except Exception as e:
            logger.error("SongData: Failed to load JP songs: %s", e)

        # ── EN Songs (lightweight metadata only) ─────────────────────────────
        try:
            new_songs_en_meta = {
                s["id"]: {
                    "title": s.get("title", ""),
                    "pronunciation": s.get("pronunciation", ""),
                    "composer": s.get("composer", ""),
                }
                for s in iter_json_array(MUSICS_FILE_EN)
                if s.get("title")
            }
            logger.info(
                "SongData: %d EN songs metadata loaded (lightweight)", len(new_songs_en_meta)
            )
        except FileNotFoundError as e:
            logger.warning("SongData: Missing EN file: %s", e.filename)
        except Exception as e:
            logger.error("SongData: Failed to load EN songs: %s", e)

        # ── Music Difficulties ──────────────────────────────────────────────
        try:
            difficulties: dict[int, dict] = {}
            for diff in iter_json_array(MUSIC_DIFFICULTIES_FILE_JP):
                diff_key = sys.intern(diff["musicDifficulty"])
                difficulties.setdefault(diff["musicId"], {})[diff_key] = {
                    "playLevel": diff["playLevel"],
                    "noteCount": diff["totalNoteCount"],
                }
            new_difficulties = difficulties
            logger.info("SongData: Difficulties for %d songs loaded", len(difficulties))
        except Exception as e:
            logger.error("SongData: Failed to load difficulties: %s", e)

        # Atomic assignment (only for files that loaded successfully)
        if new_songs_jp is not None:
            self.songs_jp = new_songs_jp
            self.songs_jp_by_id = {s["id"]: s for s in new_songs_jp}
        if new_songs_en_meta is not None:
            self.songs_en_meta = new_songs_en_meta
        if new_difficulties is not None:
            self.difficulties = new_difficulties

        self._rebuild_indexes()

    def _rebuild_indexes(self) -> None:
        """Precompute normalized search tuples and autocomplete labels."""
        en_index: list[tuple] = []
        for song_id, meta in self.songs_en_meta.items():
            master_lv = self.difficulties.get(song_id, {}).get("master", {}).get("playLevel", "?")
            ac_label = f"{meta['title']} (Master Lv.{master_lv})"[:100]
            en_index.append(
                _search_entry(
                    song_id,
                    self.songs_jp_by_id.get(song_id),
                    meta["title"],
                    meta["pronunciation"],
                    meta["composer"],
                    ac_label,
                )
            )

        jp_index: list[tuple] = []
        for song in self.songs_jp:
            song_id = song["id"]
            title = song.get("title", "")
            master_lv = self.difficulties.get(song_id, {}).get("master", {}).get("playLevel", "?")
            display_title = self.songs_en_meta.get(song_id, {}).get("title", title)
            ac_label = f"{display_title} (Master Lv.{master_lv})"[:100]
            jp_index.append(
                _search_entry(
                    song_id,
                    song,
                    title,
                    song.get("pronunciation", ""),
                    song.get("composer", ""),
                    ac_label,
                )
            )

        self._en_index = en_index
        self._jp_index = jp_index

    def reload(self):
        """Reload from disk. Called by DataUpdater after file updates."""
        self._load()
        logger.info("SongData: Reloaded.")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def get_song_by_id(self, song_id: int) -> dict | None:
        """Get song dict by ID (JP source of truth)."""
        return self.songs_jp_by_id.get(song_id)

    def get_display_title(self, song: dict, song_id: int) -> str:
        """Get display title, using EN title if available."""
        en_meta = self.songs_en_meta.get(song_id)
        if en_meta and en_meta.get("title"):
            return en_meta["title"]
        return song.get("title", "Unknown")

    def search_songs(self, query: str, limit: int = 50) -> list[dict]:
        """Search songs by name, ID, or romaji across EN and JP."""
        if query.isascii() and query.isdigit():
            target_id = int(query)
            song = self.get_song_by_id(target_id)
            if song:
                return [song]
            if self.songs_jp:
                return [min(self.songs_jp, key=lambda s: (abs(s["id"] - target_id), -s["id"]))]
            return []

        en_index = getattr(self, "_en_index", None)
        jp_index = getattr(self, "_jp_index", None)
        if en_index is None or jp_index is None:
            return self._search_songs_uncached(query, limit)

        q_lower = query.lower()
        q_norm = normalize_for_search(query)
        results: list[dict] = []
        seen_ids: set[int] = set()

        for entry in en_index:
            song_id, jp_song = entry[0], entry[1]
            if jp_song and song_id not in seen_ids and _entry_matches(entry, q_lower, q_norm):
                results.append(jp_song)
                seen_ids.add(song_id)
                if len(results) >= limit:
                    return results

        for entry in jp_index:
            song_id, song = entry[0], entry[1]
            if song_id not in seen_ids and _entry_matches(entry, q_lower, q_norm):
                results.append(song)
                seen_ids.add(song_id)
                if len(results) >= limit:
                    break

        return results

    def _search_songs_uncached(self, query: str, limit: int) -> list[dict]:
        results: list[dict] = []
        seen_ids: set[int] = set()
        for song_id, meta in self.songs_en_meta.items():
            if matches_query(query, meta["title"], meta["pronunciation"], meta["composer"]):
                jp_song = self.songs_jp_by_id.get(song_id)
                if jp_song and song_id not in seen_ids:
                    results.append(jp_song)
                    seen_ids.add(song_id)
                    if len(results) >= limit:
                        return results
        for song in self.songs_jp:
            song_id = song["id"]
            if song_id in seen_ids:
                continue
            if matches_query(
                query,
                song.get("title", ""),
                song.get("pronunciation", ""),
                song.get("composer", ""),
            ):
                results.append(song)
                seen_ids.add(song_id)
                if len(results) >= limit:
                    break
        return results

    def get_random_song(
        self, min_level: int | None = None, max_level: int | None = None
    ) -> dict | None:
        """Get a random song optionally filtered by Master level range."""
        valid_songs = []
        for song in self.songs_jp:
            master = self.difficulties.get(song["id"], {}).get("master")
            if not master:
                continue
            level = master.get("playLevel", 0)
            if min_level is not None and level < min_level:
                continue
            if max_level is not None and level > max_level:
                continue
            valid_songs.append(song)

        return random.choice(valid_songs) if valid_songs else None

    def get_autocomplete_choices(self, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete choices for song selection."""
        en_index = getattr(self, "_en_index", None)
        jp_index = getattr(self, "_jp_index", None)
        if en_index is None or jp_index is None:
            return []

        q_lower = current.lower()
        q_norm = normalize_for_search(current)
        choices: list[app_commands.Choice[str]] = []
        seen_ids: set[int] = set()

        for entry in en_index:
            song_id = entry[0]
            if entry[1] and _entry_matches(entry, q_lower, q_norm, ac_only=True):
                choices.append(app_commands.Choice(name=entry[6], value=entry[7]))
                seen_ids.add(song_id)
                if len(choices) >= 25:
                    return choices

        for entry in jp_index:
            song_id = entry[0]
            if song_id not in seen_ids and _entry_matches(entry, q_lower, q_norm, ac_only=True):
                choices.append(app_commands.Choice(name=entry[6], value=entry[7]))
                seen_ids.add(song_id)
                if len(choices) >= 25:
                    break

        return choices


# Module-level singleton
song_data = SongDataManager()
