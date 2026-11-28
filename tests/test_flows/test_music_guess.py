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


async def test_music_helpers_scan_cleanup_voice_and_diagnostics(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from utils.game import music_helpers as mh

    # scan_audio_files finds nested audio files and resolves case-insensitive dir names
    music_dir = tmp_path / "Music"
    sub = music_dir / "comm"
    sub.mkdir(parents=True)
    (sub / "54.mp3").write_bytes(b"a")
    (music_dir / "1.wav").write_bytes(b"b")
    (music_dir / "notes.txt").write_text("ignore", encoding="utf-8")

    resolved, found = mh.scan_audio_files(tmp_path / "music")
    assert resolved.exists()
    assert {p.replace("\\", "/") for p in found} == {"1.wav", "comm/54.mp3"}

    # Missing dir is created empty
    new_dir, empty = mh.scan_audio_files(tmp_path / "brand_new_audio")
    assert new_dir.is_dir() and empty == []

    # sweep_leftover_temp_clips removes temp files in TEMP_DIR
    monkeypatch.setattr(mh, "TEMP_DIR", tmp_path)
    leftover = tmp_path / f"{mh.TEMP_CLIP_PREFIX}stale.mp3"
    leftover.write_bytes(b"old")
    assert mh.sweep_leftover_temp_clips() >= 1
    assert not leftover.exists()

    # remove_wrong_reactions swallows HTTPException and handles bot_user=None
    m_ok = MagicMock(remove_reaction=AsyncMock())
    m_err = MagicMock(
        remove_reaction=AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone"))
    )
    await mh.remove_wrong_reactions([m_ok, m_err], "❌", None)
    m_ok.remove_reaction.assert_not_called()
    await mh.remove_wrong_reactions([m_ok, m_err], "❌", MagicMock())
    m_ok.remove_reaction.assert_awaited_once()

    # connect_to_voice: reuse same channel, move to new channel, disconnect stale, fresh connect
    ch_a, ch_b = MagicMock(), MagicMock()
    vc = MagicMock(channel=ch_a, move_to=AsyncMock(), disconnect=AsyncMock())
    vc.is_connected.return_value = True
    guild = MagicMock(voice_client=vc)
    assert await mh.connect_to_voice(guild, ch_a) is vc
    assert await mh.connect_to_voice(guild, ch_b) is vc
    vc.move_to.assert_awaited_once_with(ch_b)

    vc.is_connected.return_value = False
    fresh_vc = MagicMock()
    ch_b.connect = AsyncMock(return_value=fresh_vc)
    assert await mh.connect_to_voice(guild, ch_b) is fresh_vc
    vc.disconnect.assert_awaited_once_with(force=True)

    # format_no_eligible_songs_message covers all 4 diagnostic paths
    assert "boom" in mh.format_no_eligible_songs_message(
        SimpleNamespace(last_error="boom", _db={}), ["1.mp3"], "comm"
    )
    assert "đang trống" in mh.format_no_eligible_songs_message(
        SimpleNamespace(last_error=None, _db={}), ["1.mp3"], "comm"
    )
    assert "commission" in mh.format_no_eligible_songs_message(
        SimpleNamespace(last_error=None, _db={1: {}}, get_commission_ids=lambda: set()),
        ["1.mp3"],
        "comm",
    )
    assert "foo.mp3" in mh.format_no_eligible_songs_message(
        SimpleNamespace(last_error=None, _db={1: {}}, get_commission_ids=lambda: {54}),
        ["foo.mp3"],
        "all",
    )


async def test_music_guess_full_round_start_wrong_guesses_and_play_error(
    mock_bot, make_ctx, monkeypatch, tmp_path
):
    from cogs.voice import music_guess as mg

    cog = MusicGuess(mock_bot)
    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"fake-audio")

    vc = MagicMock()
    vc.is_connected.return_value = True
    vc.is_playing.return_value = False
    vc.guild.id = 500
    vc.play = MagicMock()
    vc.stop = MagicMock()
    vc.disconnect = AsyncMock()

    monkeypatch.setattr(mg, "scan_audio_files", lambda _d: (tmp_path, ["54.mp3"]))
    monkeypatch.setattr(mg, "prepare_clip", lambda _p, _v: (str(clip), None))
    monkeypatch.setattr(mg, "connect_to_voice", AsyncMock(return_value=vc))
    monkeypatch.setattr(mg, "GUESS_TIME_LIMIT", 60)

    fake_src = MagicMock()
    monkeypatch.setattr(discord, "FFmpegPCMAudio", lambda _p: fake_src)

    ctx = make_ctx(channel_id=501, guild_id=500)
    ctx.author.voice = MagicMock(channel=MagicMock(name="Voice"))
    await cog.start_game_logic(ctx, variant_mode=False, pool_type="comm")

    assert 501 in cog.active_games
    vc.play.assert_called_once_with(fake_src)

    # Wrong guesses increment counter and hit MAX_GUESSES limit
    game = cog.active_games[501]
    for _ in range(mg.MAX_GUESSES + 1):
        wrong = _guess_message(501, 777, "-g definitely wrong song")
        await cog.on_message(wrong)
    assert game["guesses"][777] == mg.MAX_GUESSES

    # Non-guess messages are ignored
    await cog.on_message(_guess_message(501, 777, "hello chat"))

    # Cleanup cancels timer and removes active game
    await cog.cleanup_game(501, schedule_idle=False)
    assert 501 not in cog.active_games

    # Play failure cleans up FFmpeg source and frees channel
    clip2 = tmp_path / "clip2.mp3"
    clip2.write_bytes(b"fake-audio-2")
    monkeypatch.setattr(mg, "prepare_clip", lambda _p, _v: (str(clip2), None))
    vc.play.side_effect = RuntimeError("ffmpeg failed")
    fake_src2 = MagicMock()
    monkeypatch.setattr(discord, "FFmpegPCMAudio", lambda _p: fake_src2)
    ctx2 = make_ctx(channel_id=502, guild_id=500)
    ctx2.author.voice = MagicMock(channel=MagicMock(name="Voice"))
    await cog.start_game_logic(ctx2, variant_mode=False, pool_type="comm")
    fake_src2.cleanup.assert_called_once()
    assert 502 not in cog.active_games
    cog.cog_unload()
