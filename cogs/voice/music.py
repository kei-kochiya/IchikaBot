import discord
from discord.ext import commands
from discord import app_commands
import os
import random
import asyncio
import logging
import glob
import re
from pathlib import Path
from pydub import AudioSegment
from pydub.effects import speedup
from config import AUDIO_DIR, TEMP_DIR, GUESS_TIME_LIMIT, MAX_GUESSES, SONG_CLIP_DURATION, SONG_SAFE_ZONE

logger = logging.getLogger(__name__)

TEMP_CLIP_PREFIX = "temp_guess_clip_"
WRONG_EMOJI = '❌'
CORRECT_EMOJI = '✅'

# Path to the song database spreadsheet
SONG_DB_PATH = Path(__file__).parent.parent / "gameData" / "static" / "song.xlsx"


def normalize(text: str) -> str:
    """
    Keep only alphanumeric characters, strip everything else (including spaces),
    and lowercase. Applied to both song titles and player guesses before comparison.
    """
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()


def is_correct_guess(raw_guess: str, norm_targets: list[str]) -> bool:
    """
    Check whether raw_guess matches any of the normalized target strings.

    Rules:
      - Normalize the guess the same way as the titles.
      - Exact match  → correct.
      - len(normalized_guess) >= 3 AND normalized_guess is a substring of any target → correct.
    """
    ng = normalize(raw_guess)
    if not ng:
        return False
    for target in norm_targets:
        if ng == target:
            return True
        if len(ng) >= 3 and ng in target:
            return True
    return False


class MusicGuess(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_games = {}
        # Per-session song tracking (two-set approach for efficient selection)
        self.played_songs: set = set()
        self.available_songs: set = set()
        # song_db: str(index) -> {"title_en": str|None, "romaji_title": str|None, "title_jp": str|None}
        self.song_db: dict[str, dict] = {}

    # ── Song database ──────────────────────────────────────────────────────────

    def load_song_db(self) -> None:
        """Load song.xlsx into self.song_db keyed by song index (as string)."""
        if not SONG_DB_PATH.exists():
            logger.warning("Music: song.xlsx not found at %s", SONG_DB_PATH)
            return
        try:
            import openpyxl
            wb = openpyxl.load_workbook(SONG_DB_PATH, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
        except Exception as e:
            logger.error("Music: Failed to load song.xlsx: %s", e)
            return

        if not rows:
            return

        # Detect header row: first row where column A looks like "index" (text)
        # Skip if it is a header
        start = 0
        if rows[0][0] is not None and str(rows[0][0]).lower() == 'index':
            start = 1

        db: dict[str, dict] = {}
        # Columns: 0=index, 1=title_jp, 2=title_en, 3=lyricist, 4=composer,
        #           5=arranger, 6=link, 7=romaji_title
        for row in rows[start:]:
            if not row or row[0] is None:
                continue
            idx        = str(row[0]).strip()
            title_jp   = str(row[1]).strip() if len(row) > 1 and row[1] else None
            title_en   = str(row[2]).strip() if len(row) > 2 and row[2] else None
            romaji     = str(row[7]).strip() if len(row) > 7 and row[7] else None
            # Treat empty strings as None
            title_jp   = title_jp   or None
            title_en   = title_en   or None
            romaji     = romaji     or None
            db[idx] = {"title_en": title_en, "romaji_title": romaji, "title_jp": title_jp}

        self.song_db = db
        logger.info("Music: Loaded %d songs from song.xlsx", len(db))

    def get_song_info(self, filename: str) -> dict:
        """
        Look up song info by filename.
        filename e.g. '123.mp3' → index '123'.
        Returns dict with title_en, romaji_title, title_jp (any may be None).
        """
        idx = os.path.splitext(filename)[0]
        return self.song_db.get(idx, {"title_en": None, "romaji_title": None, "title_jp": idx})

    def build_display_answer(self, info: dict) -> str:
        """Build the human-readable answer string shown on reveal."""
        parts = []
        if info.get("title_en"):
            parts.append(info["title_en"])
        if info.get("romaji_title") and info["romaji_title"] != info.get("title_en"):
            parts.append(info["romaji_title"])
        if not parts:
            # Fallback to jp title or raw index
            parts.append(info.get("title_jp") or "???")
        return " / ".join(parts)

    def build_norm_targets(self, info: dict) -> list[str]:
        """Return list of normalized strings the player may guess against."""
        targets = []
        if info.get("title_en"):
            targets.append(normalize(info["title_en"]))
        if info.get("romaji_title"):
            targets.append(normalize(info["romaji_title"]))
        return [t for t in targets if t]  # filter out empty strings

    # ── Pool management ────────────────────────────────────────────────────────

    def _refresh_available_songs(self, all_songs: list[str]) -> None:
        if not self.available_songs:
            self.available_songs = set(all_songs)
            self.played_songs.clear()
            logger.info("Music: All songs played, resetting song pool.")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def cog_load(self):
        """Load song database and clean up leftover temp files."""
        self.load_song_db()

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

    # ── Audio helpers ──────────────────────────────────────────────────────────

    def prepare_clip(self, file_path: str, variant: str | None = None) -> tuple[str | None, str | None]:
        """Prepare audio clip with optional effects."""
        try:
            song = AudioSegment.from_file(file_path)
        except Exception as e:
            logger.error("Failed to load audio file: %s", e)
            return None, None

        duration_ms = len(song)
        min_start = SONG_SAFE_ZONE
        max_start = duration_ms - SONG_SAFE_ZONE - SONG_CLIP_DURATION

        start_time = random.randint(min_start, max_start) if min_start < max_start else 0
        clip = song[start_time:start_time + SONG_CLIP_DURATION]

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

        temp_filename = TEMP_DIR / f"{TEMP_CLIP_PREFIX}{random.randint(1000, 9999)}.mp3"
        clip.export(str(temp_filename), format="mp3")
        return str(temp_filename), effect_name

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
                None, self.prepare_clip, full_path, variant
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
        info           = self.get_song_info(chosen_file)
        display_answer = self.build_display_answer(info)
        norm_targets   = self.build_norm_targets(info)

        if not norm_targets:
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
            await message.add_reaction(CORRECT_EMOJI)

            info   = game['info']
            reveal = self._build_reveal(info)
            await message.reply(
                f"Chính xác! 🎉 {message.author.mention} giỏi quá!\n{reveal}"
            )
            await self.cleanup_game(channel_id)
        else:
            game['guesses'][user_id] = game['guesses'].get(user_id, 0) + 1
            await message.add_reaction(WRONG_EMOJI)
            game['wrong_reactions'].append(message)

            if game['guesses'][user_id] >= MAX_GUESSES:
                await message.reply("Tiếc quá, cậu hết lượt đoán rồi!", delete_after=5)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_reveal(info: dict) -> str:
        """Build the reveal string shown when someone wins or time runs out."""
        lines = []
        if info.get("title_en"):
            lines.append(f"🎵 **{info['title_en']}**")
        if info.get("romaji_title") and info["romaji_title"] != info.get("title_en"):
            lines.append(f"🔤 *{info['romaji_title']}*")
        if not lines and info.get("title_jp"):
            lines.append(f"🎵 **{info['title_jp']}**")
        return "\n".join(lines) if lines else "???"

    # ── Error handlers ─────────────────────────────────────────────────────────

    @guess_music.error
    @guess_music_variant.error
    async def guess_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Đang hồi chiêu: {error.retry_after:.1f}s", delete_after=10)


async def setup(bot):
    await bot.add_cog(MusicGuess(bot))