"""
Songs Database Cog - Browse and search Project Sekai songs.
Supports both JP and EN song data with English search.
"""
import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import logging
from datetime import datetime

from config import MUSICS_FILE_JP, MUSICS_FILE_EN, MUSIC_DIFFICULTIES_FILE_JP, MUSIC_DIFFICULTIES_FILE_EN
from utils.romaji import matches_query, normalize_for_search

logger = logging.getLogger(__name__)

DIFFICULTY_EMOJI = {
    'easy': '🟢',
    'normal': '🔵', 
    'hard': '🟡',
    'expert': '🔴',
    'master': '🟣',
    'append': '⚪'
}


class SongsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.songs_jp = []
        self.songs_en = []
        self.songs_en_by_id = {}
        self.difficulties = {}
        self.load_data()

    def load_data(self):
        """Load both JP and EN song data."""
        # Load JP songs
        try:
            with open(MUSICS_FILE_JP, 'r', encoding='utf-8') as f:
                self.songs_jp = json.load(f)
            logger.info(f"Songs: Loaded {len(self.songs_jp)} JP songs.")
        except FileNotFoundError as e:
            logger.error(f"Songs: Missing JP file: {e.filename}")
            self.songs_jp = []
        except Exception as e:
            logger.error(f"Songs: Failed to load JP data: {e}")
            self.songs_jp = []
        
        # Load EN songs
        try:
            with open(MUSICS_FILE_EN, 'r', encoding='utf-8') as f:
                self.songs_en = json.load(f)
            self.songs_en_by_id = {s['id']: s for s in self.songs_en}
            logger.info(f"Songs: Loaded {len(self.songs_en)} EN songs.")
        except FileNotFoundError as e:
            logger.warning(f"Songs: Missing EN file: {e.filename}")
            self.songs_en = []
            self.songs_en_by_id = {}
        except Exception as e:
            logger.error(f"Songs: Failed to load EN data: {e}")
            self.songs_en = []
            self.songs_en_by_id = {}
        
        # Load difficulties (JP has more data usually)
        try:
            with open(MUSIC_DIFFICULTIES_FILE_JP, 'r', encoding='utf-8') as f:
                raw_difficulties = json.load(f)
                self.difficulties = {}
                for diff in raw_difficulties:
                    music_id = diff['musicId']
                    if music_id not in self.difficulties:
                        self.difficulties[music_id] = {}
                    self.difficulties[music_id][diff['musicDifficulty']] = {
                        'playLevel': diff['playLevel'],
                        'noteCount': diff['totalNoteCount']
                    }
        except Exception as e:
            logger.error(f"Songs: Failed to load difficulty data: {e}")
            self.difficulties = {}

    def get_song_by_id(self, song_id: int) -> dict | None:
        """Get song by ID, prioritizing EN data, fallback to JP."""
        if song_id in self.songs_en_by_id:
            return self.songs_en_by_id[song_id]
        for song in self.songs_jp:
            if song['id'] == song_id:
                return song
        return None

    def get_display_title(self, song: dict, song_id: int) -> str:
        """Get display title, using EN if available."""
        en_song = self.songs_en_by_id.get(song_id)
        if en_song and en_song.get('title'):
            return en_song['title']
        return song.get('title', 'Unknown')

    def create_song_embed(self, song: dict) -> discord.Embed:
        song_id = song['id']
        # Use EN title if available
        title = self.get_display_title(song, song_id)
        diff_info = self.difficulties.get(song_id, {})
        
        diff_lines = []
        for diff_name in ['easy', 'normal', 'hard', 'expert', 'master', 'append']:
            if diff_name in diff_info:
                level = diff_info[diff_name]['playLevel']
                notes = diff_info[diff_name]['noteCount']
                emoji = DIFFICULTY_EMOJI.get(diff_name, '⚪')
                diff_lines.append(f"{emoji} **{diff_name.title()}**: Lv.{level} ({notes} notes)")
        
        release_ts = song.get('publishedAt', 0) / 1000
        release_date = datetime.fromtimestamp(release_ts).strftime('%Y-%m-%d') if release_ts > 0 else 'Unknown'
        
        embed = discord.Embed(
            title=f"{title}",
            color=discord.Color.from_str('#00BFFF')
        )
        
        embed.add_field(
            name="Credits",
            value=f"**Composer**: {song.get('composer', '-')}\n"
                  f"**Lyricist**: {song.get('lyricist', '-')}\n"
                  f"**Arranger**: {song.get('arranger', '-')}",
            inline=True
        )
        
        embed.add_field(
            name="Info",
            value=f"**ID**: {song_id}\n"
                  f"**Released**: {release_date}\n"
                  f"**Has MV**: {'✅' if 'mv' in song.get('categories', []) else '❌'}",
            inline=True
        )
        
        if diff_lines:
            embed.add_field(name="Difficulties", value='\n'.join(diff_lines), inline=False)
        
        # Asset URLs always use JP storage
        jacket_name = song.get('assetbundleName', '')
        if jacket_name:
            embed.set_thumbnail(url=f"https://storage.sekai.best/sekai-jp-assets/music/jacket/{jacket_name}/{jacket_name}.png")
        
        return embed

    def search_songs(self, query: str, limit: int = 25) -> list:
        """Search songs by name, ID, or romaji in both JP and EN."""
        query_lower = query.lower()
        query_normalized = normalize_for_search(query)
        
        # If query is a number, try ID-based search
        if query.isdigit():
            target_id = int(query)
            song = self.get_song_by_id(target_id)
            if song:
                return [song]
            # Find nearest ID
            all_songs = self.songs_jp if self.songs_jp else self.songs_en
            sorted_songs = sorted(all_songs, key=lambda s: (abs(s['id'] - target_id), -s['id']))
            if sorted_songs:
                return [sorted_songs[0]]
            return []
        
        results = []
        seen_ids = set()
        
        # Search EN songs first
        for song in self.songs_en:
            title = song.get('title', '')
            pronunciation = song.get('pronunciation', '')
            composer = song.get('composer', '')
            
            if matches_query(query, title, pronunciation, composer):
                if song['id'] not in seen_ids:
                    results.append(song)
                    seen_ids.add(song['id'])
                    if len(results) >= limit:
                        return results
        
        # Then search JP songs
        for song in self.songs_jp:
            if song['id'] in seen_ids:
                continue
            title = song.get('title', '')
            pronunciation = song.get('pronunciation', '')
            composer = song.get('composer', '')
            
            if matches_query(query, title, pronunciation, composer):
                results.append(song)
                seen_ids.add(song['id'])
                if len(results) >= limit:
                    break
        
        return results

    # ===== SLASH COMMANDS =====
    song_group = app_commands.Group(name="song", description="Tra cứu thông tin bài hát Project Sekai")

    @song_group.command(name="search", description="Tìm kiếm bài hát theo tên (JP/EN)")
    @app_commands.describe(query="Tên bài hát cần tìm")
    async def song_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        results = self.search_songs(query, limit=10)
        
        if not results:
            await interaction.followup.send(f"Không tìm thấy bài hát nào với từ khóa: **{query}**", ephemeral=True)
            return
        
        if len(results) == 1:
            await interaction.followup.send(embed=self.create_song_embed(results[0]))
        else:
            embed = discord.Embed(
                title=f"🔍 Kết quả tìm kiếm: {query}",
                description=f"Tìm thấy {len(results)} bài hát. Sử dụng `/song info` để xem chi tiết.",
                color=discord.Color.blue()
            )
            song_list = []
            for song in results:
                diff_info = self.difficulties.get(song['id'], {})
                master_level = diff_info.get('master', {}).get('playLevel', '?')
                title = self.get_display_title(song, song['id'])
                song_list.append(f"• **{title}** (Master Lv.{master_level})")
            embed.add_field(name="Bài hát", value='\n'.join(song_list), inline=False)
            await interaction.followup.send(embed=embed)

    @song_group.command(name="random", description="Gợi ý bài hát ngẫu nhiên")
    @app_commands.describe(min_level="Level Master tối thiểu", max_level="Level Master tối đa")
    async def song_random(self, interaction: discord.Interaction, min_level: int = None, max_level: int = None):
        await interaction.response.defer()
        
        # Use JP songs as base (more complete)
        valid_songs = []
        for song in self.songs_jp:
            diff_info = self.difficulties.get(song['id'], {})
            master = diff_info.get('master', {})
            if not master:
                continue
            level = master.get('playLevel', 0)
            if min_level is not None and level < min_level:
                continue
            if max_level is not None and level > max_level:
                continue
            valid_songs.append(song)
        
        if not valid_songs:
            await interaction.followup.send(f"Không tìm thấy bài hát nào trong khoảng level {min_level or 1}-{max_level or 37}.", ephemeral=True)
            return
        
        chosen = random.choice(valid_songs)
        embed = self.create_song_embed(chosen)
        embed.title = f"🎲 Bài hát ngẫu nhiên: {self.get_display_title(chosen, chosen['id'])}"
        await interaction.followup.send(embed=embed)

    @song_group.command(name="info", description="Xem chi tiết bài hát")
    @app_commands.describe(song_name="Chọn bài hát")
    async def song_info(self, interaction: discord.Interaction, song_name: str):
        await interaction.response.defer()
        song_id = int(song_name)
        song = self.get_song_by_id(song_id)
        
        if not song:
            await interaction.followup.send("Không tìm thấy bài hát.", ephemeral=True)
            return
        
        await interaction.followup.send(embed=self.create_song_embed(song))

    @song_info.autocomplete('song_name')
    async def song_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete searching both JP and EN songs."""
        choices = []
        seen_ids = set()
        
        # Search EN songs first
        for song in self.songs_en:
            title = song.get('title', '')
            pronunciation = song.get('pronunciation', '')
            
            if matches_query(current, title, pronunciation):
                song_id = song['id']
                if song_id in seen_ids:
                    continue
                diff_info = self.difficulties.get(song_id, {})
                master_level = diff_info.get('master', {}).get('playLevel', '?')
                display = f"{title} (Master Lv.{master_level})"
                choices.append(app_commands.Choice(name=display[:100], value=str(song_id)))
                seen_ids.add(song_id)
                if len(choices) >= 25:
                    return choices
        
        # Then search JP songs
        for song in self.songs_jp:
            song_id = song['id']
            if song_id in seen_ids:
                continue
            title = song.get('title', '')
            pronunciation = song.get('pronunciation', '')
            
            if matches_query(current, title, pronunciation):
                diff_info = self.difficulties.get(song_id, {})
                master_level = diff_info.get('master', {}).get('playLevel', '?')
                # Use EN title if available
                display_title = self.songs_en_by_id.get(song_id, {}).get('title', title)
                display = f"{display_title} (Master Lv.{master_level})"
                choices.append(app_commands.Choice(name=display[:100], value=str(song_id)))
                seen_ids.add(song_id)
                if len(choices) >= 25:
                    break
        
        return choices

    # ===== PREFIX COMMANDS =====
    @commands.command(name='song', aliases=['music', 's'])
    async def song_prefix(self, ctx: commands.Context, *, query: str = None):
        """Search for a song: !song <name>"""
        if not query:
            await ctx.send("Vui lòng nhập tên bài hát: `!song <name>`")
            return
        
        results = self.search_songs(query, limit=5)
        
        if not results:
            await ctx.send(f"Không tìm thấy bài hát nào với từ khóa: **{query}**")
            return
        
        if len(results) == 1:
            await ctx.send(embed=self.create_song_embed(results[0]))
        else:
            embed = discord.Embed(
                title=f"Kết quả: {query}",
                color=discord.Color.blue()
            )
            for song in results[:5]:
                diff_info = self.difficulties.get(song['id'], {})
                master_level = diff_info.get('master', {}).get('playLevel', '?')
                title = self.get_display_title(song, song['id'])
                embed.add_field(name=title, value=f"Master Lv.{master_level}", inline=False)
            await ctx.send(embed=embed)

    @commands.command(name='songr', aliases=['randomsong'])
    async def song_random_prefix(self, ctx: commands.Context):
        """Get a random song: !songr"""
        valid_songs = [s for s in self.songs_jp if self.difficulties.get(s['id'], {}).get('master')]
        if not valid_songs:
            await ctx.send("Không có dữ liệu bài hát!")
            return
        
        chosen = random.choice(valid_songs)
        embed = self.create_song_embed(chosen)
        embed.title = f"🎲 Bài hát ngẫu nhiên: {self.get_display_title(chosen, chosen['id'])}"
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(SongsCog(bot))