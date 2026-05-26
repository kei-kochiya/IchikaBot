"""
Card Tournament Cog - 5-round channel-wide card guessing tournament.
"""
import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import logging

from utils.media.image_helper import get_card_image_path
from utils.data.card_data import card_data
from utils.data.game_data import game_data

# Import helpers and UI
from utils.game.tournament_logic import make_phase_images
from utils.game.tournament_ui import (
    TOTAL_ROUNDS,
    GUESS_PREFIX,
    PHASE_TIMEOUT,
    PHASE_WRONG_MAX,
    PHASE_POINTS,
    PHASE_META,
    create_start_embed,
    create_round_embed,
    create_result_embed,
    create_leaderboard_embed
)

logger = logging.getLogger(__name__)

class TournamentCog(commands.Cog):
    """5-round card-guessing tournament for a single channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[int, dict] = {}  # channel_id → state

    # -- Data ------------------------------------------------------------------

    def get_display_prefix(self, card: dict) -> str:
        return card_data.get_display_prefix(card)

    def build_answers(self, card: dict) -> list[str]:
        char = game_data.characters.get(str(card["characterId"]))
        if not char:
            return []
        fn, gn = char.get("firstName", ""), char.get("givenName", "")
        answers = {
            fn.lower(), gn.lower(),
            f"{fn} {gn}".strip().lower(),
            f"{gn} {fn}".strip().lower(),
        }
        for nick in game_data.nicknames.get(str(card["characterId"]), []):
            answers.add(nick.lower())
        return list(answers)

    def is_correct(self, guess: str, answers: list[str]) -> bool:
        g = guess.strip().lower()
        return g in answers or (len(g) > 2 and any(g in a for a in answers))

    # -- Round logic -----------------------------------------------------------

    async def run_round(self, channel: discord.TextChannel, round_num: int, state: dict):
        """Run one round with 3 phases. Updates state['scores'] on a correct guess."""
        card = random.choice(card_data.pool_3_4)
        answers = self.build_answers(card)
        char = game_data.characters.get(str(card["characterId"]))
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

            buf = phase_bufs[phase_num]
            buf.seek(0)
            fname = f"r{round_num}p{phase_num}.png"

            embed = create_round_embed(round_num, phase_num, state["scores"], fname)
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
        pts = PHASE_POINTS[winning_phase] if winner else 0
        if winner:
            state["scores"][winner.id] = state["scores"].get(winner.id, 0) + pts
        
        result_embed = create_result_embed(winner, pts, full_name, card_prefix, round_num)

        # Reveal: use the full-resolution card image (already cached from make_phase_images)
        reveal_path = await get_card_image_path(card["assetbundleName"], is_trained=True)
        if not reveal_path:
            reveal_path = await get_card_image_path(card["assetbundleName"], is_trained=False)

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

        embed = create_leaderboard_embed(state["scores"])
        await channel.send(embed=embed)
        self.active.pop(channel.id, None)

    # -- Commands --------------------------------------------------------------

    @app_commands.command(name="tournament", description="Bắt đầu tournament đoán card (5 vòng)")
    async def slash_tournament(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid in self.active:
            await interaction.response.send_message(
                "Kênh này đang có tournament! Chờ nó kết thúc nhé.", ephemeral=True
            )
            return
        if not card_data.pool_3_4:
            await interaction.response.send_message("Không có dữ liệu card.", ephemeral=True)
            return

        state = {"active": True, "scores": {}}
        self.active[cid] = state
        await interaction.response.send_message(embed=create_start_embed())
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
        if not card_data.pool_3_4:
            await ctx.send("Không có dữ liệu card.")
            return

        state = {"active": True, "scores": {}}
        self.active[cid] = state
        await ctx.send(embed=create_start_embed())
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
