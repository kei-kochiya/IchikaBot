"""Command-flow & background-loop integration tests for Birthday, CardOfDay, and DataUpdater."""

import threading
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.social.birthday import BirthdayCog
from cogs.social.card_of_day import FAILURE_BACKOFF_SECONDS, CardOfDayCog
from cogs.system.data_updater import DataUpdaterCog
from utils.core import database
from utils.core.autoupdater import auto_updater
from utils.data.card_data import card_data
from utils.data.event_data import event_data
from utils.data.song_data import song_data
from utils.social.birthday_helpers import (
    _days_until_mm_dd,
    get_characters_with_birthday,
    resolve_character_and_countdown,
)
from utils.social.birthday_ui import BirthdayCardView

# ── Birthday ──────────────────────────────────────────────────────────────────


async def test_birthday_commands_persistence_and_card_view(
    mock_bot, make_interaction, monkeypatch, temp_db
):
    cog = BirthdayCog(mock_bot)

    # /birthday channel & /birthday disable persist in SQLite
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = 4242
    ch.mention = "<#4242>"
    inter_set = make_interaction(guild_id=77)
    await cog.set_channel.callback(cog, inter_set, channel=ch)
    assert await database.get_setting(77, "birthday_channel") == "4242"

    # /birthday check returns calendar embed
    inter_check = make_interaction()
    await cog.check_birthday_slash.callback(cog, inter_check)
    assert len(inter_check.last_reply["embed"].fields) >= 2

    # /birthday countdown and /birthday test answer via interaction followup (not channel.send)
    embed = discord.Embed(title="bday")
    g = BirthdayCog.cog_load.__globals__
    monkeypatch.setitem(
        g, "prepare_daily_card_message", AsyncMock(return_value=(embed, None, None))
    )
    monkeypatch.setitem(g, "prepare_birthday_message", AsyncMock(return_value=(embed, None, None)))

    inter_cd = make_interaction()
    await cog.countdown_slash.callback(cog, inter_cd, character="Ichika")
    assert inter_cd.last_reply["embed"] is embed and not inter_cd.channel.messages

    inter_preview = make_interaction()
    await cog.test_birthday.callback(cog, inter_preview, character="1")
    assert inter_preview.last_reply["embed"] is embed and not inter_preview.channel.messages

    # No cards for character still answers the deferred interaction
    monkeypatch.setitem(g, "prepare_daily_card_message", AsyncMock(return_value=(None, None, None)))
    inter_nocard = make_interaction()
    await cog.countdown_slash.callback(cog, inter_nocard, character="1")
    assert "card" in inter_nocard.last_reply["content"]

    # BirthdayCardView steps Older/Newer via deferred edit
    cards = [
        {"id": 102, "characterId": 1, "assetbundleName": "b2", "releaseAt": 1700000000000},
        {"id": 101, "characterId": 1, "assetbundleName": "b1", "releaseAt": 1600000000000},
    ]
    view = BirthdayCardView({"id": "1", "unit": "leo_need"}, cards, current_index=0)
    monkeypatch.setattr(
        "utils.media.image_helper.get_card_image_path", AsyncMock(return_value=None)
    )
    btn = make_interaction()
    btn.message = MagicMock(spec=discord.Message, embeds=[embed], attachments=[])
    await view.prev_callback(btn)
    assert view.current_index == 1 and btn.response.deferred and len(btn.edits) == 1
    await view.next_callback(make_interaction())
    assert view.current_index == 0

    # /birthday disable cleans SQLite
    inter_dis = make_interaction(guild_id=77)
    await cog.disable_birthday.callback(cog, inter_dis)
    assert await database.get_setting(77, "birthday_channel") is None


async def test_birthday_daily_loop_and_date_math(mock_bot, monkeypatch):
    # Leap-day handling + lookup helpers
    assert (
        _days_until_mm_dd("02-29", date(2025, 3, 1), min_days=1)
        == (date(2028, 2, 29) - date(2025, 3, 1)).days
    )
    assert len(get_characters_with_birthday("08-11")) >= 1
    assert get_characters_with_birthday("99-99") == []
    assert resolve_character_and_countdown("Ichika")[1]["id"] == "1"
    assert resolve_character_and_countdown("UnknownXYZ") is not None

    # Scheduled loop survives settings mutating mid-run
    embed = discord.Embed(title="daily")
    g = BirthdayCog.cog_load.__globals__
    monkeypatch.setitem(g, "get_characters_with_birthday", lambda _today: [])
    monkeypatch.setitem(g, "resolve_character_and_countdown", lambda _c: (3, {"id": "1"}))
    monkeypatch.setitem(
        g, "prepare_daily_card_message", AsyncMock(return_value=(embed, None, None))
    )

    cog = BirthdayCog(mock_bot)
    cog.settings = {"1": 11, "2": 22, "3": 33}

    def mutate(**_kwargs):
        cog.settings.pop("3", None)
        cog.settings["4"] = 44

    channel = MagicMock()
    channel.send = AsyncMock(side_effect=mutate)
    monkeypatch.setattr(cog.bot, "get_channel", lambda _cid: channel)

    await cog.birthday_check_task.coro(cog)
    assert channel.send.await_count == 3


