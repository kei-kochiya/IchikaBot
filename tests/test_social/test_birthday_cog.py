from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.social.birthday import BirthdayCog


def _interaction():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.channel.send = AsyncMock()
    return interaction


def _patch(monkeypatch, name, value):
    # cog modules are re-imported by other tests: patch the functions the cog really uses
    monkeypatch.setitem(BirthdayCog.cog_load.__globals__, name, value)


async def test_countdown_answers_the_interaction(mock_bot, monkeypatch):
    embed = discord.Embed(title="countdown")
    _patch(monkeypatch, "resolve_character_and_countdown", lambda c: (3, {"id": "1"}))
    _patch(monkeypatch, "prepare_daily_card_message", AsyncMock(return_value=(embed, None, None)))
    cog = BirthdayCog(mock_bot)
    interaction = _interaction()

    await cog.countdown_slash.callback(cog, interaction, character=None)

    # Through the followup: channel.send left the deferred "thinking..." up forever
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.kwargs["embed"] is embed
    interaction.channel.send.assert_not_called()


async def test_countdown_without_cards_still_answers(mock_bot, monkeypatch):
    _patch(monkeypatch, "resolve_character_and_countdown", lambda c: (3, {"id": "1"}))
    _patch(monkeypatch, "prepare_daily_card_message", AsyncMock(return_value=(None, None, None)))
    cog = BirthdayCog(mock_bot)
    interaction = _interaction()

    await cog.countdown_slash.callback(cog, interaction, character="1")

    interaction.followup.send.assert_awaited_once()
    assert "card" in interaction.followup.send.call_args.args[0]


async def test_birthday_preview_answers_the_interaction(mock_bot, monkeypatch):
    embed = discord.Embed(title="preview")
    _patch(monkeypatch, "prepare_birthday_message", AsyncMock(return_value=(embed, None, None)))
    cog = BirthdayCog(mock_bot)
    interaction = _interaction()

    await cog.test_birthday.callback(cog, interaction, character="1")

    interaction.followup.send.assert_awaited_once()
    interaction.channel.send.assert_not_called()


async def test_daily_loop_survives_settings_changing_mid_run(mock_bot, monkeypatch):
    embed = discord.Embed(title="daily")
    _patch(monkeypatch, "get_characters_with_birthday", lambda today: [])
    _patch(monkeypatch, "resolve_character_and_countdown", lambda c: (3, {"id": "1"}))
    _patch(monkeypatch, "prepare_daily_card_message", AsyncMock(return_value=(embed, None, None)))
    cog = BirthdayCog(mock_bot)
    cog.settings = {"1": 11, "2": 22, "3": 33}

    def admin_changes_settings(**kwargs):
        # e.g. /birthday disable or /birthday channel while the 00:00 run is posting
        cog.settings.pop("3", None)
        cog.settings["4"] = 44

    channel = MagicMock()
    channel.send = AsyncMock(side_effect=admin_changes_settings)
    monkeypatch.setattr(cog.bot, "get_channel", lambda cid: channel)

    await cog.birthday_check_task.coro(cog)  # used to raise "dictionary changed size"

    assert channel.send.await_count == 3
