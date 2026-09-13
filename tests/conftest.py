import asyncio
import os
import tempfile
import pytest
from pathlib import Path
import discord
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


@pytest.fixture(autouse=True)
async def cleanup_shared_session():
    """Ensure aiohttp ClientSession is cleanly closed after tests."""
    yield
    await SharedResources.close_session()
