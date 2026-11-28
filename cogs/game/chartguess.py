"""Static chart slice guessing minigame (`/chartguess`, Master & Append only)."""

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
from utils.game.song_guess_media import build_song_answers, crop_chart_image_sync
from utils.media.image_helper import get_song_chart_path, get_song_jacket_path

logger = logging.getLogger(__name__)

CHART_DIFF_CHOICES = [
    app_commands.Choice(name="Master", value="master"),
    app_commands.Choice(name="Append", value="append"),
]
CHART_MODE_CHOICES = [
    app_commands.Choice(name="Dễ: 2 cột chart", value="easy"),
    app_commands.Choice(name="Thường: 1 cột chart", value="normal"),
    app_commands.Choice(name="Khó: đoạn ngắn 1 cột", value="hard"),
]
CHART_DIFF_COLORS = {"master": 0x9B59B6, "append": 0xE879F9}


class ChartGuessCog(commands.Cog):
    """Slash command for guessing songs from spoiler-free Master/Append chart slices."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="chartguess", description="Đoán tên bài hát qua một đoạn chart (Master / Append)!"
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
    @app_commands.describe(
        difficulty="Độ khó chart muốn đoán (mặc định: Master)",
        mode="Kích thước đoạn chart cắt (mặc định: Thường)",
    )
    @app_commands.choices(difficulty=CHART_DIFF_CHOICES, mode=CHART_MODE_CHOICES)
    async def chart_guess(
        self,
        interaction: discord.Interaction,
        difficulty: str = "master",
        mode: str = "normal",
    ):
        channel_id = interaction.channel_id
        if channel_id is None:
            await interaction.response.send_message(
                "Lệnh này chỉ dùng được trong kênh văn bản.", ephemeral=True
            )
            return

        diff = difficulty.lower() if difficulty.lower() in ("master", "append") else "master"
        mode = mode if mode in GUESS_MODES else "normal"

        eligible_songs = [
            s
            for s in song_data.songs_jp
            if diff in (song_data.difficulties.get(int(s["id"])) or {})
        ]
        if not eligible_songs:
            await interaction.response.send_message(
                f"Chưa có dữ liệu chart **{diff.capitalize()}**. Vui lòng thử lại sau ít phút.",
                ephemeral=True,
            )
            return

        if is_channel_active(channel_id):
            await interaction.response.send_message(
                "Ai đó đang thử tài rồi, hãy chơi cùng họ nhé!", ephemeral=True
            )
            return

        token = acquire_channel(channel_id)
        try:
            await interaction.response.defer()
            try:
                chosen_song = None
                chart_path = None
                for song in random.sample(eligible_songs, min(3, len(eligible_songs))):
                    async with asyncio.timeout(15.0):
                        path = await get_song_chart_path(int(song["id"]), diff)
                    if path:
                        chosen_song = song
                        chart_path = path
                        break

                if not chosen_song or not chart_path:
                    await interaction.followup.send(
                        "Lỗi tải ảnh chart từ máy chủ. Vui lòng thử lại sau.", ephemeral=True
                    )
                    return

                puzzle_io, jacket_path = await asyncio.gather(
                    asyncio.to_thread(crop_chart_image_sync, chart_path, mode),
                    get_song_jacket_path(
                        int(chosen_song["id"]), chosen_song.get("assetbundleName")
                    ),
                )
                if not puzzle_io:
                    await interaction.followup.send(
                        "Lỗi cắt ảnh chart. Vui lòng thử lại sau.", ephemeral=True
                    )
                    return

                display_title, norm_answers, raw_jp_answers = build_song_answers(chosen_song)
                diff_info = (song_data.difficulties.get(int(chosen_song["id"])) or {}).get(diff, {})
                level = diff_info.get("level")
                notes = diff_info.get("noteCount")
                chart_meta = diff.capitalize()
                if level:
                    chart_meta += f" Lv.{level}"
                if notes:
                    chart_meta += f" ({notes:,} notes)"

                logger.debug("ChartGuess answer: %s (%s)", display_title, chart_meta)

                embed = discord.Embed(
                    title=f"Đoán Chart ({diff.capitalize()}) · {MODE_LABELS[mode]}",
                    description=f"Gõ `{GUESS_PREFIX}[tên bài hát]` để đoán. Bạn có {SONG_GUESS_DURATION}s.",
                    color=CHART_DIFF_COLORS.get(diff, MODE_COLORS[mode]),
                )
                embed.set_image(url="attachment://chart_guess.jpg")

                await run_guess_round(
                    self.bot,
                    interaction,
                    channel_id,
                    puzzle_embed=embed,
                    puzzle_file=discord.File(puzzle_io, filename="chart_guess.jpg"),
                    norm_answers=norm_answers,
                    answer_label=display_title,
                    reveal_path=jacket_path,
                    reveal_fields=[("Chart", chart_meta)],
                    raw_jp_answers=raw_jp_answers,
                )
            except Exception as e:
                logger.error("ChartGuess error: %s", e)
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send(
                        "Ván đoán chart gặp lỗi và đã dừng. Bạn thử lại nhé.", ephemeral=True
                    )
        finally:
            release_channel(channel_id, token)


async def setup(bot):
    await bot.add_cog(ChartGuessCog(bot))
