import asyncio

import discord
import pytest
from discord.ext import commands

from config import SharedResources
from utils.core import database


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def temp_db(monkeypatch, tmp_path):
    """Provide an isolated temporary database for each test."""
    db_file = tmp_path / "test_ichika.db"
    monkeypatch.setattr(database, "DB_FILE", db_file)
    monkeypatch.setattr("config.DB_FILE", db_file)

    await database.init_db()
    yield db_file


@pytest.fixture
def mock_bot():
    """Provide a mock discord.py Bot instance with default configuration."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
    return bot


@pytest.fixture(scope="session", autouse=True)
def ensure_game_data_fixtures():
    """Ensure minimal game data JSON fixtures exist on clean environments (like CI)."""
    import json
    from pathlib import Path

    from utils.data.card_data import card_data
    from utils.data.event_data import event_data
    from utils.data.game_data import game_data
    from utils.data.song_data import song_data
    from utils.data.stamp_data import stamp_data

    fixtures = {
        Path("gameData/JP_data/cards.json"): [
            {
                "id": 1,
                "characterId": 1,
                "cardRarityType": "rarity_2",
                "prefix": "Test 2*",
                "assetbundleName": "card_001",
                "releaseAt": 1600000000,
            },
            {
                "id": 2,
                "characterId": 1,
                "cardRarityType": "rarity_3",
                "prefix": "Test 3*",
                "assetbundleName": "card_002",
                "releaseAt": 1600000000,
            },
            {
                "id": 3,
                "characterId": 1,
                "cardRarityType": "rarity_4",
                "prefix": "Test 4*",
                "assetbundleName": "card_003",
                "releaseAt": 1600000000,
            },
            {
                "id": 4,
                "characterId": 1,
                "cardRarityType": "rarity_birthday",
                "prefix": "Birthday",
                "assetbundleName": "card_004",
                "releaseAt": 1700000000,
            },
        ],
        Path("gameData/EN_data/cards.json"): [
            {"id": 1, "prefix": "EN Test 2*"},
            {"id": 2, "prefix": "EN Test 3*"},
            {"id": 3, "prefix": "EN Test 4*"},
            {"id": 4, "prefix": "EN Birthday"},
        ],
        Path("gameData/JP_data/events.json"): [
            {
                "id": 1,
                "name": "Stella Event",
                "eventType": "marathon",
                "startAt": 1600000000000,
                "closedAt": 2000000000000,
            }
        ],
        Path("gameData/EN_data/events.json"): [{"id": 1, "name": "Stella Event EN"}],
        Path("gameData/JP_data/musics.json"): [
            {
                "id": 1,
                "title": "Tell Your World",
                "pronunciation": "teru yua waarudo",
                "composer": "kz",
            }
        ],
        Path("gameData/EN_data/musics.json"): [
            {
                "id": 1,
                "title": "Tell Your World",
                "pronunciation": "teru yua waarudo",
                "composer": "kz",
            }
        ],
        Path("gameData/JP_data/musicDifficulties.json"): [
            {"musicId": 1, "musicDifficulty": "master", "playLevel": 26, "totalNoteCount": 800}
        ],
        Path("gameData/JP_data/stamps.json"): [
            {
                "id": 1,
                "name": "Test Stamp",
                "characterId1": 1,
                "stampType": "illustration",
                "assetbundleName": "stamp_001",
            }
        ],
        Path("gameData/EN_data/stamps.json"): [{"id": 1, "name": "Test Stamp EN"}],
    }

    reloaded = False
    for path, data in fixtures.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            reloaded = True

    if reloaded:
        card_data.reload()
        event_data.reload()
        song_data.reload()
        stamp_data.reload()
        game_data.reload()


@pytest.fixture(autouse=True)
async def cleanup_shared_session():
    """Ensure aiohttp ClientSession is cleanly closed after tests."""
    yield
    await SharedResources.close_session()
