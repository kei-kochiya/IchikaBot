import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.voice.music_guess import MusicGuess


def test_music_guess_independent_pools():
    bot = MagicMock()
    cog = MusicGuess(bot)

    # Initially both pools are empty
    avail_comm, played_comm = cog._get_pool("comm")
    avail_all, played_all = cog._get_pool("all")
    assert len(avail_comm) == 0 and len(played_comm) == 0
    assert len(avail_all) == 0 and len(played_all) == 0

    # Test filtering
    mock_files = ["1.mp3", "54.mp3", "63.mp3", "138.mp3"]
    # 54 (Ready Steady) and 63 (needLe) are commissions
    # 1 (Tell Your World) and 138 (KING) are not
    comm_eligible = cog._filter_eligible_songs("comm", mock_files)
    all_eligible = cog._filter_eligible_songs("all", mock_files)

    assert set(comm_eligible) == {"54.mp3", "63.mp3"}
    assert set(all_eligible) == set(mock_files)

    # Refresh comm pool
    cog._refresh_available_songs("comm", comm_eligible)
    avail_comm, played_comm = cog._get_pool("comm")
    assert avail_comm == {"54.mp3", "63.mp3"}
    assert len(played_comm) == 0

    # Verify 'all' pool is untouched
    avail_all, played_all = cog._get_pool("all")
    assert len(avail_all) == 0 and len(played_all) == 0

    # Refresh all pool
    cog._refresh_available_songs("all", all_eligible)
    avail_all, played_all = cog._get_pool("all")
    assert avail_all == set(mock_files)

    # Simulate playing a song in comm pool
    avail_comm.discard("54.mp3")
    played_comm.add("54.mp3")
    cog._set_pool("comm", avail_comm, played_comm)

    # Verify comm pool updated
    assert cog.available_songs_comm == {"63.mp3"}
    assert cog.played_songs_comm == {"54.mp3"}

    # Verify all pool remains completely independent and unmodified
    assert cog.available_songs_all == set(mock_files)
    assert len(cog.played_songs_all) == 0


@pytest.mark.asyncio
async def test_simultaneous_starts_in_channel_rejected(mock_bot):
    cog = MusicGuess(mock_bot)
    ctx1 = MagicMock()
    ctx1.channel.id = 12345
    ctx1.author.voice.channel = MagicMock()
    ctx1.send = AsyncMock()

    ctx2 = MagicMock()
    ctx2.channel.id = 12345
    ctx2.author.voice.channel = MagicMock()
    ctx2.send = AsyncMock()

    # Mark channel 12345 as currently starting
    cog.starting_channels[12345] = asyncio.get_running_loop().time()

    await cog.start_game_logic(ctx2, pool_type="comm")

    ctx2.send.assert_called_once()
    assert "Đang chuẩn bị ván chơi rồi" in ctx2.send.call_args[0][0]


@pytest.mark.asyncio
async def test_race_condition_only_first_guesser_wins(mock_bot):
    cog = MusicGuess(mock_bot)
    channel_id = 55555

    timer_task = MagicMock()
    game = {
        "norm_targets": ["needle"],
        "display_answer": "needLe",
        "info": {"title_ro": "needLe"},
        "guesses": {},
        "wrong_reactions": [],
        "voice_client": None,
        "clip_path": None,
        "timer_task": timer_task,
        "ended": False,
    }
    cog.active_games[channel_id] = game

    msg1 = MagicMock(spec=discord.Message)
    msg1.channel.id = channel_id
    msg1.author.bot = False
    msg1.author.id = 101
    msg1.author.mention = "<@101>"
    msg1.content = "-g needle"
    msg1.reply = AsyncMock()
    msg1.add_reaction = AsyncMock()

    msg2 = MagicMock(spec=discord.Message)
    msg2.channel.id = channel_id
    msg2.author.bot = False
    msg2.author.id = 102
    msg2.author.mention = "<@102>"
    msg2.content = "-g needle"
    msg2.reply = AsyncMock()
    msg2.add_reaction = AsyncMock()

    # Simulate both messages arriving almost concurrently
    with patch.object(cog, "cleanup_game", new_callable=AsyncMock) as mock_cleanup:
        await asyncio.gather(cog.on_message(msg1), cog.on_message(msg2))

        # Only one message should have called reply with winning message!
        replied_count = msg1.reply.call_count + msg2.reply.call_count
        assert replied_count == 1, f"Expected 1 winner reply, but got {replied_count}"
        mock_cleanup.assert_called_once_with(channel_id)


@pytest.mark.asyncio
async def test_idle_disconnect_scheduled_and_cancelled_on_new_game(mock_bot):
    cog = MusicGuess(mock_bot)
    channel_id = 77777
    guild_id = 88888

    vc = MagicMock(spec=discord.VoiceClient)
    vc.is_connected.return_value = True
    vc.is_playing.return_value = False
    vc.guild.id = guild_id
    vc.disconnect = AsyncMock()

    game = {
        "voice_client": vc,
        "timer_task": None,
        "clip_path": None,
        "wrong_reactions": [],
    }
    cog.active_games[channel_id] = game

    # Cleanup should NOT disconnect immediately; it schedules idle task
    await cog.cleanup_game(channel_id)
    vc.disconnect.assert_not_called()
    assert guild_id in cog.idle_tasks
    idle_task = cog.idle_tasks[guild_id]
    assert not idle_task.done()

    # When starting a new game in the same guild, the idle task is cancelled
    ctx = MagicMock()
    ctx.channel.id = channel_id
    ctx.author.guild.id = guild_id
    ctx.author.guild.voice_client = vc
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()

    with (
        patch.object(cog, "_filter_eligible_songs", return_value=[]),
        patch.object(cog, "_refresh_available_songs", return_value=[]),
    ):
        await cog.start_game_logic(ctx, pool_type="comm")

    assert idle_task.cancelling() or idle_task.cancelled() or idle_task.done()
    # That start failed (no songs), so a fresh idle timer must be armed again: otherwise
    # the bot would stay in voice until everyone leaves
    assert guild_id in cog.idle_tasks and cog.idle_tasks[guild_id] is not idle_task
    cog.cog_unload()


