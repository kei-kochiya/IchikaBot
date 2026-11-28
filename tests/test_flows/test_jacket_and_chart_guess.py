"""Command-flow & image pipeline tests for /jacketguess and /chartguess."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from PIL import Image, ImageDraw

from cogs.game import chartguess as chartguess_module
from cogs.game import jacketguess as jacketguess_module
from cogs.game.chartguess import ChartGuessCog
from cogs.game.jacketguess import JacketGuessCog
from utils.game import guess_engine
from utils.game import song_guess_media as sgm


def test_build_song_answers_combines_multilingual_sources(monkeypatch):
    fake_song_data = MagicMock()
    fake_song_data.songs_en_meta = {1: {"title": "Tell Your World"}}
    fake_db = MagicMock()
    fake_db._db = {"1": {"title_en": "Tell Your World", "romaji_title": "Teru Yua Waarudo"}}

    monkeypatch.setattr(sgm, "song_data", fake_song_data)
    monkeypatch.setattr(sgm.MusicQuizDB, "get_instance", lambda: fake_db)

    display, targets, raw_jp = sgm.build_song_answers(
        {"id": 1, "title": "Tell Your World (JP)", "pronunciation": "てるゆあわーるど"}
    )
    assert display == "Tell Your World (Tell Your World (JP))"
    assert sgm.is_song_guess_correct("tell your world", targets, raw_jp)
    assert sgm.is_song_guess_correct("teru yua waarudo", targets, raw_jp)
    assert sgm.is_song_guess_correct("てるゆあわーるど", targets, raw_jp)

    # Pure-JP song not in song.xlsx or EN still matches via romaji(pronunciation) and exact kanji
    display_jp, targets_jp, raw_jp_only = sgm.build_song_answers(
        {"id": 999, "title": "群青讃歌", "pronunciation": "ぐんじょうさんか"}
    )
    assert display_jp == "群青讃歌"
    assert sgm.is_song_guess_correct("gunjousanka", targets_jp, raw_jp_only)
    assert sgm.is_song_guess_correct("ぐんじょうさんか", targets_jp, raw_jp_only)
    assert sgm.is_song_guess_correct("群青讃歌", targets_jp, raw_jp_only)
    assert not sgm.is_song_guess_correct("999", targets_jp, raw_jp_only)


def test_jacket_image_pipeline_modes_and_errors(tmp_path, monkeypatch):
    jacket = tmp_path / "jacket.png"
    Image.linear_gradient("L").resize((520, 520)).convert("RGB").save(jacket)

    out_easy, label_easy = sgm.process_jacket_image_sync(str(jacket), "easy")
    assert label_easy == "Crop rộng" and Image.open(out_easy).format == "JPEG"

    out_norm, label_norm = sgm.process_jacket_image_sync(str(jacket), "normal")
    assert label_norm == "Crop" and Image.open(out_norm).format == "JPEG"

    for effect, expected_mode in (
        ("crop_bw", "L"),
        ("pixelate", "RGB"),
        ("blur", "RGB"),
        ("negative", "RGB"),
    ):
        monkeypatch.setattr(sgm.random, "choice", lambda _seq, e=effect: e)
        out_hard, label_hard = sgm.process_jacket_image_sync(str(jacket), "hard")
        im = Image.open(out_hard)
        assert label_hard and im.format == "JPEG" and im.mode == expected_mode

    tiny = tmp_path / "tiny_jacket.png"
    Image.new("RGB", (100, 100), (20, 40, 60)).save(tiny)
    assert sgm.process_jacket_image_sync(str(tiny), "normal")[0] is not None
    assert sgm.process_jacket_image_sync(str(tmp_path / "missing.png"), "normal") == (None, "")


def test_chart_crop_never_leaks_footer_spoiler(tmp_path):
    # Synthetic sekai-music-charts layout: lavender bg, 4 lane columns, divider at h - 256,
    # and a bright-red spoiler footer below the divider that must NEVER appear in any crop.
    w, h = 1400, 1200
    divider_y = h - 256
    img = Image.new("RGB", (w, h), (190, 180, 210))
    draw = ImageDraw.Draw(img)

    for ci in range(4):
        x0 = 80 + ci * 280
        x1 = x0 + 194
        draw.rectangle([x0, 32, x1, divider_y - 40], fill=(245, 245, 250))
        for ny in range(120, divider_y - 100, 70):
            draw.rectangle([x0 + 20, ny, x0 + 120, ny + 18], fill=(40, 200, 255))

    draw.rectangle([0, divider_y, w, divider_y + 4], fill=(226, 226, 226))
    draw.rectangle([0, divider_y + 5, w, h], fill=(255, 0, 0))  # pure-red spoiler banner

    chart_path = tmp_path / "chart.png"
    img.save(chart_path)

    for mode in ("easy", "normal", "hard"):
        buf = sgm.crop_chart_image_sync(str(chart_path), mode)
        assert buf is not None
        out = Image.open(buf)
        assert out.format == "JPEG"
        assert out.width >= 360
        rgb_pixels = list(out.convert("RGB").getdata())
        assert not any(r > 200 and g < 40 and b < 40 for r, g, b in rgb_pixels)

    tiny = tmp_path / "tiny_chart.png"
    Image.new("RGB", (120, 200), (0, 0, 0)).save(tiny)
    assert sgm.crop_chart_image_sync(str(tiny), "normal") is None
    assert sgm.crop_chart_image_sync(str(tmp_path / "missing.png"), "normal") is None


async def test_jacketguess_round_win_and_cross_cog_channel_lock(
    mock_bot, make_interaction, tmp_path, monkeypatch
):
    jacket_cog = JacketGuessCog(mock_bot)
    chart_cog = ChartGuessCog(mock_bot)

    jacket = tmp_path / "jacket.png"
    Image.new("RGB", (400, 400), (80, 120, 200)).save(jacket)

    fake_song_data = MagicMock()
    fake_song_data.songs_jp = [
        {
            "id": 54,
            "title": "群青讃歌",
            "pronunciation": "ぐんじょうさんか",
            "composer": "Eve",
            "assetbundleName": "jacket_s_054",
        }
    ]
    fake_song_data.songs_en_meta = {54: {"title": "Journey to Bloom"}}
    fake_song_data.difficulties = {54: {"master": {"level": 29, "noteCount": 1111}}}

    monkeypatch.setattr(jacketguess_module, "song_data", fake_song_data)
    monkeypatch.setattr(chartguess_module, "song_data", fake_song_data)
    monkeypatch.setattr(sgm, "song_data", fake_song_data)
    monkeypatch.setattr(
        jacketguess_module, "get_song_jacket_path", AsyncMock(return_value=str(jacket))
    )

    # Shared channel lock across cogs blocks /chartguess while another `-g` game is active
    guess_engine.active_channels[777] = asyncio.get_running_loop().time()
    inter_blocked = make_interaction(channel_id=777)
    await chart_cog.chart_guess.callback(
        chart_cog, inter_blocked, difficulty="master", mode="normal"
    )
    assert inter_blocked.last_reply["ephemeral"] is True
    guess_engine.active_channels.clear()

    inter = make_interaction(channel_id=777)
    winning_msg = MagicMock(spec=discord.Message)
    winning_msg.channel.id = 777
    winning_msg.author.bot = False
    winning_msg.author.display_name = "IchikaFan"
    winning_msg.content = "-g journey to bloom"
    winning_msg.add_reaction = AsyncMock()

    with patch.object(mock_bot, "wait_for", new_callable=AsyncMock, return_value=winning_msg):
        await jacket_cog.jacket_guess.callback(jacket_cog, inter, mode="normal")

    assert 777 not in guess_engine.active_channels
    assert len(inter.followup.messages) == 2
    assert inter.followup.messages[0]["file"].filename == "jacket_guess.jpg"
    reveal_embed = inter.followup.messages[1]["embed"]
    assert "Đúng rồi" in reveal_embed.title
    assert any(f.name == "Sáng tác" and f.value == "Eve" for f in reveal_embed.fields)


async def test_chartguess_append_filter_retry_and_win(
    mock_bot, make_interaction, tmp_path, monkeypatch
):
    cog = ChartGuessCog(mock_bot)
    chart = tmp_path / "0002_append.png"
    jacket = tmp_path / "jacket_0002.png"
    Image.new("RGB", (600, 900), (190, 180, 210)).save(chart)
    Image.new("RGB", (300, 300), (50, 90, 140)).save(jacket)

    fake_song_data = MagicMock()
    fake_song_data.songs_jp = [
        {"id": 1, "title": "MasterOnly", "pronunciation": "", "assetbundleName": "j1"},
        {"id": 2, "title": "AppendSong", "pronunciation": "", "assetbundleName": "j2"},
        {"id": 3, "title": "AppendMissing", "pronunciation": "", "assetbundleName": "j3"},
    ]
    fake_song_data.songs_en_meta = {}
    fake_song_data.difficulties = {
        1: {"master": {"level": 28, "noteCount": 900}},
        2: {"master": {"level": 30, "noteCount": 1000}, "append": {"level": 32, "noteCount": 1234}},
        3: {"master": {"level": 31, "noteCount": 1050}, "append": {"level": 34, "noteCount": 1500}},
    }

    monkeypatch.setattr(chartguess_module, "song_data", fake_song_data)
    monkeypatch.setattr(sgm, "song_data", fake_song_data)
    monkeypatch.setattr(
        chartguess_module.random,
        "sample",
        lambda seq, k: sorted(seq, key=lambda s: s["id"], reverse=True)[:k],
    )

    fetched_calls: list[tuple[int, str]] = []

    async def fake_chart_fetch(song_id: int, diff: str):
        fetched_calls.append((song_id, diff))
        return str(chart) if song_id == 2 else None

    monkeypatch.setattr(chartguess_module, "get_song_chart_path", fake_chart_fetch)
    monkeypatch.setattr(
        chartguess_module, "get_song_jacket_path", AsyncMock(return_value=str(jacket))
    )

    inter = make_interaction(channel_id=666)
    winning_msg = MagicMock(spec=discord.Message)
    winning_msg.channel.id = 666
    winning_msg.author.bot = False
    winning_msg.author.display_name = "ChartPro"
    winning_msg.content = "-g appendsong"
    winning_msg.add_reaction = AsyncMock()

    with patch.object(mock_bot, "wait_for", new_callable=AsyncMock, return_value=winning_msg):
        await cog.chart_guess.callback(cog, inter, difficulty="append", mode="hard")

    assert fetched_calls == [(3, "append"), (2, "append")]
    assert 666 not in guess_engine.active_channels
    assert len(inter.followup.messages) == 2
    assert inter.followup.messages[0]["file"].filename == "chart_guess.jpg"
    reveal_embed = inter.followup.messages[1]["embed"]
    assert "Đúng rồi" in reveal_embed.title
    assert any(
        f.name == "Chart" and "Append Lv.32 (1,234 notes)" in f.value for f in reveal_embed.fields
    )
