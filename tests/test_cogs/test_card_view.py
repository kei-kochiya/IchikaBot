from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.info.card import CardView
from utils.game.cards import CardToggleView
from utils.social.birthday_ui import BirthdayCardView


@pytest.fixture
def mock_card_interaction():
    inter = MagicMock(spec=discord.Interaction)
    inter.response = MagicMock(spec=discord.InteractionResponse)
    inter.response.defer = AsyncMock()
    inter.response.is_done.return_value = False

    def defer_side_effect():
        inter.response.is_done.return_value = True

    inter.response.defer.side_effect = defer_side_effect
    inter.edit_original_response = AsyncMock()
    inter.response.edit_message = AsyncMock()

    msg = MagicMock(spec=discord.Message)
    embed = discord.Embed(title="Test Card")
    msg.embeds = [embed]
    msg.attachments = []
    inter.message = msg
    return inter


@pytest.mark.asyncio
async def test_card_view_switch_callback_defers(mock_card_interaction):
    card = {
        "id": 100,
        "characterId": 1,
        "assetbundleName": "card_test_001",
        "cardRarityType": "rarity_4",
    }
    view = CardView(card, {"id": 1}, "https://storage.sekai.best")

    with patch(
        "cogs.info.card.get_card_image_path", new_callable=AsyncMock, return_value=None
    ) as mock_get_path:
        await view.switch_callback(mock_card_interaction)
        mock_card_interaction.response.defer.assert_called_once()
        mock_get_path.assert_called_once()
        mock_card_interaction.edit_original_response.assert_called_once()


@pytest.mark.asyncio
async def test_card_toggle_view_callback_defers(mock_card_interaction):
    card = {
        "id": 100,
        "characterId": 1,
        "assetbundleName": "card_test_001",
        "cardRarityType": "rarity_4",
    }
    embed = discord.Embed(title="COTD Card")
    view = CardToggleView(embed, card, default_trained=False)

    with patch(
        "utils.media.image_helper.get_card_image_path",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_get_path:
        await view.toggle_callback(mock_card_interaction)
        mock_card_interaction.response.defer.assert_called_once()
        mock_get_path.assert_called_once()
        mock_card_interaction.edit_original_response.assert_called_once()


@pytest.mark.asyncio
async def test_birthday_card_view_callbacks_defer(mock_card_interaction):
    character = {"id": 1, "unit": "leo_need"}
    cards = [
        {"id": 101, "characterId": 1, "assetbundleName": "bday_01", "releaseAt": 1600000000},
        {"id": 102, "characterId": 1, "assetbundleName": "bday_02", "releaseAt": 1630000000},
    ]
    view = BirthdayCardView(character, cards, current_index=0)

    with patch(
        "utils.media.image_helper.get_card_image_path",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_get_path:
        # Test prev_callback (Older)
        await view.prev_callback(mock_card_interaction)
        mock_card_interaction.response.defer.assert_called_once()
        mock_get_path.assert_called_once()
        mock_card_interaction.edit_original_response.assert_called_once()

    # Reset mock and test next_callback (Newer)
    mock_card_interaction.response.defer.reset_mock()
    mock_card_interaction.response.is_done.return_value = False
    mock_card_interaction.edit_original_response.reset_mock()

    with patch(
        "utils.media.image_helper.get_card_image_path",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_get_path:
        await view.next_callback(mock_card_interaction)
        mock_card_interaction.response.defer.assert_called_once()
        mock_get_path.assert_called_once()
        mock_card_interaction.edit_original_response.assert_called_once()
