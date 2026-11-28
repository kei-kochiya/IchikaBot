"""Songs database cog for browsing and searching JP/EN Project Sekai songs."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.data.song_data import song_data
from utils.info.songs_ui import SearchPaginationView, create_song_embed

logger = logging.getLogger(__name__)


class SongsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def load_data(self):
        """Song data is managed by utils.song_data singleton."""

    @property
    def difficulties(self):
        return song_data.difficulties

    def get_song_by_id(self, song_id: int) -> dict | None:
        """Get song by ID."""
        return song_data.get_song_by_id(song_id)

    def get_display_title(self, song: dict, song_id: int) -> str:
        """Get display title, using EN if available."""
        return song_data.get_display_title(song, song_id)

    def search_songs(self, query: str, limit: int = 50) -> list[dict]:
        """Search songs by name, ID, or romaji in both JP and EN."""
        return song_data.search_songs(query, limit)

    def _build_search_reply(
        self, query: str
    ) -> tuple[discord.Embed | None, discord.ui.View | None]:
        results = self.search_songs(query, limit=50)
        if not results:
            return None, None
        if len(results) == 1:
            title = self.get_display_title(results[0], results[0]["id"])
            return create_song_embed(results[0], title, self.difficulties), None

        def formatter(song: dict) -> str:
            diff_info = self.difficulties.get(song["id"], {})
            master_level = diff_info.get("master", {}).get("playLevel", "?")
            title = self.get_display_title(song, song["id"])
            return f"• **{title}** (Master Lv.{master_level})"

        view = SearchPaginationView(
            results,
            f"Kết quả tìm kiếm: {query}",
            formatter,
            items_per_page=10,
            hint="Dùng `/song info` hoặc `!song` để xem chi tiết.",
        )
        return view._create_embed(), view

    # ===== SLASH COMMANDS =====
    song_group = app_commands.Group(
        name="song", description="Tra cứu thông tin bài hát Project Sekai"
    )

    @song_group.command(name="search", description="Tìm kiếm bài hát theo tên (JP/EN)")
    @app_commands.describe(query="Tên bài hát cần tìm")
    async def song_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        embed, view = self._build_search_reply(query)
        if embed is None:
            await interaction.followup.send(
                f"Không tìm thấy bài hát nào với từ khóa: **{query[:100]}**",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if view is None:
            await interaction.followup.send(embed=embed)
            return
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    @song_group.command(name="random", description="Gợi ý bài hát ngẫu nhiên")
    @app_commands.describe(min_level="Level Master tối thiểu", max_level="Level Master tối đa")
    async def song_random(
        self,
        interaction: discord.Interaction,
        min_level: int | None = None,
        max_level: int | None = None,
    ):
        await interaction.response.defer()

        chosen = song_data.get_random_song(min_level, max_level)
        if not chosen:
            lo = min_level if min_level is not None else 1
            hi = max_level if max_level is not None else 37
            await interaction.followup.send(
                f"Không tìm thấy bài hát nào trong khoảng level {lo}-{hi}.",
                ephemeral=True,
            )
            return

        title = self.get_display_title(chosen, chosen["id"])
        embed = create_song_embed(chosen, title, self.difficulties)
        embed.title = f"Bài hát ngẫu nhiên: {title}"
        await interaction.followup.send(embed=embed)

    @song_group.command(name="info", description="Xem chi tiết bài hát")
    @app_commands.describe(song_name="Chọn bài hát")
    async def song_info(self, interaction: discord.Interaction, song_name: str):
        await interaction.response.defer()

        song = None
        try:
            song_id = int(song_name)
            song = self.get_song_by_id(song_id)
        except ValueError:
            matches = song_data.search_songs(song_name, limit=1)
            song = matches[0] if matches else None

        if not song:
            await interaction.followup.send("Không tìm thấy bài hát.", ephemeral=True)
            return

        title = self.get_display_title(song, song["id"])
        await interaction.followup.send(embed=create_song_embed(song, title, self.difficulties))

    @song_info.autocomplete("song_name")
    async def song_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return song_data.get_autocomplete_choices(current)


async def setup(bot):
    await bot.add_cog(SongsCog(bot))
