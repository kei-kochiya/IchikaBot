"""
Streaming Cog - YouTube audio streaming for IchikaBot.

Features:
  - Single videos and playlists (lazy-loaded, no upfront rate-limit risk)
  - Slash commands (/stream group) + prefix aliases (!play, !skip, etc.)
  - Queue with shuffle, remove, loop modes (off/track/queue), volume
  - Auto-leave on inactivity or when left alone in voice
  - Browser header spoofing + optional impersonate flag for yt-dlp
  - Exponential backoff retry on rate limits/errors

System requirement: FFmpeg must be installed and in PATH.
"""

import asyncio
import logging
import os
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

INACTIVITY_TIMEOUT = 300   # seconds before auto-leave (no tracks)
ALONE_TIMEOUT      = 120   # seconds before auto-leave (bot alone in VC)
MAX_QUEUE_SIZE     = 200
QUEUE_PAGE_SIZE    = 10
MAX_RETRIES        = 5
BASE_RETRY_DELAY   = 2.0   # seconds; doubles each attempt

# FFmpeg options for robust reconnection on network hiccups
FFMPEG_BEFORE = (
    "-reconnect 1 "
    "-reconnect_streamed 1 "
    "-reconnect_delay_max 5 "
    "-reconnect_on_network_error 1"
)
FFMPEG_OPTIONS = {
    "before_options": FFMPEG_BEFORE,
    "options": "-vn",
}

# Browser-style headers to avoid YouTube bot detection
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

# yt-dlp options for resolving a single playable URL
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
    # Uncomment to use full browser impersonation if yt-dlp >= 2023.11:
    # "impersonate": "chrome",
}

# yt-dlp options for flat playlist extraction (URLs only — very fast, low rate-limit risk)
YDL_OPTS_FLAT: dict = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "ignoreerrors": True,
    "sleep_interval": 1,
    "http_headers": _BROWSER_HEADERS,
}


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class QueueEntry:
    """A fully resolved, ready-to-play track."""
    url:         str            # Direct audio stream URL (may expire — re-fetch on loop)
    webpage_url: str            # Canonical YouTube URL (stable)
    title:       str
    duration:    int            # seconds (0 = unknown)
    thumbnail:   str
    requester:   discord.Member

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
    raw_url:   str
    title:     str = "Loading..."
    requester: Optional[discord.Member] = None


# ── Per-guild player state ─────────────────────────────────────────────────────

class GuildPlayer:
    LOOP_OFF   = 0
    LOOP_TRACK = 1
    LOOP_QUEUE = 2
    LOOP_LABEL = {0: "Off", 1: "🔂 Track", 2: "🔁 Queue"}

    def __init__(self):
        self.queue:           deque  = deque()
        self.current:         Optional[QueueEntry]       = None
        self.vc:              Optional[discord.VoiceClient] = None
        self.text_channel:    Optional[discord.abc.Messageable] = None
        self.loop:            int   = self.LOOP_OFF
        self.volume:          float = 1.0          # 0.0–2.0
        self.play_task:       Optional[asyncio.Task] = None
        self.inactivity_task: Optional[asyncio.Task] = None
        self._skip_flag:      bool = False
        self._stop_flag:      bool = False

    @property
    def is_active(self) -> bool:
        return self.vc is not None and (
            self.vc.is_playing() or self.vc.is_paused()
        )

    def cancel_tasks(self):
        for t in (self.play_task, self.inactivity_task):
            if t and not t.done():
                t.cancel()

    def restart_inactivity(self, coro):
        if self.inactivity_task and not self.inactivity_task.done():
            self.inactivity_task.cancel()
        self.inactivity_task = asyncio.create_task(coro)


# ── Main Cog ───────────────────────────────────────────────────────────────────

