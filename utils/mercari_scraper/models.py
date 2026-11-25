from dataclasses import dataclass, field
from datetime import datetime

from .enums import ItemSource


@dataclass
class MercariItem:
    """Unified item listing from either individual sellers (C2C) or Mercari Shops."""

    id: str
    name: str
    price: int
    thumbnail_url: str
    item_url: str
    source: ItemSource
    is_sold: bool
    seller_id: str | None = None
    created_at: datetime | None = None
    photos: list[str] = field(default_factory=list)
