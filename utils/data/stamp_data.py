"""
Shared stamp data singleton.

Loads JP stamp data ONCE and keeps only lightweight EN name strings to minimize RAM.
"""
import json
import logging
import random

from config import STAMPS_FILE_JP, STAMPS_FILE_EN
from utils.core.romaji import matches_query

logger = logging.getLogger(__name__)


class StampDataManager:
    """
    Singleton for managing Project Sekai stamps data.
    Provides memory-efficient access and helper methods used by StampsCog and others.
    """
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if StampDataManager._initialized:
            return
        self.stamps_jp: list[dict] = []
        self.stamps_jp_by_id: dict[int, dict] = {}
        self.stamps_en_names: dict[int, str] = {}
        self._load()
        StampDataManager._initialized = True

    def _load(self):
        """Load JP stamps and lightweight EN name mappings atomically."""
        new_stamps_jp = []
        new_stamps_jp_by_id = {}
        new_stamps_en_names = {}

        # ── JP Stamps ────────────────────────────────────────────────────────
        try:
            with open(STAMPS_FILE_JP, 'r', encoding='utf-8') as f:
                new_stamps_jp = json.load(f)
            new_stamps_jp_by_id = {s['id']: s for s in new_stamps_jp}
            logger.info("StampData: %d JP stamps loaded", len(new_stamps_jp))
        except FileNotFoundError as e:
            logger.error("StampData: Missing JP file: %s", e.filename)
        except Exception as e:
            logger.error("StampData: Failed to load JP stamps: %s", e)

        # ── EN Stamps (names only to save RAM) ──────────────────────────────
        stamps_en_raw = None
        try:
            with open(STAMPS_FILE_EN, 'r', encoding='utf-8') as f:
                stamps_en_raw = json.load(f)
            new_stamps_en_names = {s['id']: s['name'] for s in stamps_en_raw if s.get('name')}
            logger.info("StampData: %d EN stamp names loaded (lightweight)", len(new_stamps_en_names))
        except FileNotFoundError as e:
            logger.warning("StampData: Missing EN file: %s", e.filename)
        except Exception as e:
            logger.error("StampData: Failed to load EN stamps: %s", e)
        finally:
            del stamps_en_raw

        # Atomic assignment
        self.stamps_jp = new_stamps_jp
        self.stamps_jp_by_id = new_stamps_jp_by_id
        self.stamps_en_names = new_stamps_en_names

    def reload(self):
        """Reload from disk. Called by DataUpdater after file updates."""
        self._load()
        logger.info("StampData: Reloaded.")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def get_stamp_by_id(self, stamp_id: int) -> dict | None:
        """Get stamp by ID (JP source of truth)."""
        return self.stamps_jp_by_id.get(stamp_id)

    def get_display_name(self, stamp: dict, stamp_id: int) -> str:
        """Get display name, using EN name if available."""
        name = self.stamps_en_names.get(stamp_id) or stamp.get('name', 'Unknown')
        # Strip prefix tag
        if name.startswith('[スタンプ]'):
            name = name[6:]
        if name.startswith('[Stamp]'):
            name = name[7:]
        return name

    def search_stamps(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search stamps by keyword, ID, or romaji across EN and JP."""
        if keyword.isdigit():
            target_id = int(keyword)
            stamp = self.get_stamp_by_id(target_id)
            if stamp:
                return [stamp]
            if self.stamps_jp:
                sorted_stamps = sorted(self.stamps_jp, key=lambda s: (abs(s['id'] - target_id), -s['id']))
                if sorted_stamps:
                    return [sorted_stamps[0]]
            return []

        results = []
        seen_ids = set()

        # 1. Search EN names first
        for stamp_id, en_name in self.stamps_en_names.items():
            if matches_query(keyword, en_name):
                jp_stamp = self.stamps_jp_by_id.get(stamp_id)
                if jp_stamp and stamp_id not in seen_ids:
                    results.append(jp_stamp)
                    seen_ids.add(stamp_id)
                    if len(results) >= limit:
                        return results

        # 2. Then search JP stamps
        for stamp in self.stamps_jp:
            stamp_id = stamp['id']
            if stamp_id in seen_ids:
                continue
            name = stamp.get('name', '')
            if matches_query(keyword, name):
                results.append(stamp)
                seen_ids.add(stamp_id)
                if len(results) >= limit:
                    break

        return results

    def get_stamps_by_character(self, char_id: int) -> list[dict]:
        """Get all stamps for a character."""
        return [
            s for s in self.stamps_jp
            if s.get('characterId1') == char_id or s.get('gameCharacterUnitId') == char_id
        ]

    def get_random_stamp(self) -> dict | None:
        """Get a random stamp."""
        if not self.stamps_jp:
            return None
        return random.choice(self.stamps_jp)


# Module-level singleton
stamp_data = StampDataManager()
