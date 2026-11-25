"""Helper utilities for MusicGuess voice quiz: audio scanning, temp cleanup, and voice connect."""

import contextlib
import glob
import logging
import os
from pathlib import Path

import discord

from config import AUDIO_DIR, TEMP_DIR
from utils.media.audio_fx import TEMP_CLIP_PREFIX

logger = logging.getLogger(__name__)

_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg")


def scan_audio_files(audio_dir: Path | str = AUDIO_DIR) -> tuple[Path, list[str]]:
    """Scan *audio_dir* (with case-insensitive fallback on Linux) for playable audio files."""
    audio_path = Path(audio_dir)
    if not audio_path.exists():
        parent = audio_path.parent
        if parent.exists():
            for entry in parent.iterdir():
                if entry.name.lower() == audio_path.name.lower() and entry.is_dir():
                    audio_path = entry
                    break
    if not audio_path.exists():
        audio_path.mkdir(parents=True, exist_ok=True)

    song_files: list[str] = []
    for root, _, files in os.walk(str(audio_path)):
        for filename in files:
            if filename.lower().endswith(_AUDIO_EXTS):
                song_files.append(os.path.relpath(os.path.join(root, filename), str(audio_path)))
    return audio_path, song_files


def sweep_leftover_temp_clips() -> int:
    """Delete leftover temp clip files from previous runs; return count removed."""
    count = 0
    for file in TEMP_DIR.glob(f"{TEMP_CLIP_PREFIX}*"):
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
    return count


async def remove_wrong_reactions(
    messages: list[discord.Message], emoji: str, bot_user: discord.abc.User | None
) -> None:
    """Cosmetically clear wrong-guess reactions in the background without blocking teardown."""
    if bot_user is None:
        return
    for msg in messages:
        with contextlib.suppress(discord.HTTPException):
            await msg.remove_reaction(emoji, bot_user)


async def connect_to_voice(
    guild: discord.Guild, target_channel: discord.VoiceChannel
) -> discord.VoiceClient:
    """Connect, move, or reuse the guild's voice client for *target_channel*."""
    guild_vc = guild.voice_client
    if guild_vc and guild_vc.channel == target_channel and guild_vc.is_connected():
        return guild_vc
    if guild_vc and guild_vc.channel != target_channel and guild_vc.is_connected():
        await guild_vc.move_to(target_channel)
        return guild_vc
    if guild_vc and not guild_vc.is_connected():
        await guild_vc.disconnect(force=True)
    return await target_channel.connect(self_deaf=True, timeout=20.0, reconnect=False)


def format_no_eligible_songs_message(db, song_files: list[str], pool_type: str) -> str:
    """Build a clear Vietnamese diagnostic message when no eligible songs match the DB."""
    if db.last_error:
        return f"Không đọc được `song.xlsx`: {db.last_error}"
    if len(db._db) == 0:
        return (
            "Danh sách bài hát đang trống. "
            "Vui lòng kiểm tra file `gameData/static/song.xlsx` hoặc cài `openpyxl`."
        )
    if pool_type == "comm" and len(db.get_commission_ids()) == 0:
        return (
            "`song.xlsx` chưa đánh dấu bài commission nào. "
            "Vui lòng `git pull` để nhận file `song.xlsx` mới nhất có đánh dấu commission."
        )
    sample_files = ", ".join(song_files[:3])
    pool_desc = "commission" if pool_type == "comm" else "hợp lệ"
    return (
        f"Không tìm thấy bài hát {pool_desc} nào trong thư mục nhạc.\n"
        f"Đã phát hiện {len(song_files)} file nhạc (ví dụ: `{sample_files}`), "
        f"nhưng tên file cần đặt theo ID bài hát (ví dụ: `54.mp3`, `101.mp3`)."
    )
