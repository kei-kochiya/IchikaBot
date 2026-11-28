"""Song jacket guessing minigame (`/jacketguess`)."""

import asyncio
import contextlib
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from config import SONG_GUESS_DURATION
from utils.data.song_data import song_data
from utils.game.guess_engine import (
    GUESS_MODES,
    GUESS_PREFIX,
    MODE_COLORS,
    MODE_LABELS,
    acquire_channel,
    is_channel_active,
    release_channel,
    run_guess_round,
)
from utils.game.song_guess_media import build_song_answers, process_jacket_image_sync
from utils.media.image_helper import get_song_jacket_path

logger = logging.getLogger(__name__)

JACKET_MODE_CHOICES = [
    app_commands.Choice(name="Dễ: cắt rộng", value="easy"),
    app_commands.Choice(name="Thường: cắt ngẫu nhiên", value="normal"),
    app_commands.Choice(name="Khó: hiệu ứng ngẫu nhiên", value="hard"),
]


class JacketGuessCog(commands.Cog):
    """Slash command for guessing songs from cropped/effected jacket art."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="jacketguess", description="Đoán tên bài hát qua ảnh bìa (Jacket)!")
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
    @app_commands.describe(mode="Độ khó (mặc định: Thường)")
    @app_commands.choices(mode=JACKET_MODE_CHOICES)
    async def jacket_guess(self, interaction: discord.Interaction, mode: str = "normal"):
        channel_id = interaction.channel_id
        if channel_id is None:
            await interaction.response.send_message(
                "Lệnh này chỉ dùng được trong kênh văn bản.", ephemeral=True
            )
            return

        if not song_data.songs_jp:
            await interaction.response.send_message(
                "Dữ liệu bài hát chưa sẵn sàng. Vui lòng thử lại sau ít phút.", ephemeral=True
            )
            return

        if is_channel_active(channel_id):
            await interaction.response.send_message(
                "Ai đó đang thử tài rồi, hãy chơi cùng họ nhé!", ephemeral=True
            )
            return

        mode = mode if mode in GUESS_MODES else "normal"
        token = acquire_channel(channel_id)
        try:
            await interaction.response.defer()
            try:
                chosen_song = None
                jacket_path = None
                for song in random.sample(song_data.songs_jp, min(3, len(song_data.songs_jp))):
                    async with asyncio.timeout(12.0):
                        path = await get_song_jacket_path(
                            int(song["id"]), song.get("assetbundleName")
                        )
                    if path:
                        chosen_song = song
                        jacket_path = path
                        break

                if not chosen_song or not jacket_path:
                    await interaction.followup.send(
                        "Lỗi tải ảnh bìa bài hát. Vui lòng thử lại sau.", ephemeral=True
                    )
                    return

                puzzle_io, effect_label = await asyncio.to_thread(
                    process_jacket_image_sync, jacket_path, mode
                )
                if not puzzle_io:
                    await interaction.followup.send(
                        "Lỗi xử lý ảnh bìa bài hát. Vui lòng thử lại sau.", ephemeral=True
                    )
                    return

                display_title, norm_answers, raw_jp_answers = build_song_answers(chosen_song)
                composer = str(chosen_song.get("composer") or "")
                logger.debug("JacketGuess answer: %s", display_title)

                effect_note = f" ({effect_label})" if mode == "hard" and effect_label else ""
                embed = discord.Embed(
                    title=f"Đoán Jacket bài hát · {MODE_LABELS[mode]}{effect_note}",
                    description=f"Gõ `{GUESS_PREFIX}[tên bài hát]` để đoán. Bạn có {SONG_GUESS_DURATION}s.",
                    color=MODE_COLORS[mode],
                )
                embed.set_image(url="attachment://jacket_guess.jpg")

                fields = [("Sáng tác", composer)] if composer else []
                await run_guess_round(
                    self.bot,
                    interaction,
                    channel_id,
                    puzzle_embed=embed,
                    puzzle_file=discord.File(puzzle_io, filename="jacket_guess.jpg"),
                    norm_answers=norm_answers,
                    answer_label=display_title,
                    reveal_path=jacket_path,
                    reveal_fields=fields,
                    raw_jp_answers=raw_jp_answers,
                )
            except Exception as e:
                logger.error("JacketGuess error: %s", e)
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send(
                        "Ván đoán jacket gặp lỗi và đã dừng. Bạn thử lại nhé.", ephemeral=True
                    )
        finally:
            release_channel(channel_id, token)


async def setup(bot):
    await bot.add_cog(JacketGuessCog(bot))
