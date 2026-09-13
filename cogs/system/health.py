"""
Health & Diagnostics Cog for IchikaBot.
Provides runtime status, latency, uptime, memory, database, and background task metrics.
"""
import time
import math
import sys
import logging
import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite

from config import DB_FILE

logger = logging.getLogger(__name__)

# Track process start time
BOT_START_TIME = time.time()


def format_uptime(seconds: float) -> str:
    """Format seconds into days, hours, minutes, and seconds."""
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if mins > 0:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def get_memory_usage_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


class HealthCog(commands.Cog):
    """Cog for reporting bot health, system performance, and diagnostic metrics."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _check_database_latency(self) -> float:
        """Measure SQLite ping response time in milliseconds."""
        t0 = time.perf_counter()
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                async with conn.execute("SELECT 1") as cur:
                    await cur.fetchone()
            return (time.perf_counter() - t0) * 1000
        except Exception as e:
            logger.error("Health check: DB ping failed: %s", e)
            return -1.0

    def _get_background_tasks_status(self) -> dict[str, str]:
        """Inspect status of registered background loops."""
        tasks_status = {}

        # Birthday check task
        bday_cog = self.bot.get_cog("BirthdayCog")
        if bday_cog and hasattr(bday_cog, "birthday_check_task"):
            tasks_status["Birthdays"] = "🟢 Running" if bday_cog.birthday_check_task.is_running() else "🔴 Stopped"
        else:
            tasks_status["Birthdays"] = "⚪ N/A"

        # Card of Day task
        cotd_cog = self.bot.get_cog("CardOfDayCog")
        if cotd_cog and hasattr(cotd_cog, "card_loop"):
            tasks_status["Card of Day"] = "🟢 Running" if cotd_cog.card_loop.is_running() else "🔴 Stopped"
        else:
            tasks_status["Card of Day"] = "⚪ N/A"

        # Data updater task
        updater_cog = self.bot.get_cog("DataUpdaterCog")
        if updater_cog and hasattr(updater_cog, "scheduled_update"):
            tasks_status["Auto-Updater"] = "🟢 Running" if updater_cog.scheduled_update.is_running() else "🔴 Stopped"
        else:
            tasks_status["Auto-Updater"] = "⚪ N/A"

        return tasks_status

    def create_health_embed(self, db_latency_ms: float) -> discord.Embed:
        """Generate a structured diagnostic embed."""
        uptime_str = format_uptime(time.time() - BOT_START_TIME)
        latency = self.bot.latency
        ws_latency = round(latency * 1000) if (latency is not None and not math.isnan(latency) and not math.isinf(latency)) else 0
        mem_mb = get_memory_usage_mb()
        tasks = self._get_background_tasks_status()

        is_healthy = db_latency_ms >= 0 and all("🔴" not in s for s in tasks.values())
        embed_color = discord.Color.green() if is_healthy else discord.Color.orange()

        embed = discord.Embed(
            title="🩺 IchikaBot System Health & Diagnostics",
            color=embed_color,
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(name="📶 WebSocket Latency", value=f"{ws_latency} ms", inline=True)
        embed.add_field(name="💾 Database Ping", value=f"{db_latency_ms:.1f} ms" if db_latency_ms >= 0 else "❌ Error", inline=True)
        embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)

        mem_display = f"{mem_mb:.1f} MB" if mem_mb > 0 else "N/A"
        embed.add_field(name="🧠 Process RAM", value=mem_display, inline=True)
        embed.add_field(name="🧩 Loaded Cogs", value=f"{len(self.bot.cogs)} cogs", inline=True)
        embed.add_field(name="🐍 Runtime", value=f"Python {sys.version.split()[0]} | d.py {discord.__version__}", inline=True)

        task_lines = [f"• **{name}**: {status}" for name, status in tasks.items()]
        embed.add_field(name="🔄 Background Tasks", value="\n".join(task_lines) if task_lines else "None", inline=False)

        embed.set_footer(text="IchikaBot Health Monitor")
        return embed

    @app_commands.command(name="health", description="Kiểm tra trạng thái hoạt động của bot")
    async def health_slash(self, interaction: discord.Interaction):
        """Slash command for checking system health."""
        await interaction.response.defer()
        db_latency = await self._check_database_latency()
        embed = self.create_health_embed(db_latency)
        await interaction.followup.send(embed=embed)

    @commands.command(name="health", aliases=["ping", "stats"])
    async def health_prefix(self, ctx: commands.Context):
        """Prefix command for checking system health: !health / !ping"""
        db_latency = await self._check_database_latency()
        embed = self.create_health_embed(db_latency)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(HealthCog(bot))
