"""
Gacha Cog - Gacha simulation for Project Sekai.
"""

import logging
import random
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw

from config import GACHA_RATES, PITY_THRESHOLD, RARITY_ICONS
from utils.core import database
from utils.data.card_data import card_data
from utils.data.game_data import get_unit_color_hex
from utils.media.image_helper import get_card_image_path

logger = logging.getLogger(__name__)


def _compose_10pull_image(results: list[dict], image_paths: list[str | None]) -> BytesIO:
    """Synchronous helper for composing the 10-pull grid image."""
    THUMB_W, THUMB_H = 192, 110
    PADDING, BORDER, COLS = 20, 5, 5
    canvas_w = (THUMB_W * COLS) + (PADDING * (COLS + 1))
    canvas_h = (THUMB_H * 2) + (PADDING * 3)

    bg = Image.new("RGBA", (canvas_w, canvas_h), (44, 47, 51, 255))
    draw = ImageDraw.Draw(bg)

    def get_border_color(rarity):
        if rarity == "rarity_4":
            return "#9B59B6"
        if rarity == "rarity_3":
            return "#F1C40F"
        return "#3498DB"

    for i, card in enumerate(results):
        row, col = i // COLS, i % COLS
        x = PADDING + col * (THUMB_W + PADDING)
        y = PADDING + row * (THUMB_H + PADDING)

        draw.rectangle(
            [x - BORDER, y - BORDER, x + THUMB_W + BORDER, y + THUMB_H + BORDER],
            fill=get_border_color(card["cardRarityType"]),
        )

        path = image_paths[i]
        if path:
            try:
                with Image.open(path) as thumb:
                    thumb = thumb.resize((THUMB_W, THUMB_H))
                    bg.paste(thumb, (x, y))
            except OSError as e:
                logger.warning(f"Failed to open thumbnail: {e}")

    out_buffer = BytesIO()
    bg.save(out_buffer, format="PNG")
    out_buffer.seek(0)
    return out_buffer


class GachaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Rarity pools — references into the shared card_data singleton (no copies)
        self.cards_2 = card_data.pool_2
        self.cards_3 = card_data.pool_3
        self.cards_4 = card_data.pool_4

    def load_data(self):
        """Card data managed by utils.card_data singleton. Refresh pool refs."""
        self.cards_2 = card_data.pool_2
        self.cards_3 = card_data.pool_3
        self.cards_4 = card_data.pool_4

    def get_display_prefix(self, card: dict) -> str:
        return card_data.get_display_prefix(card)

    async def get_user_pity(self, user_id: int) -> int:
        """Get user's current pity count from the database."""
        return await database.get_pity(user_id)

    async def update_user_pity(self, user_id: int, count: int):
        """Update user's pity count in the database."""
        await database.set_pity(user_id, count)

    def _simulate_single_pull(
        self, current_pity: int, is_guaranteed_slot: bool = False
    ) -> tuple[dict, int]:
        """Simulate a single card pull in memory and return (card, new_pity)."""
        current_pity += 1
        if current_pity >= PITY_THRESHOLD:
            return random.choice(self.cards_4), 0

        rand = random.random()
        if is_guaranteed_slot:
            total_rate = GACHA_RATES["rarity_4"] + GACHA_RATES["rarity_3"]
            rate_4_norm = GACHA_RATES["rarity_4"] / total_rate
            if rand < rate_4_norm:
                return random.choice(self.cards_4), 0
            else:
                return random.choice(self.cards_3), current_pity
        else:
            if rand < GACHA_RATES["rarity_4"]:
                return random.choice(self.cards_4), 0
            elif rand < (GACHA_RATES["rarity_4"] + GACHA_RATES["rarity_3"]):
                return random.choice(self.cards_3), current_pity
            else:
                return random.choice(self.cards_2), current_pity

    async def pull_one_card(self, user_id: int, is_guaranteed_slot: bool = False) -> dict:
        """Pull a single card with pity system."""
        current_pity = await self.get_user_pity(user_id)
        card, new_pity = self._simulate_single_pull(current_pity, is_guaranteed_slot)
        await self.update_user_pity(user_id, new_pity)
        return card

    gacha_group = app_commands.Group(name="gacha", description="Mô phỏng Gacha Project Sekai")

    @gacha_group.command(name="pull", description="Thử vận may")
    @app_commands.choices(
        amount=[
            app_commands.Choice(name="Quay 1 lần", value=1),
            app_commands.Choice(name="Quay 10 lần", value=10),
        ]
    )
    async def pull(self, interaction: discord.Interaction, amount: int = 10):
        await interaction.response.defer()
        user_id = interaction.user.id

        current_pity = await self.get_user_pity(user_id)
        results = []

        if amount == 1:
            card, final_pity = self._simulate_single_pull(current_pity)
            results.append(card)
            await self.update_user_pity(user_id, final_pity)
        else:
            for _ in range(9):
                card, current_pity = self._simulate_single_pull(current_pity)
                results.append(card)
            card, current_pity = self._simulate_single_pull(current_pity, is_guaranteed_slot=True)
            results.append(card)
            final_pity = current_pity
            await self.update_user_pity(user_id, final_pity)

        best_card = max(results, key=lambda x: x["cardRarityType"])

        if amount == 1:
            card = results[0]
            local_path = await get_card_image_path(card["assetbundleName"])

            if not local_path:
                await interaction.followup.send("Lỗi tải ảnh. Vui lòng thử lại.")
                return

            f = discord.File(local_path, filename="card.png")
            color = get_unit_color_hex(card["characterId"])
            rarity_icon = RARITY_ICONS.get(card["cardRarityType"], "")

            display_name = self.get_display_prefix(card)
            embed = discord.Embed(
                title=f"{rarity_icon} Kết Quả Gacha",
                description=f"**{display_name}**",
                color=discord.Color.from_str(color),
            )
            embed.set_image(url="attachment://card.png")
            embed.set_footer(text=f"Pity: {final_pity}/{PITY_THRESHOLD}")

            await interaction.followup.send(embed=embed, file=f)

        else:
            image_paths = []
            for card in results:
                path = await get_card_image_path(card["assetbundleName"])
                image_paths.append(path)

            out_buffer = await self.bot.loop.run_in_executor(
                None, _compose_10pull_image, results, image_paths
            )
            f = discord.File(out_buffer, filename="gacha_10.png")

            c4 = len([c for c in results if c["cardRarityType"] == "rarity_4"])
            c3 = len([c for c in results if c["cardRarityType"] == "rarity_3"])

            color = get_unit_color_hex(best_card["characterId"])

            embed = discord.Embed(
                title=f"Kết quả 10 lần quay của {interaction.user.name}",
                description=f"**4⭐:** {c4} | **3⭐:** {c3}",
                color=discord.Color.from_str(color),
            )
            embed.set_image(url="attachment://gacha_10.png")
            embed.set_footer(text=f"Pity: {final_pity}/{PITY_THRESHOLD}")

            await interaction.followup.send(embed=embed, file=f)

    @gacha_group.command(name="pity", description="Kiểm tra số lần quay đã tích lũy")
    async def check_pity(self, interaction: discord.Interaction):
        """Check current pity count."""
        pity = await self.get_user_pity(interaction.user.id)
        remaining = PITY_THRESHOLD - pity

        embed = discord.Embed(
            title="📊 Thông tin Pity",
            description=f"**Đã quay:** {pity}/{PITY_THRESHOLD}\n**Còn lại:** {remaining} lần để đảm bảo 4⭐",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(GachaCog(bot))
