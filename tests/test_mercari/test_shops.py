from utils.mercari_scraper.enums import ItemSource, ItemStatus, SortBy
from utils.mercari_scraper.shops_client import (
    SyncShopsClient,
    _build_payload,
    _parse_shops_node,
)


def test_parse_shops_node():
    node = {
        "id": "2JQWJsrefiPSsATsQHvT5v",
        "name": "Shop Item Test",
        "price": 3200,
        "inStock": True,
        "assets": [{"id": "a1", "imageUrl": "https://example.com/asset.jpg"}],
    }
    item = _parse_shops_node(node)
    assert item.id == "2JQWJsrefiPSsATsQHvT5v"
    assert item.name == "Shop Item Test"
    assert item.price == 3200
    assert item.thumbnail_url == "https://example.com/asset.jpg"
    assert item.item_url == "https://jp.mercari.com/shops/product/2JQWJsrefiPSsATsQHvT5v"
    assert item.source == ItemSource.SHOPS
    assert item.is_sold is False


def test_build_payload():
    payload = _build_payload("pikachu", ItemStatus.ON_SALE, 1000, 5000, SortBy.PRICE_ASC)
    assert payload["operationName"] == "SearchTop"
    vars_ = payload["variables"]
    assert vars_["search"]["query"] == "pikachu"
    assert vars_["inStock"] is True
    assert vars_["priceMin"] == 1000
    assert vars_["priceMax"] == 5000
    assert vars_["orderBy"] == "PRICE_ASC"


def test_live_shops_search_page():
    with SyncShopsClient() as client:
        items, has_next, cursor = client.search_page("pikachu")
        assert len(items) > 0
        assert items[0].source == ItemSource.SHOPS
        assert items[0].item_url.startswith("https://jp.mercari.com/shops/product/")
