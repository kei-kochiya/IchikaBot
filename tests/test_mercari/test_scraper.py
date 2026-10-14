import pytest

from mercari_scraper import AsyncMercariScraper, ItemSource, MercariScraper


def test_sync_scraper_search_both_sources():
    with MercariScraper() as scraper:
        items = scraper.search("pikachu", source=ItemSource.ALL, limit=20)
        assert len(items) == 20
        sources = {item.source for item in items}
        # Both individual and shops should be present
        assert ItemSource.INDIVIDUAL in sources
        assert ItemSource.SHOPS in sources


def test_sync_scraper_search_individual_only():
    with MercariScraper() as scraper:
        items = scraper.search("pikachu", source=ItemSource.INDIVIDUAL, limit=10)
        assert len(items) == 10
        for item in items:
            assert item.source == ItemSource.INDIVIDUAL
            assert item.id.startswith("m")


def test_sync_scraper_search_shops_only():
    with MercariScraper() as scraper:
        items = scraper.search("pikachu", source=ItemSource.SHOPS, limit=10)
        assert len(items) == 10
        for item in items:
            assert item.source == ItemSource.SHOPS
            assert not item.id.startswith("m")


@pytest.mark.asyncio
async def test_async_scraper_search():
    async with AsyncMercariScraper() as scraper:
        items = await scraper.search("pikachu", source=ItemSource.ALL, limit=20)
        assert len(items) == 20
        sources = {item.source for item in items}
        assert ItemSource.INDIVIDUAL in sources
        assert ItemSource.SHOPS in sources
