"""
Image helper utilities for downloading and caching card images.
"""

import logging

import aiofiles

from config import CACHE_DIR, SharedResources

logger = logging.getLogger(__name__)


async def get_card_image_path(asset_bundle_name: str, is_trained: bool = False) -> str | None:
    """
    Get path to a card image, downloading and caching if necessary.

    Args:
        asset_bundle_name: The asset bundle name for the card
        is_trained: Whether to get the trained or normal version

    Returns:
        Path to the cached image file, or None if download failed
    """
    suffix = "after_training" if is_trained else "normal"
    filename = f"{asset_bundle_name}_{suffix}.png"
    file_path = CACHE_DIR / filename

    # Return cached file if exists
    if file_path.exists():
        return str(file_path)

    # Build URL and download
    url_type = "card_after_training" if is_trained else "card_normal"
    url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_bundle_name}/{url_type}.png"

    try:
        session = await SharedResources.get_session()
        async with session.get(url) as resp:
            if resp.status == 200:
                async with aiofiles.open(file_path, mode="wb") as f:
                    await f.write(await resp.read())
                return str(file_path)
            else:
                logger.warning(f"Failed to download {url}: HTTP {resp.status}")
                return None
    except Exception as e:
        logger.error(f"Error downloading {asset_bundle_name}: {e}")
        return None
