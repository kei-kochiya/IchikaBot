"""
Card Tournament Cog - 5-round channel-wide card guessing tournament.

Each round has 3 progressive hint phases:
  Phase 1 → 250×250 crop, grayscale  (3 pts if correct)
  Phase 2 → 300×300 crop, colour     (2 pts if correct)
  Phase 3 → 400×400 crop, colour     (1 pt  if correct)

Crop strategy: pick a random 400×400 base region, then take progressively
larger centre-cuts from it so each phase reveals the same spot.
"""
import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import asyncio
import logging
from PIL import Image, ImageOps
from io import BytesIO

from utils.image_helper import get_card_image_path
from utils.card_data import card_data
from utils.game_data import game_data

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
GUESS_PREFIX    = "-g "
TOTAL_ROUNDS    = 5
PHASE_TIMEOUT   = 20    # seconds per phase
PHASE_WRONG_MAX = 4     # total wrong guesses (any player) before advancing

CROP_BASE = 400   # base crop size (also phase 3)
CROP_P2   = 300   # phase 2 crop (colour, centred in base)
CROP_P1   = 250   # phase 1 crop (grayscale, centred in base)

PHASE_POINTS = {1: 3, 2: 2, 3: 1}

PHASE_META = {
    1: ("Giai đoạn 1", f"{CROP_P1}×{CROP_P1} đen trắng", discord.Color.dark_gray()),
    2: ("Giai đoạn 2", f"{CROP_P2}×{CROP_P2} màu",      discord.Color.gold()),
    3: ("Giai đoạn 3", f"{CROP_BASE}×{CROP_BASE} màu",  discord.Color.green()),
}


# ── Helper: image generation ───────────────────────────────────────────────────

async def make_phase_images(
    asset_name: str,
) -> tuple[BytesIO | None, BytesIO | None, BytesIO | None]:
    """
    Generate the three progressive hint images for a card.

    Strategy:
      1. Pick a random 400×400 base crop from the card.
      2. Phase 1 (250×250): centre of base, grayscale.
      3. Phase 2 (300×300): centre of base, colour.
      4. Phase 3 (400×400): the full base crop, colour.

    All three share the same centre point so later phases always reveal
    more context around the same spot seen in phase 1.
    """
    # Try trained art first, fall back to normal
    path = await get_card_image_path(asset_name, is_trained=True)
    if not path:
        path = await get_card_image_path(asset_name, is_trained=False)
    if not path:
        return None, None, None

    try:
        with Image.open(path) as img:
            img = img.convert("RGBA")
            w, h = img.size

            # Scale up if needed
            if w < CROP_BASE or h < CROP_BASE:
                scale = max(CROP_BASE / w, CROP_BASE / h)
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                w, h = img.size

            # Random base 400×400 region
            bx = random.randint(0, w - CROP_BASE)
            by = random.randint(0, h - CROP_BASE)
            base = img.crop((bx, by, bx + CROP_BASE, by + CROP_BASE))

            def centre_crop(src: Image.Image, size: int) -> Image.Image:
                off = (CROP_BASE - size) // 2
                return src.crop((off, off, off + size, off + size))

            p1_colour = centre_crop(base, CROP_P1)
            p1 = ImageOps.grayscale(p1_colour)
            p2 = centre_crop(base, CROP_P2)
            p3 = base.copy()

            def to_buf(image: Image.Image) -> BytesIO:
                buf = BytesIO()
                image.save(buf, format="PNG")
                buf.seek(0)
                return buf

            return to_buf(p1), to_buf(p2), to_buf(p3)

    except Exception as e:
        logger.error("Tournament: Image generation failed for %s: %s", asset_name, e)
        return None, None, None


# ── Cog ────────────────────────────────────────────────────────────────────────

