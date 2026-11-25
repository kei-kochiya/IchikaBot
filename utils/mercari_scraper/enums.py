from enum import StrEnum


class ItemSource(StrEnum):
    """Source of a Mercari listing."""

    INDIVIDUAL = "individual"
    SHOPS = "shops"
