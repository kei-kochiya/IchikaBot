"""Mercari URL / item ID parsing. Kept free of HTTP libraries so it is cheap to import."""

import re
from urllib.parse import urlparse

from .enums import ItemSource

_MERCARI_HOSTS = ("mercari.com", "mercari.jp", "mercari-shops.com")


def extract_item_info(text: str) -> tuple[str, ItemSource | None]:
    """Extract item ID and source hint from full URL or bare ID string."""
    clean = text.strip().strip("<>").strip()
    if not clean or any(ch.isspace() for ch in clean):
        return "", None
    base = re.split(r"[?#]", clean, maxsplit=1)[0].rstrip("/")
    base_lower = base.lower()
    if base_lower.startswith(("http://", "https://")):
        parsed = urlparse(base)
        host = (parsed.hostname or "").lower()
        if not any(host == h or host.endswith(f".{h}") for h in _MERCARI_HOSTS):
            return "", None
        path_parts = [p for p in parsed.path.split("/") if p]
        if not path_parts or path_parts[-1].lower() in ("item", "items", "product", "products"):
            return "", None
        item_id = path_parts[-1]
    else:
        item_id = base.split("/")[-1]
    if "shops/product/" in base_lower or "mercari-shops.com" in base_lower:
        return item_id, ItemSource.SHOPS

    if (
        item_id.startswith("m")
        and len(item_id) > 5
        and item_id[1:].isascii()
        and item_id[1:].isdigit()
    ):
        return item_id, ItemSource.INDIVIDUAL

    return item_id, None
