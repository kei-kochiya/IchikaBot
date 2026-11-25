"""
Mercari JP item lookup (Individual C2C & Mercari Shops).
"""

from .enums import ItemSource
from .models import MercariItem
from .urls import extract_item_info

# AsyncMercariScraper is loaded lazily on first use so idle startup stays lean.
_LAZY = {"AsyncMercariScraper"}


def __getattr__(name: str):
    if name in _LAZY:
        from . import scraper

        return getattr(scraper, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AsyncMercariScraper",
    "ItemSource",
    "MercariItem",
    "extract_item_info",
]
