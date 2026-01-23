"""
Centralized configuration for the Discord bot.
Contains all constants, paths, and shared resources.
"""
import aiohttp
import asyncio
from pathlib import Path

# --- Paths ---
GAME_DATA_PATH = Path('./gameData')
CACHE_DIR = Path('./.gachacache')
TEMP_DIR = CACHE_DIR / 'temp'
ASSETS_PATH = Path('./assets')
AUDIO_DIR = Path('./music')

CARDS_FILE = GAME_DATA_PATH / 'cards.json'
CHARACTERS_FILE = GAME_DATA_PATH / 'gameCharacters.json'
UNIT_COLOR_FILE = GAME_DATA_PATH / 'gameCharacterUnits.json'
NICKNAMES_FILE = GAME_DATA_PATH / 'nicknames.json'
PITY_FILE = Path('./pityData.json')

# Rarity display icons
RARITY_ICONS = {
    'rarity_1': '★☆☆☆',
    'rarity_2': '★★☆☆',
    'rarity_3': '★★★☆',
    'rarity_4': '★★★★',
    'rarity_birthday': '🎂 Birthday'
}

# Song Database
MUSICS_FILE = GAME_DATA_PATH / 'musics.json'
MUSIC_DIFFICULTIES_FILE = GAME_DATA_PATH / 'musicDifficulties.json'

# Birthday Announcements
BIRTHDAY_SETTINGS_FILE = GAME_DATA_PATH / 'birthdaySettings.json'

# --- Gacha Settings ---
PITY_THRESHOLD = 50
GACHA_RATES = {
    'rarity_4': 0.06,
    'rarity_3': 0.15,
    'rarity_2': 0.79
}

# --- Game Timing ---
GUESS_TIME_LIMIT = 30
MAX_GUESSES = 4
SONG_GUESS_DURATION = 20
SONG_CLIP_DURATION = 20 * 1000  # ms
SONG_SAFE_ZONE = 15 * 1000  # ms

# --- Cache Settings ---
MAX_CACHE_SIZE_MB = 15000
CACHE_CLEANUP_THRESHOLD = 0.9  # Clean when 90% full

# --- Card Update Settings ---
CARD_UPDATE_INTERVAL_HOURS = 6
CARD_DATA_URL = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/cards.json'

# Song Update URLs
MUSICS_DATA_URL = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/musics.json'
MUSIC_DIFFICULTIES_URL = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/musicDifficulties.json'

# Stamp Database
STAMPS_FILE = GAME_DATA_PATH / 'stamps.json'
STAMPS_DATA_URL = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/stamps.json'

# Character Profiles
PROFILES_FILE = GAME_DATA_PATH / 'characterProfiles.json'
PROFILES_DATA_URL = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/characterProfiles.json'

# Events
EVENTS_FILE = GAME_DATA_PATH / 'events.json'
EVENTS_DATA_URL = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/events.json'

# --- Shared Resources ---
class SharedResources:
    """Singleton for shared resources like aiohttp session."""
    _instance = None
    _session: aiohttp.ClientSession = None
    _pity_lock: asyncio.Lock = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        """Get or create the shared aiohttp session."""
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return cls._session
    
    @classmethod
    async def close_session(cls):
        """Close the shared session. Call on bot shutdown."""
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None
    
    @classmethod
    def get_pity_lock(cls) -> asyncio.Lock:
        """Get or create the pity file lock."""
        if cls._pity_lock is None:
            cls._pity_lock = asyncio.Lock()
        return cls._pity_lock


# Ensure directories exist
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
