from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogs.misc.mercari import (
    MercariCog,
    _build_item_embed,
    _compute_vnd_price,
    extract_item_id,
)
from utils.mercari_scraper import ItemSource, MercariItem


def test_extract_item_id():
    assert extract_item_id("m12345678901") == "m12345678901"
    assert extract_item_id("https://jp.mercari.com/item/m12345678901") == "m12345678901"
    assert (
        extract_item_id("https://jp.mercari.com/item/m12345678901?source=shared") == "m12345678901"
    )
    assert (
        extract_item_id("https://jp.mercari.com/shops/product/2JXEJvn8QLxnZwwEJZ4RfK")
        == "2JXEJvn8QLxnZwwEJZ4RfK"
    )


def test_compute_vnd_price():
    # Regular user: 1000 * 182 + 10,000 = 192,000
    regular_user = 999999999999999999
    assert _compute_vnd_price(1000, regular_user) == 192000

    # Preferred users: 1000 * 180 + 10,000 = 190,000
    for uid in (304351602637012992, 602357018782597120, 458547599947857920):
        assert _compute_vnd_price(1000, uid) == 190000


def test_build_item_embed_c2c():
    item = MercariItem(
        id="m12345",
        name="Test C2C Item",
        price=5000,
        thumbnail_url="https://example.com/thumb.jpg",
        item_url="https://jp.mercari.com/item/m12345",
        source=ItemSource.INDIVIDUAL,
        is_sold=False,
        photos=["https://example.com/1.jpg", "https://example.com/2.jpg"],
    )

    embed = _build_item_embed(item, user_id=123)
    assert isinstance(embed, discord.Embed)
    assert embed.title == "Test C2C Item"
    assert embed.color == discord.Color.green()
    assert len(embed.fields) == 3
    assert embed.fields[0].name == "Giá gốc (JPY)"
    assert embed.fields[0].value == "¥5,000"
    assert embed.fields[1].name == "Giá (VND)"
    # 5000 * 182 + 10_000 = 920,000
    assert embed.fields[1].value == "920,000 VND"
    assert embed.fields[2].name == "Trạng thái"
    assert embed.fields[2].value == "🟢 Còn hàng"
    assert "Mercari C2C" in embed.footer.text


def test_build_item_embed_shops_sold():
    item = MercariItem(
        id="shop123",
        name="Test Shop Item",
        price=10000,
        thumbnail_url="https://example.com/thumb.jpg",
        item_url="https://jp.mercari.com/shops/product/shop123",
        source=ItemSource.SHOPS,
        is_sold=True,
        photos=["https://example.com/1.jpg"],
    )

    embed = _build_item_embed(item, user_id=304351602637012992)
    assert isinstance(embed, discord.Embed)
    assert embed.title == "Test Shop Item"
    assert embed.color == discord.Color.red()
    # Preferred user: 10000 * 180 + 10_000 = 1,810,000
    assert embed.fields[1].value == "1,810,000 VND"
    assert embed.fields[2].value == "🔴 Sold"
    assert "Mercari Shops" in embed.footer.text


@pytest.mark.asyncio
async def test_lookup_c2c(mock_bot):
    cog = MercariCog(mock_bot)
    fake_item = MercariItem(
        id="m999",
        name="Pikachu Plush",
        price=3000,
        thumbnail_url="https://example.com/pika.jpg",
        item_url="https://jp.mercari.com/item/m999",
        source=ItemSource.INDIVIDUAL,
        is_sold=False,
    )

    mock_scraper = MagicMock()
    mock_scraper.get_item = AsyncMock(return_value=fake_item)
    cog._scraper = mock_scraper

    result = await cog._lookup("m999", 123)
    assert isinstance(result, discord.Embed)
    assert result.title == "Pikachu Plush"


@pytest.mark.asyncio
async def test_lookup_not_found(mock_bot):
    cog = MercariCog(mock_bot)
    mock_scraper = MagicMock()
    mock_scraper.get_item = AsyncMock(return_value=None)
    cog._scraper = mock_scraper

    result = await cog._lookup("m000", 123)
    assert isinstance(result, str)
    assert "Không tìm thấy" in result


@pytest.mark.asyncio
async def test_search_embed(mock_bot):
    cog = MercariCog(mock_bot)
    fake_items = [
        MercariItem(
            id="m1",
            name="Zelda 1",
            price=2000,
            thumbnail_url="https://example.com/z1.jpg",
            item_url="https://jp.mercari.com/item/m1",
            source=ItemSource.INDIVIDUAL,
            is_sold=False,
        ),
        MercariItem(
            id="s1",
            name="Zelda 2",
            price=3000,
            thumbnail_url="https://example.com/z2.jpg",
            item_url="https://jp.mercari.com/shops/product/s1",
            source=ItemSource.SHOPS,
            is_sold=False,
        ),
    ]

    mock_scraper = MagicMock()
    mock_scraper.search = AsyncMock(return_value=fake_items)
    cog._scraper = mock_scraper

    result = await cog._search_embed("zelda", "all", 123)
    assert isinstance(result, discord.Embed)
    assert "zelda" in result.title
    assert len(result.fields) == 2
    assert "Zelda 1" in result.fields[0].value
    assert "Zelda 2" in result.fields[1].value


@pytest.mark.asyncio
async def test_search_embed_empty(mock_bot):
    cog = MercariCog(mock_bot)
    mock_scraper = MagicMock()
    mock_scraper.search = AsyncMock(return_value=[])
    cog._scraper = mock_scraper

    result = await cog._search_embed("nonexistent_item_xyz", "all", 123)
    assert isinstance(result, str)
    assert "Không tìm thấy" in result
