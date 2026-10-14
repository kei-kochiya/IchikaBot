import logging
import uuid
from typing import Any

import httpx

from .enums import ItemSource, ItemStatus, SortBy
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

GRAPHQL_SEARCH_QUERY = """
query SearchTop(
  $search: ProductSearchCriteria!,
  $cursor: String,
  $inStock: Boolean,
  $priceMin: Int,
  $priceMax: Int,
  $orderBy: OrderBy,
  $searchSessionId: String!
) {
  products(
    search: $search
    first: 60
    after: $cursor
    inStock: $inStock
    priceMin: $priceMin
    priceMax: $priceMax
    orderBy: $orderBy
    searchSessionId: $searchSessionId
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        price
        inStock
        assets(count: 1) {
          id
          imageUrl(options: { presets: [Small] })
        }
      }
    }
  }
}
"""

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


def _map_sort_by(sort_by: SortBy) -> str:
    mapping = {
        SortBy.NEWEST: "CREATED_AT",
        SortBy.PRICE_ASC: "PRICE_ASC",
        SortBy.PRICE_DESC: "PRICE_DESC",
        SortBy.DEFAULT: "CREATED_AT",
        SortBy.NUM_LIKES: "CREATED_AT",
    }
    return mapping.get(sort_by, "CREATED_AT")


def _build_payload(
    query: str,
    status: ItemStatus = ItemStatus.ON_SALE,
    price_min: int = 0,
    price_max: int = 0,
    sort_by: SortBy = SortBy.DEFAULT,
    cursor: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    variables: dict[str, Any] = {
        "search": {"query": query},
        "orderBy": _map_sort_by(sort_by),
        "searchSessionId": session_id or uuid.uuid4().hex,
        "cursor": cursor,
    }
    if status == ItemStatus.ON_SALE:
        variables["inStock"] = True
    elif status == ItemStatus.SOLD_OUT:
        variables["inStock"] = False

    if price_min > 0:
        variables["priceMin"] = price_min
    if price_max > 0:
        variables["priceMax"] = price_max

    return {
        "operationName": "SearchTop",
        "variables": variables,
        "query": GRAPHQL_SEARCH_QUERY,
    }


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
    """Asynchronous client for Mercari Shops GraphQL API."""

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 15.0):
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=timeout)

    async def close(self):
        if not self._external_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def search_page(
        self,
        query: str,
        status: ItemStatus = ItemStatus.ON_SALE,
        price_min: int = 0,
        price_max: int = 0,
        sort_by: SortBy = SortBy.DEFAULT,
        cursor: str | None = None,
        session_id: str | None = None,
    ) -> tuple[list[MercariItem], bool, str | None]:
        """Fetch a single page of Mercari Shops items."""
        payload = _build_payload(query, status, price_min, price_max, sort_by, cursor, session_id)
        resp = await self._client.post(GRAPHQL_URL, json=payload)
        resp.raise_for_status()

        data = resp.json()
        if "errors" in data:
            log.warning(f"GraphQL returned errors: {data['errors']}")
            return [], False, None

        products_data = data.get("data", {}).get("products")
        if not products_data:
            return [], False, None

        page_info = products_data.get("pageInfo", {})
        has_next = bool(page_info.get("hasNextPage", False))
        next_cursor = page_info.get("endCursor")

        items = [
            _parse_shops_node(e["node"]) for e in products_data.get("edges", []) if "node" in e
        ]
        return items, has_next, next_cursor

    async def get_product(self, product_id: str) -> MercariItem | None:
        """Fetch a single Mercari Shops product by ID asynchronously."""
        payload = {
            "operationName": "GetProduct",
            "variables": {"id": product_id},
            "query": GRAPHQL_GET_PRODUCT_QUERY,
        }
        try:
            resp = await self._client.post(GRAPHQL_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            product = data.get("data", {}).get("product")
            if not product:
                return None
            return _parse_shops_node(product)
        except Exception as e:
            log.warning(f"Error fetching Shops product {product_id}: {e}")
            return None


class SyncShopsClient:
    """Synchronous client for Mercari Shops GraphQL API."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 15.0):
        self._external_client = client is not None
        self._client = client or httpx.Client(headers=DEFAULT_HEADERS, timeout=timeout)

    def close(self):
        if not self._external_client and not self._client.is_closed:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def search_page(
        self,
        query: str,
        status: ItemStatus = ItemStatus.ON_SALE,
        price_min: int = 0,
        price_max: int = 0,
        sort_by: SortBy = SortBy.DEFAULT,
        cursor: str | None = None,
        session_id: str | None = None,
    ) -> tuple[list[MercariItem], bool, str | None]:
        """Fetch a single page of Mercari Shops items synchronously."""
        payload = _build_payload(query, status, price_min, price_max, sort_by, cursor, session_id)
        resp = self._client.post(GRAPHQL_URL, json=payload)
        resp.raise_for_status()

        data = resp.json()
        if "errors" in data:
            log.warning(f"GraphQL returned errors: {data['errors']}")
            return [], False, None

        products_data = data.get("data", {}).get("products")
        if not products_data:
            return [], False, None

        page_info = products_data.get("pageInfo", {})
        has_next = bool(page_info.get("hasNextPage", False))
        next_cursor = page_info.get("endCursor")

        items = [
            _parse_shops_node(e["node"]) for e in products_data.get("edges", []) if "node" in e
        ]
        return items, has_next, next_cursor

    def get_product(self, product_id: str) -> MercariItem | None:
        """Fetch a single Mercari Shops product by ID synchronously."""
        payload = {
            "operationName": "GetProduct",
            "variables": {"id": product_id},
            "query": GRAPHQL_GET_PRODUCT_QUERY,
        }
        try:
            resp = self._client.post(GRAPHQL_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            product = data.get("data", {}).get("product")
            if not product:
                return None
            return _parse_shops_node(product)
        except Exception as e:
            log.warning(f"Error fetching Shops product {product_id}: {e}")
            return None
