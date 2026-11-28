"""Centralized bot configuration: paths, constants, URLs, and shared HTTP session."""

import os
from pathlib import Path

import aiohttp

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent

# Ensure local bin directories are in PATH for container/Pterodactyl environments
_path_entries = os.environ.get("PATH", "").split(os.pathsep)
for _extra_bin in [
    os.path.expanduser("~/.local/bin"),
    "/home/container/.local/bin",
    str(BASE_DIR / "bin"),
]:
    if os.path.isdir(_extra_bin) and _extra_bin not in _path_entries:
        _path_entries.insert(0, _extra_bin)
        os.environ["PATH"] = os.pathsep.join(_path_entries)

DB_FILE = BASE_DIR / "ichika.db"

GAME_DATA_PATH = BASE_DIR / "gameData"
STATIC_DATA_PATH = GAME_DATA_PATH / "static"
JP_DATA_PATH = GAME_DATA_PATH / "JP_data"
EN_DATA_PATH = GAME_DATA_PATH / "EN_data"

CACHE_DIR = BASE_DIR / ".assetcache"
TEMP_DIR = CACHE_DIR / "temp"
ASSETS_PATH = BASE_DIR / "assets"
AUDIO_DIR = BASE_DIR / "music"

# Static files (not updated)
CHARACTERS_FILE = STATIC_DATA_PATH / "gameCharacters.json"
UNIT_COLOR_FILE = STATIC_DATA_PATH / "gameCharacterUnits.json"
NICKNAMES_FILE = STATIC_DATA_PATH / "nicknames.json"
PROFILES_FILE = STATIC_DATA_PATH / "characterProfiles.json"

# JP Data files
CARDS_FILE_JP = JP_DATA_PATH / "cards.json"
MUSICS_FILE_JP = JP_DATA_PATH / "musics.json"
MUSIC_DIFFICULTIES_FILE_JP = JP_DATA_PATH / "musicDifficulties.json"
EVENTS_FILE_JP = JP_DATA_PATH / "events.json"

# EN Data files
CARDS_FILE_EN = EN_DATA_PATH / "cards.json"
MUSICS_FILE_EN = EN_DATA_PATH / "musics.json"
MUSIC_DIFFICULTIES_FILE_EN = EN_DATA_PATH / "musicDifficulties.json"
EVENTS_FILE_EN = EN_DATA_PATH / "events.json"

PITY_FILE = BASE_DIR / "pityData.json"

# Rarity display icons
RARITY_ICONS = {
    "rarity_1": "★☆☆☆",
    "rarity_2": "★★☆☆",
    "rarity_3": "★★★☆",
    "rarity_4": "★★★★",
    "rarity_birthday": "Birthday",
}

# Birthday Announcements
BIRTHDAY_SETTINGS_FILE = GAME_DATA_PATH / "birthdaySettings.json"

# Card of the Day
CARD_OF_DAY_SETTINGS_FILE = GAME_DATA_PATH / "cardOfDaySettings.json"

# Auto-updater bookkeeping (per-source ETag / content hash / item count)
UPDATER_STATE_FILE = GAME_DATA_PATH / "updaterState.json"

# --- Gacha Settings ---
PITY_THRESHOLD = 50
GACHA_RATES = {"rarity_4": 0.06, "rarity_3": 0.15, "rarity_2": 0.79}

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
CARD_DATA_URL_JP = (
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/cards.json"
)
MUSICS_DATA_URL_JP = (
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/musics.json"
)
MUSIC_DIFFICULTIES_URL_JP = (
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/musicDifficulties.json"
)
EVENTS_DATA_URL_JP = (
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/events.json"
)

# EN Data Update URLs
CARD_DATA_URL_EN = (
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/cards.json"
)
MUSICS_DATA_URL_EN = (
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/musics.json"
)
MUSIC_DIFFICULTIES_URL_EN = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/musicDifficulties.json"
EVENTS_DATA_URL_EN = (
    "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/events.json"
)


# --- Shared Resources ---
class SharedResources:
    """Singleton for shared resources like aiohttp session."""

    _instance = None
    _session: aiohttp.ClientSession | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        """Get or create the shared aiohttp session."""
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return cls._session

    @classmethod
    async def close_session(cls):
        """Close the shared session. Call on bot shutdown."""
        session, cls._session = cls._session, None
        if session and not session.closed:
            await session.close()


# Ensure directories exist
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
