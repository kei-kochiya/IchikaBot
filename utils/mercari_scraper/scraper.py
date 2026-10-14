import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterator

import httpx

from .c2c_client import AsyncC2CClient, SyncC2CClient
from .enums import ItemSource, ItemStatus, SortBy
from .models import MercariItem
from .shops_client import AsyncShopsClient, SyncShopsClient

log = logging.getLogger(__name__)


def extract_item_info(text: str) -> tuple[str, ItemSource | None]:
    """Extract item ID and source hint from full URL or bare ID string."""
    clean = text.strip()
    if "shops/product/" in clean or "mercari-shops.com" in clean:
        item_id = clean.split("?")[0].rstrip("/").split("/")[-1]
        return item_id, ItemSource.SHOPS

    item_id = clean.split("?")[0].rstrip("/").split("/")[-1]
    if item_id.startswith("m") and len(item_id) > 5 and item_id[1:].isdigit():
        return item_id, ItemSource.INDIVIDUAL

    return item_id, None


def _sort_items(items: list[MercariItem], sort_by: SortBy) -> list[MercariItem]:
    """Sort a unified list of items based on requested order."""
    if sort_by == SortBy.PRICE_ASC:
        return sorted(items, key=lambda x: x.price)
    elif sort_by == SortBy.PRICE_DESC:
        return sorted(items, key=lambda x: x.price, reverse=True)
    return items


