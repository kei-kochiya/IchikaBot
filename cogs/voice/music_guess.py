import asyncio
import contextlib
import logging
import os
import random

import discord
from discord import app_commands
from discord.ext import commands

from config import AUDIO_DIR, GUESS_TIME_LIMIT, MAX_GUESSES
from utils.core.tasks import react_in_background, spawn
from utils.data.music_quiz_db import MusicQuizDB, is_correct_guess, normalize
from utils.game.music_helpers import (
    connect_to_voice,
    format_no_eligible_songs_message,
    remove_wrong_reactions,
    scan_audio_files,
    sweep_leftover_temp_clips,
)
from utils.media.audio_fx import prepare_clip

logger = logging.getLogger(__name__)

WRONG_EMOJI = "❌"
CORRECT_EMOJI = "✅"
IDLE_TIMEOUT = 180.0  # Keep bot in voice for 3 minutes before auto-disconnect


class MusicGuess(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games: dict[int, dict] = {}
        self.starting_channels: dict[int, float] = {}
        # A guild has a single voice connection, so only one game may start/run per guild
        self.starting_guilds: dict[int, float] = {}
        self._starting_channel_tokens: dict[int, object] = {}
        self._starting_guild_tokens: dict[int, object] = {}
        self.idle_tasks: dict[int, asyncio.Task] = {}
        # Independent per-session song tracking for comm and all modes
        self.played_songs_comm: set = set()
        self.available_songs_comm: set = set()
        self.played_songs_all: set = set()
        self.available_songs_all: set = set()

    # ── Pool management ────────────────────────────────────────────────────────

    def _get_pool(self, pool_type: str) -> tuple[set, set]:
        if pool_type == "all":
            return self.available_songs_all, self.played_songs_all
        return self.available_songs_comm, self.played_songs_comm

    def _set_pool(self, pool_type: str, available: set, played: set) -> None:
        if pool_type == "all":
            self.available_songs_all = available
            self.played_songs_all = played
        else:
            self.available_songs_comm = available
            self.played_songs_comm = played

    def _filter_eligible_songs(self, pool_type: str, all_files: list[str]) -> list[str]:
        if pool_type == "all":
            return all_files
        comm_ids = MusicQuizDB.get_instance().get_commission_ids()
        return [f for f in all_files if os.path.splitext(os.path.basename(f))[0] in comm_ids]

    def _refresh_available_songs(self, pool_type: str, eligible_files: list[str]) -> set:
        available = set(eligible_files)
        self._set_pool(pool_type, available, set())
        logger.info("Music: Reset [%s] song pool with %d songs.", pool_type, len(eligible_files))
        return available

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def cog_load(self):
        """Load song database and clean up leftover temp files."""
        await asyncio.to_thread(MusicQuizDB.get_instance)
        logger.info("Music: Checking for leftover temp files...")
        count = await asyncio.to_thread(sweep_leftover_temp_clips)
        if count > 0:
            logger.info("Music: Cleaned up %d temp files.", count)

    def cog_unload(self):
        for task in self.idle_tasks.values():
            if not task.done():
                task.cancel()
        self.idle_tasks.clear()

        for game in list(self.active_games.values()):
            timer = game.get("timer_task")
            if timer and not timer.done():
                timer.cancel()
            vc = game.get("voice_client")
            if vc and vc.is_connected():
                with contextlib.suppress(Exception):
                    vc.stop()
            clip_path = game.get("clip_path")
            if clip_path:
                with contextlib.suppress(OSError):
                    os.remove(clip_path)
        self.active_games.clear()

    def _cancel_idle_task(self, guild_id: int) -> None:
        task = self.idle_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _schedule_idle_disconnect(self, guild_id: int, voice_client: discord.VoiceClient):
        """Schedule disconnecting from voice after IDLE_TIMEOUT (3 minutes) of inactivity."""
        self._cancel_idle_task(guild_id)

        async def _idle_disconnect():
            try:
                await asyncio.sleep(IDLE_TIMEOUT)
                if (
                    voice_client
                    and voice_client.is_connected()
                    and not voice_client.is_playing()
                    and self._guild_game_channel(guild_id) is None
                    and guild_id not in self.starting_guilds
                ):
                    logger.info(
                        "Music: Voice client idle for %ds in guild %d, disconnecting.",
                        IDLE_TIMEOUT,
                        guild_id,
                    )
                    await voice_client.disconnect()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Music: Idle disconnect failed in guild %d: %s", guild_id, e)
            finally:
                if self.idle_tasks.get(guild_id) is asyncio.current_task():
                    self.idle_tasks.pop(guild_id, None)

        self.idle_tasks[guild_id] = asyncio.create_task(_idle_disconnect())

    # ── Game lifecycle ─────────────────────────────────────────────────────────

    async def cleanup_game(self, channel_id: int, *, schedule_idle: bool = True):
        game = self.active_games.pop(channel_id, None)
        if game is None:
            return

        current_task = asyncio.current_task()
        if game.get("timer_task") and game["timer_task"] != current_task:
            game["timer_task"].cancel()

        vc = game.get("voice_client")
        if vc and vc.is_connected():
            vc.stop()
            if schedule_idle and vc.guild:
                self._schedule_idle_disconnect(vc.guild.id, vc)

        # Offload cosmetic wrong-reaction removal so REST rate limits never stall voice teardown
        wrong_reactions = game.get("wrong_reactions")
        if wrong_reactions:
            spawn(remove_wrong_reactions(list(wrong_reactions), WRONG_EMOJI, self.bot.user))

        await asyncio.sleep(0.5)

        clip_path = game.get("clip_path")
        if clip_path and os.path.exists(clip_path):
            try:
                os.remove(clip_path)
            except OSError as e:
                logger.warning("Failed to remove temp file %s: %s", clip_path, e)

    def _guild_game_channel(self, guild_id: int) -> int | None:
        """Text channel of the game already running in this guild, if any."""
        for ch_id, game in self.active_games.items():
            if game.get("guild_id") == guild_id:
                return ch_id
        return None

    async def end_game_timer(self, channel, channel_id: int):
        await asyncio.sleep(GUESS_TIME_LIMIT)
        game = self.active_games.get(channel_id)
        if game is None or game.get("ended"):
            return
        game["ended"] = True
        try:
            await channel.send(f"Hết giờ! Đáp án là **{game['display_answer']}**")
        except discord.HTTPException as e:
            logger.warning("Music: Could not announce timeout in %s: %s", channel_id, e)
        finally:
            await self.cleanup_game(channel_id)

    # ── Core game logic ────────────────────────────────────────────────────────

    async def start_game_logic(
        self, interaction_or_ctx, variant_mode: bool = False, pool_type: str = "comm"
    ):
        """Core game logic shared between slash and prefix commands."""
        pool_type = "all" if pool_type.lower() in ("all", "a", "tatca") else "comm"

        if isinstance(interaction_or_ctx, discord.Interaction):
            interaction = interaction_or_ctx
            user = interaction.user
            channel = interaction.channel
            await interaction.response.defer()

            async def send_msg(content, **kwargs):
                if "delete_after" in kwargs:
                    del kwargs["delete_after"]
                    kwargs.setdefault("ephemeral", True)
                await interaction.followup.send(content, **kwargs)
        else:
            ctx = interaction_or_ctx
            user = ctx.author
            channel = ctx.channel

            async def send_msg(content, **kwargs):
                await ctx.send(content, **kwargs)

        channel_id = channel.id
        if channel_id in self.active_games:
            await send_msg(
                "Kênh này đang có người thử tài rồi. Vào chơi cùng họ đi!", delete_after=10
            )
            return

        now = asyncio.get_running_loop().time()
        if channel_id in self.starting_channels:
            if now - self.starting_channels[channel_id] < 45.0:
                await send_msg("Đang chuẩn bị ván chơi rồi, bạn đợi một chút nhé!", delete_after=10)
                return
            logger.warning("Stale starting lock for channel %s, auto-recovering", channel_id)
            self.starting_channels.pop(channel_id, None)
            self._starting_channel_tokens.pop(channel_id, None)

        if not user.voice or not user.voice.channel:
            await send_msg("Mời bạn vào kênh voice để chơi nhé!", delete_after=10)
            return

        guild_id = user.guild.id
        other_channel = self._guild_game_channel(guild_id)
        if other_channel is not None:
            await send_msg(
                f"Server này đang có một ván đoán nhạc ở <#{other_channel}> rồi "
                "(bot chỉ phát nhạc ở một kênh voice mỗi lúc). Vào chơi cùng nhé!",
                delete_after=10,
            )
            return
        if guild_id in self.starting_guilds:
            if now - self.starting_guilds[guild_id] < 45.0:
                await send_msg(
                    "Đang chuẩn bị một ván chơi khác trong server, bạn đợi một chút nhé!",
                    delete_after=10,
                )
                return
            self.starting_guilds.pop(guild_id, None)
            self._starting_guild_tokens.pop(guild_id, None)

        token = object()
        self.starting_channels[channel_id] = now
        self.starting_guilds[guild_id] = now
        self._starting_channel_tokens[channel_id] = token
        self._starting_guild_tokens[guild_id] = token
        self._cancel_idle_task(guild_id)

        try:
            await self._run_game_start(user, channel, send_msg, pool_type, variant_mode)
        finally:
            if self._starting_channel_tokens.get(channel_id) is token:
                self._starting_channel_tokens.pop(channel_id, None)
                self.starting_channels.pop(channel_id, None)
            if self._starting_guild_tokens.get(guild_id) is token:
                self._starting_guild_tokens.pop(guild_id, None)
                self.starting_guilds.pop(guild_id, None)
            vc = getattr(user.guild, "voice_client", None)
            if (
                self._guild_game_channel(guild_id) is None
                and guild_id not in self.starting_guilds
                and vc is not None
                and vc.is_connected()
            ):
                self._schedule_idle_disconnect(guild_id, vc)

    async def _run_game_start(self, user, channel, send_msg, pool_type, variant_mode):
        try:
            audio_path, song_files = await asyncio.to_thread(scan_audio_files, AUDIO_DIR)
            if not song_files:
                await send_msg(f"Không tìm thấy bài hát nào trong thư mục `{audio_path}`.")
                return
        except Exception as e:
            logger.error("Error reading music directory: %s", e)
            await send_msg(f"Lỗi đọc thư mục nhạc: {e}")
            return

        eligible_files = self._filter_eligible_songs(pool_type, song_files)
        if not eligible_files:
            db = MusicQuizDB.get_instance()
            if len(db._db) == 0 or (pool_type == "comm" and len(db.get_commission_ids()) == 0):
                await asyncio.to_thread(db.load_db)
                eligible_files = self._filter_eligible_songs(pool_type, song_files)
        if not eligible_files:
            await send_msg(
                format_no_eligible_songs_message(MusicQuizDB.get_instance(), song_files, pool_type)
            )
            return

        variant = random.choice(["fast", "slow", "reverse"]) if variant_mode else None

        available, played = self._get_pool(pool_type)
        eligible_set = set(eligible_files)
        available &= eligible_set
        played &= eligible_set
        if not available:
            available = self._refresh_available_songs(pool_type, eligible_files)
            played = set()

        chosen_file = None
        clip_path = None
        effect_name = None
        for _ in range(5):
            if not available:
                await send_msg("Không có bài hát nào có thể phát được.")
                return
            chosen_file = random.choice(list(available))
            full_path = os.path.join(str(audio_path), chosen_file)
            clip_path, effect_name = await asyncio.to_thread(prepare_clip, full_path, variant)
            if clip_path is not None:
                break
            available.discard(chosen_file)
            if not available:
                available = self._refresh_available_songs(pool_type, eligible_files)
                played = set()

        if chosen_file:
            available.discard(chosen_file)
            played.add(chosen_file)
            self._set_pool(pool_type, available, played)

        if clip_path is None:
            await send_msg("Lỗi kỹ thuật khi xử lý bài hát.")
            return

        clip_owned_by_game = False
        try:
            db = MusicQuizDB.get_instance()
            info = db.get_song_info(chosen_file)
            display_answer = db.build_display_answer(info)
            norm_targets = db.build_norm_targets(info)
            if not norm_targets:
                stem = os.path.splitext(chosen_file)[0]
                norm_targets = [normalize(stem)]
                logger.warning(
                    "Music: No title found for song index %s; using filename as answer.", stem
                )

            if not user.voice or not user.voice.channel:
                await send_msg("Bạn đã rời kênh voice trước khi ván chơi bắt đầu.", delete_after=10)
                return
            if (
                channel.id in self.active_games
                or self._guild_game_channel(user.guild.id) is not None
            ):
                await send_msg("Đã có ván chơi khác đang diễn ra trong server!", delete_after=10)
                return

            target_channel = user.voice.channel
            try:
                voice_client = await connect_to_voice(user.guild, target_channel)
            except TimeoutError:
                logger.error("Voice connection timed out on %s", target_channel.name)
                await send_msg(
                    "Không vào được kênh voice: hết thời gian chờ (mạng của bot có thể đang chặn UDP)."
                )
                return
            except Exception as e:
                logger.error("Voice connection error: %s", e)
                await send_msg(f"Lỗi vào voice: {e}")
                return

            if (
                channel.id in self.active_games
                or self._guild_game_channel(user.guild.id) is not None
            ):
                await send_msg("Đã có ván chơi khác đang diễn ra trong server!", delete_after=10)
                return

            timer_task = asyncio.create_task(self.end_game_timer(channel, channel.id))
            game = {
                "guild_id": user.guild.id,
                "norm_targets": norm_targets,
                "display_answer": display_answer,
                "info": info,
                "guesses": {},
                "wrong_reactions": [],
                "voice_client": voice_client,
                "clip_path": clip_path,
                "timer_task": timer_task,
                "ended": False,
            }
            self.active_games[channel.id] = game
            clip_owned_by_game = True
        finally:
            if not clip_owned_by_game:
                with contextlib.suppress(OSError):
                    os.remove(clip_path)

        pool_label = "Commission" if pool_type == "comm" else "Tất cả bài hát"
        mode_text = f"\n(Hiệu ứng: {effect_name})" if variant_mode else ""
        try:
            await send_msg(
                f"**Đoán tên bài hát** · Gói **{pool_label}**{mode_text}\n"
                f"Thời gian: {GUESS_TIME_LIMIT}s | Số lượt đoán: {MAX_GUESSES}\n"
                f"Gõ `-g [tên bài hát]` để trả lời!"
            )
            if self.active_games.get(channel.id) is not game:
                return
            if not voice_client.is_connected():
                await self.cleanup_game(channel.id, schedule_idle=False)
                return
            source = discord.FFmpegPCMAudio(clip_path)
            try:
                voice_client.play(source)
            except Exception:
                source.cleanup()
                raise
        except Exception as e:
            logger.error("Playback/announcement error: %s", e, exc_info=True)
            await self.cleanup_game(channel.id)
            with contextlib.suppress(discord.HTTPException):
                await send_msg("Lỗi khi phát nhạc.")

    # ── Commands ───────────────────────────────────────────────────────────────

    @commands.command(name="songguess", aliases=["sg", "sgc"])
    @commands.guild_only()
    async def guess_music(self, ctx, pool: str = "comm"):
        """Đoán nhạc. Mặc định là commission (-sg), hoặc tất cả (-sg all)"""
        await self.start_game_logic(ctx, variant_mode=False, pool_type=pool)

    @commands.command(name="songguessv", aliases=["sgv"])
    @commands.guild_only()
    async def guess_music_variant(self, ctx, pool: str = "comm"):
        """Đoán nhạc có hiệu ứng (-sgv hoặc -sgv all)"""
        await self.start_game_logic(ctx, variant_mode=True, pool_type=pool)

    @commands.command(name="songguessall", aliases=["sga"])
    @commands.guild_only()
    async def guess_music_all(self, ctx):
        """Đoán nhạc toàn bộ bài hát (-sga)"""
        await self.start_game_logic(ctx, variant_mode=False, pool_type="all")

    @commands.command(name="songguessallv", aliases=["sgav"])
    @commands.guild_only()
    async def guess_music_all_variant(self, ctx):
        """Đoán nhạc toàn bộ bài hát có hiệu ứng (-sgav)"""
        await self.start_game_logic(ctx, variant_mode=True, pool_type="all")

    @app_commands.command(name="songguess", description="Bắt đầu game đoán bài hát!")
    @app_commands.guild_only()
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.describe(
        mode="Chế độ hiệu ứng âm thanh",
        pool="Gói bài hát muốn đoán (Commission hoặc Tất cả)",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Bình thường", value="normal"),
            app_commands.Choice(name="Khó (Hiệu ứng)", value="hard"),
        ],
        pool=[
            app_commands.Choice(name="Commission (Viết riêng cho game)", value="comm"),
            app_commands.Choice(name="Tất cả bài hát", value="all"),
        ],
    )
    async def slash_songguess(
        self,
        interaction: discord.Interaction,
        mode: str = "normal",
        pool: str = "comm",
    ):
        await self.start_game_logic(interaction, variant_mode=(mode == "hard"), pool_type=pool)

    # ── Message & voice listeners ──────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.content.lower().startswith("-g "):
            return

        channel_id = message.channel.id
        game = self.active_games.get(channel_id)
        if game is None or game.get("ended"):
            return

        user_id = message.author.id
        if game["guesses"].get(user_id, 0) >= MAX_GUESSES:
            return

        guess_input = message.content[3:].strip()
        if not guess_input:
            return

        if is_correct_guess(guess_input, game["norm_targets"]):
            if game.get("ended"):
                return
            game["ended"] = True

            if game.get("timer_task") and not game["timer_task"].done():
                game["timer_task"].cancel()

            react_in_background(message, CORRECT_EMOJI)
            reveal = MusicQuizDB.build_reveal(game["info"])
            try:
                await message.reply(f"Chính xác! {message.author.mention} giỏi quá!\n{reveal}")
            except discord.HTTPException as e:
                logger.warning("Music: Could not announce winner in %s: %s", channel_id, e)
            finally:
                await self.cleanup_game(channel_id)
        else:
            if game.get("ended"):
                return
            game["guesses"][user_id] = game["guesses"].get(user_id, 0) + 1
            react_in_background(message, WRONG_EMOJI)
            game["wrong_reactions"].append(message)

            if game["guesses"][user_id] >= MAX_GUESSES:
                with contextlib.suppress(discord.HTTPException):
                    await message.reply("Tiếc quá, cậu hết lượt đoán rồi!", delete_after=5)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        """Auto-disconnect if bot is left alone, and clean up if bot is kicked from voice."""
        guild = member.guild

        if self.bot.user is not None and member.id == self.bot.user.id and after.channel is None:
            self._cancel_idle_task(guild.id)
            ch_id = self._guild_game_channel(guild.id)
            if ch_id is not None:
                await self.cleanup_game(ch_id, schedule_idle=False)
            return

        vc = guild.voice_client
        if not vc or not vc.channel:
            return

        if not any(not m.bot for m in vc.channel.members):
            self._cancel_idle_task(guild.id)
            for ch_id, game in list(self.active_games.items()):
                if game.get("voice_client") == vc:
                    await self.cleanup_game(ch_id, schedule_idle=False)
                    break
            # Re-verify after awaiting cleanup: a player may have rejoined or started a new round
            if (
                vc.is_connected()
                and vc.channel is not None
                and not any(not m.bot for m in vc.channel.members)
                and self._guild_game_channel(guild.id) is None
                and guild.id not in self.starting_guilds
            ):
                logger.info(
                    "Music: Bot left alone in voice channel %s, disconnecting.",
                    vc.channel.name,
                )
                await vc.disconnect()


async def setup(bot):
    await bot.add_cog(MusicGuess(bot))
