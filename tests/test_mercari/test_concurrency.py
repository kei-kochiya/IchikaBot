"""Offline tests: the scraper's page-fetch logic with stand-in marketplace clients."""

import asyncio

import pytest

from utils.mercari_scraper import AsyncMercariScraper, ItemSource, MercariItem


def _item(item_id: str, source: ItemSource, price: int = 100) -> MercariItem:
    return MercariItem(
        id=item_id,
        name=item_id,
        price=price,
        thumbnail_url="",
        item_url=f"https://example.invalid/{item_id}",
        source=source,
        is_sold=False,
    )


class _Marketplace:
    """Stand-in client. Each instance waits for its peer to start before returning."""

    def __init__(self, items, fail=False):
        self.items = items
        self.fail = fail
        self.started = asyncio.Event()
        self.peer: _Marketplace | None = None

    async def search_page(self, **_kwargs):
        self.started.set()
        if self.peer is not None:
            # Only completes if the other client is queried at the same time
            await asyncio.wait_for(self.peer.started.wait(), timeout=1.0)
        if self.fail:
            raise RuntimeError("upstream down")
        return self.items, False, None


@pytest.fixture
def scraper():
    s = AsyncMercariScraper(delay=0)
    s._c2c_client = _Marketplace([_item("m1", ItemSource.INDIVIDUAL)])
    s._shops_client = _Marketplace([_item("s1", ItemSource.SHOPS)])
    s._c2c_client.peer, s._shops_client.peer = s._shops_client, s._c2c_client
    return s


@pytest.mark.asyncio
async def test_both_marketplaces_are_queried_concurrently(scraper):
    items = await scraper.search("pikachu", source=ItemSource.ALL, limit=10)

    assert {i.id for i in items} == {"m1", "s1"}


@pytest.mark.asyncio
async def test_one_marketplace_failing_does_not_lose_the_other(scraper):
    scraper._c2c_client.fail = True

    items = await scraper.search("pikachu", source=ItemSource.ALL, limit=10)

    assert [i.id for i in items] == ["s1"]


@pytest.mark.asyncio
async def test_single_source_search_only_queries_that_source(scraper):
    scraper._c2c_client.peer = scraper._shops_client.peer = None

    items = await scraper.search("pikachu", source=ItemSource.SHOPS, limit=10)

    assert [i.id for i in items] == ["s1"]
    assert not scraper._c2c_client.started.is_set()


@pytest.mark.asyncio
async def test_close_releases_the_c2c_http_client():
    scraper = AsyncMercariScraper()
    http_client = scraper._c2c_client._mercapi._client
    assert not http_client.is_closed

    await scraper.close()

    assert http_client.is_closed
