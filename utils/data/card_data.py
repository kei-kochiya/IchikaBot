"""
Shared card data singleton.

Loads JP/EN card data ONCE and shares references across all cogs.

Memory comparison (cards.json is 32MB raw, ~100-250MB as Python objects):
  OLD: 7 cogs × JP copy + 6 cogs × EN copy  ≈ 400-600 MB
  NEW: 1 × JP data (shared) + dict[int,str] prefixes ≈ 60-100 MB
"""
import json
import logging
from config import CARDS_FILE_JP, CARDS_FILE_EN

logger = logging.getLogger(__name__)


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

    def _load(self):
        # ── JP cards ────────────────────────────────────────────────────────
        new_cards = []
        new_cards_by_id = {}
        new_pool_2 = []
        new_pool_3 = []
        new_pool_4 = []
        new_pool_3_4 = []
        try:
            with open(CARDS_FILE_JP, "r", encoding="utf-8") as f:
                new_cards = json.load(f)

            new_cards_by_id = {c["id"]: c for c in new_cards}
            new_pool_2   = [c for c in new_cards if c["cardRarityType"] == "rarity_2" and c.get("prefix")]
            new_pool_3   = [c for c in new_cards if c["cardRarityType"] == "rarity_3" and c.get("prefix")]
            new_pool_4   = [c for c in new_cards if c["cardRarityType"] == "rarity_4" and c.get("prefix")]
            new_pool_3_4 = new_pool_3 + new_pool_4

            # Atomically update JP data
            self.cards = new_cards
            self.cards_by_id = new_cards_by_id
            self.pool_2 = new_pool_2
            self.pool_3 = new_pool_3
            self.pool_4 = new_pool_4
            self.pool_3_4 = new_pool_3_4

            logger.info(
                "CardData: %d JP cards  (pool: %d★2 / %d★3 / %d★4)",
                len(self.cards), len(self.pool_2), len(self.pool_3), len(self.pool_4),
            )
        except Exception as e:
            logger.error("CardData: Failed to load JP cards: %s", e)

        # ── EN cards: prefix strings only (not full card objects) ────────────
        # The full EN list is parsed and immediately discarded; only a
        # flat dict[int, str] of prefix strings is retained.
        cards_en_raw = None
        try:
            with open(CARDS_FILE_EN, "r", encoding="utf-8") as f:
                cards_en_raw = json.load(f)
            self.en_prefix = {c["id"]: c["prefix"] for c in cards_en_raw if c.get("prefix")}
            logger.info("CardData: %d EN prefix strings (lightweight)", len(self.en_prefix))
        except FileNotFoundError:
            self.en_prefix = {}
        except Exception as e:
            logger.warning("CardData: Failed to load EN prefixes: %s", e)
            self.en_prefix = {}
        finally:
            del cards_en_raw  # release the temporary list immediately

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
