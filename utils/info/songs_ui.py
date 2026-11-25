import asyncio
import contextlib
import math
from datetime import datetime, timedelta, timezone

import discord

# Release times are set in Japan time: in UTC, songs released at JST midnight showed the
# previous day.
JST = timezone(timedelta(hours=9))
DIFFICULTIES = ("easy", "normal", "hard", "expert", "master", "append")


def create_song_embed(song: dict, display_title: str, difficulties: dict) -> discord.Embed:
    song_id = song["id"]
    diff_info = difficulties.get(song_id, {})

    diff_lines = []
    for diff_name in DIFFICULTIES:
        if diff_name in diff_info:
            level = diff_info[diff_name]["playLevel"]
            notes = diff_info[diff_name]["noteCount"]
            diff_lines.append(f"**{diff_name.title()}**: Lv.{level} ({notes} notes)")

    release_ts = (song.get("publishedAt") or 0) / 1000
    release_date = (
        datetime.fromtimestamp(release_ts, tz=JST).strftime("%Y-%m-%d")
        if release_ts > 0
        else "Unknown"
    )

    embed = discord.Embed(title=f"{display_title}", color=discord.Color.from_str("#00BFFF"))

    embed.add_field(
        name="Credits",
        value=f"**Composer**: {song.get('composer', '-')}\n"
        f"**Lyricist**: {song.get('lyricist', '-')}\n"
        f"**Arranger**: {song.get('arranger', '-')}",
        inline=True,
    )

    embed.add_field(
        name="Info",
        value=f"**ID**: {song_id}\n"
        f"**Released**: {release_date}\n"
        f"**Has MV**: {'Yes' if 'mv' in song.get('categories', []) else 'No'}",
        inline=True,
    )

    if diff_lines:
        embed.add_field(name="Difficulties", value="\n".join(diff_lines), inline=False)

    # Asset URLs always use JP storage
    jacket_name = song.get("assetbundleName", "")
    if jacket_name:
        embed.set_thumbnail(
            url=f"https://storage.sekai.best/sekai-jp-assets/music/jacket/{jacket_name}/{jacket_name}.png"
        )

    return embed


class SearchPaginationView(discord.ui.View):
    """A generic pagination view for search results."""

    def __init__(
        self,
        results: list,
        title: str,
        formatter_func,
        items_per_page: int = 5,
        hint: str = "",
    ):
        self.results = results
        self.title = title[:256]
        self.formatter_func = formatter_func
        self.items_per_page = items_per_page
        self.hint = hint
        self.current_page = 0
        self.total_pages = max(1, math.ceil(len(results) / items_per_page))
        super().__init__(timeout=180 if self.total_pages > 1 else None)
        self._lock = asyncio.Lock()

        self._prev_btn = discord.ui.Button(
            label="Trang trước",
            style=discord.ButtonStyle.secondary,
            custom_id="page_prev",
        )
        self._prev_btn.callback = self.prev_callback
        self._page_label = discord.ui.Button(
            label=f"1/{self.total_pages}",
            style=discord.ButtonStyle.primary,
            disabled=True,
            custom_id="page_indicator",
        )
        self._next_btn = discord.ui.Button(
            label="Trang sau",
            style=discord.ButtonStyle.secondary,
            custom_id="page_next",
        )
        self._next_btn.callback = self.next_callback
        self.add_item(self._prev_btn)
        self.add_item(self._page_label)
        self.add_item(self._next_btn)

        self.update_buttons()
        if self.total_pages <= 1:
            self.stop()

    def update_buttons(self):
        self._prev_btn.disabled = self.current_page == 0
        self._page_label.label = f"{self.current_page + 1}/{self.total_pages}"
        self._next_btn.disabled = self.current_page >= self.total_pages - 1

    async def _step(self, interaction: discord.Interaction, delta: int) -> None:
        async with self._lock:
            prev_page = self.current_page
            self.current_page = max(0, min(self.total_pages - 1, self.current_page + delta))
            self.update_buttons()
            embed = self._create_embed()
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.HTTPException:
                self.current_page = prev_page
                self.update_buttons()

    async def prev_callback(self, interaction: discord.Interaction):
        await self._step(interaction, -1)

    async def next_callback(self, interaction: discord.Interaction):
        await self._step(interaction, +1)

    def _create_embed(self) -> discord.Embed:
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = self.results[start_idx:end_idx]

        header = f"Tìm thấy {len(self.results)} kết quả."
        if self.hint:
            header = f"{header} {self.hint}"

        lines = [self.formatter_func(item) for item in page_items]
        body = "\n".join(lines) if lines else "Không có dữ liệu"
        description = f"{header}\n\n{body}"
        if len(description) > 4096:
            description = description[:4093] + "..."

        embed = discord.Embed(
            title=self.title,
            description=description,
            color=discord.Color.blue(),
        )
        if self.total_pages > 1:
            embed.set_footer(text=f"Trang {self.current_page + 1}/{self.total_pages}")
        return embed

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, "message") and self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)
