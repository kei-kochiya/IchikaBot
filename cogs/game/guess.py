import asyncio
import contextlib
import logging
import random
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageFilter, ImageOps

from config import SONG_GUESS_DURATION
from utils.core.tasks import react_in_background
from utils.data.card_data import card_data
from utils.data.game_data import game_data
from utils.data.music_quiz_db import MIN_PARTIAL_LEN, normalize
from utils.game.cards import is_pre_trained_card, supports_trained_art
from utils.media.image_helper import get_card_image_path

logger = logging.getLogger(__name__)

GUESS_PREFIX = "-g "
MAX_FAILS = 4
MAX_PUZZLE_WIDTH = 1280


def is_correct_name_guess(guess: str, answers: list[str]) -> bool:
    """True if guess matches an answer exactly, or is any 3+ character piece of one.

    Both sides go through the music quiz's normalize() first (Unicode fold, letters and
    digits only, lowercase), so the 3 characters are counted after normalizing: "n e" is
    only 2 and doesn't win, and "banh tao" matches the nickname "bánh táo".
    """
    ng = normalize(guess)
    if not ng:
        return False
    for answer in answers:
        na = normalize(answer)
        if ng == na or (len(ng) >= MIN_PARTIAL_LEN and ng in na):
            return True
    return False


