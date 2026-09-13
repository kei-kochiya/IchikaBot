"""
Shared event data singleton.

Loads JP event data ONCE and keeps only lightweight EN name strings to minimize RAM.
"""

import json
import logging
from datetime import UTC, datetime

from config import EVENTS_FILE_EN, EVENTS_FILE_JP
from utils.core.romaji import matches_query

logger = logging.getLogger(__name__)


class EventDataManager:
    """
    Singleton for managing Project Sekai event data.
    Provides memory-efficient access and helper methods used by EventsCog and others.
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if EventDataManager._initialized:
            return
        self.events_jp: list[dict] = []
        self.events_jp_by_id: dict[int, dict] = {}
        self.events_en_names: dict[int, str] = {}
        self._load()
        EventDataManager._initialized = True

    def _load(self):
        """Load JP events and lightweight EN name mappings atomically."""
        new_events_jp = []
        new_events_jp_by_id = {}
        new_events_en_names = {}

        # ── JP Events ───────────────────────────────────────────────────────
        try:
            with open(EVENTS_FILE_JP, encoding="utf-8") as f:
                new_events_jp = json.load(f)
            new_events_jp.sort(key=lambda e: e.get("startAt", 0), reverse=True)
            new_events_jp_by_id = {e["id"]: e for e in new_events_jp}
            logger.info("EventData: %d JP events loaded", len(new_events_jp))
        except FileNotFoundError as e:
            logger.error("EventData: Missing JP file: %s", e.filename)
        except Exception as e:
            logger.error("EventData: Failed to load JP event data: %s", e)

        # ── EN Events (names only to save RAM) ──────────────────────────────
        events_en_raw = None
        try:
            with open(EVENTS_FILE_EN, encoding="utf-8") as f:
                events_en_raw = json.load(f)
            new_events_en_names = {e["id"]: e["name"] for e in events_en_raw if e.get("name")}
            logger.info(
                "EventData: %d EN event names loaded (lightweight)", len(new_events_en_names)
            )
        except FileNotFoundError as e:
            logger.warning("EventData: Missing EN file: %s", e.filename)
        except Exception as e:
            logger.error("EventData: Failed to load EN event data: %s", e)
        finally:
            del events_en_raw

        # Atomic assignment
        self.events_jp = new_events_jp
        self.events_jp_by_id = new_events_jp_by_id
        self.events_en_names = new_events_en_names

    def reload(self):
        """Reload from disk. Called by DataUpdater after file updates."""
        self._load()
        logger.info("EventData: Reloaded.")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def get_event_by_id(self, event_id: int) -> dict | None:
        """Get event by ID from JP data (for correct timing)."""
        return self.events_jp_by_id.get(event_id)

    def get_display_name(self, event: dict, event_id: int) -> str:
        """Get display name, using EN name if available."""
        en_name = self.events_en_names.get(event_id)
        if en_name:
            return en_name
        return event.get("name", "Unknown Event")

    def get_current_event(self) -> dict | None:
        """Get current event from JP data."""
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        for event in self.events_jp:
            start = event.get("startAt", 0)
            end = event.get("closedAt", 0)
            if start <= now_ms <= end:
                return event
            elif now_ms < start:
                return event  # Return upcoming if no current
        return self.events_jp[0] if self.events_jp else None

    def get_past_events(self, count: int = 5) -> list[dict]:
        """Get past closed events."""
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        return [e for e in self.events_jp if e.get("closedAt", 0) < now_ms][:count]

    def search_events(self, query: str, limit: int = 50) -> list[dict]:
        """Search events by name, ID, or romaji. Returns JP events for correct timing."""
        if query.isdigit():
            target_id = int(query)
            event = self.get_event_by_id(target_id)
            if event:
                return [event]
            if self.events_jp:
                sorted_events = sorted(
                    self.events_jp, key=lambda e: (abs(e["id"] - target_id), -e["id"])
                )
                if sorted_events:
                    return [sorted_events[0]]
            return []

        results = []
        seen_ids = set()

        # 1. Search EN names first
        for event_id, en_name in self.events_en_names.items():
            if matches_query(query, en_name):
                jp_event = self.events_jp_by_id.get(event_id)
                if jp_event and event_id not in seen_ids:
                    results.append(jp_event)
                    seen_ids.add(event_id)
                    if len(results) >= limit:
                        return results

        # 2. Then search JP event names
        for event in self.events_jp:
            event_id = event["id"]
            if event_id in seen_ids:
                continue
            name = event.get("name", "")
            if matches_query(query, name):
                results.append(event)
                seen_ids.add(event_id)
                if len(results) >= limit:
                    break

        return results


# Module-level singleton
event_data = EventDataManager()
