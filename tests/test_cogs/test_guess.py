import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.game.guess import GuessCog


def test_build_answer_list():
    bot = MagicMock()
    cog = GuessCog(bot)

    # Character 1 is Ichika Hoshino
    answers = cog.build_answer_list(1)
    assert isinstance(answers, list)
    assert len(answers) > 0
    # Should include 'ichika', 'hoshino', etc.
    assert any("ichika" in a for a in answers)


@pytest.mark.asyncio
async def test_defer_failure_does_not_softlock(mock_bot):
    cog = GuessCog(mock_bot)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel_id = 999999
    # Simulate defer failing (e.g. 3-second timeout -> Unknown interaction)
    interaction.response.defer = AsyncMock(
        side_effect=discord.NotFound(MagicMock(), "Unknown interaction")
    )
    interaction.response.send_message = AsyncMock()

    with pytest.raises(discord.NotFound):
        await cog.guess.callback(cog, interaction, mode="normal")

    # The channel MUST NOT be locked!
    assert 999999 not in cog.active_channels


@pytest.mark.asyncio
async def test_active_channel_auto_recovery(mock_bot):
    cog = GuessCog(mock_bot)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel_id = 888888
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()

    # Simulate a stale game in this channel that started 60s ago
    loop = asyncio.get_running_loop()
    if isinstance(cog.active_channels, dict):
        cog.active_channels[888888] = loop.time() - 60.0
    else:
        # For set-based implementation
        cog.active_channels.add(888888)

    # When someone starts a new game, if auto-recovery is present, it recovers stale channel
    # Mock process_game_image to quickly abort with None
    with patch.object(
        cog, "process_game_image", new_callable=AsyncMock, return_value=(None, None, "")
    ):
        await cog.guess.callback(cog, interaction, mode="normal")

    # If it recovered, defer was called and 888888 is now cleared
    assert 888888 not in cog.active_channels
