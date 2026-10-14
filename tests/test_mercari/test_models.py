from utils.mercari_scraper import ItemSource, MercariItem


def test_mercari_item_creation_and_to_dict():
    item = MercariItem(
        id="m12345",
        name="Test Pokemon Card",
        price=1500,
        thumbnail_url="https://example.com/thumb.jpg",
        item_url="https://jp.mercari.com/item/m12345",
        source=ItemSource.INDIVIDUAL,
        is_sold=False,
        seller_id="seller99",
    )
    assert item.id == "m12345"
    assert item.price == 1500
    assert item.is_sold is False
    assert item.source == ItemSource.INDIVIDUAL

    d = item.to_dict()
    assert d["id"] == "m12345"
    assert d["source"] == "individual"
    assert d["price"] == 1500
    assert d["is_sold"] is False
    assert d["item_url"] == "https://jp.mercari.com/item/m12345"
