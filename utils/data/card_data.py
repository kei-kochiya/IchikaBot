"""
Shared card data singleton.

Loads JP/EN card data using streaming and memory pruning to keep RAM usage minimal.

Memory comparison:
  ORIGINAL (full json.load): JP (~78MB) + EN (~63MB fragmentation) ≈ 140+ MB
  OPTIMIZED (streaming + pruning heavy tables): JP (~4.7MB) + EN (~1MB) ≈ ~5.7 MB (96% RAM reduction)
"""

import json
import logging
from pathlib import Path

from config import CARDS_FILE_EN, CARDS_FILE_JP

logger = logging.getLogger(__name__)

# Exclude massive nested tables that are unused by the bot (e.g. 220,000+ per-level param dicts)
EXCLUDED_HEAVY_KEYS = {
    "cardParameters",
    "specialTrainingCosts",
    "masterLessonAchieveResources",
}


class CardDataManager:
    """
    Singleton. All cogs import the module-level `card_data` instance.

    Attributes
    ----------
    cards        : list[dict]     All JP cards. Shared across cogs (not copied).
    cards_by_id  : dict[int,dict] O(1) lookup by card ID (values are refs into cards).
    en_prefix    : dict[int,str]  EN prefix strings only — NOT full EN card objects.
    pool_2/3/4   : list[dict]     Pre-filtered by rarity (refs into cards, not copies).
    pool_3_4     : list[dict]     Union of pool_3 and pool_4.
    """

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
        self._load()
        CardDataManager._initialized = True

    @staticmethod
    def _stream_cards(filepath: Path | str, excluded_keys: set[str] | None = None) -> list[dict]:
        """
        Stream and parse JSON cards array one-by-one to avoid allocating
        the entire 37MB file and hundreds of thousands of dicts all at once in memory.
        Falls back to standard json.load if file does not match formatted array indentation.
        """
        cards = []
        card_lines = []
        in_card = False

        try:
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    if not in_card:
                        if line.startswith("  {"):
                            in_card = True
                            card_lines = ["{\n"]
                    else:
                        if line.startswith("  }") or line.startswith("  },"):
                            card_lines.append("}\n")
                            card_raw = json.loads("".join(card_lines))
                            if excluded_keys:
                                cards.append(
                                    {k: v for k, v in card_raw.items() if k not in excluded_keys}
                                )
                            else:
                                cards.append(card_raw)
                            in_card = False
                            card_lines = []
                        else:
                            card_lines.append(line)
        except Exception as e:
            logger.warning(
                "CardData: Streaming error on %s: %s, falling back to full read", filepath, e
            )
            cards = []

        if not cards:
            # Fallback for unexpected JSON formatting (e.g. minified single-line)
            with open(filepath, encoding="utf-8") as f:
                raw = json.load(f)
                if excluded_keys:
                    cards = [{k: v for k, v in c.items() if k not in excluded_keys} for c in raw]
                else:
                    cards = raw

        return cards

    @staticmethod
    def _stream_en_prefixes(filepath: Path | str) -> dict[int, str]:
        """
        Stream EN cards file and extract only {id: prefix} without loading
        the full 30MB+ JSON into memory.
        """
        en_prefix = {}
        card_lines = []
        in_card = False

        try:
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    if not in_card:
                        if line.startswith("  {"):
                            in_card = True
                            card_lines = ["{\n"]
                    else:
                        if line.startswith("  }") or line.startswith("  },"):
                            card_lines.append("}\n")
                            card_raw = json.loads("".join(card_lines))
                            prefix = card_raw.get("prefix")
                            if prefix and "id" in card_raw:
                                en_prefix[card_raw["id"]] = prefix
                            in_card = False
                            card_lines = []
                        else:
                            card_lines.append(line)
        except Exception as e:
            logger.warning("CardData: Streaming error on EN file %s: %s, falling back", filepath, e)
            en_prefix = {}

        if not en_prefix:
            # Fallback for unexpected JSON formatting
            with open(filepath, encoding="utf-8") as f:
                raw = json.load(f)
                en_prefix = {c["id"]: c["prefix"] for c in raw if c.get("prefix")}

        return en_prefix

    def _load(self):
        # ── JP cards ────────────────────────────────────────────────────────
        try:
            new_cards = self._stream_cards(CARDS_FILE_JP, excluded_keys=EXCLUDED_HEAVY_KEYS)
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

            # Atomically update JP data
            self.cards = new_cards
            self.cards_by_id = new_cards_by_id
            self.pool_2 = new_pool_2
            self.pool_3 = new_pool_3
            self.pool_4 = new_pool_4
            self.pool_3_4 = new_pool_3_4

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
            self.en_prefix = self._stream_en_prefixes(CARDS_FILE_EN)
            logger.info(
                "CardData: %d EN prefix strings [Memory-Optimized]",
                len(self.en_prefix),
            )
        except FileNotFoundError:
            self.en_prefix = {}
        except Exception as e:
            logger.warning("CardData: Failed to load EN prefixes: %s", e)
            self.en_prefix = {}

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
