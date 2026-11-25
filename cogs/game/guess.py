import asyncio
import contextlib
import logging
import random
from io import BytesIO
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageFilter, ImageOps

from config import SONG_GUESS_DURATION
from utils.core import database
from utils.core.tasks import react_in_background
from utils.data.card_data import card_data
from utils.data.game_data import game_data
from utils.data.music_quiz_db import is_correct_guess, normalize
from utils.game.cards import is_pre_trained_card, supports_trained_art
from utils.media.card_focus import focus_crop_box
from utils.media.image_helper import get_card_image_path, get_member_cutout_path

logger = logging.getLogger(__name__)

GUESS_PREFIX = "-g "
MAX_FAILS = 4
MAX_PUZZLE_WIDTH = 1280
CROP_SIZE = 300

# Difficulties: easy crops on the card's own character (found with its member_cutout),
# normal crops anywhere on the card, hard adds a random effect.
GUESS_MODES = ("easy", "normal", "hard")
MODE_ALIASES = {"random": "hard"}  # the old name of hard mode
DEFAULT_MODE = "easy"  # for players who never chose one with /guessmode
MODE_SETTING = "guess_mode"  # user_settings key
MODE_LABELS = {"easy": "Dễ", "normal": "Thường", "hard": "Khó"}
MODE_COLORS = {"easy": 0x2ECC71, "normal": 0xF1C40F, "hard": 0x9B59B6}
MODE_CHOICES = [
    app_commands.Choice(name="Dễ: cắt vào nhân vật", value="easy"),
    app_commands.Choice(name="Thường: cắt ngẫu nhiên", value="normal"),
    app_commands.Choice(name="Khó: hiệu ứng ngẫu nhiên", value="hard"),
]
_OUTCOME_META = {
    "failed": (f"Game Over. Bạn chỉ được phép đoán sai {MAX_FAILS} lần!", 0xE74C3C),
    "gave_up": ("Đã bỏ cuộc!", 0xE74C3C),
    "timeout": ("Hết giờ rồi!", 0xE74C3C),
}


def is_correct_name_guess(guess: str, answers: list[str]) -> bool:
    """True if guess matches an answer exactly, or is any 3+ character piece of one.

    Both sides go through the music quiz's normalize() first (Unicode fold, letters and
    digits only, lowercase), so the 3 characters are counted after normalizing: "n e" is
    only 2 and doesn't win, and "banh tao" matches the nickname "bánh táo".
    """
    return is_correct_guess(guess, [na for answer in answers if (na := normalize(answer))])


def _focus_box(img: Image.Image, cutout_path: str | None) -> tuple[int, int, int, int] | None:
    if not cutout_path:
        return None
    try:
        with Image.open(cutout_path) as cutout:
            return focus_crop_box(img, cutout, CROP_SIZE)
    except OSError as e:
        logger.warning("Guess: unusable member cutout %s: %s", cutout_path, e)
        return None


