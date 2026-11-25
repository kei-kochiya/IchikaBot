"""Live external API contract checks (skipped by default; run with `pytest -m live`)."""

import aiohttp
import pytest

from cogs.misc.gas_price import fetch_prices
from utils.mercari_scraper import AsyncMercariScraper

pytestmark = pytest.mark.live


async def test_petrolimex_api_contract():
    """Verify Petrolimex still returns retail fuel products with expected price fields."""
    async with aiohttp.ClientSession() as session:
        products = await fetch_prices(session)

    assert len(products) > 0
    first = products[0]
    assert first.get("Title") or first.get("EnglishTitle")
    assert first.get("Zone1Price") is not None
    assert first.get("Zone2Price") is not None


async def test_mercari_shops_graphql_reachable():
    """Verify Mercari Shops GraphQL endpoint responds cleanly (even for a nonexistent ID)."""
    async with AsyncMercariScraper() as scraper:
        result = await scraper.get_item("https://jp.mercari.com/shops/product/nonexistent_test_id")
    assert result is None
