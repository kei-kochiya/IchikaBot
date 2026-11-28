"""Character guessing minigame (`/guess` and `/guessmode`) from cropped/effected card art."""

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
from utils.data.card_data import card_data
from utils.data.game_data import game_data
from utils.data.music_quiz_db import normalize
from utils.game.cards import is_pre_trained_card, supports_trained_art
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
from utils.media.card_focus import focus_crop_box
from utils.media.image_helper import get_card_image_path, get_member_cutout_path

logger = logging.getLogger(__name__)

MAX_PUZZLE_WIDTH = 1280
CROP_SIZE = 300

# Difficulties: easy crops on the card's own character (found with its member_cutout),
# normal crops anywhere on the card, hard adds a random effect.
MODE_ALIASES = {"random": "hard"}  # the old name of hard mode
DEFAULT_MODE = "easy"  # for players who never chose one with /guessmode
MODE_SETTING = "guess_mode"  # user_settings key
MODE_CHOICES = [
    app_commands.Choice(name="Dễ: cắt vào nhân vật", value="easy"),
    app_commands.Choice(name="Thường: cắt ngẫu nhiên", value="normal"),
    app_commands.Choice(name="Khó: hiệu ứng ngẫu nhiên", value="hard"),
]


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
    """Build a puzzle JPEG from cached card art off the event loop.

    mode: "easy" (crops on the character using cutout_path, falling back to normal crop),
    "normal" (random 300x300 crop), or "hard" (random effect; "random" accepted as alias).
    Returns `(puzzle_jpeg, reveal_path, effect_name)`.
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
            elif effect in ("crop", "crop_bw"):
                x = random.randint(0, w - CROP_SIZE)
                y = random.randint(0, h - CROP_SIZE)
                game_img = img.crop((x, y, x + CROP_SIZE, y + CROP_SIZE))
                if effect == "crop_bw":
                    game_img = ImageOps.grayscale(game_img)
                    effect_used = "Trắng đen"
                else:
                    effect_used = "Crop"
            else:
                tw, th = (
                    (MAX_PUZZLE_WIDTH, round(h * MAX_PUZZLE_WIDTH / w))
                    if w > MAX_PUZZLE_WIDTH
                    else (w, h)
                )

                if effect == "pixelate":
                    game_img = img.resize((48, 48), Image.NEAREST).resize((tw, th), Image.NEAREST)
                    effect_used = "Pixelate"
                elif effect == "blur":
                    small = img.resize(
                        (max(1, tw // 4), max(1, th // 4)),
                        Image.BILINEAR,
                        reducing_gap=2.0,
                    ).filter(ImageFilter.GaussianBlur(radius=25 / 4))
                    game_img = small.resize((tw, th), Image.BILINEAR)
                    effect_used = "Blur"
                else:
                    if (tw, th) != (w, h):
                        img = img.resize((tw, th), Image.BILINEAR, reducing_gap=2.0)
                    rgb = img if img.mode == "RGB" else img.convert("RGB")
                    game_img = ImageOps.invert(rgb)
                    effect_used = "Âm bản"

            game_io = BytesIO()
            if game_img.mode not in ("RGB", "L"):
                game_img = game_img.convert("RGB")
            game_img.save(game_io, format="JPEG", quality=90)
            game_io.seek(0)

        return game_io, local_path, effect_used
    except OSError as e:
        logger.error("Failed to process image: %s", e)
        return None, None, ""


class CardGuessCog(commands.Cog):
    """Slash commands for character guessing from card art (`/guess`, `/guessmode`)."""

    def __init__(self, bot):
        self.bot = bot
        self.cards = card_data.pool_3_4

    def load_data(self):
        """Refresh card pool reference after singleton reload."""
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
        """Fetch card art (and cutout in easy mode) and build the puzzle JPEG off-thread."""
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
        """Resolve effective difficulty: explicit choice, else saved user setting, else easy."""
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

        if is_channel_active(channel_id):
            await interaction.response.send_message(
                "Ai đó đang thử tài rồi, hãy chơi cùng họ nhé!", ephemeral=True
            )
            return

        token = acquire_channel(channel_id)
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

                game_img, full_img, _effect_name = await self.process_game_image(
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
                logger.debug("Guess answer: %s", full_name)

                embed = discord.Embed(
                    title=f"Đoán nhân vật · {MODE_LABELS[mode]}",
                    description=f"Gõ `{GUESS_PREFIX}[name]` để đoán. Bạn có {SONG_GUESS_DURATION}s.",
                    color=MODE_COLORS[mode],
                )
                embed.set_image(url="attachment://guess.jpg")

                await run_guess_round(
                    self.bot,
                    interaction,
                    channel_id,
                    puzzle_embed=embed,
                    puzzle_file=discord.File(game_img, filename="guess.jpg"),
                    norm_answers=norm_answers,
                    answer_label=full_name,
                    reveal_path=full_img,
                    reveal_fields=[("Card", self.get_display_prefix(card))],
                )
            except Exception as e:
                logger.error("Guess game error: %s", e)
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send(
                        "Ván đoán gặp lỗi và đã dừng. Bạn thử lại nhé.", ephemeral=True
                    )
        finally:
            release_channel(channel_id, token)


async def setup(bot):
    await bot.add_cog(CardGuessCog(bot))
