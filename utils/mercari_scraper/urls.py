"""Mercari URL / item ID parsing. Kept free of HTTP libraries so it is cheap to import."""

from .enums import ItemSource


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
