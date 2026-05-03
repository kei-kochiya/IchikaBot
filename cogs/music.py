import discord
from discord.ext import commands
from discord import app_commands
import os
import random
import asyncio
import logging
import glob
import re
from pydub import AudioSegment
from pydub.effects import speedup
from config import AUDIO_DIR, TEMP_DIR, GUESS_TIME_LIMIT, MAX_GUESSES, SONG_CLIP_DURATION, SONG_SAFE_ZONE

logger = logging.getLogger(__name__)

TEMP_CLIP_PREFIX = "temp_guess_clip_"
WRONG_EMOJI = '❌'
CORRECT_EMOJI = '✅'


class MusicGuess(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}
        # Per-session song tracking (two-set approach for efficient selection)
        self.played_songs = set()      # Songs that have been played this session
        self.available_songs = set()   # Songs that haven't been played yet

    def _refresh_available_songs(self, all_songs: list[str]) -> None:
        """Refresh available songs pool when all songs have been played."""
        if not self.available_songs:
            # Reset: move all songs back to available
            self.available_songs = set(all_songs)
            self.played_songs.clear()
            logger.info("Music: All songs played, resetting song pool.")

    async def cog_load(self):
        """Clean up leftover temp files from previous runs."""
        logger.info("Music: Checking for leftover temp files...")
        count = 0
        
        # Clean from the dedicated temp directory
        for file in TEMP_DIR.glob(f"{TEMP_CLIP_PREFIX}*.mp3"):
            try:
                file.unlink()
                count += 1
            except OSError as e:
                logger.warning(f"Could not remove {file}: {e}")
        
        # Also clean any in root (from old version)
        for file in glob.glob(f"./{TEMP_CLIP_PREFIX}*.mp3"):
            try:
                os.remove(file)
                count += 1
            except OSError as e:
                logger.warning(f"Could not remove legacy temp file {file}: {e}")
        
        if count > 0:
            logger.info(f"Music: Cleaned up {count} temp files.")

    def clean_answer(self, filename: str) -> str:
        """Clean filename to create answer string - trim, lowercase, remove special chars."""
        name_without_ext = os.path.splitext(filename)[0]
        # Remove special characters, keep only alphanumeric and spaces
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', name_without_ext)
        return cleaned.strip().lower()

    def check_answer(self, guess: str, correct_answer: str, full_name: str) -> bool:
        """Check if guess matches the answer."""
        # Remove special characters, keep only alphanumeric and spaces
        guess_clean = re.sub(r'[^a-zA-Z0-9\s]', '', guess).strip().lower()
        
        # Exact match
        if guess_clean == correct_answer:
            return True
        
        # Partial match (at least 3 chars and is substring)
        if len(guess_clean) >= 3:
            if guess_clean in correct_answer or correct_answer in guess_clean:
                return True
            # Also check against full name (cleaned)
            full_clean = re.sub(r'[^a-zA-Z0-9\s]', '', full_name).strip().lower()
            if guess_clean in full_clean or full_clean in guess_clean:
                return True
        
        return False

    def prepare_clip(self, file_path: str, variant: str | None = None) -> tuple[str | None, str | None]:
        """Prepare audio clip with optional effects."""
        try:
            song = AudioSegment.from_file(file_path)
        except Exception as e:
            logger.error(f"Failed to load audio file: {e}")
            return None, None

        duration_ms = len(song)
        min_start = SONG_SAFE_ZONE
        max_start = duration_ms - SONG_SAFE_ZONE - SONG_CLIP_DURATION

        if min_start >= max_start:
            start_time = 0
        else:
            start_time = random.randint(min_start, max_start)
        
        end_time = start_time + SONG_CLIP_DURATION
        clip = song[start_time:end_time]
        
        effect_name = "Bình thường"
        if variant == 'fast':
            clip = speedup(clip, playback_speed=1.5)
            effect_name = "Tua nhanh 1.5x ⏩"
        elif variant == 'slow':
            clip = clip._spawn(clip.raw_data, overrides={"frame_rate": int(clip.frame_rate * 0.75)})
            effect_name = "Tua chậm 0.75x ⏪"
        elif variant == 'reverse':
            clip = clip.reverse()
            effect_name = "Phát ngược 🔄"
        
        # Save to dedicated temp directory
        temp_filename = TEMP_DIR / f"{TEMP_CLIP_PREFIX}{random.randint(1000, 9999)}.mp3"
        clip.export(str(temp_filename), format="mp3")
        return str(temp_filename), effect_name

    async def cleanup_game(self, channel_id: int):
        """Clean up game resources."""
        if channel_id not in self.active_games:
            return

        game_data = self.active_games.pop(channel_id)
        
        current_task = asyncio.current_task()
        if game_data['timer_task'] and game_data['timer_task'] != current_task:
            game_data['timer_task'].cancel()

        if game_data['voice_client'] and game_data['voice_client'].is_connected():
            game_data['voice_client'].stop()
            await game_data['voice_client'].disconnect()
            
        await asyncio.sleep(0.5)

        try:
            clip_path = game_data['clip_path']
            if clip_path and os.path.exists(clip_path):
                os.remove(clip_path)
        except OSError as e:
            logger.warning(f"Failed to remove temp file {game_data['clip_path']}: {e}")
            
        for msg in game_data['wrong_reactions']:
            try:
                await msg.remove_reaction(WRONG_EMOJI, self.bot.user)
            except discord.HTTPException:
                pass  # Reaction already removed or message deleted

    async def end_game_timer(self, channel, channel_id: int):
        """Timer that ends the game when time runs out."""
        await asyncio.sleep(GUESS_TIME_LIMIT)
        if channel_id in self.active_games:
            game_data = self.active_games[channel_id]
            await channel.send(f"Hết giờ rồi! ⏰ Đáp án chính xác là: **{game_data['full_answer']}**")
            await self.cleanup_game(channel_id)

    async def start_game_logic(self, interaction_or_ctx, variant_mode: bool = False):
        """Core game logic shared between command types."""
        if isinstance(interaction_or_ctx, discord.Interaction):
            interaction = interaction_or_ctx
            user = interaction.user
            channel = interaction.channel
            await interaction.response.defer()
            async def send_msg(content, **kwargs):
                # Webhook.send() doesn't support delete_after; use ephemeral instead
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

        try:
            audio_dir = str(AUDIO_DIR)
            if not os.path.exists(audio_dir):
                os.makedirs(audio_dir)
            
            song_files = [f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav', '.m4a', '.ogg'))]
            if not song_files:
                await send_msg(f"Không tìm thấy bài hát nào trong thư mục `{audio_dir}`.")
                return
        except Exception as e:
            logger.error(f"Error reading music directory: {e}")
            await send_msg(f"Lỗi đọc thư mục nhạc: {e}")
            return

        variant = random.choice(['fast', 'slow', 'reverse']) if variant_mode else None
        
        # Initialize or sync available_songs with current song files
        song_files_set = set(song_files)
        # Remove any songs that no longer exist from our tracking sets
        self.available_songs &= song_files_set
        self.played_songs &= song_files_set
        
        # If available_songs is empty, refresh the pool
        if not self.available_songs:
            self._refresh_available_songs(song_files)
        
        chosen_file = None
        clip_path = None
        effect_name = None
        
        attempts = 0
        while clip_path is None and attempts < 5:
            # Choose from available songs only
            if not self.available_songs:
                # Edge case: all songs failed to process
                await send_msg("Không có bài hát nào có thể phát được.")
                return
            
            chosen_file = random.choice(list(self.available_songs))
            full_path = os.path.join(audio_dir, chosen_file)
            clip_path, effect_name = await self.bot.loop.run_in_executor(
                None, self.prepare_clip, full_path, variant
            )
            
            if clip_path is None:
                # Remove problematic song from available pool for this attempt
                self.available_songs.discard(chosen_file)
                if not self.available_songs:
                    self._refresh_available_songs(song_files)
            
            attempts += 1
        
        # Mark the chosen song as played
        if chosen_file:
            self.available_songs.discard(chosen_file)
            self.played_songs.add(chosen_file)

        if clip_path is None:
            await send_msg("Lỗi kỹ thuật khi xử lý bài hát.")
            return

        try:
            voice_channel = user.voice.channel
            voice_client = await voice_channel.connect()
        except discord.errors.ClientException:
            voice_client = user.guild.voice_client
            if voice_client and voice_client.channel != voice_channel:
                 await voice_client.move_to(voice_channel)
            elif not voice_client:
                 await send_msg("Bot đang bị kẹt voice. Hãy kick bot ra.")
                 return
        except Exception as e:
            logger.error(f"Voice connection error: {e}")
            await send_msg(f"Lỗi vào voice: {e}")
            if clip_path and os.path.exists(clip_path): 
                os.remove(clip_path)
            return

        full_answer_name = os.path.splitext(chosen_file)[0]
        correct_answer = self.clean_answer(chosen_file)
        
        timer_task = self.bot.loop.create_task(self.end_game_timer(channel, channel.id))

        self.active_games[channel.id] = {
            'answer': correct_answer,
            'full_answer': full_answer_name,
            'guesses': {}, 
            'wrong_reactions': [],
            'voice_client': voice_client,
            'clip_path': clip_path,
            'timer_task': timer_task
        }

        mode_text = f"\n(Chế độ: {effect_name})" if variant_mode else ""
        await send_msg(f"**Đoán Tên Bài Hát!** 🎧{mode_text}\nThời gian: {GUESS_TIME_LIMIT}s | Số lượt đoán: {MAX_GUESSES}\nGõ `-g [tên bài hát]` để trả lời!")
        
        try:
            voice_client.play(discord.FFmpegPCMAudio(clip_path))
        except Exception as e:
            logger.error(f"Playback error: {e}")
            await send_msg("Lỗi khi phát nhạc.")
            await self.cleanup_game(channel.id)

    # --- COMMANDS ---
    @commands.command(name='songguess', aliases=['sg'])
    async def guess_music(self, ctx):
        await self.start_game_logic(ctx, variant_mode=False)

    @commands.command(name='songguessv', aliases=['sgv'])
    async def guess_music_variant(self, ctx):
        await self.start_game_logic(ctx, variant_mode=True)

    @app_commands.command(name="songguess", description="Bắt đầu game đoán bài hát!")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Bình thường", value="normal"),
        app_commands.Choice(name="Khó (Hiệu ứng)", value="hard")
    ])
    async def slash_songguess(self, interaction: discord.Interaction, mode: str = "normal"):
        variant_mode = (mode == "hard")
        await self.start_game_logic(interaction, variant_mode=variant_mode)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.content.lower().startswith('-g '):
            return

        channel_id = message.channel.id
        if channel_id not in self.active_games:
            return

        game_data = self.active_games[channel_id]
        user_id = message.author.id
        
        if game_data['guesses'].get(user_id, 0) >= MAX_GUESSES:
            return

        guess_input = message.content[3:].strip()
        if not guess_input:
            return
            
        is_correct = self.check_answer(guess_input, game_data['answer'], game_data['full_answer'])
        
        if is_correct:
            await message.add_reaction(CORRECT_EMOJI)
            await message.reply(f"Chính xác! 🎉 {message.author.mention} giỏi quá!\nBài hát là: **{game_data['full_answer']}**")
            await self.cleanup_game(channel_id)
        else:
            game_data['guesses'][user_id] = game_data['guesses'].get(user_id, 0) + 1
            await message.add_reaction(WRONG_EMOJI)
            game_data['wrong_reactions'].append(message)

            if game_data['guesses'][user_id] >= MAX_GUESSES:
                await message.reply("Tiếc quá, cậu hết lượt đoán rồi!", delete_after=5)

    @guess_music.error
    @guess_music_variant.error
    async def guess_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Đang hồi chiêu: {error.retry_after:.1f}s", delete_after=10)


async def setup(bot):
    await bot.add_cog(MusicGuess(bot))