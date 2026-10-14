from mercapi.requests.search import SearchRequestData

from utils.mercari_scraper.c2c_client import SyncC2CClient, _map_c2c_sorting, _map_c2c_status
from utils.mercari_scraper.enums import ItemSource, ItemStatus, SortBy


def test_map_c2c_status():
    assert _map_c2c_status(ItemStatus.ON_SALE) == [SearchRequestData.Status.STATUS_ON_SALE]
    assert _map_c2c_status(ItemStatus.SOLD_OUT) == [SearchRequestData.Status.STATUS_SOLD_OUT]
    assert _map_c2c_status(ItemStatus.ALL) == []


def test_map_c2c_sorting():
    by, order = _map_c2c_sorting(SortBy.PRICE_ASC)
    assert by == SearchRequestData.SortBy.SORT_PRICE
    assert order == SearchRequestData.SortOrder.ORDER_ASC


def test_live_c2c_search_page():
    client = SyncC2CClient()
    items, has_next, token = client.search_page("pikachu")
    assert len(items) > 0
    assert items[0].source == ItemSource.INDIVIDUAL
    assert items[0].item_url.startswith("https://jp.mercari.com/item/m")
