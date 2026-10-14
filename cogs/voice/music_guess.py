import asyncio
import contextlib
import glob
import logging
import os
import random
import shutil
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from config import AUDIO_DIR, GUESS_TIME_LIMIT, MAX_GUESSES, TEMP_DIR
from utils.data.music_quiz_db import MusicQuizDB, is_correct_guess
from utils.media.audio_fx import TEMP_CLIP_PREFIX, prepare_clip

logger = logging.getLogger(__name__)

WRONG_EMOJI = "❌"
CORRECT_EMOJI = "✅"


class MusicGuess(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}
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
        db = MusicQuizDB.get_instance()
        comm_ids = db.get_commission_ids()
        return [f for f in all_files if os.path.splitext(os.path.basename(f))[0] in comm_ids]

    def _refresh_available_songs(self, pool_type: str, eligible_files: list[str]) -> set:
        available = set(eligible_files)
        played = set()
        self._set_pool(pool_type, available, played)
        logger.info(
            "Music: Reset [%s] song pool with %d songs.",
            pool_type,
            len(eligible_files),
        )
        return available

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def cog_load(self):
        """Load song database and clean up leftover temp files."""
        # Initialize the song DB singleton
        MusicQuizDB.get_instance()

        logger.info("Music: Checking for leftover temp files...")
        count = 0
        for file in TEMP_DIR.glob(f"{TEMP_CLIP_PREFIX}*.mp3"):
            try:
                file.unlink()
                count += 1
            except OSError as e:
                logger.warning("Could not remove %s: %s", file, e)
        for file in glob.glob(f"./{TEMP_CLIP_PREFIX}*.mp3"):
            try:
                os.remove(file)
                count += 1
            except OSError as e:
                logger.warning("Could not remove legacy temp file %s: %s", file, e)
        if count > 0:
            logger.info("Music: Cleaned up %d temp files.", count)

    # ── Game lifecycle ─────────────────────────────────────────────────────────

    async def cleanup_game(self, channel_id: int):
        if channel_id not in self.active_games:
            return
        game = self.active_games.pop(channel_id)

        current_task = asyncio.current_task()
        if game["timer_task"] and game["timer_task"] != current_task:
            game["timer_task"].cancel()

        if game["voice_client"] and game["voice_client"].is_connected():
            game["voice_client"].stop()
            await game["voice_client"].disconnect()

        await asyncio.sleep(0.5)

        try:
            if game["clip_path"] and os.path.exists(game["clip_path"]):
                os.remove(game["clip_path"])
        except OSError as e:
            logger.warning("Failed to remove temp file %s: %s", game["clip_path"], e)

        for msg in game["wrong_reactions"]:
            with contextlib.suppress(discord.HTTPException):
                await msg.remove_reaction(WRONG_EMOJI, self.bot.user)

    async def end_game_timer(self, channel, channel_id: int):
        await asyncio.sleep(GUESS_TIME_LIMIT)
        if channel_id in self.active_games:
            game = self.active_games[channel_id]
            await channel.send(f"Hết giờ rồi! ⏰ Đáp án chính xác là: **{game['display_answer']}**")
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

        if channel.id in self.active_games:
            await send_msg(
                "Kênh này đang có người thử tài rồi. Vào chơi cùng họ đi!", delete_after=10
            )
            return

        if not user.voice:
            await send_msg("Mời bạn vào kênh voice để chơi nhé!", delete_after=10)
            return

        # ── Scan song files ─────────────────────────────────────────────────
        try:
            audio_path = Path(AUDIO_DIR)
            if not audio_path.exists():
                # Case-insensitive fallback for Linux
                parent = audio_path.parent
                if parent.exists():
                    for p in parent.iterdir():
                        if p.name.lower() == audio_path.name.lower() and p.is_dir():
                            audio_path = p
                            break
            if not audio_path.exists():
                audio_path.mkdir(parents=True, exist_ok=True)

            song_files = []
            for root, _, files in os.walk(str(audio_path)):
                for f in files:
                    if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
                        rel_path = os.path.relpath(os.path.join(root, f), str(audio_path))
                        song_files.append(rel_path)

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
            # Retry loading once in case song.xlsx was recently updated or added on disk
            if len(db._db) == 0 or (pool_type == "comm" and len(db.get_commission_ids()) == 0):
                db.load_db()
                eligible_files = self._filter_eligible_songs(pool_type, song_files)

        if not eligible_files:
            db = MusicQuizDB.get_instance()
            if db.last_error:
                await send_msg(f"❌ Lỗi nạp dữ liệu `song.xlsx`: {db.last_error}")
                return
            if len(db._db) == 0:
                await send_msg(
                    "❌ Cơ sở dữ liệu bài hát đang trống. "
                    "Vui lòng kiểm tra file `gameData/static/song.xlsx` hoặc cài `openpyxl`."
                )
                return
            comm_ids = db.get_commission_ids()
            if pool_type == "comm" and len(comm_ids) == 0:
                await send_msg(
                    "❌ Dữ liệu commission chưa có trong `song.xlsx`. "
                    "Vui lòng `git pull` để nhận file `song.xlsx` mới nhất có đánh dấu commission."
                )
                return

            sample_files = ", ".join(song_files[:3])
            pool_desc = "commission" if pool_type == "comm" else "hợp lệ"
            await send_msg(
                f"Không tìm thấy bài hát {pool_desc} nào trong thư mục nhạc.\n"
                f"Đã phát hiện {len(song_files)} file nhạc (ví dụ: `{sample_files}`), "
                f"nhưng tên file cần đặt theo ID bài hát (ví dụ: `54.mp3`, `101.mp3`)."
            )
            return

        variant = random.choice(["fast", "slow", "reverse"]) if variant_mode else None

        # Sync pool with current files
        available, played = self._get_pool(pool_type)
        eligible_set = set(eligible_files)
        available &= eligible_set
        played &= eligible_set
        if not available:
            available = self._refresh_available_songs(pool_type, eligible_files)
            played = set()

        # ── Check ffmpeg ───────────────────────────────────────────────────
        if not shutil.which("ffmpeg"):
            await send_msg(
                "❌ Máy chủ chưa có công cụ `ffmpeg`! Vui lòng cài `ffmpeg` vào host để bot có thể phát nhạc."
            )
            return

        # ── Pick a song ─────────────────────────────────────────────────────
        chosen_file = None
        clip_path = None
        effect_name = None

        for _ in range(5):
            if not available:
                await send_msg("Không có bài hát nào có thể phát được.")
                return
            chosen_file = random.choice(list(available))
            full_path = os.path.join(str(audio_path), chosen_file)
            clip_path, effect_name = await self.bot.loop.run_in_executor(
                None, prepare_clip, full_path, variant
            )
            if clip_path is not None:
                break
            available.discard(chosen_file)
            if not available:
                available = self._refresh_available_songs(pool_type, eligible_files)

        if chosen_file:
            available.discard(chosen_file)
            played.add(chosen_file)
            self._set_pool(pool_type, available, played)

        if clip_path is None:
            await send_msg("Lỗi kỹ thuật khi xử lý bài hát.")
            return

        # ── Look up song titles ─────────────────────────────────────────────
        db = MusicQuizDB.get_instance()
        info = db.get_song_info(chosen_file)
        display_answer = db.build_display_answer(info)
        norm_targets = db.build_norm_targets(info)

        if not norm_targets:
            from utils.data.music_quiz_db import normalize

            # No known title — fall back to filename stem so the game can still work
            stem = os.path.splitext(chosen_file)[0]
            norm_targets = [normalize(stem)]
            logger.warning(
                "Music: No title found for song index %s; using filename as answer.", stem
            )

        # ── Connect to voice ────────────────────────────────────────────────
        try:
            guild_vc = user.guild.voice_client
            if guild_vc and guild_vc.channel == user.voice.channel and guild_vc.is_connected():
                voice_client = guild_vc
            elif guild_vc and guild_vc.channel != user.voice.channel and guild_vc.is_connected():
                await guild_vc.move_to(user.voice.channel)
                voice_client = guild_vc
            else:
                if guild_vc and not guild_vc.is_connected():
                    await guild_vc.disconnect(force=True)
                voice_client = await user.voice.channel.connect(
                    self_deaf=True, timeout=20.0, reconnect=False
                )
        except TimeoutError:
            logger.error("Voice connection timed out on %s", user.voice.channel.name)
            await send_msg(
                "❌ Không thể kết nối Voice (Hết thời gian chờ handshake UDP).\n"
                "👉 **Nguyên nhân:** Máy chủ host có thể đang chặn luồng mạng UDP (Voice Discord yêu cầu cổng UDP).\n"
                "👉 **Khắc phục thử:** Vào Discord -> Chỉnh sửa kênh Voice -> Đổi **Region Override** sang Singapore hoặc Hong Kong."
            )
            if clip_path and os.path.exists(clip_path):
                os.remove(clip_path)
            return
        except discord.errors.ClientException as e:
            logger.error("Voice client exception: %s", e)
            await send_msg(f"Lỗi vào voice: {e}")
            if clip_path and os.path.exists(clip_path):
                os.remove(clip_path)
            return
        except Exception as e:
            logger.error("Voice connection error: %s", e)
            await send_msg(f"Lỗi vào voice: {e}")
            if clip_path and os.path.exists(clip_path):
                os.remove(clip_path)
            return

        timer_task = self.bot.loop.create_task(self.end_game_timer(channel, channel.id))

        self.active_games[channel.id] = {
            "norm_targets": norm_targets,  # normalized strings to match against
            "display_answer": display_answer,  # shown on reveal
            "info": info,  # full title dict for rich embeds
            "guesses": {},
            "wrong_reactions": [],
            "voice_client": voice_client,
            "clip_path": clip_path,
            "timer_task": timer_task,
        }

        pool_label = "Commission" if pool_type == "comm" else "Tất cả bài hát"
        mode_text = f"\n(Hiệu ứng: {effect_name})" if variant_mode else ""
        await send_msg(
            f"**Đoán Tên Bài Hát!** 🎧 [Gói: **{pool_label}**]{mode_text}\n"
            f"Thời gian: {GUESS_TIME_LIMIT}s | Số lượt đoán: {MAX_GUESSES}\n"
            f"Gõ `-g [tên bài hát]` để trả lời!"
        )

        try:
            voice_client.play(discord.FFmpegPCMAudio(clip_path))
        except Exception as e:
            logger.error("Playback error: %s", e)
            await send_msg("Lỗi khi phát nhạc.")
            await self.cleanup_game(channel.id)

    # ── Commands ───────────────────────────────────────────────────────────────

    @commands.command(name="songguess", aliases=["sg", "sgc"])
    async def guess_music(self, ctx, pool: str = "comm"):
        """Đoán nhạc. Mặc định là commission (-sg), hoặc tất cả (-sg all)"""
        await self.start_game_logic(ctx, variant_mode=False, pool_type=pool)

    @commands.command(name="songguessv", aliases=["sgv"])
    async def guess_music_variant(self, ctx, pool: str = "comm"):
        """Đoán nhạc có hiệu ứng (-sgv hoặc -sgv all)"""
        await self.start_game_logic(ctx, variant_mode=True, pool_type=pool)

    @commands.command(name="songguessall", aliases=["sga"])
    async def guess_music_all(self, ctx):
        """Đoán nhạc toàn bộ bài hát (-sga)"""
        await self.start_game_logic(ctx, variant_mode=False, pool_type="all")

    @commands.command(name="songguessallv", aliases=["sgav"])
    async def guess_music_all_variant(self, ctx):
        """Đoán nhạc toàn bộ bài hát có hiệu ứng (-sgav)"""
        await self.start_game_logic(ctx, variant_mode=True, pool_type="all")

    @app_commands.command(name="songguess", description="Bắt đầu game đoán bài hát!")
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

    # ── Message listener ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.content.lower().startswith("-g "):
            return

        channel_id = message.channel.id
        if channel_id not in self.active_games:
            return

        game = self.active_games[channel_id]
        user_id = message.author.id

        if game["guesses"].get(user_id, 0) >= MAX_GUESSES:
            return

        guess_input = message.content[3:].strip()
        if not guess_input:
            return

        if is_correct_guess(guess_input, game["norm_targets"]):
            asyncio.create_task(message.add_reaction(CORRECT_EMOJI))

            info = game["info"]
            reveal = MusicQuizDB.build_reveal(info)
            await message.reply(f"Chính xác! 🎉 {message.author.mention} giỏi quá!\n{reveal}")
            await self.cleanup_game(channel_id)
        else:
            game["guesses"][user_id] = game["guesses"].get(user_id, 0) + 1
            asyncio.create_task(message.add_reaction(WRONG_EMOJI))
            game["wrong_reactions"].append(message)

            if game["guesses"][user_id] >= MAX_GUESSES:
                await message.reply("Tiếc quá, cậu hết lượt đoán rồi!", delete_after=5)

    # ── Error handlers ─────────────────────────────────────────────────────────

    @guess_music.error
    @guess_music_variant.error
    async def guess_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Đang hồi chiêu: {error.retry_after:.1f}s", delete_after=10)


async def setup(bot):
    await bot.add_cog(MusicGuess(bot))
