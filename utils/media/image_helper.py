"""
Image helper utilities for downloading and caching card images.
"""

import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path

import aiofiles

from config import CACHE_DIR, SharedResources

logger = logging.getLogger(__name__)

# Downloads currently in flight, keyed by destination path. Concurrent requests for the same
# image (duplicate cards in a 10-pull, two users, ...) share a single HTTP request.
_inflight: dict[str, asyncio.Task] = {}

# URLs the CDN has answered 404 for, with when. Remembered so that e.g. pre-trained cards
# (which only have trained art) don't pay for a guaranteed-404 round trip on every request,
# but only for a while: art for a brand-new card often reaches the CDN hours after the card
# appears in master data. Bounded so it can never grow without limit.
_not_found: dict[str, float] = {}
_NOT_FOUND_LIMIT = 4096
_NOT_FOUND_TTL = 3600.0  # seconds


def _is_known_missing(url: str) -> bool:
    seen = _not_found.get(url)
    if seen is None:
        return False
    if time.monotonic() - seen < _NOT_FOUND_TTL:
        return True
    _not_found.pop(url, None)
    return False


async def _fetch(url: str, dest: Path) -> str | None:
    """Download *url* to *dest* atomically. Returns the path, or None if unavailable."""
    if _is_known_missing(url):
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
                _not_found[url] = time.monotonic()
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
    # An empty file (left by versions before writes were atomic) is not a valid image:
    # treat it as missing instead of serving a broken image forever.
    with contextlib.suppress(OSError):
        if dest.stat().st_size > 0:
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


CARD_ART_URL = "https://storage.sekai.best/sekai-jp-assets/character/member/{asset}/{kind}.{ext}"


def _png_to_webp(png: Path, dest: Path) -> str | None:
    """Convert a downloaded PNG into the WebP the cache serves, then drop the PNG."""
    from PIL import Image  # only needed on this rare path

    tmp = dest.with_name(dest.name + ".part")
    try:
        with Image.open(png) as im:
            im.convert("RGB").save(tmp, "WEBP", quality=90, method=4)
        os.replace(tmp, dest)
        png.unlink(missing_ok=True)
        return str(dest)
    except OSError as e:
        logger.warning("Could not convert %s to WebP: %s", png, e)
        return None
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


async def _card_art(asset_bundle_name: str, trained: bool) -> tuple[str | None, bool]:
    """(path, missing): missing is True only if the CDN answered 404 for every format."""
    sfx = "after_training" if trained else "normal"
    kind = "card_after_training" if trained else "card_normal"
    dest = CACHE_DIR / f"{asset_bundle_name}_{sfx}.webp"
    webp_url = CARD_ART_URL.format(asset=asset_bundle_name, kind=kind, ext="webp")
    path = await _cached_download(webp_url, dest)
    if path or not _is_known_missing(webp_url):
        return path, False  # got it, or a network error: don't pile on more requests

    # No WebP (yet) for this card: take the PNG and convert it, so the cache stays WebP
    png_url = CARD_ART_URL.format(asset=asset_bundle_name, kind=kind, ext="png")
    png = await _cached_download(png_url, CACHE_DIR / f"{asset_bundle_name}_{sfx}.png")
    if png:
        return await asyncio.to_thread(_png_to_webp, Path(png), dest), False
    return None, _is_known_missing(png_url)


async def get_card_image_path(asset_bundle_name: str, is_trained: bool = False) -> str | None:
    """Get the path of a card's art (a .webp file), downloading and caching it if needed.

    The CDN's WebP is ~20x smaller than its PNG (~0.2 MB vs ~4 MB) and faster to decode,
    so downloads, the disk cache and every upload of the art to Discord shrink with it.

    If the requested version (normal or trained) is missing on the CDN (404), falls back
    to the other one (pre-trained cards only have trained art). A network error is not a
    404: then None is returned at once instead of waiting on more downloads.
    """
    path, missing = await _card_art(asset_bundle_name, is_trained)
    if path or not missing:
        return path

    path, _ = await _card_art(asset_bundle_name, not is_trained)
    if path:
        logger.info(
            "get_card_image_path: Fallback to %s for %s",
            "after_training" if not is_trained else "normal",
            asset_bundle_name,
        )
    return path


async def get_ui_asset_path(name: str, url: str) -> str | None:
    """Get a static game-UI image (gacha background, rarity star, ...), cached in CACHE_DIR/ui."""
    ui_dir = CACHE_DIR / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    return await _cached_download(url, ui_dir / name)


def cached_ui_asset_path(name: str) -> str | None:
    """The path of a game-UI image if it is already on disk (never downloads)."""
    path = CACHE_DIR / "ui" / name
    with contextlib.suppress(OSError):
        if path.stat().st_size > 0:
            return str(path)
    return None


MEMBER_CUTOUT_URL = (
    "https://storage.sekai.best/sekai-jp-assets/character/member_cutout/{asset}/{variant}.webp"
)


async def get_member_cutout_path(asset_bundle_name: str, trained: bool) -> str | None:
    """Get a card's member_cutout close-up (exists for every card, ~50 KB), cached in
    CACHE_DIR/cutouts. Used to find the character in the card art for easy /guess."""
    variant = "after_training" if trained else "normal"
    folder = CACHE_DIR / "cutouts"
    folder.mkdir(parents=True, exist_ok=True)
    url = MEMBER_CUTOUT_URL.format(asset=asset_bundle_name, variant=variant)
    return await _cached_download(url, folder / f"{asset_bundle_name}_{variant}.webp")


async def get_character_trim_path(char_id: int | str) -> str | None:
    """Get path to a character trim image, downloading and caching if necessary."""
    url = f"https://storage.sekai.best/sekai-jp-assets/character/character_trim/chr_trim_{char_id}.webp"
    return await _cached_download(url, CACHE_DIR / f"chr_trim_{char_id}.webp")
