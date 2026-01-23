"""
Event Tracker Cog - Track current and past Project Sekai events.
"""
import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import aiofiles
from datetime import datetime, timezone

from config import EVENTS_FILE
from utils.romaji import matches_query

logger = logging.getLogger(__name__)

EVENT_BANNER_URL = "https://storage.sekai.best/sekai-jp-assets/home/banner/{asset}/{asset}.webp"

EVENT_TYPES = {
    'marathon': 'Marathon',
    'cheerful_carnival': 'Cheerful Carnival',
    'world_bloom': 'World Link',
}


class EventsCog(commands.Cog):
    """Cog for tracking Project Sekai events."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.events = []
        
    async def cog_load(self):
        await self.load_data()
        logger.info("EventsCog loaded with %d events", len(self.events))
    
    async def load_data(self):
        try:
            async with aiofiles.open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                self.events = json.loads(await f.read())
                self.events.sort(key=lambda e: e.get('startAt', 0), reverse=True)
        except Exception as e:
            logger.error("Failed to load event data: %s", e)
    
    def format_timestamp(self, ms: int, style: str = 'F') -> str:
        """Format timestamp using Discord's dynamic timestamp.
        
        Styles:
        - t: Short Time (16:20)
        - T: Long Time (16:20:30)
        - d: Short Date (20/04/2021)
        - D: Long Date (20 April 2021)
        - f: Short Date/Time (20 April 2021 16:20)
        - F: Long Date/Time (Tuesday, 20 April 2021 16:20)
        - R: Relative Time (2 months ago)
        """
        if not ms:
            return 'N/A'
        unix_ts = int(ms / 1000)
        return f"<t:{unix_ts}:{style}>"
    
    def get_event_status(self, event: dict) -> tuple[str, str]:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start = event.get('startAt', 0)
        end = event.get('closedAt', 0)
        aggregate = event.get('aggregateAt', 0)
        
        if now_ms < start:
            return "⏳ Sắp diễn ra", self.format_timestamp(start, 'R')
        elif now_ms < aggregate:
            return "Đang diễn ra", f"Kết thúc {self.format_timestamp(aggregate, 'R')}"
        elif now_ms < end:
            return "Đang xếp hạng", "Đang tổng hợp kết quả"
        else:
            return "Đã kết thúc", self.format_timestamp(end, 'R')
    
    def create_event_embed(self, event: dict, show_details: bool = True) -> discord.Embed:
        name = event.get('name', 'Unknown Event')
        event_type = EVENT_TYPES.get(event.get('eventType', ''), event.get('eventType', 'Unknown'))
        status, status_info = self.get_event_status(event)
        
        embed = discord.Embed(
            title=f"🎉 {name}",
            color=0xFF69B4 if status.startswith("🟢") else 0x5865F2
        )
        
        embed.add_field(name="Loại sự kiện", value=event_type, inline=True)
        embed.add_field(name="Trạng thái", value=status, inline=True)
        embed.add_field(name="Thời gian", value=status_info, inline=True)
        
        if show_details:
            embed.add_field(name="Bắt đầu", value=self.format_timestamp(event.get('startAt')), inline=True)
            embed.add_field(name="Kết thúc", value=self.format_timestamp(event.get('closedAt')), inline=True)
            embed.add_field(name="ID", value=str(event.get('id', 'N/A')), inline=True)
        
        asset = event.get('assetbundleName', '')
        if asset:
            embed.set_image(url=EVENT_BANNER_URL.format(asset=asset))
        
        return embed
    
    def get_current_event(self) -> dict | None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for event in self.events:
            start = event.get('startAt', 0)
            end = event.get('closedAt', 0)
            if start <= now_ms <= end:
                return event
            elif now_ms < start:
                return event  # Return upcoming if no current
        return self.events[0] if self.events else None
    
    def search_events(self, query: str, limit: int = 5) -> list:
        """Search events by name, ID, or romaji."""
        # If query is a number, try ID-based search
        if query.isdigit():
            target_id = int(query)
            # First check for exact name match
            name_matches = [e for e in self.events if query in e.get('name', '')]
            if name_matches:
                return name_matches[:limit]
            
            # Find nearest ID (higher if tied)
            sorted_events = sorted(self.events, key=lambda e: (abs(e['id'] - target_id), -e['id']))
            if sorted_events:
                return [sorted_events[0]]
            return []
        
        # Search by name with romaji support
        results = []
        for event in self.events:
            name = event.get('name', '')
            if matches_query(query, name):
                results.append(event)
                if len(results) >= limit:
                    break
        return results
    
    # ===== SLASH COMMANDS =====
    event_group = app_commands.Group(name="event", description="Thông tin sự kiện Project Sekai")
    
    @event_group.command(name="current", description="Xem sự kiện hiện tại hoặc sắp tới")
    async def event_current(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        event = self.get_current_event()
        if event is None:
            await interaction.followup.send("Không tìm thấy sự kiện!")
            return
        
        await interaction.followup.send(embed=self.create_event_embed(event))
    
    @event_group.command(name="history", description="Xem lịch sử các sự kiện")
    @app_commands.describe(count="Số lượng sự kiện muốn xem (mặc định: 5)")
    async def event_history(self, interaction: discord.Interaction, count: int = 5):
        await interaction.response.defer()
        
        count = max(1, min(count, 25))
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        past_events = [e for e in self.events if e.get('closedAt', 0) < now_ms][:count]
        
        if not past_events:
            await interaction.followup.send("Không có sự kiện đã kết thúc!")
            return
        
        embed = discord.Embed(
            title="Lịch sử sự kiện",
            description=f"Hiển thị {len(past_events)} sự kiện gần nhất",
            color=0x5865F2
        )
        
        for event in past_events:
            event_type = EVENT_TYPES.get(event.get('eventType', ''), '❓')
            end_date = self.format_timestamp(event.get('closedAt'))[:10]
            embed.add_field(
                name=f"{event_type} {event.get('name', 'Unknown')}",
                value=f"ID: {event['id']} | Kết thúc: {end_date}",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
    
    @event_group.command(name="search", description="Tìm kiếm sự kiện theo tên")
    @app_commands.describe(name="Tên sự kiện cần tìm")
    async def event_search(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        
        results = self.search_events(name)
        
        if not results:
            await interaction.followup.send(f"Không tìm thấy sự kiện: **{name}**")
            return
        
        if len(results) == 1:
            await interaction.followup.send(embed=self.create_event_embed(results[0]))
            return
        
        embed = discord.Embed(
            title=f"🔍 Kết quả tìm kiếm: {name}",
            description=f"Tìm thấy {len(results)} sự kiện",
            color=0x5865F2
        )
        
        for event in results:
            status, _ = self.get_event_status(event)
            event_type = EVENT_TYPES.get(event.get('eventType', ''), '❓')
            embed.add_field(
                name=f"{event_type} {event.get('name', 'Unknown')}",
                value=f"{status} | ID: {event['id']}",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
    
    # ===== PREFIX COMMANDS =====
    @commands.command(name='event', aliases=['ev'])
    async def event_prefix(self, ctx: commands.Context):
        """Get current event: !event"""
        event = self.get_current_event()
        if event is None:
            await ctx.send("Không tìm thấy sự kiện!")
            return
        await ctx.send(embed=self.create_event_embed(event))
    
    @commands.command(name='events', aliases=['evhistory'])
    async def events_history_prefix(self, ctx: commands.Context, count: int = 5):
        """Get event history: !events [count]"""
        count = max(1, min(count, 10))
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        past_events = [e for e in self.events if e.get('closedAt', 0) < now_ms][:count]
        
        if not past_events:
            await ctx.send("Không có sự kiện đã kết thúc!")
            return
        
        embed = discord.Embed(
            title="Lịch sử sự kiện",
            description=f"Hiển thị {len(past_events)} sự kiện gần nhất",
            color=0x5865F2
        )
        
        for event in past_events:
            event_type = EVENT_TYPES.get(event.get('eventType', ''), '❓')
            embed.add_field(
                name=f"{event_type} {event.get('name', 'Unknown')}",
                value=f"ID: {event['id']}",
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='eventsearch', aliases=['evsearch'])
    async def event_search_prefix(self, ctx: commands.Context, *, name: str = None):
        """Search events: !eventsearch <name>"""
        if not name:
            await ctx.send("Vui lòng nhập tên sự kiện: `!eventsearch <name>`")
            return
        
        results = self.search_events(name, limit=3)
        
        if not results:
            await ctx.send(f"Không tìm thấy sự kiện: **{name}**")
            return
        
        if len(results) == 1:
            await ctx.send(embed=self.create_event_embed(results[0]))
            return
        
        embed = discord.Embed(
            title=f"🔍 Kết quả: {name}",
            color=0x5865F2
        )
        
        for event in results:
            status, _ = self.get_event_status(event)
            embed.add_field(
                name=event.get('name', 'Unknown'),
                value=f"{status} | ID: {event['id']}",
                inline=False
            )
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
