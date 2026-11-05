"""
Mercari JP Scraper - High performance, <1GB RAM Mercari Japan Scraper.
Supports both Individual C2C Listings and Mercari Shops Products.
"""

from .enums import ItemSource, ItemStatus, SortBy
from .models import MercariItem
from .urls import extract_item_info

# The scraper classes pull in httpx and mercapi (~12 MB RAM, ~0.2 s to import): load them
# only when they are first used, not whenever the package is imported.
_LAZY = {"AsyncMercariScraper", "MercariScraper"}


def __getattr__(name: str):
    if name in _LAZY:
        from . import scraper

        return getattr(scraper, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__version__ = "0.1.0"
__all__ = [
    "AsyncMercariScraper",
    "ItemSource",
    "ItemStatus",
    "MercariItem",
    "MercariScraper",
    "SortBy",
    "extract_item_info",
]