class TournamentCog(commands.Cog):
    """5-round card-guessing tournament for a single channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[int, dict] = {}  # channel_id → state
        # Use shared singleton refs — no per-cog JSON loading
        self.cards   = card_data.pool_3_4
        self.chars   = game_data.characters
        self.nicknames = game_data.nicknames

    # -- Data ------------------------------------------------------------------

    def load_data(self):
        """Refresh references after card_data/game_data reload."""
        self.cards     = card_data.pool_3_4
        self.chars     = game_data.characters
        self.nicknames = game_data.nicknames

    def get_display_prefix(self, card: dict) -> str:
        return card_data.get_display_prefix(card)

    def build_answers(self, card: dict) -> list[str]:
        char = self.chars.get(str(card["characterId"]))
        if not char:
            return []
        fn, gn = char.get("firstName", ""), char.get("givenName", "")
        answers = {
            fn.lower(), gn.lower(),
            f"{fn} {gn}".strip().lower(),
            f"{gn} {fn}".strip().lower(),
        }
        for nick in self.nicknames.get(str(card["characterId"]), []):
            answers.add(nick.lower())
        return list(answers)

    def is_correct(self, guess: str, answers: list[str]) -> bool:
        g = guess.strip().lower()
        return g in answers or (len(g) > 2 and any(g in a for a in answers))

    # -- Round logic -----------------------------------------------------------

    async def run_round(self, channel: discord.TextChannel, round_num: int, state: dict):
        """Run one round with 3 phases. Updates state['scores'] on a correct guess."""
        card = random.choice(self.cards)
        answers = self.build_answers(card)
        char = self.chars.get(str(card["characterId"]))
        if not answers or not char:
            await channel.send(f"Vòng {round_num}: Lỗi dữ liệu, bỏ qua vòng này.")
            return

        full_name    = f"{char.get('firstName', '')} {char.get('givenName', '')}".strip()
        card_prefix  = self.get_display_prefix(card)

        p1, p2, p3 = await make_phase_images(card["assetbundleName"])
        if not p1:
            await channel.send(f"Vòng {round_num}: Không tải được ảnh, bỏ qua vòng này.")
            return

        phase_bufs = {1: p1, 2: p2, 3: p3}
        winner       = None
        winning_phase = None

        for phase_num in (1, 2, 3):
            if not state["active"]:
                return

            label, size_text, color = PHASE_META[phase_num]
            buf = phase_bufs[phase_num]
            buf.seek(0)
            fname = f"r{round_num}p{phase_num}.png"

            embed = discord.Embed(
                title=f"Tournament — Vòng {round_num}/{TOTAL_ROUNDS}",
                description=(
                    f"{label} | {size_text}\n"
                    f"Gõ `{GUESS_PREFIX.strip()} [tên]` để đoán!\n\n"
                    f"*{PHASE_TIMEOUT}s · tối đa {PHASE_WRONG_MAX} lần sai toàn kênh*"
                ),
                color=color,
            )
            embed.set_image(url=f"attachment://{fname}")

            scores_line = self._scores_preview(state["scores"])
            if scores_line:
                embed.set_footer(text=f"Điểm: {scores_line}")

            await channel.send(embed=embed, file=discord.File(buf, filename=fname))

            # ── Listen for guesses ─────────────────────────────────────────
            phase_wrong = 0
            end_time = asyncio.get_running_loop().time() + PHASE_TIMEOUT

            def check(m: discord.Message) -> bool:
                return (
                    m.channel.id == channel.id
                    and not m.author.bot
                    and m.content.lower().startswith(GUESS_PREFIX.lower())
                )

            while asyncio.get_running_loop().time() < end_time:
                remaining = end_time - asyncio.get_running_loop().time()
                try:
                    msg = await self.bot.wait_for(
                        "message", check=check, timeout=min(remaining, 1.0)
                    )
                    guess = msg.content[len(GUESS_PREFIX):].strip()

                    if self.is_correct(guess, answers):
                        winner        = msg.author
                        winning_phase = phase_num
                        await msg.add_reaction("✅")
                        break
                    else:
                        phase_wrong += 1
                        await msg.add_reaction("❌")
                        if phase_wrong >= PHASE_WRONG_MAX:
                            break
                except asyncio.TimeoutError:
                    continue

            if not state["active"]:
                return
            if winner:
                break

            # Announce phase transition (not after the last phase)
            if phase_num < 3:
                next_label = PHASE_META[phase_num + 1][1]
                await channel.send(
                    f"Thêm gợi ý — **{next_label}**!",
                    delete_after=4,
                )

        # ── Round result ───────────────────────────────────────────────────
        if winner:
            pts = PHASE_POINTS[winning_phase]
            state["scores"][winner.id] = state["scores"].get(winner.id, 0) + pts
            result_embed = discord.Embed(
                title=f"{winner.display_name} đoán đúng! +{pts} điểm",
                description=f"Đáp án: **{full_name}**\n*{card_prefix}*",
                color=discord.Color.green(),
            )
        else:
            result_embed = discord.Embed(
                title="Hết thời gian & lượt đoán!",
                description=f"Đáp án: **{full_name}**\n*{card_prefix}*",
                color=discord.Color.red(),
            )

        # Reveal: use the full-resolution card image (already cached from make_phase_images)
        reveal_path = await get_card_image_path(card["assetbundleName"], is_trained=True)
        if not reveal_path:
            reveal_path = await get_card_image_path(card["assetbundleName"], is_trained=False)

        result_embed.set_footer(text=f"Vòng {round_num}/{TOTAL_ROUNDS}")
        if reveal_path:
            result_embed.set_image(url="attachment://result.png")
            await channel.send(
                embed=result_embed,
                file=discord.File(str(reveal_path), filename="result.png"),
            )
        else:
            # Fallback to the 400×400 crop if the path is unavailable
            p3.seek(0)
            result_embed.set_image(url="attachment://result.png")
            await channel.send(embed=result_embed, file=discord.File(p3, filename="result.png"))

        if round_num < TOTAL_ROUNDS:
            await asyncio.sleep(4)

    # -- Tournament orchestrator -----------------------------------------------

    async def run_tournament(self, channel: discord.TextChannel, state: dict):
        """Run all 5 rounds then post the leaderboard."""
        await asyncio.sleep(5)  # Countdown buffer

        for round_num in range(1, TOTAL_ROUNDS + 1):
            if not state["active"]:
                break

            await channel.send(
                f"──────────────────────\n"
                f"**▶ VÒNG {round_num} / {TOTAL_ROUNDS}**\n"
                f"──────────────────────"
            )
            await self.run_round(channel, round_num, state)

        await self._post_leaderboard(channel, state)
        self.active.pop(channel.id, None)

    async def _post_leaderboard(self, channel: discord.TextChannel, state: dict):
        scores  = state["scores"]
        medals  = ["🥇", "🥈", "🥉"]
        embed   = discord.Embed(title="🏆 Kết Quả Tournament", color=discord.Color.gold())

        if not scores:
            embed.description = "Không ai đoán được câu nào!"
        else:
            lines = []
            for i, (uid, pts) in enumerate(
                sorted(scores.items(), key=lambda x: x[1], reverse=True)
            ):
                medal = medals[i] if i < 3 else f"**#{i + 1}**"
                lines.append(f"{medal} <@{uid}> — **{pts} điểm**")
            embed.description = "\n".join(lines)

        embed.set_footer(
            text="Giai đoạn 1 = 3đ  |  Giai đoạn 2 = 2đ  |  Giai đoạn 3 = 1đ"
        )
        await channel.send(embed=embed)

    # -- Utilities -------------------------------------------------------------

    def _scores_preview(self, scores: dict) -> str:
        if not scores:
            return ""
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
        return "  ".join(f"<@{uid}>:{pts}" for uid, pts in top)

    def _start_embed(self) -> discord.Embed:
        return discord.Embed(
            title="🏆 Card Guessing Tournament!",
            description=(
                f"**{TOTAL_ROUNDS} vòng** — bắt đầu sau **5 giây**!\n\n"
                f"Gõ `{GUESS_PREFIX.strip()} [tên nhân vật]` để đoán.\n\n"
                f"**Điểm thưởng mỗi vòng:**\n"
                f"⬛ Giai đoạn 1 — {CROP_P1}×{CROP_P1} đen trắng → **3 điểm**\n"
                f"🟨 Giai đoạn 2 — {CROP_P2}×{CROP_P2} màu → **2 điểm**\n"
                f"🟩 Giai đoạn 3 — {CROP_BASE}×{CROP_BASE} màu → **1 điểm**"
            ),
            color=discord.Color.gold(),
        ).set_footer(
            text=f"Mỗi giai đoạn: {PHASE_TIMEOUT}s | {PHASE_WRONG_MAX} lần đoán sai toàn kênh"
        )

    # -- Commands --------------------------------------------------------------

    @app_commands.command(name="tournament", description="Bắt đầu tournament đoán card (5 vòng)")
    async def slash_tournament(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid in self.active:
            await interaction.response.send_message(
                "Kênh này đang có tournament! Chờ nó kết thúc nhé.", ephemeral=True
            )
            return
        if not self.cards:
            await interaction.response.send_message("Không có dữ liệu card.", ephemeral=True)
            return

        state = {"active": True, "scores": {}}
        self.active[cid] = state
        await interaction.response.send_message(embed=self._start_embed())
        state["task"] = asyncio.create_task(
            self.run_tournament(interaction.channel, state)
        )

    @app_commands.command(name="tournament_stop", description="Dừng tournament đang chạy (Admin)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_stop(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid not in self.active:
            await interaction.response.send_message("Không có tournament nào đang chạy.", ephemeral=True)
            return
        state = self.active.pop(cid)
        state["active"] = False
        if task := state.get("task"):
            task.cancel()
        await interaction.response.send_message("Tournament đã dừng.")

    @commands.command(name="tournament", aliases=["tour"])
    async def prefix_tournament(self, ctx: commands.Context):
        """Start a card guessing tournament: !tournament"""
        cid = ctx.channel.id
        if cid in self.active:
            await ctx.send("Kênh này đang có tournament!")
            return
        if not self.cards:
            await ctx.send("Không có dữ liệu card.")
            return

        state = {"active": True, "scores": {}}
        self.active[cid] = state
        await ctx.send(embed=self._start_embed())
        state["task"] = asyncio.create_task(self.run_tournament(ctx.channel, state))

    @commands.command(name="tournament_stop", aliases=["tourstop"])
    @commands.has_permissions(manage_guild=True)
    async def prefix_stop(self, ctx: commands.Context):
        """Stop the running tournament: !tournament_stop"""
        cid = ctx.channel.id
        if cid not in self.active:
            await ctx.send("Không có tournament nào đang chạy.")
            return
        state = self.active.pop(cid)
        state["active"] = False
        if task := state.get("task"):
            task.cancel()
        await ctx.send("Tournament đã dừng.")

    @slash_stop.error
    async def stop_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "Bạn cần quyền **Manage Server**.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(TournamentCog(bot))
