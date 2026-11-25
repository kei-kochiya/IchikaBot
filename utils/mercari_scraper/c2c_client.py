import logging

import httpx
from mercapi import Mercapi

from .enums import ItemSource
from .models import MercariItem

log = logging.getLogger(__name__)


def _parse_c2c_item(item) -> MercariItem:
    item_id = getattr(item, "id_", "") or getattr(item, "id", "")
    photos = getattr(item, "photos", None) or []
    thumbnails = getattr(item, "thumbnails", []) or []
    thumbnail_url = photos[0] if photos else (thumbnails[0] if thumbnails else "")
    status_str = str(getattr(item, "status", None) or "")
    is_sold = bool(
        "SOLD" in status_str
        or "TRADING" in status_str
        or (status_str and "on_sale" not in status_str.lower())
    )
    seller = getattr(item, "seller", None)
    seller_id = getattr(seller, "id_", None) or getattr(item, "seller_id", None)

    return MercariItem(
        id=item_id,
        name=getattr(item, "name", "") or "",
        price=int(getattr(item, "price", 0) or 0),
        thumbnail_url=thumbnail_url,
        item_url=f"https://jp.mercari.com/item/{item_id}",
        source=ItemSource.INDIVIDUAL,
        is_sold=is_sold,
        seller_id=seller_id,
        created_at=getattr(item, "created", None),
        photos=photos,
    )


class AsyncC2CClient:
    """Asynchronous client for Mercari individual C2C item lookups."""

    def __init__(self, timeout: float = 15.0):
        self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        self._mercapi = Mercapi(httpx_client=self._http_client)

    async def close(self) -> None:
        """Close the HTTP client owned by this C2C client."""
        client = getattr(self, "_http_client", None) or getattr(self._mercapi, "_client", None)
        if client is not None and not client.is_closed:
            await client.aclose()

    async def get_item(self, item_id: str) -> MercariItem | None:
        """Fetch a single C2C item by ID asynchronously."""
        try:
            item = await self._mercapi.item(item_id)
            if not item:
                return None
            return _parse_c2c_item(item)
        except Exception as e:
            log.warning("Error fetching C2C item %s: %s", item_id, e)
            return None
