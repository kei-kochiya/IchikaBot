"""
Gacha Cog - Gacha simulation for Project Sekai.
"""

import asyncio
import logging
import random
import weakref
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from config import GACHA_RATES, PITY_THRESHOLD, RARITY_ICONS
from utils.core import database
from utils.data.card_data import card_data
from utils.game.cards import is_pre_trained_card
from utils.media.gacha_render import get_ui_assets, render_single_pull, render_ten_pull
from utils.media.image_helper import get_card_image_path

logger = logging.getLogger(__name__)


async def _card_art(card: dict) -> str | None:
    # Pre-trained cards only have trained art: ask for it directly instead of via a 404
    return await get_card_image_path(card["assetbundleName"], is_pre_trained_card(card))


class GachaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Rarity pools — references into the shared card_data singleton (no copies)
        self.cards_2 = card_data.pool_2
        self.cards_3 = card_data.pool_3
        self.cards_4 = card_data.pool_4
        # Per-user locks so two concurrent pulls can't both read the same pity value.
        # Weak values: a lock disappears as soon as nobody is using it.
        self._pity_locks: weakref.WeakValueDictionary[int, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def _pity_lock(self, user_id: int) -> asyncio.Lock:
        lock = self._pity_locks.get(user_id)
        if lock is None:
            lock = self._pity_locks[user_id] = asyncio.Lock()
        return lock

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
            # "3★ or better" slot: 4★ keeps its normal rate and the 2★ share goes to 3★.
            # (Rescaling 4★ and 3★ together made this slot 4★ ~29% of the time, not 6%.)
            if rand < GACHA_RATES["rarity_4"]:
                return random.choice(self.cards_4), 0
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
        async with self._pity_lock(user_id):
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

        results = []

        # Read-modify-write of the pity counter must be atomic per user
        async with self._pity_lock(user_id):
            current_pity = await self.get_user_pity(user_id)

            if amount == 1:
                card, final_pity = self._simulate_single_pull(current_pity)
                results.append(card)
            else:
                for _ in range(9):
                    card, current_pity = self._simulate_single_pull(current_pity)
                    results.append(card)
                card, current_pity = self._simulate_single_pull(
                    current_pity, is_guaranteed_slot=True
                )
                results.append(card)
                final_pity = current_pity

            await self.update_user_pity(user_id, final_pity)

        assets = await get_ui_assets()
        content, data, filename = await self._build_result(
            interaction.user, results, final_pity, assets
        )
        # A plain image attachment rather than an embed: Discord shows it larger (an embed
        # caps the image at ~400 px wide, which made the ten cards tiny), and the result
        # reads like the in-game screen instead of a framed card.
        await interaction.followup.send(
            content=content,
            file=discord.File(BytesIO(data), filename=filename),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _build_result(
        self, user: discord.abc.User, results: list[dict], final_pity: int, assets: dict
    ) -> tuple[str, bytes, str]:
        """Render the result: (one-line caption, image bytes, filename)."""
        loop = asyncio.get_running_loop()
        name = discord.utils.escape_markdown(user.display_name)
        pity = f"Pity {final_pity}/{PITY_THRESHOLD}"
        if len(results) == 1:
            card = results[0]
            # Missing art (not on the CDN yet) renders as a placeholder: the pull, and maybe
            # a pity reset, must never happen without the user seeing which card it was
            local_path = await _card_art(card)
            image = await loop.run_in_executor(None, render_single_pull, card, local_path, assets)
            data, filename = image.getvalue(), "card.jpg"
            rarity = RARITY_ICONS.get(card["cardRarityType"], "")
            prefix = discord.utils.escape_markdown(self.get_display_prefix(card))
            content = f"**{name}** · {rarity} **{prefix}** · {pity}"
        else:
            # Fetch all ten images concurrently (duplicates share one download)
            image_paths = await asyncio.gather(*(_card_art(card) for card in results))
            image = await loop.run_in_executor(None, render_ten_pull, results, image_paths, assets)
            data, filename = image.getvalue(), "gacha_10.jpg"
            c4 = sum(c["cardRarityType"] == "rarity_4" for c in results)
            c3 = sum(c["cardRarityType"] == "rarity_3" for c in results)
            content = f"**{name}** quay 10 lần · 4★ **{c4}** · 3★ **{c3}** · {pity}"
        return content, data, filename

    @gacha_group.command(name="pity", description="Kiểm tra số lần quay đã tích lũy")
    async def check_pity(self, interaction: discord.Interaction):
        """Check current pity count."""
        pity = await self.get_user_pity(interaction.user.id)
        remaining = PITY_THRESHOLD - pity

        embed = discord.Embed(
            title="Pity của bạn",
            description=f"**Đã quay:** {pity}/{PITY_THRESHOLD}\n**Còn:** {remaining} lần nữa là chắc chắn có 4★",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(GachaCog(bot))
