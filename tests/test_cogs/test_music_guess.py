from unittest.mock import MagicMock

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
