import contextlib
import random
from collections import deque

import discord

from utils.voice.models import QueueEntry
from utils.voice.player import GuildPlayer

QUEUE_PAGE_SIZE = 10


def np_embed(entry: QueueEntry, player: GuildPlayer) -> discord.Embed:
    embed = discord.Embed(
        title="🎵 Đang phát",
        description=f"**[{entry.title}]({entry.webpage_url})**",
        color=discord.Color.from_rgb(255, 90, 90),
    )
    if entry.thumbnail:
        embed.set_thumbnail(url=entry.thumbnail)
    embed.add_field(name="Thời lượng", value=entry.fmt_duration(), inline=True)
    embed.add_field(
        name="Yêu cầu bởi", value=entry.requester.mention if entry.requester else "?", inline=True
    )
    embed.add_field(name="Loop", value=GuildPlayer.LOOP_LABEL[player.loop], inline=True)
    embed.add_field(name="Tiếp theo", value=f"{len(player.queue)} bài", inline=True)
    embed.add_field(name="Âm lượng", value=f"{int(player.volume * 100)}%", inline=True)
    return embed


def queue_embed(player: GuildPlayer, page: int = 0) -> discord.Embed:
    items = list(player.queue)
    total = len(items)
    total_pages = max(1, (total + QUEUE_PAGE_SIZE - 1) // QUEUE_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    slc = items[page * QUEUE_PAGE_SIZE : (page + 1) * QUEUE_PAGE_SIZE]

    embed = discord.Embed(
        title=f"Queue — {total} bài",
        color=discord.Color.blurple(),
    )
    if player.current:
        embed.add_field(
            name="🎵 Đang phát",
            value=f"[{player.current.title}]({player.current.webpage_url})",
            inline=False,
        )
    if slc:
        lines = []
        for i, item in enumerate(slc, start=page * QUEUE_PAGE_SIZE + 1):
            title = getattr(item, "title", "?")
            dur = item.fmt_duration() if isinstance(item, QueueEntry) else "..."
            lines.append(f"`{i}.` {title} `[{dur}]`")
        embed.add_field(name="Tiếp theo", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Tiếp theo", value="*(Queue rỗng)*", inline=False)

    embed.set_footer(
        text=(
            f"Trang {page + 1}/{total_pages} | "
            f"Loop: {GuildPlayer.LOOP_LABEL[player.loop]} | "
            f"Vol: {int(player.volume * 100)}%"
        )
    )
    return embed


class NowPlayingView(discord.ui.View):
    """Persistent Now-Playing control buttons attached to the NP embed."""

    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self._refresh_pause_button()

    def _player(self) -> GuildPlayer | None:
        return self.cog._players.get(self.guild_id)

    def _refresh_pause_button(self):
        player = self._player()
        is_paused = player and player.vc and player.vc.is_paused()
        self.btn_pause.label = "▶ Resume" if is_paused else "⏸ Pause"
        self.btn_pause.style = (
            discord.ButtonStyle.success if is_paused else discord.ButtonStyle.secondary
        )

    def _refresh_loop_button(self):
        player = self._player()
        loop = player.loop if player else GuildPlayer.LOOP_OFF
        labels = {
            GuildPlayer.LOOP_OFF: "🔁 Loop",
            GuildPlayer.LOOP_TRACK: "🔂 Track",
            GuildPlayer.LOOP_QUEUE: "🔁 Queue",
        }
        styles = {
            GuildPlayer.LOOP_OFF: discord.ButtonStyle.secondary,
            GuildPlayer.LOOP_TRACK: discord.ButtonStyle.primary,
            GuildPlayer.LOOP_QUEUE: discord.ButtonStyle.primary,
        }
        self.btn_loop.label = labels[loop]
        self.btn_loop.style = styles[loop]

    async def _vc_guard(self, interaction: discord.Interaction) -> bool:
        player = self._player()
        member = interaction.user
        if (
            player
            and player.vc
            and player.vc.channel
            and hasattr(member, "voice")
            and member.voice
            and member.voice.channel
            and member.voice.channel.id == player.vc.channel.id
        ):
            return True
        await interaction.response.send_message(
            "Bạn cần vào cùng kênh voice với bot để dùng nút này!",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="⏸ Pause", style=discord.ButtonStyle.secondary, custom_id="np:pause", row=0
    )
    async def btn_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._vc_guard(interaction):
            return
        player = self._player()
        if not player:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)
            return
        if player.vc and player.vc.is_playing():
            player.vc.pause()
        elif player.vc and player.vc.is_paused():
            player.vc.resume()
        self._refresh_pause_button()
        if player.current and player.np_message:
            embed = np_embed(player.current, player)
            with contextlib.suppress(discord.HTTPException):
                await player.np_message.edit(embed=embed, view=self)
        await interaction.response.defer()

    @discord.ui.button(
        label="⏭ Skip", style=discord.ButtonStyle.primary, custom_id="np:skip", row=0
    )
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._vc_guard(interaction):
            return
        player = self._player()
        if player and self.cog._do_skip(player):
            await interaction.response.send_message("⏭️ Đã bỏ qua!", ephemeral=True)
        else:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)

    @discord.ui.button(
        label="🔁 Loop", style=discord.ButtonStyle.secondary, custom_id="np:loop", row=0
    )
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._vc_guard(interaction):
            return
        player = self._player()
        if not player:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)
            return
        player.loop = (player.loop + 1) % 3
        self._refresh_loop_button()
        if player.current and player.np_message:
            embed = np_embed(player.current, player)
            with contextlib.suppress(discord.HTTPException):
                await player.np_message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"🔁 Loop: **{GuildPlayer.LOOP_LABEL[player.loop]}**", ephemeral=True
        )

    @discord.ui.button(
        label="🔀 Shuffle", style=discord.ButtonStyle.secondary, custom_id="np:shuffle", row=0
    )
    async def btn_shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._vc_guard(interaction):
            return
        player = self._player()
        if not player:
            await interaction.response.send_message("Không có gì đang phát.", ephemeral=True)
            return
        q = list(player.queue)
        random.shuffle(q)
        player.queue = deque(q)
        await interaction.response.send_message(f"🔀 Đã xáo trộn **{len(q)}** bài!", ephemeral=True)

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger, custom_id="np:stop", row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._vc_guard(interaction):
            return
        await self.cog._destroy_player(self.guild_id)
        await interaction.response.send_message("⏹️ Đã dừng và rời kênh.", ephemeral=True)

    def disable_all(self):
        for item in self.children:
            item.disabled = True
