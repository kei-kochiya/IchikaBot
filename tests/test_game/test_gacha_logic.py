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


def _pull_interaction(user_id=7):
    from unittest.mock import AsyncMock, MagicMock

    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.user.name = "tester"
    interaction.user.display_name = "Tester"
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _patch_rendering(monkeypatch, tmp_path, art_available=True):
    from io import BytesIO

    art = tmp_path / "art.webp"
    art.write_bytes(b"x")
    g = GachaCog.pull.callback.__globals__  # cog modules are re-imported by other tests

    async def fake_assets():
        return {}

    async def fake_art(card):
        return str(art) if art_available else None

    monkeypatch.setitem(g, "get_ui_assets", fake_assets)
    monkeypatch.setitem(g, "_card_art", fake_art)
    monkeypatch.setitem(g, "render_ten_pull", lambda *a: BytesIO(b"jpeg"))
    monkeypatch.setitem(g, "render_single_pull", lambda *a: BytesIO(b"jpeg"))


async def test_ten_pull_sends_the_result_as_a_plain_image(mock_bot, monkeypatch, tmp_path, temp_db):
    _patch_rendering(monkeypatch, tmp_path)
    cog = GachaCog(mock_bot)
    interaction = _pull_interaction()
    interaction.user.display_name = "Saki_fan"

    await cog.pull.callback(cog, interaction, amount=10)

    (sent,) = interaction.followup.send.call_args_list
    assert sent.kwargs["file"].filename == "gacha_10.jpg"
    assert "embed" not in sent.kwargs  # an embed shrinks the image to ~400 px
    content = sent.kwargs["content"]
    assert r"Saki\_fan" in content  # markdown in names is escaped
    assert "4★" in content and "3★" in content and "Pity" in content


async def test_single_pull_sends_the_result_image(mock_bot, monkeypatch, tmp_path, temp_db):
    _patch_rendering(monkeypatch, tmp_path)
    cog = GachaCog(mock_bot)
    interaction = _pull_interaction()

    await cog.pull.callback(cog, interaction, amount=1)

    (sent,) = interaction.followup.send.call_args_list
    assert sent.kwargs["file"].filename == "card.jpg"
    assert "embed" not in sent.kwargs and "Pity" in sent.kwargs["content"]


async def test_single_pull_without_art_still_shows_the_result(
    mock_bot, monkeypatch, tmp_path, temp_db
):
    # e.g. a brand-new card whose art is not on the CDN yet: the pull (and maybe a pity
    # reset) already happened, so the user must still see which card it was
    _patch_rendering(monkeypatch, tmp_path, art_available=False)
    cog = GachaCog(mock_bot)
    interaction = _pull_interaction()

    await cog.pull.callback(cog, interaction, amount=1)

    (sent,) = interaction.followup.send.call_args_list
    assert sent.kwargs["file"].filename == "card.jpg"
    assert "embed" not in sent.kwargs and "Pity" in sent.kwargs["content"]
