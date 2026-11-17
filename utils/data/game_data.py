"""
Game Data Utility - Centralized access to character and unit data.
Used by multiple cogs to avoid code duplication.
"""

import json
import logging

from discord import app_commands

from config import CHARACTERS_FILE, NICKNAMES_FILE, PROFILES_FILE, UNIT_COLOR_FILE

logger = logging.getLogger(__name__)


def _index_by_id(raw: dict | list) -> tuple[dict[str, dict], dict[int, dict]]:
    """Normalize dict- or list-shaped JSON records into str-keyed and int-keyed maps."""
    if isinstance(raw, dict):
        return raw, {int(k): v for k, v in raw.items()}
    return {str(item["id"]): item for item in raw}, {item["id"]: item for item in raw}


class GameDataManager:
    """
    Singleton manager for game data (characters, units, profiles).
    Provides shared access and helper methods used across multiple cogs.
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if GameDataManager._initialized:
            return

        self.characters: dict[str, dict] = {}  # id (str) -> char data
        self.characters_by_int: dict[int, dict] = {}  # id (int) -> char data
        self.unit_colors: dict[str, str] = {}  # id (str) -> color hex
        self.unit_colors_by_int: dict[int, str] = {}  # id (int) -> color hex
        self.nicknames: dict[str, list] = {}  # id (str) -> list of nickname strings
        self.profiles: dict[int, dict] = {}  # id (int) -> profile data
        self._search_names: list[tuple[int, dict, list[str]]] = []

        self._load_data()
        GameDataManager._initialized = True

    def _load_data(self):
        """Load character, unit, and profile data from JSON files atomically."""
        new_characters: dict[str, dict] = {}
        new_characters_by_int: dict[int, dict] = {}
        new_unit_colors: dict[str, str] = {}
        new_unit_colors_by_int: dict[int, str] = {}
        new_nicknames: dict[str, list] = {}
        new_profiles: dict[int, dict] = {}
        try:
            with open(CHARACTERS_FILE, encoding="utf-8") as f:
                new_characters, new_characters_by_int = _index_by_id(json.load(f))

            with open(UNIT_COLOR_FILE, encoding="utf-8") as f:
                units_str, units_int = _index_by_id(json.load(f))
            new_unit_colors = {k: v.get("colorCode", "#5865F2") for k, v in units_str.items()}
            new_unit_colors_by_int = {
                k: v.get("colorCode", "#5865F2") for k, v in units_int.items()
            }

        except FileNotFoundError as e:
            logger.error("GameDataManager: Missing file: %s", e.filename)
        except Exception as e:
            logger.error("GameDataManager: Failed to load data: %s", e)

        # Nicknames (optional file)
        try:
            if NICKNAMES_FILE.exists():
                with open(NICKNAMES_FILE, encoding="utf-8") as f:
                    new_nicknames = json.load(f)
        except Exception as e:
            logger.warning("GameDataManager: Failed to load nicknames: %s", e)
            new_nicknames = {}

        # Profiles (optional file)
        try:
            if PROFILES_FILE.exists():
                with open(PROFILES_FILE, encoding="utf-8") as f:
                    raw_profiles = json.load(f)
                    new_profiles = {p["characterId"]: p for p in raw_profiles}
        except Exception as e:
            logger.warning("GameDataManager: Failed to load profiles: %s", e)
            new_profiles = {}

        # Precompute character name variants for fast get_character_by_name() lookups
        search_names: list[tuple[int, dict, list[str]]] = []
        for char_id, char in new_characters_by_int.items():
            given = char.get("givenName", "").lower()
            first = char.get("firstName", "").lower()
            full = f"{first} {given}".strip()
            rev = f"{given} {first}".strip()
            candidates = [n for n in (given, first, full, rev) if n]
            search_names.append((char_id, char, candidates))

        # Atomic assignment
        self.characters = new_characters
        self.characters_by_int = new_characters_by_int
        self.unit_colors = new_unit_colors
        self.unit_colors_by_int = new_unit_colors_by_int
        self.nicknames = new_nicknames
        self.profiles = new_profiles
        self._search_names = search_names

        logger.info(
            "GameDataManager: Loaded %d characters, %d unit colors, %d profiles, nicknames for %d chars",
            len(self.characters),
            len(self.unit_colors),
            len(self.profiles),
            len(self.nicknames),
        )

    def reload(self):
        """Reload data from files (call after updates)."""
        self._load_data()

    def get_profile(self, char_id: int | str) -> dict | None:
        """Get character profile by ID."""
        char_id_int = int(char_id) if isinstance(char_id, str) and char_id.isdigit() else char_id
        if isinstance(char_id_int, int):
            return self.profiles.get(char_id_int)
        return None

    # --- Character Helpers ---

    def get_character(self, char_id: int | str) -> dict | None:
        """Get character data by ID (accepts int or str)."""
        if isinstance(char_id, int):
            return self.characters_by_int.get(char_id)
        return self.characters.get(str(char_id))

    def get_character_name(self, char_id: int | str, full: bool = False) -> str:
        """
        Get character name from ID.

        Args:
            char_id: Character ID (int or str)
            full: If True, return "FirstName GivenName", else just givenName
        """
        char = self.get_character(char_id)
        if not char:
            return f"Character {char_id}"

        if full:
            first = char.get("firstName", "")
            given = char.get("givenName", "")
            return f"{first} {given}".strip() or f"Character {char_id}"

        return char.get("givenName", char.get("firstName", f"Character {char_id}"))

    def get_character_by_name(self, name: str) -> tuple[int | None, dict | None]:
        """
        Find character by name, case-insensitive. Tries, in order: an exact name ("an",
        "shiraishi an", "an shiraishi"), an exact nickname, a name prefix, then any
        partial match. Without the ranking "an" matched Minori H*an*asato before An.

        Returns:
            (char_id, char_data) or (None, None) if not found
        """
        query = name.strip().lower()
        if not query:
            return None, None

        def find(match) -> tuple[int | None, dict | None]:
            for char_id, char, candidates in self._search_names:
                if any(match(n) for n in candidates):
                    return char_id, char
            return None, None

        found = find(lambda n: n == query)
        if found[0] is not None:
            return found
        for char_id, char, _ in self._search_names:
            if query in (nick.lower() for nick in self.nicknames.get(str(char_id), [])):
                return char_id, char
        found = find(lambda n: n.startswith(query))
        if found[0] is not None:
            return found
        return find(lambda n: query in n)

    # --- Unit Color Helpers ---

    def get_unit_color(self, char_id: int | str) -> int:
        """Get unit color as Discord-compatible integer (e.g., 0x5865F2)."""
        color_hex = self.get_unit_color_hex(char_id).lstrip("#")
        try:
            return int(color_hex, 16)
        except ValueError:
            return 0x5865F2  # Discord blurple fallback

    def get_unit_color_hex(self, char_id: int | str) -> str:
        """Get unit color as hex string (e.g., '#5865F2')."""
        if isinstance(char_id, int):
            return self.unit_colors_by_int.get(char_id, "#5865F2")
        return self.unit_colors.get(str(char_id), "#5865F2")

    # --- Autocomplete Helper ---

    def character_autocomplete_choices(
        self, current: str, max_id: int | None = None, limit: int = 25
    ) -> list[app_commands.Choice[str]]:
        """
        Generate autocomplete choices for character selection.

        Args:
            current: Current user input
            max_id: Only include characters with ID <= max_id (e.g., 26 for main chars)
            limit: Maximum choices to return (Discord limit is 25)
        """
        choices = []
        search = current.lower()

        for char_id, char in self.characters_by_int.items():
            if max_id and char_id > max_id:
                continue

            given = char.get("givenName", "")
            first = char.get("firstName", "")
            full_name = f"{first} {given}".strip()

            if search in full_name.lower() or search in given.lower():
                choices.append(
                    app_commands.Choice(name=full_name or given or first, value=str(char_id))
                )

                if len(choices) >= limit:
                    break

        return choices


# Global singleton instance
game_data = GameDataManager()


# Convenience functions for direct import
def get_character_name(char_id: int | str, full: bool = False) -> str:
    """Get character name from ID."""
    return game_data.get_character_name(char_id, full)


def get_unit_color(char_id: int | str) -> int:
    """Get unit color as Discord-compatible integer."""
    return game_data.get_unit_color(char_id)


def get_unit_color_hex(char_id: int | str) -> str:
    """Get unit color as hex string."""
    return game_data.get_unit_color_hex(char_id)


def character_autocomplete(
    current: str, max_id: int | None = None
) -> list[app_commands.Choice[str]]:
    """Generate character autocomplete choices."""
    return game_data.character_autocomplete_choices(current, max_id)
