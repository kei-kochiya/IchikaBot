from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import discord
import pytest

from cogs.misc.gas_price import (
    GasPriceCog,
    _build_embed,
    _get_current_vn_date,
    _load_cache,
    _save_cache,
    fetch_prices,
)


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


def test_cache_save_and_load(tmp_path):
    cache_file = tmp_path / "test_gas_cache.json"
    assert _load_cache(cache_file) is None

    test_data = {"date": "2026-10-14", "products": [{"Title": "Fuel A"}]}
    _save_cache(test_data, cache_file)

    loaded = _load_cache(cache_file)
    assert loaded == test_data


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
    mock_session.get = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(),
        )
    )

    result = await fetch_prices(mock_session)
    assert len(result) == 2
    assert result[0]["Title"] == "Item A"
    assert result[1]["Title"] == "Item B"


@pytest.mark.asyncio
async def test_cache_hit_same_date(mock_bot, tmp_path):
    today = _get_current_vn_date()
    cache_file = tmp_path / "cache.json"
    cached_products = [{"Title": "Cached Fuel", "Zone1Price": 25000, "Zone2Price": 25500}]

    cog = GasPriceCog(mock_bot, cache_file=cache_file)
    cog._cache = {"date": today, "products": cached_products}

    with patch.object(cog, "fetch_prices", new_callable=AsyncMock) as mock_fetch:
        result = await cog._price_embed()
        assert isinstance(result, discord.Embed)
        assert len(result.fields) == 1
        assert "Cached Fuel" in result.fields[0].name
        # API should NOT have been called
        mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_another_date(mock_bot, tmp_path):
    today = _get_current_vn_date()
    cache_file = tmp_path / "cache.json"
    stale_products = [{"Title": "Stale Fuel", "Zone1Price": 20000, "Zone2Price": 20500}]
    fresh_products = [{"Title": "Fresh Fuel", "Zone1Price": 26000, "Zone2Price": 26500}]

    # Cache has an older date
    cog = GasPriceCog(mock_bot, cache_file=cache_file)
    cog._cache = {"date": "2020-01-01", "products": stale_products}
    cog._session = MagicMock(spec=aiohttp.ClientSession)

    with patch.object(
        cog, "fetch_prices", new_callable=AsyncMock, return_value=fresh_products
    ) as mock_fetch:
        result = await cog._price_embed()
        assert isinstance(result, discord.Embed)
        assert "Fresh Fuel" in result.fields[0].name
        mock_fetch.assert_called_once()
        # Cache must be updated with today's date
        assert cog._cache["date"] == today
        assert cog._cache["products"] == fresh_products
        # File cache must also be saved
        disk_data = _load_cache(cache_file)
        assert disk_data is not None
        assert disk_data["date"] == today
        assert disk_data["products"] == fresh_products


@pytest.mark.asyncio
async def test_api_error_fallback_to_stale_cache(mock_bot, tmp_path):
    cache_file = tmp_path / "cache.json"
    stale_products = [{"Title": "Stale Fuel", "Zone1Price": 20000, "Zone2Price": 20500}]

    cog = GasPriceCog(mock_bot, cache_file=cache_file)
    cog._cache = {"date": "2020-01-01", "products": stale_products}
    cog._session = MagicMock(spec=aiohttp.ClientSession)

    with patch.object(
        cog,
        "fetch_prices",
        new_callable=AsyncMock,
        side_effect=Exception("API Down"),
    ):
        result = await cog._price_embed()
        # Gracefully falls back to existing cache
        assert isinstance(result, discord.Embed)
        assert "Stale Fuel" in result.fields[0].name


@pytest.mark.asyncio
async def test_price_embed_error_handling_no_cache(mock_bot, tmp_path):
    cache_file = tmp_path / "empty_cache.json"
    cog = GasPriceCog(mock_bot, cache_file=cache_file)
    cog._session = MagicMock(spec=aiohttp.ClientSession)

    with patch.object(
        cog,
        "fetch_prices",
        new_callable=AsyncMock,
        side_effect=Exception("Network error"),
    ):
        result = await cog._price_embed()
        assert isinstance(result, str)
        assert "❌" in result
