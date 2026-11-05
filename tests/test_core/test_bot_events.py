from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord.ext import commands

from bot import on_command_error, on_message


@pytest.mark.asyncio
async def test_on_message_ignores_bot_messages():
    message = MagicMock(spec=discord.Message)
    message.author.bot = True
    message.content = "-g test"

    with patch("bot.bot.process_commands", new_callable=AsyncMock) as mock_process:
        await on_message(message)
        mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_skips_game_guess_prefix():
    # Both '-g answer' and '-G answer' and '-g' alone should not trigger command processing
    for content in ["-g ichika", "-G miku", "-g   kanade", "-g"]:
        message = MagicMock(spec=discord.Message)
        message.author.bot = False
        message.content = content

        with patch("bot.bot.process_commands", new_callable=AsyncMock) as mock_process:
            await on_message(message)
            mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_processes_normal_commands():
    for content in ["!help", "-play roki", "-skip"]:
        message = MagicMock(spec=discord.Message)
        message.author.bot = False
        message.content = content

        with patch("bot.bot.process_commands", new_callable=AsyncMock) as mock_process:
            await on_message(message)
            mock_process.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_on_command_error_ignores_command_not_found():
    ctx = MagicMock(spec=commands.Context)
    ctx.command = None
    error = commands.CommandNotFound('Command "g" is not found')

    with patch("bot.logger.error") as mock_logger:
        await on_command_error(ctx, error)
        mock_logger.assert_not_called()


@pytest.mark.asyncio
async def test_on_command_error_logs_other_errors():
    ctx = MagicMock(spec=commands.Context)
    ctx.command = MagicMock()
    ctx.command.__str__.return_value = "play"
    error = commands.BadArgument("Invalid URL")

    with patch("bot.logger.error") as mock_logger:
        await on_command_error(ctx, error)
        mock_logger.assert_called_once()


@pytest.mark.asyncio
async def test_sync_command_is_owner_only():
    from bot import bot

    sync_cmd = bot.get_command("sync")
    assert sync_cmd is not None and len(sync_cmd.checks) == 1

    ctx = MagicMock()  # Context.bot is an instance attribute, so a spec'd mock lacks it
    ctx.bot.is_owner = AsyncMock(return_value=False)
    with pytest.raises(commands.NotOwner):
        await sync_cmd.checks[0](ctx)

    ctx.bot.is_owner = AsyncMock(return_value=True)
    assert await sync_cmd.checks[0](ctx) is True


@pytest.mark.asyncio
async def test_on_command_error_quietly_ignores_failed_checks():
    ctx = MagicMock(spec=commands.Context)
    ctx.command = MagicMock()
    ctx.send = AsyncMock()

    with patch("bot.logger.error") as mock_logger:
        await on_command_error(ctx, commands.NotOwner())

    mock_logger.assert_not_called()
    ctx.send.assert_not_called()


@pytest.mark.asyncio
async def test_on_command_error_explains_guild_only_commands():
    ctx = MagicMock(spec=commands.Context)
    ctx.command = MagicMock()
    ctx.send = AsyncMock()

    await on_command_error(ctx, commands.NoPrivateMessage())

    ctx.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_ready_syncs_commands_only_once():
    import bot as bot_module

    bot_module._commands_synced = False
    with (
        patch.object(bot_module.bot.tree, "sync", new_callable=AsyncMock, return_value=[]) as sync,
        patch.object(type(bot_module.bot), "user", MagicMock()),
    ):
        await bot_module.on_ready()
        await bot_module.on_ready()  # e.g. after a gateway reconnect

    sync.assert_awaited_once()


def _interaction(done: bool):
    interaction = MagicMock()
    interaction.response.is_done.return_value = done
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.command.qualified_name = "gacha pull"
    return interaction


def _invoke_error():
    from discord import app_commands

    command = MagicMock()
    command.name = "pull"
    return app_commands.CommandInvokeError(command, ValueError("boom"))


@pytest.mark.asyncio
async def test_slash_error_after_defer_tells_the_user():
    from bot import bot

    interaction = _interaction(done=True)  # command had already deferred
    with patch("bot.logger.error") as mock_logger:
        await bot.tree.on_error(interaction, _invoke_error())

    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.kwargs["ephemeral"] is True
    # The traceback of the original exception is kept
    assert isinstance(mock_logger.call_args.kwargs["exc_info"], ValueError)


@pytest.mark.asyncio
async def test_slash_error_before_any_reply_answers_the_interaction():
    from bot import bot

    interaction = _interaction(done=False)
    with patch("bot.logger.error"):
        await bot.tree.on_error(interaction, _invoke_error())

    interaction.response.send_message.assert_awaited_once()
    interaction.followup.send.assert_not_called()


@pytest.mark.asyncio
async def test_slash_check_failure_is_not_answered_twice():
    from discord import app_commands

    from bot import bot

    # A per-command handler already answered "missing permissions"
    interaction = _interaction(done=True)
    await bot.tree.on_error(interaction, app_commands.MissingPermissions(["manage_guild"]))
    interaction.followup.send.assert_not_called()
    interaction.response.send_message.assert_not_called()

    # Nobody answered (e.g. a command without its own handler): explain it once
    interaction = _interaction(done=False)
    await bot.tree.on_error(interaction, app_commands.MissingPermissions(["administrator"]))
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_prefix_command_crash_is_logged_with_traceback_and_reported():
    ctx = MagicMock(spec=commands.Context)
    ctx.command = MagicMock()
    ctx.send = AsyncMock()
    original = RuntimeError("boom")

    with patch("bot.logger.error") as mock_logger:
        await on_command_error(ctx, commands.CommandInvokeError(original))

    ctx.send.assert_awaited_once()
    assert mock_logger.call_args.kwargs["exc_info"] is original
