import threading
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.system.data_updater import DataUpdaterCog
from utils.core.autoupdater import auto_updater
from utils.data.card_data import card_data
from utils.data.event_data import event_data
from utils.data.song_data import song_data


@pytest.fixture
def interaction():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def run_all_updates(monkeypatch):
    """Replace the cog's `run_all_updates` so no test can ever reach the network.

    Patched through the class's own module globals rather than a "cogs...." string: other
    tests load/unload the extension, which makes the string resolve to a *different* module
    object than the one DataUpdaterCog's methods use.
    """
    mock = AsyncMock(side_effect=AssertionError("run_all_updates called without a test result"))
    monkeypatch.setitem(DataUpdaterCog.__init__.__globals__, "run_all_updates", mock)
    return mock


@pytest.mark.asyncio
async def test_manual_update_is_refused_while_another_run_is_in_progress(
    mock_bot, interaction, run_all_updates
):
    cog = DataUpdaterCog(mock_bot)

    async with auto_updater._lock:
        await cog.manual_update.callback(cog, interaction)

    run_all_updates.assert_not_called()
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_manual_update_reloads_data_when_something_changed(
    mock_bot, interaction, run_all_updates
):
    cog = DataUpdaterCog(mock_bot)
    results = {
        "cards_jp": (True, "Updated: 1 -> 2 items"),
        "events_jp": (True, "Already up to date"),
    }
    run_all_updates.side_effect = None
    run_all_updates.return_value = results

    with patch.object(cog, "_notify_cogs_to_reload", new_callable=AsyncMock) as notify:
        await cog.manual_update.callback(cog, interaction)

    notify.assert_awaited_once_with(results)
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_update_skips_reload_when_nothing_changed(
    mock_bot, interaction, run_all_updates
):
    cog = DataUpdaterCog(mock_bot)
    run_all_updates.side_effect = None
    run_all_updates.return_value = {"cards_jp": (True, "Already up to date")}

    with patch.object(cog, "_notify_cogs_to_reload", new_callable=AsyncMock) as notify:
        await cog.manual_update.callback(cog, interaction)

    notify.assert_not_called()


@pytest.mark.asyncio
async def test_singleton_reloads_run_off_the_event_loop_thread(mock_bot, monkeypatch):
    cog = DataUpdaterCog(mock_bot)
    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    for name, singleton in (("cards", card_data), ("songs", song_data), ("events", event_data)):
        monkeypatch.setattr(
            singleton, "reload", lambda name=name: seen.setdefault(name, threading.get_ident())
        )

    await cog._notify_cogs_to_reload(
        {
            "cards_jp": (True, "Updated: 1 -> 2 items"),
            "musics_jp": (True, "Updated: 1 -> 2 items"),
            "events_jp": (True, "Updated: 1 -> 2 items"),
        }
    )

    assert set(seen) == {"cards", "songs", "events"}
    assert all(thread != loop_thread for thread in seen.values())
