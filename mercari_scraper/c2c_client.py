import asyncio
import logging
import threading

from mercapi import Mercapi
from mercapi.requests.search import SearchRequestData

from .enums import ItemSource, ItemStatus, SortBy
from .models import MercariItem

log = logging.getLogger(__name__)


def _map_c2c_status(status: ItemStatus) -> list[SearchRequestData.Status]:
    if status == ItemStatus.ON_SALE:
        return [SearchRequestData.Status.STATUS_ON_SALE]
    elif status == ItemStatus.SOLD_OUT:
        return [SearchRequestData.Status.STATUS_SOLD_OUT]
    return []


def _map_c2c_sorting(
    sort_by: SortBy,
) -> tuple[SearchRequestData.SortBy, SearchRequestData.SortOrder]:
    if sort_by == SortBy.NEWEST:
        return SearchRequestData.SortBy.SORT_CREATED_TIME, SearchRequestData.SortOrder.ORDER_DESC
    elif sort_by == SortBy.PRICE_ASC:
        return SearchRequestData.SortBy.SORT_PRICE, SearchRequestData.SortOrder.ORDER_ASC
    elif sort_by == SortBy.PRICE_DESC:
        return SearchRequestData.SortBy.SORT_PRICE, SearchRequestData.SortOrder.ORDER_DESC
    elif sort_by == SortBy.NUM_LIKES:
        return SearchRequestData.SortBy.SORT_NUM_LIKES, SearchRequestData.SortOrder.ORDER_DESC
    return SearchRequestData.SortBy.SORT_SCORE, SearchRequestData.SortOrder.ORDER_DESC


def _parse_c2c_item(item) -> MercariItem:
    item_id = getattr(item, "id_", "") or getattr(item, "id", "")
    photos = getattr(item, "photos", None) or []
    thumbnails = getattr(item, "thumbnails", []) or []
    thumbnail_url = photos[0] if photos else (thumbnails[0] if thumbnails else "")
    status_str = str(getattr(item, "status", ""))
    is_sold = (
        "SOLD" in status_str
        or "TRADING" in status_str
        or (status_str and "on_sale" not in status_str.lower())
    )

    return MercariItem(
        id=item_id,
        name=getattr(item, "name", "") or "",
        price=int(getattr(item, "price", 0) or 0),
        thumbnail_url=thumbnail_url,
        item_url=f"https://jp.mercari.com/item/{item_id}",
        source=ItemSource.INDIVIDUAL,
        is_sold=is_sold,
        seller_id=getattr(item, "seller_id", None),
        created_at=getattr(item, "created", None),
        photos=photos,
    )


class AsyncC2CClient:
    """Asynchronous client for Mercari individual C2C marketplace listings."""

    def __init__(self):
        self._mercapi = Mercapi()

    async def get_item(self, item_id: str) -> MercariItem | None:
        """Fetch a single C2C item by ID asynchronously."""
        try:
            item = await self._mercapi.item(item_id)
            if not item:
                return None
            return _parse_c2c_item(item)
        except Exception as e:
            log.warning(f"Error fetching C2C item {item_id}: {e}")
            return None

    async def search_page(
        self,
        query: str,
        status: ItemStatus = ItemStatus.ON_SALE,
        price_min: int = 0,
        price_max: int = 0,
        sort_by: SortBy = SortBy.DEFAULT,
        page_token: str | None = None,
    ) -> tuple[list[MercariItem], bool, str | None]:
        """Fetch a page of individual C2C listings asynchronously."""
        c2c_status = _map_c2c_status(status)
        c2c_sort_by, c2c_sort_order = _map_c2c_sorting(sort_by)

        res = await self._mercapi.search(
            query=query,
            status=c2c_status,
            price_min=price_min,
            price_max=price_max,
            sort_by=c2c_sort_by,
            sort_order=c2c_sort_order,
            page_token=page_token,
        )

        items = [_parse_c2c_item(i) for i in res.items]
        next_token = (
            getattr(res.meta, "next_page_token", None) if getattr(res, "meta", None) else None
        )
        has_next = bool(next_token)
        return items, has_next, next_token


class _LoopWorker:
    """Manages a single dedicated background thread and event loop for sync operations."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coro(self, coro):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result()

    def close(self):
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2.0)
            self.loop.close()


class SyncC2CClient:
    """Synchronous client for Mercari individual C2C marketplace listings."""

    def __init__(self):
        self._worker = _LoopWorker()
        self._async_client = None

    def _get_client(self):
        if self._async_client is None:
            # Create AsyncC2CClient inside worker loop
            self._async_client = self._worker.run_coro(self._init_async())
        return self._async_client

    async def _init_async(self):
        return AsyncC2CClient()

    def close(self):
        self._worker.close()

    def search_page(
        self,
        query: str,
        status: ItemStatus = ItemStatus.ON_SALE,
        price_min: int = 0,
        price_max: int = 0,
        sort_by: SortBy = SortBy.DEFAULT,
        page_token: str | None = None,
    ) -> tuple[list[MercariItem], bool, str | None]:
        """Fetch a page of individual C2C listings synchronously."""
        client = self._get_client()
        return self._worker.run_coro(
            client.search_page(
                query=query,
                status=status,
                price_min=price_min,
                price_max=price_max,
                sort_by=sort_by,
                page_token=page_token,
            )
        )

    def get_item(self, item_id: str) -> MercariItem | None:
        """Fetch a single C2C item by ID synchronously."""
        client = self._get_client()
        return self._worker.run_coro(client.get_item(item_id))
