"""Shared card data singleton using streaming JSON load and key pruning (~96% RAM reduction)."""

import logging
import sys
from pathlib import Path

from config import CARDS_FILE_EN, CARDS_FILE_JP
from utils.core.jsonstream import iter_json_array

logger = logging.getLogger(__name__)

# Exclude massive nested tables that are unused by the bot (e.g. 220,000+ per-level param dicts)
EXCLUDED_HEAVY_KEYS = {
    "cardParameters",
    "specialTrainingCosts",
    "masterLessonAchieveResources",
}

# Only the fields actually read across cogs and utilities
CARD_KEYS = frozenset(
    {
        "id",
        "characterId",
        "cardRarityType",
        "prefix",
        "assetbundleName",
        "attr",
        "releaseAt",
        "initialSpecialTrainingStatus",
    }
)
_INTERNED_CARD_KEYS = ("cardRarityType", "attr", "initialSpecialTrainingStatus")


class CardDataManager:
    """Singleton card store (`card_data`) with O(1) ID lookup, rarity pools, and lightweight EN prefixes."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if CardDataManager._initialized:
            return
        self.cards: list[dict] = []
        self.cards_by_id: dict[int, dict] = {}
        self.en_prefix: dict[int, str] = {}
        self.pool_2: list[dict] = []
        self.pool_3: list[dict] = []
        self.pool_4: list[dict] = []
        self.pool_3_4: list[dict] = []
        self.by_char_3_4: dict[int, list[dict]] = {}
        self._load()
        CardDataManager._initialized = True

    @staticmethod
    def _stream_cards(
        filepath: Path | str,
        excluded_keys: set[str] | None = None,
        included_keys: frozenset[str] | set[str] | None = None,
    ) -> list[dict]:
        """Stream cards one element at a time and drop heavy per-level tables to minimize RAM."""
        if included_keys is not None:
            cards: list[dict] = []
            for card in iter_json_array(filepath):
                slim = {k: card[k] for k in included_keys if k in card}
                for key in _INTERNED_CARD_KEYS:
                    if isinstance(slim.get(key), str):
                        slim[key] = sys.intern(slim[key])
                cards.append(slim)
            return cards
        if excluded_keys:
            return [
                {k: v for k, v in card.items() if k not in excluded_keys}
                for card in iter_json_array(filepath)
            ]
        return list(iter_json_array(filepath))

    @staticmethod
    def _stream_en_prefixes(filepath: Path | str) -> dict[int, str]:
        """Stream the EN cards file and keep only {id: prefix}."""
        return {
            card["id"]: card["prefix"]
            for card in iter_json_array(filepath)
            if card.get("prefix") and "id" in card
        }

    def _load(self):
        # ── JP cards ────────────────────────────────────────────────────────
        try:
            new_cards = self._stream_cards(CARDS_FILE_JP, included_keys=CARD_KEYS)
            new_cards_by_id = {c["id"]: c for c in new_cards}
            new_pool_2 = [
                c for c in new_cards if c.get("cardRarityType") == "rarity_2" and c.get("prefix")
            ]
            new_pool_3 = [
                c for c in new_cards if c.get("cardRarityType") == "rarity_3" and c.get("prefix")
            ]
            new_pool_4 = [
                c for c in new_cards if c.get("cardRarityType") == "rarity_4" and c.get("prefix")
            ]
            new_pool_3_4 = new_pool_3 + new_pool_4
            new_by_char_3_4: dict[int, list[dict]] = {}
            for c in new_pool_3_4:
                new_by_char_3_4.setdefault(c["characterId"], []).append(c)

            # Atomically update JP data
            self.cards = new_cards
            self.cards_by_id = new_cards_by_id
            self.pool_2 = new_pool_2
            self.pool_3 = new_pool_3
            self.pool_4 = new_pool_4
            self.pool_3_4 = new_pool_3_4
            self.by_char_3_4 = new_by_char_3_4

            logger.info(
                "CardData: %d JP cards (pool: %d★2 / %d★3 / %d★4) [Memory-Optimized]",
                len(self.cards),
                len(self.pool_2),
                len(self.pool_3),
                len(self.pool_4),
            )
        except Exception as e:
            logger.error("CardData: Failed to load JP cards: %s", e)

        # ── EN cards: prefix strings only (not full card objects) ────────────
        try:
            new_en_prefix = self._stream_en_prefixes(CARDS_FILE_EN)
            self.en_prefix = new_en_prefix
            logger.info(
                "CardData: %d EN prefix strings [Memory-Optimized]",
                len(self.en_prefix),
            )
        except FileNotFoundError:
            if not self.en_prefix:
                self.en_prefix = {}
            else:
                logger.warning(
                    "CardData: EN cards file missing on reload; keeping cached EN prefixes"
                )
        except Exception as e:
            logger.warning("CardData: Failed to load EN prefixes (keeping existing): %s", e)

    def reload(self):
        """Reload from disk. Called by DataUpdater after file updates."""
        self._load()
        logger.info("CardData: Reloaded.")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def get_by_id(self, card_id: int) -> dict | None:
        """O(1) card lookup by ID."""
        return self.cards_by_id.get(card_id)

    def get_display_prefix(self, card: dict) -> str:
        """Return EN prefix if available, otherwise JP prefix."""
        return self.en_prefix.get(card.get("id")) or card.get("prefix", "???")


# Module-level singleton — import this, do NOT call CardDataManager() directly.
card_data = CardDataManager()
