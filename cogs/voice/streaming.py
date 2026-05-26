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
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.voice.models import QueueEntry, UnresolvedEntry
from utils.voice.player import GuildPlayer
from utils.voice.ui import NowPlayingView, np_embed, queue_embed
from utils.voice.youtube import resolve_track, fetch_playlist_flat

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

INACTIVITY_TIMEOUT = 300   # seconds before auto-leave (no tracks)
ALONE_TIMEOUT      = 120   # seconds before auto-leave (bot alone in VC)
MAX_QUEUE_SIZE     = 200

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
        # Disable the persistent NP embed buttons
        if player.np_message and player.np_view:
            await self._disable_np_message(player, stopped=True)
        if player.vc:
            if player.vc.is_playing() or player.vc.is_paused():
                player.vc.stop()
            try:
                await player.vc.disconnect()
            except Exception:
                pass

    # ── NP embed helpers ───────────────────────────────────────────────────────

    async def _update_np_message(self, player: GuildPlayer) -> None:
        """Send (first time) or edit (subsequent) the persistent NP embed."""
        if not player.current:
            return
        embed = np_embed(player.current, player)
        # Refresh view button states
        if player.np_view:
            player.np_view._refresh_pause_button()
            player.np_view._refresh_loop_button()
        if player.np_message is None:
            # First track — send the message and keep the reference
            player.np_view = NowPlayingView(self, player.vc.guild.id if player.vc else 0)
            try:
                player.np_message = await player.text_channel.send(embed=embed, view=player.np_view)
            except Exception as exc:
                logger.warning("NP message send failed: %s", exc)
        else:
            # Subsequent tracks — edit in place
            try:
                await player.np_message.edit(embed=embed, view=player.np_view)
            except discord.NotFound:
                # Message was deleted — send a fresh one
                player.np_message = None
                player.np_view = None
                await self._update_np_message(player)
            except Exception as exc:
                logger.warning("NP message edit failed: %s", exc)

    async def _disable_np_message(self, player: GuildPlayer, stopped: bool = False) -> None:
        """Disable all buttons and optionally update the embed title."""
        if not player.np_message or not player.np_view:
            return
        player.np_view.disable_all()
        try:
            embed = player.np_message.embeds[0] if player.np_message.embeds else None
            if embed and stopped:
                embed.title = "⏹ Đã dừng"
            elif embed:
                embed.title = "✅ Đã phát xong"
            await player.np_message.edit(embed=embed, view=player.np_view)
        except Exception:
            pass
        player.np_message = None
        player.np_view = None

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
                fetched = await resolve_track(
                    player.current.webpage_url, player.current.requester
                )
                entry = fetched  # None → fall through to queue

            if entry is None:
                if not player.queue:
                    # Queue exhausted
                    player.current = None
                    await self._disable_np_message(player, stopped=False)
                    await self._safe_send(player, "Đã hết queue!")
                    player.restart_inactivity(self._inactivity_leave(guild_id, INACTIVITY_TIMEOUT))
                    return

                raw = player.queue.popleft()

                # Queue loop: re-append at end
                if player.loop == GuildPlayer.LOOP_QUEUE:
                    player.queue.append(raw)

                if isinstance(raw, UnresolvedEntry):
                    await self._safe_send(player, f"Đang tải: **{raw.title}**...", delete_after=8)
                    entry = await resolve_track(raw.raw_url, raw.requester)
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
                # Update (or send) the persistent NP embed
                await self._update_np_message(player)

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
            entries = await fetch_playlist_flat(url, author)
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

        # Always resolve the deferred interaction (prevents stuck "thinking" indicator).
        # Prefix commands go through _safe_send only when already playing.
        if is_ix:
            await ctx_or_ix.followup.send(confirm, ephemeral=True)
        elif player.is_active:
            await self._safe_send(player, confirm)


    # ── Shared skip / stop helpers ─────────────────────────────────────────────

    def _do_skip(self, player: GuildPlayer) -> bool:
        if not player.is_active:
            return False
        player._skip_flag = True
        if player.vc and (player.vc.is_playing() or player.vc.is_paused()):
            player.vc.stop()
        return True

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
        player = self._players.get(interaction.guild_id)
        if player and self._do_skip(player):
            await interaction.response.send_message("⏭️ Đã bỏ qua!", ephemeral=True)
        else:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)

    @stream.command(name="stop", description="Dừng nhạc và rời kênh")
    async def slash_stop(self, interaction: discord.Interaction):
        await self._destroy_player(interaction.guild_id)
        await interaction.response.send_message("⏹️ Đã dừng.", ephemeral=True)

    @stream.command(name="queue", description="Xem danh sách phát")
    async def slash_queue(self, interaction: discord.Interaction, page: int = 1):
        player = self._players.get(interaction.guild_id)
        if not player or (not player.queue and not player.current):
            await interaction.response.send_message("Queue trống.", ephemeral=True)
            return
        embed = queue_embed(player, page - 1)
        await interaction.response.send_message(embed=embed)

    @stream.command(name="remove", description="Xóa một bài khỏi queue")
    async def slash_remove(self, interaction: discord.Interaction, index: int):
        player = self._players.get(interaction.guild_id)
        if not player or not player.queue:
            await interaction.response.send_message("Queue trống.", ephemeral=True)
            return
        if 1 <= index <= len(player.queue):
            item = player.queue[index - 1]
            del player.queue[index - 1]
            title = getattr(item, 'title', 'Bài hát')
            await interaction.response.send_message(f"🗑️ Đã xóa: **{title}**", ephemeral=True)
            if player.np_message:
                try:
                    await player.np_message.edit(embed=np_embed(player.current, player))
                except Exception:
                    pass
        else:
            await interaction.response.send_message("Số thứ tự không hợp lệ.", ephemeral=True)

    @stream.command(name="volume", description="Chỉnh âm lượng (1-200)")
    async def slash_volume(self, interaction: discord.Interaction, vol: int):
        player = self._players.get(interaction.guild_id)
        if not player:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)
            return
        v = max(1, min(200, vol))
        player.volume = v / 100.0
        if player.vc and player.vc.source:
            player.vc.source.volume = player.volume
        await interaction.response.send_message(f"🔊 Âm lượng: **{v}%**", ephemeral=True)
        if player.np_message and player.current:
            try:
                await player.np_message.edit(embed=np_embed(player.current, player))
            except Exception:
                pass


    # ══════════════════════════════════════════════════════════════════════════
    # Prefix Commands (Legacy)
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="play", aliases=["p"])
    async def cmd_play(self, ctx: commands.Context, *, url: str):
        await self._handle_play(ctx, url)

    @commands.command(name="skip", aliases=["sk", "next"])
    async def cmd_skip(self, ctx: commands.Context):
        player = self._players.get(ctx.guild.id)
        if player and self._do_skip(player):
            await ctx.message.add_reaction("⏭️")
        else:
            await ctx.send("Không có gì đang phát.")

    @commands.command(name="stop", aliases=["leave", "dc"])
    async def cmd_stop(self, ctx: commands.Context):
        await self._destroy_player(ctx.guild.id)
        await ctx.message.add_reaction("⏹️")

    @commands.command(name="queue", aliases=["q"])
    async def cmd_queue(self, ctx: commands.Context, page: int = 1):
        player = self._players.get(ctx.guild.id)
        if not player or (not player.queue and not player.current):
            await ctx.send("Queue trống.")
            return
        embed = queue_embed(player, page - 1)
        await ctx.send(embed=embed)

    @commands.command(name="remove", aliases=["rm"])
    async def cmd_remove(self, ctx: commands.Context, index: int):
        player = self._players.get(ctx.guild.id)
        if not player or not player.queue:
            return await ctx.send("Queue trống.")
        if 1 <= index <= len(player.queue):
            item = player.queue[index - 1]
            del player.queue[index - 1]
            title = getattr(item, 'title', 'Bài hát')
            await ctx.send(f"🗑️ Đã xóa: **{title}**")
            if player.np_message:
                try:
                    await player.np_message.edit(embed=np_embed(player.current, player))
                except Exception:
                    pass
        else:
            await ctx.send("Số thứ tự không hợp lệ.")

    @commands.command(name="volume", aliases=["vol"])
    async def cmd_volume(self, ctx: commands.Context, vol: int):
        player = self._players.get(ctx.guild.id)
        if not player:
            return await ctx.send("Không có gì đang phát.")
        v = max(1, min(200, vol))
        player.volume = v / 100.0
        if player.vc and player.vc.source:
            player.vc.source.volume = player.volume
        await ctx.send(f"🔊 Âm lượng: **{v}%**")
        if player.np_message and player.current:
            try:
                await player.np_message.edit(embed=np_embed(player.current, player))
            except Exception:
                pass


    # ── Voice State Events ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Auto-pause/leave when people leave the channel."""
        if member == self.bot.user:
            return

        vc = member.guild.voice_client
        if not vc or not vc.channel:
            return
        
        # If bot is left alone in the channel (only bot remains)
        non_bot_members = [m for m in vc.channel.members if not m.bot]
        if not non_bot_members:
            player = self._players.get(member.guild.id)
            if player and player.vc:
                # Set a timer to leave if nobody joins back
                player.restart_inactivity(
                    self._inactivity_leave(member.guild.id, ALONE_TIMEOUT)
                )

        # If someone joined and bot was alone, cancel the leave timer
        if after.channel == vc.channel and len(non_bot_members) > 0:
            player = self._players.get(member.guild.id)
            if player and player.inactivity_task:
                if player.vc and (player.vc.is_playing() or player.vc.is_paused()):
                    player.inactivity_task.cancel()


async def setup(bot):
    await bot.add_cog(StreamingCog(bot))
