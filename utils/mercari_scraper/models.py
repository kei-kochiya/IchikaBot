from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .enums import ItemSource


@dataclass
class MercariItem:
    """Represents a unified item listing from either individual sellers or Mercari Shops."""

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

    def to_dict(self) -> dict[str, Any]:
        """Convert the item to a JSON-serializable dictionary."""
        data = asdict(self)
        data["source"] = (
            self.source.value if isinstance(self.source, ItemSource) else str(self.source)
        )
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        return data
