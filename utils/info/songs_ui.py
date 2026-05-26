import discord
from datetime import datetime, timezone
import math

DIFFICULTY_EMOJI = {
    'easy': '🟢',
    'normal': '🔵', 
    'hard': '🟡',
    'expert': '🔴',
    'master': '🟣',
    'append': '⚪'
}

def create_song_embed(song: dict, display_title: str, difficulties: dict) -> discord.Embed:
    song_id = song['id']
    diff_info = difficulties.get(song_id, {})
    
    diff_lines = []
    for diff_name in ['easy', 'normal', 'hard', 'expert', 'master', 'append']:
        if diff_name in diff_info:
            level = diff_info[diff_name]['playLevel']
            notes = diff_info[diff_name]['noteCount']
            emoji = DIFFICULTY_EMOJI.get(diff_name, '⚪')
            diff_lines.append(f"{emoji} **{diff_name.title()}**: Lv.{level} ({notes} notes)")
    
    release_ts = song.get('publishedAt', 0) / 1000
    release_date = datetime.fromtimestamp(release_ts, tz=timezone.utc).strftime('%Y-%m-%d') if release_ts > 0 else 'Unknown'
    
    embed = discord.Embed(
        title=f"{display_title}",
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


class SearchPaginationView(discord.ui.View):
    """A generic pagination view for search results."""
    def __init__(self, results: list, title: str, formatter_func, items_per_page: int = 5):
        super().__init__(timeout=180)
        self.results = results
        self.title = title
        self.formatter_func = formatter_func
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = math.ceil(len(results) / items_per_page)
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        
        # Prev button
        prev_btn = discord.ui.Button(
            label="Trang trước",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page == 0,
            custom_id="page_prev"
        )
        prev_btn.callback = self.prev_callback
        self.add_item(prev_btn)
        
        # Page indicator
        page_label = discord.ui.Button(
            label=f"{self.current_page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.primary,
            disabled=True,
            custom_id="page_indicator"
        )
        self.add_item(page_label)
        
        # Next button
        next_btn = discord.ui.Button(
            label="Trang sau",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page >= self.total_pages - 1,
            custom_id="page_next"
        )
        next_btn.callback = self.next_callback
        self.add_item(next_btn)

    async def prev_callback(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        embed = self._create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def next_callback(self, interaction: discord.Interaction):
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        self.update_buttons()
        embed = self._create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def _create_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            description=f"Tìm thấy {len(self.results)} kết quả. Dùng `/song info` hoặc `!song` để xem chi tiết.",
            color=discord.Color.blue()
        )
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = self.results[start_idx:end_idx]
        
        lines = []
        for item in page_items:
            lines.append(self.formatter_func(item))
            
        embed.add_field(name="Danh sách", value='\n'.join(lines) if lines else "Không có dữ liệu", inline=False)
        return embed

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
