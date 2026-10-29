"""
Centralized Auto-updater Utility
Handles fetching and updating JSON data files from remote sources.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import aiofiles
import aiohttp

from config import UPDATER_STATE_FILE, SharedResources
from utils.core.jsonstream import count_json_array

logger = logging.getLogger(__name__)

# The shared session has a 30s total timeout, far too short for the multi-megabyte card files.
_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=300, connect=15, sock_read=60)
_DOWNLOAD_CHUNK = 1 << 18  # 256 KiB


@dataclass
class DataSource:
    """Configuration for a data source to be auto-updated."""

    name: str
    url: str
    local_path: Path
    transform: Callable[[list | dict], Any] | None = None  # Optional data transform


def _validate_json_file(path: Path) -> int:
    """
    Validate that *path* holds well-formed JSON and return its item count.

    Top-level arrays (every registered source) are validated by streaming, so the
    parse tree is never held in memory. Anything else falls back to a full parse.
    """
    with open(path, "rb") as f:
        head = f.read(4096).lstrip()
    if head.startswith(b"["):
        return count_json_array(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return len(data) if isinstance(data, list | dict) else 1


class AutoUpdater:
    """
    Centralized auto-updater for fetching and updating JSON data files.

    Memory/bandwidth features:
    - Conditional requests (ETag / If-None-Match): an unchanged file costs one tiny
      304 response instead of a multi-megabyte download and parse.
    - The body is streamed to disk and validated by streaming, so peak memory stays
      at a few buffers instead of several full copies of the parsed data.
    - Changes are detected by content hash, so edits that do not change the item count
      are picked up as well.
    - Heavy work (validation, hashing, replace) runs off the event loop.

    Security features:
    - Only fetches from whitelisted URLs (configured in config.py)
    - Validates response is valid JSON before replacing the local file
    - Atomic writes to prevent corruption
    - Rejects empty datasets
    - Only one update run at a time
    """

    # Whitelisted URL prefixes for security
    ALLOWED_URL_PREFIXES: ClassVar[list[str]] = [
        "https://raw.githubusercontent.com/Sekai-World/",
    ]

    def __init__(self, state_file: Path | None = None):
        self.sources: dict[str, DataSource] = {}
        self._last_update_status: dict[str, bool] = {}
        self._state_file = state_file or UPDATER_STATE_FILE
        # {source_name: {"etag": str | None, "sha256": str, "count": int}}
        self._state: dict[str, dict[str, Any]] | None = None
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        """True while an update run is in progress."""
        return self._lock.locked()

    def register(self, source: DataSource) -> bool:
        """
        Register a data source for auto-updating.

        Returns False if URL is not in whitelist.
        """
        # Security: Validate URL is in whitelist
        if not any(source.url.startswith(prefix) for prefix in self.ALLOWED_URL_PREFIXES):
            logger.warning(
                "AutoUpdater: Rejected source '%s' - URL not in whitelist: %s",
                source.name,
                source.url,
            )
            return False

        self.sources[source.name] = source
        logger.debug("AutoUpdater: Registered source '%s'", source.name)
        return True

    # ── Persistent per-source state (ETag / content hash / item count) ──────

    def _get_state(self) -> dict[str, dict[str, Any]]:
        if self._state is None:
            try:
                raw = json.loads(self._state_file.read_text(encoding="utf-8"))
                self._state = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self._state = {}
        return self._state

    def _save_state(self) -> None:
        tmp = self._state_file.with_name(self._state_file.name + ".part")
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._get_state()), encoding="utf-8")
            tmp.replace(self._state_file)
        except OSError as e:
            logger.warning("AutoUpdater: Failed to persist update state: %s", e)

    # ── Public API ──────────────────────────────────────────────────────────

    async def check_and_update(self, source_name: str) -> tuple[bool, str]:
        """
        Check for updates and download if available.

        Returns:
            (success: bool, message: str)
        """
        async with self._lock:
            return await self._check_and_update(source_name)

    async def check_all(self) -> dict[str, tuple[bool, str]]:
        """Check and update all registered sources."""
        async with self._lock:
            results = {}
            for name in self.sources:
                results[name] = await self._check_and_update(name)
            return results

    # ── Implementation ──────────────────────────────────────────────────────

    def _finish(self, name: str, ok: bool, msg: str) -> tuple[bool, str]:
        self._last_update_status[name] = ok
        return ok, msg

    async def _check_and_update(self, source_name: str) -> tuple[bool, str]:
        if source_name not in self.sources:
            return False, f"Unknown source: {source_name}"

        source = self.sources[source_name]
        state = self._get_state().get(source_name, {})
        part_path = source.local_path.with_name(source.local_path.name + ".part")

        headers = {}
        if state.get("etag") and source.local_path.exists():
            headers["If-None-Match"] = state["etag"]

        try:
            session = await SharedResources.get_session()
            async with session.get(
                source.url, headers=headers, timeout=_DOWNLOAD_TIMEOUT
            ) as response:
                if response.status == 304:
                    logger.debug("AutoUpdater[%s]: Not modified", source.name)
                    return self._finish(source_name, True, "Already up to date")

                if response.status != 200:
                    msg = f"HTTP {response.status}"
                    logger.warning("AutoUpdater[%s]: Failed to fetch - %s", source.name, msg)
                    return self._finish(source_name, False, msg)

                # Validate content type is JSON-like (GitHub raw returns text/plain)
                content_type = response.headers.get("Content-Type", "")
                if "json" not in content_type and "text/plain" not in content_type:
                    msg = f"Unexpected content type: {content_type}"
                    logger.warning("AutoUpdater[%s]: %s", source.name, msg)
                    return self._finish(source_name, False, msg)

                source.local_path.parent.mkdir(parents=True, exist_ok=True)
                digest = await self._download(response, part_path)
                etag = response.headers.get("ETag")

            # Identical content (e.g. the server did not honour If-None-Match)
            if state.get("sha256") == digest and source.local_path.exists():
                self._get_state()[source_name] = {**state, "etag": etag or state.get("etag")}
                await asyncio.to_thread(self._save_state)
                logger.debug("AutoUpdater[%s]: Data is up to date", source.name)
                return self._finish(source_name, True, "Already up to date")

            try:
                old_count, new_count = await asyncio.to_thread(
                    self._install, source, part_path, state.get("count")
                )
            except ValueError as e:
                msg = f"Invalid JSON: {e}"
                logger.error("AutoUpdater[%s]: %s", source.name, msg)
                return self._finish(source_name, False, msg)

            self._get_state()[source_name] = {"etag": etag, "sha256": digest, "count": new_count}
            await asyncio.to_thread(self._save_state)

            msg = f"Updated: {old_count} -> {new_count} items"
            logger.info("AutoUpdater[%s]: %s", source.name, msg)
            return self._finish(source_name, True, msg)

        except Exception as e:
            msg = f"Error: {e}"
            logger.error("AutoUpdater[%s]: %s", source.name, msg)
            return self._finish(source_name, False, msg)
        finally:
            with contextlib.suppress(OSError):
                part_path.unlink(missing_ok=True)

    @staticmethod
    async def _download(response: aiohttp.ClientResponse, dest: Path) -> str:
        """Stream the response body to *dest* and return its SHA-256 hex digest."""
        digest = hashlib.sha256()
        async with aiofiles.open(dest, "wb") as f:
            async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK):
                digest.update(chunk)
                await f.write(chunk)
        return digest.hexdigest()

    def _install(
        self, source: DataSource, part_path: Path, known_old_count: int | None
    ) -> tuple[int | str, int]:
        """
        Validate the downloaded file and atomically move it into place.
        Runs in a worker thread. Returns (old_count, new_count).
        Raises ValueError if the download is not valid / usable JSON.
        """
        if source.transform is not None:
            # Transforms need the whole structure in memory; none of the built-in sources use one.
            with open(part_path, encoding="utf-8") as f:
                new_data = source.transform(json.load(f))
            if not new_data:
                raise ValueError("empty dataset")
            current = None
            if source.local_path.exists():
                with open(source.local_path, encoding="utf-8") as f:
                    current = json.load(f)
            if not self._needs_update(current, new_data):
                new_count = len(new_data) if isinstance(new_data, list | dict) else 1
                return new_count, new_count
            with open(part_path, "w", encoding="utf-8") as f:
                json.dump(new_data, f, ensure_ascii=False)
            new_count = len(new_data) if isinstance(new_data, list | dict) else 1
            old_count = len(current) if isinstance(current, list | dict) else 0
        else:
            new_count = _validate_json_file(part_path)
            if new_count == 0:
                raise ValueError("empty dataset")
            old_count = known_old_count
            if old_count is None:
                try:
                    old_count = _validate_json_file(source.local_path)
                except (OSError, ValueError):
                    old_count = 0

        os.replace(part_path, source.local_path)
        return old_count, new_count

    def _needs_update(self, current: Any, new: Any) -> bool:
        """Determine if data needs updating."""
        if current is None:
            return True

        # For lists, compare lengths
        if isinstance(new, list):
            if not isinstance(current, list):
                return True
            return len(new) != len(current)

        # For dicts, compare key counts
        if isinstance(new, dict):
            if not isinstance(current, dict):
                return True
            return len(new) != len(current)

        return current != new


# Global auto-updater instance
auto_updater = AutoUpdater()


async def register_all_sources():
    """Register all known data sources for auto-updating (both JP and EN)."""
    from config import (
        CARD_DATA_URL_EN,
        CARD_DATA_URL_JP,
        # EN Data
        CARDS_FILE_EN,
        # JP Data
        CARDS_FILE_JP,
        EVENTS_DATA_URL_EN,
        EVENTS_DATA_URL_JP,
        EVENTS_FILE_EN,
        EVENTS_FILE_JP,
        MUSIC_DIFFICULTIES_FILE_EN,
        MUSIC_DIFFICULTIES_FILE_JP,
        MUSIC_DIFFICULTIES_URL_EN,
        MUSIC_DIFFICULTIES_URL_JP,
        MUSICS_DATA_URL_EN,
        MUSICS_DATA_URL_JP,
        MUSICS_FILE_EN,
        MUSICS_FILE_JP,
    )

    sources = [
        # JP Sources
        DataSource("cards_jp", CARD_DATA_URL_JP, CARDS_FILE_JP),
        DataSource("musics_jp", MUSICS_DATA_URL_JP, MUSICS_FILE_JP),
        DataSource("music_difficulties_jp", MUSIC_DIFFICULTIES_URL_JP, MUSIC_DIFFICULTIES_FILE_JP),
        DataSource("events_jp", EVENTS_DATA_URL_JP, EVENTS_FILE_JP),
        # EN Sources
        DataSource("cards_en", CARD_DATA_URL_EN, CARDS_FILE_EN),
        DataSource("musics_en", MUSICS_DATA_URL_EN, MUSICS_FILE_EN),
        DataSource("music_difficulties_en", MUSIC_DIFFICULTIES_URL_EN, MUSIC_DIFFICULTIES_FILE_EN),
        DataSource("events_en", EVENTS_DATA_URL_EN, EVENTS_FILE_EN),
    ]

    for source in sources:
        auto_updater.register(source)

    logger.info("AutoUpdater: Registered %d data sources (JP and EN)", len(sources))


async def run_all_updates() -> dict[str, tuple[bool, str]]:
    """
    Run updates for all registered sources.

    This can be called from a scheduled task or manually.
    """
    return await auto_updater.check_all()