# ── Card of the Day ───────────────────────────────────────────────────────────


async def test_cotd_commands_and_loop_backoff(mock_bot, make_interaction, monkeypatch, temp_db):
    monkeypatch.setitem(
        CardOfDayCog.__init__.__globals__,
        "get_card_image_path",
        AsyncMock(return_value=None),
    )
    cog = CardOfDayCog(mock_bot)

    ch = MagicMock(spec=discord.TextChannel)
    ch.id = 999
    ch.mention = "<#999>"

    # /cotd channel, interval, status, now, disable
    await cog.set_channel.callback(cog, make_interaction(guild_id=123), channel=ch)
    await cog.set_interval.callback(cog, make_interaction(guild_id=123), hours=2.5)
    assert (await database.get_all_settings_prefix("cotd_"))[123]["interval_hours"] == "2.5"

    inter_bad = make_interaction(guild_id=123)
    await cog.set_interval.callback(cog, inter_bad, hours=99.0)
    assert inter_bad.last_reply["ephemeral"] is True

    inter_status = make_interaction(guild_id=123)
    await cog.status.callback(cog, inter_status)
    assert isinstance(inter_status.last_reply["embed"], discord.Embed)

    inter_now = make_interaction(guild_id=123)
    await cog.send_now.callback(cog, inter_now)
    assert isinstance(inter_now.last_reply["embed"], discord.Embed)

    # Loop backs off after Forbidden, then recovers and persists timestamp
    cog.settings["123"]["last_post_ts"] = 0
    channel = MagicMock()
    channel.send = AsyncMock(
        side_effect=discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "No perms")
    )
    monkeypatch.setattr(cog.bot, "get_channel", lambda _cid: channel)

    await cog.card_loop.coro(cog)
    await cog.card_loop.coro(cog)
    assert channel.send.await_count == 1
    assert "123" in cog._retry_after and FAILURE_BACKOFF_SECONDS > 60

    cog._retry_after["123"] = 0
    channel.send = AsyncMock(return_value=MagicMock())
    await cog.card_loop.coro(cog)
    assert channel.send.await_count == 1 and "123" not in cog._retry_after
    assert float(await database.get_setting(123, "cotd_last_post_ts")) > 0

    await cog.disable.callback(cog, make_interaction(guild_id=123))
    assert 123 not in await database.get_all_settings_prefix("cotd_")


# ── Data Updater ──────────────────────────────────────────────────────────────


async def test_data_updater_manual_run_lock_and_threaded_reload(
    mock_bot, make_interaction, monkeypatch
):
    cog = DataUpdaterCog(mock_bot)
    run_mock = AsyncMock()
    monkeypatch.setitem(DataUpdaterCog.__init__.__globals__, "run_all_updates", run_mock)

    # Refused while busy
    inter_busy = make_interaction()
    async with auto_updater._lock:
        await cog.manual_update.callback(cog, inter_busy)
    run_mock.assert_not_called()
    assert inter_busy.last_reply["ephemeral"] is True

    # Skips reload when nothing changed
    run_mock.return_value = {"cards_jp": (True, "Already up to date")}
    with patch.object(cog, "_notify_cogs_to_reload", new_callable=AsyncMock) as notify:
        await cog.manual_update.callback(cog, make_interaction())
    notify.assert_not_called()

    # Triggers reload off the event-loop thread when sources updated
    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}
    for name, singleton in (("cards", card_data), ("songs", song_data), ("events", event_data)):
        monkeypatch.setattr(
            singleton, "reload", lambda name=name: seen.setdefault(name, threading.get_ident())
        )

    run_mock.return_value = {
        "cards_jp": (True, "Updated: 1 -> 2 items"),
        "musics_jp": (True, "Updated: 1 -> 2 items"),
        "events_jp": (True, "Updated: 1 -> 2 items"),
    }
    inter_ok = make_interaction()
    await cog.manual_update.callback(cog, inter_ok)
    assert set(seen) == {"cards", "songs", "events"}
    assert all(tid != loop_thread for tid in seen.values())
    assert isinstance(inter_ok.last_reply["embed"], discord.Embed)
