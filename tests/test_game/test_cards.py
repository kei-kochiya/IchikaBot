"""Unit tests for card utilities."""

from utils.game.cards import get_card_image_url, get_random_card, supports_trained_art


class TestSupportsTrainedArt:
    def test_rarity_1_and_2_not_supported(self):
        assert supports_trained_art({"cardRarityType": "rarity_1"}) is False
        assert supports_trained_art({"cardRarityType": "rarity_2"}) is False

    def test_rarity_birthday_not_supported(self):
        assert supports_trained_art({"cardRarityType": "rarity_birthday"}) is False

    def test_rarity_3_and_4_supported(self):
        assert supports_trained_art({"cardRarityType": "rarity_3"}) is True
        assert supports_trained_art({"cardRarityType": "rarity_4"}) is True

    def test_pre_trained_cards_not_supported(self):
        assert (
            supports_trained_art(
                {"cardRarityType": "rarity_4", "initialSpecialTrainingStatus": "done"}
            )
            is False
        )
        assert (
            supports_trained_art(
                {"cardRarityType": "rarity_3", "initialSpecialTrainingStatus": "done"}
            )
            is False
        )

    def test_invalid_input(self):
        assert supports_trained_art(None) is False
        assert supports_trained_art({}) is False
        assert supports_trained_art("not a dict") is False


class TestIsPreTrainedCard:
    def test_pre_trained_card_detection(self):
        from utils.game.cards import is_pre_trained_card

        assert is_pre_trained_card({"initialSpecialTrainingStatus": "done"}) is True
        assert is_pre_trained_card({"initialSpecialTrainingStatus": "not_done"}) is False
        assert is_pre_trained_card({}) is False
        assert is_pre_trained_card(None) is False
        assert is_pre_trained_card("invalid") is False


class TestGetCardImageUrl:
    def test_normal_image_url(self):
        url = get_card_image_url("card_bundle_1", trained=False)
        assert "card_bundle_1" in url
        assert url.endswith("card_normal.png")

    def test_trained_image_url(self):
        url = get_card_image_url("card_bundle_1", trained=True)
        assert "card_bundle_1" in url
        assert url.endswith("card_after_training.png")


class TestGetRandomCard:
    cards = [
        {"id": 1, "characterId": 1, "cardRarityType": "rarity_1", "prefix": "Card 1"},
        {"id": 2, "characterId": 1, "cardRarityType": "rarity_2", "prefix": "Card 2"},
        {"id": 3, "characterId": 1, "cardRarityType": "rarity_3", "prefix": "Card 3"},
        {"id": 4, "characterId": 1, "cardRarityType": "rarity_4", "prefix": "Card 4"},
        {"id": 5, "characterId": 2, "cardRarityType": "rarity_4", "prefix": "Card 5"},
        {"id": 6, "characterId": 1, "cardRarityType": "rarity_4", "prefix": None},  # No prefix
    ]

    def test_get_random_card_by_character(self):
        card = get_random_card(self.cards, 1)
        assert card is not None
        assert card["characterId"] == 1
        assert card.get("prefix") is not None

    def test_get_random_card_with_rarity_filter(self):
        card = get_random_card(self.cards, 1, rarity=["rarity_4"])
        assert card is not None
        assert card["characterId"] == 1
        assert card["cardRarityType"] == "rarity_4"
        assert card["id"] == 4

    def test_get_random_card_no_match(self):
        card = get_random_card(self.cards, 99)
        assert card is None
