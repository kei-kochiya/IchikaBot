"""
Image helper utilities for downloading and caching card images.
"""

import asyncio
import contextlib
import logging
import os
from pathlib import Path

import aiofiles

from config import CACHE_DIR, SharedResources

logger = logging.getLogger(__name__)

# Downloads currently in flight, keyed by destination path. Concurrent requests for the same
# image (duplicate cards in a 10-pull, two users, ...) share a single HTTP request.
_inflight: dict[str, asyncio.Task] = {}

# URLs the CDN has answered 404 for. Remembered so that e.g. pre-trained cards (which only
# have trained art) don't pay for a guaranteed-404 round trip on every request.
# Bounded so it can never grow without limit.
_not_found: set[str] = set()
_NOT_FOUND_LIMIT = 4096


async def _fetch(url: str, dest: Path) -> str | None:
    """Download *url* to *dest* atomically. Returns the path, or None if unavailable."""
    if url in _not_found:
        return None

    # Write to a side file first: readers check dest.exists(), and must never see a
    # half-written image.
    tmp = dest.with_name(dest.name + ".part")
    try:
        session = await SharedResources.get_session()
        async with session.get(url) as resp:
            if resp.status == 200:
                async with aiofiles.open(tmp, mode="wb") as f:
                    await f.write(await resp.read())
                os.replace(tmp, dest)
                return str(dest)
            if resp.status == 404:
                if len(_not_found) >= _NOT_FOUND_LIMIT:
                    _not_found.clear()
                _not_found.add(url)
            else:
                logger.warning("Failed to download %s: HTTP %s", url, resp.status)
    except Exception as e:
        logger.error("Error downloading %s: %s", url, e)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
    return None


async def _cached_download(url: str, dest: Path) -> str | None:
    """Return the cached file at *dest*, downloading it from *url* first if needed."""
    if dest.exists():
        return str(dest)

    key = str(dest)
    task = _inflight.get(key)
    if task is None or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.ensure_future(_fetch(url, dest))
        _inflight[key] = task
        task.add_done_callback(
            lambda t: _inflight.pop(key, None) if _inflight.get(key) is t else None
        )
    # shield: one caller timing out/cancelling must not abort the download for the others
    return await asyncio.shield(task)


async def get_card_image_path(asset_bundle_name: str, is_trained: bool = False) -> str | None:
    """Get path to a card image, downloading and caching if necessary.

    If the requested version (normal or trained) returns 404 on CDN,
    automatically falls back to the opposite version (e.g. for pre-trained cards
    which only have card_after_training, or cards without trained art).
    """

    async def _try_download(trained: bool) -> str | None:
        sfx = "after_training" if trained else "normal"
        url_t = "card_after_training" if trained else "card_normal"
        target_url = f"https://storage.sekai.best/sekai-jp-assets/character/member/{asset_bundle_name}/{url_t}.png"
        return await _cached_download(target_url, CACHE_DIR / f"{asset_bundle_name}_{sfx}.png")

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
    url = f"https://storage.sekai.best/sekai-jp-assets/character/character_trim/chr_trim_{char_id}.webp"
    return await _cached_download(url, CACHE_DIR / f"chr_trim_{char_id}.webp")
