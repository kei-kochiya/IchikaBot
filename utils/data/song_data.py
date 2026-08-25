"""
Shared song and music difficulties data singleton.

Loads JP music data ONCE and keeps only lightweight EN search/display strings to minimize RAM.
"""
import json
import logging
import random
from discord import app_commands

from config import MUSICS_FILE_JP, MUSICS_FILE_EN, MUSIC_DIFFICULTIES_FILE_JP
from utils.core.romaji import matches_query, normalize_for_search

logger = logging.getLogger(__name__)


class SongDataManager:
    """
    Singleton for managing Project Sekai songs and difficulties data.
    Provides memory-efficient access and helper methods used by SongsCog and others.
    """
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
        self._load()
        SongDataManager._initialized = True

    def _load(self):
        """Load JP songs, difficulties, and lightweight EN metadata atomically."""
        new_songs_jp = []
        new_songs_jp_by_id = {}
        new_songs_en_meta = {}
        new_difficulties = {}

        # ── JP Songs ────────────────────────────────────────────────────────
        try:
            with open(MUSICS_FILE_JP, 'r', encoding='utf-8') as f:
                new_songs_jp = json.load(f)
            new_songs_jp_by_id = {s['id']: s for s in new_songs_jp}
            logger.info("SongData: %d JP songs loaded", len(new_songs_jp))
        except FileNotFoundError as e:
            logger.error("SongData: Missing JP file: %s", e.filename)
        except Exception as e:
            logger.error("SongData: Failed to load JP songs: %s", e)

        # ── EN Songs (lightweight metadata only) ─────────────────────────────
        songs_en_raw = None
        try:
            with open(MUSICS_FILE_EN, 'r', encoding='utf-8') as f:
                songs_en_raw = json.load(f)
            new_songs_en_meta = {
                s['id']: {
                    'title': s.get('title', ''),
                    'pronunciation': s.get('pronunciation', ''),
                    'composer': s.get('composer', ''),
                }
                for s in songs_en_raw if s.get('title')
            }
            logger.info("SongData: %d EN songs metadata loaded (lightweight)", len(new_songs_en_meta))
        except FileNotFoundError as e:
            logger.warning("SongData: Missing EN file: %s", e.filename)
        except Exception as e:
            logger.error("SongData: Failed to load EN songs: %s", e)
        finally:
            del songs_en_raw

        # ── Music Difficulties ──────────────────────────────────────────────
        try:
            with open(MUSIC_DIFFICULTIES_FILE_JP, 'r', encoding='utf-8') as f:
                raw_diffs = json.load(f)
            for diff in raw_diffs:
                music_id = diff['musicId']
                if music_id not in new_difficulties:
                    new_difficulties[music_id] = {}
                new_difficulties[music_id][diff['musicDifficulty']] = {
                    'playLevel': diff['playLevel'],
                    'noteCount': diff['totalNoteCount']
                }
            logger.info("SongData: Difficulties for %d songs loaded", len(new_difficulties))
        except Exception as e:
            logger.error("SongData: Failed to load difficulties: %s", e)

        # Atomic assignment
        self.songs_jp = new_songs_jp
        self.songs_jp_by_id = new_songs_jp_by_id
        self.songs_en_meta = new_songs_en_meta
        self.difficulties = new_difficulties

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
        if en_meta and en_meta.get('title'):
            return en_meta['title']
        return song.get('title', 'Unknown')

    def search_songs(self, query: str, limit: int = 50) -> list[dict]:
        """Search songs by name, ID, or romaji across EN and JP."""
        if query.isdigit():
            target_id = int(query)
            song = self.get_song_by_id(target_id)
            if song:
                return [song]
            if self.songs_jp:
                sorted_songs = sorted(self.songs_jp, key=lambda s: (abs(s['id'] - target_id), -s['id']))
                if sorted_songs:
                    return [sorted_songs[0]]
            return []

        results = []
        seen_ids = set()

        # 1. Search EN songs metadata first
        for song_id, meta in self.songs_en_meta.items():
            if matches_query(query, meta['title'], meta['pronunciation'], meta['composer']):
                jp_song = self.songs_jp_by_id.get(song_id)
                if jp_song and song_id not in seen_ids:
                    results.append(jp_song)
                    seen_ids.add(song_id)
                    if len(results) >= limit:
                        return results

        # 2. Then search JP songs
        for song in self.songs_jp:
            song_id = song['id']
            if song_id in seen_ids:
                continue
            title = song.get('title', '')
            pronunciation = song.get('pronunciation', '')
            composer = song.get('composer', '')
            if matches_query(query, title, pronunciation, composer):
                results.append(song)
                seen_ids.add(song_id)
                if len(results) >= limit:
                    break

        return results

    def get_random_song(self, min_level: int = None, max_level: int = None) -> dict | None:
        """Get a random song optionally filtered by Master level range."""
        valid_songs = []
        for song in self.songs_jp:
            diff_info = self.difficulties.get(song['id'], {})
            master = diff_info.get('master', {})
            if not master:
                continue
            level = master.get('playLevel', 0)
            if min_level is not None and level < min_level:
                continue
            if max_level is not None and level > max_level:
                continue
            valid_songs.append(song)

        if not valid_songs:
            return None
        return random.choice(valid_songs)

    def get_autocomplete_choices(self, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete choices for song selection."""
        choices = []
        seen_ids = set()

        # 1. EN matches
        for song_id, meta in self.songs_en_meta.items():
            title = meta['title']
            pronunciation = meta['pronunciation']
            if matches_query(current, title, pronunciation):
                diff_info = self.difficulties.get(song_id, {})
                master_level = diff_info.get('master', {}).get('playLevel', '?')
                display = f"{title} (Master Lv.{master_level})"
                choices.append(app_commands.Choice(name=display[:100], value=str(song_id)))
                seen_ids.add(song_id)
                if len(choices) >= 25:
                    return choices

        # 2. JP matches
        for song in self.songs_jp:
            song_id = song['id']
            if song_id in seen_ids:
                continue
            title = song.get('title', '')
            pronunciation = song.get('pronunciation', '')
            if matches_query(current, title, pronunciation):
                diff_info = self.difficulties.get(song_id, {})
                master_level = diff_info.get('master', {}).get('playLevel', '?')
                display_title = self.songs_en_meta.get(song_id, {}).get('title', title)
                display = f"{display_title} (Master Lv.{master_level})"
                choices.append(app_commands.Choice(name=display[:100], value=str(song_id)))
                seen_ids.add(song_id)
                if len(choices) >= 25:
                    break

        return choices


# Module-level singleton
song_data = SongDataManager()