class StreamingCog(commands.Cog, name="Streaming"):
    """YouTube audio streaming with queue management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._players: dict[int, GuildPlayer] = {}  # guild_id → GuildPlayer

    # ── Player lifecycle ───────────────────────────────────────────────────────

    def _get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer()
        return self._players[guild_id]

    async def _destroy_player(self, guild_id: int):
        player = self._players.pop(guild_id, None)
        if not player:
            return
        player._stop_flag = True
        player._skip_flag = True
        player.cancel_tasks()
        if player.vc:
            if player.vc.is_playing() or player.vc.is_paused():
                player.vc.stop()
            try:
                await player.vc.disconnect()
            except Exception:
                pass

    # ── yt-dlp helpers ─────────────────────────────────────────────────────────

    async def _resolve_track(
        self,
        url: str,
        requester: Optional[discord.Member] = None,
    ) -> Optional[QueueEntry]:
        """
        Fully resolve a YouTube URL to a playable QueueEntry.
        Retries up to MAX_RETRIES times with exponential backoff.
        Runs yt-dlp in a thread pool to avoid blocking the event loop.
        """
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

                # Search results wrap entries
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
                    logger.warning(
                        "Rate-limited by YouTube. Retry %d/%d in %.1fs", attempt + 1, MAX_RETRIES, delay
                    )
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

    async def _fetch_playlist_flat(
        self, url: str, requester: Optional[discord.Member]
    ) -> list[UnresolvedEntry]:
        """
        Extract only the video URLs from a playlist (no full metadata).
        Very fast. Each entry is an UnresolvedEntry resolved lazily at play time.
        """
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

    # ── Playback engine ────────────────────────────────────────────────────────

    async def _play_loop(self, guild_id: int):
        """
        Background task that drives playback for one guild.
        Runs until queue is empty, stop is called, or an unrecoverable error occurs.
        """
        player = self._get_player(guild_id)

        while not player._stop_flag:
            entry: Optional[QueueEntry] = None

            # ── Determine next entry ────────────────────────────────────────
            if player.loop == GuildPlayer.LOOP_TRACK and player.current:
                # Re-resolve because stream URLs expire
                fetched = await self._resolve_track(
                    player.current.webpage_url, player.current.requester
                )
                entry = fetched  # None → fall through to queue

            if entry is None:
                if not player.queue:
                    # Queue exhausted
                    player.current = None
                    await self._safe_send(player, "Đã hết queue!")
                    player.restart_inactivity(self._inactivity_leave(guild_id, INACTIVITY_TIMEOUT))
                    return

                raw = player.queue.popleft()

                # Queue loop: re-append at end
                if player.loop == GuildPlayer.LOOP_QUEUE:
                    player.queue.append(raw)

                if isinstance(raw, UnresolvedEntry):
                    await self._safe_send(player, f"Đang tải: **{raw.title}**...", delete_after=8)
                    entry = await self._resolve_track(raw.raw_url, raw.requester)
                    if entry is None:
                        await self._safe_send(
                            player, f"Không tải được: **{raw.title}** — bỏ qua.", delete_after=10
                        )
                        continue
                else:
                    entry = raw

            # ── Play ────────────────────────────────────────────────────────
            player.current = entry
            player._skip_flag = False

            try:
                source = discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(entry.url, **FFMPEG_OPTIONS),
                    volume=player.volume,
                )

                done = asyncio.Event()

                def _after(err):
                    if err:
                        logger.error("Playback error in guild %d: %s", guild_id, err)
                    asyncio.run_coroutine_threadsafe(
                        self._signal(done), self.bot.loop
                    )

                if not player.vc or not player.vc.is_connected():
                    logger.warning("Guild %d: VC disconnected before playback.", guild_id)
                    return

                player.vc.play(source, after=_after)
                await self._safe_send(player, embed=self._np_embed(entry, player))

                # Wait until track ends or skip/stop is signalled
                while not done.is_set():
                    if player._skip_flag or player._stop_flag:
                        if player.vc and player.vc.is_playing():
                            player.vc.stop()
                        break
                    await asyncio.sleep(0.4)

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Error playing %s: %s", entry.title, exc)
                await self._safe_send(
                    player, f"Lỗi phát: **{entry.title}** — bỏ qua.", delete_after=10
                )

        player.current = None

    @staticmethod
    async def _signal(event: asyncio.Event):
        event.set()

    async def _inactivity_leave(self, guild_id: int, timeout: int):
        await asyncio.sleep(timeout)
        player = self._players.get(guild_id)
        if player and player.vc and not player.is_active:
            ch = player.text_channel
            await self._destroy_player(guild_id)
            if ch:
                try:
                    await ch.send(
                        f"Rời kênh vì không hoạt động trong **{timeout // 60} phút**."
                    )
                except Exception:
                    pass

    # ── Voice helpers ──────────────────────────────────────────────────────────

    async def _join_voice(self, ctx_or_ix) -> tuple[bool, Optional[GuildPlayer]]:
        """
        Ensure the bot is in the user's voice channel.
        Returns (success, player).  Sends an error message on failure.
        """
        is_ix = isinstance(ctx_or_ix, discord.Interaction)
        author = ctx_or_ix.user if is_ix else ctx_or_ix.author
        guild  = ctx_or_ix.guild

        async def err(msg: str):
            if is_ix:
                try:
                    await ctx_or_ix.followup.send(msg, ephemeral=True)
                except Exception:
                    pass
            else:
                try:
                    await ctx_or_ix.send(msg)
                except Exception:
                    pass

        if not guild:
            await err("Lệnh này chỉ dùng được trong server.")
            return False, None

        if not getattr(author, "voice", None) or not author.voice.channel:
            await err("Bạn cần vào kênh voice trước!")
            return False, None

        player = self._get_player(guild.id)
        vc_channel = author.voice.channel

        if player.vc and player.vc.is_connected():
            if player.vc.channel.id != vc_channel.id:
                await player.vc.move_to(vc_channel)
        else:
            try:
                player.vc = await vc_channel.connect()
            except discord.ClientException as exc:
                await err(f"Không thể vào kênh voice: {exc}")
                return False, None

        player.text_channel = ctx_or_ix.channel
        return True, player

    # ── Shared play handler (slash + prefix) ───────────────────────────────────

    async def _handle_play(self, ctx_or_ix, url: str):
        is_ix = isinstance(ctx_or_ix, discord.Interaction)
        author = ctx_or_ix.user if is_ix else ctx_or_ix.author

        if is_ix:
            await ctx_or_ix.response.defer()

        ok, player = await self._join_voice(ctx_or_ix)
        if not ok:
            return

        guild_id = ctx_or_ix.guild_id if is_ix else ctx_or_ix.guild.id
        player.cancel_tasks()   # clear any pending inactivity timer

        # ── Playlist vs single ──────────────────────────────────────────────
        if "list=" in url or "playlist" in url:
            await self._safe_send(player, "Đang tải playlist...")
            entries = await self._fetch_playlist_flat(url, author)
            if not entries:
                msg = "Không lấy được playlist. Kiểm tra link hoặc thử lại."
                await (ctx_or_ix.followup.send(msg, ephemeral=True) if is_ix else ctx_or_ix.send(msg))
                return
            added = 0
            for e in entries:
                if len(player.queue) >= MAX_QUEUE_SIZE:
                    break
                player.queue.append(e)
                added += 1
            confirm = f"Thêm **{added}** bài từ playlist vào queue."
        else:
            if len(player.queue) >= MAX_QUEUE_SIZE:
                msg = f"Queue đầy! (tối đa {MAX_QUEUE_SIZE} bài)"
                await (ctx_or_ix.followup.send(msg, ephemeral=True) if is_ix else ctx_or_ix.send(msg))
                return
            player.queue.append(UnresolvedEntry(raw_url=url, title=url, requester=author))
            confirm = f"Đã thêm vào queue: `{url}`"

        # ── Start playback ──────────────────────────────────────────────────
        if not player.is_active:
            player._stop_flag = False
            player.play_task = asyncio.create_task(self._play_loop(guild_id))
        else:
            await self._safe_send(player, confirm)

    # ── Shared skip / stop helpers ─────────────────────────────────────────────

    def _do_skip(self, player: GuildPlayer) -> bool:
        if not player.is_active:
            return False
        player._skip_flag = True
        if player.vc and (player.vc.is_playing() or player.vc.is_paused()):
            player.vc.stop()
        return True

    # ── Embeds ────────────────────────────────────────────────────────────────

    def _np_embed(self, entry: QueueEntry, player: GuildPlayer) -> discord.Embed:
        embed = discord.Embed(
            title="🎵 Đang phát",
            description=f"**[{entry.title}]({entry.webpage_url})**",
            color=discord.Color.from_rgb(255, 90, 90),
        )
        if entry.thumbnail:
            embed.set_thumbnail(url=entry.thumbnail)
        embed.add_field(name="Thời lượng",   value=entry.fmt_duration(),                              inline=True)
        embed.add_field(name="Yêu cầu bởi", value=entry.requester.mention if entry.requester else "?", inline=True)
        embed.add_field(name="Loop",          value=GuildPlayer.LOOP_LABEL[player.loop],               inline=True)
        embed.add_field(name="Tiếp theo",    value=f"{len(player.queue)} bài",                        inline=True)
        embed.add_field(name="Âm lượng",     value=f"{int(player.volume * 100)}%",                   inline=True)
        return embed

    def _queue_embed(self, player: GuildPlayer, page: int = 0) -> discord.Embed:
        items      = list(player.queue)
        total      = len(items)
        total_pages = max(1, (total + QUEUE_PAGE_SIZE - 1) // QUEUE_PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        slc  = items[page * QUEUE_PAGE_SIZE:(page + 1) * QUEUE_PAGE_SIZE]

        embed = discord.Embed(
            title=f"Queue — {total} bài",
            color=discord.Color.blurple(),
        )
        if player.current:
            embed.add_field(
                name="🎵 Đang phát",
                value=f"[{player.current.title}]({player.current.webpage_url})",
                inline=False,
            )
        if slc:
            lines = []
            for i, item in enumerate(slc, start=page * QUEUE_PAGE_SIZE + 1):
                title = getattr(item, "title", "?")
                dur   = item.fmt_duration() if isinstance(item, QueueEntry) else "..."
                lines.append(f"`{i}.` {title} `[{dur}]`")
            embed.add_field(name="Tiếp theo", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Tiếp theo", value="*(Queue rỗng)*", inline=False)

        embed.set_footer(
            text=(
                f"Trang {page+1}/{total_pages} | "
                f"Loop: {GuildPlayer.LOOP_LABEL[player.loop]} | "
                f"Vol: {int(player.volume*100)}%"
            )
        )
        return embed

    @staticmethod
    async def _safe_send(player: GuildPlayer, content: str = None, *, embed=None, delete_after=None):
        if not player.text_channel:
            return
        try:
            kwargs = {}
            if content:
                kwargs["content"] = content
            if embed:
                kwargs["embed"] = embed
            if delete_after:
                kwargs["delete_after"] = delete_after
            await player.text_channel.send(**kwargs)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # Slash Commands  (/stream group)
    # ══════════════════════════════════════════════════════════════════════════

    stream = app_commands.Group(
        name="stream",
        description="🎵 Streaming nhạc từ YouTube",
    )

    @stream.command(name="play", description="Phát nhạc từ YouTube (link video hoặc playlist)")
    @app_commands.describe(url="YouTube URL hoặc tên bài hát để tìm kiếm")
    async def slash_play(self, interaction: discord.Interaction, url: str):
        await self._handle_play(interaction, url)

    @stream.command(name="skip", description="Bỏ qua bài đang phát")
    async def slash_skip(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player = self._get_player(interaction.guild_id)
        if self._do_skip(player):
            await interaction.followup.send("⏭️ Đã bỏ qua!", ephemeral=True)
        else:
            await interaction.followup.send("Không có gì đang phát.", ephemeral=True)

    @stream.command(name="stop", description="Dừng phát và rời kênh voice")
    async def slash_stop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self._destroy_player(interaction.guild_id)
        await interaction.followup.send("⏹️ Đã dừng và rời kênh.", ephemeral=True)

    @stream.command(name="pause", description="Tạm dừng nhạc")
    async def slash_pause(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player = self._get_player(interaction.guild_id)
        if player.vc and player.vc.is_playing():
            player.vc.pause()
            await interaction.followup.send("⏸️ Đã tạm dừng.", ephemeral=True)
        else:
            await interaction.followup.send("Không có gì đang phát.", ephemeral=True)

    @stream.command(name="resume", description="Tiếp tục phát nhạc")
    async def slash_resume(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player = self._get_player(interaction.guild_id)
        if player.vc and player.vc.is_paused():
            player.vc.resume()
            await interaction.followup.send("▶️ Tiếp tục phát!", ephemeral=True)
        else:
            await interaction.followup.send("Không có gì đang tạm dừng.", ephemeral=True)

    @stream.command(name="nowplaying", description="Xem thông tin bài đang phát")
    async def slash_np(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player = self._get_player(interaction.guild_id)
        if not player.current:
            await interaction.followup.send("Không có gì đang phát.", ephemeral=True)
            return
        await interaction.followup.send(embed=self._np_embed(player.current, player))

    @stream.command(name="queue", description="Xem danh sách")
    @app_commands.describe(page="Trang")
    async def slash_queue(self, interaction: discord.Interaction, page: int = 1):
        await interaction.response.defer()
        player = self._get_player(interaction.guild_id)
        await interaction.followup.send(embed=self._queue_embed(player, page - 1))

    @stream.command(name="loop", description="Đổi chế độ lặp (Off → Track → Queue → Off)")
    async def slash_loop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player = self._get_player(interaction.guild_id)
        player.loop = (player.loop + 1) % 3
        await interaction.followup.send(
            f"🔁 Lặp: **{GuildPlayer.LOOP_LABEL[player.loop]}**", ephemeral=True
        )

    @stream.command(name="volume", description="Đặt âm lượng")
    @app_commands.describe(percent="Phần trăm âm lượng")
    async def slash_volume(self, interaction: discord.Interaction, percent: int):
        await interaction.response.defer(ephemeral=True)
        if not 1 <= percent <= 200:
            await interaction.followup.send("Âm lượng phải từ 1 đến 200.", ephemeral=True)
            return
        player = self._get_player(interaction.guild_id)
        player.volume = percent / 100
        if player.vc and player.vc.source and hasattr(player.vc.source, "volume"):
            player.vc.source.volume = player.volume
        await interaction.followup.send(f"Âm lượng: **{percent}%**", ephemeral=True)

    @stream.command(name="shuffle", description="Xáo trộn queue")
    async def slash_shuffle(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player = self._get_player(interaction.guild_id)
        q = list(player.queue)
        random.shuffle(q)
        player.queue = deque(q)
        await interaction.followup.send(f"🔀 Đã xáo trộn **{len(q)}** bài!", ephemeral=True)

    @stream.command(name="remove", description="Xóa bài ra khỏi queue theo vị trí")
    @app_commands.describe(index="Vị trí trong queue (bắt đầu từ 1)")
    async def slash_remove(self, interaction: discord.Interaction, index: int):
        await interaction.response.defer(ephemeral=True)
        player = self._get_player(interaction.guild_id)
        q = list(player.queue)
        if not 1 <= index <= len(q):
            await interaction.followup.send(
                f"Vị trí không hợp lệ (1–{len(q)}).", ephemeral=True
            )
            return
        removed = q.pop(index - 1)
        player.queue = deque(q)
        await interaction.followup.send(
            f"Đã xóa: **{getattr(removed, 'title', removed.raw_url)}**", ephemeral=True
        )

    @stream.command(name="clear", description="Xóa toàn bộ queue (giữ bài đang phát)")
    async def slash_clear(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        player = self._get_player(interaction.guild_id)
        count = len(player.queue)
        player.queue.clear()
        await interaction.followup.send(f"Đã xóa **{count}** bài khỏi queue.", ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    # Prefix Commands  (!play, !skip, etc.)
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="play", aliases=["p"])
    async def prefix_play(self, ctx: commands.Context, *, url: str):
        """Phát nhạc từ YouTube. Dùng: !play <url hoặc tên bài>"""
        await self._handle_play(ctx, url)

    @commands.command(name="skip", aliases=["sk", "next", "fs"])
    async def prefix_skip(self, ctx: commands.Context):
        """Bỏ qua bài đang phát. !skip"""
        player = self._get_player(ctx.guild.id)
        if self._do_skip(player):
            await ctx.message.add_reaction("⏭️")
        else:
            await ctx.send("Không có gì đang phát.")

    @commands.command(name="stop", aliases=["leave", "dc"])
    async def prefix_stop(self, ctx: commands.Context):
        """Dừng phát và rời kênh voice. !stop"""
        await self._destroy_player(ctx.guild.id)
        await ctx.send("⏹️ Đã dừng và rời kênh.")

    @commands.command(name="pause")
    async def prefix_pause(self, ctx: commands.Context):
        """Tạm dừng nhạc. !pause"""
        player = self._get_player(ctx.guild.id)
        if player.vc and player.vc.is_playing():
            player.vc.pause()
            await ctx.message.add_reaction("⏸️")
        else:
            await ctx.send("Không có gì đang phát.")

    @commands.command(name="resume", aliases=["r", "unpause"])
    async def prefix_resume(self, ctx: commands.Context):
        """Tiếp tục nhạc. !resume"""
        player = self._get_player(ctx.guild.id)
        if player.vc and player.vc.is_paused():
            player.vc.resume()
            await ctx.message.add_reaction("▶️")
        else:
            await ctx.send("Không có gì đang tạm dừng.")

    @commands.command(name="np", aliases=["nowplaying", "current"])
    async def prefix_np(self, ctx: commands.Context):
        """Xem bài đang phát. !np"""
        player = self._get_player(ctx.guild.id)
        if not player.current:
            await ctx.send("Không có gì đang phát.")
            return
        await ctx.send(embed=self._np_embed(player.current, player))

    @commands.command(name="queue", aliases=["q"])
    async def prefix_queue(self, ctx: commands.Context, page: int = 1):
        """Xem danh sách nhạc. !queue [trang]"""
        player = self._get_player(ctx.guild.id)
        await ctx.send(embed=self._queue_embed(player, page - 1))

    @commands.command(name="loop", aliases=["repeat"])
    async def prefix_loop(self, ctx: commands.Context):
        """Đổi chế độ lặp. !loop"""
        player = self._get_player(ctx.guild.id)
        player.loop = (player.loop + 1) % 3
        await ctx.send(f"🔁 Loop: **{GuildPlayer.LOOP_LABEL[player.loop]}**")

    @commands.command(name="volume", aliases=["vol"])
    async def prefix_volume(self, ctx: commands.Context, percent: int):
        """Đặt âm lượng 1–200. !volume 80"""
        if not 1 <= percent <= 200:
            await ctx.send("Âm lượng phải từ 1 đến 200.")
            return
        player = self._get_player(ctx.guild.id)
        player.volume = percent / 100
        if player.vc and player.vc.source and hasattr(player.vc.source, "volume"):
            player.vc.source.volume = player.volume
        await ctx.send(f"Âm lượng: **{percent}%**")

    @commands.command(name="shuffle")
    async def prefix_shuffle(self, ctx: commands.Context):
        """Xáo trộn queue. !shuffle"""
        player = self._get_player(ctx.guild.id)
        q = list(player.queue)
        random.shuffle(q)
        player.queue = deque(q)
        await ctx.send(f"🔀 Đã xáo trộn **{len(q)}** bài!")

    @commands.command(name="remove", aliases=["rm", "del"])
    async def prefix_remove(self, ctx: commands.Context, index: int):
        """Xóa bài khỏi queue. !remove <số>"""
        player = self._get_player(ctx.guild.id)
        q = list(player.queue)
        if not 1 <= index <= len(q):
            await ctx.send(f"Vị trí không hợp lệ (1–{len(q)}).")
            return
        removed = q.pop(index - 1)
        player.queue = deque(q)
        await ctx.send(f"Đã xóa: **{getattr(removed, 'title', removed.raw_url)}**")

    @commands.command(name="clearqueue", aliases=["cq", "qclear"])
    async def prefix_clear(self, ctx: commands.Context):
        """Xóa toàn bộ queue. !clearqueue"""
        player = self._get_player(ctx.guild.id)
        count = len(player.queue)
        player.queue.clear()
        await ctx.send(f"Đã xóa **{count}** bài khỏi queue.")

    # ══════════════════════════════════════════════════════════════════════════
    # Events
    # ══════════════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        """Start inactivity timer if bot is left alone in voice."""
        if not member.guild:
            return
        guild_id = member.guild.id
        player = self._players.get(guild_id)
        if not player or not player.vc or not player.vc.channel:
            return

        # Only care about members leaving the bot's channel
        bot_channel = player.vc.channel
        non_bot_members = [m for m in bot_channel.members if not m.bot]
        if not non_bot_members:
            player.restart_inactivity(self._inactivity_leave(guild_id, ALONE_TIMEOUT))


async def setup(bot: commands.Bot):
    await bot.add_cog(StreamingCog(bot))
