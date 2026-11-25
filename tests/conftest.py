from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands

from config import SharedResources
from utils.core import database


class FakeResponse:
    """Minimal stand-in for discord.InteractionResponse tracking defer/send/edit calls."""

    def __init__(self) -> None:
        self._done = False
        self.deferred = False
        self.messages: list[dict] = []
        self.edits: list[dict] = []

    def is_done(self) -> bool:
        return self._done

    async def defer(self, *, ephemeral: bool = False, thinking: bool = True) -> None:
        self._done = True
        self.deferred = True

    async def send_message(self, content=None, **kwargs) -> None:
        self._done = True
        self.messages.append({"content": content, **kwargs})

    async def edit_message(self, **kwargs) -> None:
        self._done = True
        self.edits.append(kwargs)


class FakeFollowup:
    """Minimal stand-in for discord.Webhook followup recording every sent payload."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send(self, content=None, **kwargs):
        payload = {"content": content, **kwargs}
        self.messages.append(payload)
        msg = MagicMock(spec=discord.Message)
        msg.embeds = [kwargs["embed"]] if kwargs.get("embed") else []
        msg.attachments = []
        msg.edit = AsyncMock()
        return msg


class FakeChannel:
    """Minimal text channel recording messages sent directly to it."""

    def __init__(self, channel_id: int = 1001, mention: str = "#general") -> None:
        self.id = channel_id
        self.mention = mention
        self.messages: list[dict] = []

    async def send(self, content=None, **kwargs):
        self.messages.append({"content": content, **kwargs})
        msg = MagicMock(spec=discord.Message)
        msg.embeds = [kwargs["embed"]] if kwargs.get("embed") else []
        msg.attachments = []
        msg.edit = AsyncMock()
        return msg


class FakeInteraction:
    """Lightweight discord.Interaction fake for end-to-end command-flow tests."""

    def __init__(
        self,
        *,
        user_id: int = 101,
        display_name: str = "Tester",
        guild_id: int | None = 5001,
        channel_id: int | None = 1001,
    ) -> None:
        self.user = SimpleNamespace(
            id=user_id,
            name=display_name.lower(),
            display_name=display_name,
            mention=f"<@{user_id}>",
            bot=False,
        )
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.channel = FakeChannel(channel_id) if channel_id is not None else None
        self.created_at = datetime.now(UTC)
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.edits: list[dict] = []
        self.message = None
        self.command = SimpleNamespace(qualified_name="test")

    async def edit_original_response(self, **kwargs) -> None:
        self.edits.append(kwargs)

    @property
    def all_replies(self) -> list[dict]:
        """All replies sent either via response.send_message or followup.send."""
        return [*self.response.messages, *self.followup.messages]

    @property
    def last_reply(self) -> dict:
        assert self.all_replies, "Expected at least one reply on FakeInteraction"
        return self.all_replies[-1]


class _TypingCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeContext:
    """Lightweight commands.Context fake for prefix-command flow tests."""

    def __init__(
        self,
        *,
        user_id: int = 101,
        display_name: str = "Tester",
        guild_id: int = 5001,
        channel_id: int = 1001,
    ) -> None:
        self.author = SimpleNamespace(
            id=user_id,
            name=display_name.lower(),
            display_name=display_name,
            mention=f"<@{user_id}>",
            bot=False,
            guild=SimpleNamespace(id=guild_id, voice_client=None),
            voice=None,
        )
        self.guild = self.author.guild
        self.channel = FakeChannel(channel_id)
        self.messages: list[dict] = []

    def typing(self) -> _TypingCM:
        return _TypingCM()

    async def send(self, content=None, **kwargs):
        self.messages.append({"content": content, **kwargs})
        msg = MagicMock(spec=discord.Message)
        msg.embeds = [kwargs["embed"]] if kwargs.get("embed") else []
        msg.attachments = []
        msg.edit = AsyncMock()
        return msg

    @property
    def last_reply(self) -> dict:
        assert self.messages, "Expected at least one reply on FakeContext"
        return self.messages[-1]


@pytest.fixture
def make_interaction():
    """Factory fixture producing fresh FakeInteraction instances."""
    return FakeInteraction


@pytest.fixture
def make_ctx():
    """Factory fixture producing fresh FakeContext instances."""
    return FakeContext


@pytest.fixture
async def temp_db(monkeypatch, tmp_path):
    """Provide an isolated temporary database for each test."""
    db_file = tmp_path / "test_ichika.db"
    monkeypatch.setattr(database, "DB_FILE", db_file)
    monkeypatch.setattr("config.DB_FILE", db_file)

    await database.init_db()
    yield db_file
    await database.close_db()


@pytest.fixture
def mock_bot():
    """Provide a mock discord.py Bot instance with default configuration."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    return commands.Bot(command_prefix="!", intents=intents, help_command=None)


@pytest.fixture(scope="session", autouse=True)
def ensure_game_data_fixtures():
    """Ensure minimal game data JSON fixtures exist on clean environments (like CI)."""
    import json
    from pathlib import Path

    from utils.data.card_data import card_data
    from utils.data.event_data import event_data
    from utils.data.game_data import game_data
    from utils.data.song_data import song_data

    fixtures = {
        Path("gameData/JP_data/cards.json"): [
            {
                "id": 1,
                "characterId": 1,
                "cardRarityType": "rarity_2",
                "prefix": "Test 2*",
                "assetbundleName": "card_001",
                "attr": "cool",
                "releaseAt": 1600000000000,
            },
            {
                "id": 2,
                "characterId": 1,
                "cardRarityType": "rarity_3",
                "prefix": "Test 3*",
                "assetbundleName": "card_002",
                "attr": "cute",
                "releaseAt": 1600000000000,
            },
            {
                "id": 3,
                "characterId": 1,
                "cardRarityType": "rarity_4",
                "prefix": "Test 4*",
                "assetbundleName": "card_003",
                "attr": "happy",
                "releaseAt": 1600000000000,
            },
            {
                "id": 4,
                "characterId": 1,
                "cardRarityType": "rarity_birthday",
                "prefix": "Birthday",
                "assetbundleName": "card_004",
                "attr": "pure",
                "releaseAt": 1700000000000,
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
                "aggregateAt": 1999999000000,
                "closedAt": 2000000000000,
                "assetbundleName": "event_stella",
            }
        ],
        Path("gameData/EN_data/events.json"): [{"id": 1, "name": "Stella Event EN"}],
        Path("gameData/JP_data/musics.json"): [
            {
                "id": 1,
                "title": "Tell Your World",
                "pronunciation": "teru yua waarudo",
                "composer": "kz",
                "lyricist": "kz",
                "arranger": "kz",
                "publishedAt": 1601424000000,
                "categories": ["mv"],
                "assetbundleName": "jacket_s_001",
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
        game_data.reload()


@pytest.fixture(autouse=True)
async def cleanup_shared_session():
    """Ensure aiohttp ClientSession is cleanly closed after tests."""
    yield
    await SharedResources.close_session()
