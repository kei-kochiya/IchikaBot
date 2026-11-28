"""Shared `-g` text-channel guessing round engine, Give Up view, and cross-cog channel lock."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

import discord

from config import SONG_GUESS_DURATION
from utils.core.tasks import react_in_background
from utils.data.music_quiz_db import is_correct_guess
from utils.game.song_guess_media import is_song_guess_correct

logger = logging.getLogger(__name__)

GUESS_PREFIX = "-g "
MAX_FAILS = 4
GUESS_MODES = ("easy", "normal", "hard")
MODE_LABELS = {"easy": "Dễ", "normal": "Thường", "hard": "Khó"}
MODE_COLORS = {"easy": 0x2ECC71, "normal": 0xF1C40F, "hard": 0x9B59B6}

_OUTCOME_META = {
    "failed": (f"Game Over. Bạn chỉ được phép đoán sai {MAX_FAILS} lần!", 0xE74C3C),
    "gave_up": ("Đã bỏ cuộc!", 0xE74C3C),
    "timeout": ("Hết giờ rồi!", 0xE74C3C),
}

# Shared across CardGuessCog, JacketGuessCog, and ChartGuessCog so two `-g` games
# can never overlap in the same text channel.
active_channels: dict[int, float] = {}
_channel_tokens: dict[int, object] = {}


def is_channel_active(channel_id: int) -> bool:
    """Return True if a `-g` game is running in *channel_id*, auto-recovering stale locks."""
    if channel_id not in active_channels:
        return False
    start_time = active_channels[channel_id]
    now = asyncio.get_running_loop().time()
    stale_after = SONG_GUESS_DURATION + 35.0
    if now - start_time > stale_after:
        logger.warning(
            "Guess game in channel %s hung or timed out (%0.1fs ago). Auto-recovering channel.",
            channel_id,
            now - start_time,
        )
        active_channels.pop(channel_id, None)
        _channel_tokens.pop(channel_id, None)
        return False
    return True


def acquire_channel(channel_id: int) -> object:
    """Claim *channel_id* for a new guessing round and return its ownership token."""
    token = object()
    active_channels[channel_id] = asyncio.get_running_loop().time()
    _channel_tokens[channel_id] = token
    return token


def release_channel(channel_id: int, token: object) -> None:
    """Release *channel_id* only if *token* still owns the active lock."""
    if _channel_tokens.get(channel_id) is token:
        _channel_tokens.pop(channel_id, None)
        active_channels.pop(channel_id, None)


class GiveUpView(discord.ui.View):
    """View with a working Give Up button."""

    def __init__(self):
        super().__init__(timeout=SONG_GUESS_DURATION + 5)
        self.gave_up = False
        self.give_up_event = asyncio.Event()
        self.message = None

    @discord.ui.button(label="Give Up", style=discord.ButtonStyle.danger)
    async def give_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle give up button click."""
        self.gave_up = True
        self.give_up_event.set()
        button.disabled = True
        with contextlib.suppress(discord.HTTPException):
            await interaction.response.defer()

    def disable_all(self):
        """Disable all buttons."""
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        """Handle view timeout."""
        self.disable_all()
        if self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)


async def run_guess_round(
    bot,
    interaction: discord.Interaction,
    channel_id: int,
    *,
    puzzle_embed: discord.Embed,
    puzzle_file: discord.File,
    norm_answers: list[str],
    answer_label: str,
    reveal_path: str | None,
    reveal_fields: list[tuple[str, str]] | None = None,
    raw_jp_answers: list[str] | None = None,
) -> None:
    """Run the interactive `-g` guess loop, Give Up handling, and reveal message."""
    view = GiveUpView()
    msg = None
    try:
        msg = await interaction.followup.send(embed=puzzle_embed, file=puzzle_file, view=view)
        view.message = msg

        winner = None
        reason = "timeout"
        fails = 0

        def check(m):
            return (
                m.channel.id == channel_id
                and not m.author.bot
                and m.content.lower().startswith(GUESS_PREFIX)
            )

        end_time = asyncio.get_running_loop().time() + SONG_GUESS_DURATION

        while not view.gave_up:
            remaining = end_time - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            msg_task = asyncio.create_task(bot.wait_for("message", check=check, timeout=remaining))
            give_up_task = asyncio.create_task(view.give_up_event.wait())
            done, pending = await asyncio.wait(
                (msg_task, give_up_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

            if msg_task in done:
                try:
                    guess_msg = msg_task.result()
                except TimeoutError:
                    break
                guess = guess_msg.content[len(GUESS_PREFIX) :].strip()

                matched = (
                    is_song_guess_correct(guess, norm_answers, raw_jp_answers)
                    if raw_jp_answers is not None
                    else is_correct_guess(guess, norm_answers)
                )
                if matched:
                    winner = guess_msg.author
                    reason = "win"
                    react_in_background(guess_msg, "✅")
                    break
                fails += 1
                react_in_background(guess_msg, "❌")
                if fails >= MAX_FAILS:
                    reason = "failed"
                    break
            elif view.gave_up:
                reason = "gave_up"
                break

        if view.gave_up and reason != "win":
            reason = "gave_up"

        result_embed = discord.Embed(description=f"Đáp án: **{answer_label}**")
        for field_name, field_val in reveal_fields or ():
            if field_val:
                result_embed.add_field(name=field_name, value=field_val, inline=True)

        if reason == "win":
            result_embed.title = f"Đúng rồi! Xin chúc mừng {winner.display_name}"
            result_embed.color = 0x2ECC71
        else:
            result_embed.title, result_embed.color = _OUTCOME_META[reason]

        send_kwargs: dict = {"embed": result_embed}
        if reveal_path:
            ext = Path(reveal_path).suffix or ".webp"
            reveal_name = f"reveal{ext}"
            result_embed.set_image(url=f"attachment://{reveal_name}")
            send_kwargs["file"] = discord.File(reveal_path, filename=reveal_name)

        view.disable_all()
        view.stop()
        with contextlib.suppress(discord.HTTPException):
            await interaction.followup.send(**send_kwargs)
        if msg:
            with contextlib.suppress(discord.HTTPException):
                await msg.edit(view=view)
    finally:
        if not view.is_finished():
            view.disable_all()
            view.stop()
            if msg:
                with contextlib.suppress(discord.HTTPException):
                    await msg.edit(view=view)
