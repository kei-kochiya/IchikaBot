"""
Event Tracker Cog - Track current and past Project Sekai events.
Supports both JP and EN event data with English search.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging
from datetime import datetime, timezone

from utils.data.event_data import event_data
from utils.info.events_ui import create_event_embed, EVENT_TYPES, format_timestamp, get_event_status
from utils.info.songs_ui import SearchPaginationView

logger = logging.getLogger(__name__)


class EventsCog(commands.Cog):
    """Cog for tracking Project Sekai events."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    async def cog_load(self):
        logger.info("EventsCog loaded with %d JP events and %d EN event names (shared singleton)", 
                    len(event_data.events_jp), len(event_data.events_en_names))
    
    def load_data(self):
        """Event data is managed by utils.event_data singleton."""
        pass

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
    
    # ===== SLASH COMMANDS =====
    event_group = app_commands.Group(name="event", description="Thông tin sự kiện Project Sekai")
    
    @event_group.command(name="current", description="Xem sự kiện hiện tại hoặc sắp tới")
    async def event_current(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        event = self.get_current_event()
        if event is None:
            await interaction.followup.send("Không tìm thấy sự kiện!")
            return
        
        title = self.get_display_name(event, event['id'])
        await interaction.followup.send(embed=create_event_embed(event, title))
    
    @event_group.command(name="history", description="Xem lịch sử các sự kiện")
    @app_commands.describe(count="Số lượng sự kiện muốn xem (mặc định: 5)")
    async def event_history(self, interaction: discord.Interaction, count: int = 5):
        await interaction.response.defer()
        
        count = max(1, min(count, 50))
        past_events = event_data.get_past_events(count)
        
        if not past_events:
            await interaction.followup.send("Không có sự kiện đã kết thúc!")
            return
            
        def formatter(event):
            event_type = EVENT_TYPES.get(event.get('eventType', ''), '❓')
            end_date = format_timestamp(event.get('closedAt'))[:10]
            name = self.get_display_name(event, event['id'])
            return f"• **{event_type} {name}**\n  ID: {event['id']} | Kết thúc: {end_date}"
            
        view = SearchPaginationView(past_events, "📜 Lịch sử sự kiện", formatter, items_per_page=10)
        embed = view._create_embed()
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg
    
    @event_group.command(name="search", description="Tìm kiếm sự kiện theo tên (JP/EN)")
    @app_commands.describe(name="Tên sự kiện cần tìm")
    async def event_search(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        
        results = self.search_events(name, limit=50)
        
        if not results:
            await interaction.followup.send(f"Không tìm thấy sự kiện: **{name}**")
            return
        
        if len(results) == 1:
            title = self.get_display_name(results[0], results[0]['id'])
            await interaction.followup.send(embed=create_event_embed(results[0], title))
            return
        
        def formatter(event):
            status, _ = get_event_status(event)
            event_type = EVENT_TYPES.get(event.get('eventType', ''), '❓')
            display_name = self.get_display_name(event, event['id'])
            return f"• **{event_type} {display_name}**\n  {status} | ID: {event['id']}"
            
        view = SearchPaginationView(results, f"🔍 Kết quả tìm kiếm: {name}", formatter, items_per_page=10)
        embed = view._create_embed()
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg
    
    # ===== PREFIX COMMANDS =====
    @commands.command(name='event', aliases=['ev'])
    async def event_prefix(self, ctx: commands.Context):
        """Get current event: !event"""
        event = self.get_current_event()
        if event is None:
            await ctx.send("Không tìm thấy sự kiện!")
            return
        title = self.get_display_name(event, event['id'])
        await ctx.send(embed=create_event_embed(event, title))
    
    @commands.command(name='events', aliases=['evhistory'])
    async def events_history_prefix(self, ctx: commands.Context, count: int = 5):
        """Get event history: !events [count]"""
        count = max(1, min(count, 50))
        past_events = event_data.get_past_events(count)
        
        if not past_events:
            await ctx.send("Không có sự kiện đã kết thúc!")
            return
        
        def formatter(event):
            event_type = EVENT_TYPES.get(event.get('eventType', ''), '❓')
            name = self.get_display_name(event, event['id'])
            return f"• **{event_type} {name}**\n  ID: {event['id']}"
            
        view = SearchPaginationView(past_events, "📜 Lịch sử sự kiện", formatter, items_per_page=10)
        embed = view._create_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
    
    @commands.command(name='eventsearch', aliases=['evsearch'])
    async def event_search_prefix(self, ctx: commands.Context, *, name: str = None):
        """Search events: !eventsearch <name>"""
        if not name:
            await ctx.send("Vui lòng nhập tên sự kiện: `!eventsearch <name>`")
            return
        
        results = self.search_events(name, limit=50)
        
        if not results:
            await ctx.send(f"Không tìm thấy sự kiện: **{name}**")
            return
        
        if len(results) == 1:
            title = self.get_display_name(results[0], results[0]['id'])
            await ctx.send(embed=create_event_embed(results[0], title))
            return
        
        def formatter(event):
            status, _ = get_event_status(event)
            display_name = self.get_display_name(event, event['id'])
            return f"• **{display_name}**\n  {status} | ID: {event['id']}"
            
        view = SearchPaginationView(results, f"🔍 Kết quả: {name}", formatter, items_per_page=10)
        embed = view._create_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
