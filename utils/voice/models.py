from dataclasses import dataclass

import discord


@dataclass
class QueueEntry:
    """A fully resolved, ready-to-play track."""

    url: str  # Direct audio stream URL (may expire — re-fetch on loop)
    webpage_url: str  # Canonical YouTube URL (stable)
    title: str
    duration: int  # seconds (0 = unknown)
    thumbnail: str
    requester: discord.Member

    def fmt_duration(self) -> str:
        if not self.duration:
            return "?:??"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@dataclass
class UnresolvedEntry:
    """
    A playlist item stored by URL only.
    Full info is fetched lazily right before playback starts.
    This keeps playlist queueing fast and avoids bulk yt-dlp calls.
    """

    raw_url: str
    title: str = "Loading..."
    requester: discord.Member | None = None
