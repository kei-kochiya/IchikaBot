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