class AsyncMercariScraper:
    """Asynchronous Mercari JP Scraper supporting both Individual and Shop items with <1GB RAM."""

    def __init__(
        self,
        delay: float = 0.5,
        timeout: float = 15.0,
        max_retries: int = 3,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self._c2c_client = AsyncC2CClient()
        self._shops_client = AsyncShopsClient(client=http_client, timeout=timeout)

    async def close(self):
        """Release underlying HTTP client resources."""
        await self._shops_client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def search_iter(
        self,
        query: str,
        source: ItemSource = ItemSource.ALL,
        status: ItemStatus = ItemStatus.ON_SALE,
        price_min: int = 0,
        price_max: int = 0,
        sort_by: SortBy = SortBy.DEFAULT,
        limit: int | None = None,
    ) -> AsyncIterator[MercariItem]:
        """Stream items one by one across pages, fetching both individual and shops items."""
        yielded_count = 0
        seen_ids: set[str] = set()

        c2c_token: str | None = None
        c2c_has_next = source in (ItemSource.ALL, ItemSource.INDIVIDUAL)

        shops_cursor: str | None = None
        shops_has_next = source in (ItemSource.ALL, ItemSource.SHOPS)

        is_first_page = True

        while c2c_has_next or shops_has_next:
            if not is_first_page and self.delay > 0:
                await asyncio.sleep(self.delay)
            is_first_page = False

            batch: list[MercariItem] = []

            c2c_items: list[MercariItem] = []
            shops_items: list[MercariItem] = []

            # 1. Fetch individual C2C listings if active
            if c2c_has_next:
                try:
                    c2c_items, c2c_has_next, c2c_token = await self._c2c_client.search_page(
                        query=query,
                        status=status,
                        price_min=price_min,
                        price_max=price_max,
                        sort_by=sort_by,
                        page_token=c2c_token,
                    )
                except Exception as e:
                    log.warning(f"Error fetching C2C page: {e}")
                    c2c_has_next = False

            # 2. Fetch Mercari Shops listings if active
            if shops_has_next:
                try:
                    (
                        shops_items,
                        shops_has_next,
                        shops_cursor,
                    ) = await self._shops_client.search_page(
                        query=query,
                        status=status,
                        price_min=price_min,
                        price_max=price_max,
                        sort_by=sort_by,
                        cursor=shops_cursor,
                    )
                except Exception as e:
                    log.warning(f"Error fetching Shops page: {e}")
                    shops_has_next = False

            if not c2c_items and not shops_items:
                break

            # When merging ALL sources, interleave items evenly
            if source == ItemSource.ALL and c2c_items and shops_items:
                batch = []
                max_l = max(len(c2c_items), len(shops_items))
                for idx in range(max_l):
                    if idx < len(c2c_items):
                        batch.append(c2c_items[idx])
                    if idx < len(shops_items):
                        batch.append(shops_items[idx])
            else:
                batch = c2c_items + shops_items

            # Deduplicate and sort within batch
            batch = _sort_items(batch, sort_by)

            for item in batch:
                if item.id in seen_ids:
                    continue
                seen_ids.add(item.id)
                yield item
                yielded_count += 1
                if limit is not None and yielded_count >= limit:
                    return

    async def search(
        self,
        query: str,
        source: ItemSource = ItemSource.ALL,
        status: ItemStatus = ItemStatus.ON_SALE,
        price_min: int = 0,
        price_max: int = 0,
        sort_by: SortBy = SortBy.DEFAULT,
        limit: int = 120,
    ) -> list[MercariItem]:
        """Fetch items up to the requested limit."""
        results: list[MercariItem] = []
        async for item in self.search_iter(
            query=query,
            source=source,
            status=status,
            price_min=price_min,
            price_max=price_max,
            sort_by=sort_by,
            limit=limit,
        ):
            results.append(item)
        return _sort_items(results, sort_by)

    async def get_item(self, item_id_or_url: str) -> MercariItem | None:
        """Look up a single item by ID or full URL across Individual C2C or Mercari Shops."""
        item_id, source_hint = extract_item_info(item_id_or_url)

        if source_hint == ItemSource.SHOPS:
            return await self._shops_client.get_product(item_id)
        elif source_hint == ItemSource.INDIVIDUAL:
            return await self._c2c_client.get_item(item_id)

        # Unknown hint: try C2C first, fallback to Shops
        c2c_item = await self._c2c_client.get_item(item_id)
        if c2c_item:
            return c2c_item
        return await self._shops_client.get_product(item_id)


class MercariScraper:
    """Synchronous Mercari JP Scraper supporting both Individual and Shop items with <1GB RAM."""

    def __init__(
        self,
        delay: float = 0.5,
        timeout: float = 15.0,
        max_retries: int = 3,
        http_client: httpx.Client | None = None,
    ):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self._c2c_client = SyncC2CClient()
        self._shops_client = SyncShopsClient(client=http_client, timeout=timeout)

    def close(self):
        """Release underlying HTTP client resources."""
        self._c2c_client.close()
        self._shops_client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def search_iter(
        self,
        query: str,
        source: ItemSource = ItemSource.ALL,
        status: ItemStatus = ItemStatus.ON_SALE,
        price_min: int = 0,
        price_max: int = 0,
        sort_by: SortBy = SortBy.DEFAULT,
        limit: int | None = None,
    ) -> Iterator[MercariItem]:
        """Synchronously stream items one by one across pages."""
        yielded_count = 0
        seen_ids: set[str] = set()

        c2c_token: str | None = None
        c2c_has_next = source in (ItemSource.ALL, ItemSource.INDIVIDUAL)

        shops_cursor: str | None = None
        shops_has_next = source in (ItemSource.ALL, ItemSource.SHOPS)

        is_first_page = True

        while c2c_has_next or shops_has_next:
            if not is_first_page and self.delay > 0:
                time.sleep(self.delay)
            is_first_page = False

            batch: list[MercariItem] = []

            c2c_items: list[MercariItem] = []
            shops_items: list[MercariItem] = []

            # 1. Fetch individual C2C listings if active
            if c2c_has_next:
                try:
                    c2c_items, c2c_has_next, c2c_token = self._c2c_client.search_page(
                        query=query,
                        status=status,
                        price_min=price_min,
                        price_max=price_max,
                        sort_by=sort_by,
                        page_token=c2c_token,
                    )
                except Exception as e:
                    log.warning(f"Error fetching C2C page: {e}")
                    c2c_has_next = False

            # 2. Fetch Mercari Shops listings if active
            if shops_has_next:
                try:
                    shops_items, shops_has_next, shops_cursor = self._shops_client.search_page(
                        query=query,
                        status=status,
                        price_min=price_min,
                        price_max=price_max,
                        sort_by=sort_by,
                        cursor=shops_cursor,
                    )
                except Exception as e:
                    log.warning(f"Error fetching Shops page: {e}")
                    shops_has_next = False

            if not c2c_items and not shops_items:
                break

            # When merging ALL sources, interleave items evenly
            if source == ItemSource.ALL and c2c_items and shops_items:
                batch = []
                max_l = max(len(c2c_items), len(shops_items))
                for idx in range(max_l):
                    if idx < len(c2c_items):
                        batch.append(c2c_items[idx])
                    if idx < len(shops_items):
                        batch.append(shops_items[idx])
            else:
                batch = c2c_items + shops_items

            # Deduplicate and sort within batch
            batch = _sort_items(batch, sort_by)

            for item in batch:
                if item.id in seen_ids:
                    continue
                seen_ids.add(item.id)
                yield item
                yielded_count += 1
                if limit is not None and yielded_count >= limit:
                    return

    def search(
        self,
        query: str,
        source: ItemSource = ItemSource.ALL,
        status: ItemStatus = ItemStatus.ON_SALE,
        price_min: int = 0,
        price_max: int = 0,
        sort_by: SortBy = SortBy.DEFAULT,
        limit: int = 120,
    ) -> list[MercariItem]:
        """Synchronously fetch items up to the requested limit."""
        results: list[MercariItem] = []
        for item in self.search_iter(
            query=query,
            source=source,
            status=status,
            price_min=price_min,
            price_max=price_max,
            sort_by=sort_by,
            limit=limit,
        ):
            results.append(item)
        return _sort_items(results, sort_by)

    def get_item(self, item_id_or_url: str) -> MercariItem | None:
        """Look up a single item by ID or full URL across Individual C2C or Mercari Shops synchronously."""
        item_id, source_hint = extract_item_info(item_id_or_url)

        if source_hint == ItemSource.SHOPS:
            return self._shops_client.get_product(item_id)
        elif source_hint == ItemSource.INDIVIDUAL:
            return self._c2c_client.get_item(item_id)

        c2c_item = self._c2c_client.get_item(item_id)
        if c2c_item:
            return c2c_item
        return self._shops_client.get_product(item_id)
