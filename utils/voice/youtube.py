import os
import random
import asyncio
import logging
from typing import Optional
import discord
import yt_dlp
from utils.voice.models import QueueEntry, UnresolvedEntry

logger = logging.getLogger(__name__)

MAX_RETRIES        = 5
BASE_RETRY_DELAY   = 2.0

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Mode": "navigate",
}

YDL_OPTS_SINGLE: dict = {
    "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "noplaylist": True,
    "ignoreerrors": False,
    "sleep_interval": 1,
    "max_sleep_interval": 4,
    "retries": 5,
    "fragment_retries": 5,
    "http_headers": _BROWSER_HEADERS,
}

YDL_OPTS_FLAT: dict = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "ignoreerrors": True,
    "sleep_interval": 1,
    "http_headers": _BROWSER_HEADERS,
}

async def resolve_track(url: str, requester: Optional[discord.Member] = None) -> Optional[QueueEntry]:
    """Fully resolve a YouTube URL to a playable QueueEntry."""
    opts = dict(YDL_OPTS_SINGLE)
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"

    loop = asyncio.get_event_loop()

    for attempt in range(MAX_RETRIES):
        try:
            def _extract():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)

            info = await loop.run_in_executor(None, _extract)
            if info is None:
                return None

            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                if not entries:
                    return None
                info = entries[0]

            audio_url = info.get("url") or info.get("webpage_url", url)
            return QueueEntry(
                url=audio_url,
                webpage_url=info.get("webpage_url", url),
                title=info.get("title", "Unknown"),
                duration=info.get("duration") or 0,
                thumbnail=info.get("thumbnail", ""),
                requester=requester,
            )
        except yt_dlp.utils.DownloadError as exc:
            err_str = str(exc).lower()
            if "429" in err_str or "rate limit" in err_str:
                delay = BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0.5, 2.0)
                logger.warning("Rate-limited by YouTube. Retry %d/%d in %.1fs", attempt + 1, MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            elif attempt < MAX_RETRIES - 1:
                delay = BASE_RETRY_DELAY * (1.5 ** attempt)
                logger.warning("yt-dlp error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, exc)
                await asyncio.sleep(delay)
            else:
                logger.error("Failed to resolve %s after %d attempts: %s", url, MAX_RETRIES, exc)
                return None
        except Exception as exc:
            logger.error("Unexpected error resolving %s: %s", url, exc)
            return None
    return None

async def fetch_playlist_flat(url: str, requester: Optional[discord.Member]) -> list[UnresolvedEntry]:
    """Extract only the video URLs from a playlist (no full metadata)."""
    opts = dict(YDL_OPTS_FLAT)
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"

    loop = asyncio.get_event_loop()
    try:
        def _extract():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = await loop.run_in_executor(None, _extract)
        if not info or "entries" not in info:
            return []

        result = []
        for item in info["entries"]:
            if item is None:
                continue
            vid_url = (
                item.get("url")
                or item.get("webpage_url")
                or (f"https://www.youtube.com/watch?v={item['id']}" if item.get("id") else None)
            )
            if not vid_url:
                continue
            if not vid_url.startswith("http"):
                vid_url = f"https://www.youtube.com/watch?v={vid_url}"
            result.append(UnresolvedEntry(
                raw_url=vid_url,
                title=item.get("title") or "Unknown",
                requester=requester,
            ))
        return result
    except Exception as exc:
        logger.error("Playlist flat-extract failed: %s", exc)
        return []
