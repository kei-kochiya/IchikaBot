from __future__ import annotations

from typing import TYPE_CHECKING

from .enums import ItemSource
from .models import MercariItem
from .shops_client import AsyncShopsClient
from .urls import extract_item_info

if TYPE_CHECKING:
    from .c2c_client import AsyncC2CClient


class AsyncMercariScraper:
    """Asynchronous Mercari JP item lookup for Individual C2C and Mercari Shops links."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self._c2c_client: AsyncC2CClient | None = None
        self._shops_client = AsyncShopsClient(timeout=timeout)

    def _get_c2c_client(self) -> AsyncC2CClient:
        # Import mercapi/httpx only when a C2C (or unknown) item is actually looked up.
        if self._c2c_client is None:
            from .c2c_client import AsyncC2CClient

            self._c2c_client = AsyncC2CClient(timeout=self.timeout)
        return self._c2c_client

    async def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._c2c_client is not None:
            client, self._c2c_client = self._c2c_client, None
            await client.close()
        await self._shops_client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get_item(self, item_id_or_url: str) -> MercariItem | None:
        """Look up a single item by ID or full URL across Individual C2C or Mercari Shops."""
        item_id, source_hint = extract_item_info(item_id_or_url)
        if not item_id:
            return None

        if source_hint == ItemSource.SHOPS:
            return await self._shops_client.get_product(item_id)
        if source_hint == ItemSource.INDIVIDUAL:
            return await self._get_c2c_client().get_item(item_id)

        # Unknown hint: try C2C first, fallback to Shops
        c2c_item = await self._get_c2c_client().get_item(item_id)
        if c2c_item:
            return c2c_item
        return await self._shops_client.get_product(item_id)
