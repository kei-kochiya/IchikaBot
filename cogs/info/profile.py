"""
Character Profile Cog - Detailed character information from Project Sekai.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.data.card_data import card_data
from utils.data.game_data import (
    character_autocomplete,
    game_data,
    get_character_name,
    get_unit_color,
)
from utils.game.cards import CardToggleView, get_card_image_url, get_random_card

logger = logging.getLogger(__name__)


class ProfileCog(commands.Cog):
    """Cog for displaying detailed character profiles."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        logger.info(
            "ProfileCog loaded with %d profiles, %d cards (shared singletons)",
            len(game_data.profiles),
            len(card_data.cards),
        )

    def load_data(self):
        """Profile and card data are managed by shared singletons."""
        pass

    def get_display_prefix(self, card: dict) -> str:
        return card_data.get_display_prefix(card)

    def get_random_card_for_character(self, char_id: int, rarity: list[str] = None) -> dict | None:
        """Get a random 3-star or 4-star card for a character."""
        if rarity is None:
            rarity = ["rarity_3", "rarity_4"]
        return get_random_card(card_data.cards, char_id, rarity)

    def get_birthday_card_for_character(self, char_id: int) -> dict | None:
        """Get a birthday card for a character."""
        return get_random_card(card_data.cards, char_id, ["rarity_birthday"])

    def create_profile_embed(self, char_id: int, card: dict = None) -> discord.Embed | None:
        profile = game_data.get_profile(char_id)
        if not profile:
            return None

        name = get_character_name(char_id, full=True)

        embed = discord.Embed(
            title=f"📋 {name}",
            description=profile.get("introduction", ""),
            color=get_unit_color(char_id),
        )

        embed.add_field(name="Seiyuu", value=profile.get("characterVoice", "N/A"), inline=True)
        embed.add_field(name="Sinh nhật", value=profile.get("birthday", "N/A"), inline=True)
        embed.add_field(name="Chiều cao", value=profile.get("height", "N/A"), inline=True)
        embed.add_field(name="Trường", value=profile.get("school", "N/A"), inline=True)
        embed.add_field(name="Lớp", value=profile.get("schoolYear", "N/A"), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        if profile.get("hobby"):
            embed.add_field(
                name="Sở thích", value=profile["hobby"].replace("\\n", " "), inline=False
            )
        if profile.get("specialSkill"):
            embed.add_field(name="Kỹ năng", value=profile["specialSkill"], inline=True)
        if profile.get("weak"):
            embed.add_field(name="Điểm yếu", value=profile["weak"], inline=True)
        if profile.get("favoriteFood"):
            embed.add_field(name="Món ăn yêu thích", value=profile["favoriteFood"], inline=True)
        if profile.get("hatedFood"):
            embed.add_field(name="Món ăn không thích", value=profile["hatedFood"], inline=True)

        # Set card image
        if card:
            embed.set_image(url=get_card_image_url(card["assetbundleName"], False))
            rarity = (
                "🎂"
                if card["cardRarityType"] == "rarity_birthday"
                else f"{card['cardRarityType'][-1]}⭐"
            )
            embed.set_footer(text=f"Card: {self.get_display_prefix(card)} ({rarity})")

        return embed

    # --- Autocomplete ---
    async def char_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return character_autocomplete(current, max_id=26)

    # ===== SLASH COMMANDS =====
    profile_group = app_commands.Group(name="profile", description="Thông tin chi tiết nhân vật")

    @profile_group.command(name="info", description="Xem thông tin đầy đủ của một nhân vật")
    @app_commands.describe(character="Chọn nhân vật")
    @app_commands.autocomplete(character=char_autocomplete)
    async def profile_info(self, interaction: discord.Interaction, character: str):
        await interaction.response.defer()

        try:
            char_id = int(character)
        except ValueError:
            char_id, _ = game_data.get_character_by_name(character)
            if char_id is None:
                await interaction.followup.send(f"Không tìm thấy nhân vật: **{character}**")
                return

        card = self.get_random_card_for_character(char_id)
        embed = self.create_profile_embed(char_id, card)

        if embed is None:
            await interaction.followup.send("Không có thông tin profile cho nhân vật này.")
            return

        if card:
            view = CardToggleView(embed, card)
            msg = await interaction.followup.send(embed=embed, view=view)
            view.message = msg
        else:
            await interaction.followup.send(embed=embed)

    # ===== PREFIX COMMANDS =====
    @commands.command(name="profile", aliases=["char", "character"])
    async def profile_prefix(self, ctx: commands.Context, *, name: str = None):
        """Get character profile: !profile <name>"""
        if not name:
            await ctx.send("Vui lòng nhập tên nhân vật: `!profile <name>`")
            return

        char_id, _ = game_data.get_character_by_name(name)
        if char_id is None:
            await ctx.send(f"Không tìm thấy nhân vật: **{name}**")
            return

        card = self.get_random_card_for_character(char_id)
        embed = self.create_profile_embed(char_id, card)

        if embed is None:
            await ctx.send("Không có thông tin profile cho nhân vật này.")
            return

        if card:
            view = CardToggleView(embed, card)
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))
