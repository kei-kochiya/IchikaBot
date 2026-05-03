"""
Game Data Utility - Centralized access to character and unit data.
Used by multiple cogs to avoid code duplication.
"""
import json
import logging
from pathlib import Path
from typing import Any
from discord import app_commands

from config import CHARACTERS_FILE, UNIT_COLOR_FILE, NICKNAMES_FILE

logger = logging.getLogger(__name__)


class GameDataManager:
    """
    Singleton manager for game data (characters, units).
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
        
        self._load_data()
        GameDataManager._initialized = True
    
    def _load_data(self):
        """Load character and unit data from JSON files."""
        try:
            with open(CHARACTERS_FILE, 'r', encoding='utf-8') as f:
                chars = json.load(f)
                
            # Handle both dict and list formats
            if isinstance(chars, dict):
                self.characters = chars
                self.characters_by_int = {int(k): v for k, v in chars.items()}
            else:
                # List format - index by 'id' field
                self.characters = {str(c['id']): c for c in chars}
                self.characters_by_int = {c['id']: c for c in chars}
            
            with open(UNIT_COLOR_FILE, 'r', encoding='utf-8') as f:
                units = json.load(f)
            
            # Handle both dict and list formats
            if isinstance(units, dict):
                self.unit_colors = {k: v.get('colorCode', '#5865F2') for k, v in units.items()}
                self.unit_colors_by_int = {int(k): v.get('colorCode', '#5865F2') for k, v in units.items()}
            else:
                self.unit_colors = {str(u['id']): u.get('colorCode', '#5865F2') for u in units}
                self.unit_colors_by_int = {u['id']: u.get('colorCode', '#5865F2') for u in units}
            
            logger.info("GameDataManager: Loaded %d characters, %d unit colors",
                       len(self.characters), len(self.unit_colors))

        except FileNotFoundError as e:
            logger.error("GameDataManager: Missing file: %s", e.filename)
        except Exception as e:
            logger.error("GameDataManager: Failed to load data: %s", e)

        # Nicknames (optional file)
        try:
            if NICKNAMES_FILE.exists():
                with open(NICKNAMES_FILE, 'r', encoding='utf-8') as f:
                    self.nicknames = json.load(f)
                logger.info("GameDataManager: Loaded nicknames for %d characters", len(self.nicknames))
        except Exception as e:
            logger.warning("GameDataManager: Failed to load nicknames: %s", e)
            self.nicknames = {}
    
    def reload(self):
        """Reload data from files (call after updates)."""
        self._load_data()
    
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
            first = char.get('firstName', '')
            given = char.get('givenName', '')
            return f"{first} {given}".strip() or f"Character {char_id}"
        
        return char.get('givenName', char.get('firstName', f"Character {char_id}"))
    
    def get_character_by_name(self, name: str) -> tuple[int | None, dict | None]:
        """
        Find character by name (case-insensitive partial match).
        
        Returns:
            (char_id, char_data) or (None, None) if not found
        """
        name_lower = name.lower()
        for char_id, char in self.characters_by_int.items():
            given = char.get('givenName', '').lower()
            first = char.get('firstName', '').lower()
            full = f"{first} {given}".strip()
            
            if name_lower in given or name_lower in first or name_lower in full:
                return char_id, char
        
        return None, None
    
    # --- Unit Color Helpers ---
    
    def get_unit_color(self, char_id: int | str) -> int:
        """
        Get unit color as Discord-compatible integer.
        
        Args:
            char_id: Character ID
            
        Returns:
            Color as integer (e.g., 0x5865F2)
        """
        if isinstance(char_id, int):
            color_hex = self.unit_colors_by_int.get(char_id, '#5865F2')
        else:
            color_hex = self.unit_colors.get(str(char_id), '#5865F2')
        
        if color_hex.startswith('#'):
            color_hex = color_hex[1:]
        
        try:
            return int(color_hex, 16)
        except ValueError:
            return 0x5865F2  # Discord blurple fallback
    
    def get_unit_color_hex(self, char_id: int | str) -> str:
        """Get unit color as hex string (e.g., '#5865F2')."""
        if isinstance(char_id, int):
            return self.unit_colors_by_int.get(char_id, '#5865F2')
        return self.unit_colors.get(str(char_id), '#5865F2')
    
    # --- Autocomplete Helper ---
    
    def character_autocomplete_choices(
        self, 
        current: str, 
        max_id: int | None = None,
        limit: int = 25
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
            
            given = char.get('givenName', '')
            first = char.get('firstName', '')
            full_name = f"{first} {given}".strip()
            
            if search in full_name.lower() or search in given.lower():
                choices.append(app_commands.Choice(
                    name=full_name or given or first,
                    value=str(char_id)
                ))
                
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
    current: str,
    max_id: int | None = None
) -> list[app_commands.Choice[str]]:
    """Generate character autocomplete choices."""
    return game_data.character_autocomplete_choices(current, max_id)
