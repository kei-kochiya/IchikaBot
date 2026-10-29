from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.social.card_of_day import FAILURE_BACKOFF_SECONDS, CardOfDayCog
from utils.core import database


@pytest.fixture
def cog(temp_db, mock_bot, monkeypatch):
    # Patch via the class's own module globals: a "cogs...." string path can resolve to a
    # different module object once another test has unloaded the extension (and would then
    # let the real image download run).
    monkeypatch.setitem(
        CardOfDayCog.__init__.__globals__,
        "get_card_image_path",
        AsyncMock(return_value=None),
    )
    cog = CardOfDayCog(mock_bot)
    cog.settings = {"123": {"channel_id": 999, "interval_hours": 1, "last_post_ts": 0}}
    return cog


def _forbidden() -> discord.Forbidden:
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Permissions")


@pytest.mark.asyncio
async def test_failed_post_backs_off_instead_of_retrying_every_minute(cog, monkeypatch):
    channel = MagicMock()
    channel.send = AsyncMock(side_effect=_forbidden())
    monkeypatch.setattr(cog.bot, "get_channel", lambda _cid: channel)

    await cog.card_loop.coro(cog)
    assert channel.send.await_count == 1
    assert "123" in cog._retry_after

    await cog.card_loop.coro(cog)  # the next minute's tick must leave this guild alone
    assert channel.send.await_count == 1

    # ...until the back-off has elapsed
    cog._retry_after["123"] = 0
    await cog.card_loop.coro(cog)
    assert channel.send.await_count == 2
    assert FAILURE_BACKOFF_SECONDS > 60


@pytest.mark.asyncio
async def test_successful_post_clears_backoff_and_persists_timestamp(cog, monkeypatch):
    channel = MagicMock()
    channel.send = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(cog.bot, "get_channel", lambda _cid: channel)
    cog._retry_after["123"] = 0

    await cog.card_loop.coro(cog)

    channel.send.assert_awaited_once()
    assert "123" not in cog._retry_after
    assert cog.settings["123"]["last_post_ts"] > 0
    stored = await database.get_setting(123, "cotd_last_post_ts")
    assert float(stored) == cog.settings["123"]["last_post_ts"]


@pytest.mark.asyncio
async def test_guild_config_is_saved_in_one_call(cog):
    await cog._save_guild_cfg(7, {"channel_id": 5, "interval_hours": 2.5, "last_post_ts": 0})

    rows = await database.get_all_settings_prefix("cotd_")
    assert rows[7] == {"channel_id": "5", "interval_hours": "2.5", "last_post_ts": "0"}
