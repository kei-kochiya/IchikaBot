"""
Centralized configuration for the Discord bot.
Contains all constants, paths, and shared resources.
"""
import aiohttp
import asyncio
from pathlib import Path

# --- Paths ---
DB_FILE = Path('./ichika.db')

GAME_DATA_PATH = Path('./gameData')
STATIC_DATA_PATH = GAME_DATA_PATH / 'static'
JP_DATA_PATH = GAME_DATA_PATH / 'JP_data'
EN_DATA_PATH = GAME_DATA_PATH / 'EN_data'

CACHE_DIR = Path('./.gachacache')
TEMP_DIR = CACHE_DIR / 'temp'
ASSETS_PATH = Path('./assets')
AUDIO_DIR = Path('./music')

# Static files (not updated)
CHARACTERS_FILE = STATIC_DATA_PATH / 'gameCharacters.json'
UNIT_COLOR_FILE = STATIC_DATA_PATH / 'gameCharacterUnits.json'
NICKNAMES_FILE = STATIC_DATA_PATH / 'nicknames.json'
PROFILES_FILE = STATIC_DATA_PATH / 'characterProfiles.json'

# JP Data files
CARDS_FILE_JP = JP_DATA_PATH / 'cards.json'
MUSICS_FILE_JP = JP_DATA_PATH / 'musics.json'
MUSIC_DIFFICULTIES_FILE_JP = JP_DATA_PATH / 'musicDifficulties.json'
STAMPS_FILE_JP = JP_DATA_PATH / 'stamps.json'
EVENTS_FILE_JP = JP_DATA_PATH / 'events.json'

# EN Data files
CARDS_FILE_EN = EN_DATA_PATH / 'cards.json'
MUSICS_FILE_EN = EN_DATA_PATH / 'musics.json'
MUSIC_DIFFICULTIES_FILE_EN = EN_DATA_PATH / 'musicDifficulties.json'
STAMPS_FILE_EN = EN_DATA_PATH / 'stamps.json'
EVENTS_FILE_EN = EN_DATA_PATH / 'events.json'

# Legacy aliases for backwards compatibility
CARDS_FILE = CARDS_FILE_JP
MUSICS_FILE = MUSICS_FILE_JP
MUSIC_DIFFICULTIES_FILE = MUSIC_DIFFICULTIES_FILE_JP
STAMPS_FILE = STAMPS_FILE_JP
EVENTS_FILE = EVENTS_FILE_JP

PITY_FILE = Path('./pityData.json')

# Rarity display icons
RARITY_ICONS = {
    'rarity_1': '★☆☆☆',
    'rarity_2': '★★☆☆',
    'rarity_3': '★★★☆',
    'rarity_4': '★★★★',
    'rarity_birthday': '🎂 Birthday'
}

# Birthday Announcements
BIRTHDAY_SETTINGS_FILE = GAME_DATA_PATH / 'birthdaySettings.json'

# Card of the Day
CARD_OF_DAY_SETTINGS_FILE = GAME_DATA_PATH / 'cardOfDaySettings.json'

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
# Cache grows without bound; manage disk space manually.

# --- Card Update Settings ---
CARD_UPDATE_INTERVAL_HOURS = 6

# JP Data Update URLs
CARD_DATA_URL_JP = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/cards.json'
MUSICS_DATA_URL_JP = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/musics.json'
MUSIC_DIFFICULTIES_URL_JP = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/musicDifficulties.json'
STAMPS_DATA_URL_JP = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/stamps.json'
EVENTS_DATA_URL_JP = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/events.json'

# EN Data Update URLs
CARD_DATA_URL_EN = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/cards.json'
MUSICS_DATA_URL_EN = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/musics.json'
MUSIC_DIFFICULTIES_URL_EN = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/musicDifficulties.json'
STAMPS_DATA_URL_EN = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/stamps.json'
EVENTS_DATA_URL_EN = 'https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/events.json'

# Legacy aliases (point to JP)
CARD_DATA_URL = CARD_DATA_URL_JP
MUSICS_DATA_URL = MUSICS_DATA_URL_JP
MUSIC_DIFFICULTIES_URL = MUSIC_DIFFICULTIES_URL_JP
STAMPS_DATA_URL = STAMPS_DATA_URL_JP
EVENTS_DATA_URL = EVENTS_DATA_URL_JP


# --- Shared Resources ---
class SharedResources:
    """Singleton for shared resources like aiohttp session."""
    _instance = None
    _session: aiohttp.ClientSession = None
    
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


# Ensure directories exist
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
