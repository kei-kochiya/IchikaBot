from unittest.mock import AsyncMock, MagicMock

import aiohttp
import discord
import pytest

from cogs.misc.gas_price import GasPriceCog, _build_embed, fetch_prices


def test_build_embed():
    sample_products = [
        {
            "Title": "Xăng E5 RON 92 Mức 2",
            "Zone1Price": 27700,
            "Zone2Price": 28250,
            "LastModified": "2026-10-08T07:57:05.107Z",
            "DIsplayOrder": 5,
        },
        {
            "Title": "Xăng E10 RON 95 Mức 3",
            "Zone1Price": 28250,
            "Zone2Price": 28810,
            "LastModified": "2026-10-08T07:56:43.586Z",
            "DIsplayOrder": 4,
        },
    ]

    embed = _build_embed(sample_products)
    assert isinstance(embed, discord.Embed)
    assert "Giá xăng dầu bán lẻ" in embed.title
    assert len(embed.fields) == 2
    assert "27,700 đ" in embed.fields[0].value
    assert "28,250 đ" in embed.fields[0].value
    assert "Petrolimex" in embed.footer.text


def test_build_embed_empty():
    embed = _build_embed([])
    assert isinstance(embed, discord.Embed)
    assert len(embed.fields) == 0
    assert "Petrolimex" in embed.footer.text


@pytest.mark.asyncio
async def test_fetch_prices_success():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = AsyncMock(
        return_value={
            "Objects": [
                {"Title": "Item B", "DIsplayOrder": 2},
                {"Title": "Item A", "DIsplayOrder": 1},
            ]
        }
    )

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()))

    result = await fetch_prices(mock_session)
    assert len(result) == 2
    assert result[0]["Title"] == "Item A"
    assert result[1]["Title"] == "Item B"


@pytest.mark.asyncio
async def test_price_embed_error_handling(mock_bot):
    cog = GasPriceCog(mock_bot)
    cog._session = MagicMock(spec=aiohttp.ClientSession)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(side_effect=Exception("Network error"))
    cog._session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()))

    result = await cog._price_embed()
    assert isinstance(result, str)
    assert "❌" in result
