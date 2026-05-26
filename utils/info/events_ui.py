import discord
from datetime import datetime, timezone

EVENT_BANNER_URL = "https://storage.sekai.best/sekai-jp-assets/home/banner/{asset}/{asset}.webp"

EVENT_TYPES = {
    'marathon': 'Marathon',
    'cheerful_carnival': 'Cheerful Carnival',
    'world_bloom': 'World Link',
}

def format_timestamp(ms: int, style: str = 'F') -> str:
    """Format timestamp using Discord's dynamic timestamp."""
    if not ms:
        return 'N/A'
    unix_ts = int(ms / 1000)
    return f"<t:{unix_ts}:{style}>"

def get_event_status(event: dict) -> tuple[str, str]:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = event.get('startAt', 0)
    end = event.get('closedAt', 0)
    aggregate = event.get('aggregateAt', 0)
    
    if now_ms < start:
        return "⏳ Sắp diễn ra", format_timestamp(start, 'R')
    elif now_ms < aggregate:
        return "🟢 Đang diễn ra", f"Kết thúc {format_timestamp(aggregate, 'R')}"
    elif now_ms < end:
        return "🟡 Đang xếp hạng", "Đang tổng hợp kết quả"
    else:
        return "⚫ Đã kết thúc", format_timestamp(end, 'R')

def create_event_embed(event: dict, display_name: str, show_details: bool = True) -> discord.Embed:
    event_id = event.get('id', 0)
    event_type = EVENT_TYPES.get(event.get('eventType', ''), event.get('eventType', 'Unknown'))
    status, status_info = get_event_status(event)
    
    embed = discord.Embed(
        title=f"🎉 {display_name}",
        color=0xFF69B4 if "Đang diễn ra" in status else 0x5865F2
    )
    
    embed.add_field(name="Loại sự kiện", value=event_type, inline=True)
    embed.add_field(name="Trạng thái", value=status, inline=True)
    embed.add_field(name="Thời gian", value=status_info, inline=True)
    
    if show_details:
        embed.add_field(name="Bắt đầu", value=format_timestamp(event.get('startAt')), inline=True)
        embed.add_field(name="Kết thúc", value=format_timestamp(event.get('closedAt')), inline=True)
        embed.add_field(name="ID", value=str(event_id), inline=True)
    
    # Asset URLs always use JP storage
    asset = event.get('assetbundleName', '')
    if asset:
        embed.set_image(url=EVENT_BANNER_URL.format(asset=asset))
    
    return embed
