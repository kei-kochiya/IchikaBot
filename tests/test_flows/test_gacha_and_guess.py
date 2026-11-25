"""Command-flow & pipeline tests for /gacha, /guess, and /guessmode."""

import asyncio
import gc
import random
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from PIL import Image

from cogs.game import guess as guess_module
from cogs.game.gacha import GachaCog
from cogs.game.guess import (
    MAX_PUZZLE_WIDTH,
    GuessCog,
    _process_game_image_sync,
    is_correct_name_guess,
)
from config import GACHA_RATES, PITY_THRESHOLD
from utils.core import database

# ── /gacha ────────────────────────────────────────────────────────────────────


def _patch_gacha_render(monkeypatch, tmp_path, art_available: bool = True):
    art = tmp_path / "art.webp"
    art.write_bytes(b"x")
    g = GachaCog.pull.callback.__globals__

    async def fake_assets():
        return {}

    async def fake_art(_card):
        return str(art) if art_available else None

    monkeypatch.setitem(g, "get_ui_assets", fake_assets)
    monkeypatch.setitem(g, "_card_art", fake_art)
    monkeypatch.setitem(g, "render_ten_pull", lambda *a: BytesIO(b"jpeg"))
    monkeypatch.setitem(g, "render_single_pull", lambda *a: BytesIO(b"jpeg"))


def test_gacha_rates_guaranteed_slot_and_pity_threshold(mock_bot, monkeypatch):
    cog = GachaCog(mock_bot)

    # Pity triggers guaranteed 4* and resets counter
    card, pity = cog._simulate_single_pull(current_pity=PITY_THRESHOLD - 1)
    assert card["cardRarityType"] == "rarity_4" and pity == 0

    # Guaranteed 10th slot keeps normal 4* rate (6%) and never yields 2*
    monkeypatch.setattr(random, "random", lambda: GACHA_RATES["rarity_4"] - 0.001)
    card, pity = cog._simulate_single_pull(current_pity=0, is_guaranteed_slot=True)
    assert card["cardRarityType"] == "rarity_4" and pity == 0

    monkeypatch.setattr(random, "random", lambda: 0.10)
    card, pity = cog._simulate_single_pull(current_pity=0, is_guaranteed_slot=True)
    assert card["cardRarityType"] == "rarity_3" and pity == 1


async def test_gacha_pull_and_pity_command_flows(
    mock_bot, make_interaction, monkeypatch, tmp_path, temp_db
):
    _patch_gacha_render(monkeypatch, tmp_path)
    cog = GachaCog(mock_bot)

    # 10-pull sends plain JPEG attachment (not embed) and escapes markdown in username
    inter10 = make_interaction(user_id=7, display_name="Saki_fan")
    await cog.pull.callback(cog, inter10, amount=10)
    sent = inter10.last_reply
    assert sent["file"].filename == "gacha_10.jpg"
    assert "embed" not in sent
    assert r"Saki\_fan" in sent["content"] and "Pity" in sent["content"]

    # 1-pull without art still renders placeholder & reports result
    _patch_gacha_render(monkeypatch, tmp_path, art_available=False)
    inter1 = make_interaction(user_id=7)
    await cog.pull.callback(cog, inter1, amount=1)
    assert inter1.last_reply["file"].filename == "card.jpg"

    # /gacha pity shows persisted DB counter ephemerally
    inter_pity = make_interaction(user_id=7)
    await cog.check_pity.callback(cog, inter_pity)
    assert inter_pity.last_reply["ephemeral"] is True
    assert f"/{PITY_THRESHOLD}" in inter_pity.last_reply["embed"].description

    # Empty card pool fails gracefully instead of IndexError
    cog.cards_4 = []
    inter_empty = make_interaction(user_id=7)
    await cog.pull.callback(cog, inter_empty, amount=1)
    assert inter_empty.last_reply["ephemeral"] is True


async def test_gacha_pity_lock_serializes_same_user_and_releases_when_idle(mock_bot, monkeypatch):
    cog = GachaCog(mock_bot)
    store = {1: 0, 2: 0}

    async def get_pity(uid):
        val = store[uid]
        await asyncio.sleep(0.01)
        return val

    async def set_pity(uid, count):
        await asyncio.sleep(0.01)
        store[uid] = count

    monkeypatch.setattr(cog, "get_user_pity", get_pity)
    monkeypatch.setattr(cog, "update_user_pity", set_pity)
    monkeypatch.setattr(cog, "_simulate_single_pull", lambda pity, guaranteed=False: ({}, pity + 1))

    await asyncio.gather(*(cog.pull_one_card(1) for _ in range(5)), cog.pull_one_card(2))
    assert store == {1: 5, 2: 1}

    gc.collect()
    assert len(cog._pity_locks) == 0


# ── /guess & /guessmode ───────────────────────────────────────────────────────


def test_guess_answer_matching_normalizes_before_length_check():
    cog = GuessCog(MagicMock())
    ichika = cog.build_answer_list(1)
    kanade = cog.build_answer_list(17)
    honami = cog.build_answer_list(3)
    an = cog.build_answer_list(10)

    assert is_correct_name_guess("Ichika  Hoshino", ichika)
    assert is_correct_name_guess("ick", ichika)
    assert is_correct_name_guess("an", an)
    assert not is_correct_name_guess("n e", kanade)
    assert not is_correct_name_guess("k.a", kanade)
    assert is_correct_name_guess("k a n", kanade)
    assert is_correct_name_guess("bánh táo", honami)
    assert is_correct_name_guess("banh tao", honami)


