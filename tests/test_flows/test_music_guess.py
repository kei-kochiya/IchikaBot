"""Flow & concurrency tests for MusicGuess voice minigame."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.voice.music_guess import MusicGuess


def _game(guild_id: int | None = None, **extra) -> dict:
    game = {
        "norm_targets": ["needle"],
        "display_answer": "needLe",
        "info": {"title_en": "needLe"},
        "guesses": {},
        "wrong_reactions": [],
        "voice_client": None,
        "clip_path": None,
        "timer_task": None,
        "ended": False,
    }
    if guild_id is not None:
        game["guild_id"] = guild_id
    game.update(extra)
    return game


def _guess_message(channel_id: int, author_id: int, content: str) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.channel.id = channel_id
    msg.author.bot = False
    msg.author.id = author_id
    msg.author.mention = f"<@{author_id}>"
    msg.content = content
    msg.reply = AsyncMock()
    msg.add_reaction = AsyncMock()
    return msg


def test_music_guess_independent_comm_and_all_pools(mock_bot):
    cog = MusicGuess(mock_bot)
    files = ["1.mp3", "54.mp3", "63.mp3", "138.mp3"]  # 54 & 63 are commissions
    comm = cog._filter_eligible_songs("comm", files)
    assert set(comm) == {"54.mp3", "63.mp3"}
    assert set(cog._filter_eligible_songs("all", files)) == set(files)

    cog._refresh_available_songs("comm", comm)
    cog._refresh_available_songs("all", files)
    avail_c, played_c = cog._get_pool("comm")
    avail_c.discard("54.mp3")
    played_c.add("54.mp3")
    cog._set_pool("comm", avail_c, played_c)

    assert cog.available_songs_comm == {"63.mp3"}
    assert cog.available_songs_all == set(files) and not cog.played_songs_all


async def test_channel_and_guild_start_locks(mock_bot, make_ctx):
    cog = MusicGuess(mock_bot)

    # Same channel already preparing
    cog.starting_channels[10] = asyncio.get_running_loop().time()
    ctx = make_ctx(channel_id=10, guild_id=99)
    ctx.author.voice = MagicMock(channel=MagicMock())
    await cog.start_game_logic(ctx, pool_type="comm")
    assert "Đang chuẩn bị ván chơi rồi" in ctx.last_reply["content"]
    cog.starting_channels.clear()

    # Another channel in the same guild already running or preparing
    cog.active_games[111] = _game(guild_id=99)
    ctx2 = make_ctx(channel_id=222, guild_id=99)
    ctx2.author.voice = MagicMock(channel=MagicMock())
    with patch.object(cog, "_run_game_start", new_callable=AsyncMock) as run:
        await cog.start_game_logic(ctx2, pool_type="comm")
    run.assert_not_called()
    assert "<#111>" in ctx2.last_reply["content"]

    # Locks are always released even if _run_game_start raises
    cog.active_games.clear()
    ctx3 = make_ctx(channel_id=333, guild_id=444)
    ctx3.author.voice = MagicMock(channel=MagicMock())
    with (
        patch.object(cog, "_run_game_start", new_callable=AsyncMock, side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        await cog.start_game_logic(ctx3, pool_type="comm")
    assert 444 not in cog.starting_guilds and 333 not in cog.starting_channels
    assert 444 not in cog.idle_tasks


async def test_concurrent_winners_and_error_resilience(mock_bot, monkeypatch):
    cog = MusicGuess(mock_bot)

    # Two simultaneous correct guesses: strictly one wins and cleans up once
    cog.active_games[55] = _game(timer_task=MagicMock())
    m1 = _guess_message(55, 101, "-g needle")
    m2 = _guess_message(55, 102, "-g needle")
    m1.add_reaction = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone"))
    with patch.object(cog, "cleanup_game", new_callable=AsyncMock) as cleanup:
        await asyncio.gather(cog.on_message(m1), cog.on_message(m2))
        await asyncio.sleep(0)
    assert m1.reply.call_count + m2.reply.call_count == 1
    cleanup.assert_called_once_with(55)

    # Reply failure on win still frees channel
    cog.active_games[56] = _game()
    m_fail = _guess_message(56, 1, "-g needle")
    m_fail.reply = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=400), "deleted"))
    with patch.object(cog, "cleanup_game", new_callable=AsyncMock) as cleanup:
        await cog.on_message(m_fail)
    cleanup.assert_awaited_once_with(56)

    # Timeout frees channel even if channel.send raises Forbidden
    monkeypatch.setitem(MusicGuess.end_game_timer.__globals__, "GUESS_TIME_LIMIT", 0)
    cog.active_games[57] = _game()
    channel = MagicMock()
    channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no perms"))
    await cog.end_game_timer(channel, 57)
    assert 57 not in cog.active_games


async def test_idle_disconnect_and_alone_in_voice(mock_bot, make_ctx):
    cog = MusicGuess(mock_bot)
    vc = MagicMock()
    vc.is_connected.return_value = True
    vc.is_playing.return_value = False
    vc.guild.id = 88
    vc.channel.name = "General"
    vc.channel.members = [MagicMock(bot=True)]
    vc.disconnect = AsyncMock()

    # Cleanup schedules idle timer instead of immediate disconnect
    cog.active_games[77] = _game(guild_id=88, voice_client=vc)
    await cog.cleanup_game(77)
    vc.disconnect.assert_not_called()
    idle_task = cog.idle_tasks[88]
    assert not idle_task.done()

    # Failed start cancels old idle timer and re-arms a new one
    ctx = make_ctx(channel_id=77, guild_id=88)
    ctx.author.guild.voice_client = vc
    ctx.author.voice = MagicMock(channel=MagicMock())
    with patch.object(cog, "_filter_eligible_songs", return_value=[]):
        await cog.start_game_logic(ctx, pool_type="comm")
    assert idle_task.cancelling() or idle_task.cancelled() or idle_task.done()
    assert 88 in cog.idle_tasks and cog.idle_tasks[88] is not idle_task

    # Bot left alone in voice cancels idle timer and disconnects
    member = MagicMock()
    member.guild.id = 88
    member.guild.voice_client = vc
    await cog.on_voice_state_update(member, MagicMock(), MagicMock())
    vc.disconnect.assert_awaited_once()
    cog.cog_unload()
