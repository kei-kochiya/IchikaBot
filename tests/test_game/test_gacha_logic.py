from cogs.game.gacha import GachaCog
from config import PITY_THRESHOLD


def test_gacha_simulation_rates(mock_bot):
    cog = GachaCog(mock_bot)

    # Test single pull produces valid card structure
    card, new_pity = cog._simulate_single_pull(current_pity=0)
    assert "cardRarityType" in card
    assert card["cardRarityType"] in ["rarity_2", "rarity_3", "rarity_4"]
    assert new_pity in [0, 1]  # 0 if 4-star, 1 otherwise


def test_gacha_guaranteed_slot(mock_bot):
    cog = GachaCog(mock_bot)

    # Guaranteed 10th slot must be 3-star or 4-star, never 2-star
    for _ in range(50):
        card, _ = cog._simulate_single_pull(current_pity=0, is_guaranteed_slot=True)
        assert card["cardRarityType"] in ["rarity_3", "rarity_4"]


def test_gacha_guaranteed_slot_keeps_normal_4_star_rate(mock_bot, monkeypatch):
    import random

    from config import GACHA_RATES

    cog = GachaCog(mock_bot)

    # Just under the normal 4-star rate: still a 4-star on the guaranteed slot
    monkeypatch.setattr(random, "random", lambda: GACHA_RATES["rarity_4"] - 0.001)
    card, pity = cog._simulate_single_pull(current_pity=0, is_guaranteed_slot=True)
    assert card["cardRarityType"] == "rarity_4" and pity == 0

    # Above it: 3-star. The old rescaling gave a 4-star up to ~0.286 (6% / 21%)
    monkeypatch.setattr(random, "random", lambda: 0.10)
    card, pity = cog._simulate_single_pull(current_pity=0, is_guaranteed_slot=True)
    assert card["cardRarityType"] == "rarity_3" and pity == 1


def test_gacha_pity_trigger(mock_bot):
    cog = GachaCog(mock_bot)

    # When pity reaches PITY_THRESHOLD - 1, the next pull triggers 4-star guaranteed & resets pity to 0
    card, new_pity = cog._simulate_single_pull(current_pity=PITY_THRESHOLD - 1)
    assert card["cardRarityType"] == "rarity_4"
    assert new_pity == 0
