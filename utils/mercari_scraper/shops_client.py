import logging
from typing import Any

import aiohttp

from config import SharedResources

from .enums import ItemSource
from .models import MercariItem

log = logging.getLogger(__name__)

GRAPHQL_URL = "https://mercari-shops.com/graphql"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "x-data-fetch-for": "csr",
    "Origin": "https://mercari-shops.com",
    "Referer": "https://mercari-shops.com/",
}

GRAPHQL_GET_PRODUCT_QUERY = """
query GetProduct($id: String!) {
  product(id: $id) {
    id
    name
    price
    inStock
    assets(count: 10) {
      id
      imageUrl(options: { presets: [Small] })
    }
  }
}
"""


def _parse_shops_node(node: dict[str, Any]) -> MercariItem:
    item_id = node.get("id", "")
    assets = node.get("assets", [])
    photos = [a["imageUrl"] for a in assets if isinstance(a, dict) and a.get("imageUrl")]
    thumbnail_url = photos[0] if photos else ""

    in_stock = node.get("inStock", True)
    return MercariItem(
        id=item_id,
        name=node.get("name", ""),
        price=int(node.get("price", 0)),
        thumbnail_url=thumbnail_url,
        item_url=f"https://jp.mercari.com/shops/product/{item_id}",
        source=ItemSource.SHOPS,
        is_sold=not in_stock,
        photos=photos,
    )


class AsyncShopsClient:
    """Asynchronous client for Mercari Shops single-product lookups via shared aiohttp."""

    def __init__(self, timeout: float = 15.0, graphql_url: str = GRAPHQL_URL):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._graphql_url = graphql_url

    async def close(self) -> None:
        """No-op: uses the bot's shared aiohttp session."""

    async def get_product(self, product_id: str) -> MercariItem | None:
        """Fetch a single Mercari Shops product by ID asynchronously."""
        payload = {
            "operationName": "GetProduct",
            "variables": {"id": product_id},
            "query": GRAPHQL_GET_PRODUCT_QUERY,
        }
        try:
            session = await SharedResources.get_session()
            async with session.post(
                self._graphql_url,
                json=payload,
                headers=DEFAULT_HEADERS,
                timeout=self._timeout,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
            product = (data.get("data") or {}).get("product")
            if not product:
                return None
            return _parse_shops_node(product)
        except Exception as e:
            log.warning("Error fetching Shops product %s: %s", product_id, e)
            return None