async def test_guessmode_persists_per_player_and_honors_alias(mock_bot, make_interaction, temp_db):
    cog = GuessCog(mock_bot)
    assert await cog.resolve_mode(5, None) == "easy"

    inter = make_interaction(user_id=5)
    await cog.guess_mode.callback(cog, inter, mode="normal")
    assert await cog.resolve_mode(5, None) == "normal"
    assert await cog.resolve_mode(5, "random") == "hard"
    assert await cog.resolve_mode(6, None) == "easy"

    await database.set_user_setting(6, "guess_mode", "invalid")
    assert await cog.resolve_mode(6, None) == "easy"

    inter_show = make_interaction(user_id=5)
    await cog.guess_mode.callback(cog, inter_show, mode=None)
    assert "Thường" in inter_show.last_reply["content"]


async def test_guess_round_win_and_stale_channel_recovery(
    mock_bot, make_interaction, tmp_path, temp_db
):
    cog = GuessCog(mock_bot)
    reveal = tmp_path / "reveal.webp"
    reveal.write_bytes(b"RIFFfake")

    # Stale channel (>45s) auto-recovers and plays a full winning round
    cog.active_channels[888] = asyncio.get_running_loop().time() - 60.0
    inter = make_interaction(channel_id=888)

    winning_msg = MagicMock(spec=discord.Message)
    winning_msg.channel.id = 888
    winning_msg.author.bot = False
    winning_msg.author.display_name = "Winner"
    winning_msg.content = "-g ichika"
    winning_msg.add_reaction = AsyncMock()

    with (
        patch.object(
            cog,
            "process_game_image",
            new_callable=AsyncMock,
            return_value=(BytesIO(b"jpg"), str(reveal), "Focus"),
        ),
        patch.object(mock_bot, "wait_for", new_callable=AsyncMock, return_value=winning_msg),
    ):
        await cog.guess.callback(cog, inter, mode="easy")

    assert 888 not in cog.active_channels
    assert len(inter.followup.messages) == 2
    assert "Đúng rồi" in inter.followup.messages[1]["embed"].title


async def test_guess_defer_failure_and_empty_pool_do_not_softlock(mock_bot, make_interaction):
    cog = GuessCog(mock_bot)
    inter = make_interaction(channel_id=999)
    inter.response.defer = AsyncMock(
        side_effect=discord.NotFound(MagicMock(), "Unknown interaction")
    )

    with pytest.raises(discord.NotFound):
        await cog.guess.callback(cog, inter, mode="normal")
    assert 999 not in cog.active_channels

    cog.cards = []
    inter_empty = make_interaction(channel_id=999)
    await cog.guess.callback(cog, inter_empty, mode="normal")
    assert inter_empty.last_reply["ephemeral"] is True
    assert 999 not in cog.active_channels


def test_guess_image_pipeline_modes_and_fallbacks(tmp_path, monkeypatch):
    card_path = tmp_path / "card.png"
    Image.linear_gradient("L").resize((2000, 1200)).convert("RGBA").save(card_path)
    cutout_path = tmp_path / "cutout.webp"
    Image.new("RGB", (600, 576), (200, 0, 0)).save(cutout_path)

    # Normal crop keeps native 300x300 and returns untouched reveal path
    puzzle, reveal, used = _process_game_image_sync(str(card_path), "normal")
    assert used == "Crop" and reveal == str(card_path) and Image.open(puzzle).size == (300, 300)

    # Easy mode with locator vs fallback without cutout
    monkeypatch.setitem(
        _process_game_image_sync.__globals__,
        "focus_crop_box",
        lambda img, cut, crop: (100, 200, 100 + crop, 200 + crop),
    )
    puzzle, _, used = _process_game_image_sync(str(card_path), "easy", str(cutout_path))
    assert used == "Focus" and Image.open(puzzle).size == (300, 300)
    _, _, used_fb = _process_game_image_sync(str(card_path), "easy", None)
    assert used_fb == "Crop"

    # Hard effects: crop_bw (300x300 L) + whole-image effects (capped at MAX_PUZZLE_WIDTH)
    for effect, expected_size, expected_mode in (
        ("crop_bw", (300, 300), "L"),
        ("pixelate", (MAX_PUZZLE_WIDTH, round(1200 * MAX_PUZZLE_WIDTH / 2000)), "RGB"),
        ("blur", (MAX_PUZZLE_WIDTH, round(1200 * MAX_PUZZLE_WIDTH / 2000)), "RGB"),
        ("negative", (MAX_PUZZLE_WIDTH, round(1200 * MAX_PUZZLE_WIDTH / 2000)), "RGB"),
    ):
        monkeypatch.setattr(guess_module.random, "choice", lambda _seq, e=effect: e)
        out, _, _ = _process_game_image_sync(str(card_path), "hard")
        img = Image.open(out)
        assert img.format == "JPEG" and img.size == expected_size and img.mode == expected_mode

    # Tiny image upscales; broken/missing files fail softly
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (80, 80), (10, 20, 30)).save(tiny)
    assert Image.open(_process_game_image_sync(str(tiny), "normal")[0]).size == (300, 300)

    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not-an-image")
    assert _process_game_image_sync(str(broken), "normal") == (None, None, "")
    assert _process_game_image_sync(str(tmp_path / "missing.png"), "normal") == (None, None, "")