def _process_game_image_sync(local_path: str, mode: str) -> tuple[BytesIO | None, str | None, str]:
    """Synchronous helper for image processing with effects.

    Returns (puzzle_png, reveal_path, effect_name).  The reveal image is the untouched
    cached card file, so it is never decoded/re-encoded or held in memory during a game.
    """
    CROP_SIZE = 250
    try:
        with Image.open(local_path) as img:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            w, h = img.size

            if w < CROP_SIZE or h < CROP_SIZE:
                img = img.resize((max(w, CROP_SIZE), max(h, CROP_SIZE)))
                w, h = img.size

            if mode == "random":
                effect = random.choice(["crop_bw", "pixelate", "blur", "negative"])
            else:
                effect = "crop"

            if effect == "crop" or effect == "crop_bw":
                # Crop first: only the 250x250 region is ever copied/converted
                x = random.randint(0, w - CROP_SIZE)
                y = random.randint(0, h - CROP_SIZE)
                game_img = img.crop((x, y, x + CROP_SIZE, y + CROP_SIZE))
                if effect == "crop_bw":
                    game_img = ImageOps.grayscale(game_img)
                    effect_used = "Trắng đen"
                else:
                    effect_used = "Crop"

            else:
                # Whole-image effects don't need the 2520px source art: cap the width so
                # encoding is faster and the upload to Discord is several times smaller.
                if w > MAX_PUZZLE_WIDTH:
                    img = img.resize(
                        (MAX_PUZZLE_WIDTH, round(h * MAX_PUZZLE_WIDTH / w)),
                        Image.BILINEAR,
                        reducing_gap=2.0,
                    )
                    w, h = img.size

                if effect == "pixelate":
                    small = img.resize((48, 48), Image.NEAREST)
                    game_img = small.resize((w, h), Image.NEAREST)
                    effect_used = "Pixelate"

                elif effect == "blur":
                    # Blurring a quarter-size copy and scaling back up looks the same as a
                    # big blur but costs a fraction of the time.
                    small = img.reduce(4).filter(ImageFilter.GaussianBlur(radius=25 / 4))
                    game_img = small.resize((w, h), Image.BILINEAR)
                    effect_used = "Blur"

                else:  # negative
                    game_img = ImageOps.invert(img.convert("RGB"))
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
        # References to shared singletons — no per-cog loading
        self.cards = card_data.pool_3_4

    def _is_channel_active(self, channel_id: int) -> bool:
        """Check if game is actively running in channel. Auto-recovers stale/hung channels (>45s)."""
        if channel_id not in self.active_channels:
            return False
        start_time = self.active_channels[channel_id]
        now = asyncio.get_running_loop().time()
        if now - start_time > 45.0:
            logger.warning(
                "Guess game in channel %s hung or timed out (%0.1fs ago). Auto-recovering channel.",
                channel_id,
                now - start_time,
            )
            self.active_channels.pop(channel_id, None)
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
                local_path = await get_card_image_path(asset_name, is_trained)
                if not local_path:
                    return None, None, ""

                return await self.bot.loop.run_in_executor(
                    None, _process_game_image_sync, local_path, mode
                )
        except TimeoutError:
            logger.warning("Timed out fetching/processing card image for %s", asset_name)
            return None, None, ""
        except Exception as e:
            logger.error("Failed to process card image for %s: %s", asset_name, e)
            return None, None, ""

    @app_commands.command(name="guess", description="Đoán nhân vật qua hình ảnh!")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Normal", value="normal"),
            app_commands.Choice(name="Random", value="random"),
        ]
    )
    async def guess(self, interaction: discord.Interaction, mode: str = "normal"):
        channel_id = interaction.channel_id
        if channel_id is None:
            await interaction.response.send_message(
                "Lệnh này chỉ dùng được trong kênh văn bản.", ephemeral=True
            )
            return

        if self._is_channel_active(channel_id):
            await interaction.response.send_message(
                "Ai đó đang thử tài rồi, hãy chơi cùng họ nhé!", ephemeral=True
            )
            return

        self.active_channels[channel_id] = asyncio.get_running_loop().time()

        try:
            await interaction.response.defer()
            try:
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
                full_name = f"{char_data['firstName']} {char_data['givenName']}".strip()
                logger.debug(f"Guess answer: {full_name}")

                file = discord.File(game_img, filename="guess.jpg")
                embed = discord.Embed(
                    title="Đoán nhân vật",
                    description=f"Gõ `{GUESS_PREFIX}[name]` để đoán. Bạn có {SONG_GUESS_DURATION}s.",
                    color=0xF1C40F if mode == "normal" else 0x9B59B6,
                )
                embed.set_image(url="attachment://guess.jpg")

                # Create view with working Give Up button
                view = GiveUpView(channel_id, self, char_data, card, full_img)
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

                while asyncio.get_running_loop().time() < end_time and not view.gave_up:
                    remaining = end_time - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        guess_msg = await self.bot.wait_for(
                            "message", check=check, timeout=min(remaining, 1.0)
                        )
                        guess = guess_msg.content[len(GUESS_PREFIX) :].strip().lower()

                        if is_correct_name_guess(guess, possible_answers):
                            winner = guess_msg.author
                            reason = "win"
                            react_in_background(guess_msg, "✅")
                            break
                        else:
                            fails += 1
                            react_in_background(guess_msg, "❌")
                            if fails >= MAX_FAILS:
                                reason = "failed"
                                break

                    except TimeoutError:
                        continue

                if view.gave_up:
                    reason = "gave_up"

                # Prepare result (full_img is the cached card file's path)
                result_file = discord.File(full_img, filename="reveal.webp")
                result_embed = discord.Embed(
                    description=f"Đáp án: **{char_data['firstName']} {char_data['givenName']}**"
                )
                result_embed.set_image(url="attachment://reveal.webp")
                result_embed.add_field(name="Card", value=self.get_display_prefix(card))

                if reason == "win":
                    result_embed.title = f"Đúng rồi! Xin chúc mừng {winner.display_name}"
                    result_embed.color = 0x2ECC71
                elif reason == "failed":
                    result_embed.title = f"Game Over. Bạn chỉ được phép đoán sai {MAX_FAILS} lần!"
                    result_embed.color = 0xE74C3C
                elif reason == "gave_up":
                    result_embed.title = "Đã bỏ cuộc!"
                    result_embed.color = 0xE74C3C
                else:
                    result_embed.title = "Hết giờ rồi!"
                    result_embed.color = 0xE74C3C

                view.disable_all()
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send(embed=result_embed, file=result_file)
                if msg:
                    with contextlib.suppress(discord.HTTPException):
                        await msg.edit(view=view)

            except Exception as e:
                logger.error(f"Guess game error: {e}")
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send("Error occurred.", ephemeral=True)
        finally:
            self.active_channels.pop(channel_id, None)


class GiveUpView(discord.ui.View):
    """View with a working Give Up button."""

    def __init__(self, channel_id: int, cog: GuessCog, char_data: dict, card: dict, full_img: str):
        super().__init__(timeout=SONG_GUESS_DURATION + 5)
        self.channel_id = channel_id
        self.cog = cog
        self.char_data = char_data
        self.card = card
        self.full_img = full_img
        self.gave_up = False
        self.message = None

    @discord.ui.button(label="Give Up", style=discord.ButtonStyle.danger)
    async def give_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle give up button click."""
        self.gave_up = True
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
