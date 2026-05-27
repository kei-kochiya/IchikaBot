import discord
from discord.ext import commands
from discord import app_commands
import os
import random
import asyncio
import logging
import glob
from config import AUDIO_DIR, TEMP_DIR, GUESS_TIME_LIMIT, MAX_GUESSES

from utils.data.music_quiz_db import MusicQuizDB, is_correct_guess
from utils.media.audio_fx import prepare_clip, TEMP_CLIP_PREFIX

logger = logging.getLogger(__name__)

WRONG_EMOJI = '❌'
CORRECT_EMOJI = '✅'

class MusicGuess(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}
        # Per-session song tracking (two-set approach for efficient selection)
        self.played_songs: set = set()
        self.available_songs: set = set()

    # ── Pool management ────────────────────────────────────────────────────────

    def _refresh_available_songs(self, all_songs: list[str]) -> None:
        if not self.available_songs:
            self.available_songs = set(all_songs)
            self.played_songs.clear()
            logger.info("Music: All songs played, resetting song pool.")

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
        if game['timer_task'] and game['timer_task'] != current_task:
            game['timer_task'].cancel()

        if game['voice_client'] and game['voice_client'].is_connected():
            game['voice_client'].stop()
            await game['voice_client'].disconnect()

        await asyncio.sleep(0.5)

        try:
            if game['clip_path'] and os.path.exists(game['clip_path']):
                os.remove(game['clip_path'])
        except OSError as e:
            logger.warning("Failed to remove temp file %s: %s", game['clip_path'], e)

        for msg in game['wrong_reactions']:
            try:
                await msg.remove_reaction(WRONG_EMOJI, self.bot.user)
            except discord.HTTPException:
                pass

    async def end_game_timer(self, channel, channel_id: int):
        await asyncio.sleep(GUESS_TIME_LIMIT)
        if channel_id in self.active_games:
            game = self.active_games[channel_id]
            await channel.send(
                f"Hết giờ rồi! ⏰ Đáp án chính xác là: **{game['display_answer']}**"
            )
            await self.cleanup_game(channel_id)

    # ── Core game logic ────────────────────────────────────────────────────────

    async def start_game_logic(self, interaction_or_ctx, variant_mode: bool = False):
        """Core game logic shared between slash and prefix commands."""
        if isinstance(interaction_or_ctx, discord.Interaction):
            interaction = interaction_or_ctx
            user = interaction.user
            channel = interaction.channel
            await interaction.response.defer()

            async def send_msg(content, **kwargs):
                if 'delete_after' in kwargs:
                    del kwargs['delete_after']
                    kwargs.setdefault('ephemeral', True)
                await interaction.followup.send(content, **kwargs)
        else:
            ctx = interaction_or_ctx
            user = ctx.author
            channel = ctx.channel

            async def send_msg(content, **kwargs):
                await ctx.send(content, **kwargs)

        if channel.id in self.active_games:
            await send_msg("Kênh này đang có người thử tài rồi. Vào chơi cùng họ đi!", delete_after=10)
            return

        if not user.voice:
            await send_msg("Mời bạn vào kênh voice để chơi nhé!", delete_after=10)
            return

        # ── Scan song files ─────────────────────────────────────────────────
        try:
            audio_dir = str(AUDIO_DIR)
            if not os.path.exists(audio_dir):
                os.makedirs(audio_dir)
            song_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav', '.m4a', '.ogg'))]
            if not song_files:
                await send_msg(f"Không tìm thấy bài hát nào trong thư mục `{audio_dir}`.")
                return
        except Exception as e:
            logger.error("Error reading music directory: %s", e)
            await send_msg(f"Lỗi đọc thư mục nhạc: {e}")
            return

        variant = random.choice(['fast', 'slow', 'reverse']) if variant_mode else None

        # Sync pool with current files
        song_files_set = set(song_files)
        self.available_songs &= song_files_set
        self.played_songs    &= song_files_set
        if not self.available_songs:
            self._refresh_available_songs(song_files)

        # ── Pick a song ─────────────────────────────────────────────────────
        chosen_file = None
        clip_path   = None
        effect_name = None

        for _ in range(5):
            if not self.available_songs:
                await send_msg("Không có bài hát nào có thể phát được.")
                return
            chosen_file = random.choice(list(self.available_songs))
            full_path   = os.path.join(audio_dir, chosen_file)
            clip_path, effect_name = await self.bot.loop.run_in_executor(
                None, prepare_clip, full_path, variant
            )
            if clip_path is not None:
                break
            self.available_songs.discard(chosen_file)
            if not self.available_songs:
                self._refresh_available_songs(song_files)

        if chosen_file:
            self.available_songs.discard(chosen_file)
            self.played_songs.add(chosen_file)

        if clip_path is None:
            await send_msg("Lỗi kỹ thuật khi xử lý bài hát.")
            return

        # ── Look up song titles ─────────────────────────────────────────────
        db = MusicQuizDB.get_instance()
        info           = db.get_song_info(chosen_file)
        display_answer = db.build_display_answer(info)
        norm_targets   = db.build_norm_targets(info)

        if not norm_targets:
            from utils.data.music_quiz_db import normalize
            # No known title — fall back to filename stem so the game can still work
            stem = os.path.splitext(chosen_file)[0]
            norm_targets = [normalize(stem)]
            logger.warning("Music: No title found for song index %s; using filename as answer.", stem)

        # ── Connect to voice ────────────────────────────────────────────────
        try:
            voice_client = await user.voice.channel.connect()
        except discord.errors.ClientException:
            voice_client = user.guild.voice_client
            if voice_client and voice_client.channel != user.voice.channel:
                await voice_client.move_to(user.voice.channel)
            elif not voice_client:
                await send_msg("Bot đang bị kẹt voice. Hãy kick bot ra.")
                return
        except Exception as e:
            logger.error("Voice connection error: %s", e)
            await send_msg(f"Lỗi vào voice: {e}")
            if clip_path and os.path.exists(clip_path):
                os.remove(clip_path)
            return

        timer_task = self.bot.loop.create_task(self.end_game_timer(channel, channel.id))

        self.active_games[channel.id] = {
            'norm_targets':   norm_targets,    # normalized strings to match against
            'display_answer': display_answer,  # shown on reveal
            'info':           info,            # full title dict for rich embeds
            'guesses':        {},
            'wrong_reactions': [],
            'voice_client':   voice_client,
            'clip_path':      clip_path,
            'timer_task':     timer_task,
        }

        mode_text = f"\n(Chế độ: {effect_name})" if variant_mode else ""
        await send_msg(
            f"**Đoán Tên Bài Hát!** 🎧{mode_text}\n"
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

    @commands.command(name='songguess', aliases=['sg'])
    async def guess_music(self, ctx):
        await self.start_game_logic(ctx, variant_mode=False)

    @commands.command(name='songguessv', aliases=['sgv'])
    async def guess_music_variant(self, ctx):
        await self.start_game_logic(ctx, variant_mode=True)

    @app_commands.command(name="songguess", description="Bắt đầu game đoán bài hát!")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Bình thường", value="normal"),
        app_commands.Choice(name="Khó (Hiệu ứng)", value="hard"),
    ])
    async def slash_songguess(self, interaction: discord.Interaction, mode: str = "normal"):
        await self.start_game_logic(interaction, variant_mode=(mode == "hard"))

    # ── Message listener ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.content.lower().startswith('-g '):
            return

        channel_id = message.channel.id
        if channel_id not in self.active_games:
            return

        game    = self.active_games[channel_id]
        user_id = message.author.id

        if game['guesses'].get(user_id, 0) >= MAX_GUESSES:
            return

        guess_input = message.content[3:].strip()
        if not guess_input:
            return

        if is_correct_guess(guess_input, game['norm_targets']):
            asyncio.create_task(message.add_reaction(CORRECT_EMOJI))

            info   = game['info']
            reveal = MusicQuizDB.build_reveal(info)
            await message.reply(
                f"Chính xác! 🎉 {message.author.mention} giỏi quá!\n{reveal}"
            )
            await self.cleanup_game(channel_id)
        else:
            game['guesses'][user_id] = game['guesses'].get(user_id, 0) + 1
            asyncio.create_task(message.add_reaction(WRONG_EMOJI))
            game['wrong_reactions'].append(message)

            if game['guesses'][user_id] >= MAX_GUESSES:
                await message.reply("Tiếc quá, cậu hết lượt đoán rồi!", delete_after=5)

    # ── Error handlers ─────────────────────────────────────────────────────────

    @guess_music.error
    @guess_music_variant.error
    async def guess_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Đang hồi chiêu: {error.retry_after:.1f}s", delete_after=10)


async def setup(bot):
    await bot.add_cog(MusicGuess(bot))