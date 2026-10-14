from enum import StrEnum


class ItemSource(StrEnum):
    """Source of Mercari listings."""

    ALL = "all"
    INDIVIDUAL = "individual"
    SHOPS = "shops"


class ItemStatus(StrEnum):
    """Listing status filter."""

    ALL = "all"
    ON_SALE = "on_sale"
    SOLD_OUT = "sold_out"


class SortBy(StrEnum):
    """Sort order for results."""

    DEFAULT = "default"  # Score / Recommended
    NEWEST = "newest"  # Created time descending
    PRICE_ASC = "price_asc"  # Lowest price first
    PRICE_DESC = "price_desc"  # Highest price first
    NUM_LIKES = "num_likes"  # Most likes