def test_song_guess_commands_cannot_be_used_in_dms(mock_bot):
    cog = MusicGuess(mock_bot)

    # Starting a round needs the caller's voice channel and guild: DMs have neither
    assert cog.slash_songguess.guild_only is True
    for command in (
        cog.guess_music,
        cog.guess_music_variant,
        cog.guess_music_all,
        cog.guess_music_all_variant,
    ):
        assert len(command.checks) == 1, f"{command.name} must carry the guild_only check"


@pytest.mark.asyncio
async def test_correct_guess_reaction_is_sent_in_the_background(mock_bot):
    cog = MusicGuess(mock_bot)
    channel_id = 66666
    cog.active_games[channel_id] = {
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
    message = MagicMock(spec=discord.Message)
    message.channel.id = channel_id
    message.author.bot = False
    message.author.id = 1
    message.author.mention = "<@1>"
    message.content = "-g needle"
    message.reply = AsyncMock()
    # A deleted message / missing permission must not leak an unretrieved task exception
    message.add_reaction = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone"))

    with patch.object(cog, "cleanup_game", new_callable=AsyncMock):
        await cog.on_message(message)
        await asyncio.sleep(0)  # let the background reaction task run

    message.add_reaction.assert_awaited_once()
    message.reply.assert_awaited_once()


def _game(guild_id=None, **extra):
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


@pytest.mark.asyncio
async def test_timeout_frees_channel_even_if_announcement_fails(mock_bot, monkeypatch):
    cog = MusicGuess(mock_bot)
    monkeypatch.setitem(MusicGuess.end_game_timer.__globals__, "GUESS_TIME_LIMIT", 0)
    cog.active_games[1] = _game()
    channel = MagicMock()
    channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no perms"))

    await cog.end_game_timer(channel, 1)

    channel.send.assert_awaited_once()
    assert 1 not in cog.active_games  # otherwise the channel stays "in a game"


@pytest.mark.asyncio
async def test_winner_frees_channel_even_if_reply_fails(mock_bot):
    cog = MusicGuess(mock_bot)
    cog.active_games[2] = _game()
    message = MagicMock(spec=discord.Message)
    message.channel.id = 2
    message.author.bot = False
    message.author.id = 1
    message.author.mention = "<@1>"
    message.content = "-g needle"
    message.add_reaction = AsyncMock()
    # e.g. the winning message was deleted before the reply went out
    message.reply = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=400), "gone"))

    with patch.object(cog, "cleanup_game", new_callable=AsyncMock) as cleanup:
        await cog.on_message(message)

    cleanup.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_second_game_in_same_guild_is_rejected(mock_bot):
    cog = MusicGuess(mock_bot)
    cog.active_games[111] = _game(guild_id=999)  # running in another text channel

    ctx = MagicMock()
    ctx.channel.id = 222
    ctx.author.guild.id = 999
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()

    with patch.object(cog, "_run_game_start", new_callable=AsyncMock) as run:
        await cog.start_game_logic(ctx, pool_type="comm")

    run.assert_not_called()
    assert "<#111>" in ctx.send.call_args[0][0]

    # Same while another channel of the guild is still preparing its round
    cog.active_games.clear()
    cog.starting_guilds[999] = asyncio.get_running_loop().time()
    ctx.send.reset_mock()
    with patch.object(cog, "_run_game_start", new_callable=AsyncMock) as run:
        await cog.start_game_logic(ctx, pool_type="comm")
    run.assert_not_called()
    assert "Đang chuẩn bị một ván chơi khác" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_game_start_releases_guild_lock(mock_bot):
    cog = MusicGuess(mock_bot)
    ctx = MagicMock()
    ctx.channel.id = 333
    ctx.author.guild.id = 444
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()

    with (
        patch.object(cog, "_run_game_start", new_callable=AsyncMock, side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        await cog.start_game_logic(ctx, pool_type="comm")

    assert 444 not in cog.starting_guilds and 333 not in cog.starting_channels


@pytest.mark.asyncio
async def test_no_idle_timer_when_bot_is_not_in_voice(mock_bot):
    cog = MusicGuess(mock_bot)
    ctx = MagicMock()
    ctx.channel.id = 1
    ctx.author.guild.id = 2
    ctx.author.guild.voice_client = None
    ctx.author.voice.channel = MagicMock()
    ctx.send = AsyncMock()

    with patch.object(cog, "_run_game_start", new_callable=AsyncMock):
        await cog.start_game_logic(ctx, pool_type="comm")

    assert 2 not in cog.idle_tasks
