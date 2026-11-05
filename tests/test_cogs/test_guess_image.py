import random
from io import BytesIO

import pytest
from PIL import Image

from cogs.game import guess
from cogs.game.guess import MAX_PUZZLE_WIDTH, _process_game_image_sync


@pytest.fixture
def card_png(tmp_path):
    path = tmp_path / "card.png"
    Image.linear_gradient("L").resize((2000, 1200)).convert("RGBA").save(path)
    return str(path)


def _force_effect(monkeypatch, effect: str):
    monkeypatch.setattr(guess.random, "choice", lambda _seq: effect)


def test_normal_mode_is_a_native_resolution_crop(card_png):
    puzzle, reveal, effect = _process_game_image_sync(card_png, "normal")

    assert effect == "Crop"
    assert Image.open(puzzle).size == (300, 300)


def test_reveal_is_the_untouched_cached_file(card_png):
    _, reveal, _ = _process_game_image_sync(card_png, "normal")

    assert reveal == card_png  # nothing is re-encoded or kept in memory for the reveal


@pytest.mark.parametrize(
    ("effect", "label"),
    [("pixelate", "Pixelate"), ("blur", "Blur"), ("negative", "Âm bản")],
)
def test_whole_image_effects_cap_the_upload_width(card_png, monkeypatch, effect, label):
    _force_effect(monkeypatch, effect)

    puzzle, reveal, used = _process_game_image_sync(card_png, "random")

    assert used == label
    image = Image.open(puzzle)
    assert image.size == (MAX_PUZZLE_WIDTH, round(1200 * MAX_PUZZLE_WIDTH / 2000))
    assert reveal == card_png


def test_black_and_white_crop(card_png, monkeypatch):
    _force_effect(monkeypatch, "crop_bw")

    puzzle, _, used = _process_game_image_sync(card_png, "random")

    assert used == "Trắng đen"
    image = Image.open(puzzle)
    assert image.size == (300, 300)
    assert image.mode == "L"


def test_negative_actually_inverts(tmp_path, monkeypatch):
    path = tmp_path / "white.png"
    Image.new("RGBA", (400, 300), (255, 255, 255, 255)).save(path)
    _force_effect(monkeypatch, "negative")

    puzzle, _, _ = _process_game_image_sync(str(path), "random")

    assert Image.open(puzzle).convert("RGB").getpixel((10, 10)) == (0, 0, 0)


def test_small_images_are_upscaled_enough_to_crop(tmp_path):
    path = tmp_path / "tiny.png"
    Image.new("RGB", (100, 80), (10, 20, 30)).save(path)

    puzzle, _, effect = _process_game_image_sync(str(path), "normal")

    assert effect == "Crop"
    assert Image.open(puzzle).size == (300, 300)


@pytest.mark.parametrize("mode", ["normal", "random"])
def test_all_random_effects_produce_valid_jpeg(card_png, mode):
    random.seed(1234)
    for _ in range(12):
        puzzle, reveal, effect = _process_game_image_sync(card_png, mode)
        assert isinstance(puzzle, BytesIO)
        assert Image.open(puzzle).format == "JPEG"
        assert effect


def test_unreadable_image_fails_softly(tmp_path):
    bogus = tmp_path / "broken.png"
    bogus.write_bytes(b"not an image")

    assert _process_game_image_sync(str(bogus), "normal") == (None, None, "")
    assert _process_game_image_sync(str(tmp_path / "missing.png"), "normal") == (None, None, "")


def test_hard_is_the_old_random_mode(card_png, monkeypatch):
    _force_effect(monkeypatch, "blur")
    for mode in ("hard", "random"):  # "random" still works for old clients
        _, _, used = _process_game_image_sync(card_png, mode)
        assert used == "Blur"


def test_easy_mode_crops_where_the_locator_points(card_png, tmp_path, monkeypatch):
    cutout = tmp_path / "cutout.webp"
    Image.new("RGB", (600, 576), (200, 0, 0)).save(cutout)
    monkeypatch.setitem(
        _process_game_image_sync.__globals__,
        "focus_crop_box",
        lambda img, cut, crop: (100, 200, 100 + crop, 200 + crop),
    )

    puzzle, reveal, used = _process_game_image_sync(card_png, "easy", str(cutout))

    assert used == "Focus" and reveal == card_png
    assert Image.open(puzzle).size == (300, 300)


def test_easy_mode_without_cutout_falls_back_to_a_normal_crop(card_png):
    puzzle, _, used = _process_game_image_sync(card_png, "easy", None)

    assert used == "Crop"
    assert Image.open(puzzle).size == (300, 300)
