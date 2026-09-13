"""
Songs Database Cog - Browse and search Project Sekai songs.
Supports both JP and EN song data with English search.
"""

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
        pass

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

    # ===== SLASH COMMANDS =====
    song_group = app_commands.Group(
        name="song", description="Tra cứu thông tin bài hát Project Sekai"
    )

    @song_group.command(name="search", description="Tìm kiếm bài hát theo tên (JP/EN)")
    @app_commands.describe(query="Tên bài hát cần tìm")
    async def song_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        results = self.search_songs(query, limit=50)

        if not results:
            await interaction.followup.send(
                f"Không tìm thấy bài hát nào với từ khóa: **{query}**", ephemeral=True
            )
            return

        if len(results) == 1:
            title = self.get_display_title(results[0], results[0]["id"])
            await interaction.followup.send(
                embed=create_song_embed(results[0], title, self.difficulties)
            )
        else:

            def formatter(song):
                diff_info = self.difficulties.get(song["id"], {})
                master_level = diff_info.get("master", {}).get("playLevel", "?")
                title = self.get_display_title(song, song["id"])
                return f"• **{title}** (Master Lv.{master_level})"

            view = SearchPaginationView(
                results, f"🔍 Kết quả tìm kiếm: {query}", formatter, items_per_page=10
            )
            embed = view._create_embed()
            msg = await interaction.followup.send(embed=embed, view=view)
            view.message = msg

    @song_group.command(name="random", description="Gợi ý bài hát ngẫu nhiên")
    @app_commands.describe(min_level="Level Master tối thiểu", max_level="Level Master tối đa")
    async def song_random(
        self, interaction: discord.Interaction, min_level: int = None, max_level: int = None
    ):
        await interaction.response.defer()

        chosen = song_data.get_random_song(min_level, max_level)
        if not chosen:
            await interaction.followup.send(
                f"Không tìm thấy bài hát nào trong khoảng level {min_level or 1}-{max_level or 37}.",
                ephemeral=True,
            )
            return

        title = self.get_display_title(chosen, chosen["id"])
        embed = create_song_embed(chosen, title, self.difficulties)
        embed.title = f"🎲 Bài hát ngẫu nhiên: {title}"
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
            name_lower = song_name.lower()
            for s_id, meta in song_data.songs_en_meta.items():
                if name_lower in meta["title"].lower():
                    song = song_data.get_song_by_id(s_id)
                    break
            if not song:
                for s in song_data.songs_jp:
                    if s.get("title") and name_lower in s["title"].lower():
                        song = s
                        break

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

    # ===== PREFIX COMMANDS =====
    @commands.command(name="song", aliases=["music", "s"])
    async def song_prefix(self, ctx: commands.Context, *, query: str = None):
        """Search for a song: !song <name>"""
        if not query:
            await ctx.send("Vui lòng nhập tên bài hát: `!song <name>`")
            return

        results = self.search_songs(query, limit=50)

        if not results:
            await ctx.send(f"Không tìm thấy bài hát nào với từ khóa: **{query}**")
            return

        if len(results) == 1:
            title = self.get_display_title(results[0], results[0]["id"])
            await ctx.send(embed=create_song_embed(results[0], title, self.difficulties))
        else:

            def formatter(song):
                diff_info = self.difficulties.get(song["id"], {})
                master_level = diff_info.get("master", {}).get("playLevel", "?")
                title = self.get_display_title(song, song["id"])
                return f"• **{title}** (Master Lv.{master_level})"

            view = SearchPaginationView(
                results, f"🔍 Kết quả tìm kiếm: {query}", formatter, items_per_page=10
            )
            embed = view._create_embed()
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg

    @commands.command(name="songr", aliases=["randomsong"])
    async def song_random_prefix(self, ctx: commands.Context):
        """Get a random song: !songr"""
        chosen = song_data.get_random_song()
        if not chosen:
            await ctx.send("Không có dữ liệu bài hát!")
            return

        title = self.get_display_title(chosen, chosen["id"])
        embed = create_song_embed(chosen, title, self.difficulties)
        embed.title = f"🎲 Bài hát ngẫu nhiên: {title}"
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(SongsCog(bot))
