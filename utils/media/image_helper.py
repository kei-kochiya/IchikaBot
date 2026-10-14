"""
Image helper utilities for downloading and caching card images.
"""

import logging

import aiofiles

from config import CACHE_DIR, SharedResources

logger = logging.getLogger(__name__)


async def get_card_image_path(asset_bundle_name: str, is_trained: bool = False) -> str | None:
    """Get path to a card image, downloading and caching if necessary.

    If the requested version (normal or trained) returns 404 on CDN,
    automatically falls back to the opposite version (e.g. for pre-trained cards
    which only have card_after_training, or cards without trained art).
    """

    # Helper to attempt download of a specific version
    async def _try_download(trained: bool) -> str | None:
        sfx = "after_training" if trained else "normal"
        fname = f"{asset_bundle_name}_{sfx}.png"
        fpath = CACHE_DIR / fname
        if fpath.exists():
            return str(fpath)

        url_t = "card_after_training" if trained else "card_normal"
        target_url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_bundle_name}/{url_t}.png"
        try:
            session = await SharedResources.get_session()
            async with session.get(target_url) as resp:
                if resp.status == 200:
                    async with aiofiles.open(fpath, mode="wb") as f:
                        await f.write(await resp.read())
                    return str(fpath)
                elif resp.status != 404:
                    logger.warning("Failed to download %s: HTTP %s", target_url, resp.status)
        except Exception as e:
            logger.error("Error downloading %s: %s", target_url, e)
        return None

    # Try requested version first
    result = await _try_download(is_trained)
    if result:
        return result

    # Fallback to alternate version if requested was 404
    fallback_result = await _try_download(not is_trained)
    if fallback_result:
        logger.info(
            "get_card_image_path: Fallback to %s for %s",
            "after_training" if not is_trained else "normal",
            asset_bundle_name,
        )
        return fallback_result

    return None


async def get_character_trim_path(char_id: int | str) -> str | None:
    """Get path to a character trim image, downloading and caching if necessary."""
    filename = f"chr_trim_{char_id}.webp"
    file_path = CACHE_DIR / filename

    if file_path.exists():
        return str(file_path)

    url = f"https://storage.sekai.best/sekai-jp-assets/character/character_trim/chr_trim_{char_id}.webp"
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
        logger.error(f"Error downloading chr_trim_{char_id}: {e}")
        return None
