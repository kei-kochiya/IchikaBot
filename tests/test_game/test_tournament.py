from io import BytesIO

from PIL import Image

from utils.data.card_data import card_data
from utils.game.cards import get_card_image_url, get_random_card, supports_trained_art
from utils.game.tournament_logic import _create_phase_images_sync


def test_card_helpers():
    card_4star = {"cardRarityType": "rarity_4", "assetbundleName": "card_001"}
    card_2star = {"cardRarityType": "rarity_2", "assetbundleName": "card_002"}

    assert supports_trained_art(card_4star) is True
    assert supports_trained_art(card_2star) is False

    url_normal = get_card_image_url("card_001", trained=False)
    url_trained = get_card_image_url("card_001", trained=True)

    assert "card_normal.png" in url_normal
    assert "card_after_training.png" in url_trained

    # Test get_random_card
    random_card = get_random_card(card_data.cards, char_id=1, rarity=["rarity_4"])
    assert random_card is not None
    assert random_card["characterId"] == 1
    assert random_card["cardRarityType"] == "rarity_4"


def test_phase_images_sync(tmp_path):
    # Create a synthetic 500x500 test image
    img_path = tmp_path / "test_card.png"
    img = Image.new("RGBA", (500, 500), color=(255, 0, 0, 255))
    img.save(img_path)

    p1, p2, p3 = _create_phase_images_sync(str(img_path))
    assert isinstance(p1, BytesIO)
    assert isinstance(p2, BytesIO)
    assert isinstance(p3, BytesIO)

    # Check that bytes are valid image data
    img1 = Image.open(p1)
    img2 = Image.open(p2)
    img3 = Image.open(p3)

    assert img1.size == (250, 250)
    assert img2.size == (300, 300)
    assert img3.size == (400, 400)