def _process_game_image_sync(
    local_path: str, mode: str, cutout_path: str | None = None
) -> tuple[BytesIO | None, str | None, str]:
    """Synchronous helper for image processing with effects.

    mode: "easy" (a crop on the card's character, located with cutout_path; without a
    usable cutout it falls back to a normal crop), "normal" (a crop anywhere) or "hard"
    (a random effect; "random" is accepted as its old name).

    Returns (puzzle_jpeg, reveal_path, effect_name).  The reveal image is the untouched
    cached card file, so it is never decoded/re-encoded or held in memory during a game.
    """
    mode = MODE_ALIASES.get(mode, mode)
    try:
        with Image.open(local_path) as img:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            w, h = img.size

            if w < CROP_SIZE or h < CROP_SIZE:
                img = img.resize((max(w, CROP_SIZE), max(h, CROP_SIZE)))
                w, h = img.size

            if mode == "hard":
                effect = random.choice(["crop_bw", "pixelate", "blur", "negative"])
            elif mode == "easy":
                effect = "focus"
            else:
                effect = "crop"

            focus = _focus_box(img, cutout_path) if effect == "focus" else None
            if effect == "focus" and focus is None:
                effect = "crop"  # no cutout or no convincing region: an ordinary crop

            if focus is not None:
                game_img = img.crop(focus)
                effect_used = "Focus"

            elif effect == "crop" or effect == "crop_bw":
                # Crop first: only the 300x300 region is ever copied/converted
                x = random.randint(0, w - CROP_SIZE)
                y = random.randint(0, h - CROP_SIZE)
                game_img = img.crop((x, y, x + CROP_SIZE, y + CROP_SIZE))
                if effect == "crop_bw":
                    game_img = ImageOps.grayscale(game_img)
                    effect_used = "Trắng đen"
                else:
                    effect_used = "Crop"

            else:
                # Whole-image effects don't need the 2520px source art: cap the output width
                # so encoding is faster and the upload to Discord is several times smaller.
                tw, th = (
                    (MAX_PUZZLE_WIDTH, round(h * MAX_PUZZLE_WIDTH / w))
                    if w > MAX_PUZZLE_WIDTH
                    else (w, h)
                )

                if effect == "pixelate":
                    # Shrink straight to 48x48 and scale back up (skips intermediate 1280px resize)
                    game_img = img.resize((48, 48), Image.NEAREST).resize((tw, th), Image.NEAREST)
                    effect_used = "Pixelate"

                elif effect == "blur":
                    # Shrink directly to quarter size, blur, then upscale (skips 1280px resize)
                    small = img.resize(
                        (max(1, tw // 4), max(1, th // 4)),
                        Image.BILINEAR,
                        reducing_gap=2.0,
                    ).filter(ImageFilter.GaussianBlur(radius=25 / 4))
                    game_img = small.resize((tw, th), Image.BILINEAR)
                    effect_used = "Blur"

                else:  # negative
                    if (tw, th) != (w, h):
                        img = img.resize((tw, th), Image.BILINEAR, reducing_gap=2.0)
                    rgb = img if img.mode == "RGB" else img.convert("RGB")
                    game_img = ImageOps.invert(rgb)
                    effect_used = "Âm bản"

            # JPEG: a 1280px effect image is ~1-2 MB as PNG but ~0.2 MB here, and the
            # upload dominates how long the round takes to appear.
            game_io = BytesIO()
            if game_img.mode not in ("RGB", "L"):
                game_img = game_img.convert("RGB")
            game_img.save(game_io, format="JPEG", quality=90)
            game_io.seek(0)

        return game_io, local_path, effect_used

    except OSError as e:
        logger.error(f"Failed to process image: {e}")
        return None, None, ""


class GuessCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels: dict[int, float] = {}
        self._channel_tokens: dict[int, object] = {}
        # References to shared singletons — no per-cog loading
        self.cards = card_data.pool_3_4

    def _is_channel_active(self, channel_id: int) -> bool:
        """Check if game is actively running in channel. Auto-recovers stale/hung channels."""
        if channel_id not in self.active_channels:
            return False
        start_time = self.active_channels[channel_id]
        now = asyncio.get_running_loop().time()
        stale_after = SONG_GUESS_DURATION + 35.0
        if now - start_time > stale_after:
            logger.warning(
                "Guess game in channel %s hung or timed out (%0.1fs ago). Auto-recovering channel.",
                channel_id,
                now - start_time,
            )
            self.active_channels.pop(channel_id, None)
            self._channel_tokens.pop(channel_id, None)
            return False
        return True

    def load_data(self):
        """Card/character data managed by shared singletons."""
        self.cards = card_data.pool_3_4

    def get_display_prefix(self, card: dict) -> str:
        return card_data.get_display_prefix(card)

    def build_answer_list(self, char_id: int | str) -> list[str]:
        char = game_data.get_character(char_id)
        if not char:
            return []
        fn = char.get("firstName", "").lower()
        gn = char.get("givenName", "").lower()
        answers = [fn, gn, f"{fn} {gn}".strip(), f"{gn} {fn}".strip()]
        for nick in game_data.nicknames.get(str(char_id), []):
            answers.append(nick.lower())
        return [a for a in dict.fromkeys(answers) if a]

    async def process_game_image(
        self, asset_name: str, is_trained: bool, mode: str
    ) -> tuple[BytesIO | None, str | None, str]:
        """Process card image for guessing game in executor. Returns (game_img_io, reveal_path, effect_name)."""
        try:
            async with asyncio.timeout(15.0):
                is_easy = MODE_ALIASES.get(mode, mode) == "easy"
                if is_easy:
                    local_path, cutout_path = await asyncio.gather(
                        get_card_image_path(asset_name, is_trained),
                        get_member_cutout_path(asset_name, is_trained),
                    )
                    if not local_path:
                        return None, None, ""
                    # If the CDN served the fallback training variant, match the cutout to it
                    trained_art = Path(local_path).stem.endswith("_after_training")
                    if trained_art != is_trained:
                        cutout_path = await get_member_cutout_path(asset_name, trained_art)
                else:
                    local_path = await get_card_image_path(asset_name, is_trained)
                    if not local_path:
                        return None, None, ""
                    cutout_path = None

                return await asyncio.get_running_loop().run_in_executor(
                    None, _process_game_image_sync, local_path, mode, cutout_path
                )
        except TimeoutError:
            logger.warning("Timed out fetching/processing card image for %s", asset_name)
            return None, None, ""
        except Exception as e:
            logger.error("Failed to process card image for %s: %s", asset_name, e)
            return None, None, ""

    async def resolve_mode(self, user_id: int, mode: str | None) -> str:
        """The mode to play: the one asked for, else the player's default, else easy."""
        if mode is None:
            mode = await database.get_user_setting(user_id, MODE_SETTING)
        mode = MODE_ALIASES.get(mode, mode)
        return mode if mode in GUESS_MODES else DEFAULT_MODE

    @app_commands.command(name="guessmode", description="Đặt độ khó mặc định của bạn cho /guess")
    @app_commands.describe(mode="Độ khó mặc định (để trống để xem chế độ hiện tại)")
    @app_commands.choices(mode=MODE_CHOICES)
    async def guess_mode(self, interaction: discord.Interaction, mode: str | None = None):
        if mode is None:
            current = await self.resolve_mode(interaction.user.id, None)
            await interaction.response.send_message(
                f"Độ khó mặc định của bạn cho /guess: **{MODE_LABELS[current]}**. "
                "Đổi bằng `/guessmode <độ khó>`.",
                ephemeral=True,
            )
            return
        mode = await self.resolve_mode(interaction.user.id, mode)
        await database.set_user_setting(interaction.user.id, MODE_SETTING, mode)
        await interaction.response.send_message(
            f"Đã đặt độ khó mặc định cho /guess: **{MODE_LABELS[mode]}**.", ephemeral=True
        )

    @app_commands.command(name="guess", description="Đoán nhân vật qua hình ảnh!")
    # Needs gateway MESSAGE_CREATE events for -g answers (not delivered in user-install/group DMs)
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=False)
    @app_commands.describe(mode="Độ khó (để trống: độ khó mặc định của bạn, ban đầu là Dễ)")
    @app_commands.choices(mode=MODE_CHOICES)
    async def guess(self, interaction: discord.Interaction, mode: str | None = None):
        channel_id = interaction.channel_id
        if channel_id is None:
            await interaction.response.send_message(
                "Lệnh này chỉ dùng được trong kênh văn bản.", ephemeral=True
            )
            return

        if not self.cards:
            await interaction.response.send_message(
                "Dữ liệu card chưa sẵn sàng. Vui lòng thử lại sau ít phút.", ephemeral=True
            )
            return

        if self._is_channel_active(channel_id):
            await interaction.response.send_message(
                "Ai đó đang thử tài rồi, hãy chơi cùng họ nhé!", ephemeral=True
            )
            return

        token = object()
        self.active_channels[channel_id] = asyncio.get_running_loop().time()
        self._channel_tokens[channel_id] = token
        view: GiveUpView | None = None
        msg = None

        try:
            await interaction.response.defer()
            try:
                mode = await self.resolve_mode(interaction.user.id, mode)
                card = random.choice(self.cards)
                if is_pre_trained_card(card):
                    is_trained = True
                elif not supports_trained_art(card):
                    is_trained = False
                else:
                    is_trained = random.choice([True, False])

                game_img, full_img, effect_name = await self.process_game_image(
                    card["assetbundleName"], is_trained, mode
                )

                if not game_img or not full_img:
                    await interaction.followup.send(
                        "Lỗi load hình. Vui lòng thử lại sau.", ephemeral=True
                    )
                    return

                char_data = game_data.characters.get(str(card["characterId"]))
                if not char_data:
                    await interaction.followup.send("Lỗi dữ liệu nhân vật.", ephemeral=True)
                    return

                possible_answers = self.build_answer_list(card["characterId"])
                norm_answers = [na for a in possible_answers if (na := normalize(a))]
                full_name = f"{char_data['firstName']} {char_data['givenName']}".strip()
                logger.debug(f"Guess answer: {full_name}")

                file = discord.File(game_img, filename="guess.jpg")
                embed = discord.Embed(
                    title=f"Đoán nhân vật · {MODE_LABELS[mode]}",
                    description=f"Gõ `{GUESS_PREFIX}[name]` để đoán. Bạn có {SONG_GUESS_DURATION}s.",
                    color=MODE_COLORS[mode],
                )
                embed.set_image(url="attachment://guess.jpg")

                # Create view with working Give Up button
                view = GiveUpView()
                msg = await interaction.followup.send(embed=embed, file=file, view=view)
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
                    msg_task = asyncio.create_task(
                        self.bot.wait_for("message", check=check, timeout=remaining)
                    )
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

                        if is_correct_guess(guess, norm_answers):
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

                # Prepare result (full_img is the cached card file's path)
                result_file = discord.File(full_img, filename="reveal.webp")
                result_embed = discord.Embed(description=f"Đáp án: **{full_name}**")
                result_embed.set_image(url="attachment://reveal.webp")
                result_embed.add_field(name="Card", value=self.get_display_prefix(card))

                if reason == "win":
                    result_embed.title = f"Đúng rồi! Xin chúc mừng {winner.display_name}"
                    result_embed.color = 0x2ECC71
                else:
                    result_embed.title, result_embed.color = _OUTCOME_META[reason]

                view.disable_all()
                view.stop()
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send(embed=result_embed, file=result_file)
                if msg:
                    with contextlib.suppress(discord.HTTPException):
                        await msg.edit(view=view)

            except Exception as e:
                logger.error(f"Guess game error: {e}")
                if view is not None:
                    view.disable_all()
                    view.stop()
                    if msg:
                        with contextlib.suppress(discord.HTTPException):
                            await msg.edit(view=view)
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send(
                        "Ván đoán gặp lỗi và đã dừng. Bạn thử lại nhé.", ephemeral=True
                    )
        finally:
            if view is not None and not view.is_finished():
                view.stop()
            if self._channel_tokens.get(channel_id) is token:
                self._channel_tokens.pop(channel_id, None)
                self.active_channels.pop(channel_id, None)


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


async def setup(bot):
    await bot.add_cog(GuessCog(bot))
