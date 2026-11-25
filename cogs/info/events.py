"""
Event Tracker Cog - Track current and past Project Sekai events.
Supports both JP and EN event data with English search.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.data.event_data import event_data
from utils.info.events_ui import EVENT_TYPES, create_event_embed, format_timestamp, get_event_status
from utils.info.songs_ui import SearchPaginationView

logger = logging.getLogger(__name__)


class EventsCog(commands.Cog):
    """Cog for tracking Project Sekai events."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        logger.info(
            "EventsCog loaded with %d JP events and %d EN event names (shared singleton)",
            len(event_data.events_jp),
            len(event_data.events_en_names),
        )

    def load_data(self):
        """Event data is managed by utils.event_data singleton."""

    def get_event_by_id(self, event_id: int) -> dict | None:
        """Get event by ID from JP data (for correct timing)."""
        return event_data.get_event_by_id(event_id)

    def get_display_name(self, event: dict, event_id: int) -> str:
        """Get display name, using EN if available."""
        return event_data.get_display_name(event, event_id)

    def get_current_event(self) -> dict | None:
        """Get current event from JP data (more up to date)."""
        return event_data.get_current_event()

    def search_events(self, query: str, limit: int = 50) -> list[dict]:
        """Search events by name, ID, or romaji. Returns JP events for correct timing."""
        return event_data.search_events(query, limit)

    def _build_history_reply(
        self, count: int
    ) -> tuple[discord.Embed | None, discord.ui.View | None]:
        count = max(1, min(count, 50))
        past_events = event_data.get_past_events(count)
        if not past_events:
            return None, None

        def formatter(event: dict) -> str:
            event_type = EVENT_TYPES.get(event.get("eventType", ""), "Khác")
            end_date = format_timestamp(event.get("closedAt"), "d")
            name = self.get_display_name(event, event["id"])
            return f"• **{event_type} {name}**\n  ID: {event['id']} | Kết thúc: {end_date}"

        view = SearchPaginationView(
            past_events,
            "Lịch sử sự kiện",
            formatter,
            items_per_page=10,
            hint="Dùng `/event search` hoặc `!eventsearch` để xem chi tiết.",
        )
        return view._create_embed(), view

    def _build_search_reply(self, name: str) -> tuple[discord.Embed | None, discord.ui.View | None]:
        results = self.search_events(name, limit=50)
        if not results:
            return None, None
        if len(results) == 1:
            title = self.get_display_name(results[0], results[0]["id"])
            return create_event_embed(results[0], title), None

        def formatter(event: dict) -> str:
            status, _ = get_event_status(event)
            event_type = EVENT_TYPES.get(event.get("eventType", ""), "Khác")
            display_name = self.get_display_name(event, event["id"])
            return f"• **{event_type} {display_name}**\n  {status} | ID: {event['id']}"

        view = SearchPaginationView(
            results,
            f"Kết quả tìm kiếm: {name}",
            formatter,
            items_per_page=10,
            hint="Dùng `/event search <ID>` để xem chi tiết.",
        )
        return view._create_embed(), view

    # ===== SLASH COMMANDS =====
    event_group = app_commands.Group(name="event", description="Thông tin sự kiện Project Sekai")

    @event_group.command(name="current", description="Xem sự kiện hiện tại hoặc sắp tới")
    async def event_current(self, interaction: discord.Interaction):
        await interaction.response.defer()
        event = self.get_current_event()
        if event is None:
            await interaction.followup.send("Không tìm thấy sự kiện!")
            return
        await interaction.followup.send(
            embed=create_event_embed(event, self.get_display_name(event, event["id"]))
        )

    @event_group.command(name="history", description="Xem lịch sử các sự kiện")
    @app_commands.describe(count="Số lượng sự kiện muốn xem (mặc định: 5)")
    async def event_history(self, interaction: discord.Interaction, count: int = 5):
        await interaction.response.defer()
        embed, view = self._build_history_reply(count)
        if embed is None:
            await interaction.followup.send("Không có sự kiện đã kết thúc!", ephemeral=True)
            return
        if view is None:
            await interaction.followup.send(embed=embed)
            return
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    @event_group.command(name="search", description="Tìm kiếm sự kiện theo tên (JP/EN)")
    @app_commands.describe(name="Tên sự kiện cần tìm")
    async def event_search(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        embed, view = self._build_search_reply(name)
        if embed is None:
            await interaction.followup.send(
                f"Không tìm thấy sự kiện: **{name[:100]}**",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if view is None:
            await interaction.followup.send(embed=embed)
            return
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

    # ===== PREFIX COMMANDS =====
    @commands.command(name="event", aliases=["ev"])
    async def event_prefix(self, ctx: commands.Context):
        """Get current event: !event"""
        event = self.get_current_event()
        if event is None:
            await ctx.send("Không tìm thấy sự kiện!")
            return
        await ctx.send(embed=create_event_embed(event, self.get_display_name(event, event["id"])))

    @commands.command(name="events", aliases=["evhistory"])
    async def events_history_prefix(self, ctx: commands.Context, count: int = 5):
        """Get event history: !events [count]"""
        embed, view = self._build_history_reply(count)
        if embed is None:
            await ctx.send("Không có sự kiện đã kết thúc!")
            return
        if view is None:
            await ctx.send(embed=embed)
            return
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @commands.command(name="eventsearch", aliases=["evsearch"])
    async def event_search_prefix(self, ctx: commands.Context, *, name: str | None = None):
        """Search events: !eventsearch <name>"""
        if not name:
            await ctx.send("Vui lòng nhập tên sự kiện: `!eventsearch <name>`")
            return

        embed, view = self._build_search_reply(name)
        if embed is None:
            await ctx.send(
                f"Không tìm thấy sự kiện: **{name[:100]}**",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if view is None:
            await ctx.send(embed=embed)
            return
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
