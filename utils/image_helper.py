"""
Image helper utilities for downloading and caching card images.
"""
import os
import logging
import aiofiles
from pathlib import Path
from config import CACHE_DIR, MAX_CACHE_SIZE_MB, CACHE_CLEANUP_THRESHOLD, SharedResources

logger = logging.getLogger(__name__)


def get_cache_size_mb() -> float:
    """Calculate current cache size in MB."""
    total_size = 0
    for file in CACHE_DIR.glob('*.png'):
        try:
            total_size += file.stat().st_size
        except OSError:
            pass
    return total_size / (1024 * 1024)


def cleanup_old_cache_files():
    """Remove oldest files when cache exceeds threshold."""
    current_size = get_cache_size_mb()
    threshold = MAX_CACHE_SIZE_MB * CACHE_CLEANUP_THRESHOLD
    
    if current_size < threshold:
        return
    
    logger.info(f"Cache size {current_size:.1f}MB exceeds threshold. Cleaning up...")
    
    # Get all cache files sorted by modification time (oldest first)
    cache_files = list(CACHE_DIR.glob('*.png'))
    cache_files.sort(key=lambda f: f.stat().st_mtime)
    
    # Remove oldest files until we're under 70% capacity
    target_size = MAX_CACHE_SIZE_MB * 0.7
    removed_count = 0
    
    for file in cache_files:
        if get_cache_size_mb() < target_size:
            break
        try:
            file.unlink()
            removed_count += 1
        except OSError as e:
            logger.warning(f"Failed to remove cache file {file}: {e}")
    
    logger.info(f"Removed {removed_count} old cache files.")


async def get_card_image_path(asset_bundle_name: str, is_trained: bool = False) -> str | None:
    """
    Get path to a card image, downloading and caching if necessary.
    
    Args:
        asset_bundle_name: The asset bundle name for the card
        is_trained: Whether to get the trained or normal version
        
    Returns:
        Path to the cached image file, or None if download failed
    """
    suffix = 'after_training' if is_trained else 'normal'
    filename = f"{asset_bundle_name}_{suffix}.png"
    file_path = CACHE_DIR / filename

    # Return cached file if exists
    if file_path.exists():
        return str(file_path)

    # Check cache size before downloading
    cleanup_old_cache_files()

    # Build URL and download
    url_type = 'card_after_training' if is_trained else 'card_normal'
    url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_bundle_name}/{url_type}.png"

    try:
        session = await SharedResources.get_session()
        async with session.get(url) as resp:
            if resp.status == 200:
                async with aiofiles.open(file_path, mode='wb') as f:
                    await f.write(await resp.read())
                return str(file_path)
            else:
                logger.warning(f"Failed to download {url}: HTTP {resp.status}")
                return None
    except Exception as e:
        logger.error(f"Error downloading {asset_bundle_name}: {e}")
        return None